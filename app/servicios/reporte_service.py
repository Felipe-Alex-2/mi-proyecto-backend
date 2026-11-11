from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session, joinedload

from app.nucleo.excepciones import SolicitudInvalidaException
from app.modelos.sucursal import Sucursal
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.reserva import Reserva
from app.modelos.stock import Stock
from app.modelos.usuario import Usuario, RolUsuario
from app.modelos.pago import Pago
from app.configuracion import settings
from app.esquemas.reporte import ReporteRequest, ReporteResponse


REPORT_TITLES = {
    "products_detail": "Detalle de prendas en stock",
    "payments_detail": "Detalle de pagos",
    "wallet_topups": "Recargas de wallet",
    "inventory_by_branch": "Stock disponible por sucursal",
    "products_by_category": "Productos por categoría",
    "products_by_season": "Productos por temporada",
    "low_stock": "Alertas de stock bajo",
    "reservations_status": "Estado actual de reservas",
    "reservations_by_branch": "Reservas por sucursal",
    "products_by_supplier": "Catálogo por proveedor",
    "registered_customers": "Clientes registrados",
    "sales_by_branch": "Ventas cobradas por sucursal",
}
from app.servicios.reporte_datos_service import CATALOG, generate_facts
REPORT_TITLES.update({key:spec['title'] for key,spec in CATALOG.items()})


