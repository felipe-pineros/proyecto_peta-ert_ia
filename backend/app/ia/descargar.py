"""Descarga el modelo elegido y comprueba su huella SHA-256.

Uso (desde la carpeta backend/):
    .\\backend\\.venv\\Scripts\\python.exe -m app.ia.descargar            # el de IA_MODEL (dinov2_s)
    .\\backend\\.venv\\Scripts\\python.exe -m app.ia.descargar dinov2_s_int8
"""
import hashlib
import sys

import httpx

from . import MODELS, model_dir, selected_spec


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(name: str | None = None) -> None:
    spec = MODELS[name] if name else selected_spec()
    target = model_dir() / spec.file
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and sha256(target) == spec.sha256:
        print(f"{spec.name}: ya está descargado y verificado ({target})")
        return
    tmp = target.with_suffix(".part")
    with httpx.stream("GET", spec.url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in response.iter_bytes(1 << 20):
                f.write(chunk)
    if sha256(tmp) != spec.sha256:
        tmp.unlink()
        raise SystemExit(f"{spec.name}: la huella SHA-256 no coincide; descarga descartada")
    tmp.replace(target)
    print(f"{spec.name}: descargado y verificado ({target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    download(sys.argv[1] if len(sys.argv) > 1 else None)
