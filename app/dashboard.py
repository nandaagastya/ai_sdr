"""
Dashboard — server-rendered pipeline view, agent-stack map, and data-flow
diagram. Reads straight from the shared data layer (no HTTP round-trip
through the API blueprint) since it runs in the same process.
"""
from flask import Blueprint, render_template

from app.models import db, Account, Task, AgentRun

dashboard_bp = Blueprint("dashboard", __name__)

STAGES = ["new", "qualified", "outreach", "replied", "booked", "closed"]


@dashboard_bp.get("/")
def dashboard():
    stage_counts = {stage: Account.query.filter_by(stage=stage).count() for stage in STAGES}
    total_accounts = Account.query.count()
    avg_score = db.session.query(db.func.avg(Account.icp_fit_score)).scalar() or 0
    open_tasks = Task.query.filter_by(status="open").count()

    top_accounts = (
        Account.query.order_by(Account.icp_fit_score.desc()).limit(10).all()
    )
    recent_runs = AgentRun.query.order_by(AgentRun.started_at.desc()).limit(8).all()

    return render_template(
        "dashboard.html",
        stage_counts=stage_counts,
        stages=STAGES,
        total_accounts=total_accounts,
        avg_score=round(avg_score, 1),
        open_tasks=open_tasks,
        top_accounts=top_accounts,
        recent_runs=recent_runs,
    )
