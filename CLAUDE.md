# PET Alert (repositorio: proyecto_peta-ert_ia)

Plataforma web para encontrar mascotas perdidas: los usuarios publican reportes de
mascotas perdidas o encontradas con fotos, y un módulo de visión artificial sugiere
posibles coincidencias ordenadas por similitud visual y cercanía geográfica.

## Cómo trabajar conmigo
- Soy estudiante universitaria. Explica en español, paso a paso, qué haces y por qué.
- Da comandos para Windows PowerShell (y Linux cuando sea Docker/despliegue).
- Dime claramente qué debo hacer yo manualmente (crear cuentas, claves, subir fotos, etc.).
- Trabaja por etapas. Al terminar cada etapa, detente y espera mi confirmación.
- Mantén actualizado `PROGRESO.md` con: completado, pendiente, bloqueado y cómo verificarlo.

## Reglas del repositorio
- Inspecciona antes de modificar. No borres ni sobrescribas archivos sin autorización.
- Conserva el frontend actual (`index.html`) y su diseño. No cambies de tecnología
  ni rediseñes sin justificación técnica y mi aprobación.
- No crees proyectos paralelos ni microservicios innecesarios.
- No muestres secretos. Nunca pongas `service_role` ni claves reales en el frontend,
  en el repositorio ni en imágenes Docker. Usa `.env` (ignorado por git) y `.env.example`.
- No despliegues nada ni generes costos sin mi autorización.
- Ejecuta las pruebas. Nunca digas que algo pasó si no se ejecutó, ni que una
  funcionalidad está terminada si depende de datos simulados o servicios sin configurar.
- Haz un commit de git al cerrar cada etapa verificada.

## Hardware y restricciones
- Windows, Ryzen 3 3200G, 16 GB RAM (~13,9 GB útiles), GPU AMD RX 6600 XT 8 GB (sin CUDA).
- Todo debe funcionar en CPU. No exigir NVIDIA/CUDA, servidores de pago ni modelos grandes.
- Antes de instalar una dependencia o modelo, verifica: tamaño, licencia, compatibilidad
  con Windows y Docker, y memoria requerida.

## Stack (adaptar al código existente, no migrar sin motivo)
- Frontend: el existente (`index.html`, HTML/CSS/JS sin framework).
- Backend: Python + FastAPI (`backend/`).
- Supabase: PostgreSQL, Auth, Storage privado, RLS (`supabase/migrations/`).
- IA: módulo independiente y configurable para poder cambiar de modelo.
- Docker + Docker Compose (Compose NO instala Supabase; documentar Supabase remoto o local).
- Nube (más adelante, solo evaluación): Google Cloud Run.

## Requisitos funcionales
1. Registro e inicio de sesión.
2. Reportes de mascotas perdidas y encontradas (perros y gatos; extensible a otras especies).
3. Fotos de los animales.
4. Datos: especie, raza (opcional), color, tamaño, rasgos particulares, fecha y ubicación.
5. Consultar y actualizar reportes.
6. Comparar fotos con visión artificial y buscar coincidencias perdida ↔ encontrada.
7. Ordenar candidatos por similitud visual y proximidad geográfica.
8. Notificar coincidencias relevantes sin duplicados.
9. Confirmar o descartar coincidencias y actualizar estados de reportes.
- El sistema presenta POSIBLES coincidencias; nunca afirma la identidad de un animal.
- No se necesita chatbot ni LLM generativo.

## Modelo de datos (objetivo)
Perfiles, mascotas (identidad separada de los reportes), reportes, fotos, embeddings,
coincidencias y notificaciones. Con claves foráneas, índices, restricciones,
migraciones versionadas y RLS.

## Visión artificial
- Lo importante es la **reidentificación individual** (¿es el mismo animal?), no solo
  detectar "hay un perro".
- Candidatos a evaluar: DINOv2 ViT-S/14 (embeddings), MobileNetV3 (ligero; explicar qué
  adaptación necesita para individuos), detector ligero tipo YOLO para recortar, y modelos
  de re-ID de perros/gatos (verificar licencia y disponibilidad).
- No entrenar desde cero sin justificación experimental. No inventar métricas.
- Evaluar con fotos etiquetadas (mismo animal / distinto): precisión, falsos positivos, Recall@K,
  tiempo y memoria.

## Etapas
1. Auditoría · 2. Arquitectura y datos · 3. Supabase y seguridad · 4. Backend CRUD ·
5. Integración frontend · 6. Evaluación del modelo IA · 7. Motor de coincidencias ·
8. Notificaciones · 9. Docker y documentación · 10. Preparación para la nube
