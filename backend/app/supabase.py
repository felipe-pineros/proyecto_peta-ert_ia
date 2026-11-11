"""Cliente mínimo para Supabase (REST de la base de datos y Storage).

Dos formas de llamar:
- como USUARIO (`token=<access token>`): Supabase aplica RLS, igual que si fuera el navegador;
- como BACKEND (`admin=True`): usa la secret key y salta RLS. Solo para fotos, Storage y
  lecturas internas que ya se comprobaron antes con el token del usuario.
"""
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
import httpx

from .config import PHOTO_BUCKET, get_settings


_client: httpx.AsyncClient | None = None


async def start() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10))


async def stop() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def client() -> httpx.AsyncClient:
    if _client is None:  # p. ej. en pruebas sin "lifespan"
        raise RuntimeError("El cliente de Supabase no está iniciado")
    return _client


def _headers(token: str | None, admin: bool) -> dict[str, str]:
    s = get_settings()
    if admin:
        headers = {"apikey": s.secret_key}
        if s.secret_key.startswith("eyJ"):  # clave antigua tipo JWT (service_role)
            headers["Authorization"] = f"Bearer {s.secret_key}"
        return headers
    headers = {"apikey": s.publishable_key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# Códigos de PostgreSQL → respuesta HTTP clara para el frontend.
_PG_ERRORS = {
    "42501": (403, "No tienes permiso para esta acción"),
    "23505": (409, "Ese registro ya existe"),
    "23502": (422, "Falta un dato obligatorio"),
    "23503": (422, "Algún dato hace referencia a algo que no existe o no es tuyo"),
    "23514": (422, "Algún dato no cumple las reglas (longitud, valores permitidos…)"),
    "22P02": (422, "Formato de dato no válido"),
    "PGRST116": (404, "No encontrado"),
}


def raise_for_db(response: httpx.Response) -> None:
    """Convierte un error de Supabase en un HTTPException sin filtrar detalles internos."""
    if response.is_success:
        return
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    if code == "P0001":
        # Mensajes escritos por nosotros en las funciones SQL (en español y seguros de mostrar).
        raise HTTPException(status_code=409, detail=str(body.get("message", "Operación no permitida")))
    if code in _PG_ERRORS:
        status, detail = _PG_ERRORS[code]
        raise HTTPException(status_code=status, detail=detail)
    if response.status_code in (401, 403):
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
    raise HTTPException(status_code=502, detail="Error al comunicarse con la base de datos")


async def db(
    method: str,
    path: str,
    *,
    token: str | None = None,
    admin: bool = False,
    params: dict[str, str] | None = None,
    json: Any = None,
    return_rows: bool = True,
) -> Any:
    """Llama a la API REST (PostgREST) de Supabase y devuelve el JSON (o None)."""
    headers = _headers(token, admin)
    if method in ("POST", "PATCH", "DELETE"):
        headers["Prefer"] = "return=representation" if return_rows else "return=minimal"
    try:
        response = await client().request(
            method, f"{get_settings().supabase_url}/rest/v1/{path}",
            headers=headers, params=params, json=json,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="La base de datos no responde") from exc
    raise_for_db(response)
    return response.json() if response.content else None


async def rpc(name: str, args: dict[str, Any], *, token: str) -> Any:
    """Ejecuta una función SQL (publish_report, confirm_match…) como el usuario."""
    return await db("POST", f"rpc/{name}", token=token, json=args)


# ---------------------------------------------------------------------------
# Storage (solo backend)
# ---------------------------------------------------------------------------
def _object_url(path: str) -> str:
    return f"{get_settings().supabase_url}/storage/v1/object/{PHOTO_BUCKET}/{quote(path)}"


async def upload_photo(path: str, data: bytes) -> None:
    headers = _headers(None, admin=True) | {"Content-Type": "image/jpeg", "x-upsert": "false"}
    try:
        response = await client().post(_object_url(path), headers=headers, content=data)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="No se pudo guardar la foto") from exc
    if not response.is_success:
        raise HTTPException(status_code=502, detail="No se pudo guardar la foto")


async def delete_photos(paths: list[str]) -> None:
    if not paths:
        return
    url = f"{get_settings().supabase_url}/storage/v1/object/{PHOTO_BUCKET}"
    try:
        await client().request("DELETE", url, headers=_headers(None, admin=True), json={"prefixes": paths})
    except httpx.HTTPError:
        pass  # un archivo huérfano no debe romper la respuesta al usuario


async def signed_photo_url(path: str) -> tuple[str, int]:
    s = get_settings()
    url = f"{s.supabase_url}/storage/v1/object/sign/{PHOTO_BUCKET}/{quote(path)}"
    try:
        response = await client().post(
            url, headers=_headers(None, admin=True), json={"expiresIn": s.signed_url_ttl_seconds}
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="No se pudo obtener la foto") from exc
    if not response.is_success:
        raise HTTPException(status_code=404, detail="Foto no disponible")
    signed = response.json().get("signedURL") or response.json().get("signedUrl")
    if not signed:
        raise HTTPException(status_code=502, detail="No se pudo obtener la foto")
    return f"{s.supabase_url}/storage/v1{signed}", s.signed_url_ttl_seconds
