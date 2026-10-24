from app.nucleo.transacciones import commit_or_flush
from fastapi import HTTPException
from sqlalchemy import func
from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session
from app.modelos.promocion import Promocion
from app.esquemas.promocion import PromocionCreate, PromocionUpdate, PromocionResponse
from app.nucleo.excepciones import ConflictoException, NoEncontradoException


class PromocionService:
    @staticmethod
    def format_response(promotion: Promocion) -> PromocionResponse:
        today = date.today()
        is_expired = promotion.end_date < today
        return PromocionResponse(
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
    ) -> List[Promocion]:
        query = db.query(Promocion)
        if is_active is not None:
            query = query.filter(Promocion.is_active == is_active)
        if search:
            query = query.filter(Promocion.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Promocion.start_date.desc()).all()

    @staticmethod
    def get_promotion_by_id(db: Session, promotion_id: str) -> Promocion:
        promotion = db.query(Promocion).filter(Promocion.id == promotion_id).first()
        if not promotion:
            raise NoEncontradoException(detail=f"Promoción con ID {promotion_id} no encontrada")
        return promotion

    @staticmethod
    def create_promotion(db: Session, payload: PromocionCreate) -> Promocion:
        clean_name = payload.name.strip()
        existing = db.query(Promocion).filter(func.lower(Promocion.name) == clean_name.lower()).first()
        if existing:
            raise ConflictoException(detail=f"Ya existe una promoción con el nombre '{clean_name}'")

        promotion = Promocion(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            discount_percent=payload.discount_percent,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=True,
        )
        db.add(promotion)
        commit_or_flush(db)
        db.refresh(promotion)
        return promotion

    @staticmethod
    def update_promotion(db: Session, promotion_id: str, payload: PromocionUpdate) -> Promocion:
        promotion = PromocionService.get_promotion_by_id(db, promotion_id)
        start = payload.start_date or promotion.start_date
        end = payload.end_date or promotion.end_date
        if end < start:
            raise HTTPException(status_code=422, detail='La fecha de fin no puede ser anterior a la fecha de inicio')

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Promocion).filter(
                func.lower(Promocion.name) == clean_name.lower(),
                Promocion.id != promotion_id,
            ).first()
            if existing:
                raise ConflictoException(detail=f"Ya existe otra promoción con el nombre '{clean_name}'")
            promotion.name = clean_name

        if "description" in payload.model_fields_set:
            promotion.description = payload.description.strip() if payload.description else None

        if payload.discount_percent is not None:
            promotion.discount_percent = payload.discount_percent

        if payload.start_date is not None:
            promotion.start_date = payload.start_date

        if payload.end_date is not None:
            promotion.end_date = payload.end_date

        if payload.is_active is not None:
            promotion.is_active = payload.is_active

        commit_or_flush(db)
        db.refresh(promotion)
        return promotion

    @staticmethod
    def toggle_status(db: Session, promotion_id: str) -> Promocion:
        promotion = PromocionService.get_promotion_by_id(db, promotion_id)
        promotion.is_active = not promotion.is_active
        commit_or_flush(db)
        db.refresh(promotion)
        return promotion
