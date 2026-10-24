import uuid
from unittest.mock import patch
from app.nucleo.seguridad import create_access_token
from app.modelos.reserva import Reserva
from app.modelos.stock import Stock
from app.modelos.operacion_sincronizacion import OperacionSincronizacion
from app.modelos.usuario import Usuario
from tests.test_payments_module import _setup_catalog


def command(path, body=None, method="POST", operation_id=None):
    return {"operation_id": operation_id or str(uuid.uuid4()), "method":method,"path":path,"body":body or {}}


def headers(user):
    return {"Authorization":"Bearer "+create_access_token(subject=user.id,claims={"role":"CUSTOMER","email":user.email})}


def test_retry_has_one_reservation_and_one_stock_deduction(client, db_session):
    branch, user, variant = _setup_catalog(db_session)
    payload = command('/reservations',{'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':2}]})
    first=client.post('/api/v1/sync/operations',json=payload,headers=headers(user))
    assert first.status_code==200,first.text
    again=client.post('/api/v1/sync/operations',json=payload,headers=headers(user))
    assert again.json()==first.json()
    assert db_session.query(Reserva).count()==1
    assert db_session.query(Stock).one().quantity==18
    assert db_session.query(OperacionSincronizacion).count()==1
    payload['body']['items'][0]['quantity']=3
    assert client.post('/api/v1/sync/operations',json=payload,headers=headers(user)).status_code==409


def test_first_reservation_wins_last_unit(client, db_session):
    branch,user,variant=_setup_catalog(db_session)
    db_session.query(Stock).update({'quantity':1});db_session.commit()
    body={'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':1}]}
    first=client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(user))
    other=Usuario(email='other-offline@example.com',full_name='Otro cliente',hashed_password='unused',role='CUSTOMER',is_active=True)
    db_session.add(other);db_session.commit()
    second=client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(other))
    assert first.status_code==200
    assert second.status_code==409
    assert second.json()['detail']['code']=='STOCK_INSUFFICIENT'
    assert second.json()['detail']['available']==0
    assert db_session.query(Stock).one().quantity==0
    assert db_session.query(Reserva).count()==1


def test_failure_rolls_back_command_and_receipt(client, db_session):
    branch,user,variant=_setup_catalog(db_session)
    body={'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':1}]}
    with patch('app.servicios.reserva_service.BitacoraService.log_event',side_effect=RuntimeError('failed')):
        try:
            client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(user))
        except RuntimeError:
            pass
    assert db_session.query(Reserva).count()==0
    assert db_session.query(OperacionSincronizacion).count()==0
    assert db_session.query(Stock).one().quantity==20


def test_cart_local_id_resolves_by_owned_variant(client, db_session):
    _,user,variant=_setup_catalog(db_session)
    added=client.post('/api/v1/sync/operations',json=command('/cart/items',{'variant_id':variant.id,'quantity':1}),headers=headers(user))
    assert added.status_code==200
    updated=client.post('/api/v1/sync/operations',json=command('/cart/items/local:abc',{'_variant_id':variant.id,'quantity':3},'PUT'),headers=headers(user))
    assert updated.status_code==200
    assert updated.json()['total_items']==3


def test_offline_paypal_intent_is_not_a_payment(client, db_session):
    branch,user,variant=_setup_catalog(db_session)
    body={'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':1}],'payment_method':'PAYPAL'}
    with patch('app.servicios.paypal_service.PayPalService.create_order') as paypal:
        response=client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(user))
        assert response.status_code==200
        assert response.json()['payment_status']=='PENDING'
        paypal.assert_not_called()
    rid=response.json()['id']
    with patch('app.servicios.paypal_service.PayPalService.create_order',return_value={'order_id':'ORDER-OFFLINE','approval_url':'https://example.com/approve'}) as paypal:
        resumed=client.post(f'/api/v1/reservations/{rid}/paypal-order',headers=headers(user))
        assert resumed.status_code==200,resumed.text
        assert paypal.call_args.kwargs['request_id']==rid
    assert db_session.query(Reserva).count()==1
    assert db_session.query(Stock).one().quantity==19


def test_invalid_and_unsupported_commands(client,db_session):
    _,user,_=_setup_catalog(db_session)
    for payload in [command('/auth/login'),command('/users/me',{'full_name':' '},'PUT')]:
        assert client.post('/api/v1/sync/operations',json=payload,headers=headers(user)).status_code==422
    assert db_session.query(OperacionSincronizacion).count()==0


def test_duplicate_variants_do_not_consume_stock(client,db_session):
    branch,user,variant=_setup_catalog(db_session)
    body={'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':1}]*2}
    assert client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(user)).status_code==400
    assert db_session.query(Stock).one().quantity==20


def test_queued_capture_replay_charges_once(client,db_session):
    branch,user,variant=_setup_catalog(db_session)
    body={'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':1}],'payment_method':'PAYPAL'}
    response=client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(user))
    reservation=db_session.get(Reserva,response.json()['id'])
    reservation.paypal_order_id='ORDER-QUEUE';db_session.commit()
    payload=command('/reservations/paypal-capture',{'paypal_order_id':'ORDER-QUEUE'})
    with patch('app.servicios.paypal_service.PayPalService.capture_order',return_value={'status':'COMPLETED','capture_id':'CAP-QUEUE'}) as paypal:
        first=client.post('/api/v1/sync/operations',json=payload,headers=headers(user))
        second=client.post('/api/v1/sync/operations',json=payload,headers=headers(user))
        assert first.status_code==200,first.text
        assert second.json()==first.json()
        assert first.json()['reservation']['payment_status']=='PAID'
        paypal.assert_called_once()


