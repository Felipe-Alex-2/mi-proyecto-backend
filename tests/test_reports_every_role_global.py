import pytest
from tests.test_saas import companies,headers
from tests.test_aporte_propio import shop,paid
from app.modelos.usuario import Usuario
from app.modelos.pago import Pago
from app.servicios import reporte_entrega_service as delivery


@pytest.mark.parametrize('role',['CUSTOMER','CASHIER','STORE_MANAGER','ADMIN'])
def test_every_role_can_report_foreign_company_download_and_email(client,db_session,shop,monkeypatch,role):
    paid(db_session,shop,40,currency='USD')
    db_session.info.clear()
    if role=='CUSTOMER':user=shop['customer']
    elif role=='ADMIN':user=shop['admin']
    else:
        user=Usuario(tenant_id=shop['tenant'],branch_id=shop['origin'],role=role,
            email=role.lower()+'-global@example.com',full_name=role,hashed_password='unused')
        db_session.add(user)
    db_session.add(Pago(tenant_id=shop['other_admin'].tenant_id,branch_id=shop['foreign'],payment_code='FOREIGN-GLOBAL',
        customer_name='Venta externa',concept='Venta',amount=200,currency='USD',payment_type='EFECTIVO',status='PAID'))
    db_session.commit()
    auth=headers(user)
    response=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_company'})
    assert response.status_code==200,response.text
    report=response.json()
    assert report['summary']['companies']==2 and report['summary']['total_USD']==240
    assert report['platform_only'] is False
    branches=client.get('/api/v1/reports/branches',headers=auth)
    assert branches.status_code==200 and shop['foreign'] in {b['id'] for b in branches.json()}
    foreign=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','branch_id':shop['foreign']})
    assert foreign.status_code==200 and foreign.json()['summary']['total_USD']==200
    voice=client.post('/api/v1/reports/voice',headers=auth,json={'transcript':'Qué empresa vende más'})
    assert voice.status_code==200 and voice.json()['report']['summary']['total_USD']==240
    assert client.get('/api/v1/reports/'+report['report_id']+'/pdf',headers=auth).content.startswith(b'%PDF')
    sent=[]
    monkeypatch.setattr(delivery,'send_report_email',lambda recipient,report:sent.append(recipient) or True)
    assert client.post('/api/v1/reports/'+report['report_id']+'/email',headers=auth,json={'email_self':True}).status_code==200
    assert sent==[user.email]
    # Reporting must not switch the account's working company or open operational endpoints.
    assert client.get('/api/v1/branches/'+shop['foreign'],headers=auth).status_code in (403,404)
    assert client.get('/api/v1/reports/'+report['report_id']+'/pdf',headers=headers(shop['other_admin'])).status_code==404


def test_global_reports_still_require_login(client):
    assert client.post('/api/v1/reports/generate',json={'report_type':'sales_by_company'}).status_code==401
    assert client.get('/api/v1/reports/branches').status_code==401
