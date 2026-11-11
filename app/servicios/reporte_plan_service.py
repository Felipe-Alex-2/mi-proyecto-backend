"""Execute a typed report plan on already authorized rows; never execute user SQL."""
from collections import defaultdict
from decimal import Decimal
from app.nucleo.excepciones import SolicitudInvalidaException
import unicodedata


def _text(value):
    return ''.join(c for c in unicodedata.normalize('NFD',str(value).casefold()) if unicodedata.category(c)!='Mn')


def apply_filters(rows,columns,filters):
    for spec in filters or []:
        if spec.field not in columns:
            raise SolicitudInvalidaException(detail=f'El campo {spec.field} no está disponible en estos datos.')
        def matches(row):
            value=row.get(spec.field);target=spec.value;op=spec.operator
            if op=='is_null':return value is None
            if op=='not_null':return value is not None
            if value is None:return False
            if op=='contains':return _text(target) in _text(value)
            if op=='in':
                if not isinstance(target,list) or len(target)>100:
                    raise SolicitudInvalidaException(detail='El filtro in necesita una lista de hasta 100 valores.')
                return any(_text(value)==_text(v) for v in target)
            if op in ('eq','ne'):
                try:
                    equal=Decimal(str(value))==Decimal(str(target)) if isinstance(value,(int,float,Decimal)) and not isinstance(value,bool) else _text(value)==_text(target)
                except (ValueError,TypeError,ArithmeticError):equal=False
                return equal if op=='eq' else not equal
            try:
                if isinstance(value,(int,float,Decimal)) and not isinstance(value,bool):
                    value,target=Decimal(str(value)),Decimal(str(target))
                elif isinstance(value,str) and isinstance(target,str):value,target=_text(value),_text(target)
                else:raise ValueError()
                return {'gt':lambda:value>target,'gte':lambda:value>=target,'lt':lambda:value<target,'lte':lambda:value<=target}[op]()
            except (ValueError,TypeError,ArithmeticError) as exc:
                raise SolicitudInvalidaException(detail=f'El filtro de {spec.field} tiene un valor incompatible.') from exc
        rows=[r for r in rows if matches(r)]
    return rows


def shape(request, columns, rows, summary):
    rows=apply_filters(rows,columns,request.filters)
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
        if 'company' in columns and any(c in dimensions for c in ('branch','product','customer')) and 'company' not in dimensions:
            dimensions.insert(0,'company')
        if any(c not in columns for c in dimensions):
            raise SolicitudInvalidaException(detail='La agrupación contiene una columna no disponible.')
        # Monetary aggregation must preserve currency, even if the AI omitted it.
        monetary = any(m.field in ('amount','price','unit_price','current_value','estimated_amount','fee') and m.operation not in ('count','distinct') for m in request.aggregations)
        if 'currency' in columns and monetary and 'currency' not in dimensions:dimensions.append('currency')
        for metric in request.aggregations:
            if metric.field!='*' and metric.field not in columns:
                raise SolicitudInvalidaException(detail='La métrica contiene una columna no disponible.')
            if metric.field=='*' and metric.operation!='count':
                raise SolicitudInvalidaException(detail='Solo count permite contar registros sin columna.')
        identity_dimensions=list(dimensions)
        for name,identifier in [('product','product_id'),('branch','branch_id'),('customer','customer_id')]:
            if name in dimensions and identifier in columns and identifier not in identity_dimensions:identity_dimensions.append(identifier)
        grouped=defaultdict(list)
        for row in rows:grouped[tuple(row.get(c) for c in identity_dimensions)].append(row)
        result=[]
        for key,group in grouped.items():
            row=dict(zip(identity_dimensions,key))
            for metric in request.aggregations:
                name=metric.operation+'_'+('records' if metric.field=='*' else metric.field)
                values=[r.get(metric.field) for r in group if r.get(metric.field) is not None]
                if metric.operation=='count':value=len(group) if metric.field=='*' else len(values)
                elif metric.operation=='distinct':value=len(set(map(str,values)))
                else:
                    if metric.operation in ('min','max') and values and all(isinstance(v,str) for v in values) and metric.field in ('day','week','month','paid_at','created_at'):
                        row[name]=min(values) if metric.operation=='min' else max(values)
                        continue
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
        summary={'matching_records':len(rows),'groups':len(result),**{k:v for k,v in summary.items() if k in ('scope','unitemized_sales','unpriced_sales')}}
        rows=result
    elif request.group_by:
        raise SolicitudInvalidaException(detail='Indica qué métrica calcular para agrupar los registros.')
    rows=apply_filters(rows,columns,request.having)
    if request.partition_by and any(field not in columns for field in request.partition_by):
        raise SolicitudInvalidaException(detail='El límite por grupo contiene una columna no disponible.')
    if request.sort_by:
        if request.sort_by not in columns:raise SolicitudInvalidaException(detail='La columna de orden no pertenece al reporte.')
        rows.sort(key=lambda r:(r.get(request.sort_by) is not None,r.get(request.sort_by) or 0),reverse=request.descending)
        if 'currency' in columns:
            rows.sort(key=lambda r: r.get('currency') or '')
    if request.limit:
        summary['matching_records']=summary.get('matching_records',len(rows))
        if 'currency' in columns or request.partition_by:
            counts=defaultdict(int)
            limited=[]
            dimensions=list(request.partition_by or [])
            if dimensions and 'company' in columns and 'company' not in dimensions:dimensions.insert(0,'company')
            if 'currency' in columns and 'currency' not in dimensions:dimensions.append('currency')
            for row in rows:
                group=tuple(row.get(k) for k in dimensions)+tuple(row.get(k+'_id') for k in dimensions if k in ('branch','customer') and k+'_id' in row)
                if counts[group] < request.limit:
                    limited.append(row)
                    counts[group]+=1
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
        selected=list(request.selected_columns)
        if 'company' in columns and any(k in selected for k in ('branch','product','customer')) and 'company' not in selected:selected.insert(0,'company')
        if 'currency' in columns and 'currency' not in selected:selected.append('currency')
        columns=selected
        rows=[{c:r.get(c) for c in columns} for r in rows]
    summary['records_shown']=len(rows)
    if request.partition_by and request.limit:
        names={'company':'empresa','branch':'sucursal','customer':'cliente','month':'mes','year':'año','currency':'moneda'}
        summary['limit_scope']=str(request.limit)+' por '+', '.join(names.get(k,k) for k in request.partition_by)
    return columns,rows,summary
