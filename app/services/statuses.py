"""Contact progress is independent of company fit and draft approval."""
from sqlalchemy import update
from app.models import Contact, Activity, db

TRANSITIONS = {
    'not_contacted': {'outreach'}, 'outreach': {'replied'},
    'replied': {'qualified'}, 'qualified': {'call_prepped'},
    'call_prepped': {'booked'}, 'booked': {'called'}, 'called': {'logged'},
    'logged': set(), 'needs_review': set(),
}


def advance_contact(contact_id, expected, target, evidence):
    """Internal agent contract; caller commits event + transition together.

    Deliberately no public status-changing endpoint: future agents supply evidence.
    """
    if target not in TRANSITIONS.get(expected, set()):
        raise ValueError('This contact progress transition is not allowed.')
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError('A source event reference is required.')
    contact = db.session.get(Contact, contact_id)
    if contact is None:
        raise ValueError('Contact not found.')
    result = db.session.execute(update(Contact).where(Contact.id == contact_id,
        Contact.pipeline_stage == expected).values(pipeline_stage=target))
    if result.rowcount != 1:
        raise ValueError('Contact progress changed; reload before retrying.')
    db.session.add(Activity(account_id=contact.account_id, contact_id=contact.id,
        activity_type='progress_changed', channel='internal',
        summary=f'{expected} → {target}; evidence: {evidence.strip()}'))
