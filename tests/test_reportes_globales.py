import io,json,uuid
import pytest
from app.modelos import Pago
from tests.test_aporte_propio import shop,paid
from tests.test_saas import companies,headers
from app.servicios import reporte_entrega_service as delivery


def test_global_reports_are_available_to_all_roles(client,db_session,shop,companies):
    root,_=companies
    paid(db_session,shop,50,currency='USD')
    db_session.info.clear()
    db_session.add(Pago(tenant_id=shop['other_admin'].tenant_id,branch_id=shop['foreign'],payment_code='GLOBAL-TEST',customer_name='Otra venta',concept='Venta',currency='USD',payment_type='EFECTIVO',amount=200,status='PAID'))
    db_session.commit()
    payload={'report_type':'sales_by_company','all_companies':True}
    assert client.post('/api/v1/reports/generate',headers=headers(shop['admin']),json=payload).status_code==200
    assert client.post('/api/v1/reports/generate',headers=headers(shop['customer']),json=payload).status_code==200
    result=client.post('/api/v1/reports/generate',headers=headers(root),json=payload)
    assert result.status_code==200,result.text
    report=result.json()
    assert report['summary']['leader_USD']=='moda-b'
    assert report['summary']['total_USD']==250
    assert len(report['rows'])==2 and 'Empresa' in report['narration']
    normal=client.post('/api/v1/reports/generate',headers=headers(shop['admin']),json={'report_type':'sales_by_branch'}).json()
    assert normal['summary']['total_USD']==250
    global_branches=client.post('/api/v1/reports/generate',headers=headers(root),json={'report_type':'sales_by_branch','all_companies':True}).json()
    assert global_branches['rows'][0]['company']=='moda-b' and global_branches['rows'][0]['branch']=='Otra'
    assert client.get('/api/v1/reports/'+report['report_id']+'/pdf',headers=headers(shop['admin'])).status_code==404


def test_voice_company_comparison_and_audio_use_actual_totals(client,db_session,shop,companies):
    root,_=companies
    paid(db_session,shop,75,currency='USD')
    result=client.post('/api/v1/reports/voice',headers=headers(root),json={'transcript':'Qué empresa es la que más vende'})
    assert result.status_code==200,result.text
    assert result.json()['interpretation']['report_type']=='sales_by_company'
    assert '75' in result.json()['report']['narration']
    result=client.post('/api/v1/reports/voice',headers=headers(root),json={'transcript':'Qué sucursal vende más','all_companies':True})
    assert result.status_code==200,result.text
    assert result.json()['report']['rows'][0]['company']=='moda-a'


def test_email_pdf_snapshot_self_address_failure_retry_and_owner(client,db_session,shop,monkeypatch):
    paid(db_session,shop,70,currency='USD')
    sent=[]
    def email(recipient,report):sent.append((recipient,report));return True
    monkeypatch.setattr(delivery,'send_report_email',email)
    auth=headers(shop['admin'])
    result=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','email_self':True,'email_to':'ignored@example.com'})
    assert result.status_code==200,result.text
    report=result.json();assert report['email_status']=='SENT'
    assert sent[0][0]==shop['admin'].email
    id=report['report_id']
    pdf=client.get('/api/v1/reports/'+id+'/pdf',headers=auth)
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_self':True}).json()['email_status']=='SENT'
    assert len(sent)==1
    paid(db_session,shop,10,currency='USD')
    monkeypatch.setattr(delivery,'send_report_email',lambda recipient,report:False)
    retry=client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_to':'another@gmail.com'})
    assert retry.status_code==200 and retry.json()['email_status']=='FAILED'
    assert retry.json()['summary']['total_USD']==70
    monkeypatch.setattr(delivery,'send_report_email',email)
    retry=client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_to':'another@gmail.com'})
    assert retry.json()['email_status']=='SENT' and sent[-1][0]=='another@gmail.com'
    assert client.post('/api/v1/reports/'+id+'/email',headers=headers(shop['other_admin']),json={'email_self':True}).status_code==404
    assert client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','email_to':'bad\r\nBcc:other@example.com'}).status_code==422


