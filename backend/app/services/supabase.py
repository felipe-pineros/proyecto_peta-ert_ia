from typing import Any
from urllib.parse import quote, urljoin

import httpx
from fastapi import HTTPException

from ..config import get_settings


BUCKET = "pet-report-photos"


class SupabaseGateway:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _user_headers(self, access_token: str) -> dict[str, str]:
        return {
            "apikey": self.settings.supabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _server_headers(self, content_type: str = "application/json") -> dict[str, str]:
        return {
            "apikey": self.settings.service_role_key,
            "Authorization": f"Bearer {self.settings.service_role_key}",
            "Content-Type": content_type,
        }

    async def auth(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.settings.supabase_url}/auth/v1/{path}",
                    headers={"apikey": self.settings.supabase_anon_key, "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="Servicio de autenticación no disponible") from exc
        if response.is_error:
            try:
                message = response.json().get("msg") or response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            raise HTTPException(status_code=response.status_code if response.status_code < 500 else 502,
                                detail=message or "No se pudo completar la autenticación")
        return response.json()

    async def user_rpc(self, access_token: str, name: str, payload: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.settings.supabase_url}/rest/v1/rpc/{name}",
                    headers=self._user_headers(access_token), json=payload,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="Base de datos no disponible") from exc
        self._raise_for_supabase(response, "No se pudo completar la operación")
        return response.json()

    async def server_rpc(self, name: str, payload: dict[str, Any]) -> Any:
        # Only fixed RPC names from this module are called; there is no arbitrary SQL/RPC endpoint.
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.settings.supabase_url}/rest/v1/rpc/{name}",
                    headers=self._server_headers(), json=payload,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="Base de datos no disponible") from exc
        self._raise_for_supabase(response, "No se pudo completar la operación protegida")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Respuesta RPC no válida") from exc

    async def list_reports(self, access_token: str, user_id: str, mine: bool) -> list[dict[str, Any]]:
        fields = "id,report_type,species,animal_name,breed,color,size,distinctive_features,description,location_label,event_at,status,published_at,created_at,updated_at"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if mine:
                    reports = await self.server_rpc("api_list_owned_reports", {"p_user_id": user_id})
                    if not isinstance(reports, list):
                        raise HTTPException(status_code=502, detail="Respuesta de reportes propios no válida")
                else:
                    params = {"select": fields, "order": "created_at.desc", "limit": "100", "status": "eq.active"}
                    response = await client.get(
                        f"{self.settings.supabase_url}/rest/v1/reports",
                        headers=self._user_headers(access_token), params=params,
                    )
                    self._raise_for_supabase(response, "No se pudieron consultar los reportes")
                    reports = response.json()
                if not reports:
                    return []
                ids = ",".join(report["id"] for report in reports)
                photos_response = await client.get(
                    f"{self.settings.supabase_url}/rest/v1/report_photos",
                    headers=self._user_headers(access_token),
                    params={"select": "id,report_id", "report_id": f"in.({ids})", "upload_status": "eq.ready"},
                )
                self._raise_for_supabase(photos_response, "No se pudieron consultar las fotos")
                photos = photos_response.json()
        except httpx.HTTPError as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=503, detail="Base de datos no disponible") from exc
        by_report: dict[str, list[str]] = {report["id"]: [] for report in reports}
        for photo in photos:
            if photo["report_id"] in by_report:
                by_report[photo["report_id"]].append(photo["id"])
        for report in reports:
            report["photo_ids"] = by_report[report["id"]]
        return reports

    async def upload_photo(self, path: str, body: bytes) -> None:
        encoded_path = quote(path, safe="/")
        headers = self._server_headers("image/jpeg")
        headers["x-upsert"] = "false"
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self.settings.supabase_url}/storage/v1/object/{BUCKET}/{encoded_path}",
                    headers=headers, content=body,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="No se pudo guardar la fotografía") from exc
        self._raise_for_supabase(response, "No se pudo guardar la fotografía")

    async def delete_photo_object(self, path: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.delete(
                    f"{self.settings.supabase_url}/storage/v1/object/{BUCKET}",
                    headers=self._server_headers(), json={"prefixes": [path]},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="No se pudo eliminar el objeto; se podrá reintentar") from exc
        # Missing objects are already clean and can be finalized in PostgreSQL.
        if response.status_code == 404:
            return
        self._raise_for_supabase(response, "No se pudo eliminar el objeto; se podrá reintentar")

    async def create_signed_photo_url(self, path: str) -> str:
        encoded_path = quote(path, safe="/")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.settings.supabase_url}/storage/v1/object/sign/{BUCKET}/{encoded_path}",
                    headers=self._server_headers(),
                    json={"expiresIn": self.settings.signed_url_ttl_seconds},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="No se pudo preparar el acceso temporal a la foto") from exc
        self._raise_for_supabase(response, "No se pudo preparar el acceso temporal a la foto")
        signed_url = response.json().get("signedURL")
        if not signed_url:
            raise HTTPException(status_code=502, detail="Storage no devolvió un enlace temporal")
        storage_api = f"{self.settings.supabase_url}/storage/v1/"
        return urljoin(storage_api, signed_url.lstrip("/"))

    @staticmethod
    def _raise_for_supabase(response: httpx.Response, fallback: str) -> None:
        if not response.is_error:
            return
        # Keep server diagnostics out of client responses and logs; upstream bodies may contain details.
        status = response.status_code if response.status_code in (400, 401, 403, 404, 409, 413, 422) else 502
        raise HTTPException(status_code=status, detail=fallback)
