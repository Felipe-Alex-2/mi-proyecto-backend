import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa
class ReporteGuardado(PerteneceEmpresa, Base):
    __tablename__='generated_reports'
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    user_id=Column(String(36),ForeignKey('users.id'),nullable=False)
    result_json=Column(Text,nullable=False)
    email_to=Column(String(254),nullable=True)
    email_status=Column(String(20),nullable=False,default='NOT_REQUESTED')
    created_at=Column(DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