def test_other_customer_cannot_capture_payment(client,db_session):
    branch,user,variant=_setup_catalog(db_session)
    body={'branch_id':branch.id,'items':[{'variant_id':variant.id,'quantity':1}],'payment_method':'PAYPAL'}
    response=client.post('/api/v1/sync/operations',json=command('/reservations',body),headers=headers(user))
    reservation=db_session.get(Reserva,response.json()['id'])
    reservation.paypal_order_id='ORDER-PRIVATE'
    stranger=Usuario(email='stranger@example.com',full_name='Otra persona',hashed_password='unused',role='CUSTOMER',is_active=True)
    db_session.add(stranger);db_session.commit()
    with patch('app.servicios.paypal_service.PayPalService.capture_order') as paypal:
        response=client.post('/api/v1/sync/operations',json=command('/reservations/paypal-capture',{'paypal_order_id':'ORDER-PRIVATE'}),headers=headers(stranger))
        assert response.status_code==403
        paypal.assert_not_called()


def test_simultaneous_reservations_cannot_claim_same_last_unit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException
    from app.base_datos import Base
    from app.api.v1.sincronizacion import apply_operation, ComandoSincronizacion
    engine=create_engine(f"sqlite:///{tmp_path / 'race.db'}",connect_args={'check_same_thread':False,'timeout':10})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        branch,user,variant=_setup_catalog(db)
        other = Usuario(email='concurrent-offline@example.com', full_name='Otro cliente offline', hashed_password='unused', role='CUSTOMER', is_active=True)
        db.add(other); db.commit()
        db.query(Stock).update({'quantity':1});db.commit()
        uids,bid,vid=[user.id,other.id],branch.id,variant.id
    barrier=Barrier(2)
    def reserve(uid):
        with factory() as db:
            user=db.get(Usuario,uid)
            payload=ComandoSincronizacion.model_validate(command('/reservations',{'branch_id':bid,'items':[{'variant_id':vid,'quantity':1}]}))
            barrier.wait(timeout=10)
            try:
                apply_operation(payload,db,user)
                return 200
            except HTTPException as error:
                return error.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,uids))
        assert results.count(200)==1,results
        assert next(code for code in results if code!=200) in (409,503)
        with factory() as db:
            assert db.query(Stock).one().quantity==0
            assert db.query(Reserva).count()==1
            assert db.query(OperacionSincronizacion).count()==1
    finally:
        engine.dispose()


def test_sync_measurements_and_notifications(client,db_session):
    from app.modelos.notificacion import Notificacion
    _,user,_=_setup_catalog(db_session)
    measurements={'gender':'HOMBRE','height_cm':180,'weight_kg':75,'chest_cm':95,'waist_cm':80,'hip_cm':95}
    response=client.post('/api/v1/sync/operations',json=command('/virtual-fitting/profile',measurements),headers=headers(user))
    assert response.status_code==200,response.text
    assert response.json()['height_cm']==180
    notification=Notificacion(user_id=user.id,title='Reserva',message='Confirmada')
    db_session.add(notification);db_session.commit()
    response=client.post('/api/v1/sync/operations',json=command(f'/notifications/{notification.id}/read',method='PATCH'),headers=headers(user))
    assert response.status_code==200,response.text
    db_session.refresh(notification)
    assert notification.is_read


def test_account_switch_cannot_replay_another_accounts_queue(client,db_session):
    _,user,_=_setup_catalog(db_session)
    payload=command('/users/me',{'full_name':'Otra persona'},'PUT')
    payload['account_id']=str(uuid.uuid4())
    response=client.post('/api/v1/sync/operations',json=payload,headers=headers(user))
    assert response.status_code==403
    db_session.refresh(user)
    assert user.full_name=='Cliente POS'
    assert db_session.query(OperacionSincronizacion).count()==0


def test_stock_conflict_can_reduce_quantity_then_retry_without_duplicates(client, db_session):
    branch, user, variant = _setup_catalog(db_session)
    db_session.query(Stock).update({'quantity': 1}); db_session.commit()
    payload = command('/reservations', {'branch_id': branch.id, 'items': [{'variant_id': variant.id, 'quantity': 2}]})
    rejected = client.post('/api/v1/sync/operations', json=payload, headers=headers(user))
    assert rejected.status_code == 409
    detail = rejected.json()['detail']
    assert detail['variant_id'] == variant.id and detail['requested'] == 2 and detail['available'] == 1
    assert db_session.query(Reserva).count() == db_session.query(OperacionSincronizacion).count() == 0
    assert db_session.query(Stock).one().quantity == 1
    payload['body']['items'][0]['quantity'] = 1
    accepted = client.post('/api/v1/sync/operations', json=payload, headers=headers(user))
    assert accepted.status_code == 200, accepted.text
    replay = client.post('/api/v1/sync/operations', json=payload, headers=headers(user))
    assert replay.json() == accepted.json()
    assert db_session.query(Reserva).count() == db_session.query(OperacionSincronizacion).count() == 1
    assert db_session.query(Stock).one().quantity == 0
