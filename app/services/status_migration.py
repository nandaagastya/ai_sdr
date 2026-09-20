"""Versioned, additive status migration. Never deletes or reseeds records."""
from datetime import datetime
from pathlib import Path
import sqlite3
from sqlalchemy import inspect, text

VERSION = '001_separate_fit_and_progress'


def upgrade(engine):
    inspector = inspect(engine)
    columns = {table: {c['name'] for c in inspector.get_columns(table)}
               for table in ('accounts', 'contacts')}
    additions = [('accounts', 'fit_status', "VARCHAR(30) DEFAULT 'unassessed'"),
                 ('accounts', 'legacy_stage', 'VARCHAR(50)'),
                 ('contacts', 'pipeline_stage', "VARCHAR(30) DEFAULT 'not_contacted'")]
    missing = [(t, c, definition) for t, c, definition in additions if c not in columns[t]]
    # A file-backed SQLite database gets a consistent backup before any ALTER.
    database = engine.url.database
    if missing and engine.dialect.name == 'sqlite' and database and database != ':memory:':
        source = Path(database)
        backup = source.with_name(source.name + '.before-status-' + datetime.utcnow().strftime('%Y%m%d%H%M%S%f') + '.bak')
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(backup)) as dst:
            src.backup(dst)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS schema_versions (version VARCHAR(100) PRIMARY KEY)'))
        if connection.execute(text('SELECT version FROM schema_versions WHERE version=:v'), {'v': VERSION}).first():
            return
        for table, column, definition in missing:
            connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))
        connection.execute(text("UPDATE accounts SET legacy_stage=stage WHERE legacy_stage IS NULL"))
        connection.execute(text("""UPDATE accounts SET fit_status=CASE
            WHEN icp_fit_score >= 60 THEN 'strong_fit'
            WHEN icp_fit_reasons IS NOT NULL AND icp_fit_reasons <> '' AND icp_fit_score > 0 THEN 'possible_fit'
            WHEN icp_fit_reasons IS NOT NULL AND icp_fit_reasons <> '' AND icp_fit_score = 0 THEN 'low_fit'
            ELSE 'unassessed' END"""))
        # Company history cannot establish which individual was contacted.
        connection.execute(text("""UPDATE contacts SET pipeline_stage='needs_review'
            WHERE account_id IN (SELECT id FROM accounts WHERE stage NOT IN ('new','qualified'))"""))
        connection.execute(text("UPDATE accounts SET stage='new' WHERE stage='qualified'"))
        connection.execute(text('INSERT INTO schema_versions(version) VALUES (:v)'), {'v': VERSION})
