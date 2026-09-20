"""Explicitly reviewed manual replies, deduplicated and committed atomically."""
import hashlib
import json
from app.models import db, Contact, Activity, Task, RecordedReply
from app.agents.replies import classify_reply, NEXT
from app.services.eligibility import set_stop


def record_reply(sender, body, outcome):
    analysis = classify_reply(body)
    if outcome not in NEXT:
        raise ValueError('Choose a reviewed outcome.')
    sender=(sender or '').strip().casefold()
    body=body.replace('\r\n','\n').strip()
    matches=Contact.query.filter(db.func.lower(Contact.email)==sender).all() if sender else []
    if len(matches)!=1:
        raise ValueError('Sender must match exactly one saved contact. Resolve missing or duplicate contacts before recording.')
    contact=matches[0]
    key=hashlib.sha256((sender+'\n'+body).encode()).hexdigest()
    existing=db.session.get(RecordedReply,key)
    if existing:
        if existing.outcome!=outcome:
            raise ValueError('This reply was already recorded with a different outcome; review its history before changing it.')
        return existing.activity_id
    try:
        activity=Activity(account_id=contact.account_id,contact_id=contact.id,activity_type='reply',channel='email',
            summary=json.dumps({'direction':'in','source':'manual_review','sender':sender,'body':body,
                                'outcome':outcome,'classifier':analysis,'sender_verified':False}))
        db.session.add(activity);db.session.flush()
        db.session.add(RecordedReply(fingerprint=key,contact_id=contact.id,outcome=outcome,activity_id=activity.id))
        db.session.flush()  # Claim the unique reply before applying any effects.
        set_stop(sender,'unsubscribe' if outcome=='unsubscribe' else 'paused')
        if outcome not in {'out_of_office','needs_review'} and contact.pipeline_stage in {'not_contacted','outreach'}:
            contact.pipeline_stage='replied'
        if outcome!='unsubscribe':
            from app.services.workflow_tasks import create_task
            create_task(activity.id, 'reply_review',
                f'Review {outcome.replace("_"," ")} reply #{activity.id} from {sender}. {NEXT[outcome]}'[:500])
        db.session.commit()
        return activity.id
    except Exception:
        db.session.rollback()
        raise
