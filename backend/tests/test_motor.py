"""Pruebas del motor de coincidencias (etapa 7) contra el Supabase real de backend/.env.

Usan el modelo DE VERDAD (DINOv2-S en ONNX) con imágenes del propio repositorio:
- "mismo animal": img/flujo-perro.png y una versión recortada y volteada (similitud ~0,95);
- "otro animal":  img/flujo-gato.png (similitud ~0,06 con el perro).
Crean usuarios temporales y al final borran sus fotos y cuentas.
Necesitan la migración 5 aplicada y backend/modelos/dinov2_s_model.onnx (python -m app.ia.descargar).
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
import uuid

from dotenv import load_dotenv
from fastapi.testclient import TestClient
import httpx
from PIL import Image, ImageOps
import pytest

from app import ia
from app.config import BACKEND_DIR, PHOTO_BUCKET, ROOT_DIR


load_dotenv(BACKEND_DIR / ".env")
URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
PUBLISHABLE = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SECRET = os.getenv("SUPABASE_SECRET_KEY", "").strip()
BOGOTA = (4.648312, -74.062711)
MEDELLIN = (6.244203, -75.581212)  # ~240 km: fuera del radio de 50 km


def admin_headers() -> dict[str, str]:
    headers = {"apikey": SECRET}
    if SECRET.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SECRET}"
    return headers


def ok(response, expected: int = 200):
    assert response.status_code == expected, f"{response.status_code}: {response.text}"
    return response.json() if response.content else None


def png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


DOG = Image.open(ROOT_DIR / "img" / "flujo-perro.png").convert("RGB")
_w, _h = DOG.size
PHOTO_DOG = png(DOG)
PHOTO_DOG_OTHER_SHOT = png(ImageOps.mirror(DOG.crop((int(_w * .08), int(_h * .08), int(_w * .95), int(_h * .95)))))
PHOTO_OTHER_ANIMAL = png(Image.open(ROOT_DIR / "img" / "flujo-gato.png"))


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
    previous = os.environ.get("IA_ENABLED")
    os.environ["IA_ENABLED"] = "true"
    if not ia.enabled():
        pytest.fail("Falta el modelo: cd backend; .\\.venv\\Scripts\\python.exe -m app.ia.descargar")
    from app.main import app
    try:
        with TestClient(app) as c:
            yield c
    finally:
        os.environ["IA_ENABLED"] = previous if previous is not None else "false"


@pytest.fixture(scope="module")
def users(admin):
    created: list[str] = []

    def create(name: str) -> dict:
        email = f"prueba-motor-{name}-{uuid.uuid4().hex[:8]}@example.com"
        password = uuid.uuid4().hex + "Aa1!"
        r = admin.post(f"{URL}/auth/v1/admin/users", headers=admin_headers(), json={
            "email": email, "password": password, "email_confirm": True,
            "user_metadata": {"display_name": f"Prueba {name}"}})
        assert r.status_code in (200, 201), r.text
        created.append(r.json()["id"])
        r = admin.post(f"{URL}/auth/v1/token?grant_type=password",
                       headers={"apikey": PUBLISHABLE}, json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"id": created[-1], "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}

    yield {"ana": create("ana"), "beto": create("beto")}

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
def ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def published(api, user, type_, photo, species="dog", where=BOGOTA, event_at=None) -> dict:
    body = {"type": type_, "species": species, "color": "café", "size": "medium",
            "event_at": event_at or ago(hours=2), "location_label": "Prueba del motor",
            "lat": where[0], "lng": where[1], "contact_phone": "+57 300 000 0000"}
    if type_ == "lost":
        body["pet_id"] = ok(api.post("/api/pets", headers=user["h"], json={
            "name": "Toby", "species": species, "color": "café", "size": "medium"}), 201)["id"]
    report = ok(api.post("/api/reports", headers=user["h"], json=body), 201)
    ok(api.post(f"/api/reports/{report['id']}/photos", headers=user["h"],
                files={"file": ("foto.png", photo, "image/png")}), 201)
    # Al publicar, el motor corre en segundo plano (TestClient espera a que termine).
    return ok(api.post(f"/api/reports/{report['id']}/publish", headers=user["h"]))


def matches_between(admin, lost_id, found_id) -> list[dict]:
    r = admin.get(f"{URL}/rest/v1/matches", headers=admin_headers(), params={
        "select": "*", "lost_report_id": f"eq.{lost_id}", "found_report_id": f"eq.{found_id}"})
    assert r.is_success, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Pruebas
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def lost_dog(api, users):
    return published(api, users["ana"], "lost", PHOTO_DOG)


def test_misma_mascota_crea_una_posible_coincidencia(api, admin, users, lost_dog):
    found = published(api, users["beto"], "found", PHOTO_DOG_OTHER_SHOT)
    rows = matches_between(admin, lost_dog["id"], found["id"])
    assert len(rows) == 1, "debería sugerirse la coincidencia"
    m = rows[0]
    assert m["status"] == "suggested" and m["model_name"] == "dinov2_s"
    assert m["visual_score"] >= 0.9                       # misma foto, recortada y volteada
    assert m["distance_km"] < 1                           # mismo lugar
    assert abs(m["total_score"] - (0.75 * m["visual_score"] + 0.25 * 1.0)) < 0.01
    # Las huellas quedaron guardadas (384 números por foto, normalizadas).
    photos = admin.get(f"{URL}/rest/v1/report_photos", headers=admin_headers(),
                       params={"select": "id", "report_id": f"eq.{found['id']}"}).json()
    emb = admin.get(f"{URL}/rest/v1/photo_embeddings", headers=admin_headers(), params={
        "select": "embedding,model_name", "photo_id": f"eq.{photos[0]['id']}"}).json()
    assert len(emb) == 1 and emb[0]["model_name"] == "dinov2_s"
    assert len(emb[0]["embedding"].strip("[]").split(",")) == 384
    # Ana (perdió) la ve en la app.
    listed = ok(api.get(f"/api/reports/{lost_dog['id']}/matches", headers=users["ana"]["h"]))
    assert m["id"] in [x["id"] for x in listed]


def test_recalcular_no_duplica_y_respeta_descartadas(api, admin, users, lost_dog):
    found = published(api, users["beto"], "found", PHOTO_DOG_OTHER_SHOT)
    [m] = matches_between(admin, lost_dog["id"], found["id"])
    # Una foto nueva en un reporte publicado vuelve a pasar por el motor: sigue habiendo UNA.
    ok(api.post(f"/api/reports/{found['id']}/photos", headers=users["beto"]["h"],
                files={"file": ("otra.png", PHOTO_DOG, "image/png")}), 201)
    again = matches_between(admin, lost_dog["id"], found["id"])
    assert [x["id"] for x in again] == [m["id"]]
    assert again[0]["visual_score"] >= m["visual_score"] - 1e-6  # ahora hay una foto idéntica
    # Beto la descarta; recalcular no la revive ni la cambia.
    ok(api.post(f"/api/matches/{m['id']}/discard", headers=users["beto"]["h"]))
    ok(api.post(f"/api/reports/{found['id']}/photos", headers=users["beto"]["h"],
                files={"file": ("otra2.png", PHOTO_DOG_OTHER_SHOT, "image/png")}), 201)
    after = matches_between(admin, lost_dog["id"], found["id"])
    assert len(after) == 1 and after[0]["status"] == "discarded"
    assert after[0]["visual_score"] == again[0]["visual_score"]


def test_avisa_a_las_dos_personas_sin_duplicar(api, admin, users, lost_dog):
    found = published(api, users["beto"], "found", PHOTO_DOG_OTHER_SHOT)
    [m] = matches_between(admin, lost_dog["id"], found["id"])

    def avisos(user):
        rows = ok(api.get("/api/notifications", headers=user["h"]))
        return [n for n in rows if n["match_id"] == m["id"] and n["kind"] == "new_match"]

    [ana], [beto] = avisos(users["ana"]), avisos(users["beto"])
    assert ana["my_role"] == "lost_owner" and beto["my_role"] == "found_owner"
    assert ana["species"] == "dog" and ana["read_at"] is None
    # Recalcular (foto nueva) no crea un segundo aviso ni "des-lee" el que ya se leyó.
    ok(api.post(f"/api/notifications/{ana['id']}/read", headers=users["ana"]["h"]), 204)
    ok(api.post(f"/api/reports/{found['id']}/photos", headers=users["beto"]["h"],
                files={"file": ("otra.png", PHOTO_DOG, "image/png")}), 201)
    [again] = avisos(users["ana"])
    assert again["id"] == ana["id"] and again["read_at"] is not None
    assert len(avisos(users["beto"])) == 1


def test_otro_animal_no_se_sugiere(api, admin, users, lost_dog):
    found = published(api, users["beto"], "found", PHOTO_OTHER_ANIMAL)
    assert matches_between(admin, lost_dog["id"], found["id"]) == []


@pytest.mark.parametrize("caso", ["lejos", "otra_especie", "encontrada_antes", "mismo_usuario"])
def test_filtros(api, admin, users, lost_dog, caso):
    owner = users["ana"] if caso == "mismo_usuario" else users["beto"]
    kwargs = {"lejos": {"where": MEDELLIN},
              "otra_especie": {"species": "cat"},
              "encontrada_antes": {"event_at": ago(days=5)},  # se perdió hace 2 horas
              "mismo_usuario": {}}[caso]
    found = published(api, owner, "found", PHOTO_DOG, **kwargs)
    assert matches_between(admin, lost_dog["id"], found["id"]) == [], caso
