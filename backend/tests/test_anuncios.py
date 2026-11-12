"""Leer anuncios de redes con Gemini (D6). Gemini se SIMULA: no se llama a Google ni se gasta cuota.

Lo que se comprueba es nuestra parte: qué se borra antes de enviar, qué se envía y cómo se
valida la respuesta. La conexión real se probó a mano con GEMINI_API_KEY el 2026-11-12.
"""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from app import anuncios, supabase
from app.auth import User, require_user
from app.config import get_settings
from app.main import app
from app.routers import anuncios as anuncios_router


AD = ("SE ENCONTRÓ perrita criolla café con blanco, pequeña, con collar rojo, en el parque de "
      "Chapinero el {fecha}. Info al 300 123 4567 o +57 (310) 765-4321 o al 3157654321, "
      "escribir a ana.perez@gmail.com, @rescate.bog o ver https://facebook.com/groups/123")


def test_redact_borra_contactos_y_conserva_lo_demas():
    clean, removed = anuncios.redact(AD.format(fecha="12/11/2026"))
    assert removed == 6
    for dato in ("300 123", "765-4321", "3157654321", "ana.perez", "@rescate", "facebook.com"):
        assert dato not in clean, dato
    for dato in ("café con blanco", "collar rojo", "Chapinero", "12/11/2026"):
        assert dato in clean, dato


def gemini_reply(payload: dict | str, status: int = 200):
    """Transporte falso que responde como Gemini y guarda la petición recibida."""
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(status, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def run_extract(monkeypatch, payload, status=200, text=None):
    client, seen = gemini_reply(payload, status)
    settings = replace(get_settings(), gemini_api_key="clave-de-prueba", gemini_model="gemini-3.5-flash-lite")
    monkeypatch.setattr(anuncios, "get_settings", lambda: settings)
    monkeypatch.setattr(supabase, "client", lambda: client)
    result = asyncio.run(anuncios.extract(text or AD.format(fecha="ayer")))
    return result, seen


def test_extract_envia_texto_limpio_y_valida_respuesta(monkeypatch):
    hoy = date.today().isoformat()
    (data, removed), seen = run_extract(monkeypatch, {
        "type": "found", "species": "dog", "breed": "criolla", "color": "café con blanco", "size": "small",
        "distinctive_features": "collar rojo", "location_label": "parque de Chapinero", "event_date": hoy})
    assert data.species == "dog" and data.size == "small" and data.location_label == "parque de Chapinero"
    assert data.event_date == date.today() and removed == 6
    # Lo que llegó a "Google": sin teléfonos ni correos, con la clave en la cabecera (no en la URL).
    sent = json.dumps(seen["body"], ensure_ascii=False)
    assert "300 123" not in sent and "ana.perez" not in sent and "[teléfono]" in sent
    assert seen["headers"]["x-goog-api-key"] == "clave-de-prueba" and "clave-de-prueba" not in seen["url"]
    assert "gemini-3.5-flash-lite:generateContent" in seen["url"]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_extract_recorta_y_descarta_fechas_imposibles(monkeypatch):
    futuro = (date.today() + timedelta(days=3)).isoformat()
    (data, _), _ = run_extract(monkeypatch, {
        "type": "lost", "species": "cat", "breed": None, "color": "x" * 300, "size": None,
        "distinctive_features": None, "location_label": "  Suba \n Rincón  ", "event_date": futuro})
    assert len(data.color) == 80 and data.location_label == "Suba Rincón" and data.event_date is None


@pytest.mark.parametrize("payload", [
    {"type": "found", "species": "elefante"},   # valor no permitido
    "esto no es JSON",
])
def test_extract_rechaza_respuestas_raras(monkeypatch, payload):
    with pytest.raises(HTTPException) as exc:
        run_extract(monkeypatch, payload)
    assert exc.value.status_code == 502


def test_extract_limite_gratuito(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        run_extract(monkeypatch, {}, status=429)
    assert exc.value.status_code == 429


def run_sequence(monkeypatch, statuses):
    """Gemini responde con estos códigos, uno por intento. Devuelve (resultado o excepción, nº de llamadas)."""
    calls = []
    ok = json.dumps({"type": "found", "species": "cat"})

    def handler(request):
        calls.append(1)
        return httpx.Response(statuses[len(calls) - 1], json={"candidates": [{"content": {"parts": [{"text": ok}]}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(anuncios, "get_settings", lambda: replace(get_settings(), gemini_api_key="clave-de-prueba"))
    monkeypatch.setattr(supabase, "client", lambda: client)
    monkeypatch.setattr(anuncios, "RETRY_DELAYS", (0, 0))  # sin pausas en la prueba
    try:
        return asyncio.run(anuncios.extract("Se encontró un gato gris en Suba")), len(calls)
    except HTTPException as exc:
        return exc, len(calls)


def test_extract_reintenta_si_google_esta_ocupado(monkeypatch):
    # El 503 "high demand" real de Google (visto el 2026-11-12): al tercer intento responde.
    (data, _), calls = run_sequence(monkeypatch, [503, 500, 200])
    assert data.species == "cat" and calls == 3


def test_extract_se_rinde_con_mensaje_claro(monkeypatch):
    exc, calls = run_sequence(monkeypatch, [503, 503, 503])
    assert exc.status_code == 503 and "ocupada" in exc.detail and calls == 3
    exc, calls = run_sequence(monkeypatch, [429])  # la cuota agotada no se reintenta
    assert exc.status_code == 429 and calls == 1


# ---------------------------------------------------------------------------
# Ruta de la API (con la sesión simulada: no se crea ningún usuario)
# ---------------------------------------------------------------------------
@pytest.fixture
def api():
    app.dependency_overrides[require_user] = lambda: User(id="usuario-prueba", email=None, token="x")
    anuncios_router._recent.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_ruta_sin_clave_responde_503(api, monkeypatch):
    monkeypatch.setattr(anuncios, "get_settings", lambda: replace(get_settings(), gemini_api_key=""))
    r = api.post("/api/ads/extract", json={"text": "Se encontró un perro café en Suba ayer"})
    assert r.status_code == 503
    assert isinstance(api.get("/api/config").json()["features"]["read_ad"], bool)


def test_ruta_valida_texto_y_limita_usos(api, monkeypatch):
    async def fake_extract(text):
        return anuncios.AdData(type="found", species="dog"), 0
    monkeypatch.setattr(anuncios, "extract", fake_extract)
    assert api.post("/api/ads/extract", json={"text": "corto"}).status_code == 422
    assert api.post("/api/ads/extract", json={"text": "x" * 3001}).status_code == 422
    body = {"text": "Se encontró un perro café en Suba ayer"}
    for _ in range(anuncios_router.MAX_PER_HOUR):
        assert api.post("/api/ads/extract", json=body).json()["species"] == "dog"
    assert api.post("/api/ads/extract", json=body).status_code == 429
