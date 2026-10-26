"""Idempotent upgrade of the existing single-company database, without data loss."""
from datetime import datetime, timezone
from sqlalchemy import inspect, select, text
from app.base_datos import Base
from app.modelos.saas import Empresa, Plan, Suscripcion, ClienteEmpresa, ROOT_TENANT_ID


def ensure_saas_schema(bind):
    if hasattr(bind, 'connect'):
        with bind.begin() as connection:
            _upgrade(connection)
    else:
        _upgrade(bind)


def _upgrade(conn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    # These tables do not depend on altered commercial columns.
    for model in (Empresa, Plan, Suscripcion):
        model.__table__.create(conn, checkfirst=True)
    ensure_company_department(conn)
    now = datetime.now(timezone.utc)
    if not conn.execute(select(Empresa.id).where(Empresa.id == ROOT_TENANT_ID)).first():
        conn.execute(Empresa.__table__.insert().values(id=ROOT_TENANT_ID, name='VESTA', slug='vesta', is_root=True, is_active=True, created_at=now))
    for code, name, limit, ai, price in [('BASIC', 'Básico', 2, False, 0), ('PRO', 'Profesional', 10, True, 25)]:
        if not conn.execute(select(Plan.code).where(Plan.code == code)).first():
            conn.execute(Plan.__table__.insert().values(code=code, name=name, branch_limit=limit,
                ai_reports=ai, price_usd=price, duration_days=30))
    from app.nucleo.politica_cobro_saas import ensure_billing_policy
    ensure_billing_policy(conn)
    if not conn.execute(select(Suscripcion.tenant_id).where(Suscripcion.tenant_id == ROOT_TENANT_ID)).first():
        conn.execute(Suscripcion.__table__.insert().values(tenant_id=ROOT_TENANT_ID, plan_code='PRO', status='ACTIVE', starts_at=now))
    tables = set(inspect(conn).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        columns = {c['name'] for c in inspect(conn).get_columns(table.name)}
        if 'tenant_id' in table.c and table.name not in ('users', 'saas_subscriptions', 'saas_subscription_payments', 'saas_customer_companies') and 'tenant_id' not in columns:
            conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN tenant_id VARCHAR(36) NOT NULL DEFAULT \'{ROOT_TENANT_ID}\''))
            conn.execute(text(f'CREATE INDEX ix_{table.name}_tenant_id ON "{table.name}" (tenant_id)'))
    user_columns = {c['name'] for c in inspect(conn).get_columns('users')}
    for name, definition in [('tenant_id', 'VARCHAR(36)'), ('selected_tenant_id', 'VARCHAR(36)'),
                             ('is_saas_admin', 'BOOLEAN NOT NULL DEFAULT FALSE')]:
        if name not in user_columns:
            conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {definition}'))
    conn.execute(text('UPDATE users SET tenant_id=:root WHERE role<>\'CUSTOMER\' AND tenant_id IS NULL'), {'root': ROOT_TENANT_ID})
    conn.execute(text('UPDATE users SET selected_tenant_id=:root WHERE selected_tenant_id IS NULL'), {'root': ROOT_TENANT_ID})
    # Promote an existing VESTA owner once. New company admins never receive this capability.
    if not conn.execute(text('SELECT id FROM users WHERE is_saas_admin=TRUE LIMIT 1')).first():
        owner = conn.execute(text("SELECT id FROM users WHERE role='ADMIN' AND tenant_id=:root ORDER BY CASE WHEN lower(email)='adminsas@gmail.com' THEN 0 ELSE 1 END, created_at LIMIT 1"), {'root':ROOT_TENANT_ID}).scalar()
        if owner:
            conn.execute(text('UPDATE users SET is_saas_admin=TRUE WHERE id=:id'), {'id':owner})
    if 'branch_id' not in {c['name'] for c in inspect(conn).get_columns('cart_items')}:
        conn.execute(text('ALTER TABLE cart_items ADD COLUMN branch_id VARCHAR(36)'))
    # Convert old globally unique catalog fields into company-scoped uniqueness.
    targets = {'categories':['tenant_id','name'], 'sizes':['tenant_id','code'],
               'colors':['tenant_id','name'], 'seasons':['tenant_id','name'],
               'suppliers':['tenant_id','company_name'], 'promotions':['tenant_id','name'],
               'product_variants':['tenant_id','sku'], 'branches':['tenant_id','name','city'],
               'cart_items':['tenant_id','user_id','variant_id','branch_id']}
    op = Operations(MigrationContext.configure(conn))
    for name, target in targets.items():
        inspector = inspect(conn)
        unique = inspector.get_unique_constraints(name)
        indexes = inspector.get_indexes(name)
        # Unique indexes and constraints are different objects in PostgreSQL.
        for index in indexes:
            if index.get('unique') and 'tenant_id' not in index['column_names'] and not index.get('duplicates_constraint'):
                op.drop_index(index['name'], table_name=name)
                op.create_index(index['name'], name, index['column_names'], unique=False)
        old = [u for u in unique if 'tenant_id' not in u['column_names'] and u['column_names'] != ['id']]
        exists = any(u['column_names'] == target for u in unique)
        if old or not exists:
            with op.batch_alter_table(name, naming_convention={'uq':'uq_%(table_name)s_%(column_0_name)s'}) as batch:
                for constraint in old:
                    batch.drop_constraint(constraint['name'] or f'uq_{name}_{constraint["column_names"][0]}', type_='unique')
                if not exists:
                    batch.create_unique_constraint(f'uq_{name}_company', target)
    # All other fresh tables can now be created safely.
    Base.metadata.create_all(conn)
    ensure_plan_catalog(conn)
    ensure_checkout_origin(conn)
    # Preserve the original customer/company relationship independently of selection.
    # PostgreSQL/psycopg cannot consistently infer a repeated untyped parameter
    # in both a SELECT projection and a VARCHAR comparison. Cast both uses to
    # the actual tenant_id type; SQLite accepts the same portable SQL.
    conn.execute(text('''INSERT INTO saas_customer_companies (user_id, tenant_id)
        SELECT id, CAST(:root AS VARCHAR(36)) FROM users WHERE role='CUSTOMER' AND NOT EXISTS
        (SELECT 1 FROM saas_customer_companies m WHERE m.user_id=users.id
         AND m.tenant_id=CAST(:root AS VARCHAR(36)))'''), {'root':ROOT_TENANT_ID})


