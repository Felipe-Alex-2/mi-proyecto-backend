import json
import re
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BadRequestException
from app.models.category import Category
from app.models.branch import Branch
from app.models.color import Color
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.season import Season
from app.models.size import Size
from app.models.stock import Stock
from app.schemas.recommendation import (
    RecommendationInterpretation,
    RecommendationResponse,
)
from app.services.catalog_service import CatalogService
from app.services.gemini_client import GeminiClient


class RecommendationService:
    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise BadRequestException(detail="El asistente devolvió una interpretación no válida") from exc
        if not isinstance(value, dict):
            raise BadRequestException(detail="El asistente no devolvió preferencias válidas")
        return value

    @classmethod
    def interpret(cls, message: str) -> RecommendationInterpretation:
        prompt = f"""
Eres un asistente de recomendaciones de ropa. Analiza las preferencias del cliente y devuelve SOLO JSON válido.
Campos exactos: category, color, season, gender, size, search.
Usa null si un campo no aparece. No inventes productos ni nombres de marcas.
Normaliza sinónimos en español: "pantaloncitos" o "pantalones" -> "pantalón", "para el frío" -> "invierno",
"para calor" o "verano" -> "verano". Conserva colores como "rojo", "negro", "azul oscuro".
Si dice "colores oscuros", usa "negro" como color preferido.
category debe contener el tipo de prenda; color el color o tono; season la temporada o clima;
gender el género si se menciona; size la talla si se menciona; search solo palabras adicionales relevantes.
La frase del cliente es: {message}
"""
        try:
            text = GeminiClient.generate_text(prompt)
            return RecommendationInterpretation(**cls._parse_json(text))
        except BadRequestException:
            raise
        except Exception as exc:
            raise BadRequestException(detail=f"No se pudo interpretar la preferencia: {exc}") from exc

    @staticmethod
    def _find_name(db: Session, model: Any, value: Optional[str]) -> Optional[Any]:
        if not value:
            return None
        clean_value = value.strip()
        if not clean_value:
            return None
        exact = db.query(model).filter(model.is_active == True, model.name.ilike(clean_value)).first()
        if exact:
            return exact
        return db.query(model).filter(model.is_active == True, model.name.ilike(f"%{clean_value}%")).first()

    @classmethod
    def recommend(cls, db: Session, message: str) -> RecommendationResponse:
        interpretation = cls.interpret(message)
        category = cls._find_name(db, Category, interpretation.category)
        color = cls._find_name(db, Color, interpretation.color)
        season = cls._find_name(db, Season, interpretation.season)
        size = cls._find_name(db, Size, interpretation.size)

        query = db.query(Product).filter(Product.is_active == True)
        if category:
            query = query.filter(Product.category_id == category.id)
        if season:
            query = query.filter(Product.season_id == season.id)
        if interpretation.gender:
            query = query.filter(Product.gender.ilike(f"%{interpretation.gender}%"))
        if interpretation.search:
            search = f"%{interpretation.search.strip()}%"
            query = query.filter(or_(Product.name.ilike(search), Product.description.ilike(search)))
        if size:
            query = query.filter(Product.variants.any(ProductVariant.size_id == size.id))
        if color:
            query = query.filter(Product.variants.any(ProductVariant.color_id == color.id))

        products = query.order_by(Product.created_at.desc()).limit(8).all()
        branches = db.query(Branch).filter(Branch.is_active == True).all()
        formatted = [CatalogService._format_product(db, product, branches) for product in products]
        matched_filters = {}
        for key, value in (("category", category), ("color", color), ("season", season), ("size", size)):
            if value:
                matched_filters[key] = value.name
        if interpretation.gender:
            matched_filters["gender"] = interpretation.gender

        if formatted:
            response_message = "Encontré prendas que coinciden con tus gustos."
        else:
            response_message = "No encontré una coincidencia exacta; prueba con otro color, prenda o temporada."
        return RecommendationResponse(
            message=response_message,
            interpretation=interpretation,
            matched_filters=matched_filters,
            recommendations=formatted,
        )
