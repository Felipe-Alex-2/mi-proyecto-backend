import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import os
import sys

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

# Never run startup migrations or contact the configured application database
# while collecting/running tests. Each test owns an isolated in-memory database.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BACKUPS_ENABLED"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "false"
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["PAYPAL_CLIENT_ID"] = ""
os.environ["PAYPAL_CLIENT_SECRET"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["VTON_URL"] = ""

from app.base_datos import Base, get_db
from app.main import app
from app.modelos import Usuario, ListaTokensRevocados, TokenRestablecimientoContrasena, Sucursal

# Test SQLite database
SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Creates a fresh database session for a test, clearing tables after test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI TestClient with overridden get_db dependency."""
    def override_get_db():
        try:
            yield db_session
        except Exception:
            # Mirror the rollback performed when production closes its request
            # session, while retaining this test's shared in-memory connection.
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_token(db_session) -> str:
    """Returns a valid access token for an ADMIN user."""
    from app.nucleo.seguridad import get_password_hash, create_access_token
    user = Usuario(
        email="admin_fixture@example.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="Admin Fixture",
        role="ADMIN",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return create_access_token(
        subject=user.id,
        claims={"role": user.role, "email": user.email},
    )
