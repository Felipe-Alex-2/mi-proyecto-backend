"""Create or update initial users from the SEED_USERS environment variable."""

import json
import sys
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import get_password_hash
from app.database import Base, SessionLocal, engine
from app.models import User, UserRole
import app.models  # noqa: F401  # Register all models before create_all.


def _load_users() -> list[dict[str, Any]]:
    raw_users = settings.SEED_USERS.strip()
    if not raw_users:
        raise ValueError("SEED_USERS no está definido en el entorno")

    try:
        users = json.loads(raw_users)
    except json.JSONDecodeError as exc:
        raise ValueError("SEED_USERS debe ser un JSON válido") from exc

    if not isinstance(users, list) or not users:
        raise ValueError("SEED_USERS debe ser una lista JSON con al menos un usuario")
    if not all(isinstance(user, dict) for user in users):
        raise ValueError("Cada usuario de SEED_USERS debe ser un objeto JSON")
    return users


def seed_users(db: Session, users: list[dict[str, Any]]) -> None:
    valid_roles = {role.value for role in UserRole}

    for data in users:
        email = str(data.get("email", "")).lower().strip()
        password = str(data.get("password", ""))
        full_name = str(data.get("full_name", "")).strip()
        role = str(data.get("role", "")).upper().strip()

        if not email or not password or not full_name or role not in valid_roles:
            raise ValueError(
                "Cada usuario requiere email, password, full_name y un role válido: "
                + ", ".join(sorted(valid_roles))
            )
        if len(password) < 8:
            raise ValueError(f"La contraseña de {email} debe tener al menos 8 caracteres")

        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, is_active=True, is_verified=True)
            db.add(user)
            action = "creado"
        else:
            action = "actualizado"

        user.full_name = full_name
        user.role = role
        user.hashed_password = get_password_hash(password)
        user.is_active = True
        user.is_verified = True
        print(f"Usuario {action}: {email} ({role})")

    db.commit()


def main() -> int:
    try:
        users = _load_users()
        # Base.metadata.create_all(bind=engine)esto creo que se puede elimianr
        with SessionLocal() as db:
            seed_users(db, users)
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"Error en el seeder: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())