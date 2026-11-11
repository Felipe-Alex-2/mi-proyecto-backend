"""Business facts for composable reports. No model-generated SQL is executed."""
import json
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import func
from sqlalchemy.orm import joinedload, load_only

from app.configuracion import settings
from app.modelos.pago import Pago
from app.modelos.reserva import Reserva
from app.modelos.sucursal import Sucursal
from app.modelos.usuario import Usuario
from app.modelos.variante_producto import VarianteProducto
from app.modelos.producto import Producto
from app.servicios.reporte_periodo_service import utc_bounds

TIME_COLUMNS = ['day','week','month','year']
PRODUCT_COLUMNS = ['product','product_id','sku','color','size','category','season','supplier']
CATALOG = {
    'sales_items': {
        'title':'Prendas vendidas',
        'description':'Una fila por línea de venta efectivamente pagada. Para productos más/menos vendidos, ingresos por producto, talla/color/categoría/sucursal, ventas mensuales y clientes compradores. units=unidades; amount=importe neto asignado a la línea, NO precio actual del catálogo. count cuenta líneas; distinct payment_code cuenta compras.',
        'columns':['branch','branch_id','city','customer','customer_id','payment_code','payment_type','currency','paid_at',*TIME_COLUMNS,*PRODUCT_COLUMNS,'units','unit_price','amount'],
    },
    'reservations_detail': {
        'title':'Detalle de reservas', 'description':'Una fila por reserva, pagada o pendiente; estimated_amount NO significa dinero cobrado.',
        'columns':['branch','branch_id','customer','status','payment_status','payment_type','reservation_code','created_at',*TIME_COLUMNS,'units','estimated_amount'],
    },
    'inventory_movements': {
        'title':'Movimientos de inventario', 'description':'Entradas, salidas, ajustes y devoluciones de stock registrados; movement_type indica el tipo, units la cantidad del movimiento. No confundir con ventas pagadas.',
        'columns':['branch','branch_id',*PRODUCT_COLUMNS,'movement_type','units','previous_stock','new_stock','reason','created_at',*TIME_COLUMNS],
    },
    'deliveries_detail': {
        'title':'Detalle de delivery', 'description':'Pedidos de delivery, estado, repartidor y cotización. fee y distance_km pueden ser null si no hay ruta calculada. No hay medición de llegada real si no está registrada.',
        'columns':['branch','branch_id','status','courier','fee','distance_km','estimated_minutes','created_at',*TIME_COLUMNS],
    },
    'exchanges_detail': {
        'title':'Cambios de prendas', 'description':'Cambios efectivamente registrados; units prendas cambiadas, amount diferencia cobrada, NO devolución de dinero.',
        'columns':['branch','branch_id',*PRODUCT_COLUMNS,'units','amount','currency','created_at',*TIME_COLUMNS],
    },
    'loyalty_movements': {
        'title':'Movimientos de puntos', 'description':'Puntos ganados o canjeados por cliente. points es firmado: sumar obtiene saldo, filtrar points<0 obtiene canjes. No tiene sucursal propia.',
        'columns':['customer','customer_id','points','description','created_at',*TIME_COLUMNS],
    },
    'employees_detail': {
        'title':'Personal registrado', 'description':'Empleados: nombre, correo, rol, sucursal y activo. Nunca credenciales, contraseñas ni tokens.',
        'columns':['customer','email','role','branch','branch_id','active','created_at',*TIME_COLUMNS],
    },
}


def dates(stamp):
    if stamp is None:
        return dict.fromkeys(TIME_COLUMNS)
    if stamp.tzinfo is None:
        stamp=stamp.replace(tzinfo=timezone.utc)
    day=stamp.astimezone(timezone(timedelta(hours=-4))).date()
    return dict(day=day.isoformat(),week=(day-timedelta(days=day.weekday())).isoformat(),month=day.strftime('%Y-%m'),year=day.year)


def bounded(query, field, request):
    start,end=utc_bounds(request)
    if start is not None:query=query.filter(field>=start)
    if end is not None:query=query.filter(field<end)
    return query


def number(value):
    try:
        result=Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def line_list(value):
    try:
        result=json.loads(value or '[]')
        return [v for v in result if isinstance(v,dict)] if isinstance(result,list) else []
    except (ValueError, TypeError):
        return []


