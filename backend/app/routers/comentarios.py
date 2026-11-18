"""Comentarios en los reportes publicados (migración 6).

Sirven para que la comunidad ayude ("lo vi en el parque X"). Se permiten teléfonos (decisión de Daniela);
la base rechaza correos y enlaces de chat (los teléfonos se permiten), y limita el ritmo (5 cada 10 minutos).
Borra un comentario su autor o el dueño del reporte.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from .. import supabase
from ..auth import User, require_user
from ..schemas import CommentCreate


router = APIRouter(prefix="/api", tags=["comentarios"])

COMMENT_COLS = "id,report_id,user_id,body,created_at"


def _no_guests(user: User) -> None:
    if user.is_anonymous:  # la base también lo impide
        raise HTTPException(status_code=403, detail="Crea una cuenta para ver y escribir comentarios")


async def _visible_report(report_id: UUID, user: User) -> dict:
    rows = await supabase.db("GET", "reports", token=user.token,
                             params={"select": "id,user_id,status", "id": f"eq.{report_id}"})
    if not rows:  # no existe o no lo puedo ver (RLS)
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    return rows[0]


@router.get("/reports/{report_id}/comments")
async def list_comments(report_id: UUID, user: User = Depends(require_user)):
    _no_guests(user)
    report = await _visible_report(report_id, user)
    rows = await supabase.db("GET", "report_comments", token=user.token, params={
        "select": COMMENT_COLS, "report_id": f"eq.{report_id}", "order": "created_at.asc", "limit": "200"})
    # Solo el nombre visible de cada autor (nunca su teléfono ni su correo).
    authors = {r["user_id"] for r in rows}
    names = {}
    if authors:
        profiles = await supabase.db("GET", "profiles", admin=True, params={
            "select": "id,display_name", "id": f"in.({','.join(authors)})"})
        names = {p["id"]: p["display_name"] for p in profiles}
    i_own_report = report["user_id"] == user.id
    return [{
        "id": r["id"], "body": r["body"], "created_at": r["created_at"],
        "author": names.get(r["user_id"]) or "Usuario de PetAlert",
        "is_mine": r["user_id"] == user.id,
        "is_report_owner": r["user_id"] == report["user_id"],
        "can_delete": r["user_id"] == user.id or i_own_report,
    } for r in rows]


@router.post("/reports/{report_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(report_id: UUID, body: CommentCreate, user: User = Depends(require_user)):
    _no_guests(user)
    comment_id = await supabase.rpc("add_report_comment",
                                    {"p_report_id": str(report_id), "p_body": body.body}, token=user.token)
    return {"id": comment_id}


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: UUID, user: User = Depends(require_user)):
    _no_guests(user)
    deleted = await supabase.db("DELETE", "report_comments", token=user.token,
                                params={"id": f"eq.{comment_id}", "select": "id"})
    if not deleted:  # no existe o no tengo permiso (RLS)
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
