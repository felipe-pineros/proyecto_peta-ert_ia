#!/bin/sh
# Prueba las migraciones en un PostgreSQL TEMPORAL (Docker), sin tocar el Supabase real.
# Uso (Git Bash o Linux, con Docker encendido):  sh supabase/pruebas_locales/probar.sh
set -e
export MSYS_NO_PATHCONV=1  # Git Bash en Windows: no convertir /sql en una ruta de Windows
cd "$(dirname "$0")/.."
docker rm -f petalert-pgprueba >/dev/null 2>&1 || true
docker run -d --name petalert-pgprueba -e POSTGRES_PASSWORD=prueba pgvector/pgvector:pg15 >/dev/null
trap 'docker rm -f petalert-pgprueba >/dev/null 2>&1' EXIT
until docker exec petalert-pgprueba pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
sleep 2
docker exec petalert-pgprueba mkdir -p /sql
for f in pruebas_locales/00_supabase_simulado.sql migrations/*.sql pruebas_locales/99_escenarios.sql; do
  docker cp "$f" petalert-pgprueba:/sql/ >/dev/null
  echo "== $(basename "$f")"
  docker exec petalert-pgprueba psql -q -v ON_ERROR_STOP=1 -U postgres -f "/sql/$(basename "$f")" 2>&1 \
    | grep -E "OK|FALL|ERROR|Error|Debió|===" | sed 's/^psql:[^:]*:[0-9]*: //'
done
