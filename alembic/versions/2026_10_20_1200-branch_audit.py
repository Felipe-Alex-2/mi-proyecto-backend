"""Sucursal context for business audit events."""
from alembic import op
from app.nucleo.esquema_bitacora import ensure_activity_scope_schema

revision = 'e4b61020f001'
down_revision = 'd3b61019f001'
branch_labels = None
depends_on = None


def upgrade():
    ensure_activity_scope_schema(op.get_bind())


def downgrade():
    with op.batch_alter_table('activity_logs') as batch:
        batch.drop_index('ix_activity_logs_branch_id')
        batch.drop_column('branch_name')
        batch.drop_column('branch_id')
