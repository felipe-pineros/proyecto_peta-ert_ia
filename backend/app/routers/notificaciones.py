"""Avisos dentro de la app. Los crea el backend (etapas 7 y 8) y las funciones SQL."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import supabase
from ..auth import User, require_user


router = APIRouter(prefix="/api/notifications", tags=["notificaciones"])

NOTIF_COLS = "id,match_id,kind,read_at,created_at"


@router.get("")
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_user),
):
    params = {"select": NOTIF_COLS, "user_id": f"eq.{user.id}",
              "order": "created_at.desc", "limit": str(limit)}
    if unread_only:
        params["read_at"] = "is.null"
    rows = await supabase.db("GET", "notifications", token=user.token, params=params)
    # Para escribir un aviso claro: ¿soy quien perdió o quien encontró?, y de qué especie es.
    match_ids = {n["match_id"] for n in rows}
    matches = await supabase.db("GET", "matches", token=user.token, params={
        "select": "id,lost_report_id", "id": f"in.({','.join(match_ids)})"}) if match_ids else []
    lost_ids = {m["lost_report_id"] for m in matches}
    lost = await supabase.db("GET", "reports", admin=True, params={
        "select": "id,user_id,species", "id": f"in.({','.join(lost_ids)})"}) if lost_ids else []
    lost_by_id = {r["id"]: r for r in lost}
    info = {m["id"]: lost_by_id.get(m["lost_report_id"]) for m in matches}
    for n in rows:
        report = info.get(n["match_id"])
        n["my_role"] = None if not report else (
            "lost_owner" if report["user_id"] == user.id else "found_owner")
        n["species"] = report["species"] if report else None
    return rows


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: UUID, user: User = Depends(require_user)):
    now = datetime.now(timezone.utc).isoformat()
    updated = await supabase.db("PATCH", "notifications", token=user.token, json={"read_at": now},
                                params={"id": f"eq.{notification_id}", "read_at": "is.null",
                                        "select": "id"})
    if not updated:  # ya estaba leída, no existe o no es mía
        exists = await supabase.db("GET", "notifications", token=user.token,
                                   params={"select": "id", "id": f"eq.{notification_id}"})
        if not exists:
            raise HTTPException(status_code=404, detail="Notificación no encontrada")
