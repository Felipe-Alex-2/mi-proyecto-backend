from app.nucleo.transacciones import commit_or_flush
from typing import Optional, List, Tuple
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioCreateAdmin, UsuarioUpdateAdmin
from app.nucleo.seguridad import get_password_hash
from app.nucleo.excepciones import ConflictoException, SolicitudInvalidaException


class UsuarioService:
    @staticmethod
    def get_by_id(db: Session, user_id: str) -> Optional[Usuario]:
        """Fetch user by primary key ID."""
        return db.query(Usuario).filter(Usuario.id == user_id).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[Usuario]:
        """Fetch user by email address."""
        return db.query(Usuario).execution_options(skip_tenant=True).filter(func.lower(func.trim(Usuario.email)) == email.lower().strip()).first()

    @staticmethod
    def create(db: Session, obj_in: UsuarioCreate) -> Usuario:
        """Create a customer account; employee roles require the admin endpoint."""
        clean_email = obj_in.email.lower().strip()
        existing = UsuarioService.get_by_email(db, clean_email)
        if existing:
            raise ConflictoException(detail="El correo electrónico ya está registrado")

        db_obj = Usuario(
            email=clean_email,
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name.strip(),
            phone=getattr(obj_in, "phone", None),
            role=RolUsuario.CUSTOMER.value,
            is_active=True,
            is_verified=False,
        )
        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update(db: Session, db_obj: Usuario, obj_in: UsuarioUpdate) -> Usuario:
        """Update an existing user profile."""
        if obj_in.full_name is not None:
            db_obj.full_name = obj_in.full_name.strip()
        if obj_in.email is not None:
            clean_email = obj_in.email.lower().strip()
            if clean_email != db_obj.email.lower():
                existing = UsuarioService.get_by_email(db, clean_email)
                if existing:
                    raise ConflictoException(detail="El correo electrónico ya está registrado por otro usuario")
                db_obj.email = clean_email
        if "phone" in obj_in.model_fields_set:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None
        if obj_in.avatar_id is not None:
            db_obj.avatar_id = obj_in.avatar_id
        if 'profile_photo' in obj_in.model_fields_set:
            db_obj.profile_photo = obj_in.profile_photo
        if obj_in.password is not None:
            db_obj.hashed_password = get_password_hash(obj_in.password)

        db.add(db_obj)
        commit_or_flush(db)
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
    ) -> List[Usuario]:
        """List users with optional search and filters."""
        query = db.query(Usuario)
        if db.info.get('tenant_context'):
            query = query.filter(Usuario.tenant_id == db.info.get('tenant_id'))

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Usuario.full_name.ilike(pattern),
                    Usuario.email.ilike(pattern),
                    Usuario.phone.ilike(pattern),
                )
            )

        if role:
            query = query.filter(Usuario.role == role)

        if is_active is not None:
            query = query.filter(Usuario.is_active == is_active)

        return query.order_by(Usuario.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def create_by_admin(db: Session, obj_in: UsuarioCreateAdmin) -> Usuario:
        """Create a new user/employee created by an Admin with a specific role."""
        existing = UsuarioService.get_by_email(db, obj_in.email)
        if existing:
            raise ConflictoException(detail="El correo electrónico ya está registrado")

        role_val = obj_in.role.value if hasattr(obj_in.role, "value") else str(obj_in.role)

        from app.modelos.sucursal import Sucursal
        if obj_in.branch_id and not db.query(Sucursal).filter(Sucursal.id == obj_in.branch_id).first():
            raise SolicitudInvalidaException(detail='La sucursal no pertenece a tu empresa')
        db_obj = Usuario(
            tenant_id=db.info.get('tenant_id') if role_val != 'CUSTOMER' else None,
            selected_tenant_id=db.info.get('tenant_id'), branch_id=obj_in.branch_id,
            email=obj_in.email.lower().strip(),
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name.strip(),
            phone=obj_in.phone.strip() if obj_in.phone else None,
            role=role_val,
            is_active=True,
            is_verified=True,
        )
        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update_by_admin(db: Session, db_obj: Usuario, obj_in: UsuarioUpdateAdmin) -> Usuario:
        """Update an existing user/employee by an Admin."""
        if db.info.get('tenant_context') and db_obj.role == 'CUSTOMER':
            raise SolicitudInvalidaException(detail='El cliente administra su cuenta personal desde su perfil')
        if obj_in.branch_id is not None:
            from app.modelos.sucursal import Sucursal
            if not db.query(Sucursal).filter(Sucursal.id == obj_in.branch_id).first():
                raise SolicitudInvalidaException(detail='La sucursal no pertenece a tu empresa')
            db_obj.branch_id = obj_in.branch_id
        if obj_in.email and obj_in.email.lower().strip() != db_obj.email:
            existing = UsuarioService.get_by_email(db, obj_in.email)
            if existing:
                raise ConflictoException(detail="El correo electrónico ya está registrado por otro usuario")
            db_obj.email = obj_in.email.lower().strip()

        if obj_in.full_name is not None:
            db_obj.full_name = obj_in.full_name.strip()

        if "phone" in obj_in.model_fields_set:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None

        if obj_in.role is not None:
            db_obj.role = obj_in.role.value if hasattr(obj_in.role, "value") else str(obj_in.role)

        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active

        if obj_in.password:
            db_obj.hashed_password = get_password_hash(obj_in.password)

        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def toggle_status(db: Session, db_obj: Usuario, current_user_id: str) -> Usuario:
        """Activate or deactivate a user account. Cannot self-deactivate."""
        if db.info.get('tenant_context') and db_obj.role == 'CUSTOMER':
            raise SolicitudInvalidaException(detail='La cuenta de cliente es personal y no puede desactivarse desde una empresa')
        if db_obj.id == current_user_id:
            raise SolicitudInvalidaException(detail="No puedes desactivar tu propia cuenta de administrador")

        db_obj.is_active = not db_obj.is_active
        db.add(db_obj)
        commit_or_flush(db)
        db.refresh(db_obj)
        return db_obj
