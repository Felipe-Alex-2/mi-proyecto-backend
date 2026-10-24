"""Add company department without guessing locations of existing companies."""
from alembic import op
from app.nucleo.esquema_saas import ensure_company_department

revision = 'f5b61023f001'
down_revision = 'f5b61021f003'
branch_labels = None
depends_on = None


def upgrade():
    ensure_company_department(op.get_bind())


def downgrade():
    pass
