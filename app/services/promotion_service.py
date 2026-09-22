from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.promotion import Promotion
from app.schemas.promotion import PromotionCreate, PromotionUpdate, PromotionResponse
from app.core.exceptions import ConflictException, NotFoundException


class PromotionService:
    @staticmethod
    def format_response(promotion: Promotion) -> PromotionResponse:
        today = date.today()
        is_expired = promotion.end_date < today
        return PromotionResponse(
            id=promotion.id,
            name=promotion.name,
            description=promotion.description,
            discount_percent=float(promotion.discount_percent),
            start_date=promotion.start_date,
            end_date=promotion.end_date,
            is_active=promotion.is_active,
            is_expired=is_expired,
            created_at=promotion.created_at,
            updated_at=promotion.updated_at,
        )

    @staticmethod
    def list_promotions(
        db: Session,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[Promotion]:
        query = db.query(Promotion)
        if is_active is not None:
            query = query.filter(Promotion.is_active == is_active)
        if search:
            query = query.filter(Promotion.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Promotion.start_date.desc()).all()

    @staticmethod
    def get_promotion_by_id(db: Session, promotion_id: str) -> Promotion:
        promotion = db.query(Promotion).filter(Promotion.id == promotion_id).first()
        if not promotion:
            raise NotFoundException(detail=f"Promoción con ID {promotion_id} no encontrada")
        return promotion

    @staticmethod
    def create_promotion(db: Session, payload: PromotionCreate) -> Promotion:
        clean_name = payload.name.strip()
        existing = db.query(Promotion).filter(Promotion.name.ilike(clean_name)).first()
        if existing:
            raise ConflictException(detail=f"Ya existe una promoción con el nombre '{clean_name}'")

        promotion = Promotion(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            discount_percent=payload.discount_percent,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=True,
        )
        db.add(promotion)
        db.commit()
        db.refresh(promotion)
        return promotion

    @staticmethod
    def update_promotion(db: Session, promotion_id: str, payload: PromotionUpdate) -> Promotion:
        promotion = PromotionService.get_promotion_by_id(db, promotion_id)

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Promotion).filter(
                Promotion.name.ilike(clean_name),
                Promotion.id != promotion_id,
            ).first()
            if existing:
                raise ConflictException(detail=f"Ya existe otra promoción con el nombre '{clean_name}'")
            promotion.name = clean_name

        if payload.description is not None:
            promotion.description = payload.description.strip() if payload.description else None

        if payload.discount_percent is not None:
            promotion.discount_percent = payload.discount_percent

        if payload.start_date is not None:
            promotion.start_date = payload.start_date

        if payload.end_date is not None:
            promotion.end_date = payload.end_date

        if payload.is_active is not None:
            promotion.is_active = payload.is_active

        db.commit()
        db.refresh(promotion)
        return promotion

    @staticmethod
    def toggle_status(db: Session, promotion_id: str) -> Promotion:
        promotion = PromotionService.get_promotion_by_id(db, promotion_id)
        promotion.is_active = not promotion.is_active
        db.commit()
        db.refresh(promotion)
        return promotion
