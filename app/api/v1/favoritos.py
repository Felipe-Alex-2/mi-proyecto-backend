from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.api.dependencias import require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.modelos.favorito import Favorito
from app.servicios.catalogo_service import CatalogoService
from app.esquemas.catalogo import DetalleProductoCatalogoResponse

router = APIRouter(prefix='/favorites', tags=['Favoritos'])
customer = require_roles(RolUsuario.CUSTOMER)


@router.get('', response_model=list[DetalleProductoCatalogoResponse])
def favorites(db: Session = Depends(get_db), user: Usuario = Depends(customer)):
    from app.modelos.producto import Producto
    from app.modelos.sucursal import Sucursal
    from app.servicios.carga_productos import product_load_options
    products = db.query(Producto).join(Favorito, Favorito.product_id == Producto.id).filter(
        Favorito.user_id == user.id, Producto.is_active == True).options(*product_load_options()).all()
    branches = db.query(Sucursal).filter(Sucursal.id == db.info['customer_branch_id'], Sucursal.is_active == True).all()
    return [CatalogoService._format_product(db, p, branches) for p in products]


@router.put('/{product_id}')
def save(product_id: str, db: Session = Depends(get_db), user: Usuario = Depends(customer)):
    CatalogoService.get_product(db, product_id)
    existing = db.query(Favorito).filter(Favorito.user_id == user.id, Favorito.product_id == product_id).first()
    if not existing:
        db.add(Favorito(user_id=user.id, product_id=product_id, tenant_id=db.info['tenant_id']))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not db.query(Favorito).filter(Favorito.user_id == user.id, Favorito.product_id == product_id).first():
                raise
    return {'saved': True}


@router.delete('/{product_id}')
def remove(product_id: str, db: Session = Depends(get_db), user: Usuario = Depends(customer)):
    db.query(Favorito).filter(Favorito.user_id == user.id, Favorito.product_id == product_id).delete(synchronize_session=False)
    db.commit()
    return {'saved': False}
