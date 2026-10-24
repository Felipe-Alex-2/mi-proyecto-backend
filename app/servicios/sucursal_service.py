from app.nucleo.transacciones import commit_or_flush
from typing import List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.modelos.sucursal import Sucursal
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.sucursal import SucursalCreate, SucursalUpdate, SucursalResponse, PersonalSucursal
from app.nucleo.excepciones import ConflictoException, NoEncontradoException, SolicitudInvalidaException
from app.nucleo.ubicaciones_bolivia import municipality_name
from app.modelos.saas import Empresa, ROOT_TENANT_ID


class SucursalService:
    @staticmethod
    def validar_ciudad(db, city, tenant_id=None):
        tenant = db.get(Empresa, tenant_id or db.info.get('tenant_id') or ROOT_TENANT_ID)
        if tenant and tenant.department:
            return municipality_name(tenant.department, city)
        # Existing companies can retain/edit their legacy branches until assigned.
        return city.strip()

    @staticmethod
    def get_by_id(db: Session, branch_id: str) -> Optional[Sucursal]:
        """Fetch branch by ID."""
        return db.query(Sucursal).filter(Sucursal.id == branch_id).first()

    @staticmethod
    def list_branches(
        db: Session,
        city: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[Sucursal]:
        """List branches with optional city and active status filters."""
        query = db.query(Sucursal)

        if city:
            query = query.filter(func.lower(Sucursal.city) == city.lower().strip())

        if is_active is not None:
            query = query.filter(Sucursal.is_active == is_active)

        return query.order_by(Sucursal.city.asc(), Sucursal.name.asc()).all()

    @staticmethod
    def create_branch(db: Session, obj_in: SucursalCreate) -> Sucursal:
        """Create a new branch, validating duplicate names in the same city (FA03)."""
        name_clean = obj_in.name.strip()
        city_clean = SucursalService.validar_ciudad(db, obj_in.city)
        tenant = db.get(Empresa, db.info.get('tenant_id') or ROOT_TENANT_ID)
        if tenant and not tenant.department:
            raise SolicitudInvalidaException(detail='Solicita al administrador SaaS asignar un departamento a tu empresa antes de crear sucursales.')

        existing = (
            db.query(Sucursal)
            .filter(
                func.lower(Sucursal.name) == name_clean.lower(),
                func.lower(Sucursal.city) == city_clean.lower(),
            )
            .first()
        )
        if existing:
            raise ConflictoException(
                detail=f"Ya existe una sucursal con el nombre '{name_clean}' en la ciudad de {city_clean}"
            )

        db_obj = Sucursal(
            name=name_clean,
            city=city_clean,
            address=obj_in.address.strip(),
            phone=obj_in.phone.strip() if obj_in.phone else None,
            opening_hours=obj_in.opening_hours.strip() if obj_in.opening_hours else None,
            is_active=True,
        )
        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update_branch(db: Session, db_obj: Sucursal, obj_in: SucursalUpdate) -> Sucursal:
        """Update branch details, enforcing uniqueness in city if name or city changed."""
        new_name = obj_in.name.strip() if obj_in.name is not None else db_obj.name
        new_city = SucursalService.validar_ciudad(db, obj_in.city, db_obj.tenant_id) if obj_in.city is not None else db_obj.city

        if new_name.lower() != db_obj.name.lower() or new_city.lower() != db_obj.city.lower():
            existing = (
                db.query(Sucursal)
                .filter(
                    func.lower(Sucursal.name) == new_name.lower(),
                    func.lower(Sucursal.city) == new_city.lower(),
                    Sucursal.id != db_obj.id,
                )
                .first()
            )
            if existing:
                raise ConflictoException(
                    detail=f"Ya existe una sucursal con el nombre '{new_name}' en la ciudad de {new_city}"
                )

        if obj_in.name is not None:
            db_obj.name = new_name
        if obj_in.city is not None:
            db_obj.city = new_city
        if obj_in.address is not None:
            db_obj.address = obj_in.address.strip()
        if "phone" in obj_in.model_fields_set:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None
        if "opening_hours" in obj_in.model_fields_set:
            db_obj.opening_hours = obj_in.opening_hours.strip() if obj_in.opening_hours else None
        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active

        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def toggle_status(db: Session, db_obj: Sucursal) -> Sucursal:
        """Toggle active status of a branch (temporary closure or reopening - FA02)."""
        db_obj.is_active = not db_obj.is_active
        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def assign_staff(db: Session, branch: Sucursal, user_ids: List[str]) -> Sucursal:
        """Assign or transfer employees (Encargados o Cajeros) to a branch (FA01)."""
        for uid in user_ids:
            user = db.query(Usuario).filter(Usuario.id == uid).first()
            if not user:
                raise NoEncontradoException(detail=f"Usuario con ID '{uid}' no encontrado")

            allowed_roles = [RolUsuario.STORE_MANAGER.value, RolUsuario.CASHIER.value, "STORE_MANAGER", "CASHIER"]
            if user.role not in allowed_roles:
                raise SolicitudInvalidaException(
                    detail=f"El usuario {user.full_name} tiene rol '{user.role}'. Solo se pueden asignar Encargados o Cajeros a una sucursal."
                )

            # Assign or transfer (if previously assigned to another branch)
            user.branch_id = branch.id
            db.add(user)

        commit_or_flush(db)
        db.refresh(branch)
        return branch

    @staticmethod
    def remove_staff(db: Session, branch: Sucursal, user_id: str) -> Sucursal:
        """Unassign an employee from the branch."""
        user = db.query(Usuario).filter(Usuario.id == user_id, Usuario.branch_id == branch.id).first()
        if not user:
            raise NoEncontradoException(detail="El empleado no está asignado a esta sucursal")

        user.branch_id = None
        db.add(user)
        commit_or_flush(db)
        db.refresh(branch)
        return branch

    @classmethod
    def format_response(cls, branch: Sucursal) -> SucursalResponse:
        """Convert Sucursal model to SucursalResponse with manager and cashiers."""
        employees = branch.employees or []
        staff_members = [PersonalSucursal.model_validate(e) for e in employees]

        manager = None
        cashiers = []

        for member in staff_members:
            if member.role == RolUsuario.STORE_MANAGER.value or member.role == "STORE_MANAGER":
                if not manager:
                    manager = member
                else:
                    cashiers.append(member)
            else:
                cashiers.append(member)

        return SucursalResponse(
            id=branch.id,
            name=branch.name,
            city=branch.city,
            address=branch.address,
            phone=branch.phone,
            opening_hours=branch.opening_hours,
            is_active=branch.is_active,
            created_at=branch.created_at,
            updated_at=branch.updated_at,
            staff_count=len(staff_members),
            manager=manager,
            cashiers=cashiers,
        )
