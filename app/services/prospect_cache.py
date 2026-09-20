"""Reuse successful provider results; no hidden paid fallback."""
import hashlib
import json
import os
from datetime import datetime, timedelta
from app.models import db, ProspectCache
from app.agents.prospecting import run_prospecting_agent
from app.services.public_web import normalize_url, domain


def cache_key(provider, value):
    return hashlib.sha256((provider + json.dumps(value, sort_keys=True)).encode()).hexdigest()


def read_cache(provider, value):
    cached = db.session.get(ProspectCache, cache_key(provider, value))
    return json.loads(cached.result) if cached and cached.expires_at > datetime.utcnow() else None


def write_cache(provider, value, result, hours=24):
    key = cache_key(provider, value)
    row = db.session.get(ProspectCache, key)
    if row is None:
        row = ProspectCache(key=key, provider=provider)
        db.session.add(row)
    row.result = json.dumps(result)
    row.expires_at = datetime.utcnow() + timedelta(hours=hours)
    db.session.commit()


def cached_apollo(payload):
    if not isinstance(payload, dict) or set(payload) - {'keyword_tags','employee_ranges','locations','per_page','domains','refresh'}:
        raise ValueError('Provide only supported Apollo search filters.')
    if type(payload.get('refresh', False)) is not bool:
        raise ValueError('Refresh must be true or false.')
    limit = payload.get('per_page', 10)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Choose between 1 and 100 companies per search.')
    filters = {'per_page': limit}
    for field, default in [('keyword_tags',['Salesforce consulting']), ('employee_ranges',['51,200','201,500']), ('locations',['United States']), ('domains',[])]:
        values = payload.get(field, default)
        if not isinstance(values, list) or len(values) > 20 or any(not isinstance(x,str) or not x.strip() or len(x)>255 for x in values):
            raise ValueError('Search filters must be lists of up to 20 non-empty strings.')
        filters[field] = sorted({x.strip() for x in values})
    if filters['domains']:
        filters['domains'] = sorted({domain(normalize_url(x)) for x in filters['domains']})
        # Targeted lookup ignores broad discovery filters, so missing web data
        # doesn't inadvertently filter out the requested company.
        for field in ('keyword_tags','employee_ranges','locations'): filters[field] = []
    identity = {'filters':filters, 'account':hashlib.sha256(os.environ.get('APOLLO_API_KEY','').encode()).hexdigest()}
    previous = read_cache('apollo', identity)
    if previous and not payload.get('refresh',False):
        return {**previous, 'cached':True, 'apollo_requests':0}
    result = run_prospecting_agent(**filters)
    result = {**result, 'cached':False, 'apollo_requests':1 if os.environ.get('APOLLO_API_KEY') else 0}
    if result['status'] == 'success': write_cache('apollo',identity,result)
    return result
