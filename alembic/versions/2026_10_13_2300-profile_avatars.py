"""Persist profile photos and built-in avatar selection."""
from alembic import op
import sqlalchemy as sa

revision = 'c2a41013f001'
down_revision = '7b3c1e9a2d40'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('users')}
    if 'avatar_id' not in columns:
        op.add_column('users', sa.Column('avatar_id', sa.String(16), nullable=False, server_default='terracotta'))
    if 'profile_photo' not in columns:
        op.add_column('users', sa.Column('profile_photo', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('users', 'profile_photo')
    op.drop_column('users', 'avatar_id')
