"""Consultar, confirmar y descartar posibles coincidencias.

Las coincidencias las CREA el motor (etapa 7). Aquí solo se leen y se deciden.
El sistema nunca afirma que es el mismo animal: son POSIBLES coincidencias.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import supabase
from ..auth import User, require_user
from .reportes import REPORT_COLS, attach_photos


router = APIRouter(prefix="/api", tags=["coincidencias"])

MATCH_COLS = ("id,lost_report_id,found_report_id,model_name,visual_score,distance_km,"
              "total_score,status,decided_at,created_at")
# Datos del reporte de la otra persona que se pueden mostrar (sin ubicación exacta ni contacto).
OTHER_REPORT_KEYS = ("id", "type", "status", "species", "breed", "color", "size",
                     "distinctive_features", "event_at", "location_label",
                     "approx_lat", "approx_lng", "published_at")


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
    return {
        "id": match["id"], "status": match["status"], "model_name": match["model_name"],
        "visual_score": match["visual_score"], "distance_km": match["distance_km"],
        "total_score": match["total_score"], "created_at": match["created_at"],
        "decided_at": match["decided_at"],
        "my_report_id": mine["id"],
        "my_role": "lost_owner" if mine is lost else "found_owner",
        # D2: solo el dueño de la mascota perdida confirma; cualquiera descarta.
        "can_confirm": mine is lost and match["status"] == "suggested",
        "can_discard": match["status"] == "suggested",
        "other_report": {k: other[k] for k in OTHER_REPORT_KEYS} | {"photos": other["photos"]},
    }


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
    params = {"select": MATCH_COLS, "order": "total_score.desc",
              "or": f"(lost_report_id.eq.{report_id},found_report_id.eq.{report_id})"}
    if not include_discarded:
        params["status"] = "neq.discarded"
    matches = await supabase.db("GET", "matches", token=user.token, params=params)
    ids = {m["lost_report_id"] for m in matches} | {m["found_report_id"] for m in matches}
    reports = await _reports_by_id(ids)
    return [_present(m, reports, user) for m in matches]


@router.get("/matches/{match_id}")
async def get_match(match_id: UUID, user: User = Depends(require_user)):
    """Detalle de una coincidencia. Si está CONFIRMADA, incluye el contacto de la otra persona."""
    rows = await supabase.db("GET", "matches", token=user.token,
                             params={"select": MATCH_COLS, "id": f"eq.{match_id}"})
    if not rows:  # no existe o no participo en ella (RLS)
        raise HTTPException(status_code=404, detail="Coincidencia no encontrada")
    match = rows[0]
    reports = await _reports_by_id({match["lost_report_id"], match["found_report_id"]})
    out = _present(match, reports, user)
    out["contact"] = None
    if match["status"] == "confirmed":
        other_id = out["other_report"]["id"]
        other_user = reports[other_id]["user_id"]
        private = await supabase.db("GET", "report_private", admin=True, params={
            "select": "contact_phone,contact_email", "report_id": f"eq.{other_id}"})
        profile = await supabase.db("GET", "profiles", admin=True, params={
            "select": "display_name,phone", "id": f"eq.{other_user}"})
        p = private[0] if private else {}
        prof = profile[0] if profile else {}
        out["contact"] = {
            "display_name": prof.get("display_name"),
            "phone": p.get("contact_phone") or prof.get("phone"),
            "email": p.get("contact_email"),
        }
    return out


@router.post("/matches/{match_id}/confirm")
async def confirm_match(match_id: UUID, user: User = Depends(require_user)):
    """Solo el dueño de la mascota perdida. Ambos reportes pasan a 'resolved'."""
    await supabase.rpc("confirm_match", {"p_match_id": str(match_id)}, token=user.token)
    return await get_match(match_id, user)


@router.post("/matches/{match_id}/discard")
async def discard_match(match_id: UUID, user: User = Depends(require_user)):
    """Cualquiera de las dos personas. La pareja no vuelve a sugerirse."""
    await supabase.rpc("discard_match", {"p_match_id": str(match_id)}, token=user.token)
    return await get_match(match_id, user)
