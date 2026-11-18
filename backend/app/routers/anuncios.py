"""Leer un anuncio de redes con Gemini: texto (POST /api/ads/extract) o captura (/extract-image). Ver app/anuncios.py."""
from collections import defaultdict, deque
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .. import anuncios
from ..images import read_and_normalize_image
from ..auth import User, require_user


router = APIRouter(prefix="/api/ads", tags=["anuncios"])

MAX_PER_HOUR = 10  # por persona: cuida la cuota gratuita de Gemini y frena abusos
_recent: dict[str, deque] = defaultdict(deque)


class AdText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=15, max_length=3000)


def _check_rate(user_id: str) -> None:
    now = time.monotonic()
    calls = _recent[user_id]
    while calls and now - calls[0] > 3600:
        calls.popleft()
    if len(calls) >= MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Ya leíste varios anuncios. Intenta de nuevo en una hora.")
    calls.append(now)


@router.post("/extract")
async def extract_ad(body: AdText, user: User = Depends(require_user)):
    """Devuelve los datos que entendió la IA. No crea ni publica nada: la persona los revisa."""
    _check_rate(user.id)
    data, removed = await anuncios.extract(text=body.text)
    return data.model_dump(mode="json") | {"contact_data_removed": removed}


@router.post("/extract-image")
async def extract_ad_image(file: UploadFile = File(...), user: User = Depends(require_user)):
    """Igual, pero con una CAPTURA del anuncio (decisión de Daniela, 2026-11-18).

    La imagen se valida y se vuelve a guardar como JPEG sin metadatos (images.py) antes de
    enviarla; no se guarda en ningún lado. Comparte el límite de 10 lecturas por hora.
    """
    clean = await read_and_normalize_image(file)   # valida antes de gastar el cupo
    _check_rate(user.id)
    data, removed = await anuncios.extract(image_jpeg=clean.data)
    return data.model_dump(mode="json") | {"contact_data_removed": removed}
