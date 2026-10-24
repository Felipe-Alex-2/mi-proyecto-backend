"""Crea un usuario admin por defecto para desarrollo/pruebas."""

from app.nucleo.seguridad import get_password_hash
from app.base_datos import SessionLocal
from app.modelos import Usuario

def seed_admin():
    from app.nucleo.esquema_saas import ensure_saas_schema
    from app.base_datos import engine, Base
    Base.metadata.create_all(engine)
    ensure_saas_schema(engine)
    db = SessionLocal()
    try:
        existing = db.query(Usuario).filter(Usuario.email == "admin@local.dev").first()
        if existing:
            print("El usuario admin ya existe.")
            return

        admin = Usuario(
            email="admin@local.dev",
            hashed_password=get_password_hash("Admin1234!"),
            full_name="Admin Local",
            role="ADMIN",
            is_saas_admin=True,
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