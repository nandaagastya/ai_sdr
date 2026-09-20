"""Local eligibility checks, not proof of deliverability or permission to send."""
import re
from app.models import db, Account, Contact, OutreachStop


def blocked_reason(draft):
    contact = db.session.get(Contact, draft['contact_id'])
    if contact is None or contact.account_id != draft['account_id']:
        return 'Contact no longer matches this preview.'
    email = (contact.email or '').strip().casefold()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return 'Contact needs a valid email address.'
    if email != (draft.get('recipient') or '').strip().casefold():
        return 'Recipient changed. Create and approve a new preview.'
    stop = db.session.get(OutreachStop, email)
    if stop and stop.active:
        return 'Outreach stopped: ' + stop.reason.replace('_',' ') + '.'
    if contact.pipeline_stage != 'not_contacted':
        return 'First-touch outreach blocked by contact progress: ' + contact.pipeline_stage.replace('_',' ') + '.'
    account = db.session.get(Account,contact.account_id)
    if account.stage not in ('new','qualified'):
        return 'Company has existing sales progress. Review before starting new outreach.'
    return None


def set_stop(email, reason):
    if reason not in {'paused','unsubscribe','bounced'}:
        raise ValueError('Choose a supported stop reason.')
    email = email.strip().casefold()
    existing = db.session.get(OutreachStop,email)
    # A casual pause must never downgrade a permanent suppression.
    if existing and existing.active and existing.reason in {'unsubscribe','bounced'}:
        return
    if existing is None:
        db.session.add(OutreachStop(email=email,reason=reason,active=True))
    else:
        existing.reason=reason; existing.active=True
