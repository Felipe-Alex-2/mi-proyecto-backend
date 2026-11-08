import copy
import uuid
import pytest
from tests.test_wallet import mock_paypal, fund
from tests.test_aporte_propio import shop, paid
from tests.test_saas import companies, headers
from app.servicios.paypal_service import PayPalService
from app.servicios.reporte_gemini_service import ReporteGeminiService
from app.modelos.wallet import RecargaWallet, MovimientoWallet


@pytest.mark.parametrize('marker', ['unit','capture','absent'])
def test_already_captured_order_reconciles_once_without_second_charge(client,db_session,shop,monkeypatch,marker):
    mock_paypal(monkeypatch)
    auth=headers(shop['customer'])
    row=client.post('/api/v1/wallet/topups',headers=auth,json={'amount':100,'request_id':str(uuid.uuid4())}).json()
    raw=PayPalService.capture_order(row['order_id'])['raw']
    unit=raw['purchase_units'][0]
    if marker!='unit':
        value=unit.pop('custom_id')
        if marker=='capture':unit['payments']['captures'][0]['custom_id']=value
    monkeypatch.setattr(PayPalService,'get_order',lambda order:copy.deepcopy(raw))
    def forbidden(order):raise AssertionError('An already captured order must never be captured again')
    monkeypatch.setattr(PayPalService,'capture_order',forbidden)
    for _ in range(2):
        result=client.post('/api/v1/wallet/topups/'+row['id']+'/capture',headers=auth)
        assert result.status_code==200,result.text
        assert result.json()['balance']==100
    assert db_session.query(MovimientoWallet).filter(MovimientoWallet.source_key=='topup:'+row['id']).count()==1


def test_minimal_capture_response_rereads_provider(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch)
    get=PayPalService.get_order; capture=PayPalService.capture_order
    captured={}
    def minimal(order):
        captured[order]=capture(order)['raw']
        return {'raw':{'id':order,'status':'COMPLETED'}}
    monkeypatch.setattr(PayPalService,'get_order',lambda order:captured.get(order) or get(order))
    monkeypatch.setattr(PayPalService,'capture_order',minimal)
    fund(client,shop,50)
    assert client.get('/api/v1/wallet',headers=headers(shop['customer'])).json()['balance']==50


@pytest.mark.parametrize('field,value',[('id','OTHER'),('custom_id','wallet:OTHER'),('value','1'),('currency_code','EUR')])
def test_completed_mismatched_order_is_never_credited(client,db_session,shop,monkeypatch,field,value):
    mock_paypal(monkeypatch);auth=headers(shop['customer'])
    row=client.post('/api/v1/wallet/topups',headers=auth,json={'amount':10,'request_id':str(uuid.uuid4())}).json()
    raw=PayPalService.capture_order(row['order_id'])['raw'];unit=raw['purchase_units'][0]
    if field=='id':raw[field]=value
    elif field=='custom_id':unit[field]=value
    else:unit['payments']['captures'][0]['amount'][field]=value
    monkeypatch.setattr(PayPalService,'get_order',lambda order:raw)
    assert client.post('/api/v1/wallet/topups/'+row['id']+'/capture',headers=auth).status_code==409
    assert client.get('/api/v1/wallet',headers=auth).json()['balance']==0


def test_unified_history_has_wallet_purchase_and_topup_receipts(client,db_session,shop,monkeypatch):
    mock_paypal(monkeypatch);auth=headers(shop['customer'])
    id=fund(client,shop)
    result=client.post('/api/v1/reservations',headers=auth,json={'branch_id':shop['origin'],'payment_method':'WALLET',
        'request_id':str(uuid.uuid4()),'items':[{'variant_id':shop['variant'].id,'quantity':1}]})
    assert result.status_code==201,result.text
    history=client.get('/api/v1/saas/history',headers=auth)
    assert history.status_code==200,history.text
    rows=history.json();assert len(rows)==2
    topup=next(r for r in rows if r['source']=='wallet_topup')
    assert topup['exchange_code'] is None and topup['amount']==100
    reservation=next(r for r in rows if r['source']=='reservation')
    assert reservation['exchange_code']==result.json()['reservation_code']
    for row in rows:
        pdf=client.get('/api/v1/saas/history/'+row['id']+'/invoice',headers=auth)
        assert pdf.status_code==200,pdf.text
        assert pdf.content.startswith(b'%PDF')
    assert client.get('/api/v1/saas/history/wallet:unknown/invoice',headers=auth).status_code==404


