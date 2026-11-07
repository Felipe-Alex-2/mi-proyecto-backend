"""CU19–CU23 commercial documents, loyalty ledger and delivery."""
from alembic import op
from app.modelos.aporte_propio import APORTE_TABLES

revision = 'b7b61106f001'
down_revision = 'a6b61101f001'
branch_labels = None
depends_on = None


def upgrade():
    for model in APORTE_TABLES:
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in reversed(APORTE_TABLES):
        model.__table__.drop(op.get_bind(), checkfirst=True)
