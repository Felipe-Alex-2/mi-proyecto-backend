from app.servicios.carga_productos import product_load_options
import json
import re
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.configuracion import settings
from app.nucleo.excepciones import SolicitudInvalidaException
from app.modelos.categoria import Categoria
from app.modelos.sucursal import Sucursal
from app.modelos.color import Color
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.temporada import Temporada
from app.modelos.talla import Talla
from app.modelos.stock import Stock
from app.esquemas.recomendacion import (
    RecomendacionInterpretation,
    RecomendacionResponse,
)
from app.servicios.catalogo_service import CatalogoService
from app.servicios.gemini_client import GeminiClient


class RecomendacionService:
    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise SolicitudInvalidaException(detail="El asistente devolvió una interpretación no válida") from exc
        if not isinstance(value, dict):
            raise SolicitudInvalidaException(detail="El asistente no devolvió preferencias válidas")
        return value

    @classmethod
    def interpret(cls, message: str) -> RecomendacionInterpretation:
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
            return RecomendacionInterpretation(**cls._parse_json(text))
        except SolicitudInvalidaException:
            raise
        except Exception as exc:
            raise SolicitudInvalidaException(detail=f"No se pudo interpretar la preferencia: {exc}") from exc

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
    def recommend(cls, db: Session, message: str) -> RecomendacionResponse:
        interpretation = cls.interpret(message)
        category = cls._find_name(db, Categoria, interpretation.category)
        color = cls._find_name(db, Color, interpretation.color)
        season = cls._find_name(db, Temporada, interpretation.season)
        size = cls._find_name(db, Talla, interpretation.size)

        query = db.query(Producto).options(*product_load_options()).filter(Producto.is_active == True)
        if category:
            query = query.filter(Producto.category_id == category.id)
        if season:
            query = query.filter(Producto.season_id == season.id)
        if interpretation.gender:
            query = query.filter(Producto.gender.ilike(f"%{interpretation.gender}%"))
        if interpretation.search:
            search = f"%{interpretation.search.strip()}%"
            query = query.filter(or_(Producto.name.ilike(search), Producto.description.ilike(search)))
        if size:
            query = query.filter(Producto.variants.any(VarianteProducto.size_id == size.id))
        if color:
            query = query.filter(Producto.variants.any(VarianteProducto.color_id == color.id))

        products = query.order_by(Producto.created_at.desc()).limit(8).all()
        branches = db.query(Sucursal).filter(Sucursal.is_active == True).all()
        formatted = [CatalogoService._format_product(db, product, branches) for product in products]
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
        return RecomendacionResponse(
            message=response_message,
            interpretation=interpretation,
            matched_filters=matched_filters,
            recommendations=formatted,
        )