def test_customer_directory_and_own_payments_work_without_gemini(client,db_session,shop,monkeypatch):
    auth=headers(shop['customer']);paid(db_session,shop,70,currency='USD')
    for text,kind in [('mis pagos','payments_detail'),('lista las empresas existentes','companies_list'),
                      ('cuantas sucursales existen','branches_list'),('mis recargas','wallet_topups'),
                      ('prendas en stock','products_detail')]:
        response=client.post('/api/v1/reports/voice',headers=auth,json={'transcript':text})
        assert response.status_code==200,response.text
        report=response.json()['report'];assert report['report_type']==kind
        if kind=='companies_list':
            assert report['summary']['companies']==3
            assert {r['company'] for r in report['rows']}=={'VESTA','moda-a','moda-b'}
        if kind=='payments_detail':assert len(report['rows'])==1 and report['rows'][0]['amount']==70
    forbidden=client.post('/api/v1/reports/voice',headers=auth,json={'transcript':'Qué empresa vende más'})
    assert forbidden.status_code==200


def test_dates_filters_and_safe_ai_plan(monkeypatch):
    from app.configuracion import settings
    from app.servicios.gemini_client import GeminiClient
    request=ReporteGeminiService.interpret('mis pagos desde 2026-01-01 hasta 2026-02-01')
    assert str(request.date_from)=='2026-01-01' and str(request.date_to)=='2026-02-01'
    request=ReporteGeminiService.interpret('prendas color rojo talla M menos de 30 dolares')
    assert request.color=='rojo' and request.size=='m' and request.max_price==30
    monkeypatch.setattr(settings,'GEMINI_API_KEY','mock')
    monkeypatch.setattr(GeminiClient,'generate_text',lambda prompt:'{"report_type":"products_detail","sort_by":"price","limit":3,"selected_columns":["product","price"]}')
    request=ReporteGeminiService.interpret('prendas ordenadas por precio')
    assert request.sort_by=='price' and request.limit==3


def test_dynamic_aggregations_preserve_currency_and_customer_scope(client,db_session,shop):
    paid(db_session,shop,30,currency='USD');paid(db_session,shop,50,currency='USD');paid(db_session,shop,70,currency='BOB')
    request={'report_type':'payments_detail','group_by':['payment_type'],
        'aggregations':[{'operation':'sum','field':'amount'},{'operation':'count','field':'*'}]}
    result=client.post('/api/v1/reports/generate',headers=headers(shop['customer']),json=request)
    assert result.status_code==200,result.text
    rows={r['currency']:r for r in result.json()['rows']}
    assert rows['USD']['sum_amount']==80 and rows['USD']['count_records']==2
    assert rows['BOB']['sum_amount']==70
    request['aggregations']=[{'operation':'sum','field':'payment_code'}]
    assert client.post('/api/v1/reports/generate',headers=headers(shop['customer']),json=request).status_code==400


def test_stock_details_and_invalid_plan_fields(client,db_session,shop):
    auth=headers(shop['admin'])
    result=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'products_detail',
        'sort_by':'price','descending':True,'limit':1,'selected_columns':['product','price','units']})
    assert result.status_code==200,result.text
    assert len(result.json()['rows'])==1 and result.json()['rows'][0]['price']==120
    assert client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'products_detail','sort_by':'private_key'}).status_code==400
