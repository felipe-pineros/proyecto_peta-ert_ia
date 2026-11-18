"""Coincidencias: ver, pedir el contacto ("Es mi mascota"), aceptar, descartar y ver el teléfono.

Las sugiere el motor (etapa 7) o las pide el dueño desde Explorar (migración 6).
El sistema nunca afirma que es el mismo animal: son POSIBLES coincidencias.

Protección del contacto (decisiones de Daniela, 2026-11-18; las reglas viven en la base):
- Pedirlo exige reporte perdido publicado con foto propia, una seña y máx. 3 solicitudes/24 h.
- Si quien encontró tiene cuenta, debe aceptar; mientras tanto el dueño solo ve su CORREO.
- Si quien encontró no tiene cuenta, al pasar los filtros se confirma directamente.
- El teléfono se pide aparte (POST /phone): máximo 3 teléfonos distintos cada 24 h por persona.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import ia, supabase
from ..auth import User, require_user
from ..schemas import MatchAnswer, MatchClaim, MatchRequest
from .reportes import REPORT_COLS, attach_photos


router = APIRouter(prefix="/api", tags=["coincidencias"])

MATCH_COLS = ("id,lost_report_id,found_report_id,model_name,visual_score,distance_km,"
              "total_score,status,origin,claim_note,requested_at,decided_at,created_at")
# Datos del reporte de la otra persona que se pueden mostrar (sin ubicación exacta ni contacto).
OTHER_REPORT_KEYS = ("id", "type", "status", "species", "breed", "color", "size",
                     "distinctive_features", "event_at", "location_label",
                     "approx_lat", "approx_lng", "published_at")
PHONE_LIMIT = 3
COLOMBIA = timezone(timedelta(hours=-5))  # sin horario de verano; evita depender de tzdata en Windows


async def _reports_by_id(ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = await supabase.db("GET", "reports", admin=True,
                             params={"select": REPORT_COLS, "id": f"in.({','.join(ids)})"})
    await attach_photos(rows, admin=True)
    return {r["id"]: r for r in rows}


def _present(match: dict, reports: dict[str, dict], user: User) -> dict:
    lost, found = reports[match["lost_report_id"]], reports[match["found_report_id"]]
    mine, other = (lost, found) if lost["user_id"] == user.id else (found, lost)
    is_lost_owner = mine is lost
    status = match["status"]
    return {
        "id": match["id"], "status": status, "origin": match["origin"],
        "model_name": match["model_name"],
        "visual_score": match["visual_score"], "distance_km": match["distance_km"],
        "total_score": match["total_score"], "created_at": match["created_at"],
        "requested_at": match["requested_at"], "decided_at": match["decided_at"],
        # La seña la escribe el dueño para que quien encontró pueda comprobarlo.
        "claim_note": match["claim_note"],
        "my_report_id": mine["id"],
        "my_role": "lost_owner" if is_lost_owner else "found_owner",
        # D2 + migración 6: el dueño pide el contacto; quien encontró acepta o rechaza.
        "can_request": is_lost_owner and status == "suggested",
        "can_answer": (not is_lost_owner) and status == "requested",
        "can_discard": status == "suggested" or (is_lost_owner and status == "requested"),
        "other_report": {k: other[k] for k in OTHER_REPORT_KEYS} | {"photos": other["photos"]},
    }


async def _contact_rows(report_id: str, owner_id: str) -> tuple[dict, dict]:
    private = await supabase.db("GET", "report_private", admin=True, params={
        "select": "contact_phone,contact_email", "report_id": f"eq.{report_id}"})
    profile = await supabase.db("GET", "profiles", admin=True, params={
        "select": "display_name,phone", "id": f"eq.{owner_id}"})
    return (private[0] if private else {}), (profile[0] if profile else {})


async def _phone_quota(user_id: str) -> int:
    """Cuántos teléfonos nuevos puede ver todavía en las últimas 24 horas."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    seen = await supabase.db("GET", "contact_views", admin=True, params={
        "select": "match_id", "viewer_id": f"eq.{user_id}", "created_at": f"gt.{since}"})
    return max(PHONE_LIMIT - len(seen), 0)


async def _load(match_id: UUID, user: User) -> tuple[dict, dict, dict]:
    rows = await supabase.db("GET", "matches", token=user.token,
                             params={"select": MATCH_COLS, "id": f"eq.{match_id}"})
    if not rows:  # no existe o no participo en ella (RLS)
        raise HTTPException(status_code=404, detail="Coincidencia no encontrada")
    match = rows[0]
    reports = await _reports_by_id({match["lost_report_id"], match["found_report_id"]})
    return match, reports, _present(match, reports, user)