def test_report_mail_is_an_actual_pdf_attachment(monkeypatch):
    from app.configuracion import settings
    from app.esquemas.reporte import ReporteResponse
    monkeypatch.setattr(settings,'SMTP_USER','sender@example.com');monkeypatch.setattr(settings,'SMTP_PASSWORD','test')
    messages=[]
    class SMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):pass
        def starttls(self):pass
        def login(self,*args):pass
        def send_message(self,msg):messages.append(msg)
    monkeypatch.setattr(delivery.smtplib,'SMTP',SMTP)
    assert delivery.send_report_email('receiver@gmail.com',ReporteResponse(report_type='sales_by_branch',title='Ventas',generated_by='manual'))
    attachment=list(messages[0].iter_attachments())[0]
    assert attachment.get_content_type()=='application/pdf' and attachment.get_payload(decode=True).startswith(b'%PDF')


def test_reports_available_to_customer_with_global_financial_scope(client,db_session,shop,monkeypatch):
    from datetime import timedelta
    from app.servicios.saas_service import utcnow
    from app.modelos.saas import Suscripcion
    paid(db_session,shop,30,currency='USD')
    db_session.info.clear()
    db_session.add(Pago(tenant_id=shop['tenant'],branch_id=shop['origin'],payment_code='OTHER-CUSTOMER-SALE',customer_name='Otra persona',concept='Venta ajena',currency='USD',payment_type='EFECTIVO',amount=200,status='PAID'))
    sub=db_session.get(Suscripcion,shop['tenant']);sub.plan_code='PRO';sub.expires_at=utcnow()+timedelta(days=1)
    db_session.commit()
    monkeypatch.setattr(delivery,'send_report_email',lambda recipient,report:True)
    auth=headers(shop['customer'])
    result=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','email_self':True,'_customer_id':None})
    assert result.status_code==200,result.text
    report=result.json()
    assert report['summary']['total_USD']==230 and report['summary']['sales']==2
    assert report['title']=='Ventas cobradas por sucursal' and report['email_status']=='SENT'
    profile=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'registered_customers'}).json()
    assert len(profile['rows'])==1 and profile['rows'][0]['email']==shop['customer'].email
    assert client.get('/api/v1/reports/'+report['report_id']+'/pdf',headers=auth).status_code==200
    assert client.post('/api/v1/reports/'+report['report_id']+'/email',headers=auth,json={'email_self':True}).status_code==200
    other=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','branch_id':shop['destination']})
    assert other.status_code==200
    voice=client.post('/api/v1/reports/voice',headers=auth,json={'transcript':'Mis ventas','email_self':True})
    assert voice.status_code==200,voice.text
    assert voice.json()['report']['summary']['total_USD']==230
    assert client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','all_companies':True}).status_code==200


def test_cashier_can_generate_voice_export_and_email_global_report(client,db_session,shop,monkeypatch):
    from app.modelos import Usuario
    from app.modelos.saas import Suscripcion
    from datetime import timedelta
    from app.servicios.saas_service import utcnow
    paid(db_session,shop,30,currency='USD')
    db_session.info.clear()
    cashier=Usuario(tenant_id=shop['tenant'],branch_id=shop['origin'],role='CASHIER',email='cashier-reports@example.com',full_name='Cajero Reportes',hashed_password='unused')
    db_session.add(cashier)
    db_session.add(Pago(tenant_id=shop['tenant'],branch_id=shop['destination'],payment_code='OTHER-BRANCH-SALE',customer_name='Otra venta',concept='Venta',currency='USD',payment_type='EFECTIVO',amount=200,status='PAID'))
    sub=db_session.get(Suscripcion,shop['tenant']);sub.plan_code='PRO';sub.expires_at=utcnow()+timedelta(days=1)
    db_session.commit()
    monkeypatch.setattr(delivery,'send_report_email',lambda recipient,report:True)
    auth=headers(cashier)
    report=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','email_self':True})
    assert report.status_code==200,report.text
    assert report.json()['summary']['total_USD']==230
    assert client.get('/api/v1/reports/'+report.json()['report_id']+'/pdf',headers=auth).status_code==200
    voice=client.post('/api/v1/reports/voice',headers=auth,json={'transcript':'Qué sucursal vende más'})
    assert voice.status_code==200,voice.text
    assert voice.json()['report']['summary']['total_USD']==230
    assert client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'sales_by_branch','branch_id':shop['destination']}).status_code==200
