"""Insert-only restoration of reviewed, company-scoped business records."""
import gzip
import hashlib
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from app.base_datos import Base
from app.nucleo.seguridad import create_access_token, decode_token
from app.modelos.saas import Empresa, ClienteEmpresa, Suscripcion, Plan
from app.modelos.usuario import Usuario
from app.servicios.saas_service import enforce_subscription
from app.servicios.respaldo_service import _encode

MAX_BYTES = 32 * 1024 * 1024
RESTORABLE = {'branches', 'categories', 'sizes', 'colors', 'seasons', 'suppliers',
    'promotions', 'products', 'product_variants', 'stocks', 'inventory_movements',
    'reservations', 'reservation_items', 'payments', 'cart_items', 'size_guides', 'activity_logs'}
INFORMATION_ONLY = {'users', 'tenants', 'saas_plans', 'saas_subscriptions',
                    'saas_subscription_payments', 'saas_customer_companies'}
BUSINESS_KEYS = {'products': [('tenant_id', 'name')]}


def parse_backup(content):
    try:
        if content.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, 'El respaldo supera el máximo de 32 MB sin comprimir.')
        def unique_object(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError('Claves repetidas')
                obj[key] = value
            return obj
        payload = json.loads(content.decode('utf-8-sig'), object_pairs_hook=unique_object)
        if not isinstance(payload, dict) or payload.get('format') != 'VESTA_COMPANY_BACKUP' or payload.get('version') != 1:
            raise ValueError('Formato no reconocido')
        uuid.UUID(payload['tenant_id'])
        datetime.fromisoformat(payload['created_at'])
        tables = payload['tables']
        if not isinstance(tables, dict) or len(tables) > 50:
            raise ValueError('Tablas inválidas')
        total = 0
        for name, rows in tables.items():
            if name not in RESTORABLE | INFORMATION_ONLY or not isinstance(rows, list):
                raise ValueError('Tabla no admitida')
            total += len(rows)
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError('Registro inválido')
            for row in rows:
                if 'tenant_id' in row and row['tenant_id'] not in (payload['tenant_id'], None):
                    raise ValueError('El respaldo mezcla empresas')
                if any('password' in key.lower() or 'secret' in key.lower() for key in row):
                    raise ValueError('El respaldo contiene credenciales no admitidas')
        if total > 200000:
            raise HTTPException(413, 'El respaldo supera los 200.000 registros por carga.')
        return payload, hashlib.sha256(content).hexdigest()
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, OSError, EOFError, RecursionError) as error:
        raise HTTPException(422, 'Archivo inválido. Selecciona un respaldo JSON de VESTA o una copia anterior .json.gz.') from error


def normalized(value):
    return value.strip().casefold() if isinstance(value, str) else value


def convert_row(table, original, tenant_id):
    if original.get('tenant_id') != tenant_id or set(original) - set(table.c.keys()):
        raise HTTPException(422, f'Registro inválido o de otra empresa en {table.name}.')
    row = dict(original)
    try:
        for column in table.c:
            if column.name not in row:
                if not column.nullable and column.default is None and column.server_default is None:
                    raise ValueError('Falta un campo obligatorio')
                continue
            value = row[column.name]
            if value is None:
                if not column.nullable:
                    raise ValueError('Campo obligatorio vacío')
            elif isinstance(column.type, Boolean):
                if not isinstance(value, bool): raise ValueError('Booleano inválido')
            elif isinstance(column.type, DateTime):
                row[column.name] = datetime.fromisoformat(value)
            elif isinstance(column.type, Date):
                row[column.name] = date.fromisoformat(value)
            elif isinstance(column.type, Integer):
                if not isinstance(value, int) or isinstance(value, bool): raise ValueError('Entero inválido')
            elif isinstance(column.type, Numeric):
                row[column.name] = Decimal(str(value))
                if not row[column.name].is_finite(): raise ValueError('Importe inválido')
                if column.type.precision and abs(row[column.name]) >= Decimal(10) ** (column.type.precision - (column.type.scale or 0)):
                    raise ValueError('Importe demasiado grande')
            elif isinstance(column.type, String):
                if not isinstance(value, str) or (column.type.length and len(value) > column.type.length):
                    raise ValueError('Texto inválido')
                if not column.nullable and not value.strip(): raise ValueError('Texto obligatorio vacío')
        for column in table.primary_key:
            if not row.get(column.name): raise ValueError('Identificador vacío')
        for name in ('quantity', 'min_alert_threshold', 'previous_stock', 'new_stock', 'price', 'price_override', 'amount'):
            if row.get(name) is not None and row[name] < 0: raise ValueError('Cantidad negativa')
    except (ValueError, TypeError, InvalidOperation) as error:
        raise HTTPException(422, f'Hay un registro con datos inválidos en {table.name}.') from error
    return row