class BusinessFacts:
    def __init__(self,db,request):
        self.db,self.request=db,request
        self.branches={b.id:b for b in db.query(Sucursal).all()}
        self.users={u.id:u for u in db.query(Usuario).execution_options(skip_tenant=True).options(
            load_only(Usuario.id,Usuario.full_name,Usuario.email,Usuario.role,Usuario.branch_id,Usuario.is_active)).all()}
        self._variants=None

    def branch(self,branch_id):
        branch=self.branches.get(branch_id)
        return dict(branch=branch.name if branch else 'Sucursal no disponible',branch_id=branch_id,city=branch.city if branch else '')

    def product(self,line):
        if self._variants is None:
            self._variants={v.id:v for v in self.db.query(VarianteProducto).options(joinedload(VarianteProducto.product).defer(Producto.image_url)).all()}
        variant=self._variants.get(line.get('variant_id'))
        product=variant.product if variant else None
        return dict(product=line.get('product_name') or (product.name if product else 'Prenda sin identificación en el comprobante'),
            product_id=line.get('product_id') or (product.id if product else line.get('variant_id') or line.get('product_name') or ''),
            sku=line.get('sku') or (variant.sku if variant else ''),
            color=line.get('color') or (variant.color.name if variant and variant.color else ''),
            size=line.get('size') or (variant.size.code if variant and variant.size else ''),
            category=product.category.name if product and product.category else '',
            season=product.season.name if product and product.season else '',
            supplier=product.supplier.company_name if product and product.supplier else '')

    def sales_items(self):
        paid=self.db.query(Pago).filter(Pago.status=='PAID')
        linked=self.db.query(Pago.reservation_id).filter(Pago.status=='PAID',Pago.reservation_id.isnot(None))
        reservations=self.db.query(Reserva).options(joinedload(Reserva.items)).filter(Reserva.payment_status=='PAID',~Reserva.id.in_(linked))
        if self.request.branch_id:
            paid=paid.filter(Pago.branch_id==self.request.branch_id)
            reservations=reservations.filter(Reserva.branch_id==self.request.branch_id)
        if self.request._customer_id:
            paid=paid.filter(Pago.customer_id==self.request._customer_id)
            reservations=reservations.filter(Reserva.customer_id==self.request._customer_id)
        paid=bounded(paid,func.coalesce(Pago.paid_at,Pago.created_at),self.request)
        reservations=bounded(reservations,func.coalesce(Reserva.paid_at,Reserva.created_at),self.request)
        from app.modelos.delivery import PedidoDelivery
        deliveries={r.reservation_id:r for r in self.db.query(PedidoDelivery).all()}
        sources=[]
        for payment in paid.all():
            if (payment.reference or '').startswith(('CAMBIO:','DELIVERY:')):
                continue
            lines=line_list(payment.items_detail)
            if not lines and payment.reservation:
                lines=line_list(payment.reservation.receipt_items_detail) or [dict(variant_id=i.variant_id,quantity=i.quantity) for i in payment.reservation.items]
            total=Decimal(str(payment.amount))
            delivery=deliveries.get(payment.reservation_id)
            if delivery and not delivery.destination_maps_url and payment.reservation:
                total-=Decimal(str(payment.reservation.delivery_fee or 0))
            sources.append((payment.branch_id,payment.customer_id,payment.payment_code,payment.payment_type,payment.currency,payment.paid_at or payment.created_at,total,lines))
        for reservation in reservations.all():
            lines=line_list(reservation.receipt_items_detail) or [dict(variant_id=i.variant_id,quantity=i.quantity) for i in reservation.items]
            total=Decimal(str(reservation.total_amount or 0))
            delivery=deliveries.get(reservation.id)
            if delivery and not delivery.destination_maps_url:
                total-=Decimal(str(reservation.delivery_fee or 0))
            currency='USD' if reservation.payment_method=='WALLET' else settings.PAYPAL_CURRENCY
            sources.append((reservation.branch_id,reservation.customer_id,reservation.reservation_code,reservation.payment_method,currency,reservation.paid_at or reservation.created_at,total,lines))
        result=[]
        missing,unpriced=0,0
        for branch,customer,code,method,currency,stamp,total,lines in sources:
            valid=[]
            for line in lines:
                quantity=number(line.get('quantity'))
                if quantity is not None and quantity>0 and quantity==int(quantity):
                    valid.append((line,int(quantity)))
            if not valid:
                missing+=1
                continue
            weights=[number(line.get('subtotal')) if line.get('subtotal') is not None else
                     number(line.get('unit_price'))*quantity if number(line.get('unit_price')) is not None else None for line,quantity in valid]
            priced=all(w is not None and w>=0 for w in weights) and sum(w for w in weights if w is not None)>0
            if not priced:unpriced+=1
            cumulative=Decimal(0);previous=Decimal(0)
            for index,(line,quantity) in enumerate(valid):
                amount=None
                if priced:
                    cumulative+=weights[index]
                    target=(Decimal(str(total or 0))*cumulative/sum(weights)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
                    amount=target-previous;previous=target
                result.append({**self.branch(branch),**self.product(line),**dates(stamp),
                    'customer':self.users[customer].full_name if customer in self.users else '', 'customer_id':customer,
                    'payment_code':code,'payment_type':method,'currency':currency,'paid_at':stamp.isoformat(),
                    'units':quantity,'unit_price':float(amount/quantity) if amount is not None else None,
                    'amount':float(amount) if amount is not None else None})
        return result,dict(unitemized_sales=missing,unpriced_sales=unpriced)

    def events(self,kind):
        from app.modelos.movimiento_inventario import MovimientoInventario
        from app.modelos.aporte_propio import CambioPrenda,MovimientoPuntos
        from app.modelos.delivery import PedidoDelivery,CotizacionDelivery
        models={'reservations_detail':Reserva,'inventory_movements':MovimientoInventario,
            'deliveries_detail':PedidoDelivery,'exchanges_detail':CambioPrenda,'loyalty_movements':MovimientoPuntos,'employees_detail':Usuario}
        model=models[kind]
        query=bounded(self.db.query(model),model.created_at,self.request)
        if self.request.branch_id:
            if not hasattr(model,'branch_id'):
                from app.nucleo.excepciones import SolicitudInvalidaException
                raise SolicitudInvalidaException(detail='Los puntos pertenecen al cliente de la empresa; selecciona todas las sucursales.')
            query=query.filter(model.branch_id==self.request.branch_id)
        if self.request.status and hasattr(model,'status'):query=query.filter(model.status==self.request.status)
        if kind=='employees_detail':query=query.filter(Usuario.role!='CUSTOMER')
        quotes={q.id:q for q in self.db.query(CotizacionDelivery).all()} if kind=='deliveries_detail' else {}
        result=[]
        for event in query.all():
            row={**dates(event.created_at),'created_at':event.created_at.isoformat()}
            if hasattr(event,'branch_id'):row.update(self.branch(event.branch_id))
            user=self.users.get(getattr(event,'customer_id',None))
            if kind=='reservations_detail':row.update(customer=user.full_name if user else '',status=event.status,
                payment_status=event.payment_status,payment_type=event.payment_method,reservation_code=event.reservation_code,
                units=sum(i.quantity for i in event.items),estimated_amount=float(event.total_amount) if event.total_amount is not None else None)
            elif kind=='inventory_movements':row.update(self.product({'variant_id':event.variant_id}),movement_type=event.type,
                units=event.quantity,previous_stock=event.previous_stock,new_stock=event.new_stock,reason=event.reason)
            elif kind=='exchanges_detail':
                receipt=self.db.get(Pago,event.receipt_payment_id)
                row.update(self.product({'variant_id':event.new_variant_id}),units=event.quantity,amount=float(event.difference),currency=receipt.currency if receipt else None)
            elif kind=='loyalty_movements':row.update(customer=user.full_name if user else '',customer_id=event.customer_id,points=event.points,description=event.description)
            elif kind=='employees_detail':row.update(customer=event.full_name,email=event.email,role=event.role,active=event.is_active)
            elif kind=='deliveries_detail':
                quote=quotes.get(event.quote_id)
                row.update(status=event.status,courier=event.courier,fee=float(quote.fee_usd) if quote else None,
                    distance_km=quote.distance_meters/1000 if quote else None,estimated_minutes=quote.duration_seconds/60 if quote else None)
            result.append(row)
        return result,{}


def generate_facts(db,request):
    facts=BusinessFacts(db,request)
    rows,summary=facts.sales_items() if request.report_type=='sales_items' else facts.events(request.report_type)
    if request.report_type=='sales_items':
        if request.status not in (None,'PAID'):
            from app.nucleo.excepciones import SolicitudInvalidaException
            raise SolicitudInvalidaException(detail='Prendas vendidas incluye solo cobros confirmados; para pendientes consulta reservas o pagos.')
        if request.search:rows=[r for r in rows if request.search.casefold() in r['product'].casefold()]
        if request.color:rows=[r for r in rows if request.color.casefold()==r['color'].casefold()]
        if request.size:rows=[r for r in rows if request.size.casefold()==r['size'].casefold()]
        if request.payment_method:rows=[r for r in rows if r['payment_type']==request.payment_method]
        if request.min_price is not None:rows=[r for r in rows if r['unit_price'] is not None and r['unit_price']>=request.min_price]
        if request.max_price is not None:rows=[r for r in rows if r['unit_price'] is not None and r['unit_price']<=request.max_price]
    return CATALOG[request.report_type]['columns'],rows,dict(summary,records=len(rows))
