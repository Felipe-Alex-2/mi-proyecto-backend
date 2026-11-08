from uuid import UUID
from pydantic import BaseModel,Field
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.api.dependencias import get_current_user
from app.base_datos import get_db
from app.servicios import push_service as service
router=APIRouter(prefix='/notifications/push',tags=['Firebase Push'])
class RegistroPush(BaseModel):
    installation_id:UUID
    token:str=Field(min_length=20,max_length=4096)
    user_id:str
    tenant_id:str
    branch_id:str|None=None
class BajaPush(BaseModel):
    installation_id:UUID
    token:str=Field(min_length=20,max_length=4096)
@router.post('/devices')
def register(data:RegistroPush,db:Session=Depends(get_db),user=Depends(get_current_user)):
    return service.register(db,user,data)
@router.post('/unregister')
def unregister(data:BajaPush,db:Session=Depends(get_db),user=Depends(get_current_user)):
    return service.unregister(db,user,data)
@router.get('/status')
def status(user=Depends(get_current_user)):
    return {'server_configured':service.configured(),'project_id':service.settings.FIREBASE_PROJECT_ID}


class PruebaPush(BaseModel):
    request_id:UUID

@router.post('/test')
def test_push(data:PruebaPush,db:Session=Depends(get_db),user=Depends(get_current_user)):
    from fastapi import HTTPException
    from app.modelos.notificacion import Notificacion
    if not service.configured():raise HTTPException(503,'Falta activar Firebase en el backend de Railway.')
    tenant=db.info.get('tenant_id')
    if not tenant:raise HTTPException(403,'Selecciona una empresa.')
    existing=db.query(Notificacion).filter(Notificacion.id==str(data.request_id)).first()
    if existing:
        if existing.user_id!=user.id or existing.notification_type!='PUSH_TEST':raise HTTPException(409,'Esta solicitud ya fue utilizada.')
    else:
        n=Notificacion(id=str(data.request_id),user_id=user.id,title='Prueba de notificación push',message='La integración de notificaciones de VESTA está activa.',notification_type='PUSH_TEST',is_read=False)
        n._push_tenant_id=tenant;n._push_branch_id=user.branch_id
        db.add(n);db.commit()
    return {'message':'Prueba en cola. Envía la app al segundo plano y espera unos segundos.'}
