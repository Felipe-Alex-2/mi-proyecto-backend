from datetime import date, datetime, timezone
import pytest

from tests.test_branch_reports_audit import world
from app.configuracion import settings
from app.modelos.pago import Pago
from app.modelos.sucursal import Sucursal
from app.modelos.reserva import Reserva
from tests.test_aporte_propio import shop, paid
from tests.test_saas import companies, headers
from app.servicios.gemini_client import GeminiClient
from app.servicios.reporte_gemini_service import ReporteGeminiService
from app.servicios.reporte_periodo_service import resolve_period


@pytest.mark.parametrize('phrase,start,end', [
    ('ventas de los últimos 3 meses', date(2026,8,11), date(2026,11,11)),
    ('ventas de los ultimos tres meses', date(2026,8,11), date(2026,11,11)),
    ('ventas hace 3 meses', date(2026,8,1), date(2026,8,31)),
    ('pagos de las ultimas dos semanas', date(2026,10,29), date(2026,11,11)),
    ('reservas del mes pasado', date(2026,10,1), date(2026,10,31)),
    ('ventas de la semana pasada', date(2026,11,2), date(2026,11,8)),
    ('ventas del ano pasado', date(2025,1,1), date(2025,12,31)),
    ('ventas desde 2026-10-01', date(2026,10,1), date(2026,11,11)),
    ('ventas desde 01/10/2026 hasta 01/11/2026', date(2026,10,1), date(2026,11,1)),
])
def test_calendar_periods(phrase,start,end):
    filters,_=resolve_period(ReporteGeminiService._normalize(phrase),date(2026,11,11))
    assert filters=={'date_from':start,'date_to':end}


def test_calendar_month_is_not_thirty_days():
    assert resolve_period('ultimo 1 mes',date(2024,3,31))[0]['date_from']==date(2024,2,29)
    assert resolve_period('ultimo 1 mes',date(2025,3,31))[0]['date_from']==date(2025,2,28)


@pytest.fixture
def local_planner(monkeypatch):
    monkeypatch.setattr(settings,'GEMINI_API_KEY','')
    monkeypatch.setattr(ReporteGeminiService,'_today',staticmethod(lambda:date(2026,11,11)))
    monkeypatch.setattr(GeminiClient,'generate_text',lambda *_:pytest.fail('Known dates and rankings must work locally'))


@pytest.mark.parametrize('role',['ADMIN','STORE_MANAGER','CASHIER','CUSTOMER'])
def test_zero_branch_least_sales_dates_and_real_totals(client,db_session,world,local_planner,role):
    center,south,_,_,_,users=world
    empty=Sucursal(name='La Paz',city='La Paz',address='Sin ventas')
    db_session.add(empty);db_session.flush()
    for code,branch,amount,stamp in [
        ('CURRENT',center.id,100,datetime(2026,11,10,12,tzinfo=timezone.utc)),
        ('OLD',south.id,200,datetime(2026,6,1,12,tzinfo=timezone.utc)),
        ('BEFORE-LOCAL-MIDNIGHT',south.id,1,datetime(2026,8,11,3,59,tzinfo=timezone.utc)),
    ]:
        db_session.add(Pago(payment_code=code,branch_id=branch,customer_name='Cliente',concept='Venta',
            currency='USD',amount=amount,status='PAID',paid_at=stamp))
    db_session.commit()
    def ask(text,**extra):
        result=client.post('/api/v1/reports/voice',headers=users[role],json={'transcript':text,**extra})
        assert result.status_code==200,result.text
        return result.json()
    result=ask('la sucursal que menos a vendido hasta a ahora')
    report=result['report']
    assert result['interpretation']['descending'] is False
    assert report['rows'][0]['branch']=='La Paz' and report['rows'][0]['amount']==0
    assert report['summary']['lowest_USD'].endswith('La Paz')
    assert report['summary']['total_USD']==0
    assert report['summary']['comparison_total_USD']==301
    assert not any(key.startswith('leader_') for key in report['summary'])
    result=ask('ventas por sucursal de los ultimos tres meses')
    assert result['interpretation']['date_from']=='2026-08-11'
    assert result['interpretation']['date_to']=='2026-11-11'
    report=result['report']
    assert {r['branch']:r['amount'] for r in report['rows']}=={'Centro':100,'Sur':0,'La Paz':0}
    assert report['summary']['total_USD']==100
    assert 'Últimos 3 meses' in report['summary']['period']
    assert '11/08/2026' in report['narration'] and 'Menor venta' not in report['narration']
    result=ask('la sucursal que mas vendio los ultimos 3 meses')
    assert result['report']['rows'][0]['branch']=='Centro'
    result=ask('sucursales sin ventas de los ultimos tres meses')
    assert {r['branch'] for r in result['report']['rows']}=={'Sur','La Paz'}
    assert result['report']['summary']['total_USD']==0
    scoped=ask('ventas por sucursal de los ultimos tres meses',branch_id=south.id)
    assert scoped['report']['rows'][0]['branch']=='Sur' and scoped['report']['summary']['total_USD']==0


