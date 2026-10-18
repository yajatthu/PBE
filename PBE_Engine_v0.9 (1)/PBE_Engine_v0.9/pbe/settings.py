from pydantic import BaseModel
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Deployments may inject environment variables directly.
    pass

class Settings(BaseModel):
    APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()
    PBE_APP_URL: str = os.getenv("PBE_APP_URL", "http://localhost:8000")
    PBE_ALLOWED_ORIGINS: str = os.getenv("PBE_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://pbe:pbe_dev@localhost:5433/pbe")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "pbe")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "pbe-api")
    JWT_EXPIRES_MINUTES: int = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))
    COMPOSIO_API_KEY: str = os.getenv("COMPOSIO_API_KEY", "")
    COMPOSIO_AUTH_CONFIGS: str = os.getenv("COMPOSIO_AUTH_CONFIGS", "{}")
    COMPOSIO_API_BASE: str = os.getenv("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3.1").rstrip("/")
    COMPOSIO_WEBHOOK_SECRET: str = os.getenv("COMPOSIO_WEBHOOK_SECRET", "")
    COMPOSIO_WEBHOOK_URL: str = os.getenv("COMPOSIO_WEBHOOK_URL", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    OPENROUTER_PRIMARY_MODEL: str = os.getenv("OPENROUTER_PRIMARY_MODEL", "google/gemini-2.5-flash")
    OPENROUTER_FALLBACK_MODELS: str = os.getenv("OPENROUTER_FALLBACK_MODELS", "")
    OPENROUTER_TIMEOUT_SECONDS: int = int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45"))
    PBE_SANDBOX_ENABLED: bool = os.getenv("PBE_SANDBOX_ENABLED", "false").lower() == "true"
    PBE_SANDBOX_IMAGE: str = os.getenv("PBE_SANDBOX_IMAGE", "python:3.14-slim")
    PBE_SANDBOX_TIMEOUT_SECONDS: int = int(os.getenv("PBE_SANDBOX_TIMEOUT_SECONDS", "15"))
    PBE_MAX_GENERATED_SOURCE_BYTES: int = int(os.getenv("PBE_MAX_GENERATED_SOURCE_BYTES", "200000"))
    PBE_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("PBE_RATE_LIMIT_PER_MINUTE", "120"))
    PBE_AUTH_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("PBE_AUTH_RATE_LIMIT_PER_MINUTE", "10"))
    PBE_AUTO_INIT_SCHEMA: bool = os.getenv("PBE_AUTO_INIT_SCHEMA", "false").lower() == "true"
    PBE_WEBHOOK_MAX_AGE_SECONDS: int = int(os.getenv("PBE_WEBHOOK_MAX_AGE_SECONDS", "300"))

settings = Settings()
