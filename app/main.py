from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from app.config import settings
from app.api.v1.router import api_v1_router
from app.middleware.error_handler import (
    validation_exception_handler,
    general_exception_handler,
)
from app.database import engine, Base
import app.models  # Ensure all models are registered with Base


import logging

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables are created if not running with migrations or in tests
    try:
        Base.metadata.create_all(bind=engine)
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'ADMIN' NOT NULL;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(50);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS branch_id VARCHAR(36) REFERENCES branches(id);"))
            try:
                conn.execute(text("ALTER TABLE products ALTER COLUMN image_url TYPE TEXT;"))
            except Exception:
                pass
            
            # Auto-migrate reservations payment fields
            for col_sql in [
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50) DEFAULT 'EFECTIVO';",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'PENDING';",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS paypal_order_id VARCHAR(100);",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS paypal_capture_id VARCHAR(100);",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS total_amount NUMERIC(10, 2);",
                "ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50);",
                "ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'PENDING';",
                "ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS amount NUMERIC(10, 2);",
                "ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS paypal_order_id VARCHAR(100);",
                "ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS paypal_capture_id VARCHAR(100);",
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id VARCHAR(36) PRIMARY KEY,
                    payment_code VARCHAR(30) UNIQUE NOT NULL,
                    branch_id VARCHAR(36) NOT NULL REFERENCES branches(id),
                    reservation_id VARCHAR(36) REFERENCES reservations(id),
                    customer_id VARCHAR(36) REFERENCES users(id),
                    customer_name VARCHAR(150) NOT NULL,
                    customer_email VARCHAR(150),
                    concept VARCHAR(255) NOT NULL,
                    amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                    currency VARCHAR(10) NOT NULL DEFAULT 'EUR',
                    payment_type VARCHAR(20) NOT NULL DEFAULT 'EFECTIVO',
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    reference VARCHAR(100),
                    paypal_order_id VARCHAR(100),
                    paypal_capture_id VARCHAR(100),
                    cashier_id VARCHAR(36) REFERENCES users(id),
                    items_detail TEXT,
                    notes TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    paid_at TIMESTAMP WITH TIME ZONE
                );
                """,
                "ALTER TABLE payments ADD COLUMN IF NOT EXISTS items_detail TEXT;",
                "CREATE INDEX IF NOT EXISTS ix_payments_branch_id ON payments (branch_id);",
                "CREATE INDEX IF NOT EXISTS ix_payments_reservation_id ON payments (reservation_id);",
                "CREATE INDEX IF NOT EXISTS ix_payments_payment_code ON payments (payment_code);",
            ]:
                try:
                    conn.execute(text(col_sql))
                except Exception:
                    pass
            conn.commit()
    except Exception as exc:
        logger.warning(f"Note: Database table auto-creation skipped or deferred: {exc}")
    yield



app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Full-Stack Authentication REST API with FastAPI, PostgreSQL, JWT & bcrypt.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS Middleware Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
# Only catch unhandled exceptions in production or non-debug
if settings.ENVIRONMENT != "development_debug":
    app.add_exception_handler(Exception, general_exception_handler)

# Include API Router
app.include_router(api_v1_router, prefix="/api")


@app.get("/", tags=["Health"])
def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    db_status = "ok"
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {"status": "healthy" if db_status == "ok" else "degraded", "database": db_status}
