# Progreso — PET Alert

Última actualización: 2026-11-17

## Etapas
| # | Etapa | Estado |
|---|---|---|
| 1 | Auditoría | ✅ Completada (2026-10-22) |
| 2 | Arquitectura y datos | ✅ Completada (2026-10-23) |
| 3 | Supabase y seguridad | ✅ Completada (2026-11-10) |
| 4 | Backend CRUD | ✅ Completada (2026-11-10) |
| 5 | Integración frontend | ✅ Completada (2026-11-10) |
| 6 | Evaluación del modelo IA | 🔄 Primera medición con fotos reales (2026-11-17): gana DINOv2-S; falta ampliar la muestra |
| 7 | Motor de coincidencias | ✅ Hecho y probado en local y Docker (2026-11-17); falta publicarlo en Render |
| 8 | Notificaciones | ⏳ Pendiente |
| 9 | Docker y documentación | 🔄 Docker listo y probado (2026-11-17), falta tu confirmación |
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

- **Buscadores y vista previa al compartir (2026-11-12):**
  - `index.html`: título y descripción para Google, `canonical`, Open Graph (imagen `img/compartir.jpg` de 1200×630, 117 KB, recortada del banner) y datos estructurados `WebSite`.
  - `app.html` lleva `noindex`: la app requiere sesión.
  - El backend entrega `/robots.txt` (permite la portada; bloquea `/app.html` y `/api/`) y `/sitemap.xml`. Ambos usan `PUBLIC_SITE_URL` (opcional) o, si no está, la dirección de la petición.
  - **36/36 pruebas pasan** (2026-11-12).
  - Falta (al publicar en la nube, etapa 10): dominio, `PUBLIC_SITE_URL` y registrar el sitio en Google Search Console.

- **Botones para difundir en redes (2026-11-12):**
  - `js/compartir.js` y `css/compartir.css`. En el detalle de un reporte publicado y al terminar el reporte rápido aparecen: Compartir (menú del celular, con la foto), WhatsApp, Facebook y Copiar texto.
  - El texto solo lleva datos públicos (especie, color, tamaño, fecha y lugar escrito). **Nunca** el teléfono, el correo ni el punto exacto; las pruebas lo comprueban.
  - El enlace lleva a la página principal, porque los reportes requieren sesión (D1).
  - **36/36 pruebas pasan.** Capturas revisadas en escritorio y celular.
- **Leer anuncios de redes con Gemini (decisión D6, 2026-11-12). Probado con la clave real ✅.**
  - En el formulario rápido, el bloque plegable "¿Lo viste en un anuncio de redes?": se pega el texto y la IA llena especie, color, tamaño, raza, señas, lugar y fecha. La persona lo revisa antes de publicar.
  - Backend `app/anuncios.py` + `POST /api/ads/extract`:
    - plan gratuito, solo texto;
    - borra teléfonos, correos, enlaces y @usuarios antes de enviar;
    - valida la respuesta;
    - máximo 10 por persona por hora;
    - la clave solo vive en `backend/.env`.
  - Solo aparece si hay `GEMINI_API_KEY`; sin ella, el formulario funciona igual.
  - Pruebas automáticas: **46/46 pasan**. 10 están en `test_anuncios.py`, más el flujo completo en Edge. En ellas Gemini está **simulado**, para no gastar cuota.
  - **Prueba real con Google (2026-11-12, modelo `gemini-3.5-flash-lite`):**
    - un anuncio de ejemplo, enviado por `POST /api/ads/extract` con una sesión de invitado, respondió en ~4 s con los datos correctos: gato, gris atigrado, pequeño, collar azul y oreja doblada, calle 72 con carrera 11, fecha de hoy;
    - se borraron 2 datos de contacto antes de enviarlo.
  - Hallazgo: el plan gratuito a veces responde **503 "high demand"** (modelo saturado). Es pasajero, así que el backend reintenta 2 veces. Si sigue saturado, dice "La IA está ocupada… intenta en un minuto o llena los datos a mano".
