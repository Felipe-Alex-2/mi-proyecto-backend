"""Private, company-scoped data exports with a daily server-side scheduler."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import gzip
import hashlib
import json
import logging
from pathlib import Path
import threading
import uuid
from sqlalchemy import select, or_, and_, text
from app.configuracion import settings
from app.base_datos import Base, engine
from app.modelos.saas import Empresa, ClienteEmpresa, Suscripcion, Plan
from app.modelos.usuario import Usuario

logger = logging.getLogger('backups')
LA_PAZ = timezone(timedelta(hours=-4))
_locks = {}
_guard = threading.Lock()


def backup_root():
    path = Path(settings.BACKUP_DIR)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path.resolve()


def company_folder(tenant_id):
    return backup_root() / str(uuid.UUID(str(tenant_id)))


def list_backups(tenant_id):
    folder = company_folder(tenant_id)
    if not folder.exists():
        return []
    results = []
    for path in folder.glob('*.json'):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            if row['tenant_id'] == tenant_id and (folder / (row['id'] + '.json.gz')).is_file():
                results.append(row)
        except (OSError, ValueError, KeyError):
            logger.warning('Incomplete backup metadata ignored')
    return sorted(results, key=lambda row: row['created_at'], reverse=True)


def _encode(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def create_backup(tenant_id, kind='MANUAL', bind=None):
    bind = bind or engine
    tenant_id = str(uuid.UUID(str(tenant_id)))
    with _guard:
        lock = _locks.setdefault(tenant_id, threading.Lock())
    with lock, bind.connect() as conn:
        if conn.dialect.name == 'postgresql':
            conn = conn.execution_options(isolation_level='REPEATABLE READ')
            conn.begin()
            key = int.from_bytes(hashlib.sha256(tenant_id.encode()).digest()[:8], 'big', signed=True)
            conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':key})
        else:
            conn.exec_driver_sql('BEGIN')
        try:
            now = datetime.now(timezone.utc)
            if kind == 'AUTO':
                today = now.astimezone(LA_PAZ).date()
                previous = next((row for row in list_backups(tenant_id) if row['kind']=='AUTO'), None)
                if previous and datetime.fromisoformat(previous['created_at']).astimezone(LA_PAZ).date() == today:
                    return previous
            company = conn.execute(select(Empresa.__table__).where(Empresa.id == tenant_id)).mappings().first()
            if not company:
                raise ValueError('Empresa no encontrada')
            tables = {}
            # Core SQL bypasses ORM context deliberately: each table has an explicit
            # company predicate, including the global customer membership mapping.
            for table in Base.metadata.sorted_tables:
                if 'tenant_id' not in table.c or table.name == 'users':
                    continue
                rows = conn.execute(select(table).where(table.c.tenant_id == tenant_id)).mappings().all()
                tables[table.name] = [dict(row) for row in rows]
            members = select(ClienteEmpresa.user_id).where(ClienteEmpresa.tenant_id == tenant_id)
            columns = [Usuario.__table__.c[name] for name in ('id','email','full_name','phone','role','branch_id','tenant_id','is_active','is_verified','created_at')]
            users = conn.execute(select(*columns).where(or_(Usuario.tenant_id == tenant_id, and_(Usuario.role=='CUSTOMER',Usuario.id.in_(members))))).mappings().all()
            tables['users'] = [dict(row, branch_id=row['branch_id'] if row['tenant_id']==tenant_id else None) for row in users]
            sub = conn.execute(select(Suscripcion.plan_code).where(Suscripcion.tenant_id==tenant_id)).scalar()
            tables['saas_plans'] = [dict(row) for row in conn.execute(select(Plan.__table__).where(Plan.code==sub)).mappings()]
            tables['tenants'] = [dict(company)]
            identifier = str(uuid.uuid4())
            payload = {'format':'VESTA_COMPANY_BACKUP','version':1,'tenant_id':tenant_id,
                       'created_at':now.isoformat(),'tables':tables}
            plain_content = json.dumps(payload, ensure_ascii=False, default=_encode).encode('utf-8')
            content = gzip.compress(plain_content, mtime=0)
            manifest = {'id':identifier,'tenant_id':tenant_id,'company_name':company['name'],'created_at':now.isoformat(),
                        'kind':kind,'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),
                        'download_size_bytes':len(plain_content),'download_sha256':hashlib.sha256(plain_content).hexdigest(),
                        'records':sum(len(rows) for rows in tables.values()),'tables':{name:len(rows) for name,rows in tables.items()}}
            folder = company_folder(tenant_id)
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / (identifier + '.tmp')
            temporary.write_bytes(content)
            temporary.replace(folder / (identifier + '.json.gz'))
            metadata = folder / (identifier + '.meta.tmp')
            metadata.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
            metadata.replace(folder / (identifier + '.json'))
            return manifest
        finally:
            conn.rollback()


def daily_all(bind=None):
    bind = bind or engine
    with bind.connect() as conn:
        tenants = list(conn.execute(select(Empresa.id)).scalars())
    for tenant_id in tenants:
        try:
            create_backup(tenant_id, 'AUTO', bind)
        except Exception:
            logger.exception('Daily company backup failed for %s', tenant_id)


@asynccontextmanager
async def backup_schedule():
    if not settings.BACKUPS_ENABLED:
        yield
        return
    async def worker():
        while True:
            try:
                await asyncio.to_thread(daily_all)
            except Exception:
                logger.exception('Backup scheduler failed; will retry')
            await asyncio.sleep(60)
    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
