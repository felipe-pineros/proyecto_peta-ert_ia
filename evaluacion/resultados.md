# Resultados de la evaluación (etapa 6)

Generado por `evaluar.py`. Solo números medidos con las fotos de `datos_evaluacion/`.

| Modelo | Fotos / animales | Recall@1 | Recall@5 | mAP | AUC | Detecta con 1 % FP | Detecta con 5 % FP | ms/foto | Memoria MB | Licencia | Fecha |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dinov2_s | 37 / 12 | 86.5 % | 100.0 % | 85.9 % | 94.8 % | 30.8 % | 79.5 % | 136.4 | 548.8 | Apache-2.0 | 2026-11-18 |
| dinov2_s + recorte | 37 / 12 | 83.8 % | 100.0 % | 85.8 % | 94.0 % | 25.6 % | 79.5 % | 660.3 | 953.9 | Apache-2.0 | 2026-11-18 |
| megadescriptor_t | 37 / 12 | 16.2 % | 64.9 % | 32.9 % | 56.1 % | 0.0 % | 5.1 % | 182.4 | 715.0 | CC-BY-NC-4.0 | 2026-11-18 |
| megadescriptor_t + recorte | 37 / 12 | 18.9 % | 59.5 % | 31.9 % | 55.6 % | 0.0 % | 2.6 % | 651.9 | 980.7 | CC-BY-NC-4.0 | 2026-11-18 |
