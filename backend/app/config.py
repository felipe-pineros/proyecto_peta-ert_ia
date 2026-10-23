from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / "backend" / ".env")


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    service_role_key: str
    signed_url_ttl_seconds: int


def get_settings() -> Settings:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not anon_key or not service_key:
        raise RuntimeError("SUPABASE_URL, SUPABASE_ANON_KEY y SUPABASE_SERVICE_ROLE_KEY son obligatorias")
    try:
        ttl = int(os.getenv("PHOTO_SIGNED_URL_TTL_SECONDS", "300"))
    except ValueError as exc:
        raise RuntimeError("PHOTO_SIGNED_URL_TTL_SECONDS debe ser un entero") from exc
    if not 30 <= ttl <= 900:
        raise RuntimeError("PHOTO_SIGNED_URL_TTL_SECONDS debe estar entre 30 y 900")
    return Settings(url, anon_key, service_key, ttl)
