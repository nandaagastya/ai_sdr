"""User-facing sales overview, tasks, and outreach review."""
from flask import Blueprint, render_template

from app.models import db, Account, Contact, Task, AgentRun, Activity, DeliverySimulation

dashboard_bp = Blueprint("dashboard", __name__)

STAGES = ["new", "qualified", "outreach", "replied", "booked", "closed"]


@dashboard_bp.get("/")
def dashboard():
    import secrets
    from datetime import datetime
    from flask import session
    from sqlalchemy.orm import selectinload
    from app.agents.queue import list_previews
    session.setdefault('dashboard_csrf', secrets.token_urlsafe(32))
    tasks = Task.query.filter_by(status='open').order_by(Task.due_at.asc().nulls_last(), Task.id).all()
    accounts = Account.query.filter(Account.stage != 'closed').options(selectinload(Account.contacts)).order_by(
        Account.icp_fit_score.desc(), Account.created_at.desc()).limit(8).all()
    prospects = []
    for account in accounts:
        contacts = sorted(account.contacts, key=lambda c: (not c.is_decision_maker, not bool(c.email), c.id))
        prospects.append({'account': account, 'contact': contacts[0] if contacts else None})
    from app.services.workflow import next_actions, task_contexts
    task_links=task_contexts(tasks)
    tasks=[task for task in tasks if not (task_links[task.id] and task_links[task.id]['resolved'])]
    actions=next_actions()
    queue = list_previews(status='draft')
    return render_template('dashboard.html', tasks=tasks, prospects=prospects,
                           total_accounts=Account.query.count(), review_count=queue['total'],
                           reviews=queue['previews'][:3], now=datetime.utcnow(),
                           workflow_actions=actions[:5],workflow_total=len(actions),task_links=task_links,
                           booked=db.session.query(Contact).filter_by(pipeline_stage='booked').count(),
                           csrf_token=session['dashboard_csrf'])


@dashboard_bp.post('/tasks/<int:task_id>/complete')
def complete_task(task_id):
    import secrets
    from flask import request, session, abort, redirect, url_for
    token = request.form.get('csrf_token', '')
    if not token or not secrets.compare_digest(token, session.get('dashboard_csrf', '')):
        abort(400)
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    from app.models import Meeting
    meeting = Meeting.query.filter_by(task_id=task.id).first()
    if meeting is not None:
        return redirect(url_for('dashboard.call_brief', activity_id=meeting.reply_id), code=303)
    if task.status == 'open':
        task.status = 'done'
        db.session.commit()
    return redirect(url_for('dashboard.dashboard'), code=303)


@dashboard_bp.route("/outreach", methods=["GET", "POST"])
def outreach():
    import secrets
    from flask import request, redirect, url_for, abort, current_app, session
    from app.agents.review import get_preview
    from app.models import Contact, Activity
    from app.agents.outreach import preview_outreach
    from app.services.eligibility import blocked_reason

    values = {"contact_id": request.args.get("contact_id", "")}
    error = None
    draft = None
    status = 200
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            values["contact_id"] = int(values.get("contact_id", ""))
            draft = preview_outreach(values)
            return redirect(url_for("dashboard.outreach", preview_id=draft["activity_id"]), code=303)
        except ValueError as exc:
            error, status = str(exc), 400
        except Exception:
            current_app.logger.exception("Outreach preview failed")
            error, status = "Preview generation failed. Check agent runs.", 500
    elif request.args.get("preview_id") is not None:
        preview_id = request.args.get("preview_id", type=int)
        draft = get_preview(preview_id) if preview_id else None
        if draft is None:
            abort(404)
    session.setdefault("review_csrf", secrets.token_urlsafe(32))
    contacts = Contact.query.join(Account).order_by(Account.icp_fit_score.desc(), Contact.is_decision_maker.desc(), Contact.id).all()
    return render_template("outreach.html", contacts=contacts, values=values,
                           error=error, draft=draft, edit_values={},
                           delivery_block=blocked_reason(draft) if draft else None,
                           simulations=DeliverySimulation.query.filter_by(preview_id=draft["activity_id"]).order_by(DeliverySimulation.id.desc()).all() if draft else [],
                           csrf_token=session["review_csrf"]), status


