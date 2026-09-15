"""Crea un usuario admin por defecto para desarrollo/pruebas."""

from app.core.security import get_password_hash
from app.database import SessionLocal
from app.models import User

def seed_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "admin@local.dev").first()
        if existing:
            print("El usuario admin ya existe.")
            return

        admin = User(
            email="admin@local.dev",
            hashed_password=get_password_hash("Admin1234!"),
            full_name="Admin Local",
            role="ADMIN",
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        db.commit()
        print("Usuario admin creado exitosamente.")
    finally:
        db.close()

if __name__ == "__main__":
    seed_admin()