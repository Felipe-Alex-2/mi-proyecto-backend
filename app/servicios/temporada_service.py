from app.nucleo.transacciones import commit_or_flush
from fastapi import HTTPException
from sqlalchemy import func
from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session
from app.modelos.temporada import Temporada
from app.esquemas.temporada import TemporadaCreate, TemporadaUpdate, TemporadaResponse
from app.nucleo.excepciones import ConflictoException, NoEncontradoException


class TemporadaService:
    @staticmethod
    def format_response(season: Temporada) -> TemporadaResponse:
        today = date.today()
        is_expired = season.end_date < today
        return TemporadaResponse(
            id=season.id,
            name=season.name,
            description=season.description,
            start_date=season.start_date,
            end_date=season.end_date,
            is_active=season.is_active,
            is_expired=is_expired,
            created_at=season.created_at,
            updated_at=season.updated_at,
        )

    @staticmethod
    def list_seasons(
        db: Session,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[Temporada]:
        query = db.query(Temporada)
        if is_active is not None:
            query = query.filter(Temporada.is_active == is_active)
        if search:
            query = query.filter(Temporada.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Temporada.start_date.desc()).all()

    @staticmethod
    def get_season_by_id(db: Session, season_id: str) -> Temporada:
        season = db.query(Temporada).filter(Temporada.id == season_id).first()
        if not season:
            raise NoEncontradoException(detail=f"Temporada con ID {season_id} no encontrada")
        return season

    @staticmethod
    def create_season(db: Session, payload: TemporadaCreate) -> Temporada:
        clean_name = payload.name.strip()
        existing = db.query(Temporada).filter(func.lower(Temporada.name) == clean_name.lower()).first()
        if existing:
            raise ConflictoException(detail=f"Ya existe una temporada con el nombre '{clean_name}'")

        season = Temporada(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=True,
        )
        db.add(season)
        commit_or_flush(db)
        db.refresh(season)
        return season

    @staticmethod
    def update_season(db: Session, season_id: str, payload: TemporadaUpdate) -> Temporada:
        season = TemporadaService.get_season_by_id(db, season_id)
        start = payload.start_date or season.start_date
        end = payload.end_date or season.end_date
        if end < start:
            raise HTTPException(status_code=422, detail='La fecha de fin no puede ser anterior a la fecha de inicio')

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Temporada).filter(
                func.lower(Temporada.name) == clean_name.lower(),
                Temporada.id != season_id,
            ).first()
            if existing:
                raise ConflictoException(detail=f"Ya existe otra temporada con el nombre '{clean_name}'")
            season.name = clean_name

        if "description" in payload.model_fields_set:
            season.description = payload.description.strip() if payload.description else None

        if payload.start_date is not None:
            season.start_date = payload.start_date

        if payload.end_date is not None:
            season.end_date = payload.end_date

        if payload.is_active is not None:
            season.is_active = payload.is_active

        commit_or_flush(db)
        db.refresh(season)
        return season

    @staticmethod
    def toggle_status(db: Session, season_id: str) -> Temporada:
        season = TemporadaService.get_season_by_id(db, season_id)
        season.is_active = not season.is_active
        commit_or_flush(db)
        db.refresh(season)
        return season
