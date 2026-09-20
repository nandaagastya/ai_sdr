"""Human draft revisions and approval. Never invokes a provider or delivery."""
import copy
import json
from datetime import datetime, timezone

from app.models import db, Activity


class ReviewConflict(ValueError):
    pass


def get_preview(preview_id):
    activity = db.session.get(Activity, preview_id)
    if activity is None or activity.activity_type != 'outreach_preview':
        return None
    draft = json.loads(activity.summary)
    draft.setdefault('revision', 1)
    draft.setdefault('review_status', 'draft')
    draft.setdefault('review_history', [])
    return {**draft, 'activity_id': activity.id}


def review_preview(preview_id, payload):
    if not isinstance(payload, dict):
        raise ValueError('Provide a JSON object.')
    action = payload.get('action')
    allowed = {'action', 'revision', 'messages'} if action == 'save' else {'action', 'revision'}
    if action not in ('save', 'approve', 'reopen') or set(payload) - allowed:
        raise ValueError('Choose save, approve, or reopen; only revision and edit messages are supported.')
    revision = payload.get('revision')
    if type(revision) is not int or revision < 1:
        raise ValueError('A valid revision number is required.')
    activity = db.session.get(Activity, preview_id)
    if activity is None or activity.activity_type != 'outreach_preview':
        return None
    original = activity.summary
    draft = get_preview(preview_id)
    if revision != draft['revision']:
        raise ReviewConflict('This preview changed in another tab. Reload the saved preview before continuing.')
    if action == 'approve' and draft['review_status'] == 'approved':
        return draft
    if action == 'reopen' and draft['review_status'] == 'draft':
        return draft
    before = {'revision': draft['revision'], 'review_status': draft['review_status'],
              'messages': copy.deepcopy(draft['messages']), 'approved_at': draft.get('approved_at')}
    if action == 'save':
        messages = payload.get('messages')
        if not isinstance(messages, list) or len(messages) != len(draft['messages']):
            raise ValueError('Provide all three messages with subject and body.')
        edited = []
        for source, message in zip(draft['messages'], messages):
            if not isinstance(message, dict) or set(message) != {'subject', 'body'}:
                raise ValueError('Each message must contain only subject and body.')
            for field, limit in [('subject', 200), ('body', 5000)]:
                value = message[field]
                if not isinstance(value, str) or not value.strip() or len(value) > limit:
                    raise ValueError(f'Each {field} is required and must be at most {limit} characters.')
                permitted = '\r\n\t' if field == 'body' else ''
                if any((ord(c) < 32 and c not in permitted) or ord(c) == 127 for c in value):
                    raise ValueError(f'Invalid control characters in {field}.')
            edited.append({**source, 'subject': message['subject'].strip(),
                           'body': message['body'].replace('\r\n', '\n').replace('\r', '\n').strip()})
        if edited == draft['messages']:
            return draft
        draft['messages'] = edited
        draft['review_status'] = 'draft'
        draft['approved_at'] = None
    elif action == 'approve':
        draft['review_status'] = 'approved'
        draft['approved_at'] = datetime.now(timezone.utc).isoformat()
    else:
        draft['review_status'] = 'draft'
        draft['approved_at'] = None
    draft['revision'] += 1
    draft['review_history'].append({**before, 'action': action,
                                   'changed_at': datetime.now(timezone.utc).isoformat()})
    # Approval records intent only, and is never delivery authorization.
    draft.update(sent=False, scheduled=False)
    stored = {key: value for key, value in draft.items() if key != 'activity_id'}
    try:
        updated = db.session.execute(
            db.update(Activity).where(Activity.id == preview_id, Activity.summary == original)
            .values(summary=json.dumps(stored)), execution_options={'synchronize_session': False})
        if updated.rowcount != 1:
            raise ReviewConflict('This preview changed in another tab. Reload the saved preview before continuing.')
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return draft
