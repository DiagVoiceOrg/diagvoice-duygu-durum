from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Çalışma dizininden bağımsız: /app/.env (Docker) veya backend kökü
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "diagvoice_cms"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    cms_admin_email: str = "admin@localhost"
    cms_admin_password: str = "admin123"


settings = Settings()
