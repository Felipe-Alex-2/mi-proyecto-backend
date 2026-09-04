from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.season import Season
from app.schemas.season import SeasonCreate, SeasonUpdate, SeasonResponse
from app.core.exceptions import ConflictException, NotFoundException


class SeasonService:
    @staticmethod
    def format_response(season: Season) -> SeasonResponse:
        today = date.today()
        is_expired = season.end_date < today
        return SeasonResponse(
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
    ) -> List[Season]:
        query = db.query(Season)
        if is_active is not None:
            query = query.filter(Season.is_active == is_active)
        if search:
            query = query.filter(Season.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Season.start_date.desc()).all()

    @staticmethod
    def get_season_by_id(db: Session, season_id: str) -> Season:
        season = db.query(Season).filter(Season.id == season_id).first()
        if not season:
            raise NotFoundException(detail=f"Temporada con ID {season_id} no encontrada")
        return season

    @staticmethod
    def create_season(db: Session, payload: SeasonCreate) -> Season:
        clean_name = payload.name.strip()
        existing = db.query(Season).filter(Season.name.ilike(clean_name)).first()
        if existing:
            raise ConflictException(detail=f"Ya existe una temporada con el nombre '{clean_name}'")

        season = Season(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=True,
        )
        db.add(season)
        db.commit()
        db.refresh(season)
        return season

    @staticmethod
    def update_season(db: Session, season_id: str, payload: SeasonUpdate) -> Season:
        season = SeasonService.get_season_by_id(db, season_id)

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Season).filter(
                Season.name.ilike(clean_name),
                Season.id != season_id,
            ).first()
            if existing:
                raise ConflictException(detail=f"Ya existe otra temporada con el nombre '{clean_name}'")
            season.name = clean_name

        if payload.description is not None:
            season.description = payload.description.strip() if payload.description else None

        if payload.start_date is not None:
            season.start_date = payload.start_date

        if payload.end_date is not None:
            season.end_date = payload.end_date

        if payload.is_active is not None:
            season.is_active = payload.is_active

        db.commit()
        db.refresh(season)
        return season

    @staticmethod
    def toggle_status(db: Session, season_id: str) -> Season:
        season = SeasonService.get_season_by_id(db, season_id)
        season.is_active = not season.is_active
        db.commit()
        db.refresh(season)
        return season
