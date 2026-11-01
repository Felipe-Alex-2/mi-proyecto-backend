"""Account-owned favorites for the client storefront."""
from alembic import op
from app.modelos.favorito import Favorito

revision = 'f5b61028f001'
down_revision = 'f5b61024f001'
branch_labels = None
depends_on = None


def upgrade():
    Favorito.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    Favorito.__table__.drop(op.get_bind(), checkfirst=True)
