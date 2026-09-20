"""
AI SDR Platform — Flask application factory.

Architecture note (see README.md for the full picture):
This backend is the shared data layer for an eight-agent SDR pipeline
(prospecting -> outreach -> reply/qualification -> call-prep -> booking ->
post-call logging, all orchestrated by a top-level agent, plus a learning-
loop feedback stage). Only the prospecting agent is implemented in this
prototype; the rest are stubbed as AgentRun records so the dashboard and
data model already reflect the target shape.
"""
import os
from flask import Flask
from dotenv import load_dotenv

from app.models import db

load_dotenv()


def create_app(config_overrides=None):
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///ai_sdr.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    app.config["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
    app.config["OPENAI_MODEL"] = os.environ.get("OPENAI_MODEL", "")

    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)

    from app.api import api_bp
    from app.dashboard import dashboard_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(dashboard_bp)
    from app.imports import imports_bp
    app.register_blueprint(imports_bp)
    from app.web_prospecting import web_bp
    app.register_blueprint(web_bp)
    from app.corrections import corrections_bp
    app.register_blueprint(corrections_bp)
    from app.services.legacy_task_links import register as register_task_link_commands
    register_task_link_commands(app)

    with app.app_context():
        db.create_all()
        from app.services.status_migration import upgrade
        upgrade(db.engine)

    return app
