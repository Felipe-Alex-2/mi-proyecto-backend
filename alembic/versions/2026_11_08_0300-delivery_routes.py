"""Branch Maps origins and routed delivery requests."""
from alembic import op
revision='0cc61108f003'
down_revision='fbb61108f002'
branch_labels=None
depends_on=None


def upgrade():
    from app.nucleo.esquema_delivery import ensure_delivery_schema
    ensure_delivery_schema(op.get_bind())


def downgrade():
    pass
