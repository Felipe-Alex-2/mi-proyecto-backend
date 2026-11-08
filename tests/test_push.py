import json,uuid
from datetime import timedelta
import pytest
from tests.test_aporte_propio import shop
from tests.test_saas import companies,headers
from app.modelos import Reserva,Notificacion
from app.modelos.push import DispositivoPush,EnvioPush
from app.servicios import push_service as push
from app.configuracion import settings

@pytest.fixture(autouse=True)
def no_background_provider(monkeypatch):
    monkeypatch.setattr(push,'run_batch',lambda:None)

def registration(shop,**updates):
    return dict(installation_id=str(uuid.uuid4()),token='fcm-fid-testing-'+uuid.uuid4().hex,user_id=shop['customer'].id,tenant_id=shop['tenant'],branch_id=shop['origin'],**updates)

def confirmed(db,shop):
    db.info.clear()
    row=Reserva(id=str(uuid.uuid4()),tenant_id=shop['tenant'],customer_id=shop['customer'].id,branch_id=shop['origin'],reservation_code='PUSH-'+uuid.uuid4().hex[:6],status='PENDING',expires_at=push.now()+timedelta(days=1))
    db.add(row);db.commit();row.status='CONFIRMED';db.commit()
    return row

def test_device_registration_validates_session_and_can_revoke_own_installation(client,db_session,shop):
    payload=registration(shop);auth=headers(shop['customer'])
    assert client.post('/api/v1/notifications/push/devices',json=payload).status_code==401
    result=client.post('/api/v1/notifications/push/devices',headers=auth,json=payload)
    assert result.status_code==200,result.text
    assert result.json()=={'registered':True,'server_configured':False}
    for field,value in [('tenant_id',shop['other_admin'].tenant_id),('user_id',shop['admin'].id),('branch_id',shop['destination'])]:
        assert client.post('/api/v1/notifications/push/devices',headers=auth,json=dict(payload,**{field:value})).status_code==409
    assert client.post('/api/v1/notifications/push/devices',headers=auth,json=payload).status_code==200
    db_session.info.clear();assert db_session.query(DispositivoPush).count()==1
    assert client.post('/api/v1/notifications/push/unregister',headers=headers(shop['admin']),json=payload).status_code==200
    db_session.info.clear();assert db_session.get(DispositivoPush,payload['installation_id']).active
    assert client.post('/api/v1/notifications/push/unregister',headers=auth,json=payload).status_code==200
    db_session.info.clear();assert not db_session.get(DispositivoPush,payload['installation_id']).active

def test_confirmation_outbox_is_transactional_and_retries_only_unsent_destinations(client,db_session,shop,monkeypatch):
    first=registration(shop);second=registration(shop)
    for data in [first,second]:assert client.post('/api/v1/notifications/push/devices',headers=headers(shop['customer']),json=data).status_code==200
    confirmed(db_session,shop)
    db_session.info.clear()
    job=db_session.query(EnvioPush).one();assert job.status=='PENDING'
    db_session.add(DispositivoPush(id=str(uuid.uuid4()),tenant_id=shop['other_admin'].tenant_id,user_id=shop['customer'].id,token='foreign-device',token_hash=push.digest('foreign-device'),active=True))
    db_session.commit()
    monkeypatch.setattr(settings,'FIREBASE_PUSH_ENABLED',True);monkeypatch.setattr(settings,'FIREBASE_CREDENTIALS_JSON','{}')
    calls=[]
    def send(token,data,tag):
        calls.append(token);assert data['tenant_id']==shop['tenant'] and data['user_id']==shop['customer'].id
        assert 'message' not in data and 'amount' not in data
        if token==second['token']:raise RuntimeError('temporary network failure')
    assert push.drain(db_session,send)==0
    db_session.refresh(job);assert job.status=='PENDING' and job.attempts==1
    assert 'foreign-device' not in calls and first['token'] in calls
    job.next_attempt_at=push.now()-timedelta(seconds=1);db_session.commit()
    next_calls=[]
    assert push.drain(db_session,lambda token,data,tag:next_calls.append(token))==1
    assert next_calls==[second['token']]
    assert push.drain(db_session,lambda *args:pytest.fail('must not resend a completed job'))==0

