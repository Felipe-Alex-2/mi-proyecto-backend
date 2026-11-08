import base64
import httpx
from tests.test_saas import companies,headers
from app.configuracion import settings
from app.modelos.saas import Empresa,ROOT_TENANT_ID
from app.servicios import reporte_entrega_service as delivery


def test_root_vesta_is_an_existing_company_even_without_branches(client,db_session,companies):
    root,((a,_),(b,_))=companies
    db_session.get(Empresa,a).is_active=False
    db_session.get(Empresa,b).name='MODAT'
    db_session.commit()
    result=client.post('/api/v1/reports/generate',headers=headers(root),json={'report_type':'companies_list'})
    assert result.status_code==200,result.text
    assert result.json()['summary']['companies']==2
    assert {r['company'] for r in result.json()['rows']}=={'VESTA','MODAT'}
    assert next(r for r in result.json()['rows'] if r['company']=='VESTA')['branches']==0


def test_resend_sends_real_pdf_to_edited_email_and_failed_delivery_can_retry(client,db_session,companies,monkeypatch):
    root,_=companies
    monkeypatch.setattr(settings,'RESEND_API_KEY','test-only')
    monkeypatch.setattr(settings,'REPORT_EMAIL_FROM','VESTA <reportes@example.com>')
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200,json={'id':'provider-id'},request=httpx.Request('POST',url))
    monkeypatch.setattr(delivery.httpx,'post',post)
    auth=headers(root)
    result=client.post('/api/v1/reports/generate',headers=auth,json={'report_type':'companies_list'})
    id=result.json()['report_id']
    sent=client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_to':'editado@gmail.com'})
    assert sent.status_code==200 and sent.json()['email_status']=='SENT'
    assert calls[0]['to']==['editado@gmail.com']
    assert base64.b64decode(calls[0]['attachments'][0]['content']).startswith(b'%PDF')
    assert client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_to':'bad-email'}).status_code==422
    def fail(url,**kwargs):return httpx.Response(503,request=httpx.Request('POST',url))
    monkeypatch.setattr(delivery.httpx,'post',fail)
    failed=client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_to':'otro@gmail.com'})
    assert failed.json()['email_status']=='FAILED'
    monkeypatch.setattr(delivery.httpx,'post',post)
    assert client.post('/api/v1/reports/'+id+'/email',headers=auth,json={'email_to':'otro@gmail.com'}).json()['email_status']=='SENT'
