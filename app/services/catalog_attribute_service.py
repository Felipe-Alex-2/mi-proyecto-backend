from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.category import Category
from app.models.size import Size
from app.models.color import Color
from app.schemas.catalog_attribute import (
    CategoryCreate,
    CategoryUpdate,
    SizeCreate,
    SizeUpdate,
    ColorCreate,
    ColorUpdate,
)
from app.core.exceptions import ConflictException, NotFoundException


class CatalogAttributeService:
    # ----------------------------------------------------
    # CATEGORIES
    # ----------------------------------------------------
    @staticmethod
    def list_categories(db: Session, is_active: Optional[bool] = None, search: Optional[str] = None) -> List[Category]:
        query = db.query(Category)
        if is_active is not None:
            query = query.filter(Category.is_active == is_active)
        if search:
            query = query.filter(Category.name.ilike(f"%{search.strip()}%"))
        return query.order_by(Category.name.asc()).all()

    @staticmethod
    def get_category_by_id(db: Session, category_id: str) -> Category:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            raise NotFoundException(detail=f"Categoría con ID {category_id} no encontrada")
        return category

    @staticmethod
    def create_category(db: Session, payload: CategoryCreate) -> Category:
        clean_name = payload.name.strip()
        existing = db.query(Category).filter(Category.name.ilike(clean_name)).first()
        if existing:
            raise ConflictException(detail=f"Ya existe una categoría con el nombre '{clean_name}'")

        category = Category(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            is_active=True,
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        return category

    @staticmethod
    def update_category(db: Session, category_id: str, payload: CategoryUpdate) -> Category:
        category = CatalogAttributeService.get_category_by_id(db, category_id)

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Category).filter(
                Category.name.ilike(clean_name),
                Category.id != category_id,
            ).first()
            if existing:
                raise ConflictException(detail=f"Ya existe otra categoría con el nombre '{clean_name}'")
            category.name = clean_name

        if payload.description is not None:
            category.description = payload.description.strip() if payload.description else None

        if payload.is_active is not None:
            category.is_active = payload.is_active

        db.commit()
        db.refresh(category)
        return category

    @staticmethod
    def toggle_category_status(db: Session, category_id: str) -> Category:
        category = CatalogAttributeService.get_category_by_id(db, category_id)
        category.is_active = not category.is_active
        db.commit()
        db.refresh(category)
        return category

    # ----------------------------------------------------
    # SIZES
    # ----------------------------------------------------
    @staticmethod
    def list_sizes(db: Session, is_active: Optional[bool] = None, category_type: Optional[str] = None) -> List[Size]:
        query = db.query(Size)
        if is_active is not None:
            query = query.filter(Size.is_active == is_active)
        if category_type:
            query = query.filter(Size.category_type == category_type)
        return query.order_by(Size.name.asc()).all()

    @staticmethod
    def get_size_by_id(db: Session, size_id: str) -> Size:
        size = db.query(Size).filter(Size.id == size_id).first()
        if not size:
            raise NotFoundException(detail=f"Talla con ID {size_id} no encontrada")
        return size

    @staticmethod
    def create_size(db: Session, payload: SizeCreate) -> Size:
        clean_code = payload.code.strip().upper()
        existing = db.query(Size).filter(Size.code.ilike(clean_code)).first()
        if existing:
            raise ConflictException(detail=f"Ya existe una talla con el código '{clean_code}'")

        size = Size(
            name=payload.name.strip(),
            code=clean_code,
            category_type=payload.category_type.strip() if payload.category_type else "GENERAL",
            is_active=True,
        )
        db.add(size)
        db.commit()
        db.refresh(size)
        return size

    @staticmethod
    def update_size(db: Session, size_id: str, payload: SizeUpdate) -> Size:
        size = CatalogAttributeService.get_size_by_id(db, size_id)

        if payload.code is not None:
            clean_code = payload.code.strip().upper()
            existing = db.query(Size).filter(
                Size.code.ilike(clean_code),
                Size.id != size_id,
            ).first()
            if existing:
                raise ConflictException(detail=f"Ya existe otra talla con el código '{clean_code}'")
            size.code = clean_code

        if payload.name is not None:
            size.name = payload.name.strip()

        if payload.category_type is not None:
            size.category_type = payload.category_type.strip()

        if payload.is_active is not None:
            size.is_active = payload.is_active

        db.commit()
        db.refresh(size)
        return size

    @staticmethod
    def toggle_size_status(db: Session, size_id: str) -> Size:
        size = CatalogAttributeService.get_size_by_id(db, size_id)
        size.is_active = not size.is_active
        db.commit()
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
            raise NotFoundException(detail=f"Color con ID {color_id} no encontrado")
        return color

    @staticmethod
    def create_color(db: Session, payload: ColorCreate) -> Color:
        clean_name = payload.name.strip()
        clean_hex = payload.hex_code.strip().upper()

        existing = db.query(Color).filter(Color.name.ilike(clean_name)).first()
        if existing:
            raise ConflictException(detail=f"Ya existe un color con el nombre '{clean_name}'")

        color = Color(
            name=clean_name,
            hex_code=clean_hex,
            is_active=True,
        )
        db.add(color)
        db.commit()
        db.refresh(color)
        return color

    @staticmethod
    def update_color(db: Session, color_id: str, payload: ColorUpdate) -> Color:
        color = CatalogAttributeService.get_color_by_id(db, color_id)

        if payload.name is not None:
            clean_name = payload.name.strip()
            existing = db.query(Color).filter(
                Color.name.ilike(clean_name),
                Color.id != color_id,
            ).first()
            if existing:
                raise ConflictException(detail=f"Ya existe otro color con el nombre '{clean_name}'")
            color.name = clean_name

        if payload.hex_code is not None:
            color.hex_code = payload.hex_code.strip().upper()

        if payload.is_active is not None:
            color.is_active = payload.is_active

        db.commit()
        db.refresh(color)
        return color

    @staticmethod
    def toggle_color_status(db: Session, color_id: str) -> Color:
        color = CatalogAttributeService.get_color_by_id(db, color_id)
        color.is_active = not color.is_active
        db.commit()
        db.refresh(color)
        return color