@router.get("/reports/{report_id}/matches")
async def list_report_matches(
    report_id: UUID,
    include_discarded: bool = Query(default=False),
    user: User = Depends(require_user),
):
    """Posibles coincidencias de uno de MIS reportes, de mayor a menor puntaje."""
    own = await supabase.db("GET", "reports", token=user.token,
                            params={"select": "id,user_id", "id": f"eq.{report_id}"})
    if not own or own[0]["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    params = {"select": MATCH_COLS, "order": "total_score.desc.nullslast",
              "or": f"(lost_report_id.eq.{report_id},found_report_id.eq.{report_id})"}
    if not include_discarded:
        params["status"] = "neq.discarded"
    matches = await supabase.db("GET", "matches", token=user.token, params=params)
    ids = {m["lost_report_id"] for m in matches} | {m["found_report_id"] for m in matches}
    reports = await _reports_by_id(ids)
    return [_present(m, reports, user) for m in matches]


@router.get("/matches/{match_id}")
async def get_match(match_id: UUID, user: User = Depends(require_user)):
    """Detalle de una coincidencia, con el contacto que a esta persona le corresponde ver."""
    match, reports, out = await _load(match_id, user)
    out["contact"] = None
    status = match["status"]
    other_id = out["other_report"]["id"]
    if status == "confirmed" or (status == "requested" and out["my_role"] == "lost_owner"):
        private, prof = await _contact_rows(other_id, reports[other_id]["user_id"])
        phone = private.get("contact_phone") or prof.get("phone")
        contact = {"display_name": prof.get("display_name"), "email": private.get("contact_email"),
                   "has_phone": False, "phone": None, "phone_views_left": None}
        if status == "confirmed":
            # El teléfono solo se entrega por POST /phone (cuenta para el límite), salvo si ya lo vio.
            contact["has_phone"] = bool(phone)
            seen = await supabase.db("GET", "contact_views", admin=True, params={
                "select": "match_id", "viewer_id": f"eq.{user.id}", "match_id": f"eq.{match_id}"})
            if seen and phone:
                contact["phone"] = phone
            elif phone:
                contact["phone_views_left"] = await _phone_quota(user.id)
        out["contact"] = contact
    return out


@router.post("/matches/{match_id}/phone")
async def reveal_phone(match_id: UUID, user: User = Depends(require_user)):
    """Muestra el teléfono de la otra persona. Máximo 3 teléfonos distintos cada 24 horas."""
    match, reports, out = await _load(match_id, user)
    if match["status"] != "confirmed":
        raise HTTPException(status_code=409, detail="El teléfono se comparte cuando la coincidencia está confirmada")
    other_id = out["other_report"]["id"]
    private, prof = await _contact_rows(other_id, reports[other_id]["user_id"])
    phone = private.get("contact_phone") or prof.get("phone")
    if not phone:
        raise HTTPException(status_code=404, detail="La otra persona no dejó teléfono")
    [result] = await supabase.db("POST", "rpc/reveal_phone", admin=True,
                                 json={"p_viewer": user.id, "p_match_id": str(match_id)})
    if not result["allowed"]:
        when = datetime.fromisoformat(result["next_at"]).astimezone(COLOMBIA).strftime("%d/%m a las %H:%M")
        raise HTTPException(status_code=429, detail=(
            f"Por seguridad, cada persona puede ver máximo {PHONE_LIMIT} teléfonos cada 24 horas. "
            f"Podrás ver este el {when} (hora de Colombia). Mientras tanto puedes escribirle al correo."))
    return {"phone": phone, "phone_views_left": result["views_left"]}


@router.post("/matches/{match_id}/request")
async def request_match(match_id: UUID, body: MatchRequest, user: User = Depends(require_user)):
    """"Es mi mascota" desde una coincidencia sugerida. Solo el dueño de la mascota perdida."""
    await supabase.rpc("request_match", {"p_match_id": str(match_id), "p_note": body.note}, token=user.token)
    return await get_match(match_id, user)


@router.post("/reports/{found_report_id}/claim")
async def claim_found_report(found_report_id: UUID, body: MatchClaim, user: User = Depends(require_user)):
    """"Es mi mascota" desde Explorar, sobre un reporte encontrado que la IA no sugirió."""
    if user.is_anonymous:
        raise HTTPException(status_code=403, detail="Crea una cuenta para reclamar una mascota")
    rows = await supabase.rpc("claim_found_report", {
        "p_found_report_id": str(found_report_id), "p_lost_report_id": str(body.lost_report_id),
        "p_note": body.note, "p_model": ia.selected_spec().name}, token=user.token)
    return await get_match(UUID(rows[0]["match_id"]), user)


@router.post("/matches/{match_id}/answer")
async def answer_match(match_id: UUID, body: MatchAnswer, user: User = Depends(require_user)):
    """Quien encontró (con cuenta) acepta o rechaza la solicitud del dueño."""
    await supabase.rpc("answer_match_request", {"p_match_id": str(match_id), "p_accept": body.accept},
                       token=user.token)
    return await get_match(match_id, user)


@router.post("/matches/{match_id}/discard")
async def discard_match(match_id: UUID, user: User = Depends(require_user)):
    """Cualquiera de las dos personas (o el dueño cancela su solicitud). No vuelve a sugerirse."""
    await supabase.rpc("discard_match", {"p_match_id": str(match_id)}, token=user.token)
    return await get_match(match_id, user)
