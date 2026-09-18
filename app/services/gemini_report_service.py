import json
import re
from typing import Any, Dict

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BadRequestException
from app.schemas.report import ReportRequest, ReportResponse
from app.services.report_service import ReportService


class GeminiReportService:
    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise BadRequestException(detail="Gemini devolvió una interpretación no válida") from exc
        if not isinstance(data, dict):
            raise BadRequestException(detail="Gemini no devolvió un objeto de filtros válido")
        return data

    @classmethod
    def interpret(cls, transcript: str) -> ReportRequest:
        if not settings.GEMINI_API_KEY:
            raise BadRequestException(detail="GEMINI_API_KEY no está configurada en el backend")

        prompt = f"""
Eres un traductor de consultas para reportes empresariales de una tienda de ropa.
No respondas con explicaciones. Devuelve únicamente JSON válido, sin markdown.
El JSON debe tener exactamente estos campos: report_type, branch_id, category_id,
season_id, supplier_id, status, search, low_stock_threshold.
Usa null cuando no exista un filtro en la frase.
report_type debe ser uno de: inventory_by_branch, products_by_category,
products_by_season, low_stock, reservations_status, reservations_by_branch,
products_by_supplier, registered_customers.
Interpreta español natural. Para "stock", "inventario" o "existencias" usa inventory_by_branch.
Para "poco stock", "stock bajo" o "alertas" usa low_stock.
Para reservas por estado usa reservations_status y para reservas agrupadas por tienda usa reservations_by_branch.
Si se menciona un nombre de sucursal, categoría, temporada o proveedor pero no hay ID,
colócalo en search para que el usuario pueda revisar el resultado, y no inventes IDs.
La frase del usuario es: {transcript}
"""
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.GEMINI_MODEL}:generateContent"
            )
            response = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            data = cls._parse_json(text)
            if data.get("low_stock_threshold") is None:
                data["low_stock_threshold"] = 5
            return ReportRequest(**data)
        except BadRequestException:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.json().get("error", {}).get("message", str(exc))
            raise BadRequestException(detail=f"Gemini rechazó la consulta: {detail}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise BadRequestException(detail="Gemini devolvió una respuesta sin contenido interpretable") from exc
        except Exception as exc:
            raise BadRequestException(detail=f"No se pudo interpretar la consulta con Gemini: {exc}") from exc

    @classmethod
    def generate(cls, db: Session, transcript: str) -> tuple[ReportRequest, ReportResponse]:
        interpretation = cls.interpret(transcript)
        report = ReportService.generate(db, interpretation)
        report.generated_by = "voice_gemini"
        return interpretation, report
