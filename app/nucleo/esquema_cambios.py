"""Add receipt snapshots and reservation-backed exchanges without losing rows."""
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def update_connection(connection):
    inspector = sa.inspect(connection)
    operations = Operations(MigrationContext.configure(connection))
    if 'receipt_items_detail' not in {c['name'] for c in inspector.get_columns('reservations')}:
        operations.add_column('reservations', sa.Column('receipt_items_detail', sa.Text(), nullable=True))
    columns = {c['name']: c for c in sa.inspect(connection).get_columns('garment_exchanges')}
    if 'reservation_id' not in columns or not columns['payment_id']['nullable']:
        with operations.batch_alter_table('garment_exchanges') as batch:
            if 'reservation_id' not in columns:
                batch.add_column(sa.Column('reservation_id', sa.String(36), nullable=True))
                batch.create_foreign_key('fk_exchange_reservation', 'reservations', ['reservation_id'], ['id'])
                batch.create_index('ix_garment_exchanges_reservation_id', ['reservation_id'])
            if not columns['payment_id']['nullable']:
                batch.alter_column('payment_id', existing_type=sa.String(36), nullable=True)


def ensure_exchange_schema(bind):
    if isinstance(bind, sa.engine.Connection):
        update_connection(bind)
    else:
        with bind.begin() as connection:
            update_connection(connection)
