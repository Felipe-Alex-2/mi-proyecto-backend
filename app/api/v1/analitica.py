"""CU16/CU17: authorized, company-scoped synthetic ML experiments."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.api.dependencias import require_admin
from app.api.v1.saas import require_platform
from app.base_datos import get_db
from app.esquemas.analitica import GenerarSinteticosRequest, EntrenarRequest, PrediccionDemandaRequest
from app.modelos.analitica import ConjuntoSintetico, EntrenamientoModelo
from app.modelos.saas import Empresa, ROOT_TENANT_ID
from app.modelos.sucursal import Sucursal
from app.modelos.usuario import Usuario
from app.servicios.saas_service import enforce_subscription

router = APIRouter(prefix='/analytics', tags=['Analítica y entrenamiento'])
company_router = APIRouter(prefix='/saas/companies', tags=['Datos sintéticos por empresa'])
logger = logging.getLogger(__name__)


def scope(db, user, tenant_id=None, write=False):
    own = user.tenant_id or ROOT_TENANT_ID
    target = tenant_id or own
    if target != own and not user.is_saas_admin:
        raise HTTPException(403, 'Solo puedes consultar los modelos de tu empresa.')
    company = db.query(Empresa).filter(Empresa.id == target).first()
    if not company:
        raise HTTPException(404, 'Empresa no encontrada.')
    if write and not company.is_active:
        raise HTTPException(409, 'La empresa está suspendida.')
    # Only a server-authorized administrator can select this experimental scope.
    db.info.update(tenant_id=target, tenant_context=True, personal_history=False, customer_branch_id=None)
    enforce_subscription(db, target, write=write)
    return target


def utc_timestamp(value):
    # SQLite strips timezone information from DateTime(timezone=True).
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def dataset_summary(row):
    return {'id': row.id, 'tenant_id': row.tenant_id, 'name': row.name, 'created_at': utc_timestamp(row.created_at),
            'parameters': row.parameters, 'summary': row.summary, 'status': 'READY'}


def run_summary(row):
    return {'id': row.id, 'tenant_id': row.tenant_id, 'dataset_id': row.dataset_id,
            'status': row.status, 'created_at': utc_timestamp(row.created_at), 'completed_at': utc_timestamp(row.completed_at),
            'parameters': row.parameters, 'metrics': row.metrics, 'error': row.error,
            'artifact_sha256': row.artifact_sha256}


@company_router.post('/{tenant_id}/synthetic-data', status_code=201)
def generate_dataset(tenant_id: str, payload: GenerarSinteticosRequest,
                     db: Session = Depends(get_db), user: Usuario = Depends(require_platform)):
    scope(db, user, tenant_id, write=True)
    parameters = payload.model_dump(mode='json')
    prior = db.query(ConjuntoSintetico).filter(ConjuntoSintetico.request_id == str(payload.request_id)).first()
    if prior:
        if prior.parameters != parameters:
            raise HTTPException(409, 'La misma solicitud ya generó otro conjunto. Actualiza antes de generar de nuevo.')
        return dataset_summary(prior)
    # Use only authorized branch labels; all clients/products/operations are invented.
    branches = [f'{row.name} · {row.city}' for row in db.query(Sucursal).filter(
        Sucursal.is_active == True).order_by(Sucursal.name, Sucursal.city).limit(5)]
    branches = list(dict.fromkeys(branches)) or ['Sucursal sintética Centro', 'Sucursal sintética Sur']
    from app.servicios.datos_sinteticos_service import generate
    data, preprocessing, summary = generate(payload, branches)
    row = ConjuntoSintetico(tenant_id=tenant_id, request_id=str(payload.request_id), name=payload.name,
                            created_by=user.id, parameters=parameters, summary=summary, payload=data, preprocessing=preprocessing)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.query(ConjuntoSintetico).filter(ConjuntoSintetico.request_id == str(payload.request_id)).first()
        if prior and prior.parameters == parameters:
            return dataset_summary(prior)
        raise HTTPException(409, 'La solicitud ya fue procesada con otros parámetros.')
    return dataset_summary(row)


@router.get('/datasets')
def datasets(tenant_id: str | None = Query(None), db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    scope(db, user, tenant_id)
    return [dataset_summary(row) for row in db.query(ConjuntoSintetico).options(
        defer(ConjuntoSintetico.payload), defer(ConjuntoSintetico.preprocessing)).order_by(ConjuntoSintetico.created_at.desc()).limit(100)]


def get_dataset(db, identifier):
    row = db.query(ConjuntoSintetico).filter(ConjuntoSintetico.id == str(identifier)).first()
    if not row:
        raise HTTPException(404, 'Conjunto no encontrado en esta empresa.')
    return row


def recover_interrupted(db):
    now = datetime.now(timezone.utc)
    stale = db.query(EntrenamientoModelo).filter(
        EntrenamientoModelo.status == 'TRAINING',
        EntrenamientoModelo.created_at < now - timedelta(minutes=15)).all()
    for row in stale:
        row.status = 'FAILED'
        row.completed_at = now
        row.error = 'El proceso se interrumpió o excedió 15 minutos. Puedes iniciar un nuevo entrenamiento.'
    if stale:
        db.commit()


@router.get('/datasets/{dataset_id}/download')
def download_dataset(dataset_id: str, tenant_id: str | None = Query(None), db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    scope(db, user, tenant_id)
    row = get_dataset(db, dataset_id)
    output = {'format': 'VESTA_SYNTHETIC_DATASET', 'version': 1, 'tenant_id': row.tenant_id,
              'dataset_id': row.id, 'parameters': row.parameters, 'summary': row.summary, **row.payload}
    return Response(json.dumps(output, ensure_ascii=False, allow_nan=False), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="vesta-sinteticos-{row.id}.json"'})


@router.get('/runs')
def runs(tenant_id: str | None = Query(None), db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    scope(db, user, tenant_id)
    recover_interrupted(db)
    return [run_summary(row) for row in db.query(EntrenamientoModelo).options(defer(EntrenamientoModelo.artifact),
        defer(EntrenamientoModelo.results)).order_by(EntrenamientoModelo.created_at.desc()).limit(100)]


@router.post('/train')
def train(payload: EntrenarRequest, tenant_id: str | None = Query(None),
          db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    target = scope(db, user, tenant_id, write=True)
    parameters = payload.model_dump(mode='json')
    # Serialize starts per company across processes before checking running work.
    recover_interrupted(db)
    db.query(Empresa).filter(Empresa.id == target).with_for_update().first()
    prior = db.query(EntrenamientoModelo).filter(EntrenamientoModelo.request_id == str(payload.request_id)).first()
    if prior:
        if prior.parameters != parameters:
            raise HTTPException(409, 'La solicitud ya se utilizó con otros parámetros.')
        return run_summary(prior)
    if db.query(EntrenamientoModelo.id).filter(EntrenamientoModelo.status == 'TRAINING').first():
        raise HTTPException(409, 'Ya hay un entrenamiento en curso para esta empresa. Actualiza el historial.')
    dataset = get_dataset(db, payload.dataset_id)
    row = EntrenamientoModelo(tenant_id=target, request_id=str(payload.request_id), dataset_id=dataset.id,
                               created_by=user.id, parameters=parameters, status='TRAINING')
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.query(EntrenamientoModelo).filter(EntrenamientoModelo.request_id == str(payload.request_id)).first()
        if prior and prior.parameters == parameters:
            return run_summary(prior)
        raise HTTPException(409, 'La solicitud de entrenamiento ya fue procesada con otros parámetros.')
    try:
        from app.servicios.entrenamiento_service import train_models
        row.metrics, row.results, row.artifact, row.artifact_sha256 = train_models(dataset, payload.clusters)
        row.status = 'COMPLETED'
    except Exception:
        logger.exception('Analytics training failed for run %s', row.id)
        db.rollback()
        row = db.query(EntrenamientoModelo).filter(EntrenamientoModelo.request_id == str(payload.request_id)).one()
        row.status = 'FAILED'
        row.error = 'No se pudo completar el entrenamiento. Genera otro conjunto o vuelve a intentar con una nueva ejecución.'
    row.completed_at = datetime.now(timezone.utc)
    db.commit()
    return run_summary(row)


def get_run(db, identifier):
    row = db.query(EntrenamientoModelo).filter(EntrenamientoModelo.id == identifier).first()
    if not row:
        raise HTTPException(404, 'Ejecución no encontrada en esta empresa.')
    return row


@router.get('/runs/{run_id}')
def run_detail(run_id: str, tenant_id: str | None = Query(None), db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    scope(db, user, tenant_id)
    row = get_run(db, run_id)
    return dict(run_summary(row), results=row.results)


@router.post('/runs/{run_id}/predict')
def predict(run_id: str, payload: PrediccionDemandaRequest, tenant_id: str | None = Query(None),
            db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    scope(db, user, tenant_id)
    row = get_run(db, run_id)
    if row.status != 'COMPLETED' or not row.artifact:
        raise HTTPException(409, 'El modelo todavía no está listo para consultas.')
    if hashlib.sha256(row.artifact).hexdigest() != row.artifact_sha256:
        raise HTTPException(409, 'El modelo guardado no supera la comprobación de integridad. Vuelve a entrenar.')
    import sklearn
    if row.metrics.get('sklearn_version') != sklearn.__version__:
        raise HTTPException(409, 'Cambió la versión del motor de modelos. Vuelve a entrenar para esta versión.')
    from app.servicios.datos_sinteticos_service import decode
    from app.servicios.entrenamiento_service import infer
    bundle = decode(row.artifact)
    if bundle['tenant_id'] != row.tenant_id or bundle['dataset_id'] != row.dataset_id:
        raise HTTPException(409, 'El modelo no corresponde a esta empresa y conjunto.')
    if payload.category not in bundle['categories'] or payload.branch not in bundle['branches']:
        raise HTTPException(422, 'Selecciona una categoría y sucursal incluidas en el conjunto.')
    if payload.week.weekday() != 0:
        raise HTTPException(422, 'Selecciona un lunes como inicio de semana.')
    return {'source': 'synthetic', 'run_id': row.id, 'category': payload.category, 'branch': payload.branch,
            'week': payload.week, 'predicted_units': infer(bundle, payload.week, payload.category, payload.branch)}
