from typing import Optional
from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash


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
        """Create a new user with hashed password."""
        db_obj = User(
            email=obj_in.email.lower().strip(),
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name.strip(),
            is_active=True,
            is_verified=False,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update(db: Session, db_obj: User, obj_in: UserUpdate) -> User:
        """Update an existing user."""
        if obj_in.full_name is not None:
            db_obj.full_name = obj_in.full_name.strip()
        if obj_in.email is not None:
            db_obj.email = obj_in.email.lower().strip()
        if obj_in.password is not None:
            db_obj.hashed_password = get_password_hash(obj_in.password)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj
