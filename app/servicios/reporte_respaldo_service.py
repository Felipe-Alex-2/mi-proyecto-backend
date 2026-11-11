"""Conservative compositional planner for temporary provider outages.

This combines entities, dimensions and operators, not complete question strings.
It declines unknown qualifiers instead of silently discarding their meaning.
"""
import re
from app.esquemas.reporte import ReporteRequest


def fallback_plan(phrase,period,label):
    # Do not replace unavailable measures or named product filters with a total.
    if re.search(r'ganancia|margen|costo|coste|descuento|porcentaje|mediana|entre',phrase):return None
    words=re.findall(r'\w+',phrase)
    vocabulary=r'product\w*|prenda\w*|ropa|venta\w*|vend\w*|ingreso\w*|pago\w*|cobro\w*|comprobante\w*|stock|inventario|reserva\w*|punto\w*|movimiento\w*|devolucion\w*|empleado\w*|personal|cliente\w*|sucursal\w*|empresa\w*|mes\w*|dia\w*|semana\w*|ano\w*|talla\w*|color\w*|categoria\w*|temporada\w*|proveedor\w*|unidad\w*|importe\w*|cantidad\w*|total\w*|promedio\w*|media|suma\w*|conteo|contar|cuanto\w*|cuenta|top|primer\w*|mas|menos|mayor\w*|menor\w*|mejor\w*|peor\w*|orden\w*|ascendente|descendente|agrupa\w*|durante|ultimo\w*|este|esta|pasado\w*|ahora|hasta|hoy|ayer|mostrar|muestra\w*|genera\w*|reporte\w*|informe\w*|dame|quiero|necesito|ver|por|cada|de|del|la|las|el|los|en|al|a|y|que|cual|con|un|una|unos|unas|se|ha|han|es|son|favor|desde|hace|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|\d+'
    if any(not re.fullmatch(vocabulary,w) for w in words):return None
    product=bool(re.search(r'product\w*|prenda\w*|ropa',phrase))
    sale=bool(re.search(r'vend|venta|ingreso',phrase))
    if product and sale:source,metric='sales_items','units'
    elif re.search(r'pago|comprobante|cobro',phrase):source,metric='payments_detail','amount'
    elif 'reserva' in phrase:source,metric='reservations_detail','units'
    elif 'punto' in phrase:source,metric='loyalty_movements','points'
    elif product or 'stock' in phrase or 'inventario' in phrase:source,metric='products_detail','units'
    else:return None
    dimensions=[]
    aliases={'branch':r'sucursal\w*','company':r'empresa\w*','month':r'mes(?:es)?','day':r'dia\w*','year':r'ano\w*',
             'color':r'color\w*','size':r'talla\w*','category':r'categoria\w*','season':r'temporada\w*',
             'supplier':r'proveedor\w*','customer':r'cliente\w*'}
    for field,pattern in aliases.items():
        if re.search(r'\b(?:por|cada)\s+(?:la\s+|el\s+)?'+pattern+r'\b',phrase):dimensions.append(field)
    if product and source=='sales_items':dimensions.append('product')
    if re.search(r'ingreso|importe',phrase):metric='amount'
    if 'promedio' in phrase or 'media' in phrase:operation='avg'
    elif 'contar' in phrase or 'conteo' in phrase:operation='count';metric='*'
    else:operation='sum'
    measure=operation+'_'+('records' if metric=='*' else metric)
    count=re.search(r'\b(?:top|primeros|primeras)\s+(\d+)\b|\b(?:los|las)\s+(\d+)\s+(?:product\w*|prenda\w*|resultados|sucursal\w*)',phrase)
    limit=min(1000,max(1,int(count[1] or count[2]))) if count else None
    partition=['branch'] if limit and source=='sales_items' and 'branch' in dimensions else None
    descending=not bool(re.search(r'\bmenos\b|\bmenor\w*',phrase))
    return ReporteRequest(report_type=source,group_by=dimensions or None,
        aggregations=[dict(operation=operation,field=metric)],sort_by=measure,descending=descending,
        limit=limit,partition_by=partition,**period)