class ReporteService:
    @classmethod
    def generate(cls, db: Session, request: ReporteRequest, user: Usuario | None = None) -> ReporteResponse:
        if request.report_type in ('companies_list','branches_list'):
            from app.servicios.reporte_directorio_service import directory
            return directory(db,request,user)
        if user is not None:
            from app.servicios.reporte_global_service import generate_global
            return generate_global(db, request, user)
        request = request.model_copy(deep=True)
        if request.branch_id and not db.query(Sucursal).filter(Sucursal.id == request.branch_id).first():
            raise SolicitudInvalidaException(detail="La sucursal seleccionada no existe")
        if request.date_from and request.date_to and request.date_from > request.date_to:
            raise SolicitudInvalidaException(detail="La fecha inicial debe ser anterior o igual a la fecha final")
        if (request.date_from or request.date_to) and request.report_type in ('inventory_by_branch','products_detail','products_by_category','products_by_season','products_by_supplier','low_stock'):
            raise SolicitudInvalidaException(detail='El inventario muestra existencias actuales; no hay un corte histórico de stock para esas fechas. Consulta ventas o pagos del periodo.')
        handlers = {
            "products_detail": cls._products_detail,
            "payments_detail": cls._payments_detail,
            "wallet_topups": cls._wallet_topups,
            "inventory_by_branch": cls._inventory_by_branch,
            "products_by_category": cls._products_by_category,
            "products_by_season": cls._products_by_season,
            "low_stock": cls._low_stock,
            "reservations_status": cls._reservations_status,
            "reservations_by_branch": cls._reservations_by_branch,
            "products_by_supplier": cls._products_by_supplier,
            "registered_customers": cls._registered_customers,
            "sales_by_branch": cls._sales_by_branch,
        }
        handler = generate_facts if request.report_type in CATALOG else handlers.get(request.report_type)
        if not handler:
            raise SolicitudInvalidaException(
                detail=f"Tipo de reporte no válido. Opciones: {', '.join(handlers)}"
            )
        columns, rows, summary = handler(db, request)
        from app.servicios.reporte_plan_service import shape
        columns,rows,summary=shape(request,columns,rows,summary)
        scope = db.query(Sucursal).filter(Sucursal.id == request.branch_id).first() if request.branch_id else None
        summary["scope"] = scope.name if scope else "Todas las sucursales"
        from app.servicios.reporte_periodo_service import report_metadata
        title = report_metadata(request, summary, rows, request.report_title or REPORT_TITLES[request.report_type])
        return ReporteResponse(
            customer_id=request._customer_id,
            branch_id=request.branch_id,
            report_type=request.report_type,
            title=({'sales_by_branch':'Mis compras por sucursal','reservations_status':'Estado de mis reservas','reservations_by_branch':'Mis reservas por sucursal','registered_customers':'Mi cuenta registrada'}.get(request.report_type,title) if request._customer_id else title),
            generated_by="manual",
            summary=summary,
            columns=columns,
            rows=rows,
        )

    @staticmethod
    def _active_products(db: Session, request: ReporteRequest) -> List[Producto]:
        query = db.query(Producto).options(
            joinedload(Producto.category),
            joinedload(Producto.season),
            joinedload(Producto.supplier),
            joinedload(Producto.variants).joinedload(VarianteProducto.stocks),
        ).filter(Producto.is_active == True)
        if request.category_id:
            query = query.filter(Producto.category_id == request.category_id)
        if request.season_id:
            query = query.filter(Producto.season_id == request.season_id)
        if request.supplier_id:
            query = query.filter(Producto.supplier_id == request.supplier_id)
        if request.search:
            term = f"%{request.search.strip()}%"
            query = query.filter(Producto.name.ilike(term))
        if request.branch_id:
            query = query.filter(Producto.variants.any(VarianteProducto.stocks.any(Stock.branch_id == request.branch_id)))
        return query.order_by(Producto.name.asc()).all()

    @staticmethod
    def _stocks(product, request):
        return (stock for variant in product.variants for stock in variant.stocks
                if not request.branch_id or stock.branch_id == request.branch_id)

    @classmethod
    def _inventory_by_branch(cls, db: Session, request: ReporteRequest):
        branches = db.query(Sucursal).filter(Sucursal.is_active == True).order_by(Sucursal.name.asc()).all()
        if request.branch_id:
            branches = [branch for branch in branches if branch.id == request.branch_id]
        products = cls._active_products(db, request)
        quantities = defaultdict(int)
        variant_count = defaultdict(int)
        for product in products:
            for variant in product.variants:
                for stock in variant.stocks:
                    quantities[stock.branch_id] += stock.quantity
                    if stock.quantity > 0:
                        variant_count[stock.branch_id] += 1
        rows = [
            {"branch": branch.name, "city": branch.city, "units": quantities[branch.id], "variants_in_stock": variant_count[branch.id]}
            for branch in branches
        ]
        rows.sort(key=lambda row: (-row["units"], row["branch"]))
        return ["branch", "city", "units", "variants_in_stock"], rows, {
            "branches": len(rows), "total_units": sum(row["units"] for row in rows),
            "most_stock_branch": rows[0]["branch"] if rows and rows[0]["units"] > 0 else "Sin existencias"
        }

    @classmethod
    def _products_by_category(cls, db: Session, request: ReporteRequest):
        products = cls._active_products(db, request)
        grouped = defaultdict(lambda: {"products": 0, "units": 0})
        for product in products:
            key = product.category.name if product.category else "Sin categoría"
            grouped[key]["products"] += 1
            grouped[key]["units"] += sum(stock.quantity for stock in cls._stocks(product, request))
        rows = [{"category": key, **value} for key, value in sorted(grouped.items())]
        return ["category", "products", "units"], rows, {"categories": len(rows), "products": len(products)}

    @classmethod
    def _products_by_season(cls, db: Session, request: ReporteRequest):
        products = cls._active_products(db, request)
        grouped = defaultdict(lambda: {"products": 0, "units": 0})
        for product in products:
            key = product.season.name if product.season else "Sin temporada"
            grouped[key]["products"] += 1
            grouped[key]["units"] += sum(stock.quantity for stock in cls._stocks(product, request))
        rows = [{"season": key, **value} for key, value in sorted(grouped.items())]
        return ["season", "products", "units"], rows, {"seasons": len(rows), "products": len(products)}

    @classmethod
    def _low_stock(cls, db: Session, request: ReporteRequest):
        products = cls._active_products(db, request)
        rows = []
        for product in products:
            for variant in product.variants:
                for stock in variant.stocks:
                    if request.branch_id and stock.branch_id != request.branch_id:
                        continue
                    threshold = max(request.low_stock_threshold, stock.min_alert_threshold)
                    if stock.quantity <= threshold:
                        rows.append({
                            "product": product.name,
                            "sku": variant.sku,
                            "branch": stock.branch.name if stock.branch else stock.branch_id,
                            "quantity": stock.quantity,
                            "threshold": threshold,
                        })
        rows.sort(key=lambda row: (row["quantity"], row["product"]))
        return ["product", "sku", "branch", "quantity", "threshold"], rows, {"alerts": len(rows), "threshold": request.low_stock_threshold}

    @staticmethod
    def _reservations(db: Session, request: ReporteRequest) -> List[Reserva]:
        query = db.query(Reserva).options(joinedload(Reserva.branch), joinedload(Reserva.customer))
        if request.branch_id:
            query = query.filter(Reserva.branch_id == request.branch_id)
        if request._customer_id:
            query = query.filter(Reserva.customer_id == request._customer_id)
        if request.status:
            query = query.filter(Reserva.status == request.status.upper())
        from app.servicios.reporte_periodo_service import utc_bounds
        start, end = utc_bounds(request)
        if start: query = query.filter(Reserva.created_at >= start)
        if end: query = query.filter(Reserva.created_at < end)
        return query.order_by(Reserva.created_at.desc()).all()

    @classmethod
    def _reservations_status(cls, db: Session, request: ReporteRequest):
        grouped = defaultdict(int)
        for reservation in cls._reservations(db, request):
            grouped[reservation.status] += 1
        rows = [{"status": key, "reservations": value} for key, value in sorted(grouped.items())]
        return ["status", "reservations"], rows, {"total": sum(grouped.values())}

    @classmethod
    def _reservations_by_branch(cls, db: Session, request: ReporteRequest):
        grouped = defaultdict(int)
        for reservation in cls._reservations(db, request):
            grouped[reservation.branch.name if reservation.branch else reservation.branch_id] += 1
        rows = [{"branch": key, "reservations": value} for key, value in sorted(grouped.items())]
        return ["branch", "reservations"], rows, {"total": sum(grouped.values())}

    @classmethod
    def _products_by_supplier(cls, db: Session, request: ReporteRequest):
        products = cls._active_products(db, request)
        grouped = defaultdict(list)
        for product in products:
            supplier = product.supplier.company_name if product.supplier else "Sin proveedor"
            grouped[supplier].append(product.name)
        rows = [{"supplier": key, "products": len(value), "product_names": ", ".join(value)} for key, value in sorted(grouped.items())]
        return ["supplier", "products", "product_names"], rows, {"suppliers": len(rows), "products": len(products)}

    @staticmethod
    def _registered_customers(db: Session, request: ReporteRequest):
        query = db.query(Usuario).filter(Usuario.role == RolUsuario.CUSTOMER.value, Usuario.is_active == True)
        if request._customer_id:
            query = query.filter(Usuario.id == request._customer_id)
        if request.branch_id and not request._customer_id:
            query = query.filter(Usuario.id.in_(db.query(Reserva.customer_id).filter(Reserva.branch_id == request.branch_id)))
        if request.search:
            from sqlalchemy import or_
            query=query.filter(or_(Usuario.full_name.ilike('%'+request.search+'%'),Usuario.email.ilike('%'+request.search+'%')))
        from app.servicios.reporte_periodo_service import utc_bounds
        start, end = utc_bounds(request)
        if start: query = query.filter(Usuario.created_at >= start)
        if end: query = query.filter(Usuario.created_at < end)
        customers = query.order_by(Usuario.created_at.desc()).all()
        rows = [{"customer": customer.full_name, "email": customer.email, "registered_at": customer.created_at} for customer in customers]
        return ["customer", "email", "registered_at"], rows, {"customers": len(rows)}

    @staticmethod
    def _sales_by_branch(db: Session, request: ReporteRequest):
        payments = db.query(Pago).options(joinedload(Pago.reservation).joinedload(Reserva.items)).filter(Pago.status == "PAID")
        # A reservation paid from mobile may not have a corresponding cash-desk Pago.
        paid_reservation_ids = db.query(Pago.reservation_id).filter(Pago.status == "PAID", Pago.reservation_id.isnot(None))
        reservations = db.query(Reserva).options(joinedload(Reserva.items)).filter(
            Reserva.payment_status == "PAID", ~Reserva.id.in_(paid_reservation_ids))
        if request.branch_id:
            payments = payments.filter(Pago.branch_id == request.branch_id)
            reservations = reservations.filter(Reserva.branch_id == request.branch_id)
        if request._customer_id:
            payments = payments.filter(Pago.customer_id == request._customer_id)
            reservations = reservations.filter(Reserva.customer_id == request._customer_id)
        business_timezone = timezone(timedelta(hours=-4))  # America/La_Paz
        start = datetime.combine(request.date_from, time.min, business_timezone).astimezone(timezone.utc) if request.date_from else None
        end = datetime.combine(request.date_to + timedelta(days=1), time.min, business_timezone).astimezone(timezone.utc) if request.date_to else None
        if start:
            payments = payments.filter(Pago.paid_at >= start)
            reservations = reservations.filter(Reserva.paid_at >= start)
        if end:
            payments = payments.filter(Pago.paid_at < end)
            reservations = reservations.filter(Reserva.paid_at < end)
        grouped = defaultdict(lambda: {"sales": 0, "units": 0, "amount": Decimal("0")})
        branches = {branch.id: branch for branch in db.query(Sucursal).all()}
        def add(branch_id, currency, amount, units):
            row = grouped[(branch_id, currency)]
            row["sales"] += 1
            row["units"] += units
            row["amount"] += Decimal(str(amount or 0))
        for payment in payments.all():
            try:
                items = json.loads(payment.items_detail or "[]")
                units = sum(int(item.get("quantity", 0)) for item in items)
            except (ValueError, TypeError, AttributeError):
                units = 0
            if payment.reservation:
                units = sum(item.quantity for item in payment.reservation.items)
            add(payment.branch_id, payment.currency, payment.amount, units)
        for reservation in reservations.all():
            add(reservation.branch_id, 'USD' if reservation.payment_method=='WALLET' else settings.PAYPAL_CURRENCY, reservation.total_amount,
                sum(item.quantity for item in reservation.items))
        # Compare against the complete branch universe, including stores with no
        # paid transactions in the requested period. Never create a fake sale.
        currencies = {currency for _, currency in grouped} or {settings.PAYPAL_CURRENCY}
        for branch in branches.values():
            if branch.is_active and (not request.branch_id or branch.id == request.branch_id):
                for currency in currencies:
                    grouped[(branch.id, currency)]
        rows = [{"branch": branches[b].name if b in branches else b, "branch_id": b, "currency": currency,
                 "sales": value["sales"], "units": value["units"], "amount": float(value["amount"])}
                for (b, currency), value in grouped.items()]
        rows.sort(key=lambda row: (row["currency"], -row["amount"], row["branch"]))
        summary = {"sales": sum(row["sales"] for row in rows), "units": sum(row["units"] for row in rows)}
        for currency in sorted({row["currency"] for row in rows}):
            currency_rows = [row for row in rows if row["currency"] == currency]
            summary[f"leader_{currency}"] = currency_rows[0]["branch"]
            summary[f"total_{currency}"] = float(sum((Decimal(str(row["amount"])) for row in currency_rows), Decimal("0")))
        return ["branch", "currency", "sales", "units", "amount"], rows, summary


    @staticmethod
    def _payments_detail(db, request):
        from app.servicios.historial_service import history
        if request._customer_id:
            from types import SimpleNamespace
            rows=history(db,SimpleNamespace(id=request._customer_id))
            rows=[r for r in rows if r['tenant_id']==db.info.get('tenant_id') and r['source']!='wallet_topup']
            if request.branch_id:
                branch=db.query(Sucursal).filter(Sucursal.id==request.branch_id).first()
                rows=[r for r in rows if r['branch_name']==branch.name]
        else:
            query=db.query(Pago)
            if request.branch_id:query=query.filter(Pago.branch_id==request.branch_id)
            rows=[dict(payment_code=p.payment_code,amount=float(p.amount),currency=p.currency,status=p.status,
                payment_type=p.payment_type,paid_at=p.paid_at,created_at=p.created_at,branch=p.branch.name if p.branch else '',customer=p.customer_name) for p in query.all()]
            linked=db.query(Pago.reservation_id).filter(Pago.reservation_id.isnot(None))
            reservations=db.query(Reserva).filter(Reserva.payment_status=='PAID',~Reserva.id.in_(linked))
            if request.branch_id:reservations=reservations.filter(Reserva.branch_id==request.branch_id)
            rows += [dict(payment_code=r.reservation_code,amount=float(r.total_amount),
                currency='USD' if r.payment_method=='WALLET' else settings.PAYPAL_CURRENCY,status='PAID',
                payment_type=r.payment_method,paid_at=r.paid_at,created_at=r.created_at,branch=r.branch.name if r.branch else '',customer=r.customer.full_name if r.customer else '') for r in reservations.all()]
        rows=ReporteService._filter_transactions(rows,request)
        from app.servicios.reporte_datos_service import dates
        rows=[{**r,**dates(r.get('paid_at') or r.get('created_at'))} for r in rows]
        columns=['payment_code','amount','currency','status','payment_type','paid_at','branch','customer','day','week','month','year']
        rows=[{k:(float(r[k]) if k=='amount' else str(r[k]) if k=='paid_at' and r.get(k) else r.get(k)) for k in columns} for r in rows]
        return columns,rows,{'records':len(rows)}

    @staticmethod
    def _filter_transactions(rows,request):
        result=[]
        for r in rows:
            stamp=r.get('paid_at') or r.get('created_at')
            stamp=stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
            date=stamp.astimezone(timezone(timedelta(hours=-4))).date()
            if request.date_from and date < request.date_from:continue
            if request.date_to and date > request.date_to:continue
            if request.status and r['status']!=request.status:continue
            if request.payment_method and r.get('payment_type')!=request.payment_method:continue
            if request.search and request.search.casefold() not in str(r).casefold():continue
            result.append(r)
        return result

    @staticmethod
    def _wallet_topups(db,request):
        from app.modelos.wallet import RecargaWallet
        from fastapi import HTTPException
        if not request._customer_id and request.branch_id:
            raise HTTPException(422,'Las recargas pertenecen a la empresa. Selecciona todas las sucursales.')
        query=db.query(RecargaWallet)
        if request._customer_id:query=query.filter(RecargaWallet.customer_id==request._customer_id)
        rows=[dict(payment_code='WAL-'+t.id.upper(),amount=t.amount,currency='USD',status=t.status,
            paid_at=t.paid_at,created_at=t.created_at) for t in query.all()]
        rows=ReporteService._filter_transactions(rows,request)
        columns=['payment_code','amount','currency','status','paid_at']
        return columns,[{k:(str(r[k]) if k=='paid_at' and r.get(k) else r.get(k)) for k in columns} for r in rows],{'records':len(rows)}


    @classmethod
    def _products_detail(cls,db,request):
        import unicodedata
        def normalized(value):
            return ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if unicodedata.category(c)!='Mn')
        source=request.model_copy(update={'search':None})
        rows=[]
        for p in cls._active_products(db,source):
            for v in p.variants:
                if not v.is_active:continue
                if request.color and normalized(request.color)!=normalized(v.color.name):continue
                if request.size and normalized(request.size) not in (normalized(v.size.name),normalized(v.size.code)):continue
                price=float(v.price_override if v.price_override is not None else p.price)
                if request.min_price is not None and price<request.min_price:continue
                if request.max_price is not None and price>request.max_price:continue
                for stock in v.stocks:
                    if request.branch_id and stock.branch_id!=request.branch_id:continue
                    row=dict(product=p.name,sku=v.sku,color=v.color.name,size=v.size.name,price=price,
                        units=stock.quantity,current_value=round(price*stock.quantity,2),branch=stock.branch.name,category=p.category.name if p.category else '',
                        season=p.season.name if p.season else '')
                    if request.search and request.search.casefold() not in str(row).casefold():continue
                    rows.append(row)
        return ['product','sku','color','size','price','units','current_value','branch','category','season'],rows,{'records':len(rows)}
