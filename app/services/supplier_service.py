from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierUpdate
from app.core.exceptions import ConflictException, NotFoundException


class SupplierService:
    @staticmethod
    def list_suppliers(
        db: Session,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[Supplier]:
        query = db.query(Supplier)
        if is_active is not None:
            query = query.filter(Supplier.is_active == is_active)
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Supplier.company_name.ilike(s),
                    Supplier.contact_name.ilike(s),
                    Supplier.email.ilike(s),
                    Supplier.phone.ilike(s),
                )
            )
        return query.order_by(Supplier.company_name.asc()).all()

    @staticmethod
    def get_supplier_by_id(db: Session, supplier_id: str) -> Supplier:
        supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not supplier:
            raise NotFoundException(detail=f"Proveedor con ID {supplier_id} no encontrado")
        return supplier

    @staticmethod
    def create_supplier(db: Session, payload: SupplierCreate) -> Supplier:
        clean_company = payload.company_name.strip()
        clean_email = payload.email.strip().lower()

        existing = db.query(Supplier).filter(Supplier.company_name.ilike(clean_company)).first()
        if existing:
            raise ConflictException(detail=f"Ya existe un proveedor con la razón social '{clean_company}'")

        supplier = Supplier(
            company_name=clean_company,
            contact_name=payload.contact_name.strip(),
            tax_id=payload.tax_id.strip() if payload.tax_id else None,
            email=clean_email,
            phone=payload.phone.strip(),
            address=payload.address.strip() if payload.address else None,
            is_active=True,
        )
        db.add(supplier)
        db.commit()
        db.refresh(supplier)
        return supplier

    @staticmethod
    def update_supplier(db: Session, supplier_id: str, payload: SupplierUpdate) -> Supplier:
        supplier = SupplierService.get_supplier_by_id(db, supplier_id)

        if payload.company_name is not None:
            clean_company = payload.company_name.strip()
            existing = db.query(Supplier).filter(
                Supplier.company_name.ilike(clean_company),
                Supplier.id != supplier_id,
            ).first()
            if existing:
                raise ConflictException(detail=f"Ya existe otro proveedor con la razón social '{clean_company}'")
            supplier.company_name = clean_company

        if payload.contact_name is not None:
            supplier.contact_name = payload.contact_name.strip()

        if payload.tax_id is not None:
            supplier.tax_id = payload.tax_id.strip() if payload.tax_id else None

        if payload.email is not None:
            supplier.email = payload.email.strip().lower()

        if payload.phone is not None:
            supplier.phone = payload.phone.strip()

        if payload.address is not None:
            supplier.address = payload.address.strip() if payload.address else None

        if payload.is_active is not None:
            supplier.is_active = payload.is_active

        db.commit()
        db.refresh(supplier)
        return supplier

    @staticmethod
    def toggle_status(db: Session, supplier_id: str) -> Supplier:
        supplier = SupplierService.get_supplier_by_id(db, supplier_id)
        supplier.is_active = not supplier.is_active
        db.commit()
        db.refresh(supplier)
        return supplier
