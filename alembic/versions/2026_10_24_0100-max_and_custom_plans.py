"""Max plan and purchased-plan identity on subscription receipts."""
from alembic import op
from app.nucleo.esquema_saas import ensure_plan_catalog

revision = 'f5b61024f001'
down_revision = 'f5b61023f001'
branch_labels = None
depends_on = None


def upgrade():
    ensure_plan_catalog(op.get_bind())


def downgrade():
    pass
