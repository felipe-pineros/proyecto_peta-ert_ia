"""Buscar en el mapa un lugar escrito ("Parque de Chapinero, Bogotá") — decisión de Daniela, 2026-11-18.

Sirve para que, al leer un anuncio de redes, el marcador del mapa se ponga solo; la persona
lo revisa y lo mueve si hace falta. Usa Nominatim de OpenStreetMap (gratis, el mismo proyecto
de los mapas). Su política de uso pide:
  - máximo 1 consulta por segundo  → un candado global + pausa;
  - identificar la aplicación     → User-Agent "PetAlert-IA/1.0" (+ la dirección pública si existe);
  - no repetir consultas           → caché en memoria.
Solo se envía el NOMBRE DEL LUGAR, nunca datos de la persona. Búsqueda limitada a Colombia.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import logging
import re
import time

from fastapi import HTTPException
import httpx

from . import supabase
from .config import get_settings


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
COUNTRY = "co"
CACHE_SIZE = 500
log = logging.getLogger(__name__)

_lock = asyncio.Lock()
_last_call = 0.0
_cache: OrderedDict[str, dict | None] = OrderedDict()


def _user_agent() -> str:
    site = get_settings().public_site_url
    return f"PetAlert-IA/1.0 (+{site})" if site else "PetAlert-IA/1.0"


def _key(query: str) -> str:
    return " ".join(query.lower().split())


_STREET = r"(?:avenida calle|avenida carrera|av\.? calle|av\.? carrera|calle|cl\.?|carrera|cra\.?|kr\.?|cr\.?|diagonal|dg\.?|transversal|tv\.?)"
# "calle 72 con carrera 11", "cl 72 x cra 11", "calle 72 y 11" → "calle 72 #11" (así sí lo entiende OpenStreetMap)
_CROSSING = re.compile(rf"\b({_STREET})\s*(\d+\s*[a-z]?)\s*(?:con|x|y|&|/)\s*(?:{_STREET})?\s*(\d+\s*[a-z]?)\b", re.IGNORECASE)
_FILLER = re.compile(r"\b(?:barrio|sector|por el|por la|cerca del?|cerca de la|frente al?|alrededores de)\b", re.IGNORECASE)


def candidates(query: str) -> list[str]:
    """Formas de buscar el lugar, de la más precisa a la más general (máx. 3)."""
    text = _CROSSING.sub(lambda m: f"{m.group(1)} {m.group(2).replace(' ', '')} #{m.group(3).replace(' ', '')}", query)
    text = " ".join(_FILLER.sub(" ", text).split()).strip(" ,.")
    out = [text] if text else []
    parts = [p.strip() for p in text.split(",") if p.strip()]
    # Si no aparece, se prueba quitando lo más específico: "Parque X, Chapinero, Bogotá" → "Chapinero, Bogotá".
    for i in range(1, len(parts)):
        out.append(", ".join(parts[i:]))
    seen, unique = set(), []
    for c in out:
        if len(c) >= 3 and _key(c) not in seen:
            seen.add(_key(c))
            unique.append(c)
    return unique[:3]


async def geocode(query: str) -> dict | None:
    """Devuelve {lat, lng, label, approximate} del lugar o None si no se encontró.

    approximate=True cuando no se encontró el lugar exacto y se usó algo más general (barrio/ciudad).
    """
    options = candidates(query)
    for i, option in enumerate(options):
        place = await _search(option)
        if place:
            return place | {"approximate": i > 0}
    return None


async def _search(query: str) -> dict | None:
    global _last_call
    key = _key(query)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    async with _lock:
        if key in _cache:  # otra petición lo buscó mientras esperábamos
            return _cache[key]
        wait = 1.05 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            response = await supabase.client().get(NOMINATIM_URL, timeout=10, params={
                "q": query, "format": "jsonv2", "limit": "1", "countrycodes": COUNTRY,
                "accept-language": "es"}, headers={"User-Agent": _user_agent()})
        except httpx.HTTPError as exc:
            log.warning("Nominatim sin conexión: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="No se pudo buscar el lugar en el mapa") from exc
        finally:
            _last_call = time.monotonic()
    if response.status_code != 200:
        log.warning("Nominatim respondió %d", response.status_code)
        raise HTTPException(status_code=503, detail="No se pudo buscar el lugar en el mapa")
    try:
        rows = response.json()
        result = None
        if rows:
            lat, lng = float(rows[0]["lat"]), float(rows[0]["lon"])
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                # Nombre corto: las 3 primeras partes ("Parque X, Chapinero, Bogotá").
                label = ", ".join(str(rows[0].get("display_name", "")).split(", ")[:3])[:160]
                result = {"lat": round(lat, 6), "lng": round(lng, 6), "label": label}
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise HTTPException(status_code=502, detail="No se pudo leer la respuesta del mapa") from exc
    _cache[key] = result
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result
