import uuid
from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class Favorito(PerteneceEmpresa, Base):
    __tablename__ = 'customer_favorites'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'product_id', name='uq_customer_favorite'),)
