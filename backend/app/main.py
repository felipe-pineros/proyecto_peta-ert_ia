"""Punto de entrada del backend de PET Alert.

Ejecutar (desde la raíz del proyecto, en PowerShell):
    .\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir backend --reload
Luego abrir http://localhost:8000 (frontend) o http://localhost:8000/docs (API).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import supabase
from .config import ROOT_DIR, get_settings
from .routers import coincidencias, fotos, mascotas, notificaciones, perfil, reportes


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
    return {"supabase_url": s.supabase_url, "supabase_publishable_key": s.publishable_key}


for module in (perfil, mascotas, reportes, fotos, coincidencias, notificaciones):
    app.include_router(module.router)


# Frontend: SOLO las dos páginas y las carpetas img/, css/ y js/.
# Nunca se monta la raíz del proyecto (expondría backend/.env y el código).
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT_DIR / "index.html")


@app.get("/app.html", include_in_schema=False)
async def app_page():
    return FileResponse(ROOT_DIR / "app.html")


for folder in ("img", "css", "js"):
    app.mount(f"/{folder}", StaticFiles(directory=ROOT_DIR / folder), name=folder)
