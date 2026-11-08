from typing import Literal
from uuid import UUID
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.api.dependencias import require_roles
from app.modelos.usuario import RolUsuario
from app.servicios import wallet_service as service
router=APIRouter(prefix='/wallet',tags=['Wallet'])
customer=require_roles(RolUsuario.CUSTOMER)
class Recarga(BaseModel):
    request_id: UUID
    amount: Literal[10,50,100]
@router.get('')
def wallet(db:Session=Depends(get_db),user=Depends(customer)):
    return service.view(db,user)
@router.post('/topups',status_code=201)
def topup(data:Recarga,db:Session=Depends(get_db),user=Depends(customer)):
    return service.topup(db,user,data)
@router.post('/topups/{id}/capture')
def capture(id:str,db:Session=Depends(get_db),user=Depends(customer)):
    return service.capture(db,user,id)
