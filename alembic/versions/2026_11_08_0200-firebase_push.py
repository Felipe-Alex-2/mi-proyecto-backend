"""FCM devices and transactional outbox."""
from alembic import op
revision='fbb61108f002'
down_revision='eab61108f001'
branch_labels=None
depends_on=None

def upgrade():
    from app.modelos.push import DispositivoPush,EnvioPush
    for model in (DispositivoPush,EnvioPush):model.__table__.create(op.get_bind(),checkfirst=True)

def downgrade():
    pass
