from app.modelos.saas import Empresa
from app.modelos.sucursal import Sucursal
from app.esquemas.reporte import ReporteResponse


def directory(db, request, user):
    # VESTA is both the root tenant and a business; include it even with zero branches.
    companies=db.query(Empresa).filter(Empresa.is_active == True).order_by(Empresa.name).all()
    branches=db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.is_active == True).order_by(Sucursal.name).all()
    names={c.id:c.name for c in companies}
    if request.report_type == 'companies_list':
        rows=[dict(company=c.name,branches=sum(b.tenant_id==c.id for b in branches)) for c in companies]
        columns=['company','branches'];title='Empresas existentes'
    else:
        rows=[dict(company=names[b.tenant_id],branch=b.name,city=b.city,address=b.address)
              for b in branches if b.tenant_id in names]
        columns=['company','branch','city','address'];title='Sucursales de todas las empresas'
    if request.search:
        rows=[r for r in rows if request.search.casefold() in ' '.join(str(v) for v in r.values()).casefold()]
    summary={'scope':'Directorio público de empresas','companies':len(companies),'records':len(rows)}
    from app.servicios.reporte_plan_service import shape
    columns,rows,summary=shape(request,columns,rows,summary)
    return ReporteResponse(customer_id=user.id if user and user.role=='CUSTOMER' else None,
        branch_id=user.branch_id if user else None, report_type=request.report_type,title=title,
        generated_by='manual',summary=summary,columns=columns,rows=rows)
