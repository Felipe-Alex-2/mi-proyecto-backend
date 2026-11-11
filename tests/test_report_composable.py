import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

from tests.test_branch_reports_audit import world
from app.configuracion import settings
from app.modelos.producto import Producto
from app.modelos.proveedor import Proveedor
from app.modelos.temporada import Temporada
from app.modelos.variante_producto import VarianteProducto
from app.modelos.pago import Pago
from app.modelos.reserva import Reserva
from app.modelos.reserva_item import ReservaItem
from app.modelos.movimiento_inventario import MovimientoInventario
from app.modelos.aporte_propio import MovimientoPuntos
from app.esquemas.reporte import ReporteRequest
from app.servicios.reporte_datos_service import BusinessFacts
from app.servicios.gemini_client import GeminiClient
from app.servicios.reporte_gemini_service import ReporteGeminiService


@pytest.fixture
def sold_catalog(db_session,world):
    center,south,product,variant,customer,users=world
    supplier=Proveedor(company_name='Textiles VESTA',contact_name='Contacto',email='textiles@example.com',phone='70000000')
    season=Temporada(name='Invierno',start_date=date(2026,5,1),end_date=date(2026,8,31))
    db_session.add_all([supplier,season]);db_session.flush()
    variants=[]
    for i in range(12):
        p=Producto(name=f'Prenda {i:02}',price=999,category_id=product.category_id,
            supplier_id=supplier.id if i%2==0 else None,season_id=season.id if i%2==0 else None)
        db_session.add(p);db_session.flush()
        v=VarianteProducto(product_id=p.id,size_id=variant.size_id,color_id=variant.color_id,sku=f'FACT-{i:02}')
        db_session.add(v);db_session.flush();variants.append(v)
        for branch,quantity in [(center,i+1),(south,12-i)]:
            db_session.add(Pago(payment_code=f'{branch.name}-{i}',branch_id=branch.id,customer_id=customer.id,
                customer_name='Cliente',concept='Compra',amount=quantity*10,status='PAID',currency='USD',
                paid_at=datetime(2026,11,10,12,tzinfo=timezone.utc),items_detail=json.dumps([
                    dict(variant_id=v.id,product_name=p.name,quantity=quantity,unit_price=10,subtotal=quantity*10)])))
    for code,status,stamp in [('OLD','PAID',datetime(2026,6,1,tzinfo=timezone.utc)),('PENDING','PENDING',datetime(2026,11,10,tzinfo=timezone.utc))]:
        db_session.add(Pago(payment_code=code,branch_id=center.id,customer_name='No contar',concept='Compra',amount=9990,
            status=status,currency='USD',paid_at=stamp,items_detail=json.dumps([dict(variant_id=variants[0].id,quantity=999,unit_price=10)])))
    db_session.commit()
    return center,south,variants,customer,users


def test_exact_screenshot_executes_top_ten_per_branch_and_exports(client,db_session,sold_catalog,monkeypatch):
    center,south,variants,customer,users=sold_catalog
    monkeypatch.setattr(settings,'GEMINI_API_KEY','test')
    monkeypatch.setattr(ReporteGeminiService,'_today',staticmethod(lambda:date(2026,11,11)))
    prompts=[]
    def plan(prompt,**kwargs):
        prompts.append(prompt)
        assert kwargs['json_mode'] is True
        return json.dumps(dict(report_type='sales_items',group_by=['branch','product'],
            aggregations=[dict(operation='sum',field='units')],sort_by='sum_units',descending=True,
            limit=10,partition_by=['branch'],selected_columns=['branch','product','sum_units']))
    monkeypatch.setattr(GeminiClient,'generate_text',plan)
    result=client.post('/api/v1/reports/voice',headers=users['CUSTOMER'],json={
        'transcript':'mostrar los 10 productod mas vendidos durante los ultimos 3 meses agrupados por sucursal'})
    assert result.status_code==200,result.text
    report=result.json()['report']
    assert len(report['rows'])==20
    central=[r for r in report['rows'] if r['branch']=='Centro']
    south_rows=[r for r in report['rows'] if r['branch']=='Sur']
    assert [r['sum_units'] for r in central]==list(range(12,2,-1))
    assert [r['product'] for r in central]==[f'Prenda {i:02}' for i in range(11,1,-1)]
    assert [r['product'] for r in south_rows]==[f'Prenda {i:02}' for i in range(10)]
    assert report['summary']['matching_records']==24
    assert 'Últimos 3 meses' in report['summary']['period']
    assert '999' not in str(report['rows'])
    assert 'company' in report['columns']
    assert 'sales_items' in prompts[0] and 'partition_by' in prompts[0]
    pdf=client.get('/api/v1/reports/'+report['report_id']+'/pdf',headers=users['CUSTOMER'])
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')


