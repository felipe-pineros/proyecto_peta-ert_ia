"""Fotos de los reportes.

El navegador nunca toca Storage directamente (el bucket es privado):
- subir: el backend valida, limpia y guarda la foto con la secret key;
- ver: el backend comprueba que el usuario puede verla y entrega una URL firmada
  que caduca en pocos minutos.
"""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from .. import supabase
from ..auth import User, require_user
from ..images import read_and_normalize_image
from .reportes import get_own_open_report


router = APIRouter(prefix="/api", tags=["fotos"])


@router.post("/reports/{report_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(report_id: UUID, file: UploadFile = File(...), user: User = Depends(require_user)):
    await get_own_open_report(report_id, user)
    image = await read_and_normalize_image(file)  # valida antes de reservar espacio

    photo_id = str(uuid4())
    path = f"{user.id}/{report_id}/{photo_id}.jpg"
    # 1) Reservar la fila: aquí la base aplica el límite de 5 fotos (D4).
    await supabase.db("POST", "report_photos", admin=True, return_rows=False, json={
        "id": photo_id, "report_id": str(report_id), "user_id": user.id,
        "storage_path": path, "status": "pending",
    })
    # 2) Guardar el archivo; si falla, se libera la fila para no ocupar un cupo.
    try:
        await supabase.upload_photo(path, image.data)
    except Exception:
        await supabase.db("DELETE", "report_photos", admin=True,
                          params={"id": f"eq.{photo_id}"}, return_rows=False)
        raise
    # 3) Marcarla como lista.
    await supabase.db("PATCH", "report_photos", admin=True, params={"id": f"eq.{photo_id}"},
                      return_rows=False, json={
                          "status": "ready", "width": image.width, "height": image.height,
                          "byte_size": len(image.data)})
    # Etapa 7: si el reporte ya está activo, aquí se recalcularán sus coincidencias.
    return {"id": photo_id, "report_id": str(report_id), "status": "ready",
            "width": image.width, "height": image.height}


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_photo(photo_id: UUID, user: User = Depends(require_user)):
    rows = await supabase.db("GET", "report_photos", admin=True, params={
        "select": "id,report_id,user_id,storage_path,status", "id": f"eq.{photo_id}"})
    if not rows or rows[0]["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    photo = rows[0]
    report = await get_own_open_report(photo["report_id"], user)
    if report["status"] == "active" and photo["status"] == "ready":
        ready = await supabase.db("GET", "report_photos", admin=True, params={
            "select": "id", "report_id": f"eq.{photo['report_id']}", "status": "eq.ready"})
        if len(ready) <= 1:
            raise HTTPException(status_code=409,
                                detail="Un reporte publicado debe conservar al menos una foto")
    await supabase.db("DELETE", "report_photos", admin=True,
                      params={"id": f"eq.{photo_id}"}, return_rows=False)
    await supabase.delete_photos([photo["storage_path"]])


@router.get("/photos/{photo_id}/url")
async def photo_url(photo_id: UUID, user: User = Depends(require_user)):
    """URL temporal para ver una foto, si el usuario tiene derecho a verla."""
    # a) RLS: mis fotos, o fotos listas de reportes activos.
    visible = await supabase.db("GET", "report_photos", token=user.token, params={
        "select": "id,status", "id": f"eq.{photo_id}", "status": "eq.ready"})
    rows = await supabase.db("GET", "report_photos", admin=True, params={
        "select": "report_id,storage_path,status", "id": f"eq.{photo_id}"})
    if not rows or rows[0]["status"] != "ready":
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    if not visible:
        # b) También puede verla la otra persona de una coincidencia (aunque el reporte
        #    ya no esté activo, p. ej. tras confirmarla). RLS de matches solo devuelve
        #    coincidencias en las que el usuario participa.
        related = await supabase.db("GET", "matches", token=user.token, params={
            "select": "id", "status": "neq.discarded", "limit": "1",
            "or": f"(lost_report_id.eq.{rows[0]['report_id']},found_report_id.eq.{rows[0]['report_id']})"})
        if not related:
            raise HTTPException(status_code=404, detail="Foto no encontrada")
    url, expires_in = await supabase.signed_photo_url(rows[0]["storage_path"])
    return {"url": url, "expires_in": expires_in}
