"""
Shared data layer for the AI SDR agent stack.

Five models, shared by every agent in the pipeline (prospecting today;
outreach / reply-qualification / call-prep / booking / post-call-logging
planned — see README.md):

- Account   : a company (the org-level ICP target)
- Contact   : a person at an Account (the outreach target)
- Activity  : a logged interaction (email sent, reply, call, etc.)
- Task      : a follow-up action, human- or agent-owned
- AgentRun  : an audit record of one execution of one agent in the stack
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    domain = db.Column(db.String(255), unique=True, nullable=True)
    industry = db.Column(db.String(120), nullable=True)
    employee_count = db.Column(db.Integer, nullable=True)
    location = db.Column(db.String(255), nullable=True)

    # Rules-based ICP fit score, 0-100 (see app/agents/prospecting.py::score_icp_fit)
    icp_fit_score = db.Column(db.Integer, default=0)
    icp_fit_reasons = db.Column(db.Text, nullable=True)  # human-readable, comma-joined

    stage = db.Column(
        db.String(50), default="new"
    )  # new -> qualified -> outreach -> replied -> booked -> closed
    fit_status = db.Column(db.String(30), default='unassessed')
    legacy_stage = db.Column(db.String(50), nullable=True)
    source = db.Column(db.String(50), default="apollo")  # apollo | web_scrape | manual

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contacts = db.relationship("Contact", backref="account", lazy=True, cascade="all, delete-orphan")
    activities = db.relationship("Activity", backref="account", lazy=True, cascade="all, delete-orphan")
    tasks = db.relationship("Task", backref="account", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "employee_count": self.employee_count,
            "location": self.location,
            "icp_fit_score": self.icp_fit_score,
            "icp_fit_reasons": self.icp_fit_reasons.split(" | ") if self.icp_fit_reasons else [],
            "stage": self.stage,
            "fit_status": self.fit_status,
            "legacy_stage": self.legacy_stage,
            "source": self.source,
            "contact_count": len(self.contacts),
            "created_at": self.created_at.isoformat(),
        }


class Contact(db.Model):
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)

    first_name = db.Column(db.String(120), nullable=True)
    last_name = db.Column(db.String(120), nullable=True)
    title = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    linkedin_url = db.Column(db.String(500), nullable=True)

    pipeline_stage = db.Column(db.String(30), default='not_contacted')
    is_decision_maker = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def email_kind(self):
        local = (self.email or '').split('@')[0].lower()
        if not local:
            return 'Email missing'
        if local in {'info', 'hello', 'contact', 'sales', 'support', 'admin', 'office', 'enquiries', 'inquiries', 'team'}:
            return 'Likely shared inbox · unverified'
        return 'Email unverified'

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "name": f"{self.first_name or ''} {self.last_name or ''}".strip(),
            "title": self.title,
            "email": self.email,
            "linkedin_url": self.linkedin_url,
            "is_decision_maker": self.is_decision_maker,
            "pipeline_stage": self.pipeline_stage,
            "email_kind": self.email_kind,
        }


class Activity(db.Model):
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=True)

    activity_type = db.Column(db.String(50), nullable=False)  # email_sent | reply | call | note
    channel = db.Column(db.String(50), nullable=True)  # email | linkedin | phone
    summary = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "contact_id": self.contact_id,
            "activity_type": self.activity_type,
            "channel": self.channel,
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
        }


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)

    description = db.Column(db.String(500), nullable=False)
    owner = db.Column(db.String(50), default="agent")  # agent | human
    status = db.Column(db.String(50), default="open")  # open | done | skipped
    due_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "description": self.description,
            "owner": self.owner,
            "status": self.status,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "created_at": self.created_at.isoformat(),
        }


class AgentRun(db.Model):
    __tablename__ = "agent_runs"

    id = db.Column(db.Integer, primary_key=True)

    # One of the eight agents in the target stack:
    # orchestrator | prospecting | outreach | reply_qualification |
    # call_prep | booking | post_call_logging | learning_loop
    agent_name = db.Column(db.String(50), nullable=False)

    status = db.Column(db.String(50), default="running")  # running | success | error
    records_processed = db.Column(db.Integer, default=0)
    detail = db.Column(db.Text, nullable=True)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "status": self.status,
            "records_processed": self.records_processed,
            "detail": self.detail,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class LeadImport(db.Model):
    """Session-owned staging record; contacts are created only on confirmation."""
    __tablename__ = 'lead_imports'
    id = db.Column(db.String(32), primary_key=True)
    owner = db.Column(db.String(64), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='uploaded')
    data = db.Column(db.Text, nullable=False)
    result = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ProspectCache(db.Model):
    __tablename__ = 'prospect_cache'
    key = db.Column(db.String(64), primary_key=True)
    provider = db.Column(db.String(20), nullable=False)
    result = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)


class WebDiscovery(db.Model):
    __tablename__ = 'web_discoveries'
    id = db.Column(db.String(32), primary_key=True)
    owner = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='review')
    data = db.Column(db.Text, nullable=False)
    result = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DeliverySimulation(db.Model):
    """Local fake-provider receipt; never represents an actual email send."""
    __tablename__ = 'delivery_simulations'
    id = db.Column(db.Integer, primary_key=True)
    preview_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    touch = db.Column(db.Integer, nullable=False, default=1)
    provider_id = db.Column(db.String(100), nullable=False)
    snapshot = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('preview_id', 'revision', 'touch'),)


class OutreachStop(db.Model):
    __tablename__ = 'outreach_stops'
    email = db.Column(db.String(255), primary_key=True)
    reason = db.Column(db.String(30), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecordedReply(db.Model):
    __tablename__ = 'recorded_replies'
    fingerprint = db.Column(db.String(64), primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False)
    outcome = db.Column(db.String(30), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False)


class Qualification(db.Model):
    __tablename__ = 'qualifications'
    reply_id = db.Column(db.Integer, db.ForeignKey('activities.id'), primary_key=True)
    evidence = db.Column(db.Text, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    qualified = db.Column(db.Boolean, nullable=False, default=False)


class CallBrief(db.Model):
    __tablename__ = 'call_briefs'
    reply_id = db.Column(db.Integer, db.ForeignKey('activities.id'), primary_key=True)
    snapshot = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Meeting(db.Model):
    __tablename__ = 'meetings'
    reply_id = db.Column(db.Integer, db.ForeignKey('call_briefs.reply_id'), primary_key=True)
    starts_at = db.Column(db.DateTime, nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    confirmation_note = db.Column(db.Text, nullable=False)


class MeetingChange(db.Model):
    __tablename__ = 'meeting_changes'
    id = db.Column(db.Integer, primary_key=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('meetings.reply_id'), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(20), nullable=False)
    detail = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('reply_id','revision'),)


    @property
    def details(self):
        import json
        return json.loads(self.detail)


class CallOutcome(db.Model):
    __tablename__ = 'call_outcomes'
    reply_id = db.Column(db.Integer, db.ForeignKey('meetings.reply_id'), primary_key=True)
    outcome = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    next_step = db.Column(db.Text, nullable=False)
    follow_up_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WorkflowTask(db.Model):
    """Explicit source of a generated task; descriptions remain editable prose."""
    __tablename__ = 'workflow_tasks'
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), primary_key=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    __table_args__ = (db.CheckConstraint(
        "kind IN ('reply_review','brief_review','meeting','cancellation','follow_up','correction_review')",
        name='workflow_task_kind'),)


class RecordCorrection(db.Model):
    """Append-only before/after history. Reviewer is manually asserted until auth exists."""
    __tablename__ = 'record_corrections'
    id = db.Column(db.Integer, primary_key=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False, index=True)
    entity = db.Column(db.String(30), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    reviewer = db.Column(db.String(120), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    before = db.Column(db.Text, nullable=False)
    after = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('reply_id', 'entity', 'revision'),
        db.CheckConstraint("entity IN ('qualification','call_outcome')", name='correction_entity'),
    )
