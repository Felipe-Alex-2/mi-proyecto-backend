"""Explicit offline commands sharing the ordinary API validations and permissions."""
import json
import re
from fastapi import HTTPException
from app.modelos.operacion_sincronizacion import OperacionSincronizacion


LOCAL_ID = re.compile(r'^local-([0-9a-f-]{36})(?:-variant-(\d+))?$')


def resolve_local_id(db, user, value):
    match = LOCAL_ID.fullmatch(value)
    if not match:
        return value
    receipt = db.query(OperacionSincronizacion).filter_by(user_id=user.id, operation_id=match[1]).first()
    if not receipt:
        raise HTTPException(424, 'La operación depende de un registro local aún pendiente o en conflicto.')
    response = json.loads(receipt.response)
    resolved = response.get('_local_ids', {}).get(value)
    if not resolved and match[2] is None:
        resolved = response.get('id')
    if not resolved:
        raise HTTPException(424, 'No se pudo resolver la referencia local. Revisa la operación original.')
    return resolved


def resolve_command(db, user, command):
    def visit(value, key=''):
        if isinstance(value, dict):
            return {(resolve_local_id(db, user, k) if key == 'initial_stock' else k): visit(v, k)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [visit(v, key) for v in value]
        if isinstance(value, str) and (key.endswith('_id') or key.endswith('_ids')):
            return resolve_local_id(db, user, value)
        return value
    return command.model_copy(update={
        'path': '/'.join(resolve_local_id(db, user, segment) for segment in command.path.split('/')),
        'body': visit(command.body),
        'branch_id': resolve_local_id(db, user, command.branch_id) if command.branch_id else None,
    })


def dispatch_admin(db, user, command):
    # Do not resolve an arbitrary URL to a route or bypass dependency permissions.
    from app.api.v1 import atributos as attributes, proveedores as suppliers, promociones as promotions, temporadas as seasons, productos as products, sucursales as branches, usuarios as users, inventario as inventory, stocks
    from app.esquemas import atributo_catalogo as attrs
    from app.esquemas.proveedor import ProveedorCreate, ProveedorUpdate, ProveedorResponse
    from app.esquemas.promocion import PromocionCreate, PromocionUpdate, PromocionResponse
    from app.esquemas.temporada import TemporadaCreate, TemporadaUpdate, TemporadaResponse
    from app.esquemas.producto import ProductoCreate, ProductoUpdate, ProductoResponse
    from app.esquemas.sucursal import SucursalCreate, SucursalUpdate, SucursalResponse, AsignarPersonalRequest
    from app.esquemas.usuario import UsuarioCreateAdmin, UsuarioUpdateAdmin, UsuarioUpdate, UsuarioResponse
    from app.esquemas.movimiento_inventario import MovimientoInventarioCreate, MovimientoInventarioUpdate, MovimientoInventarioResponse
    from app.esquemas.stock import AjusteStockRequest, StockResponse
    from app.esquemas.comun import MensajeResponse

    resources = [
        ('/suppliers', suppliers, 'supplier', ProveedorCreate, ProveedorUpdate, ProveedorResponse, ('ADMIN', 'STORE_MANAGER')),
        ('/promotions', promotions, 'promotion', PromocionCreate, PromocionUpdate, PromocionResponse, ('ADMIN', 'STORE_MANAGER')),
        ('/seasons', seasons, 'season', TemporadaCreate, TemporadaUpdate, TemporadaResponse, ('ADMIN', 'STORE_MANAGER')),
        ('/products', products, 'product', ProductoCreate, ProductoUpdate, ProductoResponse, ('ADMIN', 'STORE_MANAGER')),
        ('/branches', branches, 'branch', SucursalCreate, SucursalUpdate, SucursalResponse, ('ADMIN',)),
        ('/users', users, 'user', UsuarioCreateAdmin, UsuarioUpdateAdmin, UsuarioResponse, ('ADMIN',)),
    ]
    for plural, singular, create, update, response in [
        ('categories', 'category', attrs.CategoriaCreate, attrs.CategoriaUpdate, attrs.CategoriaResponse),
        ('sizes', 'size', attrs.TallaCreate, attrs.TallaUpdate, attrs.TallaResponse),
        ('colors', 'color', attrs.ColorCreate, attrs.ColorUpdate, attrs.ColorResponse),
    ]:
        resources.append(('/attributes/' + plural, attributes, singular, create, update, response, ('ADMIN', 'STORE_MANAGER')))

    path, method = command.path, command.method
    if path == '/users/me' and method == 'PUT':
        return users.update_me(UsuarioUpdate.model_validate(command.body), user, db).model_dump(mode='json')
    if path == '/inventory/movements' and method == 'POST':
        require_role(user, ('ADMIN', 'STORE_MANAGER'))
        data = MovimientoInventarioCreate.model_validate(command.body)
        if data.payment_method == 'PAYPAL':
            raise HTTPException(422, 'PayPal requiere conexión y confirmación del proveedor de pago.')
        if data.type.value == 'ADJUSTMENT':
            check_stock_baseline(db, command.body)
        return MovimientoInventarioResponse.model_validate(inventory.create_movement(data, db, user)).model_dump(mode='json')
    movement = re.fullmatch(r'/inventory/movements/([^/]+)', path)
    if movement and method in ('PUT', 'DELETE'):
        require_role(user, ('ADMIN', 'STORE_MANAGER'))
        result = inventory.update_movement(movement[1], MovimientoInventarioUpdate.model_validate(command.body), db, user) if method == 'PUT' else inventory.delete_movement(movement[1], db, user)
        return (MovimientoInventarioResponse if method == 'PUT' else MensajeResponse).model_validate(result).model_dump(mode='json')
    if path == '/stocks/adjust' and method == 'POST':
        require_role(user, ('ADMIN', 'STORE_MANAGER'))
        check_stock_baseline(db, command.body)
        return StockResponse.model_validate(stocks.adjust_stock(AjusteStockRequest.model_validate(command.body), db, user)).model_dump(mode='json')
    staff = re.fullmatch(r'/branches/([^/]+)/staff(?:/([^/]+))?', path)
    if staff and ((method == 'POST' and not staff[2]) or (method == 'DELETE' and staff[2])):
        require_role(user, ('ADMIN',))
        result = branches.assign_staff(staff[1], AsignarPersonalRequest.model_validate(command.body), db, user) if method == 'POST' else branches.remove_staff(staff[1], staff[2], db, user)
        return SucursalResponse.model_validate(result).model_dump(mode='json')
    for prefix, module, singular, create_schema, update_schema, response_schema, roles in resources:
        if path != prefix and not path.startswith(prefix + '/'):
            continue
        require_role(user, roles)
        kwargs = {'db': db, 'current_user': user}
        if path == prefix and method == 'POST':
            fn = getattr(module, 'create_' + singular)
            kwargs['payload' if singular == 'product' else 'request'] = create_schema.model_validate(command.body)
        else:
            match = re.fullmatch(re.escape(prefix) + r'/([^/]+)(/toggle-status)?', path)
            if not match or (method, bool(match[2])) not in [('PUT', False), ('PATCH', True)]:
                break
            kwargs[singular + '_id'] = match[1]
            if method == 'PUT':
                fn = getattr(module, 'update_' + singular)
                kwargs['payload' if singular == 'product' else 'request'] = update_schema.model_validate(command.body)
            else:
                name = ('toggle_' + singular + '_status') if module == attributes else ('toggle_branch_status' if singular == 'branch' else ('toggle_user_status' if singular == 'user' else 'toggle_status'))
                fn = getattr(module, name)
        result = response_schema.model_validate(fn(**kwargs)).model_dump(mode='json')
        ids = {'local-' + str(command.operation_id): result['id']}
        if prefix == '/products' and method == 'POST':
            for index, variant in enumerate(command.body.get('variants', [])):
                resolved = next(v for v in result['variants'] if v['size_id'] == variant['size_id'] and v['color_id'] == variant['color_id'])
                ids[f'local-{command.operation_id}-variant-{index}'] = resolved['id']
        result['_local_ids'] = ids
        return result
    raise HTTPException(422, 'Esta acción no admite sincronización diferida.')


def require_role(user, roles):
    if user.role not in roles:
        raise HTTPException(403, 'Tu rol no permite realizar esta operación.')


def check_stock_baseline(db, body):
    from app.modelos.stock import Stock
    stock = db.query(Stock).filter_by(branch_id=body.get('branch_id'), variant_id=body.get('variant_id')).with_for_update().first()
    if '_base_quantity' not in body or body['_base_quantity'] != (stock.quantity if stock else 0):
        raise HTTPException(409, 'El stock cambió desde la descarga. Revisa el ajuste antes de confirmarlo.')
