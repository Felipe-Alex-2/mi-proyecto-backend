import hashlib
import gzip
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, Request, Header
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.api.dependencias import require_admin
from app.base_datos import get_db
from app.modelos.saas import Empresa
from app.modelos.usuario import Usuario
from app.servicios.respaldo_service import create_backup, list_backups, company_folder
from app.servicios.restauracion_respaldo_service import MAX_BYTES, parse_backup, preview_backup, restore_backup

router = APIRouter(prefix='/backups', tags=['Copias de seguridad'])


def resolve_company(user, tenant_id, db):
    company_id = str(tenant_id) if tenant_id else user.tenant_id
    if not user.is_saas_admin and company_id != user.tenant_id:
        raise HTTPException(403, 'Solo puedes respaldar tu propia empresa.')
    if not db.get(Empresa, company_id):
        raise HTTPException(404, 'Empresa no encontrada.')
    return company_id


@router.get('')
def backups(tenant_id: uuid.UUID | None = None, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    company = resolve_company(user, tenant_id, db)
    return {'tenant_id':company,'schedule':'Diario · America/La_Paz','backups':list_backups(company)}


@router.post('', status_code=201)
def make_backup(tenant_id: uuid.UUID | None = None, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    company = resolve_company(user, tenant_id, db)
    try:
        return create_backup(company, 'MANUAL', db.get_bind())
    except (OSError, TypeError) as error:
        raise HTTPException(503, 'No se pudo guardar el respaldo. Revisa el almacenamiento privado del servidor.') from error


@router.get('/{backup_id}/download')
def download_backup(backup_id: uuid.UUID, tenant_id: uuid.UUID | None = None,
                    user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    company = resolve_company(user, tenant_id, db)
    metadata = next((row for row in list_backups(company) if row['id']==str(backup_id)), None)
    if not metadata:
        raise HTTPException(404, 'Respaldo no encontrado en esta empresa.')
    content = (company_folder(company) / (str(backup_id)+'.json.gz')).read_bytes()
    if hashlib.sha256(content).hexdigest() != metadata['sha256']:
        raise HTTPException(409, 'El archivo no pasó la verificación de integridad. Genera otro respaldo.')
    return Response(content=gzip.decompress(content), media_type='application/json', headers={
        'Content-Disposition':f'attachment; filename="vesta-backup-{backup_id}.json"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


async def read_upload(request: Request):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, 'El archivo supera el máximo de 32 MB.')
    return await run_in_threadpool(parse_backup, bytes(content))


@router.post('/preview')
async def review_upload(request: Request, tenant_id: uuid.UUID | None = None,
                        user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    company = resolve_company(user, tenant_id, db)
    payload, file_hash = await read_upload(request)
    return await run_in_threadpool(preview_backup, db, company, user, payload, file_hash)


@router.post('/restore')
async def restore_upload(request: Request, tenant_id: uuid.UUID | None = None,
                         review_token: str = Header(default='', alias='X-Vesta-Backup-Review'),
                         user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    company = resolve_company(user, tenant_id, db)
    payload, file_hash = await read_upload(request)
    return await run_in_threadpool(restore_backup, db, company, user, payload, file_hash, review_token)
