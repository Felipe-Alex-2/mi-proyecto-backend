"""Read-only cross-company reporting available to every authenticated role."""
from collections import defaultdict
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.modelos.saas import Empresa, ROOT_TENANT_ID
from app.esquemas.reporte import ReporteResponse


def generate_global(db,request,user):
    if not user:raise HTTPException(401,'Inicia sesión para consultar reportes.')
    from app.servicios.reporte_service import ReporteService
    from app.modelos.sucursal import Sucursal
    companies=db.query(Empresa).execution_options(skip_tenant=True).order_by(Empresa.name).all()
    # Older installations may still have commercial rows in the original tenant.
    if not companies and db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.tenant_id==ROOT_TENANT_ID).first():
        from types import SimpleNamespace
        companies=[SimpleNamespace(id=ROOT_TENANT_ID,name='Empresa principal')]
    if request.branch_id:
        branch=db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.id==request.branch_id).first()
        if not branch:raise HTTPException(404,'Sucursal no encontrada.')
        if request.company_id and request.company_id!=branch.tenant_id:raise HTTPException(422,'La sucursal no pertenece a la empresa seleccionada.')
        companies=[c for c in companies if c.id==branch.tenant_id]
    elif request.company_id:
        companies=[c for c in companies if c.id==request.company_id]
        if not companies:raise HTTPException(404,'Empresa no encontrada.')
    elif not request.all_companies:
        companies=[c for c in companies if c.id==db.info.get('tenant_id')]
    rows=[]; columns=[]
    for company in companies:
        # A fresh session preserves the originating request's tenant filters,
        # identity map and loaded relationships. Each child query stays scoped.
        with Session(bind=db.get_bind()) as scoped:
            scoped.info.update(tenant_context=True,tenant_id=company.id)
            sub=request.model_copy(update={'all_companies':False,'company_id':None,'group_by':None,'aggregations':None,'sort_by':None,'limit':None,'only_without_sales':False,'selected_columns':None,'report_type':'sales_by_branch' if request.report_type=='sales_by_company' else request.report_type})
            result=ReporteService.generate(scoped,sub,user=None)
            columns=result.columns
            for row in result.rows:
                rows.append(dict(company=company.name,company_id=company.id,**row))
    if request.report_type in ('sales_by_branch', 'sales_by_company'):
        # A company without sales must participate in every currency present in
        # the comparison; otherwise zero-sale branches disappear for that money.
        currencies = {row['currency'] for row in rows}
        entities = {(row['company_id'], row['branch_id']): row for row in rows}
        present = {(row['company_id'], row['branch_id'], row['currency']) for row in rows}
        for (company_id, branch_id), row in entities.items():
            for currency in currencies:
                if (company_id, branch_id, currency) not in present:
                    rows.append({**row, 'currency': currency, 'sales': 0, 'units': 0, 'amount': 0.0})
    if request.report_type=='sales_by_company':
        grouped=defaultdict(lambda:dict(sales=0,units=0,amount=Decimal(0)))
        for row in rows:
            entry=grouped[(row['company_id'],row['company'],row['currency'])]
            for key in ('sales','units'): entry[key]+=row[key]
            entry['amount']+=Decimal(str(row['amount']))
        rows=[dict(company_id=key[0],company=key[1],currency=key[2],sales=value['sales'],units=value['units'],amount=float(value['amount'])) for key,value in grouped.items()]
        columns=['currency','sales','units','amount']
    summary={'scope':branch.name if request.branch_id else companies[0].name if request.company_id and companies else 'Todas las empresas y sus sucursales' if request.all_companies else 'Empresa actual', 'companies':len(companies),'records':len(rows)}
    if request.report_type=='inventory_by_branch':
        rows.sort(key=lambda r:-r['units'])
        summary.update(total_units=sum(r['units'] for r in rows),most_stock_branch=rows[0]['branch'] if rows else 'Sin existencias')
    if request.report_type in ('reservations_status','reservations_by_branch'):
        summary['total']=sum(r['reservations'] for r in rows)
    if request.report_type in ('sales_by_branch','sales_by_company'):
        rows.sort(key=lambda r:(r['currency'],-r['amount'],r['company'],r.get('branch','')))
        summary.update(sales=sum(r['sales'] for r in rows),units=sum(r['units'] for r in rows))
        for currency in sorted({r['currency'] for r in rows}):
            matches=[r for r in rows if r['currency']==currency]
            top=matches[0]
            summary['leader_'+currency]=top['company']+(' · '+top['branch'] if 'branch' in top else '')
            summary['total_'+currency]=float(sum((Decimal(str(r['amount'])) for r in matches),Decimal(0)))
    from app.servicios.reporte_plan_service import shape
    columns,rows,summary=shape(request,['company']+columns,rows,summary)
    from app.servicios.reporte_periodo_service import report_metadata
    title = report_metadata(request, summary, rows, 'Ventas cobradas por empresa' if request.report_type=='sales_by_company' else result.title if companies else request.report_type)
    return ReporteResponse(platform_only=False,report_type=request.report_type,title=title,
        generated_by='manual',summary=summary,columns=columns,rows=rows)