- **Etapa 6 (en curso, 2026-11-12): herramientas de evaluación.**
  - `evaluacion/evaluar.py` tiene tres comandos:
    - `verificar`: revisa las fotos;
    - `modelos`: lista los candidatos;
    - `evaluar --modelo X [--recorte]`: mide Recall@1/5/10, mAP, AUC, detección con 1 % y 5 % de falsos positivos, ms/foto y memoria.
  - Modelos verificados (tamaño y licencia en Hugging Face): DINOv2 S/B (Apache-2.0, 88 y 346 MB) y MegaDescriptor T/B (CC-BY-NC-4.0, 204 y 473 MB). Recorte con el detector Faster R-CNN MobileNetV3 de torchvision (BSD, 74 MB).
  - `evaluacion/requirements-ia.txt`: torch 2.15 CPU, torchvision 0.29.2, timm 1.0.31 y psutil. Instalados en `backend/.venv` (~1 GB). No van en `backend/requirements.txt`, para que el servidor siga siendo liviano.
  - Comprobado:
    - 4 pruebas de las métricas pasan;
    - la evaluación completa corre con imágenes **sintéticas** (solo prueba que el programa funciona, no la calidad);
    - el detector recorta al perro y al gato del banner;
    - MegaDescriptor-T carga bien.
  - Carpeta `datos_evaluacion/perros` y `/gatos` creada (ignorada por git).

- **Etapa 9: Docker (2026-11-17). Probado ✅, falta la confirmación de Daniela.**
  - Archivos nuevos: `Dockerfile`, `docker-compose.yml` y `.dockerignore`.
  - La imagen `petalert:local` pesa 253 MB y usa Python 3.14 slim, la misma versión del `.venv`.
  - Lleva solo `backend/app`, las dos páginas, `css/`, `js/` e `img/`.
  - Corre con el usuario `petalert`, sin permisos de administrador. Tiene revisión de salud (`/api/health`) y usa el puerto de la variable `PORT`, que necesita Cloud Run.
  - Las claves llegan desde `backend/.env` al encender (`env_file`). **No están dentro de la imagen:** se comprobó que hay 0 archivos `.env` y 0 variables con claves al revisarla por dentro.
  - Compose no instala Supabase: el contenedor usa el Supabase remoto.
  - Comprobado con el contenedor encendido:
    - estado `healthy`;
    - `/`, `/app.html`, `/css`, `/js`, `/robots.txt`, `/docs` y `/api/config` responden 200;
    - `/.env`, `/backend/.env` y `/backend/app/config.py` dan 404.
  - Las **7 pruebas del navegador pasan contra el contenedor** (opción nueva `PETALERT_BASE_URL` en `test_frontend_e2e.py`). El contenedor atendió 201 peticiones sin errores. En modo normal, sin Docker, también pasan las 7.
  - README: nueva sección 3.1, "Encender con Docker".
  - Docker Desktop está instalado en `AppData\Local\Programs\DockerDesktop` y hay que encenderlo antes de usar `docker compose`.
- **Error corregido (2026-11-17):**
  - Problema: el enlace "Regístrate aquí" de la pantalla de inicio de sesión, el logo de la app y "Cerrar sesión" llevaban a `/index.html`, y esa dirección daba 404. Por eso no se podía llegar al registro desde la app.
  - Solución: el servidor ahora también entrega `/index.html`.
  - Hay una prueba nueva en `test_api.py`. Las 12 pruebas de la API pasan, y el contenedor responde 200 en esa dirección.

- **Publicado en Render (2026-11-17), autorizado por Daniela: https://proyecto-pet-alert.onrender.com**
  - Plan Free, región Virginia. Usa el `Dockerfile` desde el repositorio público, con la opción "Public Git Repository".
  - Las claves están solo en Environment Variables de Render.
  - Comprobado:
    - todas las páginas responden 200;
    - `/.env` da 404;
    - `/api/config` trae Supabase y Gemini;
    - `robots.txt` usa `https`;
    - **las 7 pruebas del navegador pasan contra la URL publicada**.
  - Límites del plan gratis: se duerme tras 15 minutos sin visitas (la primera carga tarda entre 30 y 60 segundos), 512 MB de memoria y 750 horas al mes.
  - Sin despliegue automático: tras cada `git push` hay que presionar **Manual Deploy** en Render.
  - Lo hace Daniela: Site URL y Redirect URLs de Supabase con la URL de Render; para la demo, desactivar "Confirm email"; opcional, `PUBLIC_SITE_URL` en Render.

