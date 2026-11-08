import asyncio,json,hashlib,logging
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from fastapi import HTTPException
from sqlalchemy import event,inspect,or_,update
from sqlalchemy.orm import Session
from app.configuracion import settings
from app.modelos.push import DispositivoPush,EnvioPush

logger=logging.getLogger('push')
def now():return datetime.now(timezone.utc)
def aware(d):return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
def digest(token):return hashlib.sha256(token.encode()).hexdigest()
def configured():
    if not settings.FIREBASE_PUSH_ENABLED:return False
    if settings.FIREBASE_CLIENT_EMAIL or settings.FIREBASE_PRIVATE_KEY:
        return bool(settings.FIREBASE_PROJECT_ID and settings.FIREBASE_CLIENT_EMAIL and settings.FIREBASE_PRIVATE_KEY)
    return bool(settings.FIREBASE_CREDENTIALS_JSON)


def service_credentials():
    if settings.FIREBASE_CLIENT_EMAIL or settings.FIREBASE_PRIVATE_KEY:
        if not settings.FIREBASE_CLIENT_EMAIL or not settings.FIREBASE_PRIVATE_KEY or not settings.FIREBASE_PROJECT_ID:
            raise ValueError('Completa FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL y FIREBASE_PRIVATE_KEY.')
        private_key=settings.FIREBASE_PRIVATE_KEY.strip()
        if private_key.startswith('"') and private_key.endswith('"'):
            private_key=json.loads(private_key)
        private_key=private_key.replace('\\n','\n').replace('\r\n','\n')
        return {'type':'service_account','project_id':settings.FIREBASE_PROJECT_ID,
            'client_email':settings.FIREBASE_CLIENT_EMAIL.strip(),'private_key':private_key,
            'token_uri':'https://oauth2.googleapis.com/token'}
    key=json.loads(settings.FIREBASE_CREDENTIALS_JSON)
    if key.get('project_id')!=settings.FIREBASE_PROJECT_ID:
        raise ValueError('La cuenta de servicio no pertenece al proyecto Firebase configurado.')
    return key

def register(db,user,data):
    tenant=db.info.get('tenant_id')
    branch=db.info.get('customer_branch_id') if user.role=='CUSTOMER' else user.branch_id
    if not tenant or data.user_id!=user.id or data.tenant_id!=tenant or data.branch_id!=branch:
        raise HTTPException(409,'La sesión o empresa cambió. Vuelve a activar las notificaciones.')
    from app.modelos.saas import Empresa
    if not db.query(Empresa).filter(Empresa.id==tenant).first():raise HTTPException(403,'Selecciona una empresa.')
    from app.modelos.usuario import Usuario
    db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id==user.id).with_for_update().first()
    row=db.query(DispositivoPush).execution_options(skip_tenant=True).filter(DispositivoPush.id==str(data.installation_id)).with_for_update().first()
    other=db.query(DispositivoPush).execution_options(skip_tenant=True).filter(DispositivoPush.token_hash==digest(data.token),DispositivoPush.id!=str(data.installation_id)).first()
    if other:raise HTTPException(409,'Este token ya está asociado a otra instalación. Renueva el registro del dispositivo.')
    if row is None:
        row=DispositivoPush(id=str(data.installation_id));db.add(row)
    row.tenant_id,row.user_id,row.branch_id=tenant,user.id,branch
    row.token,row.token_hash,row.active,row.updated_at=data.token,digest(data.token),True,now()
    from sqlalchemy.exc import IntegrityError
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'El registro cambió. Vuelve a activar las notificaciones.')
    return {'registered':True,'server_configured':configured()}

def unregister(db,user,data):
    # A user may revoke their installation after switching to another company.
    db.execute(update(DispositivoPush).where(DispositivoPush.id==str(data.installation_id),
        DispositivoPush.user_id==user.id,DispositivoPush.token_hash==digest(data.token)).values(active=False).execution_options(skip_tenant=True))
    db.commit();return {'registered':False}

def firebase_app():
    import firebase_admin
    from firebase_admin import credentials
    try:return firebase_admin.get_app('vesta-push')
    except ValueError:
        key=service_credentials()
        return firebase_admin.initialize_app(credentials.Certificate(key),name='vesta-push')

def send_to_device(token,data,tag):
    from firebase_admin import messaging
    # Keep sensitive purchase/account details out of the OS lock-screen tray.
    message=messaging.Message(fid=token,data=data,notification=messaging.Notification(
        title='Tu delivery salió' if data.get('kind')=='DELIVERY_OUT_FOR_DELIVERY' else 'VESTA',body='Tu pedido está en camino. Consulta Reservas para ver el seguimiento.' if data.get('kind')=='DELIVERY_OUT_FOR_DELIVERY' else 'Tienes una nueva notificación. Abre la app para verla.'),
        android=messaging.AndroidConfig(priority='high',ttl=timedelta(hours=24),notification=messaging.AndroidNotification(
            channel_id='vesta_notifications',tag=tag,icon='ic_notification',color='#A34F3D',default_sound=True)))
    return messaging.send(message,app=firebase_app())

