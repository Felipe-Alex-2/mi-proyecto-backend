from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.stock import Stock
from app.models.category import Category
from app.models.size import Size
from app.models.color import Color
from app.models.season import Season
from app.models.branch import Branch
from app.schemas.catalog import (
    CatalogFilterOptions,
    CatalogProductDetailResponse,
    CatalogProductVariantResponse,
    CatalogVariantBranchStock,
    CatalogProductListResponse,
)
from app.core.exceptions import NotFoundException


class CatalogService:
    @staticmethod
    def _determine_stock_status(quantity: int, min_threshold: int = 5) -> str:
        if quantity <= 0:
            return "OUT_OF_STOCK"
        elif quantity <= min_threshold:
            return "LOW_STOCK"
        return "IN_STOCK"

    @classmethod
    def get_filter_options(cls, db: Session) -> CatalogFilterOptions:
        categories = (
            db.query(Category)
            .filter(Category.is_active == True)
            .order_by(Category.name.asc())
            .all()
        )
        sizes = db.query(Size).filter(Size.is_active == True).order_by(Size.name.asc()).all()
        colors = db.query(Color).filter(Color.is_active == True).order_by(Color.name.asc()).all()
        seasons = db.query(Season).filter(Season.is_active == True).order_by(Season.name.asc()).all()
        branches = db.query(Branch).filter(Branch.is_active == True).order_by(Branch.name.asc()).all()

        min_max = db.query(func.min(Product.price), func.max(Product.price)).filter(Product.is_active == True).first()
        min_p = float(min_max[0]) if (min_max and min_max[0] is not None) else 0.0
        max_p = float(min_max[1]) if (min_max and min_max[1] is not None) else 1000.0

        return CatalogFilterOptions(
            categories=[{"id": c.id, "name": c.name, "description": c.description} for c in categories],
            sizes=[{"id": s.id, "name": s.name, "code": s.code} for s in sizes],
            colors=[{"id": c.id, "name": c.name, "hex_code": c.hex_code} for c in colors],
            seasons=[{"id": s.id, "name": s.name, "code": s.code} for s in seasons],
            branches=[{"id": b.id, "name": b.name, "city": b.city, "address": b.address} for b in branches],
            genders=["Hombre", "Mujer", "Unisex", "Niños"],
            min_price=min_p,
            max_price=max_p,
        )

    @classmethod
    def _format_product(cls, db: Session, product: Product, active_branches: List[Branch]) -> CatalogProductDetailResponse:
        variants_resp: List[CatalogProductVariantResponse] = []
        unique_colors: Dict[str, Dict[str, str]] = {}
        unique_sizes: Dict[str, Dict[str, str]] = {}
        total_product_stock = 0

        for v in product.variants:
            stocks_by_branch = {
                s.branch_id: s for s in db.query(Stock).filter(Stock.variant_id == v.id).all()
            }

            branch_stocks: List[CatalogVariantBranchStock] = []
            variant_stock_sum = 0

            for b in active_branches:
                stk = stocks_by_branch.get(b.id)
                qty = stk.quantity if stk else 0
                variant_stock_sum += qty
                status = cls._determine_stock_status(qty, stk.min_alert_threshold if stk else 5)
                branch_stocks.append(
                    CatalogVariantBranchStock(
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
                CatalogProductVariantResponse(
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

        return CatalogProductDetailResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            category_id=product.category_id,
            category_name=product.category.name if product.category else None,
            season_id=product.season_id,
            season_name=product.season.name if product.season else None,
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
    ) -> CatalogProductListResponse:
        query = db.query(Product).filter(Product.is_active == True)

        if search:
            s = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    Product.name.ilike(s),
                    Product.description.ilike(s),
                    Product.variants.any(ProductVariant.sku.ilike(s)),
                )
            )

        if category_id:
            query = query.filter(Product.category_id == category_id)

        if season_id:
            query = query.filter(Product.season_id == season_id)

        if gender:
            query = query.filter(Product.gender == gender)

        if min_price is not None:
            query = query.filter(Product.price >= min_price)

        if max_price is not None:
            query = query.filter(Product.price <= max_price)

        if size_id:
            query = query.filter(Product.variants.any(ProductVariant.size_id == size_id))

        if color_id:
            query = query.filter(Product.variants.any(ProductVariant.color_id == color_id))

        if branch_id:
            query = query.filter(
                Product.variants.any(
                    ProductVariant.stocks.any(
                        (Stock.branch_id == branch_id) & (Stock.quantity > 0)
                    )
                )
            )

        if sort_by == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort_by == "price_desc":
            query = query.order_by(Product.price.desc())
        elif sort_by == "name_asc":
            query = query.order_by(Product.name.asc())
        else:  # newest
            query = query.order_by(Product.created_at.desc())

        total = query.count()
        offset = (page - 1) * page_size
        products = query.offset(offset).limit(page_size).all()

        active_branches = db.query(Branch).filter(Branch.is_active == True).all()
        items = [cls._format_product(db, p, active_branches) for p in products]

        return CatalogProductListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def get_product(cls, db: Session, product_id: str) -> CatalogProductDetailResponse:
        product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
        if not product:
            raise NotFoundException(detail="Producto no encontrado en el catálogo")

        active_branches = db.query(Branch).filter(Branch.is_active == True).all()
        return cls._format_product(db, product, active_branches)
