"""Add branch pins and reservation-backed delivery without changing historical deliveries."""
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def ensure_delivery_schema(bind):
    def update(connection):
        columns={c['name'] for c in sa.inspect(connection).get_columns('branches')}
        operations=Operations(MigrationContext.configure(connection))
        for column in [sa.Column('maps_url',sa.String(2048),nullable=True),sa.Column('latitude',sa.Numeric(10,7),nullable=True),sa.Column('longitude',sa.Numeric(10,7),nullable=True)]:
            if column.name not in columns:operations.add_column('branches',column)
        if 'delivery_fee' not in {c['name'] for c in sa.inspect(connection).get_columns('reservations')}:
            operations.add_column('reservations',sa.Column('delivery_fee',sa.Numeric(10,2),nullable=False,server_default='0'))
        from app.modelos.delivery import CotizacionDelivery,PedidoDelivery
        for model in (CotizacionDelivery,PedidoDelivery):model.__table__.create(connection,checkfirst=True)
    if isinstance(bind,sa.engine.Connection):update(bind)
    else:
        with bind.begin() as connection:update(connection)
