from app.nucleo.transacciones import commit_or_flush
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.modelos.proveedor import Proveedor
from app.esquemas.proveedor import ProveedorCreate, ProveedorUpdate
from app.nucleo.excepciones import ConflictoException, NoEncontradoException


class ProveedorService:
    @staticmethod
    def list_suppliers(
        db: Session,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[Proveedor]:
        query = db.query(Proveedor)
        if is_active is not None:
            query = query.filter(Proveedor.is_active == is_active)
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Proveedor.company_name.ilike(s),
                    Proveedor.contact_name.ilike(s),
                    Proveedor.email.ilike(s),
                    Proveedor.phone.ilike(s),
                )
            )
        return query.order_by(Proveedor.company_name.asc()).all()

    @staticmethod
    def get_supplier_by_id(db: Session, supplier_id: str) -> Proveedor:
        supplier = db.query(Proveedor).filter(Proveedor.id == supplier_id).first()
        if not supplier:
            raise NoEncontradoException(detail=f"Proveedor con ID {supplier_id} no encontrado")
        return supplier

    @staticmethod
    def create_supplier(db: Session, payload: ProveedorCreate) -> Proveedor:
        clean_company = payload.company_name.strip()
        clean_email = payload.email.strip().lower()

        existing = db.query(Proveedor).filter(Proveedor.company_name.ilike(clean_company)).first()
        if existing:
            raise ConflictoException(detail=f"Ya existe un proveedor con la razón social '{clean_company}'")

        supplier = Proveedor(
            company_name=clean_company,
            contact_name=payload.contact_name.strip(),
            tax_id=payload.tax_id.strip() if payload.tax_id else None,
            email=clean_email,
            phone=payload.phone.strip(),
            address=payload.address.strip() if payload.address else None,
            is_active=True,
        )
        db.add(supplier)
        commit_or_flush(db)
        db.refresh(supplier)
        return supplier

    @staticmethod
    def update_supplier(db: Session, supplier_id: str, payload: ProveedorUpdate) -> Proveedor:
        supplier = ProveedorService.get_supplier_by_id(db, supplier_id)

        if payload.company_name is not None:
            clean_company = payload.company_name.strip()
            existing = db.query(Proveedor).filter(
                Proveedor.company_name.ilike(clean_company),
                Proveedor.id != supplier_id,
            ).first()
            if existing:
                raise ConflictoException(detail=f"Ya existe otro proveedor con la razón social '{clean_company}'")
            supplier.company_name = clean_company

        if payload.contact_name is not None:
            supplier.contact_name = payload.contact_name.strip()

        if "tax_id" in payload.model_fields_set:
            supplier.tax_id = payload.tax_id.strip() if payload.tax_id else None

        if payload.email is not None:
            supplier.email = payload.email.strip().lower()

        if payload.phone is not None:
            supplier.phone = payload.phone.strip()

        if "address" in payload.model_fields_set:
            supplier.address = payload.address.strip() if payload.address else None

        if payload.is_active is not None:
            supplier.is_active = payload.is_active

        commit_or_flush(db)
        db.refresh(supplier)
        return supplier

    @staticmethod
    def toggle_status(db: Session, supplier_id: str) -> Proveedor:
        supplier = ProveedorService.get_supplier_by_id(db, supplier_id)
        supplier.is_active = not supplier.is_active
        commit_or_flush(db)
        db.refresh(supplier)
        return supplier
