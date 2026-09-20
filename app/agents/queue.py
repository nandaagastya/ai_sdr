"""Read-only review queue for the prototype's JSON-backed previews."""
import json

from app.models import Activity

PAGE_SIZE = 20


def list_previews(status='all', query='', page=1):
    if status not in ('all', 'draft', 'approved'):
        raise ValueError('Choose all, draft, or approved.')
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('Search must be at most 200 characters.')
    if type(page) is not int or page < 1:
        raise ValueError('Page must be a positive integer.')
    query = query.strip()
    counts = {'all': 0, 'draft': 0, 'approved': 0}
    matches = []
    # Summary is a Text column in existing databases. Parse in Python so old
    # previews need no JSON-specific database function or schema migration.
    rows = Activity.query.with_entities(Activity.id, Activity.summary, Activity.created_at).filter_by(
        activity_type='outreach_preview').order_by(Activity.id.desc())
    for activity in rows:
        draft = json.loads(activity.summary)
        review_status = draft.get('review_status', 'draft')
        subject = draft['messages'][0]['subject']
        search_text = ' '.join([str(activity.id), draft['company'], draft['recipient'], subject])
        if query.casefold() not in search_text.casefold():
            continue
        counts['all'] += 1
        counts[review_status] += 1
        if status == 'all' or status == review_status:
            matches.append({'id': activity.id, 'company': draft['company'],
                            'recipient': draft['recipient'], 'subject': subject,
                            'review_status': review_status, 'revision': draft.get('revision', 1),
                            'generation': 'AI opening' if draft.get('ai') else 'Template',
                            'created_at': activity.created_at})
    total = len(matches)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    start = (page - 1) * PAGE_SIZE
    return {'previews': matches[start:start + PAGE_SIZE], 'counts': counts,
            'status': status, 'query': query, 'page': page, 'pages': pages,
            'total': total, 'first': start + 1 if total else 0, 'last': min(start + PAGE_SIZE, total)}