@dashboard_bp.post("/outreach/<int:preview_id>/review")
def review_outreach(preview_id):
    import secrets
    from flask import request, session, abort, redirect, url_for, current_app
    from app.agents.review import review_preview, get_preview, ReviewConflict
    token = request.form.get('csrf_token', '')
    if not token or not secrets.compare_digest(token, session.get('review_csrf', '')):
        abort(400, description='Review form expired. Reload the preview and try again.')
    draft = get_preview(preview_id)
    if draft is None:
        abort(404)
    edit_values = request.form.to_dict()
    try:
        payload = {'action': request.form.get('action'), 'revision': int(request.form.get('revision', ''))}
        if payload['action'] == 'save':
            payload['messages'] = [{'subject': request.form.get(f'subject_{i}', ''),
                                    'body': request.form.get(f'body_{i}', '')} for i in range(1, 4)]
        review_preview(preview_id, payload)
        return redirect(url_for('dashboard.outreach', preview_id=preview_id), code=303)
    except ReviewConflict as exc:
        error, status = str(exc), 409
    except ValueError as exc:
        error, status = str(exc), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Preview review failed')
        error, status = 'Could not save review. Reload and try again.', 500
    return render_template('outreach.html', contacts=[], values={}, draft=draft,
                           edit_values=edit_values, review_error=error,
                           review_conflict=status == 409, csrf_token=token), status


@dashboard_bp.get('/outreach/queue')
def outreach_queue():
    from flask import request, abort
    from app.agents.queue import list_previews
    try:
        page = int(request.args.get('page', '1'))
        queue = list_previews(status=request.args.get('status', 'all'),
                              query=request.args.get('q', ''), page=page)
    except ValueError as exc:
        abort(400, description=str(exc))
    return render_template('outreach_queue.html', **queue)


@dashboard_bp.get('/leads/discover')
def discover():
    from app.web_prospecting import token
    return render_template('discover.html',csrf_token=token())


@dashboard_bp.get('/tasks')
def task_list():
    import secrets
    from datetime import datetime
    from flask import session
    session.setdefault('dashboard_csrf', secrets.token_urlsafe(32))
    from app.services.workflow import task_contexts
    tasks=Task.query.filter_by(status='open').order_by(Task.due_at.asc().nulls_last(),Task.id).all()
    links=task_contexts(tasks)
    resolved=[task for task in tasks if links[task.id] and links[task.id]['resolved']]
    active=[task for task in tasks if task not in resolved]
    return render_template('tasks.html',tasks=active,resolved_tasks=resolved,task_links=links,now=datetime.utcnow(),csrf_token=session['dashboard_csrf'])


@dashboard_bp.post('/outreach/<int:preview_id>/simulate')
def simulate_outreach(preview_id):
    import secrets
    from flask import request, session, abort, redirect, url_for
    from app.agents.delivery import simulate_delivery
    token = request.form.get('csrf_token', '')
    if not token or not secrets.compare_digest(token, session.get('review_csrf', '')):
        abort(400)
    try:
        simulate_delivery(preview_id, int(request.form.get('revision', '')))
    except ValueError as exc:
        abort(409, description=str(exc))
    return redirect(url_for('dashboard.outreach', preview_id=preview_id), code=303)


@dashboard_bp.post('/outreach/<int:preview_id>/pause')
def pause_outreach(preview_id):
    import secrets
    from flask import request, session, abort, redirect, url_for
    from app.agents.review import get_preview
    from app.services.eligibility import set_stop
    token=request.form.get('csrf_token','')
    if not token or not secrets.compare_digest(token,session.get('review_csrf','')):
        abort(400)
    draft=get_preview(preview_id)
    if draft is None: abort(404)
    set_stop(draft['recipient'],'paused')
    db.session.add(Activity(account_id=draft['account_id'],contact_id=draft['contact_id'],
        activity_type='outreach_paused',channel='internal',summary='Manual outreach pause for saved recipient.'))
    db.session.commit()
    return redirect(url_for('dashboard.outreach',preview_id=preview_id),code=303)


