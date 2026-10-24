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
from app.nucleo.ambito_sucursal import resolve_branch
from app.configuracion import settings
from app.esquemas.reporte import ReporteRequest, ReporteResponse


REPORT_TITLES = {
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


class ReporteService:
    @classmethod
    def generate(cls, db: Session, request: ReporteRequest, user: Usuario | None = None) -> ReporteResponse:
        request = request.model_copy(deep=True)
        if user is not None:
            request.branch_id = resolve_branch(user, request.branch_id)
        if request.branch_id and not db.query(Sucursal).filter(Sucursal.id == request.branch_id).first():
            raise SolicitudInvalidaException(detail="La sucursal seleccionada no existe")
        if request.date_from and request.date_to and request.date_from > request.date_to:
            raise SolicitudInvalidaException(detail="La fecha inicial debe ser anterior o igual a la fecha final")
        handlers = {
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
        handler = handlers.get(request.report_type)
        if not handler:
            raise SolicitudInvalidaException(
                detail=f"Tipo de reporte no válido. Opciones: {', '.join(handlers)}"
            )
        columns, rows, summary = handler(db, request)
        scope = db.query(Sucursal).filter(Sucursal.id == request.branch_id).first() if request.branch_id else None
        summary["scope"] = scope.name if scope else "Todas las sucursales"
        return ReporteResponse(
            report_type=request.report_type,
            title=REPORT_TITLES[request.report_type],
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
        if request.status:
            query = query.filter(Reserva.status == request.status.upper())
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
        if request.branch_id:
            query = query.filter(Usuario.id.in_(db.query(Reserva.customer_id).filter(Reserva.branch_id == request.branch_id)))
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
            add(reservation.branch_id, settings.PAYPAL_CURRENCY, reservation.total_amount,
                sum(item.quantity for item in reservation.items))
        rows = [{"branch": branches[b].name if b in branches else b, "currency": currency,
                 "sales": value["sales"], "units": value["units"], "amount": float(value["amount"])}
                for (b, currency), value in grouped.items()]
        rows.sort(key=lambda row: (row["currency"], -row["amount"], row["branch"]))
        summary = {"sales": sum(row["sales"] for row in rows), "units": sum(row["units"] for row in rows)}
        for currency in sorted({row["currency"] for row in rows}):
            currency_rows = [row for row in rows if row["currency"] == currency]
            summary[f"leader_{currency}"] = currency_rows[0]["branch"]
            summary[f"total_{currency}"] = float(sum((Decimal(str(row["amount"])) for row in currency_rows), Decimal("0")))
        return ["branch", "currency", "sales", "units", "amount"], rows, summary
