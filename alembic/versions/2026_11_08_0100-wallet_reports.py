"""Wallet and report snapshots."""
from alembic import op
revision='eab61108f001'
down_revision='d9b61107f002'
branch_labels=None
depends_on=None

def upgrade():
    from app.modelos.wallet import CuentaWallet,RecargaWallet,MovimientoWallet
    from app.modelos.reporte_guardado import ReporteGuardado
    for model in (CuentaWallet,RecargaWallet,MovimientoWallet,ReporteGuardado):
        model.__table__.create(op.get_bind(),checkfirst=True)

def downgrade():
    # Financial ledger and delivered report records must not be silently deleted.
    pass
