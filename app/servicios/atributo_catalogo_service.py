from app.nucleo.transacciones import commit_or_flush
from sqlalchemy import func
from typing import List, Optional
from sqlalchemy.orm import Session
from app.modelos.categoria import Categoria
from app.modelos.talla import Talla
from app.modelos.color import Color
from app.esquemas.atributo_catalogo import (
    CategoriaCreate,
    CategoriaUpdate,
    TallaCreate,
    TallaUpdate,
    ColorCreate,
    ColorUpdate,
)
from app.nucleo.excepciones import ConflictoException, NoEncontradoException


class AtributoCatalogoService:
    # ----------------------------------------------------
    # CATEGORIES
    # ----------------------------------------------------
    @staticmethod
    def list_categories(db: Session, is_active: Optional[bool] = None, search: Optional[str] = None) -> List[Categoria]:
        query = db.query(Categoria)
        if is_active is not None:
            query = query.filter(Categoria.is_active == is_active)
        if search:
            query = query.filter(Categoria.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Categoria.name.asc()).all()

    @staticmethod
    def get_category_by_id(db: Session, category_id: str) -> Categoria:
        category = db.query(Categoria).filter(Categoria.id == category_id).first()
        if not category:
            raise NoEncontradoException(detail=f"Categoría con ID {category_id} no encontrada")
        return category

    @staticmethod
    def create_category(db: Session, payload: CategoriaCreate) -> Categoria:
        clean_name = payload.name.strip()
        existing = db.query(Categoria).filter(func.lower(Categoria.name) == clean_name.lower()).first()
        if existing:
            raise ConflictoException(detail=f"Ya existe una categoría con el nombre '{clean_name}'")

        category = Categoria(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            is_active=True,
        )
        db.add(category)
        commit_or_flush(db)
        db.refresh(category)
        return category

    @staticmethod
    def update_category(db: Session, category_id: str, payload: CategoriaUpdate) -> Categoria:
        category = AtributoCatalogoService.get_category_by_id(db, category_id)

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Categoria).filter(
                func.lower(Categoria.name) == clean_name.lower(),
                Categoria.id != category_id,
            ).first()
            if existing:
                raise ConflictoException(detail=f"Ya existe otra categoría con el nombre '{clean_name}'")
            category.name = clean_name

        if "description" in payload.model_fields_set:
            category.description = payload.description.strip() if payload.description else None

        if payload.is_active is not None:
            category.is_active = payload.is_active

        commit_or_flush(db)
        db.refresh(category)
        return category

    @staticmethod
    def toggle_category_status(db: Session, category_id: str) -> Categoria:
        category = AtributoCatalogoService.get_category_by_id(db, category_id)
        category.is_active = not category.is_active
        commit_or_flush(db)
        db.refresh(category)
        return category

    # ----------------------------------------------------
    # SIZES
    # ----------------------------------------------------
    @staticmethod
    def list_sizes(db: Session, is_active: Optional[bool] = None, category_type: Optional[str] = None) -> List[Talla]:
        query = db.query(Talla)
        if is_active is not None:
            query = query.filter(Talla.is_active == is_active)
        if category_type:
            query = query.filter(Talla.category_type == category_type)
        return query.order_by(Talla.name.asc()).all()

    @staticmethod
    def get_size_by_id(db: Session, size_id: str) -> Talla:
        size = db.query(Talla).filter(Talla.id == size_id).first()
        if not size:
            raise NoEncontradoException(detail=f"Talla con ID {size_id} no encontrada")
        return size

    @staticmethod
    def create_size(db: Session, payload: TallaCreate) -> Talla:
        clean_code = payload.code.strip().upper()
        existing = db.query(Talla).filter(func.lower(Talla.code) == clean_code.lower()).first()
        if existing:
            raise ConflictoException(detail=f"Ya existe una talla con el código '{clean_code}'")

        size = Talla(
            name=payload.name.strip(),
            code=clean_code,
            category_type=payload.category_type.strip() if payload.category_type else "GENERAL",
            is_active=True,
        )
        db.add(size)
        commit_or_flush(db)
        db.refresh(size)
        return size

    @staticmethod
    def update_size(db: Session, size_id: str, payload: TallaUpdate) -> Talla:
        size = AtributoCatalogoService.get_size_by_id(db, size_id)

        if payload.code is not None:
            clean_code = payload.code.strip().upper()
            existing = db.query(Talla).filter(
                func.lower(Talla.code) == clean_code.lower(),
                Talla.id != size_id,
            ).first()
            if existing:
                raise ConflictoException(detail=f"Ya existe otra talla con el código '{clean_code}'")
            size.code = clean_code

        if payload.name is not None:
            size.name = payload.name.strip()

        if "category_type" in payload.model_fields_set:
            size.category_type = payload.category_type or "GENERAL"

        if payload.is_active is not None:
            size.is_active = payload.is_active

        commit_or_flush(db)
        db.refresh(size)
        return size

    @staticmethod
    def toggle_size_status(db: Session, size_id: str) -> Talla:
        size = AtributoCatalogoService.get_size_by_id(db, size_id)
        size.is_active = not size.is_active
        commit_or_flush(db)
        db.refresh(size)
        return size

    # ----------------------------------------------------
    # COLORS
    # ----------------------------------------------------
    @staticmethod
    def list_colors(db: Session, is_active: Optional[bool] = None, search: Optional[str] = None) -> List[Color]:
        query = db.query(Color)
        if is_active is not None:
            query = query.filter(Color.is_active == is_active)
        if search:
            query = query.filter(Color.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Color.name.asc()).all()

    @staticmethod
    def get_color_by_id(db: Session, color_id: str) -> Color:
        color = db.query(Color).filter(Color.id == color_id).first()
        if not color:
            raise NoEncontradoException(detail=f"Color con ID {color_id} no encontrado")
        return color

    @staticmethod
    def create_color(db: Session, payload: ColorCreate) -> Color:
        clean_name = payload.name.strip()
        clean_hex = payload.hex_code.strip().upper()

        existing = db.query(Color).filter(func.lower(Color.name) == clean_name.lower()).first()
        if existing:
            raise ConflictoException(detail=f"Ya existe un color con el nombre '{clean_name}'")

        color = Color(
            name=clean_name,
            hex_code=clean_hex,
            is_active=True,
        )
        db.add(color)
        commit_or_flush(db)
        db.refresh(color)
        return color

    @staticmethod
    def update_color(db: Session, color_id: str, payload: ColorUpdate) -> Color:
        color = AtributoCatalogoService.get_color_by_id(db, color_id)

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Color).filter(
                func.lower(Color.name) == clean_name.lower(),
                Color.id != color_id,
            ).first()
            if existing:
                raise ConflictoException(detail=f"Ya existe otro color con el nombre '{clean_name}'")
            color.name = clean_name

        if payload.hex_code is not None:
            color.hex_code = payload.hex_code.strip().upper()

        if payload.is_active is not None:
            color.is_active = payload.is_active

        commit_or_flush(db)
        db.refresh(color)
        return color

    @staticmethod
    def toggle_color_status(db: Session, color_id: str) -> Color:
        color = AtributoCatalogoService.get_color_by_id(db, color_id)
        color.is_active = not color.is_active
        commit_or_flush(db)
        db.refresh(color)
        return color
