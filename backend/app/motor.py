"""Motor de coincidencias (etapa 7).

Cuando un reporte se publica (o recibe una foto estando publicado), en segundo plano:
  1. calcula la huella visual de sus fotos que aún no la tienen (módulo `ia`);
  2. pide a la base los candidatos que pasan los filtros (migración 5, find_match_candidates);
  3. calcula el puntaje y guarda las POSIBLES coincidencias sin duplicados (save_match_suggestion).

Puntaje (docs/arquitectura.md §4):
    visual = mejor similitud coseno entre las fotos de ambos reportes
    geo    = exp(−distancia_km / 5)
    total  = 0,75 · visual + 0,25 · geo
Solo se sugiere si visual ≥ MATCH_MIN_SIMILARITY (0,49 por defecto). Con las fotos de la etapa 6
ese umbral dejó pasar ~5 % de pares de animales distintos y encontró ~79 % de los mismos animales.
Es PROVISIONAL: salió de solo 39 pares del mismo animal; se recalibra con más fotos.
El sistema nunca afirma que es el mismo animal: son sugerencias para que las personas decidan.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os

from . import ia, supabase


log = logging.getLogger("petalert.motor")

W_VISUAL, W_GEO = 0.75, 0.25
GEO_SCALE_KM = 5.0
MAX_DISTANCE_KM = 50.0

# Un cálculo a la vez: así la memoria no se dispara si llegan varios reportes juntos.
_lock = asyncio.Lock()


def min_similarity() -> float:
    try:
        value = float(os.getenv("MATCH_MIN_SIMILARITY", "0.49"))
    except ValueError:
        value = 0.49
    return min(max(value, 0.0), 1.0)


def score(similarity: float, distance_km: float) -> tuple[float, float]:
    """Devuelve (visual, total), ambos entre 0 y 1."""
    visual = min(max(similarity, 0.0), 1.0)
    geo = math.exp(-max(distance_km, 0.0) / GEO_SCALE_KM)
    return visual, min(max(W_VISUAL * visual + W_GEO * geo, 0.0), 1.0)


async def embed_missing(report_id: str) -> int:
    """Calcula y guarda las huellas que faltan. Devuelve cuántas calculó."""
    spec = ia.selected_spec()
    photos = await supabase.db("GET", "report_photos", admin=True, params={
        "select": "id,storage_path", "report_id": f"eq.{report_id}", "status": "eq.ready"})
    if not photos:
        return 0
    ids = ",".join(p["id"] for p in photos)
    done = await supabase.db("GET", "photo_embeddings", admin=True, params={
        "select": "photo_id", "model_name": f"eq.{spec.name}", "photo_id": f"in.({ids})"})
    done_ids = {row["photo_id"] for row in done}
    embedder = ia.get_embedder()
    count = 0
    for photo in photos:
        if photo["id"] in done_ids:
            continue
        try:
            data = await supabase.download_photo(photo["storage_path"])
        except Exception as exc:  # la borraron mientras tanto: se salta y se sigue con las demás
            log.info("Foto %s no disponible, se omite: %s", photo["id"], type(exc).__name__)
            continue
        vector = await asyncio.to_thread(embedder.embed_bytes, data)
        try:
            await supabase.db("POST", "photo_embeddings", admin=True, return_rows=False, json={
                "photo_id": photo["id"], "model_name": spec.name,
                "embedding": "[" + ",".join(f"{x:.7f}" for x in vector) + "]"})
            count += 1
        except Exception as exc:  # p. ej. otra tarea la guardó primero (UNIQUE) o la foto se borró
            log.info("No se guardó la huella de la foto %s: %s", photo["id"], exc)
    return count


async def process_report(report_id: str) -> list[dict]:
    """Calcula las coincidencias de un reporte activo. Devuelve las sugerencias guardadas."""
    if not ia.enabled():
        return []
    async with _lock:
        spec = ia.selected_spec()
        await embed_missing(report_id)
        candidates = await supabase.db("POST", "rpc/find_match_candidates", admin=True, json={
            "p_report_id": report_id, "p_model": spec.name, "p_max_km": MAX_DISTANCE_KM}) or []
        threshold = min_similarity()
        saved = []
        for c in candidates:
            # Las huellas de la otra parte pueden faltar si se publicó con la IA apagada:
            # en ese caso find_match_candidates simplemente no la devuelve (se cubre con sweep()).
            if c["similarity"] is None or c["similarity"] < threshold:
                continue
            visual, total = score(c["similarity"], c["distance_km"])
            rows = await supabase.db("POST", "rpc/save_match_suggestion", admin=True, json={
                "p_lost_report_id": c["lost_report_id"], "p_found_report_id": c["found_report_id"],
                "p_model": spec.name, "p_visual_score": round(visual, 4),
                "p_distance_km": round(c["distance_km"], 2), "p_total_score": round(total, 4)}) or []
            for row in rows:
                saved.append(row | {"lost_report_id": c["lost_report_id"],
                                    "found_report_id": c["found_report_id"],
                                    "visual_score": visual, "total_score": total})
                # Etapa 8: aviso para las dos personas. Se intenta con toda sugerencia vigente
                # (no solo las nuevas) para reponer avisos que hayan faltado; la base impide duplicados.
                if row["status"] == "suggested":
                    try:
                        await notify_new_match(row["match_id"], c["lost_report_id"], c["found_report_id"])
                    except Exception:
                        log.exception("No se pudo crear el aviso de la coincidencia %s", row["match_id"])
        return saved


async def notify_new_match(match_id: str, lost_report_id: str, found_report_id: str) -> None:
    """Crea el aviso 'new_match' para el dueño de cada reporte. Nunca duplica (UNIQUE en la tabla)."""
    owners = await supabase.db("GET", "reports", admin=True, params={
        "select": "user_id", "id": f"in.({lost_report_id},{found_report_id})"})
    rows = [{"user_id": user_id, "match_id": match_id, "kind": "new_match"}
            for user_id in {o["user_id"] for o in owners}]
    if rows:
        await supabase.db("POST", "notifications", admin=True, return_rows=False,
                          ignore_duplicates=True, params={"on_conflict": "user_id,match_id,kind"},
                          json=rows)


async def notify_pending() -> int:
    """Repone los avisos de coincidencias sugeridas que se guardaron antes de la etapa 8."""
    matches = await supabase.db("GET", "matches", admin=True, params={
        "select": "id,lost_report_id,found_report_id", "status": "eq.suggested", "limit": "1000"})
    for m in matches:
        try:
            await notify_new_match(m["id"], m["lost_report_id"], m["found_report_id"])
        except Exception:
            log.exception("No se pudo reponer el aviso de la coincidencia %s", m["id"])
    return len(matches)


async def run_in_background(report_id: str) -> None:
    """Para BackgroundTasks: nunca deja que un error de la IA afecte al usuario."""
    try:
        saved = await process_report(str(report_id))
        if saved:
            log.info("Reporte %s: %d posibles coincidencias", report_id, len(saved))
    except Exception:
        log.exception("El motor falló con el reporte %s", report_id)


async def sweep() -> int:
    """Al encender: procesa reportes activos con fotos sin huella (p. ej. tras un reinicio)."""
    if not ia.enabled():
        return 0
    try:
        await notify_pending()
    except Exception:
        log.exception("No se pudieron reponer los avisos pendientes")
    spec = ia.selected_spec()
    active = await supabase.db("GET", "reports", admin=True, params={
        "select": "id", "status": "eq.active", "limit": "1000"})
    pending = 0
    for report in active:
        photos = await supabase.db("GET", "report_photos", admin=True, params={
            "select": "id", "report_id": f"eq.{report['id']}", "status": "eq.ready"})
        if not photos:
            continue
        ids = ",".join(p["id"] for p in photos)
        done = await supabase.db("GET", "photo_embeddings", admin=True, params={
            "select": "photo_id", "model_name": f"eq.{spec.name}", "photo_id": f"in.({ids})"})
        if len(done) < len(photos):
            await run_in_background(report["id"])
            pending += 1
    return pending
