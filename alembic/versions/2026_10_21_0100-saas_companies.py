"""Companies, configurable plans, subscriptions and company-scoped resources.

Existing records are retained under VESTA. Run against an initialized project
database; fresh installations can use AUTO_CREATE_TABLES=true.
"""
from alembic import op
from app.nucleo.esquema_saas import ensure_saas_schema

revision = 'f5b61021f001'
down_revision = 'e4b61020f001'
branch_labels = None
depends_on = None


def upgrade():
    ensure_saas_schema(op.get_bind())


def downgrade():
    raise RuntimeError('A multi-company database cannot be flattened safely. Restore the pre-SaaS backup explicitly.')
