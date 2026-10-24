from app.nucleo.transacciones import commit_or_flush
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.modelos.movimiento_inventario import MovimientoInventario, TipoMovimiento
from app.modelos.stock import Stock
from app.modelos.sucursal import Sucursal
from app.modelos.variante_producto import VarianteProducto
from app.modelos.producto import Producto
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.movimiento_inventario import (
    MovimientoInventarioCreate, MovimientoInventarioUpdate,
    MovimientoInventarioResponse,
    ResumenInventarioSucursal,
)
from app.nucleo.excepciones import (
    SolicitudInvalidaException,
    NoEncontradoException,
    AccesoDenegadoException,
)
from app.servicios.bitacora_service import BitacoraService
from app.nucleo.ambito_sucursal import resolve_branch


class MovimientoInventarioService:
    @staticmethod
    def _enrich_movement(movement: MovimientoInventario) -> MovimientoInventarioResponse:
        res = MovimientoInventarioResponse.model_validate(movement)
        if movement.variant:
            res.sku = movement.variant.sku
            if movement.variant.size:
                res.size_name = movement.variant.size.name
            if movement.variant.color:
                res.color_name = movement.variant.color.name
            if movement.variant.product:
                res.product_id = movement.variant.product.id
                res.product_name = movement.variant.product.name
        if movement.branch:
            res.branch_name = movement.branch.name
        if movement.user:
            res.user_name = movement.user.full_name
        return res

    @classmethod
    def create_movement(
        cls,
        db: Session,
        user: Usuario,
        data: MovimientoInventarioCreate,
    ) -> MovimientoInventarioResponse:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == RolUsuario.STORE_MANAGER.value:
            if not user.branch_id or user.branch_id != data.branch_id:
                raise AccesoDenegadoException(detail="Solo puedes registrar movimientos en tu sucursal asignada")

        branch = db.query(Sucursal).filter(Sucursal.id == data.branch_id).first()
        if not branch:
            raise NoEncontradoException(detail="Sucursal no encontrada")
        if not branch.is_active:
            raise SolicitudInvalidaException(detail="La sucursal seleccionada no está activa")

        variant = db.query(VarianteProducto).filter(VarianteProducto.id == data.variant_id).first()
        if not variant:
            raise NoEncontradoException(detail="Variante de producto no encontrada")

        if data.quantity < 1:
            raise SolicitudInvalidaException(detail="La cantidad debe ser un número entero positivo mayor a 0")

        reason = data.reason.strip()
        if len(reason) < 5:
            raise SolicitudInvalidaException(detail="El motivo debe tener al menos 5 caracteres")

        # Find or initialize Stock
        stock = (
            db.query(Stock)
            .filter(Stock.variant_id == data.variant_id, Stock.branch_id == data.branch_id)
            .with_for_update()
            .first()
        )
        if not stock:
            stock = Stock(
                variant_id=data.variant_id,
                branch_id=data.branch_id,
                quantity=0,
                min_alert_threshold=5,
            )
            db.add(stock)
            db.flush()

        previous_stock = stock.quantity
        movement_type = data.type.value if hasattr(data.type, "value") else str(data.type)

        if movement_type in (TipoMovimiento.ENTRY.value, TipoMovimiento.RETURN.value):
            new_stock = previous_stock + data.quantity
        elif movement_type == TipoMovimiento.EXIT.value:
            if previous_stock < data.quantity:
                raise SolicitudInvalidaException(
                    detail=f"Stock insuficiente para realizar la salida. Stock disponible: {previous_stock}, solicitado: {data.quantity}"
                )
            new_stock = previous_stock - data.quantity
        elif movement_type == TipoMovimiento.ADJUSTMENT.value:
            # Direct physical inventory count
            new_stock = data.quantity
        else:
            raise SolicitudInvalidaException(detail=f"Tipo de movimiento no válido: {movement_type}")

        stock.quantity = new_stock

        movement = MovimientoInventario(
            variant_id=data.variant_id,
            branch_id=data.branch_id,
            type=movement_type,
            quantity=data.quantity,
            reason=reason,
            reference_number=data.reference_number.strip() if data.reference_number else None,
            previous_stock=previous_stock,
            new_stock=new_stock,
            user_id=user.id,
            payment_method=data.payment_method,
            payment_status=data.payment_status or "PENDING",
            amount=data.amount,
        )
        db.add(movement)
        commit_or_flush(db)
        db.refresh(movement)

        BitacoraService.log_event(
            db=db,
            user=user,
            action="MOVIMIENTO_STOCK",
            description=f"Movimiento {movement.type} de {movement.quantity} unidades para SKU {variant.sku or 'N/A'} en sucursal {branch.name} (Motivo: {movement.reason})",
            category="INVENTARIO",
            branch_id=movement.branch_id,
        )

        return cls._enrich_movement(movement)

    @classmethod
    def list_movements(
        cls,
        db: Session,
        user: Usuario,
        branch_id: Optional[str] = None,
        movement_type: Optional[str] = None,
        variant_id: Optional[str] = None,
        product_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MovimientoInventarioResponse]:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == RolUsuario.STORE_MANAGER.value:
            branch_id = resolve_branch(user, branch_id)

        query = db.query(MovimientoInventario)

        if branch_id:
            query = query.filter(MovimientoInventario.branch_id == branch_id)
        if movement_type:
            query = query.filter(MovimientoInventario.type == movement_type)
        if variant_id:
            query = query.filter(MovimientoInventario.variant_id == variant_id)
        if product_id:
            query = query.join(VarianteProducto).filter(VarianteProducto.product_id == product_id)

        movements = query.order_by(MovimientoInventario.created_at.desc()).offset(offset).limit(limit).all()
        return [cls._enrich_movement(m) for m in movements]

    @classmethod
    def get_movement(
        cls,
        db: Session,
        movement_id: str,
        user: Usuario,
    ) -> MovimientoInventarioResponse:
        movement = db.query(MovimientoInventario).filter(MovimientoInventario.id == movement_id).first()
        if not movement:
            raise NoEncontradoException(detail="Movimiento de inventario no encontrado")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == RolUsuario.STORE_MANAGER.value and movement.branch_id != user.branch_id:
            raise AccesoDenegadoException(detail="No tienes permiso para ver movimientos de otra sucursal")

        return cls._enrich_movement(movement)

    @classmethod
    def get_branch_summary(
        cls,
        db: Session,
        branch_id: str,
    ) -> ResumenInventarioSucursal:
        branch = db.query(Sucursal).filter(Sucursal.id == branch_id).first()
        if not branch:
            raise NoEncontradoException(detail="Sucursal no encontrada")

        stocks = db.query(Stock).filter(Stock.branch_id == branch_id).all()
        total_variants = len(stocks)
        total_units = sum(s.quantity for s in stocks)
        low_stock_count = sum(1 for s in stocks if 0 < s.quantity <= s.min_alert_threshold)
        out_of_stock_count = sum(1 for s in stocks if s.quantity == 0)

        return ResumenInventarioSucursal(
            branch_id=branch.id,
            branch_name=branch.name,
            total_variants=total_variants,
            total_units=total_units,
            low_stock_count=low_stock_count,
            out_of_stock_count=out_of_stock_count,
        )

    @classmethod
    def update_movement(
        cls,
        db: Session,
        movement_id: str,
        user: Usuario,
        data: MovimientoInventarioUpdate,
    ) -> MovimientoInventarioResponse:
        movement = db.query(MovimientoInventario).filter(MovimientoInventario.id == movement_id).first()
        if not movement:
            raise NoEncontradoException(detail="Movimiento de inventario no encontrado")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == RolUsuario.STORE_MANAGER.value and movement.branch_id != user.branch_id:
            raise AccesoDenegadoException(detail="No tienes permiso para modificar movimientos de otra sucursal")

        if data.reason is not None and data.reason.strip():
            movement.reason = data.reason.strip()
        if data.reference_number is not None:
            movement.reference_number = data.reference_number.strip() if data.reference_number else None
        if data.payment_method is not None:
            movement.payment_method = data.payment_method
        if data.payment_status is not None:
            movement.payment_status = data.payment_status

        commit_or_flush(db)
        db.refresh(movement)
        return cls._enrich_movement(movement)

    @classmethod
    def delete_movement(
        cls,
        db: Session,
        movement_id: str,
        user: Usuario,
    ) -> None:
        movement = db.query(MovimientoInventario).filter(MovimientoInventario.id == movement_id).first()
        if not movement:
            raise NoEncontradoException(detail="Movimiento de inventario no encontrado")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == RolUsuario.STORE_MANAGER.value and movement.branch_id != user.branch_id:
            raise AccesoDenegadoException(detail="No tienes permiso para revertir/eliminar movimientos de otra sucursal")

        # Reverse stock change
        stock = db.query(Stock).filter(
            Stock.variant_id == movement.variant_id,
            Stock.branch_id == movement.branch_id,
        ).first()

        if stock:
            # Revert the quantity applied by this movement
            if movement.type in (TipoMovimiento.ENTRY.value, TipoMovimiento.RETURN.value):
                # When created, it added quantity. Reverting means subtracting.
                if stock.quantity < movement.quantity:
                    raise SolicitudInvalidaException(
                        detail=f"No se puede revertir este movimiento porque el stock actual ({stock.quantity}) es menor a la cantidad a retirar ({movement.quantity})"
                    )
                stock.quantity -= movement.quantity
            elif movement.type == TipoMovimiento.EXIT.value:
                # When created, it subtracted quantity. Reverting means adding back.
                stock.quantity += movement.quantity
            elif movement.type == TipoMovimiento.ADJUSTMENT.value:
                # Revert to previous stock before adjustment
                stock.quantity = movement.previous_stock

        db.delete(movement)
        commit_or_flush(db)
