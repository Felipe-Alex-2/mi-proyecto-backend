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
