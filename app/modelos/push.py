"""Device registrations and a transactional, retryable FCM outbox."""
import uuid
from datetime import datetime,timezone
from sqlalchemy import Column,String,Text,DateTime,Integer,Boolean,ForeignKey,UniqueConstraint
from sqlalchemy.orm import relationship
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa

def now():return datetime.now(timezone.utc)

class DispositivoPush(PerteneceEmpresa,Base):
    __tablename__='push_devices'
    id=Column(String(36),primary_key=True)
    user_id=Column(String(36),ForeignKey('users.id'),nullable=False,index=True)
    branch_id=Column(String(36),ForeignKey('branches.id'),nullable=True)
    token_hash=Column(String(64),nullable=False,unique=True)
    token=Column(Text,nullable=False)
    active=Column(Boolean,nullable=False,default=True)
    updated_at=Column(DateTime(timezone=True),nullable=False,default=now)

class EnvioPush(PerteneceEmpresa,Base):
    __tablename__='push_outbox'
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    notification_id=Column(String(36),ForeignKey('notifications.id'),nullable=False,unique=True)
    notification=relationship('Notificacion')
    user_id=Column(String(36),ForeignKey('users.id'),nullable=False)
    branch_id=Column(String(36),ForeignKey('branches.id'),nullable=True)
    data_json=Column(Text,nullable=False)
    sent_devices_json=Column(Text,nullable=False,default='[]')
    status=Column(String(20),nullable=False,default='PENDING',index=True)
    attempts=Column(Integer,nullable=False,default=0)
    created_at=Column(DateTime(timezone=True),nullable=False,default=now)
    next_attempt_at=Column(DateTime(timezone=True),nullable=False,default=now)
