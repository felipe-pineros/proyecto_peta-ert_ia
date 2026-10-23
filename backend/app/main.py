import asyncio
from pathlib import Path
import logging
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT_DIR, get_settings
from .security import AuthenticatedUser, require_user
from .services.images import MAX_UPLOAD_BYTES, read_and_normalize_image
from .services.supabase import SupabaseGateway


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("peta.api")
app = FastAPI(title="PETA-ERT-IA API", version="0.1.0")

# One image is limited to 10 MiB; allow bounded multipart framing overhead.
MAX_MULTIPART_REQUEST_BYTES = MAX_UPLOAD_BYTES + 256 * 1024
MAX_CONCURRENT_MULTIPART_REQUESTS = 3


class MultipartSizeLimitMiddleware:
    """Bound photo request bodies before Starlette parses multipart data."""

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit
        # Bounds per-process buffering, image work, and upstream requests together.
        self.upload_slots = asyncio.Semaphore(MAX_CONCURRENT_MULTIPART_REQUESTS)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST" or not scope.get("path", "").endswith("/photos"):
            await self.app(scope, receive, send)
            return
        raw_headers = [(key.lower(), value) for key, value in scope.get("headers", [])]
        headers = dict(raw_headers)
        if not headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data"):
            await self.app(scope, receive, send)
            return
        content_lengths = [value for key, value in raw_headers if key == b"content-length"]
        if len(content_lengths) > 1:
            await self._bad_request(send)
            return
        raw_content_length = content_lengths[0] if content_lengths else None
        content_length = None
        if raw_content_length is not None:
            try:
                content_length = int(raw_content_length)
                if content_length < 0:
                    raise ValueError
                if content_length > self.limit:
                    await self._too_large(scope, send)
                    return
            except ValueError:
                await self._bad_request(send)
                return

        async with self.upload_slots:
            await self._buffer_and_dispatch(scope, receive, send, content_length)

    async def _buffer_and_dispatch(self, scope, receive, send, content_length: int | None) -> None:

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                logger.info("Multipart request disconnected before body completion")
                return
            if message["type"] != "http.request":
                await self._bad_request(send)
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.limit:
                await self._too_large(scope, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        if content_length is not None and total != content_length:
            await self._bad_request(send)
            return

        replay = {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return replay

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _too_large(scope, send) -> None:
        body = b'{"detail":"La solicitud multipart supera el l\\u00edmite permitido"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _bad_request(send) -> None:
        body = b'{"detail":"El cuerpo multipart est\\u00e1 incompleto o Content-Length no coincide"}'
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(MultipartSizeLimitMiddleware, limit=MAX_MULTIPART_REQUEST_BYTES)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


class ReportDraft(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    report_type: str
    species: str
    animal_name: str | None = Field(default=None, max_length=120)
    breed: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=120)
    size: str | None = None
    distinctive_features: str | None = Field(default=None, max_length=2000)
    description: str = Field(min_length=1, max_length=5000)
    location_label: str | None = Field(default=None, max_length=160)
    event_at: datetime | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=254)
    precise_latitude: float | None = Field(default=None, ge=-90, le=90)
    precise_longitude: float | None = Field(default=None, ge=-180, le=180)


class ReportDraftUpdate(BaseModel):
    # Full editable representation. Ownership, type/species and status are intentionally absent.
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    animal_name: str | None = Field(max_length=120)
    breed: str | None = Field(max_length=120)
    color: str | None = Field(max_length=120)
    size: str | None
    distinctive_features: str | None = Field(max_length=2000)
    description: str = Field(min_length=1, max_length=5000)
    location_label: str | None = Field(max_length=160)
    event_at: datetime | None
    contact_phone: str | None = Field(max_length=40)
    contact_email: str | None = Field(max_length=254)
    precise_latitude: float | None = Field(ge=-90, le=90)
    precise_longitude: float | None = Field(ge=-180, le=180)


def public_auth_result(result: dict) -> dict:
    """Return only the browser access token; never forward Supabase refresh credentials."""
    user = result.get("user") or {}
    public_user = {key: user[key] for key in ("id", "email") if key in user}
    response = {"user": public_user}
    if result.get("access_token"):
        response.update({
            "access_token": result["access_token"],
            "token_type": result.get("token_type", "bearer"),
            "expires_in": result.get("expires_in"),
        })
    else:
        response["confirmation_required"] = bool(user)
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register")
async def register(credentials: Credentials) -> dict:
    result = await SupabaseGateway().auth("signup", credentials.model_dump())
    return public_auth_result(result)


@app.post("/api/auth/login")
async def login(credentials: Credentials) -> dict:
    result = await SupabaseGateway().auth("token?grant_type=password", credentials.model_dump())
    return public_auth_result(result)


@app.get("/api/reports")
async def get_reports(
    mine: bool = False,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict]:
    return await SupabaseGateway().list_reports(user.access_token, user.id, mine)


@app.post("/api/reports", status_code=201)
async def create_report(
    report: ReportDraft,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, str]:
    if report.report_type not in ("lost", "found") or report.species not in ("dog", "cat"):
        raise HTTPException(status_code=422, detail="Tipo de reporte o especie no válidos")
    if report.size not in (None, "small", "medium", "large", "unknown"):
        raise HTTPException(status_code=422, detail="Tamaño no válido")
    if (report.precise_latitude is None) != (report.precise_longitude is None):
        raise HTTPException(status_code=422, detail="Debes enviar ambas coordenadas precisas o ninguna")
    data = report.model_dump()
    data.pop("report_type")
    data.pop("species")
    report_id = await SupabaseGateway().user_rpc(
        user.access_token,
        "create_report_draft",
        {"p_report_type": report.report_type, "p_species": report.species, **{
            f"p_{name}": value for name, value in data.items()
        }},
    )
    return {"id": str(report_id), "status": "draft"}


@app.get("/api/reports/{report_id}/draft")
async def get_report_draft(
    report_id: UUID,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    result = await SupabaseGateway().user_rpc(
        user.access_token, "get_owned_report_draft", {"p_report_id": str(report_id)},
    )
    if not isinstance(result, list) or len(result) != 1:
        raise HTTPException(status_code=404, detail="Borrador no disponible")
    return result[0]


@app.patch("/api/reports/{report_id}")
async def update_report_draft(
    report_id: UUID,
    report: ReportDraftUpdate,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, str]:
    if report.size not in (None, "small", "medium", "large", "unknown"):
        raise HTTPException(status_code=422, detail="Tama\u00f1o no v\u00e1lido")
    if (report.precise_latitude is None) != (report.precise_longitude is None):
        raise HTTPException(status_code=422, detail="Debes enviar ambas coordenadas precisas o ninguna")
    values = {f"p_{name}": value for name, value in report.model_dump().items()}
    result = await SupabaseGateway().user_rpc(
        user.access_token, "update_owned_report_draft",
        {"p_report_id": str(report_id), **values},
    )
    return {"id": str(result), "status": "draft"}


async def compensate_photo(
    gateway_client: SupabaseGateway, user_id: str, report_id: str, photo_id: str,
    path: str, upload_attempted: bool,
) -> None:
    if upload_attempted:
        # Storage may still complete a timed-out request. Preserve the pending row and object
        # for manual review; this path is deliberately excluded from automatic cleanup.
        logger.warning("Photo upload outcome is uncertain; retained for review photo_id=%s", photo_id)
        return
    marked_for_delete = False
    try:
        abandoned_path = await gateway_client.server_rpc("api_abandon_unuploaded_photo", {
            "p_user_id": user_id, "p_report_id": report_id, "p_photo_id": photo_id,
        })
        marked_for_delete = bool(abandoned_path)
    except Exception as exc:  # Keep the tracked deleting/pending row so the operation can be retried.
        logger.warning("Could not mark photo for cleanup photo_id=%s error_type=%s", photo_id, type(exc).__name__)
    # This exact UUID path was generated by this request, so deleting it is scoped and repeatable
    # because this branch runs only before any Storage upload was attempted.
    try:
        await gateway_client.delete_photo_object(path)
    except Exception as exc:
        logger.warning("Photo object cleanup needs retry photo_id=%s error_type=%s", photo_id, type(exc).__name__)
        return
    if marked_for_delete:
        try:
            await gateway_client.server_rpc("api_finish_photo_delete", {"p_user_id": user_id, "p_photo_id": photo_id})
        except Exception as exc:
            logger.warning("Photo metadata cleanup needs retry photo_id=%s error_type=%s", photo_id, type(exc).__name__)


@app.post("/api/reports/{report_id}/photos", status_code=201)
async def upload_report_photo(
    report_id: UUID,
    photo: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, str]:
    client = SupabaseGateway()
    photo_id = str(uuid4())
    path = f"{user.id}/{report_id}/{photo_id}.jpg"
    upload_attempted = False
    try:
        # Keep registration in the compensation scope: a lost response may follow a committed insert.
        await client.server_rpc("api_register_pending_photo", {
            "p_user_id": user.id, "p_report_id": str(report_id),
            "p_photo_id": photo_id, "p_storage_path": path,
        })
        # wait_for cannot stop Pillow once asyncio.to_thread has started. The middleware
        # already caps concurrent multipart work; let this bounded operation finish.
        body = await read_and_normalize_image(photo)
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="La imagen procesada supera el límite permitido")
        upload_attempted = True
        await client.upload_photo(path, body)
        await client.server_rpc("api_mark_photo_ready", {
            "p_user_id": user.id, "p_photo_id": photo_id,
            "p_content_type": "image/jpeg", "p_byte_size": len(body),
        })
    except Exception:
        await compensate_photo(client, user.id, str(report_id), photo_id, path,
                               upload_attempted=upload_attempted)
        raise
    finally:
        await photo.close()
    return {"id": photo_id, "status": "ready"}


@app.post("/api/reports/{report_id}/publish")
async def publish_report(report_id: UUID, user: AuthenticatedUser = Depends(require_user)) -> dict[str, str]:
    await SupabaseGateway().server_rpc("api_publish_report", {
        "p_user_id": user.id, "p_report_id": str(report_id),
    })
    return {"id": str(report_id), "status": "active"}


@app.post("/api/reports/{report_id}/resolve")
async def resolve_report(report_id: UUID, user: AuthenticatedUser = Depends(require_user)) -> dict[str, str]:
    await SupabaseGateway().server_rpc("api_transition_report", {
        "p_user_id": user.id, "p_report_id": str(report_id), "p_new_status": "resolved",
    })
    return {"id": str(report_id), "status": "resolved"}


@app.post("/api/reports/{report_id}/withdraw")
async def withdraw_report(report_id: UUID, user: AuthenticatedUser = Depends(require_user)) -> dict[str, str]:
    await SupabaseGateway().server_rpc("api_transition_report", {
        "p_user_id": user.id, "p_report_id": str(report_id), "p_new_status": "withdrawn",
    })
    return {"id": str(report_id), "status": "withdrawn"}


@app.delete("/api/reports/{report_id}/photos/{photo_id}")
async def delete_draft_photo(
    report_id: UUID,
    photo_id: UUID,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, str]:
    client = SupabaseGateway()
    path = await client.server_rpc("api_begin_photo_delete", {
        "p_user_id": user.id, "p_report_id": str(report_id), "p_photo_id": str(photo_id),
    })
    if path is None:
        # Same result for a missing or foreign photo: idempotent and non-enumerating.
        return {"id": str(photo_id), "status": "deleted"}
    if not str(path).startswith(f"{user.id}/{report_id}/"):
        raise HTTPException(status_code=404, detail="La fotografía no está disponible")
    await client.delete_photo_object(str(path))
    await client.server_rpc("api_finish_photo_delete", {
        "p_user_id": user.id, "p_photo_id": str(photo_id),
    })
    return {"id": str(photo_id), "status": "deleted"}


@app.post("/api/reports/recover-photos")
async def recover_stale_photos(user: AuthenticatedUser = Depends(require_user)) -> dict[str, int]:
    client = SupabaseGateway()
    items = await client.server_rpc("api_claim_stale_photos", {"p_user_id": user.id}) or []
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="Respuesta de recuperación no válida")
    removed = 0
    retry_pending = 0
    for item in items:
        if not isinstance(item, dict):
            retry_pending += 1
            logger.warning("Photo cleanup result was malformed")
            continue
        photo_id = item.get("photo_id")
        storage_path = item.get("storage_path")
        path_parts = storage_path.split("/") if isinstance(storage_path, str) else []
        if (not isinstance(photo_id, str) or len(path_parts) != 3
                or path_parts[0] != user.id or not path_parts[1] or not path_parts[2]):
            retry_pending += 1
            logger.warning("Photo cleanup path failed scope validation photo_id=%s", photo_id)
            continue
        try:
            # Recheck scope locally before deleting the exact database-tracked path.
            await client.delete_photo_object(storage_path)
            await client.server_rpc("api_finish_photo_delete", {
                "p_user_id": user.id, "p_photo_id": photo_id,
            })
            removed += 1
        except Exception as exc:
            retry_pending += 1
            logger.warning("Photo cleanup needs retry photo_id=%s error_type=%s",
                           photo_id, type(exc).__name__)
    pending_review = await client.server_rpc("api_count_pending_photo_reviews", {"p_user_id": user.id})
    return {"removed": removed, "retry_pending": retry_pending,
            "pending_review": int(pending_review or 0)}


