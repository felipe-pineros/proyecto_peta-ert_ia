"""Comprueba que el modelo ONNX del backend da las MISMAS huellas que el modelo evaluado (timm).

Si la similitud entre ambas huellas es ~1 y las métricas no bajan, el backend usa
exactamente lo que se midió en la etapa 6. Necesita requirements-ia.txt (timm/torch)
y los archivos ONNX en backend/modelos/ (python -m app.ia.descargar).

Uso:  .\\backend\\.venv\\Scripts\\python.exe evaluacion\\verificar_onnx.py
"""
from pathlib import Path
import statistics
import sys
import time

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluacion"))

from app.ia import MODELS, model_dir  # noqa: E402
from app.ia.dinov2_onnx import Dinov2Onnx  # noqa: E402
from evaluar import DATA_DIR, load_model, scan  # noqa: E402
from metricas import evaluate  # noqa: E402


def main() -> int:
    import torch

    photos, _ = scan(DATA_DIR)
    if not photos:
        print("No hay fotos en datos_evaluacion/")
        return 1
    images = []
    for p in photos:
        with Image.open(p.path) as im:
            images.append(ImageOps.exif_transpose(im).convert("RGB"))
    labels, species = [p.animal for p in photos], [p.species for p in photos]

    model, transform = load_model("dinov2_s")
    with torch.inference_mode():
        reference = [torch.nn.functional.normalize(model(transform(im).unsqueeze(0))[0], dim=0).tolist()
                     for im in images]
    ref = evaluate(reference, labels, species)
    print(f"timm (referencia): Recall@1 {ref['ranking']['recall@1']:.1%} · AUC {ref['pares']['auc']:.1%}")

    ok = True
    for spec in MODELS.values():
        path = model_dir() / spec.file
        if not path.is_file():
            print(f"{spec.name}: falta {path} (python -m app.ia.descargar {spec.name})")
            continue
        engine = Dinov2Onnx(path, spec.name)
        vectors, times = [], []
        for im in images:
            t = time.perf_counter()
            vectors.append(engine.embed_image(im))
            times.append(time.perf_counter() - t)
        cos = [sum(a * b for a, b in zip(u, v)) for u, v in zip(reference, vectors)]
        r = evaluate(vectors, labels, species)
        print(f"{spec.name}: similitud con timm min {min(cos):.4f} / media {statistics.mean(cos):.4f} · "
              f"Recall@1 {r['ranking']['recall@1']:.1%} · Recall@5 {r['ranking']['recall@5']:.1%} · "
              f"AUC {r['pares']['auc']:.1%} · umbral 5 % FP {r['pares']['fpr_5%']['umbral']:.3f} · "
              f"umbral 1 % FP {r['pares']['fpr_1%']['umbral']:.3f} · "
              f"{1000 * statistics.median(times[1:]):.0f} ms/foto")
        if spec.name == "dinov2_s" and min(cos) < 0.99:
            ok = False
    print("RESULTADO:", "OK, el ONNX reproduce el modelo evaluado" if ok else "FALLA: las huellas no coinciden")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
