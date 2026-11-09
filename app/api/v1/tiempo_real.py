import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.api.dependencias import get_current_user
from app.configuracion import settings
from app.servicios.tiempo_real_service import hub

router = APIRouter(prefix='/realtime', tags=['Tiempo real'])


def authenticate(db, data):
    token = data.get('token')
    if data.get('type') != 'authenticate' or not isinstance(token, str) or len(token) > 8192:
        raise HTTPException(401, 'Autenticación requerida')
    headers = []
    for key, name in [('tenant_id', 'x-vesta-empresa'), ('branch_id', 'x-vesta-sucursal')]:
        if data.get(key):
            headers.append((name.encode(), str(data[key]).encode()))
    request = Request({'type': 'http', 'method': 'GET', 'path': '/api/v1/realtime/ws',
        'headers': headers, 'query_string': b'', 'server': ('localhost', 80), 'scheme': 'https'})
    db.expire_all()
    user = get_current_user(request, HTTPAuthorizationCredentials(scheme='Bearer', credentials=token), db)
    scope = dict(user_id=user.id, tenant_id=db.info.get('tenant_id'), branch_id=user.branch_id, role=user.role)
    db.rollback()  # Do not hold a database connection while the browser waits.
    return scope


@router.websocket('/ws')
async def websocket_events(socket: WebSocket, db: Session = Depends(get_db)):
    origin = socket.headers.get('origin')
    allowed = {s.rstrip('/') for s in settings.cors_origins_list} | {settings.FRONTEND_URL.rstrip('/')}
    if origin and origin.rstrip('/') not in allowed:
        await socket.close(code=1008)
        return
    await socket.accept()
    key = None
    sender = None
    try:
        raw = await asyncio.wait_for(socket.receive_text(), timeout=10)
        if len(raw) > 10000:
            await socket.close(code=1008)
            return
        data = json.loads(raw)
        scope = await run_in_threadpool(authenticate, db, data)
        key, queue = hub.add(scope)
        await socket.send_json({'type': 'ready'})
        async def send_events():
            while True:
                await socket.send_json(await queue.get())
        sender = asyncio.create_task(send_events())
        while True:
            try:
                message = await asyncio.wait_for(socket.receive_text(), timeout=25)
                if len(message) > 100:
                    break
            except asyncio.TimeoutError:
                pass
            if await run_in_threadpool(authenticate, db, data) != scope:
                break
            # A heartbeat also lets the client recover HTTP snapshots after a gap.
            queue.put_nowait({'type': 'heartbeat'})
    except (HTTPException, WebSocketDisconnect, asyncio.TimeoutError, ValueError, TypeError, AttributeError, asyncio.QueueFull):
        pass
    finally:
        if key:
            hub.remove(key)
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        try:
            await socket.close(code=1008)
        except RuntimeError:
            pass
