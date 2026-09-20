"""Human-entered evidence, explicit qualification, optimistic revision checks."""
import json
from app.models import db, RecordedReply, Contact, Qualification, Activity, OutreachStop

FIELDS=('budget','authority','need','timing')


def save_qualification(reply_id, revision, evidence, qualify=False):
    if type(revision) is not int or revision<0 or set(evidence)!=set(FIELDS):
        raise ValueError('Invalid qualification form. Reload the reply.')
    if any(not isinstance(v,str) or len(v)>1500 for v in evidence.values()):
        raise ValueError('Each evidence note must be at most 1,500 characters.')
    evidence={k:v.strip() for k,v in evidence.items()}
    record=RecordedReply.query.filter_by(activity_id=reply_id).first()
    if record is None: raise ValueError('Saved reply not found.')
    contact=db.session.get(Contact,record.contact_id)
    current=db.session.get(Qualification,reply_id)
    if revision!=(current.revision if current else 0):
        raise ValueError('Qualification changed. Reload before saving.')
    if current and current.qualified:
        raise ValueError('This assessment is already qualified; its evidence is preserved.')
    if qualify:
        if not all(evidence.values()):raise ValueError('Record evidence for all four criteria before qualifying.')
        stop=db.session.get(OutreachStop,(contact.email or '').strip().casefold())
        if record.outcome!='interested' or contact.pipeline_stage!='replied' or (stop and stop.active and stop.reason in {'unsubscribe','bounced'}):
            raise ValueError('Qualification requires an interested reply, replied contact progress, and no unsubscribe or bounce block.')
    try:
        encoded=json.dumps(evidence)
        if current:
            changed=db.session.execute(db.update(Qualification).where(Qualification.reply_id==reply_id,Qualification.revision==revision).values(evidence=encoded,revision=revision+1,qualified=qualify))
            if changed.rowcount!=1:raise ValueError('Qualification changed. Reload before saving.')
        else:
            db.session.add(Qualification(reply_id=reply_id,evidence=encoded,revision=1,qualified=qualify));db.session.flush()
        if qualify:
            from app.services.statuses import advance_contact
            advance_contact(contact.id,'replied','qualified',f'manual qualification on reply {reply_id}')
        db.session.add(Activity(account_id=contact.account_id,contact_id=contact.id,activity_type='qualification_review',channel='internal',summary=json.dumps({'reply_id':reply_id,'revision':revision+1,'evidence':evidence,'qualified':qualify,'source':'manual review'})))
        db.session.commit()
    except Exception:
        db.session.rollback();raise
