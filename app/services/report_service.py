from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import BadRequestException
from app.models.branch import Branch
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.reservation import Reservation
from app.models.stock import Stock
from app.models.user import User, UserRole
from app.schemas.report import ReportRequest, ReportResponse


REPORT_TITLES = {
    "inventory_by_branch": "Stock disponible por sucursal",
    "products_by_category": "Productos por categoría",
    "products_by_season": "Productos por temporada",
    "low_stock": "Alertas de stock bajo",
    "reservations_status": "Estado actual de reservas",
    "reservations_by_branch": "Reservas por sucursal",
    "products_by_supplier": "Catálogo por proveedor",
    "registered_customers": "Clientes registrados",
}


class ReportService:
    @classmethod
    def generate(cls, db: Session, request: ReportRequest) -> ReportResponse:
        handlers = {
            "inventory_by_branch": cls._inventory_by_branch,
            "products_by_category": cls._products_by_category,
            "products_by_season": cls._products_by_season,
            "low_stock": cls._low_stock,
            "reservations_status": cls._reservations_status,
            "reservations_by_branch": cls._reservations_by_branch,
            "products_by_supplier": cls._products_by_supplier,
            "registered_customers": cls._registered_customers,
        }
        handler = handlers.get(request.report_type)
        if not handler:
            raise BadRequestException(
                detail=f"Tipo de reporte no válido. Opciones: {', '.join(handlers)}"
            )
        columns, rows, summary = handler(db, request)
        return ReportResponse(
            report_type=request.report_type,
            title=REPORT_TITLES[request.report_type],
            generated_by="manual",
            summary=summary,
            columns=columns,
            rows=rows,
        )

    @staticmethod
    def _active_products(db: Session, request: ReportRequest) -> List[Product]:
        query = db.query(Product).options(
            joinedload(Product.category),
            joinedload(Product.season),
            joinedload(Product.supplier),
            joinedload(Product.variants).joinedload(ProductVariant.stocks),
        ).filter(Product.is_active == True)
        if request.category_id:
            query = query.filter(Product.category_id == request.category_id)
        if request.season_id:
            query = query.filter(Product.season_id == request.season_id)
        if request.supplier_id:
            query = query.filter(Product.supplier_id == request.supplier_id)
        if request.search:
            term = f"%{request.search.strip()}%"
            query = query.filter(Product.name.ilike(term))
        return query.order_by(Product.name.asc()).all()

    @classmethod
    def _inventory_by_branch(cls, db: Session, request: ReportRequest):
        branches = db.query(Branch).filter(Branch.is_active == True).order_by(Branch.name.asc()).all()
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
        return ["branch", "city", "units", "variants_in_stock"], rows, {
            "branches": len(rows), "total_units": sum(row["units"] for row in rows)
        }

    @classmethod
    def _products_by_category(cls, db: Session, request: ReportRequest):
        products = cls._active_products(db, request)
        grouped = defaultdict(lambda: {"products": 0, "units": 0})
        for product in products:
            key = product.category.name if product.category else "Sin categoría"
            grouped[key]["products"] += 1
            grouped[key]["units"] += sum(stock.quantity for variant in product.variants for stock in variant.stocks)
        rows = [{"category": key, **value} for key, value in sorted(grouped.items())]
        return ["category", "products", "units"], rows, {"categories": len(rows), "products": len(products)}

    @classmethod
    def _products_by_season(cls, db: Session, request: ReportRequest):
        products = cls._active_products(db, request)
        grouped = defaultdict(lambda: {"products": 0, "units": 0})
        for product in products:
            key = product.season.name if product.season else "Sin temporada"
            grouped[key]["products"] += 1
            grouped[key]["units"] += sum(stock.quantity for variant in product.variants for stock in variant.stocks)
        rows = [{"season": key, **value} for key, value in sorted(grouped.items())]
        return ["season", "products", "units"], rows, {"seasons": len(rows), "products": len(products)}

    @classmethod
    def _low_stock(cls, db: Session, request: ReportRequest):
        products = cls._active_products(db, request)
        rows = []
        for product in products:
            for variant in product.variants:
                for stock in variant.stocks:
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
    def _reservations(db: Session, request: ReportRequest) -> List[Reservation]:
        query = db.query(Reservation).options(joinedload(Reservation.branch), joinedload(Reservation.customer))
        if request.branch_id:
            query = query.filter(Reservation.branch_id == request.branch_id)
        if request.status:
            query = query.filter(Reservation.status == request.status.upper())
        return query.order_by(Reservation.created_at.desc()).all()

    @classmethod
    def _reservations_status(cls, db: Session, request: ReportRequest):
        grouped = defaultdict(int)
        for reservation in cls._reservations(db, request):
            grouped[reservation.status] += 1
        rows = [{"status": key, "reservations": value} for key, value in sorted(grouped.items())]
        return ["status", "reservations"], rows, {"total": sum(grouped.values())}

    @classmethod
    def _reservations_by_branch(cls, db: Session, request: ReportRequest):
        grouped = defaultdict(int)
        for reservation in cls._reservations(db, request):
            grouped[reservation.branch.name if reservation.branch else reservation.branch_id] += 1
        rows = [{"branch": key, "reservations": value} for key, value in sorted(grouped.items())]
        return ["branch", "reservations"], rows, {"total": sum(grouped.values())}

    @classmethod
    def _products_by_supplier(cls, db: Session, request: ReportRequest):
        products = cls._active_products(db, request)
        grouped = defaultdict(list)
        for product in products:
            supplier = product.supplier.name if product.supplier else "Sin proveedor"
            grouped[supplier].append(product.name)
        rows = [{"supplier": key, "products": len(value), "product_names": ", ".join(value)} for key, value in sorted(grouped.items())]
        return ["supplier", "products", "product_names"], rows, {"suppliers": len(rows), "products": len(products)}

    @staticmethod
    def _registered_customers(db: Session, request: ReportRequest):
        customers = db.query(User).filter(User.role == UserRole.CUSTOMER.value, User.is_active == True).order_by(User.created_at.desc()).all()
        rows = [{"customer": customer.full_name, "email": customer.email, "registered_at": customer.created_at} for customer in customers]
        return ["customer", "email", "registered_at"], rows, {"customers": len(rows)}