- **Verificado en la URL publicada (2026-11-17):**
  - con `PUBLIC_SITE_URL` puesta, `canonical` y `og:image` usan la URL de Render;
  - "Confirm email" está desactivado;
  - un registro real entra sin confirmar el correo y `/api/me` responde 200 desde Render. El usuario de prueba se borró.
- **Etapa 6: primera medición con fotos reales (2026-11-17).**
  - Muestra: 37 fotos de 12 animales (8 perros con 25 fotos, 4 gatos con 12 fotos), puestas por Daniela.
  - Tabla completa en `evaluacion/resultados.md`.

  | Modelo | Recall@1 | Recall@5 | AUC | Detecta con 5 % FP | ms/foto | Memoria |
  |---|---|---|---|---|---|---|
  | **DINOv2-S** | **86,5 %** | 100 % | **94,8 %** | 79,5 % | **136** | **549 MB** |
  | DINOv2-S + recorte | 83,8 % | 100 % | 94,0 % | 79,5 % | 660 | 954 MB |
  | MegaDescriptor-T | 16,2 % | 64,9 % | 56,1 % | 5,1 % | 182 | 715 MB |
  | MegaDescriptor-T + recorte | 18,9 % | 59,5 % | 55,6 % | 2,6 % | 652 | 981 MB |

  - **Ganador provisional: DINOv2-S, sin recorte.** Es más preciso, 5 veces más rápido que con recorte, usa menos memoria y tiene licencia Apache-2.0, que permite uso comercial. El recorte no mejoró los resultados con estas fotos.
  - MegaDescriptor-T salió casi al azar (AUC 56 %), y se descartaron fallas nuestras:
    - se corrigió su preparación de imagen según su ficha (224×224 sin recorte, normalización 0,5) y el resultado no cambió;
    - se comprobó que carga sus pesos entrenados.
    - Además, su licencia es no comercial. Queda descartado.
  - **Límites de esta medición (no exagerar):**
    - 12 animales es poco: cada acierto o error mueve Recall@1 unos 3 puntos;
    - con solo 4 gatos, Recall@5 = 100 % es fácil (hay solo 3 gatos más con quienes confundirlo);
    - no se ha comprobado si hay fotos casi iguales tomadas en ráfaga, lo que inflaría los números;
    - el umbral de notificación aún no está calibrado (con 1 % de falsos positivos solo detecta el 31 %).
  - Memoria: con PyTorch, DINOv2-S llega a 549 MB, más que los 512 MB de Render Free. Para el motor (etapa 7) se propone exportarlo a ONNX Runtime.

- **Etapa 7: motor de coincidencias (2026-11-17). ✅ Probado.**
  - **Modelo:** DINOv2-S en ONNX Runtime 1.32 (MIT; 16 MB en Windows y 27 MB en Linux), sin PyTorch.
    - El archivo es `onnx-community/dinov2-small`, con versión fija y SHA-256 verificado.
    - `evaluacion/verificar_onnx.py` comprueba que da las mismas huellas que el modelo evaluado: similitud mínima de 0,9973 en las 37 fotos, mismo Recall@1 (86,5 %), AUC de 94,7 % y el mismo umbral.
    - La versión int8 se probó y se descartó: Recall@1 de 83,8 % y no es más rápida.
  - **Módulo `backend/app/ia/`:**
    - el modelo se elige con `IA_MODEL` y se apaga con `IA_ENABLED=false`;
    - `python -m app.ia.descargar` lo descarga en `backend/modelos/` (ignorado por git).
  - **Migración 5** (aplicada por Daniela el 2026-11-17):
    - `find_match_candidates` aplica los filtros (misma especie, perdida↔encontrada, ambos activos, personas distintas, fecha con 1 día de margen y 50 km o menos) y devuelve la mejor similitud entre fotos y la distancia aproximada;
    - `save_match_suggestion` guarda sin duplicados y no toca las confirmadas ni las descartadas;
    - ambas son solo para `service_role`.
  - **`backend/app/motor.py`:**
    - corre en segundo plano al publicar un reporte o al subir una foto a uno publicado;
    - al encender, procesa las fotos que quedaron sin huella;
    - `total = 0,75·visual + 0,25·exp(−km/5)`. Sugiere si visual ≥ 0,49 (`MATCH_MIN_SIMILARITY`), un valor **provisional** de la etapa 6;
    - calcula una cosa a la vez, y si una foto se borró durante el cálculo, la salta.
  - **Pruebas:**
    - **7 pruebas nuevas** (`test_motor.py`, modelo real y Supabase real): mismo animal → sugiere (visual ≥ 0,9); otro animal → no; recalcular no duplica; las descartadas no reviven; filtros de distancia, especie, fecha y mismo usuario;
    - las pruebas de confirmar y descartar apagan la IA (`conftest.py`), y la inserción manual tolera que la pareja ya exista;
    - **57/57 pasan** (53 del backend + 4 de métricas).
  - **Docker:**
    - la imagen descarga y verifica el modelo al construirse y pesa 630 MB;
    - arranca con "IA activa: dinov2_s";
    - **memoria máxima: 256 MiB** con el motor trabajando (Render Free da 512 MB);
    - las 7 pruebas del navegador pasan contra el contenedor con la IA activa, sin fallos del motor en los registros.
  - **Hallazgo corregido:** si se borraba una foto mientras el motor la procesaba, el motor abandonaba todo el reporte. Ahora la salta.
  - Pendiente: los avisos de `new_match` son de la etapa 8; ya está marcado dónde se crearán, en `motor.py`, cuando `is_new` es verdadero.

