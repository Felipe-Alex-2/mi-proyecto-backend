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
        order_columns={c['name']:c for c in sa.inspect(connection).get_columns('delivery_orders')}
        for column in [sa.Column('destination_maps_url',sa.String(2048),nullable=True),
                       sa.Column('route_error',sa.Text(),nullable=True),
                       sa.Column('shipping_payment_id',sa.String(36),nullable=True)]:
            if column.name not in order_columns:operations.add_column('delivery_orders',column)
        if not order_columns['quote_id']['nullable']:
            if connection.dialect.name=='sqlite':
                with operations.batch_alter_table('delivery_orders') as batch:
                    batch.alter_column('quote_id',existing_type=sa.String(36),nullable=True)
            else:
                operations.alter_column('delivery_orders','quote_id',existing_type=sa.String(36),nullable=True)
        if connection.dialect.name=='postgresql' and not any(
            fk['constrained_columns']==['shipping_payment_id'] for fk in sa.inspect(connection).get_foreign_keys('delivery_orders')):
            operations.create_foreign_key('fk_delivery_shipping_payment','delivery_orders','payments',['shipping_payment_id'],['id'])
    if isinstance(bind,sa.engine.Connection):update(bind)
    else:
        with bind.begin() as connection:update(connection)
