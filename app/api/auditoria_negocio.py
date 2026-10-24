"""Audit successful mutations on authenticated business routers, never reads."""
from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user
from app.base_datos import get_db
from app.modelos.sucursal import Sucursal
from app.modelos.movimiento_inventario import MovimientoInventario
from app.modelos.usuario import Usuario
from app.servicios.bitacora_service import BitacoraService


async def audit_business_mutation(request: Request, response: Response,
                                  db: Session = Depends(get_db),
                                  user: Usuario = Depends(get_current_user)):
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        yield
        return
    parts = request.url.path.split("/v1/", 1)[-1].split("/")
    resources = {"branches": ("SUCURSAL", "ADMINISTRACION"), "attributes": ("ATRIBUTO", "CATALOGO"),
                 "seasons": ("TEMPORADA", "CATALOGO"), "promotions": ("PROMOCION", "CATALOGO"),
                 "suppliers": ("PROVEEDOR", "CATALOGO"), "stocks": ("STOCK", "INVENTARIO"),
                 "inventory": ("MOVIMIENTO", "INVENTARIO")}
    resource, category = resources[parts[0]]
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(payload, dict):
        payload = {}
    branch_id = payload.get("branch_id") or user.branch_id
    if parts[0] == "branches" and len(parts) > 1:
        branch_id = parts[1]
    if parts[0] == "inventory" and len(parts) > 2:
        movement = db.get(MovimientoInventario, parts[2])
        if movement:
            branch_id = movement.branch_id
    count = db.info.get("audit_event_count", 0)
    previous = db.info.get("audit_branch_id")
    db.info["audit_branch_id"] = branch_id
    try:
        yield
        if response.status_code and response.status_code >= 400:
            return
        if db.info.get("audit_event_count", 0) != count:
            return  # A service already wrote the precise event.
        verb = {"POST": "CREAR", "PUT": "ACTUALIZAR", "PATCH": "ACTUALIZAR", "DELETE": "ELIMINAR"}[request.method]
        if "staff" in parts:
            verb = "RETIRAR" if request.method == "DELETE" else "ASIGNAR"
            resource = "PERSONAL"
        if parts[0] == "stocks":
            verb = "AJUSTAR"
        label = str(payload.get("name") or payload.get("variant_id") or "/".join(parts[1:]) or resource.lower())[:200]
        if parts[0] == "branches" and len(parts) == 1:
            branch = db.query(Sucursal).filter(Sucursal.name == payload.get("name", "").strip(), Sucursal.city == payload.get("city", "").strip()).first()
            branch_id = branch.id if branch else None
        BitacoraService.log_event(db, user, f"{verb}_{resource}",
                                    f"{verb.capitalize()} {resource.lower()}: {label}", category,
                                    branch_id=branch_id)
    finally:
        if previous is None:
            db.info.pop("audit_branch_id", None)
        else:
            db.info["audit_branch_id"] = previous
