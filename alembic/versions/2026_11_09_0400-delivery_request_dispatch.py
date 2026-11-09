"""Delivery requests without upfront route quotes."""
from alembic import op
revision='1dd61109f004'
down_revision='0cc61108f003'
branch_labels=None
depends_on=None


def upgrade():
    from app.nucleo.esquema_delivery import ensure_delivery_schema
    ensure_delivery_schema(op.get_bind())


def downgrade():
    pass
