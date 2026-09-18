"""
API layer — six endpoints over the shared data model.

  GET  /api/accounts        list accounts (optionally filtered by stage)
  GET  /api/accounts/<id>   single account with contacts/activities/tasks
  GET  /api/contacts        list contacts (optionally filtered by account_id)
  GET  /api/tasks           list open follow-up tasks
  GET  /api/agent-runs      audit trail of every agent execution
  GET  /api/pipeline        aggregate stage counts + avg ICP score (dashboard feed)
  POST /api/prospect/run    trigger the prospecting agent (Apollo -> ICP score -> upsert)
"""
from flask import Blueprint, jsonify, request

from app.models import db, Account, Contact, Task, AgentRun
from app.agents.prospecting import run_prospecting_agent

api_bp = Blueprint("api", __name__)


@api_bp.get("/accounts")
def list_accounts():
    stage = request.args.get("stage")
    query = Account.query
    if stage:
        query = query.filter_by(stage=stage)
    accounts = query.order_by(Account.icp_fit_score.desc()).all()
    return jsonify([a.to_dict() for a in accounts])


@api_bp.get("/accounts/<int:account_id>")
def get_account(account_id):
    account = Account.query.get_or_404(account_id)
    data = account.to_dict()
    data["contacts"] = [c.to_dict() for c in account.contacts]
    data["activities"] = [a.to_dict() for a in account.activities]
    data["tasks"] = [t.to_dict() for t in account.tasks]
    return jsonify(data)


@api_bp.get("/contacts")
def list_contacts():
    account_id = request.args.get("account_id", type=int)
    query = Contact.query
    if account_id:
        query = query.filter_by(account_id=account_id)
    contacts = query.all()
    return jsonify([c.to_dict() for c in contacts])


@api_bp.get("/tasks")
def list_tasks():
    status = request.args.get("status", "open")
    tasks = Task.query.filter_by(status=status).order_by(Task.due_at.asc().nulls_last()).all()
    return jsonify([t.to_dict() for t in tasks])


@api_bp.get("/agent-runs")
def list_agent_runs():
    limit = request.args.get("limit", 25, type=int)
    runs = AgentRun.query.order_by(AgentRun.started_at.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in runs])


@api_bp.get("/pipeline")
def pipeline_summary():
    stages = ["new", "qualified", "outreach", "replied", "booked", "closed"]
    counts = {
        stage: Account.query.filter_by(stage=stage).count() for stage in stages
    }
    total_accounts = Account.query.count()
    avg_score_row = db.session.query(db.func.avg(Account.icp_fit_score)).scalar()
    open_tasks = Task.query.filter_by(status="open").count()
    last_run = AgentRun.query.order_by(AgentRun.started_at.desc()).first()

    return jsonify(
        {
            "stage_counts": counts,
            "total_accounts": total_accounts,
            "avg_icp_fit_score": round(avg_score_row or 0, 1),
            "open_tasks": open_tasks,
            "last_agent_run": last_run.to_dict() if last_run else None,
        }
    )


@api_bp.post("/prospect/run")
def trigger_prospecting_run():
    """
    Kick off a live prospecting run against Apollo.

    Body (all optional, defaults match the documented working params):
    {
      "keyword_tags": ["Salesforce consulting"],
      "employee_ranges": ["51,200", "201,500"],
      "locations": ["United States"],
      "per_page": 10
    }
    """
    payload = request.get_json(silent=True) or {}
    result = run_prospecting_agent(
        keyword_tags=payload.get("keyword_tags"),
        employee_ranges=payload.get("employee_ranges"),
        locations=payload.get("locations"),
        per_page=payload.get("per_page", 10),
    )
    status_code = 200 if result["status"] == "success" else 502
    return jsonify(result), status_code


@api_bp.post("/outreach/preview")
def generate_outreach_preview():
    from app.agents.outreach import preview_outreach
    from flask import current_app
    try:
        draft = preview_outreach(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Outreach preview failed")
        return jsonify({"status": "error", "message": "Preview generation failed. Check agent runs."}), 500
    return jsonify({"status": "success", **draft}), 201