@app.get("/api/reports/{report_id}/photos/review")
async def review_draft_photos(
    report_id: UUID,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, list[dict[str, str | bool]]]:
    rows = await SupabaseGateway().server_rpc("api_review_draft_photos", {
        "p_user_id": user.id, "p_report_id": str(report_id),
    })
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Respuesta de revisi\u00f3n no v\u00e1lida")
    reviewed = []
    for row in rows:
        if not isinstance(row, dict) or row.get("upload_status") not in ("pending", "deleting"):
            raise HTTPException(status_code=502, detail="Respuesta de revisi\u00f3n no v\u00e1lida")
        status = row["upload_status"]
        object_present = bool(row.get("object_present"))
        if status == "pending":
            state = "object_present_unvalidated" if object_present else "upload_result_uncertain"
        else:
            state = "cleanup_incomplete_object_present" if object_present else "cleanup_incomplete_object_absent"
        reviewed.append({"photo_id": str(row["photo_id"]), "state": state,
                         "object_present": object_present})
    return {"photos": reviewed}


@app.get("/api/photos/{photo_id}/signed-url")
async def signed_photo_url(photo_id: UUID, user: AuthenticatedUser = Depends(require_user)) -> dict[str, str | int]:
    client = SupabaseGateway()
    path = await client.server_rpc("api_authorize_photo_read", {
        "p_user_id": user.id, "p_photo_id": str(photo_id),
    })
    url = await client.create_signed_photo_url(str(path))
    return {"url": url, "expires_in": get_settings().signed_url_ttl_seconds}


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse(ROOT_DIR / "index.html")


app.mount("/img", StaticFiles(directory=ROOT_DIR / "img"), name="images")
