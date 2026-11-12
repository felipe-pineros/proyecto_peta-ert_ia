# Progreso — PET Alert

Última actualización: 2026-11-12

## Etapas
| # | Etapa | Estado |
|---|---|---|
| 1 | Auditoría | ✅ Completada (2026-10-22) |
| 2 | Arquitectura y datos | ✅ Completada (2026-10-23) |
| 3 | Supabase y seguridad | ✅ Completada (2026-11-10) |
| 4 | Backend CRUD | ✅ Completada (2026-11-10) |
| 5 | Integración frontend | ✅ Completada (2026-11-10) |
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

- **Etapa 4:**
  - API FastAPI en `backend/app/`: perfil, especies, mascotas, reportes (crear, editar, publicar, retirar), fotos (subir, borrar, URL firmada), coincidencias (ver, confirmar, descartar, contacto tras confirmar) y notificaciones.
  - El mismo servidor entrega `index.html` e `img/` (solo eso: nunca la carpeta del proyecto).
  - Fotos: se validan y recodifican a JPEG sin metadatos (`images.py` reutilizado del respaldo).
  - Ubicación: el punto exacto va a `report_private`; el público se redondea a ~1 km.
  - Dependencias en `backend/requirements.txt` (todas MIT/BSD/Apache, ~15 MB).
  - 11 pruebas de la API en `backend/tests/test_api.py`: **23/23 pruebas pasan** (11 API + 12 seguridad) contra el Supabase real (2026-11-10). Al terminar borran sus usuarios y sus fotos de Storage (comprobado: bucket vacío).
  - Comprobado que `uvicorn` arranca y responde en `/api/health`, `/` y `/docs`.
  - Cambios respecto a `docs/arquitectura.md` (ya anotados allí): la sesión se valida con `/auth/v1/user` en vez de JWKS; rutas añadidas `GET /api/species`, `DELETE /api/photos/{id}`, `GET /api/matches/{id}`.

- **Etapa 5:**
  - Estructura aprobada por Daniela: `index.html` (landing, mismo diseño) + `app.html` (aplicación), con estilos y lógica en archivos aparte.
  - `css/estilos.css`: el CSS de `index.html` movido sin cambios (lo comparten ambas páginas). `css/app.css`: estilos de la app con la misma paleta.
  - `index.html`: botón "Iniciar sesión", botones del hero y "Reportar mascota" llevan a la app, y el formulario de demostración ahora crea la cuenta real en Supabase.
  - `app.html` + `js/app.js`: login, explorar reportes (filtros), mis reportes, crear/editar reporte con mapa y fotos, detalle, coincidencias (confirmar/descartar, contacto tras confirmar) y avisos con contador.
  - `js/sesion.js` (supabase-js 2.118.0, MIT; renueva la sesión sola), `js/mapa.js` (Leaflet 1.9.4, BSD-2 + OpenStreetMap). Ambas librerías por CDN con huella SRI.
  - Backend: `GET /api/config` (solo URL + publishable key) y entrega de `app.html`, `css/`, `js/`.
  - Sin `innerHTML` con datos de usuarios (evita XSS).
  - 5 pruebas en navegador real (`backend/tests/test_frontend_e2e.py`, Playwright + Edge de Windows). **28/28 pruebas pasan** (2026-11-10). Capturas revisadas en escritorio y celular.

- **Ajuste de la etapa 5: reporte rápido sin cuenta (decisión D5, 2026-11-12). ✅ Verificado.**
  - Pedido por Daniela: quien encuentra una mascota la reporta desde la página principal sin registrarse.
  - `index.html`: nueva sección "Encontré una mascota" (foto, Perro/Gato, mapa con "Usar mi ubicación", teléfono o correo). La tarjeta del inicio baja a esa sección. Archivos: `css/reporte-rapido.css` y `js/reporte-rapido.js`.
  - Usa un usuario **anónimo** de Supabase. Migración 4 (`20261112000004_reporte_rapido_anonimo.sql`):
    - color y tamaño pasan a ser opcionales en reportes encontrados;
    - los invitados solo crean reportes encontrados, deben dejar contacto y no ven reportes ajenos.
  - Backend: `User.is_anonymous`; la API responde 403/422 con mensajes claros a los invitados.
  - Daniela aplicó la migración 4 y activó "Allow anonymous sign-ins" (2026-11-12).
  - **35/35 pruebas pasan, sin omitidas** (2026-11-12). Al terminar, Supabase quedó limpio: 0 usuarios de prueba, 0 invitados y 0 fotos.

## Pendiente
- **Etapa 6 (siguiente):** evaluación del modelo de IA (necesita las fotos de evaluación).
- Recuperar contraseña ("olvidé mi contraseña") no está implementado todavía.
- El registro real envía un correo de confirmación; el correo gratuito de Supabase permite muy pocos por hora (para la demo puede convenir configurar SMTP propio o desactivar la confirmación en Auth).
- Las coincidencias aún no se crean solas: el motor es de la etapa 7. Hoy solo existen si se insertan a mano (así lo hacen las pruebas).
- Las notificaciones de `new_match` las creará el motor (etapas 7–8).
- Reporte sin cuenta:
  - el invitado no recibe avisos dentro de la app; el dueño lo contacta tras confirmar;
  - falta CAPTCHA contra spam antes de la nube (etapa 10);
  - falta limpiar los usuarios anónimos viejos;
  - falta la opción "convertir mi reporte de invitado en cuenta".

## Bloqueado / depende de ti
- **Docker Desktop no está instalado** (necesario en la etapa 9). Instalar con los datos en `D:`, porque `C:` tiene ~8,6 GB libres.
- **Fotos de evaluación** (etapa 6): varias fotos de los mismos animales, con permiso de sus dueños.
- ~~`git push` bloqueado (403)~~ → **resuelto el 2026-11-12**: todo está subido a `origin/master`.

## Decisiones tomadas
- El modelo de IA **no se entrena**: se usa uno preentrenado y solo se calibran los umbrales.
- Candidatos para la etapa 6: DINOv2 ViT-B/14 (Apache-2.0), MegaDescriptor-B (CC-BY-NC-4.0, solo uso no comercial) y DINOv3 (licencia propia, por revisar).
- Recorte del animal con un detector de torchvision (se evita Ultralytics YOLO por su licencia AGPL).
- D1: solo usuarios con sesión ven los reportes activos.
- D2: solo el dueño de la mascota perdida confirma una coincidencia; cualquiera de los dos puede descartarla.
- D3: la ubicación se marca en un mapa (Leaflet + OpenStreetMap).
- D4: máximo 5 fotos por reporte.
- D5: reporte rápido de mascota encontrada sin cuenta (usuario anónimo de Supabase). Los invitados no ven reportes ajenos.

## Cómo verificar
- Etapas 3, 4 y 5: `.\backend\.venv\Scripts\python.exe -m pytest backend\tests -v -rs` → deben pasar las 35 pruebas (necesita internet, `backend/.env` y Microsoft Edge). Si aparecen "skipped", falta activar el modo invitado o aplicar la migración 4.
- Arrancar el servidor: `.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload` y abrir http://localhost:8000/docs (lista de rutas de la API) o http://localhost:8000 (frontend).
- Etapa 2:
  - `git status` muestra `node_modules` como eliminado del índice y `ls node_modules` sigue funcionando.
  - `git check-ignore -v node_modules backend/.env` confirma que ambos están ignorados.
