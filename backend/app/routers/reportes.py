"""Reportes de mascotas perdidas y encontradas.

Ubicación (decisión D3): el usuario marca el punto exacto en el mapa.
- `report_private.exact_lat/lng` guarda el punto exacto (solo lo ve el dueño).
- `reports.approx_lat/lng` guarda el punto redondeado a 2 decimales (~1 km), que es
  lo que ven los demás y lo que usará el motor de coincidencias para la distancia.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import supabase
from ..auth import User, require_user
from ..schemas import ReportCreate, ReportUpdate


router = APIRouter(prefix="/api/reports", tags=["reportes"])

REPORT_COLS = ("id,user_id,pet_id,type,status,species,breed,color,size,distinctive_features,"
               "event_at,location_label,approx_lat,approx_lng,published_at,resolved_at,"
               "created_at,updated_at")
PRIVATE_COLS = "exact_lat,exact_lng,contact_phone,contact_email"
DESCRIPTIVE = ("breed", "color", "size", "distinctive_features", "event_at", "location_label")
PRIVATE = ("contact_phone", "contact_email")


def approx(value: float) -> float:
    """Redondea una coordenada a 2 decimales (≈ 1,1 km)."""
    return round(value, 2)


def present(row: dict, user: User) -> dict:
    """Prepara un reporte para el frontend: oculta user_id y dice si es mío."""
    out = {k: v for k, v in row.items() if k != "user_id"}
    out["is_mine"] = row.get("user_id") == user.id
    if not out["is_mine"]:
        out.pop("pet_id", None)
    return out


async def attach_photos(reports: list[dict], *, token: str | None = None, admin: bool = False) -> None:
    """Agrega a cada reporte la lista de sus fotos (solo id y estado; nunca la ruta interna)."""
    if not reports:
        return
    ids = ",".join(r["id"] for r in reports)
    params = {"select": "id,report_id,status", "report_id": f"in.({ids})", "order": "created_at"}
    if admin:  # lecturas internas: solo fotos listas
        params["status"] = "eq.ready"
    photos = await supabase.db("GET", "report_photos", token=token, admin=admin, params=params)
    by_report: dict[str, list] = {r["id"]: [] for r in reports}
    for p in photos:
        by_report[p["report_id"]].append({"id": p["id"], "status": p["status"]})
    for r in reports:
        r["photos"] = by_report[r["id"]]


async def get_own_open_report(report_id: UUID | str, user: User) -> dict:
    """Devuelve el reporte si es del usuario y todavía se puede editar (draft o active)."""
    rows = await supabase.db("GET", "reports", token=user.token,
                             params={"select": REPORT_COLS, "id": f"eq.{report_id}"})
    if not rows or rows[0]["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    if rows[0]["status"] not in ("draft", "active"):
        raise HTTPException(status_code=409, detail="Este reporte ya está cerrado")
    return rows[0]


# ---------------------------------------------------------------------------
@router.get("")
async def list_active_reports(
    type: Literal["lost", "found"] | None = None,
    species: str | None = Query(default=None, pattern=r"^[a-z_]{2,30}$"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10_000),
    user: User = Depends(require_user),
):
    """Reportes activos (decisión D1: solo con sesión), del más reciente al más antiguo."""
    if user.is_anonymous:  # los invitados no exploran reportes ajenos (también lo impide RLS)
        raise HTTPException(status_code=403, detail="Crea una cuenta para ver los reportes")
    params = {"select": REPORT_COLS, "status": "eq.active", "order": "published_at.desc",
              "limit": str(limit), "offset": str(offset)}
    if type:
        params["type"] = f"eq.{type}"
    if species:
        params["species"] = f"eq.{species}"
    rows = await supabase.db("GET", "reports", token=user.token, params=params)
    await attach_photos(rows, token=user.token)
    return [present(r, user) for r in rows]


@router.get("/mine")
async def list_my_reports(user: User = Depends(require_user)):
    rows = await supabase.db("GET", "reports", token=user.token, params={
        "select": REPORT_COLS, "user_id": f"eq.{user.id}", "order": "created_at.desc"})
    await attach_photos(rows, token=user.token)
    return [present(r, user) for r in rows]


@router.get("/{report_id}")
async def get_report(report_id: UUID, user: User = Depends(require_user)):
    rows = await supabase.db("GET", "reports", token=user.token,
                             params={"select": REPORT_COLS, "id": f"eq.{report_id}"})
    if not rows:  # no existe, o no es mío y no está activo (RLS)
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    report = rows[0]
    await attach_photos([report], token=user.token)
    out = present(report, user)
    if out["is_mine"]:
        private = await supabase.db("GET", "report_private", token=user.token,
                                    params={"select": PRIVATE_COLS, "report_id": f"eq.{report_id}"})
        out["private"] = private[0] if private else None
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_report(body: ReportCreate, user: User = Depends(require_user)):
    # Invitados (reporte rápido sin cuenta): solo mascotas encontradas y con un contacto.
    # La base de datos vuelve a exigir ambas cosas (migración 4).
    if user.is_anonymous:
        if body.type != "found":
            raise HTTPException(status_code=403, detail="Para reportar una mascota perdida crea una cuenta")
        if not body.contact_phone and not body.contact_email:
            raise HTTPException(status_code=422,
                                detail="Deja un teléfono o un correo para que el dueño pueda contactarte")
    data = body.model_dump(mode="json", exclude_none=True)
    report_fields = {k: data[k] for k in ("type", "pet_id", "species", *DESCRIPTIVE) if k in data}
    report_fields |= {"approx_lat": approx(body.lat), "approx_lng": approx(body.lng)}
    rows = await supabase.db("POST", "reports", token=user.token,
                             params={"select": "id"}, json=report_fields)
    report_id = rows[0]["id"]

    private = {"report_id": report_id, "exact_lat": round(body.lat, 6), "exact_lng": round(body.lng, 6)}
    private |= {k: data[k] for k in PRIVATE if k in data}
    try:
        await supabase.db("POST", "report_private", token=user.token, json=private, return_rows=False)
    except Exception:
        # Sin sus datos privados el reporte queda incompleto: se borra el borrador.
        await supabase.db("DELETE", "reports", admin=True,
                          params={"id": f"eq.{report_id}", "status": "eq.draft"}, return_rows=False)
        raise
    return await get_report(report_id, user)


@router.patch("/{report_id}")
async def update_report(report_id: UUID, body: ReportUpdate, user: User = Depends(require_user)):
    await get_own_open_report(report_id, user)
    changes = body.model_dump(mode="json", exclude_unset=True)

    report_patch = {k: changes[k] for k in DESCRIPTIVE if k in changes}
    private_patch = {k: changes[k] for k in PRIVATE if k in changes}
    if body.lat is not None and body.lng is not None:
        report_patch |= {"approx_lat": approx(body.lat), "approx_lng": approx(body.lng)}
        private_patch |= {"exact_lat": round(body.lat, 6), "exact_lng": round(body.lng, 6)}

    if report_patch:
        await supabase.db("PATCH", "reports", token=user.token,
                          params={"id": f"eq.{report_id}"}, json=report_patch, return_rows=False)
    if private_patch:
        updated = await supabase.db("PATCH", "report_private", token=user.token,
                                    params={"report_id": f"eq.{report_id}"}, json=private_patch)
        if not updated:
            await supabase.db("POST", "report_private", token=user.token,
                              json={"report_id": str(report_id)} | private_patch, return_rows=False)
    return await get_report(report_id, user)


@router.post("/{report_id}/publish")
async def publish_report(report_id: UUID, user: User = Depends(require_user)):
    """draft → active. La función SQL exige al menos una foto lista."""
    await supabase.rpc("publish_report", {"p_report_id": str(report_id)}, token=user.token)
    # Etapa 7: aquí se lanzará en segundo plano el cálculo de embeddings y coincidencias.
    return await get_report(report_id, user)


@router.post("/{report_id}/withdraw")
async def withdraw_report(report_id: UUID, user: User = Depends(require_user)):
    """draft/active → withdrawn (el usuario retira su reporte)."""
    await supabase.rpc("withdraw_report", {"p_report_id": str(report_id)}, token=user.token)
    return await get_report(report_id, user)
