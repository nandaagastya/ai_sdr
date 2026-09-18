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

from app.models import db, Account, AgentRun

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_companies/search"

# Defaults that mirror the parameters that worked in prior live runs
# (US-based Salesforce consulting firms, 51-500 employees).
DEFAULT_KEYWORD_TAGS = ["Salesforce consulting"]
DEFAULT_EMPLOYEE_RANGES = ["51,200", "201,500"]
DEFAULT_LOCATIONS = ["United States"]
DEFAULT_PER_PAGE = 10


def score_icp_fit(org: dict) -> tuple[int, list[str]]:
    """
    Transparent, rules-based ICP scorer (0-100). Every point is
    explainable — no ML black box — so a rep or a client can see exactly
    why an account ranked where it did.
    """
    score = 0
    reasons = []

    employee_count = org.get("estimated_num_employees") or org.get("employee_count") or 0
    if 51 <= employee_count <= 500:
        score += 40
        reasons.append(f"employee count {employee_count} in target range (51-500)")
    elif employee_count:
        reasons.append(f"employee count {employee_count} outside target range")

    keywords = " ".join(org.get("keywords", []) or []).lower()
    industry = (org.get("industry") or "").lower()
    name = (org.get("name") or "").lower()
    if any(term in keywords or term in industry or term in name for term in ("salesforce", "crm consulting", "consulting")):
        score += 30
        reasons.append("keyword/industry match on target vertical")

    location = (org.get("country") or org.get("primary_country") or "").lower()
    if location in ("united states", "us", "usa", ""):
        score += 20
        reasons.append("US-based (or unspecified, treated as pass)")

    if org.get("primary_domain") or org.get("website_url"):
        score += 10
        reasons.append("has a contactable domain")

    return min(score, 100), reasons


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

    payload = resp.json()
    organizations = payload.get("organizations", []) or payload.get("accounts", [])

    upserted = []
    for org in organizations:
        score, reasons = score_icp_fit(org)
        domain = org.get("primary_domain") or org.get("website_url")

        account = Account.query.filter_by(domain=domain).first() if domain else None
        is_new = account is None
        if is_new:
            account = Account(name=org.get("name", "Unknown"), domain=domain, source="apollo")
            db.session.add(account)

        account.name = org.get("name", account.name)
        account.industry = org.get("industry")
        account.employee_count = org.get("estimated_num_employees") or org.get("employee_count")
        account.location = org.get("country") or org.get("primary_country")
        account.icp_fit_score = score
        account.icp_fit_reasons = " | ".join(reasons)
        if is_new or account.stage == "new":
            account.stage = "qualified" if score >= 60 else "new"

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
