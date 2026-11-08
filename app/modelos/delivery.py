import uuid
from datetime import datetime,timezone
from sqlalchemy import Column,String,ForeignKey,Numeric,Integer,DateTime,Text
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class CotizacionDelivery(PerteneceEmpresa,Base):
    __tablename__='delivery_quotes'
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    customer_id=Column(String(36),ForeignKey('users.id'),nullable=False,index=True)
    branch_id=Column(String(36),ForeignKey('branches.id'),nullable=False)
    origin_maps_url=Column(String(2048),nullable=False)
    destination_maps_url=Column(String(2048),nullable=False)
    origin_lat=Column(Numeric(10,7),nullable=False)
    origin_lon=Column(Numeric(10,7),nullable=False)
    destination_lat=Column(Numeric(10,7),nullable=False)
    destination_lon=Column(Numeric(10,7),nullable=False)
    distance_meters=Column(Integer,nullable=False)
    duration_seconds=Column(Integer,nullable=False)
    fee_bob=Column(Numeric(10,2),nullable=False)
    bob_per_usd=Column(Numeric(10,4),nullable=False)
    fee_usd=Column(Numeric(10,2),nullable=False)
    provider=Column(String(30),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
    expires_at=Column(DateTime(timezone=True),nullable=False)


class PedidoDelivery(PerteneceEmpresa,Base):
    __tablename__='delivery_orders'
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    reservation_id=Column(String(36),ForeignKey('reservations.id'),nullable=False,unique=True)
    quote_id=Column(String(36),ForeignKey('delivery_quotes.id'),nullable=False,unique=True)
    customer_id=Column(String(36),ForeignKey('users.id'),nullable=False,index=True)
    branch_id=Column(String(36),ForeignKey('branches.id'),nullable=False,index=True)
    recipient=Column(String(150),nullable=False)
    phone=Column(String(50),nullable=False)
    address=Column(String(500),nullable=False)
    status=Column(String(30),nullable=False,default='AWAITING_PAYMENT')
    courier=Column(String(150),nullable=False,default='')
    history_json=Column(Text,nullable=False,default='[]')
    created_at=Column(DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
    departed_at=Column(DateTime(timezone=True),nullable=True)
    estimated_arrival_at=Column(DateTime(timezone=True),nullable=True)
    updated_at=Column(DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
