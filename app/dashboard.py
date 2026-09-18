"""
Dashboard — server-rendered pipeline view, agent-stack map, and data-flow
diagram. Reads straight from the shared data layer (no HTTP round-trip
through the API blueprint) since it runs in the same process.
"""
from flask import Blueprint, render_template

from app.models import db, Account, Task, AgentRun, Activity

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
        recent_previews=Activity.query.filter_by(activity_type="outreach_preview").order_by(Activity.id.desc()).limit(5).all(),
    )


@dashboard_bp.route("/outreach", methods=["GET", "POST"])
def outreach():
    import json
    from flask import request, redirect, url_for, abort, current_app
    from app.models import Contact, Activity
    from app.agents.outreach import preview_outreach

    values = {}
    error = None
    draft = None
    status = 200
    if request.method == "POST":
        values = request.form.to_dict()
        try:
            values["contact_id"] = int(values.get("contact_id", ""))
            draft = preview_outreach(values)
            return redirect(url_for("dashboard.outreach", preview_id=draft["activity_id"]), code=303)
        except ValueError as exc:
            error, status = str(exc), 400
        except Exception:
            current_app.logger.exception("Outreach preview failed")
            error, status = "Preview generation failed. Check agent runs.", 500
    elif request.args.get("preview_id") is not None:
        preview_id = request.args.get("preview_id", type=int)
        activity = db.session.get(Activity, preview_id) if preview_id else None
        if activity is None or activity.activity_type != "outreach_preview":
            abort(404)
        draft = json.loads(activity.summary)
    contacts = Contact.query.join(Account).order_by(Account.icp_fit_score.desc(), Contact.is_decision_maker.desc(), Contact.id).all()
    return render_template("outreach.html", contacts=contacts, values=values,
                           error=error, draft=draft), status