def test_monthly_sales_filters_having_and_historical_prices(client,sold_catalog):
    _,_,_,_,users=sold_catalog
    request=dict(report_type='sales_items',date_from='2026-08-11',date_to='2026-11-11',group_by=['branch','month','color'],
        aggregations=[dict(operation='sum',field='units'),dict(operation='avg',field='unit_price'),dict(operation='distinct',field='payment_code')],
        filters=[dict(field='units',operator='gte',value=10)],having=[dict(field='sum_units',operator='gt',value=30)])
    result=client.post('/api/v1/reports/generate',headers=users['ADMIN'],json=request)
    assert result.status_code==200,result.text
    rows=result.json()['rows']
    assert len(rows)==2
    assert all(r['sum_units']==33 and r['avg_unit_price']==10 and r['distinct_payment_code']==3 for r in rows)
    assert all(r['month']=='2026-11' and r['color']=='Azul' for r in rows)


def test_supplier_and_season_dimensions_use_real_model_fields(client,db_session,sold_catalog):
    center,_,variants,_,users=sold_catalog
    result=client.post('/api/v1/reports/generate',headers=users['ADMIN'],json={
        'report_type':'sales_items','date_from':'2026-08-11','date_to':'2026-11-11',
        'group_by':['supplier','season'],
        'filters':[dict(field='supplier',operator='eq',value='Textiles VESTA')],
        'aggregations':[dict(operation='sum',field='units'),dict(operation='distinct',field='product_id')]})
    assert result.status_code==200,result.text
    row=result.json()['rows'][0]
    assert row['supplier']=='Textiles VESTA' and row['season']=='Invierno'
    assert row['sum_units']==78 and row['distinct_product_id']==6
    db_session.add(MovimientoInventario(variant_id=variants[0].id,branch_id=center.id,type='ENTRY',quantity=3,reason='Ingreso'))
    db_session.commit()
    movements=client.post('/api/v1/reports/generate',headers=users['ADMIN'],json={'report_type':'inventory_movements'})
    assert movements.status_code==200,movements.text
    assert movements.json()['rows'][0]['supplier']=='Textiles VESTA'


def test_line_amounts_reconcile_discounts_and_do_not_duplicate_paid_reservations(db_session,world):
    branch,_,product,variant,customer,_=world
    reservation=Reserva(reservation_code='FACT-RSV',branch_id=branch.id,customer_id=customer.id,
        payment_method='EFECTIVO',payment_status='PAID',status='CONFIRMED',total_amount=17,
        paid_at=datetime(2026,11,10,tzinfo=timezone.utc),expires_at=datetime(2026,12,1),
        receipt_items_detail=json.dumps([dict(variant_id=variant.id,quantity=2,unit_price=10,subtotal=20)]))
    db_session.add(reservation);db_session.flush()
    db_session.add(ReservaItem(reservation_id=reservation.id,variant_id=variant.id,quantity=2))
    db_session.add(Pago(payment_code='FACT-LINKED',reservation_id=reservation.id,branch_id=branch.id,customer_name='Cliente',
        concept='Compra',amount=17,status='PAID',currency='USD',paid_at=datetime(2026,11,10,tzinfo=timezone.utc)))
    db_session.add(Pago(payment_code='FACT-DISCOUNT',branch_id=branch.id,customer_name='Cliente',concept='Compra',
        amount=Decimal('25.50'),currency='USD',status='PAID',paid_at=datetime(2026,11,10,tzinfo=timezone.utc),
        items_detail=json.dumps([dict(variant_id=variant.id,quantity=2,unit_price=10,subtotal=20),dict(variant_id=variant.id,quantity=1,unit_price=10,subtotal=10)])))
    db_session.commit()
    rows,quality=BusinessFacts(db_session,ReporteRequest(report_type='sales_items')).sales_items()
    assert sum(r['units'] for r in rows)==5
    assert sum(Decimal(str(r['amount'])) for r in rows)==Decimal('42.50')
    assert len([r for r in rows if r['payment_code']=='FACT-LINKED'])==1
    assert quality=={'unitemized_sales':0,'unpriced_sales':0}


