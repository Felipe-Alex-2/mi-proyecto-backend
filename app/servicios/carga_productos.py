"""Batch-load the graph consumed by product and catalog serializers."""
from sqlalchemy.orm import joinedload, selectinload
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.stock import Stock


def product_load_options():
    # Collections use separate batched SELECTs to avoid multiplying rows when
    # several variants and branches belong to the same product.
    return (
        joinedload(Producto.category),
        joinedload(Producto.season),
        joinedload(Producto.supplier),
        joinedload(Producto.promotion),
        selectinload(Producto.variants).joinedload(VarianteProducto.size),
        selectinload(Producto.variants).joinedload(VarianteProducto.color),
        selectinload(Producto.variants)
        .selectinload(VarianteProducto.stocks)
        .joinedload(Stock.branch),
    )
