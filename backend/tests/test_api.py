"""Pruebas de la API (etapa 4), de extremo a extremo contra el Supabase de backend/.env.

Crean dos usuarios temporales (Ana y Beto), usan la API como lo hará el frontend y al
final borran sus fotos de Storage y sus cuentas (el borrado en cascada limpia sus datos).

Las coincidencias se insertan a mano con la secret key porque el motor que las
calcula es de la etapa 7.
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
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


def admin_headers() -> dict[str, str]:
    headers = {"apikey": SECRET}
    if SECRET.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SECRET}"
    return headers


def ok(response, expected: int = 200):
    assert response.status_code == expected, f"{response.status_code}: {response.text}"
    return response.json() if response.content else None


def jpeg_like_png(color=(200, 120, 40)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
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
def users(admin):
    created: list[str] = []

    def create(name: str) -> dict:
        email = f"prueba-api-{name}-{uuid.uuid4().hex[:8]}@example.com"
        password = uuid.uuid4().hex + "Aa1!"
        r = admin.post(f"{URL}/auth/v1/admin/users", headers=admin_headers(), json={
            "email": email, "password": password, "email_confirm": True,
            "user_metadata": {"display_name": f"Prueba {name}"}})
        assert r.status_code in (200, 201), r.text
        created.append(r.json()["id"])
        r = admin.post(f"{URL}/auth/v1/token?grant_type=password",
                       headers={"apikey": PUBLISHABLE}, json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"id": created[-1], "email": email,
                "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}

    yield {"ana": create("ana"), "beto": create("beto")}

    # Limpieza: primero los archivos de Storage (no se borran en cascada), luego las cuentas.
    if created:
        r = admin.get(f"{URL}/rest/v1/report_photos", headers=admin_headers(),
                      params={"select": "storage_path", "user_id": f"in.({','.join(created)})"})
        paths = [p["storage_path"] for p in r.json()] if r.is_success else []
        if paths:
            admin.request("DELETE", f"{URL}/storage/v1/object/{PHOTO_BUCKET}",
                          headers=admin_headers(), json={"prefixes": paths})
    for user_id in created:
        admin.delete(f"{URL}/auth/v1/admin/users/{user_id}", headers=admin_headers())


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def now_iso(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def create_pet(api, user, species="dog") -> str:
    return ok(api.post("/api/pets", headers=user["h"], json={
        "name": "Toby", "species": species, "color": "café", "size": "medium"}), 201)["id"]


def create_report(api, user, type_, species="dog", lat=4.648312, lng=-74.062711, **extra) -> dict:
    body = {"type": type_, "species": species, "color": "café", "size": "medium",
            "event_at": now_iso(hours=2), "location_label": "Parque de prueba",
            "lat": lat, "lng": lng, "contact_phone": "+57 300 000 0000"} | extra
    if type_ == "lost" and "pet_id" not in extra:
        body["pet_id"] = create_pet(api, user, species)
    return ok(api.post("/api/reports", headers=user["h"], json=body), 201)


def upload(api, user, report_id, data=None, name="foto.png", ctype="image/png"):
    return api.post(f"/api/reports/{report_id}/photos", headers=user["h"],
                    files={"file": (name, data or jpeg_like_png(), ctype)})


def active_report(api, user, type_, **extra) -> dict:
    report = create_report(api, user, type_, **extra)
    ok(upload(api, user, report["id"]), 201)
    return ok(api.post(f"/api/reports/{report['id']}/publish", headers=user["h"]))


def insert_match(admin, lost_id, found_id) -> str:
    r = admin.post(f"{URL}/rest/v1/matches", headers=admin_headers() | {"Prefer": "return=representation"},
                   json={"lost_report_id": lost_id, "found_report_id": found_id, "model_name": "prueba",
                         "visual_score": 0.9, "distance_km": 1.2, "total_score": 0.85})
    assert r.is_success, r.text
    return r.json()[0]["id"]


# ---------------------------------------------------------------------------
# Pruebas
# ---------------------------------------------------------------------------
def test_salud_y_frontend_sin_exponer_archivos(api):
    assert ok(api.get("/api/health")) == {"status": "ok"}
    home = api.get("/")
    assert home.status_code == 200 and "text/html" in home.headers["content-type"]
    assert api.get("/img/logo.png").status_code == 200
    for archivo in ("/app.html", "/css/estilos.css", "/css/app.css", "/css/reporte-rapido.css",
                    "/js/app.js", "/js/sesion.js", "/js/mapa.js", "/js/reporte-rapido.js"):
        assert api.get(archivo).status_code == 200, archivo
    for secreto in ("/backend/.env", "/.env", "/backend/app/config.py", "/img/../backend/.env",
                    "/js/../backend/.env", "/PROGRESO.md", "/supabase/migrations"):
        assert api.get(secreto).status_code == 404, secreto
    # La configuración pública lleva la publishable key y NUNCA la secret key.
    config = ok(api.get("/api/config"))
    assert config["supabase_publishable_key"] == PUBLISHABLE
    assert SECRET not in json.dumps(config)


def test_buscadores_y_vista_previa(api):
    # Sin PUBLIC_SITE_URL se usa la dirección de la petición (en las pruebas: http://testserver).
    home = api.get("/").text
    assert "__SITE_URL__" not in home
    assert '<meta property="og:image" content="http://testserver/img/compartir.jpg">' in home
    assert '<link rel="canonical" href="http://testserver/">' in home
    assert api.get("/img/compartir.jpg").status_code == 200
    robots = api.get("/robots.txt")
    assert robots.status_code == 200 and "Disallow: /app.html" in robots.text and "Disallow: /api/" in robots.text
    assert "Sitemap: http://testserver/sitemap.xml" in robots.text
    sitemap = api.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert "<loc>http://testserver/</loc>" in sitemap.text
    assert '<meta name="robots" content="noindex">' in api.get("/app.html").text


def test_sin_sesion_o_token_falso_da_401(api):
    assert api.get("/api/reports").status_code == 401
    assert api.get("/api/me", headers={"Authorization": "Bearer token-falso"}).status_code == 401


def test_perfil(api, users):
    ana = users["ana"]
    me = ok(api.get("/api/me", headers=ana["h"]))
    assert me["display_name"] == "Prueba ana" and me["email"] == ana["email"]
    me = ok(api.patch("/api/me", headers=ana["h"], json={"phone": "+57 311 111 1111"}))
    assert me["phone"] == "+57 311 111 1111"
    # No se puede colar un campo que no corresponde.
    assert api.patch("/api/me", headers=ana["h"], json={"id": users["beto"]["id"]}).status_code == 422


def test_especies(api, users):
    codes = {s["code"] for s in ok(api.get("/api/species", headers=users["ana"]["h"]))}
    assert {"dog", "cat"} <= codes


def test_mascotas_solo_del_dueno(api, users):
    ana, beto = users["ana"], users["beto"]
    pet_id = create_pet(api, ana)
    assert any(p["id"] == pet_id for p in ok(api.get("/api/pets", headers=ana["h"])))
    assert ok(api.patch(f"/api/pets/{pet_id}", headers=ana["h"], json={"color": "negro"}))["color"] == "negro"
    assert api.get(f"/api/pets/{pet_id}", headers=beto["h"]).status_code == 404
    assert api.patch(f"/api/pets/{pet_id}", headers=beto["h"], json={"color": "x"}).status_code == 404
    assert api.patch(f"/api/pets/{pet_id}", headers=ana["h"], json={"species": "cat"}).status_code == 422


def test_validaciones_de_reporte(api, users):
    ana = users["ana"]
    base = {"type": "found", "species": "dog", "color": "café", "size": "medium",
            "event_at": now_iso(hours=1), "lat": 4.6, "lng": -74.0}
    malos = [
        base | {"type": "lost"},                                    # perdida sin mascota
        base | {"pet_id": str(uuid.uuid4())},                       # encontrada con mascota
        base | {"event_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
        base | {"lat": 200},
        base | {"size": "gigante"},
        base | {"status": "active"},                                # campo prohibido
        base | {"contact_email": "no-es-correo"},
    ]
    for body in malos:
        assert api.post("/api/reports", headers=ana["h"], json=body).status_code == 422, body


def test_flujo_reporte_perdido(api, users):
    ana, beto = users["ana"], users["beto"]
    report = create_report(api, ana, "lost")
    rid = report["id"]
    assert report["status"] == "draft" and report["is_mine"]
    # Ubicación: pública redondeada (~1 km), exacta solo en los datos privados del dueño.
    assert float(report["approx_lat"]) == 4.65 and float(report["approx_lng"]) == -74.06
    assert float(report["private"]["exact_lat"]) == pytest.approx(4.648312)

    assert api.get(f"/api/reports/{rid}", headers=beto["h"]).status_code == 404  # borrador ajeno
    r = api.post(f"/api/reports/{rid}/publish", headers=ana["h"])
    assert r.status_code == 409 and "foto" in r.json()["detail"]

    # Fotos: un archivo que no es imagen se rechaza; una imagen válida queda lista.
    bad = upload(api, ana, rid, data=b"esto no es una imagen", name="x.png")
    assert bad.status_code in (415, 422)
    photo = ok(upload(api, ana, rid), 201)
    assert photo["status"] == "ready" and photo["width"] == 64
    assert upload(api, beto, rid).status_code == 404  # Beto no sube fotos a reportes ajenos

    published = ok(api.post(f"/api/reports/{rid}/publish", headers=ana["h"]))
    assert published["status"] == "active" and published["published_at"]

    # Beto (con sesión) lo ve, pero sin datos privados ni la mascota.
    seen = ok(api.get(f"/api/reports/{rid}", headers=beto["h"]))
    assert not seen["is_mine"] and "private" not in seen and "pet_id" not in seen and "user_id" not in seen
    feed = ok(api.get("/api/reports", headers=beto["h"], params={"type": "lost", "species": "dog"}))
    assert rid in {r["id"] for r in feed}
    assert api.patch(f"/api/reports/{rid}", headers=beto["h"], json={"color": "x"}).status_code == 404

    # La foto se ve con una URL firmada temporal, y es un JPEG limpio.
    signed = ok(api.get(f"/api/photos/{photo['id']}/url", headers=beto["h"]))
    assert 30 <= signed["expires_in"] <= 900
    image = httpx.get(signed["url"], timeout=30)
    assert image.status_code == 200
    assert Image.open(BytesIO(image.content)).format == "JPEG"

    # El dueño mueve el punto en el mapa: se actualizan ambas ubicaciones.
    moved = ok(api.patch(f"/api/reports/{rid}", headers=ana["h"],
                         json={"lat": 6.251840, "lng": -75.563591, "color": "café claro"}))
    assert float(moved["approx_lat"]) == 6.25 and moved["color"] == "café claro"
    assert float(moved["private"]["exact_lng"]) == pytest.approx(-75.563591)
    assert rid in {r["id"] for r in ok(api.get("/api/reports/mine", headers=ana["h"]))}


def test_maximo_cinco_fotos_y_borrado(api, users):
    beto = users["beto"]
    rid = create_report(api, beto, "found")["id"]
    ids = [ok(upload(api, beto, rid), 201)["id"] for _ in range(5)]
    r = upload(api, beto, rid)
    assert r.status_code == 409 and "5" in r.json()["detail"]
    assert api.delete(f"/api/photos/{ids[0]}", headers=users["ana"]["h"]).status_code == 404
    assert api.delete(f"/api/photos/{ids[0]}", headers=beto["h"]).status_code == 204
    ok(upload(api, beto, rid), 201)  # se liberó un cupo


def test_publicado_conserva_al_menos_una_foto(api, users):
    beto = users["beto"]
    report = active_report(api, beto, "found")
    only_photo = report["photos"][0]["id"]
    assert api.delete(f"/api/photos/{only_photo}", headers=beto["h"]).status_code == 409


def test_confirmar_coincidencia_comparte_contacto(api, users, admin):
    ana, beto = users["ana"], users["beto"]
    lost = active_report(api, ana, "lost", contact_email="ana@example.com")
    found = active_report(api, beto, "found", contact_phone="+57 322 222 2222")
    match_id = insert_match(admin, lost["id"], found["id"])

    # Beto (encontró) la ve, pero no puede confirmarla (D2) y aún no ve contactos.
    listed = ok(api.get(f"/api/reports/{found['id']}/matches", headers=beto["h"]))
    assert [m["id"] for m in listed] == [match_id]
    assert listed[0]["my_role"] == "found_owner" and not listed[0]["can_confirm"]
    assert listed[0]["other_report"]["id"] == lost["id"] and "user_id" not in listed[0]["other_report"]
    assert ok(api.get(f"/api/matches/{match_id}", headers=beto["h"]))["contact"] is None
    assert api.post(f"/api/matches/{match_id}/confirm", headers=beto["h"]).status_code == 403
    # Beto no puede ver las coincidencias de un reporte que no es suyo.
    assert api.get(f"/api/reports/{lost['id']}/matches", headers=beto["h"]).status_code == 404

    # Ana (perdió) confirma: ambos reportes se resuelven y se comparten los contactos.
    confirmed = ok(api.post(f"/api/matches/{match_id}/confirm", headers=ana["h"]))
    assert confirmed["status"] == "confirmed"
    assert confirmed["contact"]["phone"] == "+57 322 222 2222"
    assert confirmed["other_report"]["status"] == "resolved"
    beto_view = ok(api.get(f"/api/matches/{match_id}", headers=beto["h"]))
    assert beto_view["contact"]["email"] == "ana@example.com"
    assert beto_view["contact"]["display_name"] == "Prueba ana"

    # Beto sigue pudiendo ver la foto de Ana aunque el reporte ya no esté activo.
    ok(api.get(f"/api/photos/{lost['photos'][0]['id']}/url", headers=beto["h"]))

    # Beto recibe UNA notificación y la marca como leída.
    notes = [n for n in ok(api.get("/api/notifications", headers=beto["h"])) if n["match_id"] == match_id]
    assert [n["kind"] for n in notes] == ["match_confirmed"]
    assert api.post(f"/api/notifications/{notes[0]['id']}/read", headers=beto["h"]).status_code == 204
    assert api.post(f"/api/notifications/{notes[0]['id']}/read", headers=ana["h"]).status_code == 404
    unread = ok(api.get("/api/notifications", headers=beto["h"], params={"unread_only": True}))
    assert notes[0]["id"] not in {n["id"] for n in unread}


def test_descartar_y_retirar(api, users, admin):
    ana, beto = users["ana"], users["beto"]
    lost = active_report(api, ana, "lost")
    found = active_report(api, beto, "found")
    match_id = insert_match(admin, lost["id"], found["id"])

    discarded = ok(api.post(f"/api/matches/{match_id}/discard", headers=beto["h"]))
    assert discarded["status"] == "discarded"
    assert api.post(f"/api/matches/{match_id}/discard", headers=ana["h"]).status_code == 409
    assert ok(api.get(f"/api/reports/{lost['id']}/matches", headers=ana["h"])) == []
    assert len(ok(api.get(f"/api/reports/{lost['id']}/matches", headers=ana["h"],
                          params={"include_discarded": True}))) == 1
    kinds = [n["kind"] for n in ok(api.get("/api/notifications", headers=ana["h"])) if n["match_id"] == match_id]
    assert kinds == ["match_discarded"]

    withdrawn = ok(api.post(f"/api/reports/{lost['id']}/withdraw", headers=ana["h"]))
    assert withdrawn["status"] == "withdrawn"
    assert api.patch(f"/api/reports/{lost['id']}", headers=ana["h"], json={"color": "x"}).status_code == 409
    assert api.get(f"/api/reports/{lost['id']}", headers=beto["h"]).status_code == 404