def test_composable_business_sources_and_private_fields(client,db_session,world):
    branch,_,_,variant,customer,users=world
    db_session.add_all([
        MovimientoInventario(variant_id=variant.id,branch_id=branch.id,type='ENTRY',quantity=5,reason='Ingreso'),
        MovimientoInventario(variant_id=variant.id,branch_id=branch.id,type='RETURN',quantity=2,reason='Devolución'),
        MovimientoPuntos(customer_id=customer.id,source_key='gain',points=10,description='Compra'),
        MovimientoPuntos(customer_id=customer.id,source_key='spend',points=-5,description='Canje'),
    ])
    db_session.commit()
    def report(payload):
        result=client.post('/api/v1/reports/generate',headers=users['CUSTOMER'],json=payload)
        assert result.status_code==200,result.text
        return result.json()
    movements=report(dict(report_type='inventory_movements',group_by=['movement_type'],aggregations=[dict(operation='sum',field='units')]))
    assert {r['movement_type']:r['sum_units'] for r in movements['rows']}=={'ENTRY':5,'RETURN':2}
    points=report(dict(report_type='loyalty_movements',group_by=['customer'],aggregations=[dict(operation='sum',field='points')]))
    assert points['rows'][0]['sum_points']==5
    staff=report(dict(report_type='employees_detail',filters=[dict(field='role',operator='eq',value='CASHIER')]))
    assert len(staff['rows'])==1 and 'hashed_password' not in str(staff)
    for dataset in ['deliveries_detail','exchanges_detail','reservations_detail']:
        report(dict(report_type=dataset))
    rejected=client.post('/api/v1/reports/generate',headers=users['CUSTOMER'],json={
        'report_type':'employees_detail','filters':[dict(field='hashed_password',operator='contains',value='unused')]})
    assert rejected.status_code==400


def test_units_aggregate_across_currencies_but_money_does_not():
    from app.servicios.reporte_plan_service import shape
    request=ReporteRequest(report_type='sales_items',group_by=['product'],aggregations=[dict(operation='sum',field='units')])
    columns,rows,_=shape(request,['product','currency','units'],[dict(product='A',currency='USD',units=2),dict(product='A',currency='BOB',units=3)],{})
    assert rows==[dict(product='A',sum_units=5)] and 'currency' not in columns


@pytest.mark.skipif(os.getenv('VESTA_REPORTS_LIVE_TEST')!='1',reason='Opt-in real Gemini integration')
def test_live_provider_and_fallback_execute_screenshot_against_test_database(client,sold_catalog,monkeypatch):
    from dotenv import dotenv_values
    key=dotenv_values('.env').get('GEMINI_API_KEY')
    assert key,'Configura una clave local para la prueba opt-in.'
    monkeypatch.setattr(settings,'GEMINI_API_KEY',key)
    monkeypatch.setattr(ReporteGeminiService,'_today',staticmethod(lambda:date(2026,11,11)))
    _,_,_,_,users=sold_catalog
    result=client.post('/api/v1/reports/voice',headers=users['ADMIN'],json={
        'transcript':'mostrar los 10 productod mas vendidos durante los ultimos 3 meses agrupados por sucursal'})
    assert result.status_code==200,result.text
    plan=result.json()['interpretation'];report=result.json()['report']
    assert plan['report_type']=='sales_items' and plan['partition_by']==['branch']
    assert plan['date_from']=='2026-08-11' and plan['date_to']=='2026-11-11'
    assert len(report['rows'])==20
    assert sorted([r['sum_units'] for r in report['rows'] if r['branch']=='Centro'],reverse=True)==list(range(12,2,-1))
    assert sorted([r['sum_units'] for r in report['rows'] if r['branch']=='Sur'],reverse=True)==list(range(12,2,-1))


def test_provider_outage_composes_screenshot_report(client,sold_catalog,monkeypatch):
    from app.nucleo.excepciones import ProveedorIAUnavailableException
    monkeypatch.setattr(settings,'GEMINI_API_KEY','test')
    monkeypatch.setattr(ReporteGeminiService,'_today',staticmethod(lambda:date(2026,11,11)))
    def unavailable(*args,**kwargs):
        raise ProveedorIAUnavailableException(detail='Alta demanda')
    monkeypatch.setattr(GeminiClient,'generate_text',unavailable)
    _,_,_,_,users=sold_catalog
    result=client.post('/api/v1/reports/voice',headers=users['ADMIN'],json={
        'transcript':'mostrar los 10 productod mas vendidos durante los ultimos 3 meses agrupados por sucursal'})
    assert result.status_code==200,result.text
    assert len(result.json()['report']['rows'])==20
    assert 'Respaldo local' in result.json()['report']['summary']['interpretation_source']


def test_outage_grammar_combines_dimensions_without_ignoring_unknown_filters():
    from app.servicios.reporte_respaldo_service import fallback_plan
    from app.servicios.reporte_interprete_service import validate_plan
    plan=validate_plan(fallback_plan('promedio de pagos por mes y por sucursal durante los ultimos 3 meses',{},None))
    assert plan.group_by==['branch','month'] and plan.limit is None
    assert plan.aggregations[0].operation=='avg' and plan.aggregations[0].field=='amount'
    assert fallback_plan('productos vendidos solo azules',{},None) is None
    assert fallback_plan('margen de productos vendidos',{},None) is None


