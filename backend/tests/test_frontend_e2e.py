"""Pruebas del frontend en un navegador real (etapa 5).

- Arranca el servidor (uvicorn) en el puerto 8765.
- Abre Microsoft Edge (el de Windows, sin descargar navegadores) con Playwright.
- Usa dos usuarios temporales (Ana y Beto) creados con la secret key; al final se
  borran junto con sus fotos.
- El registro desde el formulario se prueba SIMULANDO la respuesta de Supabase, para
  no enviar correos de confirmación a direcciones falsas (Supabase limita y castiga eso).
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from dotenv import load_dotenv
import httpx
from PIL import Image
import pytest

from app.config import BACKEND_DIR, PHOTO_BUCKET, ROOT_DIR


playwright_api = pytest.importorskip("playwright.sync_api")

load_dotenv(BACKEND_DIR / ".env")
URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
PUBLISHABLE = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SECRET = os.getenv("SUPABASE_SECRET_KEY", "").strip()
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
UUID_RE = r"[0-9a-f-]{36}"


def admin_headers() -> dict[str, str]:
    headers = {"apikey": SECRET}
    if SECRET.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SECRET}"
    return headers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND_DIR), "--port", str(PORT)],
        cwd=ROOT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{BASE}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            pytest.fail("El servidor no arrancó")
        yield BASE
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # Edge no disponible (p. ej. Linux/Docker)
            pytest.skip(f"Microsoft Edge no disponible: {exc}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def users():
    created: list[str] = []
    with httpx.Client(timeout=30) as c:
        def create(name: str) -> dict:
            email = f"prueba-web-{name}-{uuid.uuid4().hex[:8]}@example.com"
            password = uuid.uuid4().hex + "Aa1!"
            r = c.post(f"{URL}/auth/v1/admin/users", headers=admin_headers(), json={
                "email": email, "password": password, "email_confirm": True,
                "user_metadata": {"display_name": f"Prueba {name}"}})
            assert r.status_code in (200, 201), r.text
            created.append(r.json()["id"])
            return {"id": created[-1], "email": email, "password": password}

        yield {"ana": create("ana"), "beto": create("beto")}

        r = c.get(f"{URL}/rest/v1/report_photos", headers=admin_headers(),
                  params={"select": "storage_path", "user_id": f"in.({','.join(created)})"})
        paths = [p["storage_path"] for p in r.json()] if r.is_success else []
        if paths:
            c.request("DELETE", f"{URL}/storage/v1/object/{PHOTO_BUCKET}",
                      headers=admin_headers(), json={"prefixes": paths})
        for user_id in created:
            c.delete(f"{URL}/auth/v1/admin/users/{user_id}", headers=admin_headers())


@pytest.fixture(scope="module")
def state():
    return {}


@pytest.fixture(scope="module")
def photo_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("fotos") / "perro.png"
    Image.new("RGB", (320, 240), (180, 120, 60)).save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def new_page(browser, errors: list):
    context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="es-CO")
    page = context.new_page()
    page.set_default_timeout(30_000)
    page.on("pageerror", lambda exc: errors.append(str(exc)))  # errores de JavaScript sin capturar
    return page


def login(page, user):
    page.goto(f"{BASE}/app.html")
    page.fill("#login-email", user["email"])
    page.fill("#login-password", user["password"])
    page.click("#login-form .form-submit")
    page.wait_for_selector("#app-view:not([hidden])")


def token_for(user) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                   json={"email": user["email"], "password": user["password"]}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Pruebas
# ---------------------------------------------------------------------------
def test_landing_conserva_diseno_y_registra(server, browser):
    errors: list = []
    page = new_page(browser, errors)
    page.goto(BASE + "/")
    assert "¿Perdiste o encontraste" in page.inner_text("h1")
    # Los estilos movidos a css/estilos.css se aplican igual que antes (#0F4A5E en el título).
    assert page.eval_on_selector("h1", "e => getComputedStyle(e).color") == "rgb(15, 74, 94)"
    assert page.is_visible("img[src='img/banner.png']")
    assert "aún no envía datos reales" not in page.content()
    assert page.get_attribute("#nav-login", "href") == "app.html"

    # Validación en el navegador.
    page.click("#petalert-form .form-submit")
    assert page.is_visible("#err-nombre") and page.is_visible("#err-password")

    # Registro con la respuesta de Supabase SIMULADA (no se envía ningún correo).
    sent = {}

    def fake_signup(route):
        sent.update(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "id": str(uuid.uuid4()), "aud": "authenticated", "role": "authenticated",
            "email": "camila@example.com", "identities": [{"id": "x", "provider": "email"}],
            "user_metadata": {}, "app_metadata": {}, "created_at": datetime.now(timezone.utc).isoformat()}))

    page.route("**/auth/v1/signup**", fake_signup)
    page.fill("#nombre", "Camila Rojas")
    page.fill("#email", "camila@example.com")
    page.fill("#telefono", "300 123 4567")
    page.fill("#password", "una-clave-segura")
    page.click("#petalert-form .form-submit")
    page.wait_for_selector("#confirm-msg >> text=Te enviamos un correo")
    assert sent["data"]["display_name"] == "Camila Rojas" and sent["data"]["phone"] == "300 123 4567"
    assert errors == []


def test_reporte_rapido_valida_en_el_navegador(server, browser):
    errors: list = []
    page = new_page(browser, errors)
    page.goto(BASE + "/")
    assert page.get_attribute(".action-secondary", "href") == "#encontre"
    page.click(".action-secondary")                       # "Encontré una mascota" baja a la sección
    page.wait_for_selector("#qr-map.leaflet-container")   # el mapa se crea al acercarse
    page.click("#quick-form .form-submit")
    for error in ("#err-qr-photo", "#err-qr-map", "#err-qr-phone"):
        assert page.is_visible(error), error
    page.fill("#qr-email", "no-es-correo")
    assert "correo válido" in page.inner_text("#err-qr-email")
    assert errors == []


def anonymous_enabled() -> bool:
    r = httpx.get(f"{URL}/auth/v1/settings", headers={"apikey": PUBLISHABLE}, timeout=30)
    return bool(r.is_success and r.json().get("external", {}).get("anonymous_users"))


def test_reporte_rapido_sin_cuenta(server, browser, photo_file):
    if not anonymous_enabled():
        pytest.skip("El modo invitado está desactivado: activa 'Allow anonymous sign-ins' en Supabase")
    errors: list = []
    page = new_page(browser, errors)
    guest: dict = {}

    def remember_guest(response):
        if "/auth/v1/signup" in response.url and response.ok:
            guest["id"] = response.json()["user"]["id"]

    page.on("response", remember_guest)
    try:
        page.goto(BASE + "/#encontre")
        page.wait_for_selector("#qr-map.leaflet-container")
        page.set_input_files("#qr-photo", str(photo_file))
        page.wait_for_selector("#qr-photo-box img.preview")
        page.click("#qr-map", position={"x": 260, "y": 120})
        page.wait_for_selector("#qr-map .leaflet-marker-icon")
        page.click("label:has(input[value='cat'])")
        page.fill("#qr-phone", "300 765 4321")
        page.click("#quick-form .form-submit")
        page.wait_for_selector("#qr-msg >> text=Gracias por ayudar", timeout=60_000)
        assert guest.get("id"), "no se creó la sesión de invitado"

        rows = httpx.get(f"{URL}/rest/v1/reports", headers=admin_headers(), timeout=30, params={
            "select": "type,status,species,color", "user_id": f"eq.{guest['id']}"}).json()
        assert rows == [{"type": "found", "status": "active", "species": "cat", "color": None}]

        # Con la sesión de invitado, la app pide iniciar sesión (no muestra reportes ajenos).
        page.goto(f"{BASE}/app.html")
        page.wait_for_selector("#auth-view:not([hidden])")
        assert errors == []
    finally:
        if guest.get("id"):
            r = httpx.get(f"{URL}/rest/v1/report_photos", headers=admin_headers(), timeout=30,
                          params={"select": "storage_path", "user_id": f"eq.{guest['id']}"})
            paths = [p["storage_path"] for p in r.json()] if r.is_success else []
            if paths:
                httpx.request("DELETE", f"{URL}/storage/v1/object/{PHOTO_BUCKET}", headers=admin_headers(),
                              json={"prefixes": paths}, timeout=30)
            httpx.delete(f"{URL}/auth/v1/admin/users/{guest['id']}", headers=admin_headers(), timeout=30)


def test_login_con_clave_incorrecta(server, browser, users):
    errors: list = []
    page = new_page(browser, errors)
    page.goto(f"{BASE}/app.html")
    page.wait_for_selector("#auth-view:not([hidden])")
    page.fill("#login-email", users["ana"]["email"])
    page.fill("#login-password", "clave-equivocada")
    page.click("#login-form .form-submit")
    page.wait_for_selector("#login-error:not([hidden])")
    assert "incorrectos" in page.inner_text("#login-error")
    assert errors == []


def test_crear_reporte_perdido_con_mapa_y_foto(server, browser, users, state, photo_file):
    errors: list = []
    page = new_page(browser, errors)
    login(page, users["ana"])
    page.goto(f"{BASE}/app.html#nuevo/lost")
    page.wait_for_selector("#form-map.leaflet-container")
    page.fill("#f-pet-name", "Toby")
    page.fill("#f-color", "café con blanco")
    page.select_option("#f-size", "medium")
    page.fill("#f-place", "Parque de prueba")
    page.click("#form-map", position={"x": 300, "y": 150})   # marcar el punto
    page.wait_for_selector("#form-map .leaflet-marker-icon")
    page.set_input_files("#f-photos", str(photo_file))
    page.click("#view form .form-submit")

    page.wait_for_url(re.compile(rf"#reporte/{UUID_RE}$"), timeout=60_000)
    state["ana_report"] = page.url.rsplit("/", 1)[-1]
    page.wait_for_selector(".badge-active")                 # "Publicado"
    page.wait_for_function("() => { const i = document.querySelector('.photo-main');"
                           " return i && i.complete && i.naturalWidth > 0; }")  # la foto firmada carga
    assert "Tu contacto (privado)" in page.content()
    page.wait_for_selector("#detail-map .leaflet-marker-icon")  # el dueño ve el punto exacto
    assert errors == []


def test_otro_usuario_ve_el_reporte_sin_datos_privados(server, browser, users, state):
    errors: list = []
    page = new_page(browser, errors)
    login(page, users["beto"])
    page.wait_for_selector(f"a[href='#reporte/{state['ana_report']}']").click()
    page.wait_for_selector("#detail-map path.leaflet-interactive")  # círculo aproximado, no el punto
    assert page.query_selector("#detail-map .leaflet-marker-icon") is None
    assert "Tu contacto (privado)" not in page.content()
    assert errors == []


def test_confirmar_coincidencia_y_aviso(server, browser, users, state):
    ana, beto = users["ana"], users["beto"]
    # Beto publica un reporte de mascota encontrada (por la API, para ir más rápido).
    h = {"Authorization": f"Bearer {token_for(beto)}"}
    with httpx.Client(base_url=BASE, timeout=60) as api:
        found = api.post("/api/reports", headers=h, json={
            "type": "found", "species": "dog", "color": "café", "size": "medium",
            "event_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "lat": 4.65, "lng": -74.06, "contact_phone": "+57 322 222 2222"}).json()
        buf = BytesIO()
        Image.new("RGB", (64, 64), (90, 60, 30)).save(buf, format="PNG")
        assert api.post(f"/api/reports/{found['id']}/photos", headers=h,
                        files={"file": ("f.png", buf.getvalue(), "image/png")}).status_code == 201
        assert api.post(f"/api/reports/{found['id']}/publish", headers=h).status_code == 200
    # El motor es de la etapa 7: la coincidencia se inserta a mano.
    r = httpx.post(f"{URL}/rest/v1/matches", headers=admin_headers() | {"Prefer": "return=representation"},
                   json={"lost_report_id": state["ana_report"], "found_report_id": found["id"],
                         "model_name": "prueba", "visual_score": 0.91, "distance_km": 0.8, "total_score": 0.88})
    assert r.is_success, r.text

    errors: list = []
    page = new_page(browser, errors)
    page.on("dialog", lambda d: d.accept())
    login(page, ana)
    page.goto(f"{BASE}/app.html#reporte/{state['ana_report']}")
    page.wait_for_selector(".match-item >> text=Parecido 91 %")
    page.click(".match-item >> text=Ver detalle")
    page.wait_for_selector("text=No es una confirmación", timeout=30_000)
    page.click("text=Es mi mascota")
    page.wait_for_selector(".contact-box >> text=+57 322 222 2222")

    # Beto ve el aviso, lo abre y encuentra el contacto de Ana.
    page2 = new_page(browser, errors)
    login(page2, beto)
    page2.wait_for_selector("#notif-badge:not([hidden])")
    assert page2.inner_text("#notif-badge") == "1"
    page2.click("[data-nav='notificaciones']")
    page2.click(".notif-item >> text=Confirmaron una coincidencia")
    page2.wait_for_selector(".contact-box >> text=Prueba ana")
    assert errors == []
