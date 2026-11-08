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
    def interpret(cls, transcript: str, branches: list | None = None, authorize_ai=None) -> ReporteRequest:
        normalize = cls._normalize
        phrase = normalize(transcript)
        matches = [branch for branch in (branches or []) if re.search(r'(?<!\w)' + re.escape(normalize(branch.name)) + r'(?!\w)', phrase)]
        if len(matches) > 1:
            raise SolicitudInvalidaException(detail="Selecciona una sucursal o elige Todas para compararlas.")
        kind = None
        if 'empresa' in phrase and not re.search(r'vend|venta|recaud|factur|stock|inventario|reserva|cliente|pago',phrase):kind='companies_list'
        elif 'sucursal' in phrase and re.search(r'list|existen|cuantas|cuenta|registrad|hay|muestra',phrase) and not re.search(r'vend|venta|stock|prenda|inventario|reserva|pago',phrase):kind='branches_list'
        elif re.search(r'recarga|wallet|billetera',phrase):kind='wallet_topups'
        elif re.search(r'pago|compra|comprobante|recibo',phrase):kind='payments_detail'
        elif re.search(r'vend|venta|recaud|factur',phrase):kind='sales_by_branch'
        elif re.search(r'stock bajo|poco stock|agotad|alerta',phrase):kind='low_stock'
        elif 'reserva' in phrase:kind='reservations_by_branch' if 'sucursal' in phrase else 'reservations_status'
        elif re.search(r'cliente|mi cuenta',phrase):kind='registered_customers'
        elif 'proveedor' in phrase:kind='products_by_supplier'
        elif 'temporada' in phrase:kind='products_by_season'
        elif 'categoria' in phrase:kind='products_by_category'
        elif re.search(r'ropa|prenda|stock|inventario|existencia|producto',phrase):kind='inventory_by_branch' if 'sucursal' in phrase else 'products_detail'
        today=datetime.now(timezone(timedelta(hours=-4))).date()
        filters={}
        # Resolve common calendar periods locally, identically for voice and text.
        dates=re.findall(r'\b(\d{4}-\d{2}-\d{2})\b',phrase)
        if dates:
            filters['date_from']=dates[0];filters['date_to']=dates[-1]
        elif 'ayer' in phrase:filters.update(date_from=today-timedelta(days=1),date_to=today-timedelta(days=1))
        elif 'hoy' in phrase:filters.update(date_from=today,date_to=today)
        elif 'esta semana' in phrase:filters.update(date_from=today-timedelta(days=today.weekday()),date_to=today)
        elif 'este mes' in phrase:filters.update(date_from=today.replace(day=1),date_to=today)
        elif 'este ano' in phrase:filters.update(date_from=today.replace(month=1,day=1),date_to=today)
        elif match:=re.search(r'ultimos? (\d+) dias?',phrase):filters.update(date_from=today-timedelta(days=min(36600,max(1,int(match[1])))-1),date_to=today)
        unresolved_date=bool(re.search(r'ayer|hoy|semana|mes|ano|desde|hasta|dias|\d{1,2}/\d{1,2}',phrase)) and not dates and 'date_from' not in filters
        if re.search(r'pagad|cobrad|completad',phrase):filters['status']='PAID'
        elif 'pendiente' in phrase:filters['status']='PENDING'
        elif 'cancelad' in phrase:filters['status']='CANCELLED'
        if kind in ('reservations_status','reservations_by_branch'):
            if 'confirmad' in phrase:filters['status']='CONFIRMED'
            elif 'completad' in phrase:filters['status']='COMPLETED'
            elif 'expirad' in phrase:filters['status']='EXPIRED'
            elif filters.get('status')=='PAID':filters.pop('status')
        if match:=re.search(r'(?:top|primeros|primeras)\s+(\d+)',phrase):filters['limit']=min(1000,max(1,int(match[1])))
        if match:=re.search(r'(?:producto|prenda|buscar)\s+["\']([^"\']+)["\']',phrase):filters['search']=match[1]
        if match:=re.search(r'color\s+([\w]+)',phrase):filters['color']=match[1];kind='products_detail'
        if match:=re.search(r'talla\s+([\w]+)',phrase):filters['size']=match[1];kind='products_detail'
        if match:=re.search(r'(?:menos de|menor a|hasta)\s*\$?\s*(\d+(?:[.,]\d+)?)\s*(?:dolares|usd|bs)',phrase):filters['max_price']=float(match[1].replace(',','.'));kind='products_detail'
        if re.search(r'paypal|efectivo|wallet',phrase) and kind=='payments_detail':filters['payment_method']='PAYPAL' if 'paypal' in phrase else 'WALLET' if 'wallet' in phrase else 'EFECTIVO'
        # Complex comparisons/groupings go through the typed AI planner instead of
        # silently turning a different question into a generic stock report.
        complex_query=bool(re.search(r'promedio|promedia|mediana|porcentaje|margen|ganancia|compar|devoluci|ordenad|agru|solo las columnas|entre.* y |enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|mes pasado|semana pasada|mas de|mayores a|por color|por talla|por producto|por prenda',phrase))
        if kind and not unresolved_date and not complex_query:

            try:
                return ReporteRequest(report_type=kind,branch_id=matches[0].id if matches else None,**filters)
            except ValueError as exc:
                raise SolicitudInvalidaException(detail='Revisa las fechas y los filtros de la consulta.') from exc
        if authorize_ai:authorize_ai()
        from app.configuracion import settings
        if not settings.GEMINI_API_KEY:
            raise SolicitudInvalidaException(detail='La interpretación avanzada necesita configurar Gemini. Puedes consultar: mis pagos, mis recargas, lista las empresas existentes, sucursales, ventas de este mes o stock bajo.')
        prompt = f"""
Eres un traductor de consultas para reportes empresariales de una tienda de ropa.
No respondas con explicaciones. Devuelve únicamente JSON válido, sin markdown.
Si la petición no puede representarse con los tipos y filtros disponibles devuelve {{"error":"No se puede calcular esa métrica con estos reportes; precisa la consulta."}}.
No reemplaces una métrica solicitada por otra diferente.
El JSON usa estos campos: report_type, branch_id, category_id,
season_id, supplier_id, status, search, low_stock_threshold, date_from, date_to.
Usa null cuando no exista un filtro en la frase.
report_type debe ser uno de: inventory_by_branch, products_by_category,
products_by_season, low_stock, reservations_status, reservations_by_branch,
products_by_supplier, registered_customers, sales_by_branch, payments_detail, wallet_topups, companies_list, branches_list, products_detail.
products_detail: columnas product,sku,color,size,price,units,branch,category,season.
payments_detail: payment_code,amount,currency,status,payment_type,paid_at.
sales_by_branch: branch,currency,sales,units,amount.
Filtros opcionales adicionales: color,size,min_price,max_price,payment_method.
Los reportes de ventas separan monedas; nunca sumes monedas distintas.
Puedes incluir sort_by, descending, limit, selected_columns para ordenar, limitar y seleccionar columnas.
Para calcular métricas dinámicas incluye group_by (columnas disponibles) y aggregations:
lista de objetos con operation count/distinct/sum/avg/min/max y field (columna numérica o * solo para count).
La columna resultante se llama operation_field, por ejemplo sum_amount, avg_price o count_records.
Para total o promedio de pagos usa payments_detail, group_by payment_type y aggregations sum/avg amount.
Para cantidad y valor por color/talla usa products_detail con group_by color/size y sum units o avg price.
No uses sum price para calcular ingresos; price es precio unitario del catálogo.
La moneda se preserva automáticamente. No se admiten fórmulas, SQL ni atributos no listados.
Nunca inventes métricas, datos ni SQL. Usa tipos de reporte y filtros existentes únicamente.
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
            if data.get("error"):
                raise SolicitudInvalidaException(detail=str(data["error"])[:400])
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
    def generate(cls, db: Session, transcript: str, user: Usuario, branch_id: str | None = None, all_companies: bool = True) -> tuple[ReporteRequest, ReporteResponse]:
        from app.modelos.saas import Empresa, ROOT_TENANT_ID
        phrase=cls._normalize(transcript)
        companies=db.query(Empresa).filter(Empresa.id!=ROOT_TENANT_ID).all()
        named=[c for c in companies if re.search(r'(?<!\w)'+re.escape(cls._normalize(c.name))+r'(?!\w)',phrase)]
        branches=db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.is_active==True).all()
        interpretation=cls.interpret(transcript,branches)
        interpretation.all_companies=all_companies
        interpretation.branch_id=interpretation.branch_id or branch_id
        if len(named)==1:
            interpretation.company_id=named[0].id
            interpretation.all_companies=True
        elif len(named)>1:interpretation.all_companies=True
        if re.search(r'que empresa|cual empresa|cual es la empresa|todas las empresas|entre empresas|\bempresas\b',phrase) and interpretation.report_type=='sales_by_branch':
            interpretation.report_type='sales_by_company'
            interpretation.all_companies=True
            interpretation.branch_id=None
        report=ReporteService.generate(db,interpretation,user=user)
        report.generated_by='natural_language'
        return interpretation,report
