"""Basic never expires; Professional costs USD 25 per 30 days."""
from alembic import op
from app.nucleo.politica_cobro_saas import ensure_billing_policy

revision = 'f5b61021f002'
down_revision = 'f5b61021f001'
branch_labels = None
depends_on = None


def upgrade():
    ensure_billing_policy(op.get_bind())


def downgrade():
    # A free plan must not acquire an artificial expiry on downgrade.
    pass
