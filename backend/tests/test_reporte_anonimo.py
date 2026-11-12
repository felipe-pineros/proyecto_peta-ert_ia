"""Reporte rápido SIN cuenta (usuario anónimo de Supabase) · migración 4.

Requiere:
- La migración 20261112000004_reporte_rapido_anonimo.sql aplicada.
- Supabase → Authentication → Sign In / Providers → "Allow anonymous sign-ins" activado.
Si el modo invitado está desactivado, las pruebas se marcan como OMITIDAS (no como pasadas).

Crea un usuario normal (Carla) y un invitado; al final borra sus fotos y sus cuentas.
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
import uuid

from dotenv import load_dotenv
from fastapi.testclient import TestClient
import httpx
from PIL import Image
import pytest

from app.config import BACKEND_DIR, PHOTO_BUCKET
from app.main import app


load_dotenv(BACKEND_DIR / ".env")
URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
PUBLISHABLE = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SECRET = os.getenv("SUPABASE_SECRET_KEY", "").strip()
PHONE = "+57 300 123 4567"


def admin_headers() -> dict[str, str]:
    headers = {"apikey": SECRET}
    if SECRET.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SECRET}"
    return headers


def ok(response, expected: int = 200):
    assert response.status_code == expected, f"{response.status_code}: {response.text}"
    return response.json() if response.content else None


def png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (90, 60, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def now_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


def quick_body(**extra) -> dict:
    """Lo mismo que envía el formulario rápido de index.html (sin color ni tamaño)."""
    return {"type": "found", "species": "dog", "event_at": now_iso(),
            "lat": 4.601234, "lng": -74.071234} | extra


# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin():
    if not (URL and PUBLISHABLE and SECRET):
        pytest.fail("Faltan claves en backend/.env")
    with httpx.Client(timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def people(admin):
    created: list[str] = []

    # Invitado: así lo crea supabase-js con signInAnonymously().
    r = admin.post(f"{URL}/auth/v1/signup", headers={"apikey": PUBLISHABLE}, json={})
    if r.status_code != 200 and "anonymous" in r.text.lower():
        pytest.skip("El modo invitado está desactivado: activa 'Allow anonymous sign-ins' en Supabase")
    assert r.status_code == 200, r.text
    anon = r.json()
    assert anon["user"]["is_anonymous"] is True
    created.append(anon["user"]["id"])
    guest = {"id": anon["user"]["id"], "token": anon["access_token"],
             "h": {"Authorization": f"Bearer {anon['access_token']}"}}

    email = f"prueba-anon-carla-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex + "Aa1!"
    r = admin.post(f"{URL}/auth/v1/admin/users", headers=admin_headers(), json={
        "email": email, "password": password, "email_confirm": True,
        "user_metadata": {"display_name": "Prueba Carla"}})
    assert r.status_code in (200, 201), r.text
    created.append(r.json()["id"])
    r = admin.post(f"{URL}/auth/v1/token?grant_type=password",
                   headers={"apikey": PUBLISHABLE}, json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    carla = {"id": created[-1], "token": r.json()["access_token"],
             "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}

    yield {"guest": guest, "carla": carla}

    r = admin.get(f"{URL}/rest/v1/report_photos", headers=admin_headers(),
                  params={"select": "storage_path", "user_id": f"in.({','.join(created)})"})
    paths = [p["storage_path"] for p in r.json()] if r.is_success else []
    if paths:
        admin.request("DELETE", f"{URL}/storage/v1/object/{PHOTO_BUCKET}",
                      headers=admin_headers(), json={"prefixes": paths})
    for user_id in created:
        admin.delete(f"{URL}/auth/v1/admin/users/{user_id}", headers=admin_headers())


def rest(admin, person, method, table, **kwargs):
    """Llamada DIRECTA a la base (como si alguien saltara nuestra API) con el token de la persona."""
    headers = {"apikey": PUBLISHABLE, "Authorization": f"Bearer {person['token']}",
               "Prefer": "return=representation"}
    return admin.request(method, f"{URL}/rest/v1/{table}", headers=headers, **kwargs)


def publish_found(api, person, **extra) -> dict:
    report = ok(api.post("/api/reports", headers=person["h"], json=quick_body(**extra)), 201)
    ok(api.post(f"/api/reports/{report['id']}/photos", headers=person["h"],
                files={"file": ("foto.png", png(), "image/png")}), 201)
    return ok(api.post(f"/api/reports/{report['id']}/publish", headers=person["h"]))


# ---------------------------------------------------------------------------
def test_invitado_publica_reporte_rapido(api, people):
    guest = people["guest"]
    published = publish_found(api, guest, contact_phone=PHONE)
    assert published["status"] == "active" and published["is_mine"]
    assert published["color"] is None and published["size"] is None
    assert published["private"]["contact_phone"] == PHONE
    assert float(published["approx_lat"]) == 4.60  # pública redondeada (~1 km)


def test_invitado_necesita_contacto(api, people):
    guest = people["guest"]
    r = api.post("/api/reports", headers=guest["h"], json=quick_body())
    assert r.status_code == 422 and "contact" in r.json()["detail"]
    # Aunque borre el contacto después, la base no le deja publicar (migración 4).
    report = ok(api.post("/api/reports", headers=guest["h"], json=quick_body(contact_email="a@example.com")), 201)
    ok(api.patch(f"/api/reports/{report['id']}", headers=guest["h"], json={"contact_email": None}))
    ok(api.post(f"/api/reports/{report['id']}/photos", headers=guest["h"],
                files={"file": ("foto.png", png(), "image/png")}), 201)
    r = api.post(f"/api/reports/{report['id']}/publish", headers=guest["h"])
    assert r.status_code == 409 and "contactarte" in r.json()["detail"]


def test_invitado_no_reporta_perdidas_ni_registra_mascotas(api, admin, people):
    guest = people["guest"]
    assert api.post("/api/pets", headers=guest["h"], json={
        "species": "dog", "color": "café", "size": "small"}).status_code == 403
    lost = quick_body(type="lost", pet_id=str(uuid.uuid4()), color="café", size="small", contact_phone=PHONE)
    assert api.post("/api/reports", headers=guest["h"], json=lost).status_code == 403
    # Saltando la API, directo contra la base: RLS también lo bloquea.
    r = rest(admin, guest, "POST", "pets", json={"species": "dog", "color": "café", "size": "small"})
    assert r.status_code in (401, 403), r.text


def test_invitado_no_ve_reportes_ajenos(api, admin, people):
    guest, carla = people["guest"], people["carla"]
    carla_found = publish_found(api, carla, color="negro", size="large", contact_phone=PHONE)

    assert api.get("/api/reports", headers=guest["h"]).status_code == 403
    assert api.get(f"/api/reports/{carla_found['id']}", headers=guest["h"]).status_code == 404
    photo_id = carla_found["photos"][0]["id"]
    assert api.get(f"/api/photos/{photo_id}/url", headers=guest["h"]).status_code == 404
    # Directo contra la base: solo devuelve los reportes del propio invitado.
    rows = rest(admin, guest, "GET", "reports", params={"select": "id,user_id", "status": "eq.active"}).json()
    assert rows and all(r["user_id"] == guest["id"] for r in rows)


def test_usuario_con_cuenta_ve_reporte_del_invitado_y_confirma(api, admin, people):
    guest, carla = people["guest"], people["carla"]
    found = publish_found(api, guest, contact_phone=PHONE)

    feed = ok(api.get("/api/reports", headers=carla["h"], params={"type": "found"}))
    assert found["id"] in {r["id"] for r in feed}
    seen = ok(api.get(f"/api/reports/{found['id']}", headers=carla["h"]))
    assert "private" not in seen and seen["color"] is None

    # Carla perdió un perro; el motor (etapa 7) aún no existe, así que la coincidencia se inserta a mano.
    pet = ok(api.post("/api/pets", headers=carla["h"], json={"species": "dog", "color": "café", "size": "small"}), 201)
    lost = ok(api.post("/api/reports", headers=carla["h"], json=quick_body(
        type="lost", pet_id=pet["id"], color="café", size="small")), 201)
    ok(api.post(f"/api/reports/{lost['id']}/photos", headers=carla["h"],
                files={"file": ("foto.png", png(), "image/png")}), 201)
    ok(api.post(f"/api/reports/{lost['id']}/publish", headers=carla["h"]))
    r = admin.post(f"{URL}/rest/v1/matches", headers=admin_headers() | {"Prefer": "return=representation"},
                   json={"lost_report_id": lost["id"], "found_report_id": found["id"], "model_name": "prueba",
                         "visual_score": 0.9, "distance_km": 0.4, "total_score": 0.88})
    assert r.is_success, r.text
    match_id = r.json()[0]["id"]

    # El invitado no puede confirmar (D2); Carla sí, y recibe su teléfono para llamarle.
    assert api.post(f"/api/matches/{match_id}/confirm", headers=guest["h"]).status_code == 403
    confirmed = ok(api.post(f"/api/matches/{match_id}/confirm", headers=carla["h"]))
    assert confirmed["status"] == "confirmed"
    assert confirmed["contact"]["phone"] == PHONE
