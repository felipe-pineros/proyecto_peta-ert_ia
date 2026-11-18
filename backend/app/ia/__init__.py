"""Módulo de IA intercambiable: convierte una foto en su "huella visual" (embedding).

- El modelo se elige con la variable IA_MODEL (por defecto `dinov2_s`) y se apaga con IA_ENABLED=false.
- Corre con ONNX Runtime en CPU: no necesita PyTorch, GPU ni CUDA.
- Para agregar otro modelo basta con sumarlo a MODELS (archivo, origen y huella SHA-256).

Los pesos no están en git: se descargan con `python -m app.ia.descargar` (o al construir la imagen Docker).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
import threading

from ..config import BACKEND_DIR


@dataclass(frozen=True)
class ModelSpec:
    name: str       # se guarda en photo_embeddings.model_name y matches.model_name
    file: str
    url: str
    sha256: str
    dim: int


_HF = "https://huggingface.co/onnx-community/dinov2-small/resolve/8b1f705a3a7f6f062f6bdd21986c1583d3ef105d/onnx"

# DINOv2 ViT-S/14 (Meta, Apache-2.0), conversión a ONNX de onnx-community. Elegido en la etapa 6
# (evaluacion/resultados.md). La versión fija (commit) y la huella SHA-256 garantizan que siempre
# se use exactamente el mismo archivo que se verificó (evaluacion/verificar_onnx.py).
MODELS: dict[str, ModelSpec] = {
    "dinov2_s": ModelSpec("dinov2_s", "dinov2_s_model.onnx", f"{_HF}/model.onnx",
                          "f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a", 384),
    "dinov2_s_int8": ModelSpec("dinov2_s_int8", "dinov2_s_model_int8.onnx", f"{_HF}/model_int8.onnx",
                               "dfce54a839b491f395c516350ebb4a78f947e9170a6beac0f2bc5638e0f09d61", 384),
}


def model_dir() -> Path:
    return Path(os.getenv("IA_MODEL_DIR", "").strip() or BACKEND_DIR / "modelos")


def selected_spec() -> ModelSpec:
    name = os.getenv("IA_MODEL", "").strip() or "dinov2_s"
    if name not in MODELS:
        raise RuntimeError(f"IA_MODEL={name!r} no existe. Opciones: {', '.join(MODELS)}")
    return MODELS[name]


def enabled() -> bool:
    """La IA está activa si no se apagó con IA_ENABLED=false y el archivo del modelo existe."""
    if os.getenv("IA_ENABLED", "true").strip().lower() in ("0", "false", "no"):
        return False
    return (model_dir() / selected_spec().file).is_file()


_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load():
    from .dinov2_onnx import Dinov2Onnx

    spec = selected_spec()
    return Dinov2Onnx(model_dir() / spec.file, spec.name)


def get_embedder():
    """Carga el modelo una sola vez (la primera vez que se usa) y lo reutiliza."""
    with _lock:
        return _load()
