from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.inventory_movement import InventoryMovement, MovementType
from app.models.stock import Stock
from app.models.branch import Branch
from app.models.product_variant import ProductVariant
from app.models.product import Product
from app.models.user import User, UserRole
from app.schemas.inventory_movement import (
    InventoryMovementCreate,
    InventoryMovementResponse,
    BranchInventorySummary,
)
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
    ForbiddenException,
)


class InventoryMovementService:
    @staticmethod
    def _enrich_movement(movement: InventoryMovement) -> InventoryMovementResponse:
        res = InventoryMovementResponse.model_validate(movement)
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
        user: User,
        data: InventoryMovementCreate,
    ) -> InventoryMovementResponse:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == UserRole.STORE_MANAGER.value:
            if not user.branch_id or user.branch_id != data.branch_id:
                raise ForbiddenException(detail="Solo puedes registrar movimientos en tu sucursal asignada")

        branch = db.query(Branch).filter(Branch.id == data.branch_id).first()
        if not branch:
            raise NotFoundException(detail="Sucursal no encontrada")
        if not branch.is_active:
            raise BadRequestException(detail="La sucursal seleccionada no está activa")

        variant = db.query(ProductVariant).filter(ProductVariant.id == data.variant_id).first()
        if not variant:
            raise NotFoundException(detail="Variante de producto no encontrada")

        if data.quantity < 1:
            raise BadRequestException(detail="La cantidad debe ser un número entero positivo mayor a 0")

        reason = data.reason.strip()
        if len(reason) < 5:
            raise BadRequestException(detail="El motivo debe tener al menos 5 caracteres")

        # Find or initialize Stock
        stock = (
            db.query(Stock)
            .filter(Stock.variant_id == data.variant_id, Stock.branch_id == data.branch_id)
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

        if movement_type in (MovementType.ENTRY.value, MovementType.RETURN.value):
            new_stock = previous_stock + data.quantity
        elif movement_type == MovementType.EXIT.value:
            if previous_stock < data.quantity:
                raise BadRequestException(
                    detail=f"Stock insuficiente para realizar la salida. Stock disponible: {previous_stock}, solicitado: {data.quantity}"
                )
            new_stock = previous_stock - data.quantity
        elif movement_type == MovementType.ADJUSTMENT.value:
            # Direct physical inventory count
            new_stock = data.quantity
        else:
            raise BadRequestException(detail=f"Tipo de movimiento no válido: {movement_type}")

        stock.quantity = new_stock

        movement = InventoryMovement(
            variant_id=data.variant_id,
            branch_id=data.branch_id,
            type=movement_type,
            quantity=data.quantity,
            reason=reason,
            reference_number=data.reference_number.strip() if data.reference_number else None,
            previous_stock=previous_stock,
            new_stock=new_stock,
            user_id=user.id,
        )
        db.add(movement)
        db.commit()
        db.refresh(movement)

        return cls._enrich_movement(movement)

    @classmethod
    def list_movements(
        cls,
        db: Session,
        user: User,
        branch_id: Optional[str] = None,
        movement_type: Optional[str] = None,
        variant_id: Optional[str] = None,
        product_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[InventoryMovementResponse]:
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == UserRole.STORE_MANAGER.value:
            branch_id = user.branch_id

        query = db.query(InventoryMovement)

        if branch_id:
            query = query.filter(InventoryMovement.branch_id == branch_id)
        if movement_type:
            query = query.filter(InventoryMovement.type == movement_type)
        if variant_id:
            query = query.filter(InventoryMovement.variant_id == variant_id)
        if product_id:
            query = query.join(ProductVariant).filter(ProductVariant.product_id == product_id)

        movements = query.order_by(InventoryMovement.created_at.desc()).offset(offset).limit(limit).all()
        return [cls._enrich_movement(m) for m in movements]

    @classmethod
    def get_movement(
        cls,
        db: Session,
        movement_id: str,
        user: User,
    ) -> InventoryMovementResponse:
        movement = db.query(InventoryMovement).filter(InventoryMovement.id == movement_id).first()
        if not movement:
            raise NotFoundException(detail="Movimiento de inventario no encontrado")

        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role == UserRole.STORE_MANAGER.value and movement.branch_id != user.branch_id:
            raise ForbiddenException(detail="No tienes permiso para ver movimientos de otra sucursal")

        return cls._enrich_movement(movement)

    @classmethod
    def get_branch_summary(
        cls,
        db: Session,
        branch_id: str,
    ) -> BranchInventorySummary:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise NotFoundException(detail="Sucursal no encontrada")

        stocks = db.query(Stock).filter(Stock.branch_id == branch_id).all()
        total_variants = len(stocks)
        total_units = sum(s.quantity for s in stocks)
        low_stock_count = sum(1 for s in stocks if 0 < s.quantity <= s.min_alert_threshold)
        out_of_stock_count = sum(1 for s in stocks if s.quantity == 0)

        return BranchInventorySummary(
            branch_id=branch.id,
            branch_name=branch.name,
            total_variants=total_variants,
            total_units=total_units,
            low_stock_count=low_stock_count,
            out_of_stock_count=out_of_stock_count,
        )
