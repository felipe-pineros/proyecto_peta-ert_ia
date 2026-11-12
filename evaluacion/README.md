# Evaluación de modelos de IA (etapa 6)

Objetivo: elegir con **datos reales** qué modelo reconoce mejor si dos fotos son **del mismo animal**.
No se entrena ningún modelo: se usan modelos ya entrenados y se mide cuál funciona mejor.

## 1. Dónde poner las fotos

En la carpeta `datos_evaluacion/` (en la raíz del proyecto). Git la ignora, así que las fotos
**nunca se suben a GitHub**.

```
datos_evaluacion/
├─ perros/
│  ├─ toby/        foto1.jpg  foto2.jpg  foto3.jpg
│  ├─ luna/        ...
│  └─ ...
└─ gatos/
   ├─ michi/       ...
   └─ ...
```

- **Una carpeta por animal.** El nombre de la carpeta solo sirve para agrupar (puede ser `perro01`).
- **2 a 5 fotos por animal** en distintos momentos: ángulos, lugares y luz diferentes (como sería
  la foto del dueño frente a la de quien lo encontró en la calle). No sirven fotos casi idénticas
  tomadas en ráfaga, porque harían ver al modelo mejor de lo que es.
- **Meta:** 15 a 30 animales. Un animal con 1 sola foto también ayuda, como "distractor".
- Formatos: JPG, PNG o WebP. Las fotos de iPhone en HEIC hay que convertirlas o enviarlas como JPG.
- **Pide permiso** a los dueños. Si aparecen personas, mejor recorta la foto.

## 2. Instalar (solo una vez, ~1 GB)

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r evaluacion\requirements-ia.txt
```

Los modelos se descargan solos la primera vez (88 a 473 MB cada uno) en `C:\Users\<tu usuario>\.cache`.

## 3. Usar

```powershell
# Revisar las fotos (cuántos animales hay, fotos dañadas o mal ubicadas)
.\backend\.venv\Scripts\python.exe evaluacion\evaluar.py verificar

# Ver los modelos candidatos
.\backend\.venv\Scripts\python.exe evaluacion\evaluar.py modelos

# Medir un modelo (agrega --recorte para recortar al animal antes de comparar)
.\backend\.venv\Scripts\python.exe evaluacion\evaluar.py evaluar --modelo dinov2_s
.\backend\.venv\Scripts\python.exe evaluacion\evaluar.py evaluar --modelo dinov2_s --recorte
.\backend\.venv\Scripts\python.exe evaluacion\evaluar.py evaluar --modelo megadescriptor_t --recorte
```

Los resultados quedan en `evaluacion/resultados/*.json`, y una tabla comparativa en
`evaluacion/resultados.md`. Solo contienen números: ni fotos ni nombres.

## 4. Qué significa cada número

| Métrica | Pregunta que responde |
|---|---|
| **Recall@1 / @5** | ¿La foto correcta aparece como 1.ª sugerencia / entre las 5 primeras? (lo que verá el dueño) |
| **mAP** | En promedio, ¿qué tan arriba quedan todas las fotos correctas? |
| **AUC** | ¿Qué tan bien separa "mismo animal" de "distinto"? (50 % = al azar, 100 % = perfecto) |
| **Detecta con 1 % / 5 % FP** | Si solo aceptamos 1 % o 5 % de falsas alarmas, ¿cuántas coincidencias reales detecta? Sirve para fijar el umbral de las notificaciones (etapa 7) |
| **ms/foto y memoria** | Si corre bien en tu computador y en Cloud Run |

Solo se comparan fotos de la misma especie (perro con perro), como hará el motor.

## 5. Pruebas de las métricas

```powershell
.\backend\.venv\Scripts\python.exe -m pytest evaluacion -q
```
