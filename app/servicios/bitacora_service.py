from typing import Optional

from fastapi import Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.nucleo.transacciones import commit_or_flush
from app.modelos.bitacora import Bitacora
from app.modelos.sucursal import Sucursal
from app.modelos.usuario import Usuario
from app.esquemas.bitacora import BitacoraCreate, BitacoraListResponse


BUSINESS_PREFIXES = ("CREAR_", "ACTUALIZAR_", "ELIMINAR_", "CAMBIAR_", "CANCELAR_", "COBRO_", "REGISTRO_", "ASIGNAR_", "RETIRAR_", "AJUSTAR_")
BUSINESS_ACTIONS = ("MOVIMIENTO_STOCK",)


class BitacoraService:
    @staticmethod
    def create(db: Session, user: Usuario, payload: BitacoraCreate, request: Optional[Request] = None):
        return BitacoraService.log_event(db, user, payload.action, payload.description, payload.category)

    @staticmethod
    def log_event(db: Session, user: Optional[Usuario], action: str, description: str,
                  category: str = "NEGOCIO", ip_address: Optional[str] = None,
                  branch_id: Optional[str] = None) -> Optional[Bitacora]:
        action = action.strip().upper()
        if not (action.startswith(BUSINESS_PREFIXES) or action in BUSINESS_ACTIONS):
            return None
        scope = branch_id or db.info.get("audit_branch_id") or (user.branch_id if user else None)
        branch = db.get(Sucursal, scope) if scope else None
        log = Bitacora(
            user_id=user.id if user else None,
            user_email=user.email if user else "sistema@local.dev",
            user_name=user.full_name if user else "Sistema",
            action=action, description=description.strip(), category=category.strip().upper(),
            branch_id=scope, branch_name=branch.name if branch else None,
            ip_address=None,
        )
        db.add(log)
        commit_or_flush(db)
        db.refresh(log)
        db.info["audit_event_count"] = db.info.get("audit_event_count", 0) + 1
        return log

    @staticmethod
    def list_logs(db: Session, page: int = 1, page_size: int = 25,
                  action: Optional[str] = None, category: Optional[str] = None,
                  search: Optional[str] = None, branch_id: Optional[str] = None) -> BitacoraListResponse:
        # Historical navigation/login records are retained but are not business events.
        query = db.query(Bitacora).filter(or_(
            *(Bitacora.action.startswith(prefix, autoescape=True) for prefix in BUSINESS_PREFIXES),
            Bitacora.action.in_(BUSINESS_ACTIONS),
        ))
        if branch_id:
            query = query.filter(Bitacora.branch_id == branch_id)
        if action:
            key = action.strip().upper()
            if key in ("CREAR", "ACTUALIZAR", "ELIMINAR", "CANCELAR", "COBRO"):
                prefixes = {"ACTUALIZAR": ("ACTUALIZAR_", "CAMBIAR_", "AJUSTAR_"), "CREAR": ("CREAR_", "REGISTRO_")}.get(key, (key + "_",))
                query = query.filter(or_(*(Bitacora.action.startswith(p, autoescape=True) for p in prefixes)))
            else:
                query = query.filter(Bitacora.action == key)
        if category:
            query = query.filter(Bitacora.category == category.strip().upper())
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(or_(Bitacora.user_name.ilike(term), Bitacora.user_email.ilike(term), Bitacora.description.ilike(term)))
        total = query.count()
        items = query.order_by(Bitacora.created_at.desc(), Bitacora.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return BitacoraListResponse(items=items, total=total, page=page, page_size=page_size)
