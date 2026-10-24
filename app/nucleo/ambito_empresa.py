"""Central ORM isolation for commercial data, including joins and bulk mutations.

The request context is resolved from the authenticated account, never from a
client-supplied tenant header. Personal history is a narrow customer-only path;
its services must additionally constrain every record to that customer.
"""
from sqlalchemy import event, inspect, or_, select
from sqlalchemy.orm import Session, with_loader_criteria
from fastapi import HTTPException
from app.modelos.saas import PerteneceEmpresa, ROOT_TENANT_ID

_installed = False


def install_tenant_events():
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, 'do_orm_execute')
    def scope_queries(state):
        info = state.session.info
        if state.execution_options.get('skip_tenant') or not info.get('tenant_context'):
            return
        tenant_id = info.get('tenant_id') or '__no_company_selected__'
        if not info.get('personal_history'):
            state.statement = state.statement.options(with_loader_criteria(
                PerteneceEmpresa, lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True, propagate_to_loaders=True))
        from app.modelos.usuario import Usuario
        from app.modelos.saas import ClienteEmpresa
        actor_id = info.get('actor_id')
        members = select(ClienteEmpresa.user_id).where(ClienteEmpresa.tenant_id == tenant_id)
        if not info.get('personal_history'):
            state.statement = state.statement.options(with_loader_criteria(
                Usuario, or_(Usuario.tenant_id == tenant_id, Usuario.id == actor_id, Usuario.id.in_(members)),
                include_aliases=True))
        if info.get('customer_branch_id') and not info.get('personal_history'):
            from app.modelos.carrito_item import CarritoItem
            from app.modelos.stock import Stock
            branch_id = info['customer_branch_id']
            for model in (CarritoItem, Stock):
                state.statement = state.statement.options(with_loader_criteria(
                    model, model.branch_id == branch_id, include_aliases=True))

    @event.listens_for(Session, 'before_flush')
    def validate_writes(db, flush_context, instances):
        from app.modelos.usuario import Usuario
        from app.modelos.sucursal import Sucursal
        from app.servicios.saas_service import enforce_branch_limit
        context = db.info.get('tenant_context')
        tenant_id = db.info.get('tenant_id')
        new_branches = [o for o in db.new if isinstance(o, Sucursal) and o.is_active is not False]
        reopened = [o for o in db.dirty if isinstance(o, Sucursal) and o.is_active and
                    inspect(o).attrs.is_active.history.has_changes()]
        if context and (new_branches or reopened):
            enforce_branch_limit(db, tenant_id, len(new_branches) + len(reopened))
        for obj in list(db.new) + list(db.dirty):
            if isinstance(obj, Usuario):
                if obj in db.new and obj.role != 'CUSTOMER' and not obj.tenant_id:
                    obj.tenant_id = tenant_id or ROOT_TENANT_ID
                if obj.branch_id:
                    owning_company = obj.selected_tenant_id if obj.role == 'CUSTOMER' else obj.tenant_id
                    branch_company = db.connection().execute(select(Sucursal.tenant_id).where(Sucursal.id == obj.branch_id)).scalar()
                    if branch_company and owning_company and branch_company != owning_company:
                        raise HTTPException(403, 'La sucursal de la cuenta no pertenece a su empresa.')
                continue
            if not isinstance(obj, PerteneceEmpresa):
                continue
            if obj in db.new:
                obj.tenant_id = obj.tenant_id or tenant_id or ROOT_TENANT_ID
            if context and obj.tenant_id != tenant_id and not db.info.get('personal_history'):
                raise HTTPException(403, 'El recurso pertenece a otra empresa.')
            # Validate cross-company foreign keys even if an endpoint forgets a lookup.
            for column in inspect(type(obj)).columns:
                if column.name == 'tenant_id':
                    continue
                value = getattr(obj, column.name)
                if value is None:
                    continue
                for fk in column.foreign_keys:
                    table = fk.column.table
                    if 'tenant_id' not in table.c or table.name == 'users':
                        continue
                    pending = next((x for x in db.new if getattr(x, '__tablename__', None) == table.name
                                    and getattr(x, fk.column.name, None) == value), None)
                    target_tenant = getattr(pending, 'tenant_id', None) if pending else db.connection().execute(
                        select(table.c.tenant_id).where(fk.column == value)).scalar()
                    if target_tenant is not None and target_tenant != obj.tenant_id:
                        raise HTTPException(403, 'No puedes vincular recursos de empresas diferentes.')


def configure_context(db, user, request):
    """Resolve a fresh, server-owned context for each authenticated request."""
    db.info.update(tenant_context=True, actor_id=user.id,
                   tenant_id=user.selected_tenant_id if user.role == 'CUSTOMER' else user.tenant_id,
                   customer_branch_id=user.branch_id if user.role == 'CUSTOMER' else None,
                   personal_history=False)
    # Legacy fixture accounts use the original company; migrated databases have
    # explicit ownership on every staff account.
    if not db.info['tenant_id'] and user.role != 'CUSTOMER':
        db.info['tenant_id'] = ROOT_TENANT_ID
    # Customers can browse different stores on different devices. A device pins
    # its context, while staff can never use these headers to change company.
    header_tenant = request.headers.get('X-Vesta-Empresa')
    header_branch = request.headers.get('X-Vesta-Sucursal')
    if header_tenant or header_branch:
        if user.role != 'CUSTOMER':
            if header_tenant != db.info['tenant_id']:
                raise HTTPException(403, 'El personal no puede cambiar de empresa.')
        else:
            from app.modelos.sucursal import Sucursal
            branch = db.query(Sucursal).execution_options(skip_tenant=True).filter(
                Sucursal.id == header_branch, Sucursal.tenant_id == header_tenant).first()
            if not branch:
                raise HTTPException(403, 'La empresa y sucursal seleccionadas no coinciden.')
            db.info.update(tenant_id=header_tenant, customer_branch_id=header_branch)
    path = request.url.path
    history = user.role == 'CUSTOMER' and (
        path.startswith('/api/v1/reservations') and request.method in ('GET', 'DELETE')
        or path.startswith('/api/v1/notifications')
        or path.startswith('/api/v1/saas/history'))
    db.info['personal_history'] = history
    # Suscripcion management, identity and personal history remain accessible
    # after expiry so an administrator can renew and a customer can see receipts.
    excluded = ('/api/v1/backups', '/api/v1/saas', '/api/v1/auth', '/api/v1/users/me', '/api/v1/notifications', '/api/v1/sync')
    if not path.startswith(excluded) and not history:
        from app.servicios.saas_service import enforce_subscription
        enforce_subscription(db, db.info['tenant_id'], write=request.method != 'GET')
        if user.role == 'CUSTOMER' and not db.info.get('customer_branch_id'):
            from app.modelos.saas import Empresa
            if db.query(Empresa.id).first():
                raise HTTPException(403, 'Escoge tu empresa y sucursal desde Mi perfil para continuar.')
