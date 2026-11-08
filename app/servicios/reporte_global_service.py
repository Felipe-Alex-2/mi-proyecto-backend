"""Explicit, read-only cross-company reporting for the platform administrator."""
from collections import defaultdict
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.modelos.saas import Empresa, ROOT_TENANT_ID
from app.esquemas.reporte import ReporteResponse


def generate_global(db,request,user):
    if not user or not user.is_saas_admin or user.role!='ADMIN':
        raise HTTPException(403,'Solo el superadmin puede comparar empresas y sus sucursales.')
    if request.branch_id and request.all_companies:
        raise HTTPException(422,'Para comparar todas las empresas selecciona todas las sucursales.')
    from app.servicios.reporte_service import ReporteService
    from app.modelos.sucursal import Sucursal
    companies=db.query(Empresa).execution_options(skip_tenant=True).filter(Empresa.id!=ROOT_TENANT_ID).order_by(Empresa.name).all()
    if not request.all_companies:
        companies=[c for c in companies if c.id==db.info.get('tenant_id')]
    rows=[]; columns=[]
    for company in companies:
        # A fresh session preserves the originating request's tenant filters,
        # identity map and loaded relationships. Each child query stays scoped.
        with Session(bind=db.get_bind()) as scoped:
            scoped.info.update(tenant_context=True,tenant_id=company.id,actor_id=user.id)
            sub=request.model_copy(update={'all_companies':False,'report_type':'sales_by_branch' if request.report_type=='sales_by_company' else request.report_type})
            result=ReporteService.generate(scoped,sub,user=None)
            columns=result.columns
            for row in result.rows:
                rows.append(dict(company=company.name,company_id=company.id,**row))
    if request.report_type=='sales_by_company':
        grouped=defaultdict(lambda:dict(sales=0,units=0,amount=Decimal(0)))
        for row in rows:
            entry=grouped[(row['company_id'],row['company'],row['currency'])]
            for key in ('sales','units'): entry[key]+=row[key]
            entry['amount']+=Decimal(str(row['amount']))
        rows=[dict(company_id=key[0],company=key[1],currency=key[2],sales=value['sales'],units=value['units'],amount=float(value['amount'])) for key,value in grouped.items()]
        columns=['currency','sales','units','amount']
    summary={'scope':'Todas las empresas y sus sucursales' if request.all_companies else 'Empresa actual', 'companies':len(companies),'records':len(rows)}
    if request.report_type in ('sales_by_branch','sales_by_company'):
        rows.sort(key=lambda r:(r['currency'],-r['amount'],r['company'],r.get('branch','')))
        summary.update(sales=sum(r['sales'] for r in rows),units=sum(r['units'] for r in rows))
        for currency in sorted({r['currency'] for r in rows}):
            matches=[r for r in rows if r['currency']==currency]
            top=matches[0]
            summary['leader_'+currency]=top['company']+(' · '+top['branch'] if 'branch' in top else '')
            summary['total_'+currency]=float(sum((Decimal(str(r['amount'])) for r in matches),Decimal(0)))
    return ReporteResponse(report_type=request.report_type,title='Ventas cobradas por empresa' if request.report_type=='sales_by_company' else result.title if companies else request.report_type,
        generated_by='manual',summary=summary,columns=['company']+columns,rows=rows)