def build_plan(db, tenant_id, payload):
    if payload['tenant_id'] != tenant_id:
        raise HTTPException(403, 'El respaldo pertenece a otra empresa. Selecciona su empresa original.')
    conn = db.connection()
    company = conn.execute(select(Empresa.__table__).where(Empresa.id == tenant_id)).mappings().one()
    tables = {table.name: table for table in Base.metadata.sorted_tables if table.name in RESTORABLE}
    available, existing, indexes, constraints = {}, {}, {}, {}
    for name, table in tables.items():
        keys = [tuple(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)]
        keys += [(column.name,) for column in table.c if column.unique]
        keys += BUSINESS_KEYS.get(name, [])
        constraints[name] = list(dict.fromkeys(keys))
        needed = set(['id', 'tenant_id']) | {key for group in keys for key in group}
        records = conn.execute(select(*(table.c[key] for key in needed)).where(table.c.tenant_id == tenant_id)).mappings().all()
        existing[name] = {record['id']: record for record in records}
        available[name] = set(existing[name])
        indexes[name] = {key: {tuple(normalized(record[k]) for k in key): record['id'] for record in records if all(record[k] is not None for k in key)} for key in constraints[name]}
    users = Usuario.__table__
    members = select(ClienteEmpresa.user_id).where(ClienteEmpresa.tenant_id == tenant_id)
    available['users'] = set(conn.execute(select(users.c.id).where((users.c.tenant_id == tenant_id) | users.c.id.in_(members))).scalars())
    available['tenants'] = {tenant_id}
    remap, inserts, summary, issues = {}, [], [], []
    active_branches = conn.execute(select(Base.metadata.tables['branches'].c.id).where(
        Base.metadata.tables['branches'].c.tenant_id == tenant_id, Base.metadata.tables['branches'].c.is_active == True)).all()
    sub = conn.execute(select(Suscripcion.__table__).where(Suscripcion.tenant_id == tenant_id)).mappings().first()
    limit = conn.execute(select(Plan.branch_limit).where(Plan.code == sub['plan_code'])).scalar() if sub else 0
    active_count = len(active_branches)
    for name, rows in payload['tables'].items():
        if name not in tables:
            summary.append(dict(table=name, total=len(rows), missing=0, existing=0, skipped=len(rows), information_only=True))
    for name, table in tables.items():
        original_rows = payload['tables'].get(name, [])
        if not original_rows: continue
        count = dict(table=name, total=len(original_rows), missing=0, existing=0, skipped=0, information_only=False)
        seen = set()
        for raw in original_rows:
            row = convert_row(table, raw, tenant_id)
            identifier = row['id']
            if identifier in seen:
                count['skipped'] += 1
                if len(issues) < 30: issues.append(dict(table=name, name=raw.get('name') or identifier, reason='Identificador repetido dentro del archivo.'))
                continue
            seen.add(identifier)
            if identifier in existing[name]:
                remap[(name, identifier)] = identifier
                count['existing'] += 1
                continue
            # Never reassign an identifier already owned by another company.
            if conn.execute(select(table.c.id).where(table.c.id == identifier, table.c.tenant_id != tenant_id)).first():
                raise HTTPException(422, 'El archivo contiene identificadores incompatibles con la empresa seleccionada.')
            valid = True
            for column in table.c:
                if row.get(column.name) is None: continue
                for foreign in column.foreign_keys:
                    target = foreign.column.table.name
                    value = remap.get((target, row[column.name]), row[column.name])
                    row[column.name] = value
                    if value not in available.get(target, set()): valid = False
            matches = set()
            for key, index in indexes[name].items():
                signature = tuple(normalized(row.get(k)) for k in key)
                if all(value is not None for value in signature) and signature in index: matches.add(index[signature])
            if len(matches) == 1 and valid:
                remap[(name, identifier)] = matches.pop()
                count['existing'] += 1
                continue
            reason = None
            if not valid: reason = 'Falta un registro relacionado o no pertenece a esta empresa.'
            elif len(matches) > 1: reason = 'Hay coincidencias distintas para sus claves únicas; requiere revisión.'
            elif name == 'branches' and row.get('is_active', True) and not company['is_root'] and active_count >= limit:
                reason = 'La recuperación de esta sucursal excede el límite del plan actual.'
            if not reason and name == 'branches' and company['department']:
                from app.nucleo.ubicaciones_bolivia import municipality_name
                try:
                    row['city'] = municipality_name(company['department'], row['city'])
                except HTTPException:
                    reason = 'La ciudad/municipio no corresponde al departamento actual de la empresa.'
            if reason:
                count['skipped'] += 1
                if len(issues) < 30: issues.append(dict(table=name, name=raw.get('name') or raw.get('company_name') or identifier, reason=reason))
                continue
            inserts.append((name, row))
            count['missing'] += 1
            available[name].add(identifier)
            remap[(name, identifier)] = identifier
            for key, index in indexes[name].items():
                signature = tuple(normalized(row.get(k)) for k in key)
                if all(value is not None for value in signature): index[signature] = identifier
            if name == 'branches' and row.get('is_active', True): active_count += 1
        summary.append(count)
    public = dict(company_id=tenant_id, company_name=company['name'], created_at=payload['created_at'],
        tables=summary, missing=sum(r['missing'] for r in summary), existing=sum(r['existing'] for r in summary),
        skipped=sum(r['skipped'] for r in summary), issues=issues)
    for row in summary:
        row['examples'] = [next((str(item[key]) for key in ('name', 'company_name', 'sku', 'payment_code', 'reservation_code', 'full_name', 'id') if isinstance(item.get(key), str)), 'Registro')
                           for item in payload['tables'][row['table']][:5]]
    digest = hashlib.sha256(json.dumps({'summary': public, 'inserts': inserts}, sort_keys=True, default=_encode).encode()).hexdigest()
    return public, inserts, digest


