"""Human correction forms. Authentication attribution will replace the manual label."""
import json
import secrets
from flask import Blueprint, abort, render_template, request, session, redirect, url_for
from app.models import db, Qualification, CallOutcome, Activity
from app.agents.corrections import (history, outcome_snapshot, correct_qualification, correct_outcome)

corrections_bp = Blueprint('corrections', __name__)


@corrections_bp.route('/replies/<int:reply_id>/correct/<entity>', methods=['GET', 'POST'])
def correct(reply_id, entity):
    if entity not in {'qualification', 'call_outcome'}:
        abort(404)
    record = db.session.get(Qualification if entity == 'qualification' else CallOutcome, reply_id)
    if record is None:
        abort(404)
    session.setdefault('correction_csrf', secrets.token_urlsafe(32))
    revisions = history(reply_id, entity)
    revision = record.revision if entity == 'qualification' else (revisions[0].revision if revisions else 0)
    values = (json.loads(record.evidence) if entity == 'qualification' else outcome_snapshot(record))
    error = None
    if request.method == 'POST':
        token = request.form.get('csrf_token', '')
        if not token or not secrets.compare_digest(token, session['correction_csrf']):
            abort(400)
        values = request.form.to_dict()
        try:
            expected = int(values.get('revision', ''))
            if entity == 'qualification':
                if values.get('decision') not in {'keep', 'revoke'}:
                    raise ValueError('Choose whether qualification remains supported.')
                correct_qualification(reply_id, expected, {k: values.get(k, '') for k in ('budget','authority','need','timing')},
                    values['decision'] == 'keep', values.get('reviewer'), values.get('reason'))
            else:
                correct_outcome(reply_id, expected, values.get('outcome'), values.get('notes'), values.get('next_step',''),
                    values.get('follow_up_at',''), values.get('reviewer'), values.get('reason'))
            return redirect(url_for('corrections.correct', reply_id=reply_id, entity=entity), code=303)
        except ValueError as exc:
            error = str(exc)
            # Keep the submitted revision on an error; never silently bless a stale form.
            revision = values.get('revision', '')
    source = db.session.get(Activity, reply_id)
    return render_template('correction.html', entity=entity, reply_id=reply_id, record=record,
        values=values, revision=revision, revisions=[{**r.__dict__, 'before_data':json.loads(r.before),
        'after_data':json.loads(r.after)} for r in revisions], error=error, csrf_token=session['correction_csrf']), 409 if error else 200
