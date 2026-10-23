import asyncio
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException, UploadFile


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 6000
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


async def read_and_normalize_image(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="La imagen supera el límite de 10 MiB")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise HTTPException(status_code=422, detail="El archivo está vacío")
    worker = asyncio.create_task(asyncio.to_thread(_normalize_image, raw, (upload.content_type or "").lower()))
    try:
        # Cancelling an asyncio.to_thread await does not stop Pillow's worker thread.
        # Keep the request (and its middleware concurrency slot) alive until that thread ends.
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            await worker
        except Exception:
            pass
        raise


def _normalize_image(raw: bytes, declared_content_type: str) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as probe:
                detected_format = probe.format
                probe.verify()
            if detected_format not in ALLOWED_FORMATS:
                raise HTTPException(status_code=415, detail="Usa una imagen JPEG, PNG o WebP")
            if declared_content_type and declared_content_type != ALLOWED_FORMATS[detected_format]:
                raise HTTPException(status_code=415, detail="El tipo declarado no coincide con el contenido")

            with Image.open(BytesIO(raw)) as source:
                if source.width > MAX_IMAGE_DIMENSION or source.height > MAX_IMAGE_DIMENSION:
                    raise HTTPException(status_code=413, detail="La imagen excede 6000 píxeles por lado")
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise HTTPException(status_code=413, detail="La imagen excede 16 megapíxeles")
                image = ImageOps.exif_transpose(source)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
                output = BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(status_code=422, detail="El archivo no es una imagen válida") from exc
    normalized = output.getvalue()
    if not normalized or len(normalized) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="La imagen procesada supera el límite permitido")
    return normalized
