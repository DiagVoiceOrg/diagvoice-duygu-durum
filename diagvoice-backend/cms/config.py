from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Tek kaynak: depo kökündeki .env (docker-compose env_file ile aynı dosya).
# Konteynerde kök dosya yoksa (yalnızca compose ortam değişkenleri) ikinci olarak /app/.env dener.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent
_ENV_CANDIDATES = [
    _REPO_ROOT / ".env",
    _BACKEND_ROOT / ".env",
]
_ENV_FILE = next((p for p in _ENV_CANDIDATES if p.is_file()), None)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE is not None else None,
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
