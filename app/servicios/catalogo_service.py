from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.stock import Stock
from app.modelos.categoria import Categoria
from app.modelos.talla import Talla
from app.modelos.color import Color
from app.modelos.temporada import Temporada
from app.modelos.sucursal import Sucursal
from app.esquemas.catalogo import (
    OpcionesFiltroCatalogo,
    DetalleProductoCatalogoResponse,
    VarianteProductoCatalogoResponse,
    StockVarianteSucursalCatalogo,
    ListaProductosCatalogoResponse,
)
from app.nucleo.excepciones import NoEncontradoException
from app.servicios.carga_productos import product_load_options


class CatalogoService:
    @staticmethod
    def _determine_stock_status(quantity: int, min_threshold: int = 5) -> str:
        if quantity <= 0:
            return "OUT_OF_STOCK"
        elif quantity <= min_threshold:
            return "LOW_STOCK"
        return "IN_STOCK"

    @classmethod
    def get_filter_options(cls, db: Session) -> OpcionesFiltroCatalogo:
        categories = (
            db.query(Categoria)
            .filter(Categoria.is_active == True)
            .order_by(Categoria.name.asc())
            .all()
        )
        sizes = db.query(Talla).filter(Talla.is_active == True).order_by(Talla.name.asc()).all()
        colors = db.query(Color).filter(Color.is_active == True).order_by(Color.name.asc()).all()
        seasons = db.query(Temporada).filter(Temporada.is_active == True).order_by(Temporada.name.asc()).all()
        branches = db.query(Sucursal).filter(Sucursal.is_active == True).order_by(Sucursal.name.asc()).all()

        min_max = db.query(func.min(Producto.price), func.max(Producto.price)).filter(Producto.is_active == True).first()
        min_p = float(min_max[0]) if (min_max and min_max[0] is not None) else 0.0
        max_p = float(min_max[1]) if (min_max and min_max[1] is not None) else 1000.0

        return OpcionesFiltroCatalogo(
            categories=[{"id": c.id, "name": c.name, "description": c.description} for c in categories],
            sizes=[{"id": s.id, "name": s.name, "code": s.code} for s in sizes],
            colors=[{"id": c.id, "name": c.name, "hex_code": c.hex_code} for c in colors],
            seasons=[{"id": s.id, "name": s.name, "description": s.description} for s in seasons],
            branches=[{"id": b.id, "name": b.name, "city": b.city, "address": b.address} for b in branches],
            genders=["Hombre", "Mujer", "Unisex", "Niños"],
            min_price=min_p,
            max_price=max_p,
        )

    @classmethod
    def _format_product(cls, db: Session, product: Producto, active_branches: List[Sucursal]) -> DetalleProductoCatalogoResponse:
        variants_resp: List[VarianteProductoCatalogoResponse] = []
        unique_colors: Dict[str, Dict[str, str]] = {}
        unique_sizes: Dict[str, Dict[str, str]] = {}
        total_product_stock = 0

        for v in product.variants:
            stocks_by_branch = {
                s.branch_id: s for s in v.stocks
            }

            branch_stocks: List[StockVarianteSucursalCatalogo] = []
            variant_stock_sum = 0

            for b in active_branches:
                stk = stocks_by_branch.get(b.id)
                qty = stk.quantity if stk else 0
                variant_stock_sum += qty
                status = cls._determine_stock_status(qty, stk.min_alert_threshold if stk else 5)
                branch_stocks.append(
                    StockVarianteSucursalCatalogo(
                        branch_id=b.id,
                        branch_name=b.name,
                        branch_city=b.city,
                        quantity=qty,
                        status=status,
                    )
                )

            total_product_stock += variant_stock_sum

            if v.color:
                unique_colors[v.color.id] = {"name": v.color.name, "hex": v.color.hex_code}
            if v.size:
                unique_sizes[v.size.id] = {"name": v.size.name, "code": v.size.code}

            variants_resp.append(
                VarianteProductoCatalogoResponse(
                    id=v.id,
                    size_id=v.size_id,
                    size_name=v.size.name if v.size else "",
                    size_code=v.size.code if v.size else "",
                    color_id=v.color_id,
                    color_name=v.color.name if v.color else "",
                    color_hex=v.color.hex_code if v.color else "",
                    sku=v.sku,
                    price=float(product.price) if product.price is not None else 0.0,
                    total_stock=variant_stock_sum,
                    branch_availability=branch_stocks,
                )
            )

        base_price = float(product.price) if product.price is not None else 0.0

        return DetalleProductoCatalogoResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            category_id=product.category_id,
            category_name=product.category.name if product.category else None,
            season_id=product.season_id,
            season_name=product.season.name if product.season else None,
            promotion_id=product.promotion_id,
            promotion_name=product.promotion.name if (product.promotion and product.promotion.is_active) else None,
            discount_percent=float(product.promotion.discount_percent) if (product.promotion and product.promotion.is_active) else None,
            gender=product.gender,
            image_url=product.image_url,
            min_price=base_price,
            max_price=base_price,
            total_stock=total_product_stock,
            variants=variants_resp,
            colors=list(unique_colors.values()),
            sizes=list(unique_sizes.values()),
        )

    @classmethod
    def list_products(
        cls,
        db: Session,
        search: Optional[str] = None,
        category_id: Optional[str] = None,
        size_id: Optional[str] = None,
        color_id: Optional[str] = None,
        season_id: Optional[str] = None,
        gender: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        branch_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ListaProductosCatalogoResponse:
        branch_id = db.info.get("customer_branch_id") or branch_id
        query = db.query(Producto).filter(Producto.is_active == True)

        if search:
            s = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    Producto.name.ilike(s),
                    Producto.description.ilike(s),
                    Producto.variants.any(VarianteProducto.sku.ilike(s)),
                )
            )

        if category_id:
            query = query.filter(Producto.category_id == category_id)

        if season_id:
            query = query.filter(Producto.season_id == season_id)

        if gender:
            query = query.filter(Producto.gender == gender)

        if min_price is not None:
            query = query.filter(Producto.price >= min_price)

        if max_price is not None:
            query = query.filter(Producto.price <= max_price)

        if size_id:
            query = query.filter(Producto.variants.any(VarianteProducto.size_id == size_id))

        if color_id:
            query = query.filter(Producto.variants.any(VarianteProducto.color_id == color_id))

        if branch_id:
            query = query.filter(
                Producto.variants.any(
                    VarianteProducto.stocks.any(
                        (Stock.branch_id == branch_id) & (Stock.quantity > 0)
                    )
                )
            )

        if sort_by == "price_asc":
            query = query.order_by(Producto.price.asc())
        elif sort_by == "price_desc":
            query = query.order_by(Producto.price.desc())
        elif sort_by == "name_asc":
            query = query.order_by(Producto.name.asc())
        else:  # newest
            query = query.order_by(Producto.created_at.desc())

        total = query.count()
        offset = (page - 1) * page_size
        products = query.options(*product_load_options()).offset(offset).limit(page_size).all()

        active_branches = db.query(Sucursal).filter(Sucursal.is_active == True).all()
        if db.info.get("customer_branch_id"):
            active_branches = [b for b in active_branches if b.id == db.info["customer_branch_id"]]
        items = [cls._format_product(db, p, active_branches) for p in products]

        return ListaProductosCatalogoResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def get_product(cls, db: Session, product_id: str) -> DetalleProductoCatalogoResponse:
        product = db.query(Producto).options(*product_load_options()).filter(Producto.id == product_id, Producto.is_active == True).first()
        if not product:
            raise NoEncontradoException(detail="Producto no encontrado en el catálogo")

        active_branches = db.query(Sucursal).filter(Sucursal.is_active == True).all()
        if db.info.get("customer_branch_id"):
            active_branches = [b for b in active_branches if b.id == db.info["customer_branch_id"]]
        return cls._format_product(db, product, active_branches)
