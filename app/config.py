from typing import List
import json
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Project Info
    PROJECT_NAME: str = "Auth API"
    SEED_USERS: str = ""
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/probando_1_db"
    TEST_DATABASE_URL: str = "sqlite:///./test.db"

    # Security & JWT
    SECRET_KEY: str = "supersecretkeydefault32charactersminimumlengthforsecurity"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Password Reset
    RESET_TOKEN_EXPIRE_MINUTES: int = 7

    # Gemini reports
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_FALLBACK_MODEL: str = "gemini-flash-latest"

    # SMTP (Gmail)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "FashionStore"

    # PayPal Sandbox
    PAYPAL_CLIENT_ID: str = "BAAgAP2YtTQ2bAYxpfmeNidhSjKcagiXNSy-Y9MO8CCzCi7_uIH4AGjOTUWYzcC_b-R49TE3xgGtE4ZfnM"
    PAYPAL_CLIENT_SECRET: str = "EMXqvch3aLQqllX03PFwnasRL_FfFabn5JLTbr7PUj3KlLLM7dohH9Fyzya55wFlNPE9e5Whr8K7DPyE"
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_CURRENCY: str = "USD"
    FRONTEND_URL: str = "http://localhost:4200"

    # CORS — stored as plain str so pydantic-settings never calls json.loads() on it.
    # Railway: set CORS_ORIGINS=https://your-app.com,https://other.com  (comma-separated)
    # OR leave unset to use the default localhost origins.
    CORS_ORIGINS: str = (
        "http://localhost:4200,"
        "http://127.0.0.1:4200,"
        "http://localhost:3000,"
        "http://localhost:8080,"
        "http://localhost:8000"
    )

    @computed_field
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS env var: accepts comma-separated or JSON array."""
        v = self.CORS_ORIGINS.strip()
        if not v:
            return []
        if v.startswith("["):
            try:
                result = json.loads(v)
                if isinstance(result, list):
                    return [str(i).strip() for i in result if str(i).strip()]
            except json.JSONDecodeError:
                pass
        return [i.strip() for i in v.split(",") if i.strip()]


settings = Settings()

