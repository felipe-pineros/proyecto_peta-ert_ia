"""DINOv2 con ONNX Runtime (CPU).

La foto se prepara EXACTAMENTE como en la evaluación de la etapa 6 (timm, img_size=224):
lado corto a 224 px (bicúbico) → recorte central 224×224 → normalización ImageNet.
La huella es el token CLS normalizado (pooler_output), igual que timm con num_classes=0.
"""
from io import BytesIO
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


SIZE = 224
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess(image: Image.Image) -> np.ndarray:
    image = image.convert("RGB")
    w, h = image.size
    # Igual que torchvision Resize(224): el lado largo se trunca con int().
    if w <= h:
        new_w, new_h = SIZE, int(SIZE * h / w)
    else:
        new_w, new_h = int(SIZE * w / h), SIZE
    image = image.resize((new_w, new_h), Image.Resampling.BICUBIC)
    # Igual que torchvision CenterCrop: desplazamiento redondeado.
    left = int(round((new_w - SIZE) / 2.0))
    top = int(round((new_h - SIZE) / 2.0))
    image = image.crop((left, top, left + SIZE, top + SIZE))
    array = (np.asarray(image, dtype=np.float32) / 255.0 - MEAN) / STD
    return array.transpose(2, 0, 1)[np.newaxis].astype(np.float32)  # 1×3×224×224


class Dinov2Onnx:
    def __init__(self, path: Path, name: str):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.name = name
        self.input_name = self.session.get_inputs()[0].name
        outputs = [o.name for o in self.session.get_outputs()]
        self.output_name = "pooler_output" if "pooler_output" in outputs else outputs[0]

    def embed_image(self, image: Image.Image) -> list[float]:
        result = self.session.run([self.output_name], {self.input_name: preprocess(image)})[0]
        vector = result[0] if result.ndim == 2 else result[0, 0]  # (1, dim) o (1, tokens, dim)
        vector = vector.astype(np.float64)
        norm = float(np.linalg.norm(vector)) or 1.0
        return [float(x) for x in vector / norm]

    def embed_bytes(self, data: bytes) -> list[float]:
        with Image.open(BytesIO(data)) as image:
            return self.embed_image(ImageOps.exif_transpose(image))
