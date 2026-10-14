"""Batch-load the graph consumed by product and catalog serializers."""
from sqlalchemy.orm import joinedload, selectinload
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.stock import Stock


def product_load_options():
    # Collections use separate batched SELECTs to avoid multiplying rows when
    # several variants and branches belong to the same product.
    return (
        joinedload(Product.category),
        joinedload(Product.season),
        joinedload(Product.supplier),
        joinedload(Product.promotion),
        selectinload(Product.variants).joinedload(ProductVariant.size),
        selectinload(Product.variants).joinedload(ProductVariant.color),
        selectinload(Product.variants)
        .selectinload(ProductVariant.stocks)
        .joinedload(Stock.branch),
    )