def test_ai_cannot_discard_locally_resolved_period_or_least_ranking(monkeypatch):
    monkeypatch.setattr(settings,'GEMINI_API_KEY','test')
    monkeypatch.setattr(ReporteGeminiService,'_today',staticmethod(lambda:date(2026,11,11)))
    monkeypatch.setattr(GeminiClient,'generate_text',lambda *_,**kwargs:'{"report_type":"sales_by_branch","date_from":"2000-01-01","date_to":"2000-01-31","sort_by":"amount","descending":true}')
    request=ReporteGeminiService.interpret('comparar las sucursales con menos ventas de los ultimos tres meses')
    assert request.date_from==date(2026,8,11) and request.date_to==date(2026,11,11)
    assert request.sort_by=='amount' and request.descending is False


def test_zero_sales_and_rankings_keep_currencies_separate(client,db_session,world,local_planner):
    center,south,_,_,_,users=world
    db_session.add(Sucursal(name='La Paz',city='La Paz',address='Sin ventas'))
    for code,branch,currency,amount in [('USD-SALE',center.id,'USD',100),('BOB-SALE',south.id,'BOB',500)]:
        db_session.add(Pago(payment_code=code,branch_id=branch,customer_name='Cliente',concept='Venta',
            amount=amount,currency=currency,status='PAID',paid_at=datetime(2026,11,10,tzinfo=timezone.utc)))
    db_session.commit()
    result=client.post('/api/v1/reports/voice',headers=users['ADMIN'],json={'transcript':'la sucursal que menos vendio'})
    assert result.status_code==200,result.text
    report=result.json()['report']
    assert len(report['rows'])==2 and {r['currency'] for r in report['rows']}=={'USD','BOB'}
    assert all(r['amount']==0 for r in report['rows'])
    result=client.post('/api/v1/reports/voice',headers=users['ADMIN'],json={'transcript':'sucursales sin ventas'})
    assert result.status_code==200,result.text
    assert {r['branch'] for r in result.json()['report']['rows']}=={'La Paz'}


def test_global_scope_includes_foreign_zero_branches_and_current_scope_excludes_them(client,db_session,shop,local_planner):
    paid(db_session,shop,50,currency='USD')
    auth=headers(shop['admin'])
    result=client.post('/api/v1/reports/voice',headers=auth,json={
        'transcript':'sucursales sin ventas','all_companies':True})
    assert result.status_code==200,result.text
    rows=result.json()['report']['rows']
    assert {(r['company'],r['branch']) for r in rows}=={('moda-a','Norte'),('moda-b','Otra')}
    result=client.post('/api/v1/reports/voice',headers=auth,json={
        'transcript':'sucursales sin ventas','all_companies':False})
    assert result.status_code==200,result.text
    assert {(r['company'],r['branch']) for r in result.json()['report']['rows']}=={('moda-a','Norte')}


def test_periods_apply_to_reservations_not_only_sales(client,db_session,world,local_planner):
    center,_,_,_,customer,users=world
    for code,created in [('CURRENT',datetime(2026,11,10,tzinfo=timezone.utc)),('OLD',datetime(2026,6,1,tzinfo=timezone.utc))]:
        db_session.add(Reserva(reservation_code=code,customer_id=customer.id,branch_id=center.id,
            status='CONFIRMED',created_at=created,expires_at=datetime(2026,12,1,tzinfo=timezone.utc)))
    db_session.commit()
    result=client.post('/api/v1/reports/voice',headers=users['ADMIN'],json={'transcript':'reservas de los ultimos tres meses'})
    assert result.status_code==200,result.text
    assert result.json()['report']['summary']['total']==1
    assert 'Últimos 3 meses' in result.json()['report']['summary']['period']


def test_last_month_is_local_and_ranking_projection_retains_accurate_totals(local_planner):
    from app.esquemas.reporte import ReporteRequest
    from app.servicios.reporte_plan_service import shape
    request=ReporteGeminiService.interpret('ventas del mes pasado')
    assert request.date_from==date(2026,10,1) and request.date_to==date(2026,10,31)
    request=ReporteRequest(report_type='sales_by_branch',limit=2,sort_by='amount',descending=False,
        selected_columns=['branch'])
    _,rows,summary=shape(request,['branch','amount','currency','sales','units'],[
        dict(branch='A',amount=0.1,currency='USD',sales=1,units=1),
        dict(branch='B',amount=0.2,currency='USD',sales=1,units=1),
        dict(branch='C',amount=1,currency='USD',sales=1,units=1),
    ],{'total_USD':1.3,'sales':3,'units':3})
    assert rows==[{'branch':'A','currency':'USD'},{'branch':'B','currency':'USD'}]
    assert summary['total_USD']==0.3 and summary['comparison_total_USD']==1.3
