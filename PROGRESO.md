# Progreso — PET Alert

Última actualización: 2026-11-10

## Etapas
| # | Etapa | Estado |
|---|---|---|
| 1 | Auditoría | ✅ Completada (2026-10-22) |
| 2 | Arquitectura y datos | ✅ Completada (2026-10-23) |
| 3 | Supabase y seguridad | ✅ Completada (2026-11-10) |
| 4 | Backend CRUD | ⏳ Pendiente |
| 5 | Integración frontend | ⏳ Pendiente |
| 6 | Evaluación del modelo IA | ⏳ Pendiente |
| 7 | Motor de coincidencias | ⏳ Pendiente |
| 8 | Notificaciones | ⏳ Pendiente |
| 9 | Docker y documentación | ⏳ Pendiente |
| 10 | Preparación para la nube | ⏳ Pendiente |

## Completado
- **Etapa 1:** auditoría del repositorio y de la rama `respaldo-backend-ia` (reutilizable: `images.py`, patrones de `config.py` y de la migración).
- **Supabase (manual, por Daniela):** proyecto creado, Auth por correo configurado, Site URL `http://localhost:8000`.
- **Etapa 2:**
  - `.gitignore` ampliado: secretos, `node_modules/`, pesos de modelos y fotos de evaluación.
  - `node_modules/` quitado de git; la carpeta sigue en el disco.
  - `docs/arquitectura.md` aprobado, con las decisiones D1–D4.

- **Etapa 3:**
  - 3 migraciones en `supabase/migrations/` (esquema, RLS, bucket privado), aplicadas por Daniela en el SQL Editor.
  - 12 pruebas de seguridad en `backend/tests/test_seguridad_supabase.py`: **12/12 pasan contra el Supabase real** (2026-11-10). Las pruebas borran sus usuarios al terminar.
  - `backend/.env.example` y `backend/.env` con las claves (ignorado por git).
  - Entorno `backend/.venv` con httpx, pytest y python-dotenv.

## Pendiente
- **Etapa 4 (siguiente):** API FastAPI con autenticación, mascotas, reportes y subida de fotos.

## Bloqueado / depende de ti
- **Docker Desktop no está instalado** (necesario en la etapa 9). Instalar con los datos en `D:`, porque `C:` tiene ~8,6 GB libres.
- **Fotos de evaluación** (etapa 6): varias fotos de los mismos animales, con permiso de sus dueños.
- **`git push`:** el remoto es de Felipe; hay que confirmarlo con él antes de subir.

## Decisiones tomadas
- El modelo de IA **no se entrena**: se usa uno preentrenado y solo se calibran los umbrales.
- Candidatos para la etapa 6: DINOv2 ViT-B/14 (Apache-2.0), MegaDescriptor-B (CC-BY-NC-4.0, solo uso no comercial) y DINOv3 (licencia propia, por revisar).
- Recorte del animal con un detector de torchvision (se evita Ultralytics YOLO por su licencia AGPL).
- D1: solo usuarios con sesión ven los reportes activos.
- D2: solo el dueño de la mascota perdida confirma una coincidencia; cualquiera de los dos puede descartarla.
- D3: la ubicación se marca en un mapa (Leaflet + OpenStreetMap).
- D4: máximo 5 fotos por reporte.

## Cómo verificar
- Etapa 3: `.\backend\.venv\Scripts\python.exe -m pytest backend\tests -v` → deben pasar las 12 pruebas.
- Etapa 2:
  - `git status` muestra `node_modules` como eliminado del índice y `ls node_modules` sigue funcionando.
  - `git check-ignore -v node_modules backend/.env` confirma que ambos están ignorados.