@dashboard_bp.post('/outreach/<int:preview_id>/resume')
def resume_outreach(preview_id):
    import secrets
    from flask import request, session, abort, redirect, url_for
    from app.agents.review import get_preview
    from app.models import OutreachStop
    token=request.form.get('csrf_token','')
    if not token or not secrets.compare_digest(token,session.get('review_csrf','')):
        abort(400)
    draft=get_preview(preview_id)
    if draft is None: abort(404)
    changed=db.session.execute(db.update(OutreachStop).where(
        OutreachStop.email==draft['recipient'].strip().casefold(),
        OutreachStop.reason=='paused', OutreachStop.active==True).values(active=False))
    if changed.rowcount:
        db.session.add(Activity(account_id=draft['account_id'],contact_id=draft['contact_id'],
            activity_type='outreach_resumed',channel='internal',summary='Manual pause lifted. Other eligibility checks still apply.'))
    db.session.commit()
    return redirect(url_for('dashboard.outreach',preview_id=preview_id),code=303)


@dashboard_bp.route('/replies/review', methods=['GET','POST'])
def reply_review():
    import secrets
    from flask import request, session, abort
    from app.agents.replies import classify_reply, NEXT
    from app.agents.record_reply import record_reply
    session.setdefault('reply_csrf',secrets.token_urlsafe(32))
    body=request.form.get('reply','') if request.method=='POST' else ''
    sender=request.form.get('sender','')
    result,error,saved=None,None,None
    if request.method=='POST':
        try:
            result=classify_reply(body)
            if request.form.get('action')=='record':
                token=request.form.get('csrf_token','')
                if not token or not secrets.compare_digest(token,session['reply_csrf']): abort(400)
                saved=record_reply(sender,body,request.form.get('outcome'))
        except ValueError as exc: error=str(exc)
    return render_template('reply_review.html',body=body,sender=sender,result=result,error=error,
        saved=saved,outcomes=NEXT,csrf_token=session['reply_csrf']),400 if error else 200


@dashboard_bp.get('/replies')
def saved_replies():
    from flask import request, abort
    from app.models import RecordedReply, Contact
    from app.agents.replies import NEXT
    outcome=request.args.get('outcome','all')
    if outcome!='all' and outcome not in NEXT: abort(400)
    try: page=int(request.args.get('page','1'))
    except ValueError: abort(400)
    if page<1: abort(400)
    query=db.session.query(RecordedReply, Activity, Contact, Account).join(
        Activity,RecordedReply.activity_id==Activity.id).join(Contact,RecordedReply.contact_id==Contact.id).join(
        Account,Contact.account_id==Account.id)
    if outcome!='all': query=query.filter(RecordedReply.outcome==outcome)
    total=query.count()
    rows=query.order_by(Activity.created_at.desc(),Activity.id.desc()).offset((page-1)*20).limit(20).all()
    return render_template('saved_replies.html',rows=rows,total=total,page=page,outcome=outcome,outcomes=NEXT)


@dashboard_bp.get('/replies/<int:activity_id>')
def saved_reply(activity_id):
    import json
    from flask import abort
    from app.models import RecordedReply, Contact, OutreachStop
    record=RecordedReply.query.filter_by(activity_id=activity_id).first()
    if record is None: abort(404)
    activity=db.session.get(Activity,activity_id)
    contact=db.session.get(Contact,record.contact_id)
    if activity is None or contact is None or activity.activity_type!='reply': abort(404)
    data=json.loads(activity.summary)
    stop=db.session.get(OutreachStop,data['sender'].strip().casefold())
    tasks=Task.query.filter_by(account_id=contact.account_id).order_by(Task.created_at.desc(),Task.id.desc()).all()
    from flask import session
    import secrets
    from app.models import Qualification
    session.setdefault('qualification_csrf',secrets.token_urlsafe(32))
    assessment=db.session.get(Qualification,activity_id)
    return render_template('saved_reply.html',record=record,activity=activity,contact=contact,data=data,stop=stop,tasks=tasks,
        assessment=assessment,evidence=json.loads(assessment.evidence) if assessment else {},csrf_token=session['qualification_csrf'])


