"""Etapa 6 · Evaluación de modelos de IA para reidentificar mascotas (¿es el mismo animal?).

Uso (PowerShell, desde la raíz del proyecto):
    .\\backend\\.venv\\Scripts\\python.exe evaluacion\\evaluar.py verificar
    .\\backend\\.venv\\Scripts\\python.exe evaluacion\\evaluar.py modelos
    .\\backend\\.venv\\Scripts\\python.exe evaluacion\\evaluar.py evaluar --modelo dinov2_s
    .\\backend\\.venv\\Scripts\\python.exe evaluacion\\evaluar.py evaluar --modelo dinov2_s --recorte

Fotos en datos_evaluacion/ (fuera de git, por privacidad):
    datos_evaluacion/perros/<nombre_del_animal>/<fotos>
    datos_evaluacion/gatos/<nombre_del_animal>/<fotos>

Los resultados (solo números agregados, sin fotos ni nombres) se guardan en
evaluacion/resultados/<modelo>[_recorte].json y se resumen en resultados.md.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import time

from PIL import Image, ImageOps, UnidentifiedImageError

from metricas import evaluate


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "datos_evaluacion"
RESULTS_DIR = HERE / "resultados"
SPECIES_DIRS = {"perros": "dog", "gatos": "cat"}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_SIDE = 160

# Modelos candidatos (verificados el 2026-11-12: tamaño y licencia en Hugging Face).
MODELS = {
    "dinov2_s": {"timm": "vit_small_patch14_dinov2.lvd142m", "mb": 88, "licencia": "Apache-2.0",
                 "nota": "DINOv2 ViT-S/14: liviano, propósito general"},
    "dinov2_b": {"timm": "vit_base_patch14_dinov2.lvd142m", "mb": 346, "licencia": "Apache-2.0",
                 "nota": "DINOv2 ViT-B/14: más grande y lento"},
    "megadescriptor_t": {"timm": "hf-hub:BVRA/MegaDescriptor-T-224", "mb": 204, "licencia": "CC-BY-NC-4.0",
                         "nota": "Entrenado para reidentificar animales; solo uso no comercial"},
    "megadescriptor_b": {"timm": "hf-hub:BVRA/MegaDescriptor-B-224", "mb": 473, "licencia": "CC-BY-NC-4.0",
                         "nota": "Versión grande de MegaDescriptor; solo uso no comercial"},
}


@dataclass
class Photo:
    path: Path
    animal: str     # etiqueta: especie/nombre (dos perros con el mismo nombre no se mezclan)
    species: str    # dog | cat


# ---------------------------------------------------------------------------
# 1. Revisar las fotos (solo necesita Pillow)
# ---------------------------------------------------------------------------
def scan(data_dir: Path) -> tuple[list[Photo], list[str]]:
    photos, problems = [], []
    if not data_dir.is_dir():
        return [], [f"No existe la carpeta {data_dir}"]
    for folder in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        species = SPECIES_DIRS.get(folder.name.lower())
        if not species:
            problems.append(f"Carpeta '{folder.name}' ignorada: usa 'perros' o 'gatos'")
            continue
        for animal_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
            for f in sorted(animal_dir.iterdir()):
                if f.suffix.lower() not in EXTENSIONS:
                    if f.is_file():
                        problems.append(f"Ignorado (formato no soportado): {f.relative_to(data_dir)}")
                    continue
                try:
                    with Image.open(f) as im:
                        w, h = ImageOps.exif_transpose(im).size
                except (UnidentifiedImageError, OSError):
                    problems.append(f"No se pudo abrir: {f.relative_to(data_dir)}")
                    continue
                if min(w, h) < MIN_SIDE:
                    problems.append(f"Muy pequeña ({w}x{h}): {f.relative_to(data_dir)}")
                    continue
                photos.append(Photo(f, f"{species}/{animal_dir.name}", species))
        loose = [f.name for f in folder.iterdir() if f.is_file()]
        if loose:
            problems.append(f"Fotos sueltas en '{folder.name}' (deben ir dentro de una carpeta por animal): "
                            f"{len(loose)} archivo(s)")
    return photos, problems


def cmd_verificar(_args) -> int:
    photos, problems = scan(DATA_DIR)
    by_animal = defaultdict(int)
    for p in photos:
        by_animal[p.animal] += 1
    print(f"Carpeta: {DATA_DIR}")
    for species, name in (("dog", "Perros"), ("cat", "Gatos")):
        animals = {a: n for a, n in by_animal.items() if a.startswith(species + "/")}
        useful = sum(1 for n in animals.values() if n >= 2)
        print(f"  {name}: {len(animals)} animales, {sum(animals.values())} fotos "
              f"({useful} animales con 2+ fotos, los que sirven como consulta)")
    singles = [a for a, n in by_animal.items() if n == 1]
    if singles:
        print(f"  Aviso: {len(singles)} animal(es) con 1 sola foto (solo sirven como 'distractores').")
    for msg in problems:
        print("  - " + msg)
    total_useful = sum(1 for n in by_animal.values() if n >= 2)
    if total_useful < 10:
        print("\nTodavía hay pocos datos: se recomiendan al menos 15 animales con 2 a 5 fotos cada uno.")
    else:
        print("\nListo para evaluar.")
    return 0 if photos else 1


def cmd_modelos(_args) -> int:
    for key, m in MODELS.items():
        print(f"{key:18} {m['mb']:>4} MB  {m['licencia']:13} {m['nota']}")
    return 0


# ---------------------------------------------------------------------------
# 2. Evaluar un modelo (necesita evaluacion/requirements-ia.txt)
# ---------------------------------------------------------------------------
def load_model(key: str):
    import timm
    import torch

    spec = MODELS[key]
    kwargs = {"pretrained": True, "num_classes": 0}
    if spec["timm"].startswith("vit_") and "dinov2" in spec["timm"]:
        kwargs["img_size"] = 224  # DINOv2 trabaja a 518 px por defecto; 224 es ~5 veces más rápido en CPU
    model = timm.create_model(spec["timm"], **kwargs).eval()
    config = timm.data.resolve_data_config(model=model)
    if "img_size" in kwargs:  # la preparación de la imagen debe usar el mismo tamaño que el modelo
        config["input_size"] = (3, kwargs["img_size"], kwargs["img_size"])
    transform = timm.data.create_transform(**config, is_training=False)
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    return model, transform


class Cropper:
    """Recorta al perro o gato con un detector ligero de torchvision (COCO: 17 = gato, 18 = perro)."""
    LABELS = {"cat": 17, "dog": 18}

    def __init__(self):
        from torchvision.models.detection import (FasterRCNN_MobileNet_V3_Large_FPN_Weights,
                                                  fasterrcnn_mobilenet_v3_large_fpn)
        weights = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1
        self.model = fasterrcnn_mobilenet_v3_large_fpn(weights=weights, box_score_thresh=0.3).eval()
        self.preprocess = weights.transforms()
        self.found = 0
        self.total = 0

    def __call__(self, image: Image.Image, species: str) -> Image.Image:
        import torch

        self.total += 1
        with torch.inference_mode():
            out = self.model([self.preprocess(image)])[0]
        wanted = [i for i, label in enumerate(out["labels"].tolist())
                  if label == self.LABELS[species]]
        if not wanted:
            return image  # sin detección: se usa la foto completa
        self.found += 1
        best = max(wanted, key=lambda i: float(out["scores"][i]))
        x1, y1, x2, y2 = out["boxes"][best].tolist()
        pad_x, pad_y = (x2 - x1) * 0.1, (y2 - y1) * 0.1
        return image.crop((max(0, x1 - pad_x), max(0, y1 - pad_y),
                           min(image.width, x2 + pad_x), min(image.height, y2 + pad_y)))


def peak_memory_mb() -> float | None:
    try:
        import psutil
        info = psutil.Process().memory_info()
        return round(getattr(info, "peak_wset", info.rss) / 1e6, 1)  # peak_wset: pico en Windows
    except ImportError:
        return None


def cmd_evaluar(args) -> int:
    try:
        import torch
    except ImportError:
        print("Falta instalar las dependencias de IA:\n"
              "  .\\backend\\.venv\\Scripts\\python.exe -m pip install -r evaluacion\\requirements-ia.txt")
        return 1
    photos, problems = scan(DATA_DIR)
    if not photos:
        print("No hay fotos. Ejecuta primero: evaluar.py verificar")
        return 1
    for msg in problems:
        print("  - " + msg)

    print(f"Cargando {args.modelo} (la primera vez se descarga)...")
    t0 = time.perf_counter()
    model, transform = load_model(args.modelo)
    cropper = Cropper() if args.recorte else None
    load_s = time.perf_counter() - t0

    embeddings, times = [], []
    with torch.inference_mode():
        for n, p in enumerate(photos, 1):
            with Image.open(p.path) as im:
                image = ImageOps.exif_transpose(im).convert("RGB")
            start = time.perf_counter()
            if cropper:
                image = cropper(image, p.species)
            vector = model(transform(image).unsqueeze(0))[0]
            times.append(time.perf_counter() - start)
            embeddings.append(vector.tolist())
            print(f"\r  {n}/{len(photos)} fotos", end="", flush=True)
    print()

    result = evaluate(embeddings, [p.animal for p in photos], [p.species for p in photos])
    times_sorted = sorted(times[1:] or times)  # la primera foto incluye el "calentamiento"
    result |= {
        "modelo": args.modelo, "timm": MODELS[args.modelo]["timm"], "licencia": MODELS[args.modelo]["licencia"],
        "recorte": bool(cropper),
        "recorte_detecciones": f"{cropper.found}/{cropper.total}" if cropper else None,
        "datos": {"fotos": len(photos), "animales": len({p.animal for p in photos}),
                  "perros": len({p.animal for p in photos if p.species == 'dog'}),
                  "gatos": len({p.animal for p in photos if p.species == 'cat'})},
        "rendimiento": {"carga_s": round(load_s, 1),
                        "ms_por_foto_mediana": round(1000 * times_sorted[len(times_sorted) // 2], 1),
                        "dimension_embedding": len(embeddings[0]), "memoria_pico_mb": peak_memory_mb()},
        "equipo": {"cpu": platform.processor(), "nucleos": os.cpu_count(), "python": platform.python_version(),
                   "torch": torch.__version__},
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = args.modelo + ("_recorte" if cropper else "")
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary()
    print_result(result)
    print(f"\nGuardado en {RESULTS_DIR / (name + '.json')} y resumen en resultados.md")
    return 0


def pct(value) -> str:
    return "—" if value is None else f"{100 * value:.1f} %"


def print_result(r: dict) -> None:
    rk, pr, rd = r["ranking"], r["pares"], r["rendimiento"]
    print(f"\n{r['modelo']}{' + recorte' if r['recorte'] else ''} · {r['datos']['fotos']} fotos, "
          f"{r['datos']['animales']} animales ({rk.get('consultas', 0)} consultas)")
    print(f"  Recall@1 {pct(rk.get('recall@1'))} · Recall@5 {pct(rk.get('recall@5'))} · mAP {pct(rk.get('mAP'))}")
    fpr5 = pr["fpr_5%"] or {}
    print(f"  AUC {pct(pr['auc'])} · con 5 % de falsos positivos detecta {pct(fpr5.get('tpr'))}")
    print(f"  {rd['ms_por_foto_mediana']} ms por foto · memoria pico {rd['memoria_pico_mb']} MB")
    if r["recorte"]:
        print(f"  El detector encontró al animal en {r['recorte_detecciones']} fotos (en las demás se usó la foto completa)")


def write_summary() -> None:
    rows = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        rk, pr, rd = r["ranking"], r["pares"], r["rendimiento"]
        fpr1, fpr5 = pr["fpr_1%"] or {}, pr["fpr_5%"] or {}
        rows.append(f"| {r['modelo']}{' + recorte' if r['recorte'] else ''} | {r['datos']['fotos']} / "
                    f"{r['datos']['animales']} | {pct(rk.get('recall@1'))} | {pct(rk.get('recall@5'))} | "
                    f"{pct(rk.get('mAP'))} | {pct(pr['auc'])} | {pct(fpr1.get('tpr'))} | {pct(fpr5.get('tpr'))} | "
                    f"{rd['ms_por_foto_mediana']} | {rd['memoria_pico_mb']} | {r['licencia']} | {r['fecha'][:10]} |")
    (RESULTS_DIR.parent / "resultados.md").write_text(
        "# Resultados de la evaluación (etapa 6)\n\n"
        "Generado por `evaluar.py`. Solo números medidos con las fotos de `datos_evaluacion/`.\n\n"
        "| Modelo | Fotos / animales | Recall@1 | Recall@5 | mAP | AUC | Detecta con 1 % FP | Detecta con 5 % FP "
        "| ms/foto | Memoria MB | Licencia | Fecha |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    global DATA_DIR, RESULTS_DIR
    parser = argparse.ArgumentParser(description="Evaluación de modelos de reidentificación de mascotas")
    parser.add_argument("--datos", type=Path, default=DATA_DIR, help="carpeta de fotos (por defecto datos_evaluacion/)")
    parser.add_argument("--resultados", type=Path, default=RESULTS_DIR, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verificar", help="revisar las fotos de datos_evaluacion/")
    sub.add_parser("modelos", help="listar los modelos candidatos")
    ev = sub.add_parser("evaluar", help="medir un modelo")
    ev.add_argument("--modelo", choices=sorted(MODELS), default="dinov2_s")
    ev.add_argument("--recorte", action="store_true", help="recortar al animal antes de comparar")
    args = parser.parse_args()
    DATA_DIR, RESULTS_DIR = args.datos.resolve(), args.resultados.resolve()
    return {"verificar": cmd_verificar, "modelos": cmd_modelos, "evaluar": cmd_evaluar}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
