"""Additive loyalty upgrade; existing issued coupons retain their conditions."""
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def update_connection(connection):
    op = Operations(MigrationContext.configure(connection))
    existing = {c['name'] for c in sa.inspect(connection).get_columns('loyalty_rewards')}
    columns = [sa.Column('reward_type', sa.String(20), nullable=False, server_default='COUPON'),
        sa.Column('points_cost', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('discount_percent', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('max_discount', sa.Numeric(10, 2), nullable=True, server_default='20'),
        sa.Column('reservation_id', sa.String(36), nullable=True),
        sa.Column('fulfilled_variant_id', sa.String(36), nullable=True),
        sa.Column('fulfilled_branch_id', sa.String(36), nullable=True),
        sa.Column('fulfilled_by', sa.String(36), nullable=True),
        sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True)]
    missing = [c for c in columns if c.name not in existing]
    if missing:
        with op.batch_alter_table('loyalty_rewards') as batch:
            for col in missing:
                batch.add_column(col)
            if 'reservation_id' not in existing:
                batch.create_unique_constraint('uq_reward_reservation', ['reservation_id'])
                batch.create_foreign_key('fk_reward_reservation', 'reservations', ['reservation_id'], ['id'])
            for col, table in [('fulfilled_variant_id','product_variants'),('fulfilled_branch_id','branches'),('fulfilled_by','users')]:
                if col not in existing:
                    batch.create_foreign_key('fk_reward_' + col, table, [col], ['id'])


def ensure_loyalty_schema(bind):
    if isinstance(bind, sa.engine.Connection):
        update_connection(bind)
    else:
        with bind.begin() as connection:
            update_connection(connection)
