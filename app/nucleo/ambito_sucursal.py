"""Sucursal boundaries for employee operations; administrators may aggregate."""
from app.nucleo.excepciones import AccesoDenegadoException
from app.modelos.usuario import Usuario, RolUsuario


def resolve_branch(user: Usuario, requested: str | None = None) -> str | None:
    role = user.role.value if hasattr(user.role, "value") else user.role
    if role == RolUsuario.ADMIN.value:
        return requested or None
    if role in (RolUsuario.STORE_MANAGER.value, RolUsuario.CASHIER.value):
        if not user.branch_id:
            raise AccesoDenegadoException(detail="No tienes una sucursal asignada. Contacta al administrador.")
        if requested and requested != user.branch_id:
            raise AccesoDenegadoException(detail="Solo puedes operar en tu sucursal asignada.")
        return user.branch_id
    raise AccesoDenegadoException(detail="No tienes permisos para consultar la operación de las sucursales.")