@dashboard_bp.post('/replies/<int:activity_id>/qualification')
def qualification_review(activity_id):
    import secrets
    from flask import request, session, abort, redirect, url_for
    from app.agents.qualification import save_qualification, FIELDS
    token=request.form.get('csrf_token','')
    if not token or not secrets.compare_digest(token,session.get('qualification_csrf','')):abort(400)
    action=request.form.get('action')
    if action not in {'save','qualify'}:abort(400)
    try:
        save_qualification(activity_id,int(request.form.get('revision','')), {field:request.form.get(field,'') for field in FIELDS},action=='qualify')
    except ValueError as exc:abort(409,description=str(exc))
    return redirect(url_for('dashboard.saved_reply',activity_id=activity_id),code=303)


@dashboard_bp.route('/replies/<int:activity_id>/call-brief',methods=['GET','POST'])
def call_brief(activity_id):
    import json,secrets
    from flask import request,session,abort,redirect,url_for
    from app.models import CallBrief, Meeting, CallOutcome
    from app.agents.call_prep import prepare_call
    if request.method=='POST':
        token=request.form.get('csrf_token','')
        if not token or not secrets.compare_digest(token,session.get('qualification_csrf','')):abort(400)
        try:prepare_call(activity_id)
        except ValueError as exc:abort(409,description=str(exc))
        return redirect(url_for('dashboard.call_brief',activity_id=activity_id),code=303)
    brief=db.session.get(CallBrief,activity_id)
    if brief is None:abort(404)
    from app.agents.booking import meeting_changes
    session.setdefault('booking_csrf',secrets.token_urlsafe(32))
    from app.models import Qualification
    assessment = db.session.get(Qualification, activity_id)
    data = json.loads(brief.snapshot)
    stale = not assessment or not assessment.qualified or assessment.revision != data.get('qualification_revision')
    return render_template('call_brief.html',brief=brief,data=data,stale=stale,meeting=db.session.get(Meeting,activity_id),booking_token=session['booking_csrf'],changes=meeting_changes(activity_id),call_outcome=db.session.get(CallOutcome,activity_id))


@dashboard_bp.post('/replies/<int:activity_id>/meeting')
def record_meeting(activity_id):
    import secrets
    from flask import request,session,abort,redirect,url_for
    from app.agents.booking import confirm_meeting
    token=request.form.get('csrf_token','')
    if not token or not secrets.compare_digest(token,session.get('booking_csrf','')):abort(400)
    try:confirm_meeting(activity_id,request.form.get('starts_at',''),request.form.get('note',''))
    except ValueError as exc:abort(409,description=str(exc))
    return redirect(url_for('dashboard.call_brief',activity_id=activity_id),code=303)


@dashboard_bp.post('/replies/<int:activity_id>/meeting/change')
def update_meeting(activity_id):
    import secrets
    from flask import request,session,abort,redirect,url_for
    from app.agents.booking import change_meeting
    token=request.form.get('csrf_token','')
    if not token or not secrets.compare_digest(token,session.get('booking_csrf','')):abort(400)
    try:change_meeting(activity_id,int(request.form.get('revision','')),request.form.get('action'),request.form.get('starts_at',''),request.form.get('note',''))
    except ValueError as exc:abort(409,description=str(exc))
    return redirect(url_for('dashboard.call_brief',activity_id=activity_id),code=303)


@dashboard_bp.post('/replies/<int:activity_id>/call-outcome')
def record_call_outcome(activity_id):
    import secrets
    from flask import request,session,abort,redirect,url_for
    from app.agents.post_call import log_call
    token=request.form.get('csrf_token','')
    if not token or not secrets.compare_digest(token,session.get('booking_csrf','')):abort(400)
    if request.form.get('completed')!='yes':abort(400,description='Confirm that the call took place.')
    try:log_call(activity_id,request.form.get('outcome'),request.form.get('notes',''),request.form.get('next_step',''),request.form.get('follow_up_at',''))
    except ValueError as exc:abort(409,description=str(exc))
    return redirect(url_for('dashboard.call_brief',activity_id=activity_id),code=303)


@dashboard_bp.get('/workflow')
def workflow_queue():
    from app.services.workflow import next_actions
    return render_template('workflow.html',actions=next_actions())
