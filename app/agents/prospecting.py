"""
Prospecting agent — the first stage of the eight-agent SDR pipeline.

What it does:
  1. Calls the Apollo.io organization search API for a target ICP slice.
  2. Scores each returned org with a transparent, rules-based ICP-fit
     scorer (no black-box ML — see README.md for why that's a deliberate
     product choice).
  3. Upserts qualifying orgs into the shared Account table, seeding a
     placeholder AgentRun-linked audit trail as it goes.

Apollo learnings baked in here (from prior live runs):
  - Auth must be confirmed before trusting a "no results" response —
    a bad/missing key fails silently rather than raising, so we check
    for an explicit 200 and a non-empty payload before treating a run
    as successful.
  - Organization *search* (this module) is the right call pre-scoring;
    per-domain *enrichment* (a separate, credit-costed call) belongs
    downstream, only on orgs that already cleared the ICP bar.
"""
import os
from datetime import datetime

import requests

from app.models import db, Account, AgentRun, Activity

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_companies/search"

# Defaults that mirror the parameters that worked in prior live runs
# (US-based Salesforce consulting firms, 51-500 employees).
DEFAULT_KEYWORD_TAGS = ["Salesforce consulting"]
DEFAULT_EMPLOYEE_RANGES = ["51,200", "201,500"]
DEFAULT_LOCATIONS = ["United States"]
DEFAULT_PER_PAGE = 10


def score_icp_fit(org: dict) -> tuple[int, list[str]]:
    from app.services.lead_quality import assess
    score, reasons, _ = assess(org.get('name'), org.get('industry'),
        org.get('estimated_num_employees') or org.get('employee_count'),
        org.get('country') or org.get('primary_country'),
        org.get('primary_domain') or org.get('website_url'))
    return score, reasons


def _log_run_start(agent_name="prospecting"):
    run = AgentRun(agent_name=agent_name, status="running")
    db.session.add(run)
    db.session.commit()
    return run


def _log_run_end(run, status, records_processed, detail):
    run.status = status
    run.records_processed = records_processed
    run.detail = detail
    run.finished_at = datetime.utcnow()
    db.session.commit()


def run_prospecting_agent(
    keyword_tags=None,
    employee_ranges=None,
    locations=None,
    per_page=DEFAULT_PER_PAGE,
    domains=None,
):
    keyword_tags = keyword_tags or DEFAULT_KEYWORD_TAGS
    employee_ranges = employee_ranges or DEFAULT_EMPLOYEE_RANGES
    locations = locations or DEFAULT_LOCATIONS

    run = _log_run_start()

    api_key = os.environ.get("APOLLO_API_KEY")
    if not api_key:
        _log_run_end(
            run,
            status="error",
            records_processed=0,
            detail="APOLLO_API_KEY not set — see .env.example. No call was made.",
        )
        return {
            "status": "error",
            "message": "APOLLO_API_KEY not set. Add it to your .env file, then retry.",
            "agent_run_id": run.id,
        }

    body = {
        "q_organization_keyword_tags": keyword_tags,
        "organization_num_employees_ranges": employee_ranges,
        "organization_locations": locations,
        "per_page": per_page,
    }

    if domains:
        body = {'q_organization_domains_list': domains, 'per_page': per_page}

    try:
        resp = requests.post(
            APOLLO_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": api_key,
            },
            json=body,
            timeout=20,
        )
    except requests.RequestException as exc:
        _log_run_end(run, status="error", records_processed=0, detail=str(exc))
        return {"status": "error", "message": f"Apollo request failed: {exc}", "agent_run_id": run.id}

    if resp.status_code != 200:
        detail = f"Apollo returned HTTP {resp.status_code}: {resp.text[:300]}"
        _log_run_end(run, status="error", records_processed=0, detail=detail)
        return {"status": "error", "message": detail, "agent_run_id": run.id}

    try:
        payload = resp.json()
        organizations = payload.get("organizations", []) or payload.get("accounts", [])
        if not isinstance(organizations, list) or any(not isinstance(org, dict) for org in organizations):
            raise ValueError('Invalid organization list')
    except (ValueError, AttributeError):
        _log_run_end(run, status='error', records_processed=0, detail='Apollo returned invalid data.')
        return {'status':'error', 'message':'Apollo returned invalid data.', 'agent_run_id':run.id}

    upserted = []
    for org in organizations:
        score, reasons = score_icp_fit(org)
        domain = org.get("primary_domain") or org.get("website_url")
        if domain:
            from urllib.parse import urlsplit
            domain = urlsplit(domain if '://' in domain else 'https://' + domain).hostname
            domain = domain.lower().removeprefix('www.') if domain else None

        account = Account.query.filter(db.func.lower(Account.domain) == domain).first() if domain else None
        is_new = account is None
        if is_new:
            account = Account(name=org.get("name", "Unknown"), domain=domain, source="apollo")
            db.session.add(account)

        if not is_new and account.source in ('web', 'import'):
            account.source += '+apollo'
        db.session.add(Activity(account=account, activity_type='apollo_source', channel='apollo',
                                summary='Company data retrieved through Apollo organization search.'))
        # Partial provider responses must not erase existing facts.
        for field, value in {
            'name': org.get('name'), 'industry': org.get('industry'),
            'location': org.get('country') or org.get('primary_country'),
        }.items():
            if isinstance(value, str) and value.strip():
                setattr(account, field, value.strip())
        count = org.get('estimated_num_employees') or org.get('employee_count')
        if not isinstance(count, bool) and str(count).isdigit() and 0 < int(count) <= 100000000:
            account.employee_count = int(count)
        from app.services.lead_quality import apply_quality
        apply_quality(account)
        score = account.icp_fit_score

        upserted.append({"name": account.name, "domain": account.domain, "icp_fit_score": score})

    db.session.commit()

    detail = f"Fetched {len(organizations)} orgs from Apollo, upserted {len(upserted)} accounts."
    _log_run_end(run, status="success", records_processed=len(upserted), detail=detail)

    return {
        "status": "success",
        "agent_run_id": run.id,
        "accounts": upserted,
        "detail": detail,
    }
