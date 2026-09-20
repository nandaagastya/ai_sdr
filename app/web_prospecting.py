"""Web prospecting preview and explicit save. Never calls Apollo or AI."""
import json
import secrets
import uuid
from datetime import datetime
from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for
from app.models import db, Account, Contact, Activity, AgentRun, WebDiscovery
from app.services.public_web import PublicCrawler, normalize_url, inspect_company, inspect_directory
from app.services.prospect_cache import read_cache, write_cache

web_bp = Blueprint('web_prospecting', __name__)


def token():
    session.setdefault('web_csrf',secrets.token_urlsafe(32))
    return session['web_csrf']


def check_token():
    if not secrets.compare_digest(request.form.get('csrf_token',''),token()): abort(400)


def owned(batch_id):
    batch = db.session.get(WebDiscovery,batch_id)
    if batch is None or batch.owner != session.get('web_owner'): abort(404)
    return batch


@web_bp.post('/leads/web/scan')
def scan():
    check_token()
    kind = request.form.get('kind','companies')
    urls = request.form.getlist('selected_url') or request.form.get('urls','').splitlines()
    try:
        urls = list(dict.fromkeys(normalize_url(value) for value in urls if value.strip()))
        if kind not in ('companies','directory') or not 1 <= len(urls) <= (1 if kind=='directory' else 5):
            raise ValueError('Provide one directory URL or up to five company website URLs.')
    except ValueError as exc:
        return render_template('discover.html',error=str(exc),csrf_token=token()),400
    crawler = PublicCrawler()
    results = []
    for url in urls:
        previous = read_cache('web',{'kind':kind,'url':url})
        if previous and request.form.get('refresh') != 'yes':
            results.append({**previous,'cached':True})
            continue
        try:
            result = inspect_directory(crawler,url) if kind=='directory' else inspect_company(crawler,url)
            result['checked_at'] = datetime.utcnow().isoformat()+'Z'
            write_cache('web',{'kind':kind,'url':url},result)
            results.append({**result,'cached':False})
        except ValueError as exc:
            results.append({'url':url,'status':'error','error':str(exc)})
        except Exception:
            current_app.logger.exception('Web scan failed')
            results.append({'url':url,'status':'error','error':'Could not scan this website.'})
    session.setdefault('web_owner',secrets.token_hex(32))
    batch = WebDiscovery(id=uuid.uuid4().hex,owner=session['web_owner'],kind=kind,
                         data=json.dumps({'results':results,'web_requests':crawler.requests}))
    db.session.add(batch)
    failures = sum(result.get('status')=='error' for result in results)
    db.session.add(AgentRun(agent_name='web_prospecting',status='error' if failures==len(results) else 'success',
                           records_processed=len(results)-failures,finished_at=datetime.utcnow(),
                           detail=f'Web discovery {batch.id}; {crawler.requests} web requests; {failures} failed sites; Apollo requests 0. No email sent.'))
    db.session.commit()
    return redirect(url_for('web_prospecting.results',batch_id=batch.id),code=303)


@web_bp.route('/leads/web/<batch_id>',methods=['GET','POST'])
def results(batch_id):
    batch = owned(batch_id)
    data = json.loads(batch.data)
    error = None
    if request.method == 'POST':
        check_token()
        if batch.status == 'saved':
            return redirect(url_for('web_prospecting.results',batch_id=batch.id),code=303)
        try:
            indexes = list(dict.fromkeys(int(value) for value in request.form.getlist('selected')))
            if batch.kind != 'companies' or not indexes or any(i<0 or i>=len(data['results']) or data['results'][i].get('status')!='found' for i in indexes):
                raise ValueError('Select at least one successfully scanned company.')
            # Claim and save in a single transaction; retries cannot duplicate it.
            claimed = db.session.execute(db.update(WebDiscovery).where(WebDiscovery.id==batch.id,WebDiscovery.status=='review').values(status='saving'),execution_options={'synchronize_session':False})
            if claimed.rowcount != 1: raise ValueError('This result is already being saved. Reload the page.')
            summary = {'companies_added':0,'contacts_added':0,'existing_emails_skipped':0}
            for index in indexes:
                result = data['results'][index]
                name = request.form.get(f'company_{index}',result['company']).strip()
                if not name or len(name)>255 or any(ord(c)<32 for c in name): raise ValueError('Company names must be 1–255 characters on one line.')
                account = Account.query.filter(db.func.lower(Account.domain)==result['domain']).first()
                if account is None:
                    account = Account(name=name,domain=result['domain'],source='web',stage='new',icp_fit_score=0,icp_fit_reasons='Public website lead; fit not yet assessed')
                    db.session.add(account); db.session.flush(); summary['companies_added']+=1
                    from app.services.lead_quality import apply_quality
                    apply_quality(account)
                for published in result['emails']:
                    if Contact.query.filter(db.func.lower(Contact.email)==published['email']).first():
                        summary['existing_emails_skipped']+=1
                        continue
                    db.session.add(Contact(account_id=account.id,email=published['email'],title='Public website contact'))
                    summary['contacts_added']+=1
                db.session.add(Activity(account_id=account.id,activity_type='web_source',channel='web',
                                        summary=json.dumps({'source':'public_web',**result})))
            batch.status='saved'; batch.result=json.dumps(summary)
            db.session.commit()
            return redirect(url_for('web_prospecting.results',batch_id=batch.id),code=303)
        except ValueError as exc:
            db.session.rollback(); error=str(exc)
        except Exception:
            db.session.rollback(); current_app.logger.exception('Web leads save failed')
            error='Could not save these leads. No partial changes were saved.'
    return render_template('web_results.html',batch=batch,data=data,error=error,csrf_token=token(),
                           summary=json.loads(batch.result) if batch.result else None),400 if error else 200
