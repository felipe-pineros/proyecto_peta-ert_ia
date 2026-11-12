"""Punto de entrada del backend de PET Alert.

Ejecutar (desde la raíz del proyecto, en PowerShell):
    .\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir backend --reload
Luego abrir http://localhost:8000 (frontend) o http://localhost:8000/docs (API).
"""
from contextlib import asynccontextmanager
from html import escape as html_escape
from xml.sax.saxutils import escape as xml_escape

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import supabase
from .config import ROOT_DIR, get_settings
from .routers import anuncios, coincidencias, fotos, mascotas, notificaciones, perfil, reportes


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings()  # si faltan claves, falla al arrancar y no a mitad de una petición
    await supabase.start()
    yield
    await supabase.stop()


app = FastAPI(title="PET Alert API", version="0.4.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.get("/api/health", tags=["sistema"])
async def health():
    return {"status": "ok"}


@app.get("/api/config", tags=["sistema"])
async def public_config():
    """Datos PÚBLICOS que necesita supabase-js en el navegador (nunca la secret key)."""
    s = get_settings()
    return {"supabase_url": s.supabase_url, "supabase_publishable_key": s.publishable_key,
            "features": {"read_ad": bool(s.gemini_api_key)}}


for module in (perfil, mascotas, reportes, fotos, coincidencias, notificaciones, anuncios):
    app.include_router(module.router)


# ---------------------------------------------------------------------------
# Buscadores (SEO) y vistas previas al compartir el enlace.
# Google, WhatsApp y Facebook exigen direcciones COMPLETAS (https://...), así que
# index.html lleva el marcador __SITE_URL__ y aquí se reemplaza por la dirección real.
# ---------------------------------------------------------------------------
def site_url(request: Request) -> str:
    return get_settings().public_site_url or str(request.base_url).rstrip("/")


@app.get("/robots.txt", include_in_schema=False)
async def robots(request: Request):
    # Solo la página principal es pública; la app y la API requieren sesión (D1).
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nDisallow: /app.html\nDisallow: /api/\n"
        f"\nSitemap: {site_url(request)}/sitemap.xml\n")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap(request: Request):
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{xml_escape(site_url(request))}/</loc></url>\n"
        "</urlset>\n", media_type="application/xml")


# Frontend: SOLO las dos páginas y las carpetas img/, css/ y js/.
# Nunca se monta la raíz del proyecto (expondría backend/.env y el código).
@app.get("/", include_in_schema=False)
async def index(request: Request):
    html = (ROOT_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__SITE_URL__", html_escape(site_url(request))))


@app.get("/app.html", include_in_schema=False)
async def app_page():
    return FileResponse(ROOT_DIR / "app.html")


for folder in ("img", "css", "js"):
    app.mount(f"/{folder}", StaticFiles(directory=ROOT_DIR / folder), name=folder)