## Pendiente
- **Etapa 6:** ampliar la muestra a 15–30 animales, con más gatos y algunos animales de 1 sola foto como distractores, y volver a medir antes de fijar el umbral.
- Recuperar contraseña ("olvidé mi contraseña") no está implementado todavía.
- El registro real envía un correo de confirmación; el correo gratuito de Supabase permite muy pocos por hora (para la demo puede convenir configurar SMTP propio o desactivar la confirmación en Auth).
- Las notificaciones de `new_match` las creará el motor (etapas 7–8).
- Reporte sin cuenta:
  - el invitado no recibe avisos dentro de la app; el dueño lo contacta tras confirmar;
  - falta CAPTCHA contra spam antes de la nube (etapa 10);
  - falta limpiar los usuarios anónimos viejos;
  - falta la opción "convertir mi reporte de invitado en cuenta".

## Bloqueado / depende de ti
- ~~Clave de Gemini~~ → **resuelto el 2026-11-12**: la clave está en `backend/.env` y la conexión real funciona.
- ~~Docker Desktop no está instalado~~ → **resuelto**: instalado y funcionando (2026-11-17).
- **Google Cloud (etapa 10):** falta instalar `gcloud` y crear el proyecto con facturación. No se hace sin tu autorización.
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
- D6: leer el texto de anuncios de redes con Gemini (opcional, plan gratuito, solo texto y sin datos de contacto).

## Cómo verificar
- Etapas 3, 4 y 5: `.\backend\.venv\Scripts\python.exe -m pytest backend\tests -v -rs` → deben pasar las 46 pruebas (necesita internet, `backend/.env` y Microsoft Edge). Si aparecen "skipped", falta activar el modo invitado o aplicar la migración 4.
- Etapa 9 (Docker): con Docker Desktop encendido, ejecutar `docker compose up --build -d`. Luego `docker compose ps` debe mostrar `healthy` y http://localhost:8000 debe abrir. Para probar contra el contenedor: `$env:PETALERT_BASE_URL="http://localhost:8000"` y después `pytest backend\tests\test_frontend_e2e.py` (7 pruebas).
- Etapa 6: `.\backend\.venv\Scripts\python.exe -m pytest evaluacion -q` (4 pruebas) y `.\backend\.venv\Scripts\python.exe evaluacion\evaluar.py verificar`.
- Arrancar el servidor: `.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload` y abrir http://localhost:8000/docs (lista de rutas de la API) o http://localhost:8000 (frontend).
- Etapa 2:
  - `git status` muestra `node_modules` como eliminado del índice y `ls node_modules` sigue funcionando.
  - `git check-ignore -v node_modules backend/.env` confirma que ambos están ignorados.