def test_gemini_json_transport_uses_header_and_short_structured_generation(monkeypatch):
    import httpx
    captured=[]
    monkeypatch.setattr(settings,'GEMINI_API_KEY','fake-test-key')
    monkeypatch.setattr(settings,'GEMINI_MODEL','gemini-3.6-flash')
    def post(url,**kwargs):
        captured.append((url,kwargs))
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'{"report_type":"sales_items"}'}]}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    assert json.loads(GeminiClient.generate_text('plan',json_mode=True))['report_type']=='sales_items'
    url,request=captured[0]
    assert 'fake-test-key' not in url and request['headers']['x-goog-api-key']=='fake-test-key'
    assert request['json']['generationConfig']['responseMimeType']=='application/json'
    assert request['json']['generationConfig']['thinkingConfig']=={'thinkingLevel':'minimal'}
    assert request['timeout']==12


def test_invalid_ai_column_is_repaired_before_execution(monkeypatch):
    monkeypatch.setattr(settings,'GEMINI_API_KEY','test')
    answers=iter([
        json.dumps(dict(report_type='sales_items',group_by=['password'],aggregations=[dict(operation='sum',field='units')])),
        json.dumps(dict(report_type='sales_items',group_by=['month'],aggregations=[dict(operation='sum',field='units')],sort_by='units')),
    ])
    monkeypatch.setattr(GeminiClient,'generate_text',lambda *args,**kwargs:next(answers))
    plan=ReporteGeminiService.interpret('unidades vendidas por mes')
    assert plan.group_by==['month'] and plan.sort_by=='sum_units'


def test_saturated_model_uses_alternate_model(monkeypatch):
    import httpx
    calls=[]
    monkeypatch.setattr(settings,'GEMINI_API_KEY','test')
    monkeypatch.setattr(settings,'GEMINI_MODEL','gemini-3.6-flash')
    monkeypatch.setattr(settings,'GEMINI_REPORT_FALLBACK_MODEL','gemini-2.5-flash')
    def post(url,**kwargs):
        calls.append((url,kwargs))
        payload={'error':{'message':'High demand'}} if len(calls)==1 else {'candidates':[{'content':{'parts':[{'text':'{"report_type":"sales_items"}'}]}}]}
        return httpx.Response(503 if len(calls)==1 else 200,json=payload,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    assert json.loads(GeminiClient.generate_text('plan',json_mode=True))['report_type']=='sales_items'
    assert len(calls)==2 and 'gemini-2.5-flash' in calls[1][0]
    assert calls[1][1]['json']['generationConfig']['thinkingConfig']=={'thinkingBudget':0}


def test_directory_plan_honors_branch_filter_and_composes_counts(client,db_session,world):
    from app.modelos.saas import Empresa
    branch,_,_,_,_,users=world
    db_session.add(Empresa(id=branch.tenant_id,name='VESTA',slug='vesta',is_root=True))
    db_session.commit()
    result=client.post('/api/v1/reports/generate',headers=users['CUSTOMER'],json={
        'report_type':'branches_list','branch_id':branch.id,'report_title':'Sucursales seleccionadas',
        'group_by':['company'],'aggregations':[dict(operation='count',field='*')]})
    assert result.status_code==200,result.text
    assert result.json()['title']=='Sucursales seleccionadas'
    assert result.json()['rows'][0]['count_records']==1


@pytest.mark.parametrize('endpoint,payload',[
    ('generate',{'report_type':'sales_items'}),
    ('voice',{'transcript':'productos vendidos por sucursal'}),
])
def test_report_server_errors_keep_cors_and_log_reference(client,db_session,world,monkeypatch,caplog,endpoint,payload):
    from app.servicios.reporte_service import ReporteService
    from app.modelos.reporte_guardado import ReporteGuardado
    monkeypatch.setattr(ReporteGeminiService,'interpret',lambda *args,**kwargs:ReporteRequest(report_type='sales_items'))
    def broken(*args,**kwargs):
        raise AttributeError('Proveedor has no name')
    monkeypatch.setattr(ReporteService,'generate',broken)
    origin=settings.cors_origins_list[0]
    response=client.post('/api/v1/reports/'+endpoint,headers={**world[-1]['ADMIN'],'Origin':origin},json=payload)
    assert response.status_code==500
    assert response.headers['access-control-allow-origin']==origin
    detail=response.json()['detail']
    assert 'backend' in detail and 'Referencia' in detail
    reference=detail.split(': ')[-1].rstrip('.')
    assert reference in caplog.text and 'REPORT_GENERATION_FAILED' in caplog.text
    assert 'Proveedor' not in detail and 'Gemini' not in detail
    assert db_session.query(ReporteGuardado).count()==0
