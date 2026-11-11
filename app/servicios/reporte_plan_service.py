"""Execute a typed report plan on already authorized rows; never execute user SQL."""
from collections import defaultdict
from decimal import Decimal
from app.nucleo.excepciones import SolicitudInvalidaException


def shape(request, columns, rows, summary):
    if request.only_without_sales:
        if request.report_type not in ('sales_by_branch', 'sales_by_company'):
            raise SolicitudInvalidaException(detail='El filtro sin ventas requiere un reporte de ventas.')
        totals=defaultdict(int)
        def entity(row):return row.get('company_id'),row.get('branch_id',row.get('branch'))
        for row in rows:totals[entity(row)]+=row['sales']
        rows=[row for row in rows if totals[entity(row)]==0]
        summary={k:v for k,v in summary.items() if not k.startswith(('leader_','total_'))}
        summary.update(sales=0,units=0,records=len(rows))
        for currency in {r['currency'] for r in rows}:summary['total_'+currency]=0
    if request.aggregations:
        dimensions=list(request.group_by or [])
        if any(c not in columns for c in dimensions):
            raise SolicitudInvalidaException(detail='La agrupación contiene una columna no disponible.')
        # Monetary aggregation must preserve currency, even if the AI omitted it.
        if 'currency' in columns and 'currency' not in dimensions:dimensions.append('currency')
        for metric in request.aggregations:
            if metric.field!='*' and metric.field not in columns:
                raise SolicitudInvalidaException(detail='La métrica contiene una columna no disponible.')
            if metric.field=='*' and metric.operation!='count':
                raise SolicitudInvalidaException(detail='Solo count permite contar registros sin columna.')
        grouped=defaultdict(list)
        for row in rows:grouped[tuple(row.get(c) for c in dimensions)].append(row)
        result=[]
        for key,group in grouped.items():
            row=dict(zip(dimensions,key))
            for metric in request.aggregations:
                name=metric.operation+'_'+('records' if metric.field=='*' else metric.field)
                values=[r.get(metric.field) for r in group if r.get(metric.field) is not None]
                if metric.operation=='count':value=len(group) if metric.field=='*' else len(values)
                elif metric.operation=='distinct':value=len(set(map(str,values)))
                else:
                    if any(not isinstance(v,(int,float,Decimal)) or isinstance(v,bool) for v in values):
                        raise SolicitudInvalidaException(detail='Esta métrica necesita una columna numérica.')
                    numbers=[Decimal(str(v)) for v in values]
                    if not numbers:value=None
                    elif metric.operation=='sum':value=float(sum(numbers,Decimal(0)))
                    elif metric.operation=='avg':value=float(sum(numbers,Decimal(0))/len(numbers))
                    elif metric.operation=='min':value=float(min(numbers))
                    else:value=float(max(numbers))
                row[name]=value
            result.append(row)
        columns=dimensions+[m.operation+'_'+('records' if m.field=='*' else m.field) for m in request.aggregations]
        summary={'matching_records':len(rows),'groups':len(result),**{k:v for k,v in summary.items() if k=='scope'}}
        rows=result
    elif request.group_by:
        raise SolicitudInvalidaException(detail='Indica qué métrica calcular para agrupar los registros.')
    if request.sort_by:
        if request.sort_by not in columns:raise SolicitudInvalidaException(detail='La columna de orden no pertenece al reporte.')
        rows.sort(key=lambda r:(r.get(request.sort_by) is not None,r.get(request.sort_by) or 0),reverse=request.descending)
        if 'currency' in columns:
            rows.sort(key=lambda r: r.get('currency') or '')
    if request.limit:
        summary['matching_records']=summary.get('matching_records',len(rows))
        if 'currency' in columns:
            counts=defaultdict(int)
            limited=[]
            for row in rows:
                currency=row.get('currency')
                if counts[currency] < request.limit:
                    limited.append(row)
                    counts[currency]+=1
            rows=limited
        else:
            rows=rows[:request.limit]
    if request.report_type in {'sales_by_branch', 'sales_by_company'} and request.limit and not request.aggregations:
        # Keep the comparison universe explicit, but make the main totals
        # describe the branches actually shown in a top/bottom result.
        for key in list(summary):
            if key.startswith('total_') or key in {'sales', 'units'}:
                summary['comparison_'+key] = summary[key]
        summary.update(sales=sum(r.get('sales',0) for r in rows),
                       units=sum(r.get('units',0) for r in rows),records=len(rows))
        for currency in {r['currency'] for r in rows if 'currency' in r}:
            summary['total_'+currency] = float(sum((Decimal(str(r['amount'])) for r in rows if r.get('currency')==currency), Decimal(0)))
    if request.selected_columns:
        if any(c not in columns for c in request.selected_columns):raise SolicitudInvalidaException(detail='Las columnas solicitadas no pertenecen al reporte.')
        columns=request.selected_columns
        rows=[{c:r.get(c) for c in columns} for r in rows]
    return columns,rows,summary
