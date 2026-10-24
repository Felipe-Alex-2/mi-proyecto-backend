"""Additive upgrade for AUTO_CREATE_TABLES installations, including SQLite."""
from sqlalchemy import inspect, text
from contextlib import nullcontext
from sqlalchemy.engine import Engine


def ensure_activity_scope_schema(engine):
    with (engine.begin() if isinstance(engine, Engine) else nullcontext(engine)) as conn:
        inspector = inspect(conn)
        if not inspector.has_table("activity_logs"):
            return
        columns = {column["name"] for column in inspector.get_columns("activity_logs")}
        if "branch_id" not in columns:
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN branch_id VARCHAR(36) REFERENCES branches(id) ON DELETE SET NULL"))
        if "branch_name" not in columns:
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN branch_name VARCHAR(255)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_activity_logs_branch_id ON activity_logs (branch_id)"))
