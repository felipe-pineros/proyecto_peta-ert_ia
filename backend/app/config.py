"""Configuración leída de backend/.env (o de variables de entorno en Docker/nube).

Las claves nunca se escriben en el código: si faltan, el servidor no arranca.
"""
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

PHOTO_BUCKET = "report-photos"
MAX_PHOTOS_PER_REPORT = 5  # decisión D4 (la base de datos también lo impone)


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    publishable_key: str
    secret_key: str
    signed_url_ttl_seconds: int
    # Dirección pública del sitio (p. ej. https://petalert.co) para buscadores y vistas previas.
    # Vacía = se usa la dirección desde la que se abrió la página (útil en localhost).
    public_site_url: str = ""
    # Opcional: Gemini para "leer un anuncio de redes" (plan gratuito, solo texto, sin datos personales).
    # Vacía = la función no aparece.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"


@lru_cache
def get_settings() -> Settings:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    publishable = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not (url and publishable and secret):
        raise RuntimeError(
            "Faltan SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY o SUPABASE_SECRET_KEY en backend/.env"
        )
    try:
        ttl = int(os.getenv("PHOTO_SIGNED_URL_TTL_SECONDS", "300"))
    except ValueError as exc:
        raise RuntimeError("PHOTO_SIGNED_URL_TTL_SECONDS debe ser un número entero") from exc
    if not 30 <= ttl <= 900:
        raise RuntimeError("PHOTO_SIGNED_URL_TTL_SECONDS debe estar entre 30 y 900 segundos")
    site = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if site and not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?", site):
        raise RuntimeError("PUBLIC_SITE_URL debe ser solo la dirección, p. ej. https://petalert.co")
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
    if not re.fullmatch(r"[a-z0-9.\-]{3,60}", gemini_model):
        raise RuntimeError("GEMINI_MODEL no es un nombre de modelo válido")
    return Settings(url, publishable, secret, ttl, site, gemini_key, gemini_model)
