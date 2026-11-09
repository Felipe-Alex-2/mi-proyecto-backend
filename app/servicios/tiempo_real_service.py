"""Transactional invalidations. PostgreSQL fans out to every API worker."""
import asyncio
import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from app.base_datos import engine

log = logging.getLogger(__name__)
CHANNEL = 'vesta_realtime'
_installed = False


def authorized(scope, payload):
    if payload.get('tenant_id') != scope['tenant_id']:
        return False
    if payload.get('user_id'):
        return payload['user_id'] == scope['user_id']
    if scope['role'] == 'CUSTOMER':
        return payload.get('customer_id') == scope['user_id']
    return scope['role'] == 'ADMIN' or (
        scope['role'] in ('STORE_MANAGER', 'CASHIER') and bool(scope['branch_id'])
        and payload.get('branch_id') == scope['branch_id'])


class Hub:
    def __init__(self):
        self.clients = {}
        self.lock = threading.Lock()

    def add(self, scope):
        key = uuid.uuid4().hex
        queue = asyncio.Queue(maxsize=100)
        with self.lock:
            self.clients[key] = (asyncio.get_running_loop(), queue, scope)
        return key, queue

    def remove(self, key):
        with self.lock:
            self.clients.pop(key, None)

    def publish(self, payload):
        with self.lock:
            clients = list(self.clients.values())
        for loop, queue, scope in clients:
            if not authorized(scope, payload):
                continue
            def deliver(q=queue, data=payload):
                if q.full():
                    while not q.empty():
                        q.get_nowait()
                    q.put_nowait({'type': 'resync'})
                else:
                    q.put_nowait(data)
            try:
                loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                pass


hub = Hub()


def install_events():
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, 'before_flush')
    def collect(db, context, instances):
        from app.modelos.reserva import Reserva
        from app.modelos.delivery import PedidoDelivery
        from app.modelos.notificacion import Notificacion
        rows = db.info.setdefault('_realtime_rows', [])
        for row in list(db.new) + list(db.dirty):
            if isinstance(row, (Reserva, PedidoDelivery, Notificacion)) and (
                row in db.new or db.is_modified(row, include_collections=False)):
                rows.append((row, row in db.new))

    @event.listens_for(Session, 'after_flush_postexec')
    def stage(db, context):
        from app.modelos.reserva import Reserva
        from app.modelos.delivery import PedidoDelivery
        for row, created in db.info.pop('_realtime_rows', []):
            if isinstance(row, PedidoDelivery):
                if row.status == 'AWAITING_PAYMENT':
                    continue
                created = row.status == 'REQUESTED'
            if isinstance(row, (Reserva, PedidoDelivery)):
                payload = dict(type=('reservation' if isinstance(row, Reserva) else 'delivery') + ('.created' if created else '.changed'),
                    tenant_id=row.tenant_id, branch_id=row.branch_id, customer_id=row.customer_id,
                    reservation_id=row.id if isinstance(row, Reserva) else row.reservation_id)
            else:
                reservation = db.get(Reserva, row.reservation_id) if row.reservation_id else None
                payload = dict(type='notification.changed', user_id=row.user_id,
                    tenant_id=reservation.tenant_id if reservation else getattr(row, '_push_tenant_id', None) or db.info.get('tenant_id'))
            if not payload.get('tenant_id'):
                continue
            if db.get_bind().dialect.name == 'postgresql':
                db.execute(text('SELECT pg_notify(:channel, :payload)'),
                    {'channel': CHANNEL, 'payload': json.dumps(payload)})
            else:
                db.info.setdefault('_realtime_committed', []).append(payload)

    @event.listens_for(Session, 'after_commit')
    def committed(db):
        if db.in_nested_transaction():
            return
        for payload in db.info.pop('_realtime_committed', []):
            hub.publish(payload)

    @event.listens_for(Session, 'after_rollback')
    def rollback(db):
        db.info.pop('_realtime_rows', None)
        db.info.pop('_realtime_committed', None)


def listen(stop):
    import psycopg
    dsn = engine.url.set(drivername='postgresql').render_as_string(hide_password=False)
    while not stop.is_set():
        try:
            with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
                conn.execute('LISTEN ' + CHANNEL)
                # Re-query HTTP snapshots after any gap in the database listener.
                with hub.lock:
                    scopes = [client[2] for client in hub.clients.values()]
                for scope in scopes:
                    hub.publish(dict(type='resync', tenant_id=scope['tenant_id'], user_id=scope['user_id']))
                while not stop.is_set():
                    for notification in conn.notifies(timeout=1):
                        try:
                            hub.publish(json.loads(notification.payload))
                        except (ValueError, TypeError):
                            log.warning('Invalid realtime event ignored')
        except Exception:
            log.warning('Realtime database listener disconnected; reconnecting')
            stop.wait(3)


@asynccontextmanager
async def realtime_schedule():
    stop = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(listen, stop)) if engine.dialect.name == 'postgresql' else None
    try:
        yield
    finally:
        stop.set()
        if task:
            await task
