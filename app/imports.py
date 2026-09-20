"""Upload → map columns → review → confirm, scoped to the browser session."""
import json
import secrets
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for, Response
from werkzeug.utils import secure_filename
from app.models import db, LeadImport
from app.services.lead_import import FIELDS, parse_file, suggest_mapping, normalize_rows, classify, commit_import, MAX_BYTES

imports_bp = Blueprint('imports', __name__)


def csrf_token():
    session.setdefault('import_csrf', secrets.token_urlsafe(32))
    return session['import_csrf']


def require_csrf():
    if not secrets.compare_digest(request.form.get('csrf_token', ''), csrf_token()):
        abort(400, description='Form expired. Reload and try again.')


def owned_batch(batch_id):
    batch = db.session.get(LeadImport, batch_id)
    if batch is None or batch.owner != session.get('import_owner'):
        abort(404)
    if batch.status != 'complete' and batch.created_at < datetime.utcnow() - timedelta(hours=24):
        abort(410, description='Import preview expired. Upload the file again.')
    return batch


@imports_bp.route('/leads/import', methods=['GET', 'POST'])
def upload():
    error = None
    if request.method == 'POST':
        require_csrf()
        file = request.files.get('file')
        try:
            if file is None or not file.filename:
                raise ValueError('Choose a lead file.')
            try:
                data = parse_file(file.filename, file.read(MAX_BYTES + 1))
            finally:
                file.close()
            session.setdefault('import_owner', secrets.token_hex(32))
            batch = LeadImport(id=uuid.uuid4().hex, owner=session['import_owner'],
                               filename=secure_filename(file.filename)[:255] or 'leads', data=json.dumps(data))
            db.session.add(batch)
            # Expired staging is disposable; never touches accounts or contacts.
            LeadImport.query.filter(LeadImport.status != 'complete', LeadImport.created_at < datetime.utcnow() - timedelta(hours=24)).delete()
            db.session.commit()
            return redirect(url_for('imports.mapping', batch_id=batch.id), code=303)
        except ValueError as exc:
            error = str(exc)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Lead upload failed')
            error = 'Could not prepare this file. Try a smaller CSV file.'
    return render_template('lead_import.html', step='upload', error=error, csrf_token=csrf_token()), 400 if error else 200


@imports_bp.route('/leads/import/<batch_id>/map', methods=['GET', 'POST'])
def mapping(batch_id):
    batch = owned_batch(batch_id)
    if batch.status == 'complete':
        return redirect(url_for('imports.review', batch_id=batch.id))
    data = json.loads(batch.data)
    mapping = suggest_mapping(data['headers'])
    error = None
    if request.method == 'POST':
        require_csrf()
        mapping = {field: request.form.get(field, '') for field, _ in FIELDS}
        try:
            data['leads'] = normalize_rows(data, mapping)
            batch.data, batch.status = json.dumps(data), 'reviewed'
            db.session.commit()
            return redirect(url_for('imports.review', batch_id=batch.id), code=303)
        except ValueError as exc:
            error = str(exc)
    return render_template('lead_import.html', step='map', batch=batch, data=data, fields=FIELDS,
                           mapping=mapping, error=error, csrf_token=csrf_token()), 400 if error else 200


@imports_bp.route('/leads/import/<batch_id>', methods=['GET', 'POST'])
def review(batch_id):
    batch = owned_batch(batch_id)
    error = None
    if request.method == 'POST':
        require_csrf()
        try:
            commit_import(batch)
            return redirect(url_for('imports.review', batch_id=batch.id), code=303)
        except ValueError as exc:
            error = str(exc)
        except Exception:
            current_app.logger.exception('Lead import failed')
            error = 'Import could not be saved. No leads from this attempt were added. Please retry.'
    if batch.status == 'complete':
        return render_template('lead_import.html', step='complete', batch=batch, result=json.loads(batch.result))
    if batch.status != 'reviewed':
        return redirect(url_for('imports.mapping', batch_id=batch.id))
    rows = classify(json.loads(batch.data)['leads'])
    counts = {state: sum(row['state'] == state for row in rows) for state in ('ready', 'duplicate', 'invalid')}
    return render_template('lead_import.html', step='review', batch=batch, rows=rows, counts=counts,
                           error=error, csrf_token=csrf_token()), 400 if error else 200


@imports_bp.get('/leads/import/template.csv')
def template():
    return Response('Company,Email,First name,Last name,Job title,Website,Industry,Employees,Location\nExample Consulting,alex@example.test,Alex,Morgan,CEO,example.test,Consulting,100,United States\n',
                    mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=lead-template.csv'})
