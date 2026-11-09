import uuid
import pytest
from fastapi.websockets import WebSocketDisconnect
from tests.test_saas import companies, headers
from tests.test_aporte_propio import shop
from app.modelos import Reserva
from app.servicios.saas_service import utcnow
from app.servicios.tiempo_real_service import authorized, hub
from datetime import timedelta


def login(user, **extra):
    return dict(type='authenticate',token=headers(user)['Authorization'].split(' ',1)[1],**extra)


def test_socket_requires_auth_and_rejects_untrusted_origin(client):
    with client.websocket_connect('/api/v1/realtime/ws') as ws:
        ws.send_json({'type':'authenticate','token':'invalid'})
        with pytest.raises(WebSocketDisconnect):ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/realtime/ws',headers={'origin':'https://attacker.example'}):pass


def test_staff_receives_new_reservation_after_http_commit(client,db_session,shop):
    with client.websocket_connect('/api/v1/realtime/ws') as ws:
        ws.send_json(login(shop['admin']));assert ws.receive_json()['type']=='ready'
        result=client.post('/api/v1/reservations',headers=headers(shop['customer']),json={
            'branch_id':shop['origin'],'items':[dict(variant_id=shop['variant'].id,quantity=1)],'payment_method':'EFECTIVO'})
        assert result.status_code==201,result.text
        event=ws.receive_json()
        assert event['type']=='reservation.created' and event['reservation_id']==result.json()['id']
        assert event['tenant_id']==shop['tenant']


def test_customer_cannot_choose_other_company_or_staff_context(client,shop):
    with client.websocket_connect('/api/v1/realtime/ws') as ws:
        ws.send_json(login(shop['customer'],tenant_id=shop['tenant'],branch_id=shop['origin']))
        assert ws.receive_json()['type']=='ready'
    with client.websocket_connect('/api/v1/realtime/ws') as ws:
        ws.send_json(login(shop['admin'],tenant_id=shop['other_admin'].tenant_id,branch_id=shop['foreign']))
        with pytest.raises(WebSocketDisconnect):ws.receive_json()


def test_event_routing_respects_owner_company_and_employee_branch():
    payload=dict(tenant_id='a',branch_id='b',customer_id='client',type='reservation.created')
    def scope(role,user='staff',tenant='a',branch='b'):return dict(role=role,user_id=user,tenant_id=tenant,branch_id=branch)
    assert authorized(scope('ADMIN'),payload)
    assert not authorized(scope('ADMIN',tenant='other'),payload)
    assert authorized(scope('CASHIER'),payload)
    assert not authorized(scope('CASHIER',branch='other'),payload)
    assert not authorized(scope('STORE_MANAGER',branch=None),payload)
    assert authorized(scope('CUSTOMER',user='client'),payload)
    assert not authorized(scope('CUSTOMER',user='other'),payload)
    assert not authorized(scope('ADMIN'),dict(payload,user_id='client'))


def test_rollback_never_emits_an_event_and_nested_commit_waits(client,db_session,shop,monkeypatch):
    sent=[];monkeypatch.setattr(hub,'publish',sent.append)
    def row():return Reserva(id=str(uuid.uuid4()),tenant_id=shop['tenant'],customer_id=shop['customer'].id,
        branch_id=shop['origin'],reservation_code=uuid.uuid4().hex[:12],expires_at=utcnow()+timedelta(days=1),status='PENDING')
    db_session.info.clear();db_session.add(row());db_session.flush();assert sent==[]
    db_session.rollback();assert sent==[]
    nested=db_session.begin_nested();db_session.add(row());db_session.flush();nested.commit()
    assert sent==[]
    db_session.commit()
    assert len([s for s in sent if s['type']=='reservation.created'])==1


def test_disabled_session_is_closed_on_next_heartbeat(client,db_session,shop):
    with client.websocket_connect('/api/v1/realtime/ws') as ws:
        ws.send_json(login(shop['admin']));assert ws.receive_json()['type']=='ready'
        shop['admin'].is_active=False;db_session.commit()
        ws.send_text('ping')
        with pytest.raises(WebSocketDisconnect):ws.receive_json()
