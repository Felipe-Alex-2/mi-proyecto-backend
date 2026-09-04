from typing import List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.branch import Branch
from app.models.user import User, UserRole
from app.schemas.branch import BranchCreate, BranchUpdate, BranchResponse, BranchStaffMember
from app.core.exceptions import ConflictException, NotFoundException, BadRequestException


class BranchService:
    @staticmethod
    def get_by_id(db: Session, branch_id: str) -> Optional[Branch]:
        """Fetch branch by ID."""
        return db.query(Branch).filter(Branch.id == branch_id).first()

    @staticmethod
    def list_branches(
        db: Session,
        city: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[Branch]:
        """List branches with optional city and active status filters."""
        query = db.query(Branch)

        if city:
            query = query.filter(func.lower(Branch.city) == city.lower().strip())

        if is_active is not None:
            query = query.filter(Branch.is_active == is_active)

        return query.order_by(Branch.city.asc(), Branch.name.asc()).all()

    @staticmethod
    def create_branch(db: Session, obj_in: BranchCreate) -> Branch:
        """Create a new branch, validating duplicate names in the same city (FA03)."""
        name_clean = obj_in.name.strip()
        city_clean = obj_in.city.strip()

        existing = (
            db.query(Branch)
            .filter(
                func.lower(Branch.name) == name_clean.lower(),
                func.lower(Branch.city) == city_clean.lower(),
            )
            .first()
        )
        if existing:
            raise ConflictException(
                detail=f"Ya existe una sucursal con el nombre '{name_clean}' en la ciudad de {city_clean}"
            )

        db_obj = Branch(
            name=name_clean,
            city=city_clean,
            address=obj_in.address.strip(),
            phone=obj_in.phone.strip() if obj_in.phone else None,
            opening_hours=obj_in.opening_hours.strip() if obj_in.opening_hours else None,
            is_active=True,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update_branch(db: Session, db_obj: Branch, obj_in: BranchUpdate) -> Branch:
        """Update branch details, enforcing uniqueness in city if name or city changed."""
        new_name = obj_in.name.strip() if obj_in.name is not None else db_obj.name
        new_city = obj_in.city.strip() if obj_in.city is not None else db_obj.city

        if new_name.lower() != db_obj.name.lower() or new_city.lower() != db_obj.city.lower():
            existing = (
                db.query(Branch)
                .filter(
                    func.lower(Branch.name) == new_name.lower(),
                    func.lower(Branch.city) == new_city.lower(),
                    Branch.id != db_obj.id,
                )
                .first()
            )
            if existing:
                raise ConflictException(
                    detail=f"Ya existe una sucursal con el nombre '{new_name}' en la ciudad de {new_city}"
                )

        if obj_in.name is not None:
            db_obj.name = new_name
        if obj_in.city is not None:
            db_obj.city = new_city
        if obj_in.address is not None:
            db_obj.address = obj_in.address.strip()
        if obj_in.phone is not None:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None
        if obj_in.opening_hours is not None:
            db_obj.opening_hours = obj_in.opening_hours.strip() if obj_in.opening_hours else None
        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def toggle_status(db: Session, db_obj: Branch) -> Branch:
        """Toggle active status of a branch (temporary closure or reopening - FA02)."""
        db_obj.is_active = not db_obj.is_active
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def assign_staff(db: Session, branch: Branch, user_ids: List[str]) -> Branch:
        """Assign or transfer employees (Encargados o Cajeros) to a branch (FA01)."""
        for uid in user_ids:
            user = db.query(User).filter(User.id == uid).first()
            if not user:
                raise NotFoundException(detail=f"Usuario con ID '{uid}' no encontrado")

            allowed_roles = [UserRole.STORE_MANAGER.value, UserRole.CASHIER.value, "STORE_MANAGER", "CASHIER"]
            if user.role not in allowed_roles:
                raise BadRequestException(
                    detail=f"El usuario {user.full_name} tiene rol '{user.role}'. Solo se pueden asignar Encargados o Cajeros a una sucursal."
                )

            # Assign or transfer (if previously assigned to another branch)
            user.branch_id = branch.id
            db.add(user)

        db.commit()
        db.refresh(branch)
        return branch

    @staticmethod
    def remove_staff(db: Session, branch: Branch, user_id: str) -> Branch:
        """Unassign an employee from the branch."""
        user = db.query(User).filter(User.id == user_id, User.branch_id == branch.id).first()
        if not user:
            raise NotFoundException(detail="El empleado no está asignado a esta sucursal")

        user.branch_id = None
        db.add(user)
        db.commit()
        db.refresh(branch)
        return branch

    @classmethod
    def format_response(cls, branch: Branch) -> BranchResponse:
        """Convert Branch model to BranchResponse with manager and cashiers."""
        employees = branch.employees or []
        staff_members = [BranchStaffMember.model_validate(e) for e in employees]

        manager = None
        cashiers = []

        for member in staff_members:
            if member.role == UserRole.STORE_MANAGER.value or member.role == "STORE_MANAGER":
                if not manager:
                    manager = member
                else:
                    cashiers.append(member)
            else:
                cashiers.append(member)

        return BranchResponse(
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
