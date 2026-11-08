"""Tiered loyalty rewards and in-person mystery redemption."""
from alembic import op
revision = 'd9b61107f002'
down_revision = 'c8b61107f001'
branch_labels = None
depends_on = None

def upgrade():
    from app.nucleo.esquema_puntos import update_connection
    update_connection(op.get_bind())

def downgrade():
    # Rewards are commercial records: retain data on downgrade.
    pass
