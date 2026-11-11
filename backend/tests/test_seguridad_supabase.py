"""Pruebas de seguridad de la base de datos (etapa 3).

Se ejecutan contra el proyecto Supabase configurado en backend/.env:
  1. crean dos usuarios temporales (Ana y Beto) con la secret key;
  2. comprueban qué puede y qué NO puede hacer cada uno con su propio token;
  3. al final borran los usuarios (el borrado en cascada elimina sus datos de prueba).

La secret key solo se usa aquí para simular al backend (crear usuarios, fotos y
coincidencias). Las comprobaciones de permisos usan siempre la clave pública + token.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

from dotenv import load_dotenv
import httpx
import pytest


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
PUBLISHABLE = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SECRET = os.getenv("SUPABASE_SECRET_KEY", "").strip()

DENIED = (401, 403)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def admin_headers() -> dict[str, str]:
    headers = {"apikey": SECRET, "Content-Type": "application/json"}
    if SECRET.startswith("eyJ"):  # clave antigua tipo JWT (service_role)
        headers["Authorization"] = f"Bearer {SECRET}"
    return headers


def user_headers(token: str | None) -> dict[str, str]:
    headers = {"apikey": PUBLISHABLE, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class Db:
    """Llamadas a la API REST de Supabase como un usuario, como visitante o como backend."""

    def __init__(self, client: httpx.Client, token: str | None = None, admin: bool = False):
        self.client = client
        self.headers = admin_headers() if admin else user_headers(token)
        self.headers["Prefer"] = "return=representation"

    def get(self, path: str) -> httpx.Response:
        return self.client.get(f"{URL}/rest/v1/{path}", headers=self.headers)

    def post(self, path: str, body: dict) -> httpx.Response:
        return self.client.post(f"{URL}/rest/v1/{path}", headers=self.headers, json=body)

    def patch(self, path: str, body: dict) -> httpx.Response:
        return self.client.patch(f"{URL}/rest/v1/{path}", headers=self.headers, json=body)

    def rpc(self, name: str, body: dict) -> httpx.Response:
        return self.post(f"rpc/{name}", body)


def ok(response: httpx.Response) -> list | dict | None:
    assert response.is_success, f"{response.status_code}: {response.text}"
    return response.json() if response.content else None


@pytest.fixture(scope="module")
def client():
    if not (URL and PUBLISHABLE and SECRET):
        pytest.fail("Faltan SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY o SUPABASE_SECRET_KEY en backend/.env")
    with httpx.Client(timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def users(client):
    created = []

    def create(name: str) -> dict:
        email = f"prueba-rls-{name}-{uuid.uuid4().hex[:8]}@example.com"
        password = uuid.uuid4().hex + "Aa1!"
        r = client.post(f"{URL}/auth/v1/admin/users", headers=admin_headers(), json={
            "email": email, "password": password, "email_confirm": True,
            "user_metadata": {"display_name": f"Prueba {name}"},
        })
        assert r.status_code in (200, 201), f"No se pudo crear el usuario de prueba: {r.status_code} {r.text}"
        user_id = r.json()["id"]
        created.append(user_id)
        r = client.post(f"{URL}/auth/v1/token?grant_type=password",
                        headers=user_headers(None), json={"email": email, "password": password})
        assert r.status_code == 200, f"No se pudo iniciar sesión: {r.status_code}"
        return {"id": user_id, "db": Db(client, token=r.json()["access_token"])}

    yield {"ana": create("ana"), "beto": create("beto")}

    for user_id in created:
        client.delete(f"{URL}/auth/v1/admin/users/{user_id}", headers=admin_headers())


@pytest.fixture(scope="module")
def backend(client):
    return Db(client, admin=True)


@pytest.fixture(scope="module")
def visitor(client):
    return Db(client)


def new_pet(db: Db, species: str = "dog") -> str:
    return ok(db.post("pets", {"name": "Toby", "species": species, "color": "café", "size": "medium"}))[0]["id"]


def new_report(db: Db, type_: str, pet_id: str | None = None, species: str = "dog") -> str:
    body = {
        "type": type_, "pet_id": pet_id, "species": species, "color": "café", "size": "medium",
        "event_at": datetime.now(timezone.utc).isoformat(),
        "location_label": "Parque de prueba", "approx_lat": 4.65, "approx_lng": -74.06,
    }
    return ok(db.post("reports", body))[0]["id"]


def add_ready_photo(backend: Db, user_id: str, report_id: str) -> httpx.Response:
    photo_id = str(uuid.uuid4())
    return backend.post("report_photos", {
        "id": photo_id, "report_id": report_id, "user_id": user_id,
        "storage_path": f"{user_id}/{report_id}/{photo_id}.jpg",
        "status": "ready", "width": 800, "height": 600, "byte_size": 120_000,
    })


def active_report(db: Db, backend: Db, user_id: str, type_: str, species: str = "dog") -> str:
    pet_id = new_pet(db, species) if type_ == "lost" else None
    report_id = new_report(db, type_, pet_id, species)
    ok(add_ready_photo(backend, user_id, report_id))
    ok(db.rpc("publish_report", {"p_report_id": report_id}))
    return report_id


def new_match(backend: Db, lost_id: str, found_id: str) -> httpx.Response:
    return backend.post("matches", {
        "lost_report_id": lost_id, "found_report_id": found_id, "model_name": "prueba",
        "visual_score": 0.9, "distance_km": 1.2, "total_score": 0.85,
    })


# ---------------------------------------------------------------------------
# Pruebas
# ---------------------------------------------------------------------------
def test_perfil_se_crea_al_registrarse_y_es_privado(users):
    ana, beto = users["ana"], users["beto"]
    perfil = ok(ana["db"].get(f"profiles?id=eq.{ana['id']}"))
    assert len(perfil) == 1 and perfil[0]["display_name"] == "Prueba ana"
    assert ok(beto["db"].get(f"profiles?id=eq.{ana['id']}")) == []


def test_visitante_sin_sesion_no_ve_nada(visitor):
    for tabla in ("reports", "pets", "species", "matches", "report_private"):
        assert visitor.get(f"{tabla}?select=*").status_code in DENIED, tabla


def test_borrador_y_datos_privados_solo_para_el_dueno(users):
    ana, beto = users["ana"], users["beto"]
    pet_id = new_pet(ana["db"])
    report_id = new_report(ana["db"], "lost", pet_id)
    ok(ana["db"].post("report_private", {"report_id": report_id, "exact_lat": 4.651234,
                                          "exact_lng": -74.061234, "contact_phone": "3000000000"}))

    assert len(ok(ana["db"].get(f"reports?id=eq.{report_id}"))) == 1
    assert ok(beto["db"].get(f"reports?id=eq.{report_id}")) == []
    assert ok(beto["db"].get(f"report_private?report_id=eq.{report_id}")) == []
    assert ok(beto["db"].get(f"pets?id=eq.{pet_id}")) == []
    # Beto intenta editar el reporte de Ana: no afecta ninguna fila.
    assert ok(beto["db"].patch(f"reports?id=eq.{report_id}", {"color": "hackeado"})) == []
    assert ok(ana["db"].get(f"reports?id=eq.{report_id}"))[0]["color"] == "café"


def test_ubicacion_publica_queda_redondeada(users):
    ana = users["ana"]
    report = ok(ana["db"].post("reports", {
        "type": "found", "species": "cat", "color": "negro", "size": "small",
        "event_at": datetime.now(timezone.utc).isoformat(),
        "approx_lat": 4.651234, "approx_lng": -74.061234,
    }))[0]
    assert float(report["approx_lat"]) == 4.65 and float(report["approx_lng"]) == -74.06


def test_usuario_no_puede_cambiar_estado_ni_dueno(users):
    ana, beto = users["ana"], users["beto"]
    report_id = new_report(ana["db"], "found")
    assert ana["db"].patch(f"reports?id=eq.{report_id}", {"status": "active"}).status_code in DENIED
    assert ana["db"].patch(f"reports?id=eq.{report_id}", {"user_id": beto["id"]}).status_code in DENIED


def test_reporte_perdido_requiere_mascota_propia(users):
    ana, beto = users["ana"], users["beto"]
    assert ana["db"].post("reports", {
        "type": "lost", "species": "dog", "color": "café", "size": "medium",
        "event_at": datetime.now(timezone.utc).isoformat(), "approx_lat": 4.65, "approx_lng": -74.06,
    }).status_code == 400
    mascota_de_ana = new_pet(ana["db"])
    r = beto["db"].post("reports", {
        "type": "lost", "pet_id": mascota_de_ana, "species": "dog", "color": "café", "size": "medium",
        "event_at": datetime.now(timezone.utc).isoformat(), "approx_lat": 4.65, "approx_lng": -74.06,
    })
    assert not r.is_success


def test_publicar_requiere_foto_y_luego_es_visible(users, backend):
    ana, beto = users["ana"], users["beto"]
    report_id = new_report(ana["db"], "found")
    assert ana["db"].rpc("publish_report", {"p_report_id": report_id}).status_code == 400
    ok(add_ready_photo(backend, ana["id"], report_id))
    # Beto no puede publicar el reporte de Ana.
    assert beto["db"].rpc("publish_report", {"p_report_id": report_id}).status_code in DENIED
    ok(ana["db"].rpc("publish_report", {"p_report_id": report_id}))

    visto = ok(beto["db"].get(f"reports?id=eq.{report_id}"))
    assert len(visto) == 1 and visto[0]["status"] == "active"
    assert len(ok(beto["db"].get(f"report_photos?report_id=eq.{report_id}&select=id,status"))) == 1
    # La ruta interna de Storage no es visible desde la app.
    assert beto["db"].get(f"report_photos?report_id=eq.{report_id}&select=storage_path").status_code in DENIED


def test_maximo_cinco_fotos(users, backend):
    ana = users["ana"]
    report_id = new_report(ana["db"], "found")
    for _ in range(5):
        ok(add_ready_photo(backend, ana["id"], report_id))
    assert not add_ready_photo(backend, ana["id"], report_id).is_success


def test_coincidencias_sin_duplicados_y_reglas_de_pareja(users, backend):
    ana, beto = users["ana"], users["beto"]
    lost_id = active_report(ana["db"], backend, ana["id"], "lost")
    found_id = active_report(beto["db"], backend, beto["id"], "found")
    otro_lost = active_report(beto["db"], backend, beto["id"], "lost")
    gato_found = active_report(beto["db"], backend, beto["id"], "found", species="cat")

    ok(new_match(backend, lost_id, found_id))
    assert new_match(backend, lost_id, found_id).status_code == 409   # pareja repetida
    assert not new_match(backend, lost_id, otro_lost).is_success        # perdida con perdida
    assert not new_match(backend, lost_id, gato_found).is_success       # perro con gato
    assert not new_match(backend, otro_lost, found_id).is_success       # mismo usuario


def test_confirmar_solo_dueno_de_la_perdida(users, backend):
    ana, beto = users["ana"], users["beto"]
    lost_id = active_report(ana["db"], backend, ana["id"], "lost")
    found_id = active_report(beto["db"], backend, beto["id"], "found")
    match_id = ok(new_match(backend, lost_id, found_id))[0]["id"]

    # Ambos ven la coincidencia; nadie puede modificarla directamente.
    assert len(ok(ana["db"].get(f"matches?id=eq.{match_id}"))) == 1
    assert len(ok(beto["db"].get(f"matches?id=eq.{match_id}"))) == 1
    assert beto["db"].patch(f"matches?id=eq.{match_id}", {"status": "confirmed"}).status_code in DENIED

    # Beto (quien la encontró) no puede confirmar; Ana (dueña) sí.
    assert beto["db"].rpc("confirm_match", {"p_match_id": match_id}).status_code in DENIED
    ok(ana["db"].rpc("confirm_match", {"p_match_id": match_id}))

    assert ok(ana["db"].get(f"matches?id=eq.{match_id}"))[0]["status"] == "confirmed"
    assert ok(ana["db"].get(f"reports?id=eq.{lost_id}"))[0]["status"] == "resolved"
    # Un reporte resuelto ya no se puede editar.
    assert ok(ana["db"].patch(f"reports?id=eq.{lost_id}", {"color": "otro"})) == []

    avisos = ok(beto["db"].get(f"notifications?match_id=eq.{match_id}"))
    assert [a["kind"] for a in avisos] == ["match_confirmed"]
    assert ok(ana["db"].get(f"notifications?match_id=eq.{match_id}")) == []


def test_descartar_y_notificaciones_sin_duplicados(users, backend):
    ana, beto = users["ana"], users["beto"]
    lost_id = active_report(ana["db"], backend, ana["id"], "lost")
    found_id = active_report(beto["db"], backend, beto["id"], "found")
    match_id = ok(new_match(backend, lost_id, found_id))[0]["id"]

    ok(backend.post("notifications", {"user_id": ana["id"], "match_id": match_id, "kind": "new_match"}))
    assert backend.post("notifications", {"user_id": ana["id"], "match_id": match_id,
                                           "kind": "new_match"}).status_code == 409

    ok(beto["db"].rpc("discard_match", {"p_match_id": match_id}))
    assert ana["db"].rpc("discard_match", {"p_match_id": match_id}).status_code == 400  # ya decidida
    kinds = sorted(a["kind"] for a in ok(ana["db"].get(f"notifications?match_id=eq.{match_id}")))
    assert kinds == ["match_discarded", "new_match"]

    # Ana solo puede marcar sus avisos como leídos, no cambiarles el tipo.
    aviso = ok(ana["db"].get(f"notifications?match_id=eq.{match_id}&kind=eq.new_match"))[0]
    ok(ana["db"].patch(f"notifications?id=eq.{aviso['id']}", {"read_at": datetime.now(timezone.utc).isoformat()}))
    assert ana["db"].patch(f"notifications?id=eq.{aviso['id']}", {"kind": "match_confirmed"}).status_code in DENIED


def test_bucket_de_fotos_es_privado(client):
    r = client.get(f"{URL}/storage/v1/bucket/report-photos", headers=admin_headers())
    assert r.status_code == 200, r.text
    assert r.json()["public"] is False
