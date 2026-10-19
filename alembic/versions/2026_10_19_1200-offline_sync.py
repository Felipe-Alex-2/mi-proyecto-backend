"""Idempotent receipts for the mobile outbox."""
from alembic import op
from app.models.sync_operation import SyncOperation

revision = 'd3b61019f001'
down_revision = 'c2a41013f001'
branch_labels = None
depends_on = None


def upgrade():
    SyncOperation.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    SyncOperation.__table__.drop(bind=op.get_bind(), checkfirst=True)
