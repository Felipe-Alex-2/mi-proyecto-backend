"""Reservation receipts and a 48-hour exchange policy."""
from alembic import op
import sqlalchemy as sa
from app.nucleo.esquema_cambios import ensure_exchange_schema

revision = 'c8b61107f001'
down_revision = 'b7b61106f001'
branch_labels = None
depends_on = None


def upgrade():
    ensure_exchange_schema(op.get_bind())


def downgrade():
    # Reservation-backed exchanges must be retained; never silently delete them.
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT count(*) FROM garment_exchanges WHERE payment_id IS NULL')).scalar():
        raise RuntimeError('Existen cambios de reservas sin cobro original. Exporta y revisa los datos antes de revertir esta migración.')
    fks = [fk for fk in sa.inspect(bind).get_foreign_keys('garment_exchanges') if fk['constrained_columns'] == ['reservation_id']]
    naming = {'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}
    with op.batch_alter_table('garment_exchanges', naming_convention=naming) as batch:
        for fk in fks:
            batch.drop_constraint(fk['name'] or 'fk_garment_exchanges_reservation_id_reservations', type_='foreignkey')
        batch.drop_index('ix_garment_exchanges_reservation_id')
        batch.drop_column('reservation_id')
        batch.alter_column('payment_id', existing_type=sa.String(36), nullable=False)
    op.drop_column('reservations', 'receipt_items_detail')
