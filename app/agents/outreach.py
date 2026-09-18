"""Deterministic outreach previews. No delivery provider or scheduler is called."""
import json
from datetime import datetime
from pathlib import Path

from app.models import db, Account, Contact, Activity, AgentRun

TEMPLATE_VERSION = 'outreach-v1'
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / 'prompts' / 'outreach'


def preview_outreach(payload):
    if not isinstance(payload, dict):
        raise ValueError('Provide a JSON object or use the preview form.')
    if set(payload) - {'contact_id', 'sender_name', 'offer'}:
        raise ValueError('Only contact_id, sender_name, and offer are supported; this endpoint never sends email.')
    contact_id = payload.get('contact_id')
    if isinstance(contact_id, bool) or not isinstance(contact_id, int) or contact_id < 1:
        raise ValueError('Choose a valid contact.')
    sender = payload.get('sender_name')
    offer = payload.get('offer')
    for value, label, limit in [(sender, 'Sender name', 100), (offer, 'Offer', 600)]:
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'{label} is required and must be at most {limit} characters.')
        if any(ord(c) < 32 for c in value):
            raise ValueError(f'{label} must be a single line without control characters.')
    contact = db.session.get(Contact, contact_id)
    if contact is None:
        raise ValueError('Contact not found. Load demo data or select an existing contact.')
    account = db.session.get(Account, contact.account_id)
    if not contact.email or '@' not in contact.email or any(c.isspace() for c in contact.email):
        raise ValueError('This contact needs a valid email address before previewing outreach.')

    run = AgentRun(agent_name='outreach', status='running', detail='Preview generation; no email delivery.')
    db.session.add(run)
    db.session.commit()
    run_id = run.id
    try:
        def clean(value):
            return ' '.join((value or '').split())
        context = {
            'first_name': clean(contact.first_name) or 'there',
            'company': clean(account.name),
            'sender_name': sender.strip(),
            'offer': offer.strip(),
            'role_context': (f'Given your role as {clean(contact.title)} at {clean(account.name)}, '
                             'I wanted to reach out.' if contact.title else
                             f'I wanted to reach out to the team at {clean(account.name)}.'),
        }
        messages = []
        for index, day in enumerate((0, 4, 9), start=1):
            template = (TEMPLATE_DIR / f'{TEMPLATE_VERSION}-touch-{index}.txt').read_text()
            subject, body = template.format_map(context).split('\n', 1)
            messages.append({'touch': index, 'suggested_day': day, 'subject': subject,
                             'body': body.strip()})
        draft = {
            'mode': 'preview', 'sent': False, 'scheduled': False,
            'template_version': TEMPLATE_VERSION, 'generation': 'rules-based template',
            'contact_id': contact.id, 'account_id': account.id,
            'recipient': contact.email, 'company': account.name,
            'messages': messages,
            'icp_reasons': account.icp_fit_reasons.split(' | ') if account.icp_fit_reasons else [],
        }
        activity = Activity(account_id=account.id, contact_id=contact.id,
                            activity_type='outreach_preview', channel='email',
                            summary=json.dumps(draft))
        db.session.add(activity)
        db.session.flush()
        run.status = 'success'
        run.records_processed = 1
        run.finished_at = datetime.utcnow()
        run.detail = f'PREVIEW ONLY: 3 drafts for contact {contact.id}; activity {activity.id}; {TEMPLATE_VERSION}. Sent 0; scheduled 0; provider cost 0.'
        db.session.commit()
        return {**draft, 'activity_id': activity.id, 'agent_run_id': run_id}
    except Exception:
        db.session.rollback()
        failed = db.session.get(AgentRun, run_id)
        failed.status = 'error'
        failed.finished_at = datetime.utcnow()
        failed.detail = 'Preview generation failed; no email sent or scheduled.'
        db.session.commit()
        raise