def preview_backup(db, tenant_id, user, payload, file_hash):
    public, _, digest = build_plan(db, tenant_id, payload)
    public['review_token'] = create_access_token(user.id, timedelta(minutes=15), {
        'type': 'backup_restore_review', 'tenant_id': tenant_id, 'file_hash': file_hash, 'plan_hash': digest})
    return public


def restore_backup(db, tenant_id, user, payload, file_hash, token):
    claims = decode_token(token)
    if not claims or claims.get('type') != 'backup_restore_review' or claims.get('sub') != user.id or claims.get('tenant_id') != tenant_id or claims.get('file_hash') != file_hash:
        raise HTTPException(409, 'La revisión venció o cambió el archivo. Vuelve a analizarlo antes de restaurar.')
    # Same company lock used by branch creation; serialize concurrent restorations.
    db.query(Empresa).filter(Empresa.id == tenant_id).with_for_update().first()
    enforce_subscription(db, tenant_id, write=True)
    public, inserts, digest = build_plan(db, tenant_id, payload)
    if digest != claims.get('plan_hash'):
        raise HTTPException(409, 'Los datos cambiaron desde la revisión. Analiza el archivo otra vez para ver los faltantes actuales.')
    try:
        conn = db.connection()
        # Bounded batches retain dependency order and avoid a roundtrip per record.
        for offset in range(0, len(inserts), 100):
            batch = inserts[offset:offset + 100]
            groups = []
            for name, row in batch:
                if groups and groups[-1][0] == name and groups[-1][1][0].keys() == row.keys():
                    groups[-1][1].append(row)
                else:
                    groups.append((name, [row]))
            for name, rows in groups:
                conn.execute(Base.metadata.tables[name].insert(), rows)
        if inserts:
            conn.execute(Base.metadata.tables['activity_logs'].insert().values(
                id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user.id, user_email=user.email,
                user_name=user.full_name, action='CREAR_RESTAURACION_BACKUP', category='ADMINISTRACION',
                description=f'Restauración de respaldo: {len(inserts)} registros faltantes recuperados.'))
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, 'Se detectó una coincidencia o dependencia incompatible. No se cargó ningún registro; vuelve a analizar el archivo.') from error
    except Exception:
        db.rollback()
        raise
    return {**public, 'restored': len(inserts)}
