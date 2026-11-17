# Imagen de PET Alert: el backend FastAPI, que también entrega el frontend.
# Supabase NO va aquí: es un servicio remoto (ver README, sección Docker).
#
# Construir:  docker build -t petalert .
# Ejecutar:   docker compose up   (lee las claves de backend/.env)

FROM python:3.14-slim

# Sin archivos .pyc, registros al instante (se ven en `docker compose logs`)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# 1) Dependencias primero: Docker reutiliza esta capa si solo cambia el código
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# 2) Solo lo que el servidor entrega o ejecuta (misma estructura que en el repositorio)
COPY backend/app backend/app
COPY index.html app.html ./
COPY css css
COPY js js
COPY img img

# 3) No ejecutar como administrador (root) dentro del contenedor
RUN useradd --create-home --uid 10001 petalert
USER petalert

# Cloud Run indica el puerto con la variable PORT; en local se usa 8000
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# --proxy-headers: detrás del proxy https de la nube, la app ve la dirección real (https://...)
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