def drain(db,send=send_to_device):
    if not configured():return 0
    jobs=db.query(EnvioPush).execution_options(skip_tenant=True).filter(EnvioPush.status=='PENDING',EnvioPush.next_attempt_at<=now()).order_by(EnvioPush.created_at).limit(30).with_for_update(skip_locked=True).all()
    completed=0
    for job in jobs:
        if now()-aware(job.created_at)>timedelta(hours=24):job.status='EXPIRED';continue
        sent=set(json.loads(job.sent_devices_json));failed=False
        devices=db.query(DispositivoPush).execution_options(skip_tenant=True).filter(
            DispositivoPush.user_id==job.user_id,DispositivoPush.tenant_id==job.tenant_id,DispositivoPush.active==True).order_by(DispositivoPush.id).with_for_update().all()
        for device in devices:
            # Token refreshes create a new delivery destination on the same installation.
            key=device.id+':'+device.token_hash
            if key in sent:continue
            try:send(device.token,json.loads(job.data_json),job.notification_id);sent.add(key)
            except Exception as exc:
                # Firebase's public error code is safe to inspect; never log tokens/keys.
                code=getattr(exc,'code','')
                from firebase_admin import messaging
                if isinstance(exc,(messaging.UnregisteredError,messaging.SenderIdMismatchError)) or code in ('UNREGISTERED','registration-token-not-registered','SENDER_ID_MISMATCH'):device.active=False
                else:failed=True
        job.sent_devices_json=json.dumps(sorted(sent))
        if failed:
            job.attempts+=1;job.status='FAILED' if job.attempts>=8 else 'PENDING'
            job.next_attempt_at=now()+timedelta(seconds=min(3600,10*2**job.attempts))
        else:job.status='SENT';completed+=1
    db.commit();return completed

_installed=False

def install_events():
    global _installed
    if _installed:return
    _installed=True
    @event.listens_for(Session,'before_flush')
    def enqueue(db,flush_context,instances):
        from app.modelos.reserva import Reserva
        from app.modelos.notificacion import Notificacion
        import uuid
        for row in list(db.new)+list(db.dirty):
            if not isinstance(row,Reserva) or row.status not in ('CONFIRMED','COMPLETED'):continue
            if row not in db.new and not inspect(row).attrs.status.history.has_changes():continue
            if not row.customer_id:continue
            row.id=row.id or str(uuid.uuid4())
            if any(isinstance(n,Notificacion) and n.reservation_id==row.id for n in db.new):continue
            if db.query(Notificacion).filter(Notificacion.reservation_id==row.id,Notificacion.user_id==row.customer_id).first():continue
            notification=Notificacion(id=str(uuid.uuid4()),user_id=row.customer_id,reservation_id=row.id,
                title='¡Tu pedido fue aceptado!',message=f'Tu pedido {row.reservation_code} fue confirmado. Consulta tu reserva para ver los detalles.',
                notification_type='RESERVATION_ACCEPTED',is_read=False)
            notification.reservation=row
            db.add(notification)
        for n in list(db.new):
            if not isinstance(n,Notificacion):continue
            tenant=getattr(n,'_push_tenant_id',None)
            branch=getattr(n,'_push_branch_id',None)
            if n.reservation_id:
                reservation=next((r for r in db.new if isinstance(r,Reserva) and r.id==n.reservation_id),None)
                if reservation is None:reservation=db.query(Reserva).execution_options(skip_tenant=True).filter(Reserva.id==n.reservation_id,Reserva.customer_id==n.user_id).first()
                if reservation:tenant=reservation.tenant_id or db.info.get('tenant_id');branch=reservation.branch_id
            if not tenant:continue
            n.id=n.id or str(uuid.uuid4())
            data={'notification_id':n.id,'user_id':n.user_id,'tenant_id':tenant,'kind':n.notification_type or 'GENERAL'}
            if n.reservation_id:data['reservation_id']=n.reservation_id
            db.add(EnvioPush(notification=n,notification_id=n.id,tenant_id=tenant,user_id=n.user_id,branch_id=branch,
                data_json=json.dumps(data),sent_devices_json='[]'))

def wallet_notification(db,user,topup):
    from app.modelos.notificacion import Notificacion
    import uuid
    n=Notificacion(id=str(uuid.uuid4()),user_id=user.id,title='Recarga de wallet confirmada',
        message=f'Se acreditaron USD {topup.amount} en tu wallet de esta empresa.',notification_type='WALLET_TOPUP',is_read=False)
    n._push_tenant_id=topup.tenant_id;n._push_branch_id=db.info.get('customer_branch_id')
    db.add(n)

def run_batch():
    from app.base_datos import SessionLocal
    with SessionLocal() as db:drain(db)

@asynccontextmanager
async def push_schedule():
    async def loop():
        while True:
            if configured():
                try:await asyncio.to_thread(run_batch)
                except Exception:logger.warning('No se pudo procesar la cola push; se reintentará sin interrumpir la API.')
            await asyncio.sleep(10)
    task=asyncio.create_task(loop())
    try:yield
    finally:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