def test_rolled_back_confirmation_creates_no_push_and_reconfirmation_is_unique(client,db_session,shop):
    db_session.info.clear()
    r=Reserva(id=str(uuid.uuid4()),tenant_id=shop['tenant'],customer_id=shop['customer'].id,branch_id=shop['origin'],reservation_code='PUSH-ROLLBACK',status='PENDING',expires_at=push.now()+timedelta(days=1))
    db_session.add(r);db_session.commit();r.status='CONFIRMED';db_session.flush();db_session.rollback()
    assert db_session.query(EnvioPush).count()==0 and db_session.query(Notificacion).count()==0
    r.status='CONFIRMED';db_session.commit();r.status='COMPLETED';db_session.commit()
    assert db_session.query(EnvioPush).count()==1 and db_session.query(Notificacion).count()==1

def test_fcm_payload_uses_native_notification_sound_and_fid(monkeypatch):
    from firebase_admin import messaging
    sent=[]
    monkeypatch.setattr(push,'firebase_app',lambda:object())
    monkeypatch.setattr(messaging,'send',lambda message,app:sent.append(message))
    push.send_to_device('fid-test',{'tenant_id':'a','user_id':'u'},'notification-one')
    message=sent[0]
    assert message.fid=='fid-test' and message.token is None
    assert message.android.notification.default_sound is True
    assert message.android.notification.channel_id=='vesta_notifications'
    assert message.notification.body=='Tienes una nueva notificación. Abre la app para verla.'
    assert message.android.notification.tag=='notification-one'

def test_self_test_is_owned_idempotent_and_requires_server_configuration(client,db_session,shop,monkeypatch):
    request={'request_id':str(uuid.uuid4())};auth=headers(shop['customer'])
    assert client.post('/api/v1/notifications/push/test',headers=auth,json=request).status_code==503
    monkeypatch.setattr(settings,'FIREBASE_PUSH_ENABLED',True);monkeypatch.setattr(settings,'FIREBASE_CREDENTIALS_JSON','{}')
    for _ in range(2):assert client.post('/api/v1/notifications/push/test',headers=auth,json=request).status_code==200
    db_session.info.clear();assert db_session.query(EnvioPush).count()==1
    assert client.post('/api/v1/notifications/push/test',headers=headers(shop['admin']),json=request).status_code==409

def test_unregistered_device_is_retired_without_repeating_delivery(client,db_session,shop,monkeypatch):
    from firebase_admin import messaging
    data=registration(shop)
    assert client.post('/api/v1/notifications/push/devices',headers=headers(shop['customer']),json=data).status_code==200
    confirmed(db_session,shop)
    monkeypatch.setattr(settings,'FIREBASE_PUSH_ENABLED',True);monkeypatch.setattr(settings,'FIREBASE_CREDENTIALS_JSON','{}')
    def gone(*args):raise messaging.UnregisteredError('not registered')
    db_session.info.clear();assert push.drain(db_session,gone)==1
    assert not db_session.get(DispositivoPush,data['installation_id']).active


@pytest.mark.parametrize('escaped',[False,True])
def test_split_firebase_variables_support_multiline_and_escaped_key(monkeypatch,escaped):
    key='-----BEGIN PRIVATE KEY-----' + chr(10) + 'test-only-not-a-real-key' + chr(10) + '-----END PRIVATE KEY-----'
    monkeypatch.setattr(settings,'FIREBASE_PUSH_ENABLED',True)
    monkeypatch.setattr(settings,'FIREBASE_CLIENT_EMAIL','test@example.iam.gserviceaccount.com')
    monkeypatch.setattr(settings,'FIREBASE_PROJECT_ID','test-project')
    monkeypatch.setattr(settings,'FIREBASE_PRIVATE_KEY',key.replace(chr(10),chr(92)+'n') if escaped else key)
    monkeypatch.setattr(settings,'FIREBASE_CREDENTIALS_JSON','stale-json')
    assert push.configured()
    result=push.service_credentials()
    assert result['private_key']==key and result['project_id']=='test-project'
    assert result['client_email']=='test@example.iam.gserviceaccount.com'
    assert result['token_uri']=='https://oauth2.googleapis.com/token'


def test_incomplete_split_credentials_do_not_fall_back_to_an_old_json(monkeypatch):
    monkeypatch.setattr(settings,'FIREBASE_PUSH_ENABLED',True)
    monkeypatch.setattr(settings,'FIREBASE_CLIENT_EMAIL','test@example.com')
    monkeypatch.setattr(settings,'FIREBASE_PRIVATE_KEY','')
    monkeypatch.setattr(settings,'FIREBASE_CREDENTIALS_JSON','{}')
    assert not push.configured()
    with pytest.raises(ValueError,match='Completa'):
        push.service_credentials()