def ensure_checkout_origin(conn):
    if 'return_origin' not in {column['name'] for column in inspect(conn).get_columns('saas_subscription_payments')}:
        conn.execute(text('ALTER TABLE saas_subscription_payments ADD COLUMN return_origin VARCHAR(500)'))


def ensure_plan_catalog(conn):
    """Add Max and identify the purchased plan on new and legacy receipts."""
    from app.modelos.saas import MAX_PRICE_USD
    if not conn.execute(select(Plan.code).where(Plan.code == 'MAX')).first():
        conn.execute(Plan.__table__.insert().values(code='MAX', name='Max', branch_limit=25,
            ai_reports=True, price_usd=MAX_PRICE_USD, duration_days=30))
    columns = {c['name'] for c in inspect(conn).get_columns('saas_subscription_payments')}
    if 'plan_code' not in columns:
        conn.execute(text("ALTER TABLE saas_subscription_payments ADD COLUMN plan_code VARCHAR(20) NOT NULL DEFAULT 'PRO'"))
    if 'plan_name' not in columns:
        conn.execute(text('ALTER TABLE saas_subscription_payments ADD COLUMN plan_name VARCHAR(80)'))


def ensure_company_department(conn):
    if 'department' not in {column['name'] for column in inspect(conn).get_columns('tenants')}:
        conn.execute(text('ALTER TABLE tenants ADD COLUMN department VARCHAR(30)'))
