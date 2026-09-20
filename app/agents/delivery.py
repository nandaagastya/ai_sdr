"""Explicit first-touch simulation; independent of actual contact progress."""
import json
from datetime import datetime
from app.models import db, Activity, AgentRun, DeliverySimulation
from app.agents.review import get_preview
from app.providers.delivery import FakeDeliveryProvider


def simulate_delivery(preview_id, revision):
    if type(revision) is not int or revision < 1:
        raise ValueError('Provide the current saved revision.')
    try:
        activity = db.session.get(Activity, preview_id)
        draft = get_preview(preview_id)
        if draft is None:
            raise ValueError('Preview not found.')
        if draft['revision'] != revision or draft['review_status'] != 'approved':
            raise ValueError('Reload and approve the current saved draft before simulating delivery.')
        # Serialize against concurrent edits/approval changes in the same transaction.
        locked = db.session.execute(db.update(Activity).where(Activity.id == preview_id,
            Activity.summary == activity.summary).values(summary=activity.summary))
        if locked.rowcount != 1:
            raise ValueError('Preview changed. Reload before simulating delivery.')
        existing = DeliverySimulation.query.filter_by(preview_id=preview_id,revision=revision,touch=1).first()
        if existing:
            db.session.commit()
            return existing.id
        from app.services.eligibility import blocked_reason
        reason = blocked_reason(draft)
        if reason:
            raise ValueError(reason)
        snapshot = {'recipient': draft['recipient'], 'message': draft['messages'][0],
                    'revision': revision, 'sent': False, 'scheduled': False}
        receipt = FakeDeliveryProvider().deliver(f'{preview_id}:{revision}:1', snapshot)
        record = DeliverySimulation(preview_id=preview_id, revision=revision,touch=1,
            provider_id=receipt['provider_id'],snapshot=json.dumps(snapshot))
        db.session.add(record)
        db.session.add(AgentRun(agent_name='delivery_simulation',status='success',records_processed=1,
            finished_at=datetime.utcnow(),detail=f'Fake provider only; preview {preview_id} revision {revision}, touch 1. Real emails sent: 0.'))
        db.session.commit()
        return record.id
    except Exception:
        db.session.rollback()
        raise
