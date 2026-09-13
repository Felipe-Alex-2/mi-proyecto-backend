from typing import Optional, List, Tuple
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate, UserCreateAdmin, UserUpdateAdmin
from app.core.security import get_password_hash
from app.core.exceptions import ConflictException, BadRequestException


class UserService:
    @staticmethod
    def get_by_id(db: Session, user_id: str) -> Optional[User]:
        """Fetch user by primary key ID."""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[User]:
        """Fetch user by email address."""
        return db.query(User).filter(User.email == email.lower().strip()).first()

    @staticmethod
    def create(db: Session, obj_in: UserCreate) -> User:
        """Create a new user with hashed password (autoregistration assigns ADMIN by MVP rule)."""
        clean_email = obj_in.email.lower().strip()
        existing = UserService.get_by_email(db, clean_email)
        if existing:
            raise ConflictException(detail="El correo electrónico ya está registrado")

        db_obj = User(
            email=clean_email,
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name.strip(),
            phone=getattr(obj_in, "phone", None),
            role=UserRole.ADMIN.value,
            is_active=True,
            is_verified=False,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update(db: Session, db_obj: User, obj_in: UserUpdate) -> User:
        """Update an existing user profile."""
        if obj_in.full_name is not None:
            db_obj.full_name = obj_in.full_name.strip()
        if obj_in.email is not None:
            clean_email = obj_in.email.lower().strip()
            if clean_email != db_obj.email.lower():
                existing = UserService.get_by_email(db, clean_email)
                if existing:
                    raise ConflictException(detail="El correo electrónico ya está registrado por otro usuario")
                db_obj.email = clean_email
        if getattr(obj_in, "phone", None) is not None:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None
        if obj_in.password is not None:
            db_obj.hashed_password = get_password_hash(obj_in.password)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def list_users(
        db: Session,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[User]:
        """List users with optional search and filters."""
        query = db.query(User)

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.phone.ilike(pattern),
                )
            )

        if role:
            query = query.filter(User.role == role)

        if is_active is not None:
            query = query.filter(User.is_active == is_active)

        return query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def create_by_admin(db: Session, obj_in: UserCreateAdmin) -> User:
        """Create a new user/employee created by an Admin with a specific role."""
        existing = UserService.get_by_email(db, obj_in.email)
        if existing:
            raise ConflictException(detail="El correo electrónico ya está registrado")

        role_val = obj_in.role.value if hasattr(obj_in.role, "value") else str(obj_in.role)

        db_obj = User(
            email=obj_in.email.lower().strip(),
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name.strip(),
            phone=obj_in.phone.strip() if obj_in.phone else None,
            role=role_val,
            is_active=True,
            is_verified=True,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update_by_admin(db: Session, db_obj: User, obj_in: UserUpdateAdmin) -> User:
        """Update an existing user/employee by an Admin."""
        if obj_in.email and obj_in.email.lower().strip() != db_obj.email:
            existing = UserService.get_by_email(db, obj_in.email)
            if existing:
                raise ConflictException(detail="El correo electrónico ya está registrado por otro usuario")
            db_obj.email = obj_in.email.lower().strip()

        if obj_in.full_name is not None:
            db_obj.full_name = obj_in.full_name.strip()

        if obj_in.phone is not None:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None

        if obj_in.role is not None:
            db_obj.role = obj_in.role.value if hasattr(obj_in.role, "value") else str(obj_in.role)

        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active

        if obj_in.password:
            db_obj.hashed_password = get_password_hash(obj_in.password)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def toggle_status(db: Session, db_obj: User, current_user_id: str) -> User:
        """Activate or deactivate a user account. Cannot self-deactivate."""
        if db_obj.id == current_user_id:
            raise BadRequestException(detail="No puedes desactivar tu propia cuenta de administrador")

        db_obj.is_active = not db_obj.is_active
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj
