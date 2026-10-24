"""Preserve the allowed web origin used for a separate-tab subscription checkout."""
from alembic import op
from app.nucleo.esquema_saas import ensure_checkout_origin

revision = 'f5b61021f003'
down_revision = 'f5b61021f002'
branch_labels = None
depends_on = None


def upgrade():
    ensure_checkout_origin(op.get_bind())


def downgrade():
    pass
