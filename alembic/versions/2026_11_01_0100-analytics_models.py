"""Tenant-isolated synthetic datasets and trained models."""
from alembic import op
from app.modelos.analitica import ConjuntoSintetico, EntrenamientoModelo

revision = 'a6b61101f001'
down_revision = 'f5b61028f001'
branch_labels = None
depends_on = None


def upgrade():
    ConjuntoSintetico.__table__.create(op.get_bind(), checkfirst=True)
    EntrenamientoModelo.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    EntrenamientoModelo.__table__.drop(op.get_bind(), checkfirst=True)
    ConjuntoSintetico.__table__.drop(op.get_bind(), checkfirst=True)
