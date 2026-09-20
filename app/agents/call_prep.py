"""Deterministic brief with immutable source snapshot. No external calls."""
import json
from app.models import db, Qualification, RecordedReply, Contact, Activity, CallBrief, Task, OutreachStop
from app.services.statuses import advance_contact


def prepare_call(reply_id):
    existing=db.session.get(CallBrief,reply_id)
    if existing:return existing
    assessment=db.session.get(Qualification,reply_id)
    record=RecordedReply.query.filter_by(activity_id=reply_id).first()
    if not record or not assessment or not assessment.qualified:
        raise ValueError('Confirm qualification before preparing a call.')
    contact=db.session.get(Contact,record.contact_id)
    stop=db.session.get(OutreachStop,(contact.email or '').strip().casefold())
    if stop and stop.active and stop.reason in {'unsubscribe','bounced'}:
        raise ValueError('Resolve the contact restriction before preparing a call.')
    activity=db.session.get(Activity,reply_id)
    source=json.loads(activity.summary)
    evidence=json.loads(assessment.evidence)
    snapshot={'version':'call-brief-v1','reply_id':reply_id,'qualification_revision':assessment.revision,
        'company':contact.account.name,'contact':(' '.join(filter(None,[contact.first_name,contact.last_name])) or 'Name unknown'),
        'email':contact.email,'title':contact.title or 'Role unknown','reply':source['body'],
        'fit':contact.account.icp_fit_reasons or 'Not assessed','evidence':evidence,
        'questions':['What would a successful outcome look like for your team?',
                     'Who else should be involved in evaluating the next step?',
                     'What needs to happen before you can agree on timing and budget?']}
    try:
        brief=CallBrief(reply_id=reply_id,snapshot=json.dumps(snapshot));db.session.add(brief);db.session.flush()
        advance_contact(contact.id,'qualified','call_prepped',f'call brief for reply {reply_id}')
        from app.services.workflow_tasks import create_task
        create_task(reply_id, 'brief_review', f'Review call brief for reply #{reply_id} before scheduling.')
        db.session.commit()
        return brief
    except Exception:
        db.session.rollback();raise
