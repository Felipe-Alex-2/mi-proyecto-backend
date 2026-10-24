import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.nucleo.excepciones import SolicitudInvalidaException
from app.esquemas.reporte import ReporteRequest, ReporteResponse
from app.servicios.gemini_client import GeminiClient
from app.servicios.reporte_service import ReporteService
from app.modelos.sucursal import Sucursal
from app.modelos.usuario import Usuario
from app.nucleo.ambito_sucursal import resolve_branch


class ReporteGeminiService:
    @staticmethod
    def _normalize(value: str) -> str:
        return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if unicodedata.category(c) != 'Mn')

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise SolicitudInvalidaException(detail="Gemini devolvió una interpretación no válida") from exc
        if not isinstance(data, dict):
            raise SolicitudInvalidaException(detail="Gemini no devolvió un objeto de filtros válido")
        return data

    @classmethod
    def interpret(cls, transcript: str, branches: list | None = None) -> ReporteRequest:
        normalize = cls._normalize
        phrase = normalize(transcript)
        matches = [branch for branch in (branches or []) if re.search(r'(?<!\w)' + re.escape(normalize(branch.name)) + r'(?!\w)', phrase)]
        if len(matches) > 1:
            raise SolicitudInvalidaException(detail="Selecciona una sucursal o elige Todas para compararlas.")
        # These comparisons do not require an external model or invented figures.
        kind = None
        if any(word in phrase for word in ("vendio", "vendieron", "ventas", "recaudo", "facturo")):
            kind = "sales_by_branch"
        elif "sucursal" in phrase and any(word in phrase for word in ("ropa", "prenda", "stock", "inventario", "existencia")):
            kind = "inventory_by_branch"
        # Dates and other qualifiers must be interpreted, not silently discarded.
        qualified = bool(re.search(r'\d|ayer|hoy|semana|mes|ano|desde|hasta|categoria|temporada|proveedor', phrase))
        if kind and not qualified:
            return ReporteRequest(report_type=kind, branch_id=matches[0].id if matches else None)
        prompt = f"""
Eres un traductor de consultas para reportes empresariales de una tienda de ropa.
No respondas con explicaciones. Devuelve únicamente JSON válido, sin markdown.
El JSON debe tener exactamente estos campos: report_type, branch_id, category_id,
season_id, supplier_id, status, search, low_stock_threshold, date_from, date_to.
Usa null cuando no exista un filtro en la frase.
report_type debe ser uno de: inventory_by_branch, products_by_category,
products_by_season, low_stock, reservations_status, reservations_by_branch,
products_by_supplier, registered_customers, sales_by_branch.
Para ventas cobradas, qué sucursal vendió más o recaudación usa sales_by_branch.
Para qué sucursal tiene más ropa usa inventory_by_branch.
Fechas date_from/date_to en formato YYYY-MM-DD, o null. Hoy es {datetime.now(timezone(timedelta(hours=-4))).date()}.
Interpreta español natural. Para "stock", "inventario" o "existencias" usa inventory_by_branch.
Para "poco stock", "stock bajo" o "alertas" usa low_stock.
Para reservas por estado usa reservations_status y para reservas agrupadas por tienda usa reservations_by_branch.
Sucursales permitidas (solo puedes usar estos IDs): {json.dumps([{'id': b.id, 'name': b.name} for b in (branches or [])], ensure_ascii=False)}.
search es únicamente nombre de producto, nunca un nombre de sucursal.
Si no conoces un ID, usa null; no inventes IDs.
La frase del usuario es: {transcript}
"""
        try:
            data = cls._parse_json(GeminiClient.generate_text(prompt))
            if data.get("low_stock_threshold") is None:
                data["low_stock_threshold"] = 5
            request = ReporteRequest(**data)
            if matches:
                request.branch_id = matches[0].id
            if request.branch_id and request.branch_id not in {b.id for b in (branches or [])}:
                raise SolicitudInvalidaException(detail="No se pudo identificar la sucursal. Selecciónala en el filtro.")
            return request
        except SolicitudInvalidaException:
            raise
        except Exception as exc:
            raise SolicitudInvalidaException(detail=f"No se pudo interpretar la consulta con Gemini: {exc}") from exc

    @classmethod
    def generate(cls, db: Session, transcript: str, user: Usuario, branch_id: str | None = None) -> tuple[ReporteRequest, ReporteResponse]:
        scope = resolve_branch(user, branch_id)
        if scope:
            phrase = cls._normalize(transcript)
            for branch in db.query(Sucursal).filter(Sucursal.is_active == True).all():
                if branch.id != scope and re.search(r'(?<!\w)' + re.escape(cls._normalize(branch.name)) + r'(?!\w)', phrase):
                    raise SolicitudInvalidaException(detail="La sucursal mencionada no coincide con tu sucursal seleccionada o asignada.")
        query = db.query(Sucursal).filter(Sucursal.is_active == True)
        if scope:
            query = query.filter(Sucursal.id == scope)
        interpretation = cls.interpret(transcript, query.all())
        if scope and interpretation.branch_id and interpretation.branch_id != scope:
            raise SolicitudInvalidaException(detail="La sucursal de la consulta no coincide con el filtro seleccionado.")
        interpretation.branch_id = scope or interpretation.branch_id
        report = ReporteService.generate(db, interpretation, user=user)
        report.generated_by = "natural_language"
        return interpretation, report
