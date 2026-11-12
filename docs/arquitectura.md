# Arquitectura y modelo de datos — PET Alert

> Estado: **APROBADO** (etapa 2, 2026-10-23). Nada de esto existe todavía en Supabase.
> Cuando se apruebe, la etapa 3 lo convierte en migraciones SQL en `supabase/migrations/`.

## 1. Vista general

```
Navegador (index.html, HTML/CSS/JS sin framework)
  │  supabase-js (CDN, versión fija) → SOLO registro, login y refresco de sesión
  │  (la URL y la publishable key se piden a GET /api/config; no están escritas en el código)
  │  fetch /api/...  con  Authorization: Bearer <token del usuario>
  ▼
FastAPI  (backend/, un solo servicio)
  ├─ sirve index.html e img/ (mismo origen → sin problemas de CORS)
  ├─ valida el token del usuario preguntando a Supabase Auth (/auth/v1/user)
  │   (etapa 4: se prefirió a JWKS porque no añade dependencias y una sesión
  │    cerrada o una cuenta borrada deja de servir al instante)
  ├─ operaciones del usuario → Supabase con el TOKEN DEL USUARIO (aplica RLS)
  ├─ operaciones internas → Supabase con la SECRET KEY (Storage, embeddings,
  │                          coincidencias, notificaciones)
  ├─ ia/          modelo intercambiable (se elige por variable de entorno)
  └─ coincidencias/  calcula y guarda posibles coincidencias
  ▼
Supabase (remoto, plan gratis)
  ├─ PostgreSQL + extensión pgvector, RLS en todas las tablas
  ├─ Auth (correo y contraseña)
  └─ Storage: bucket PRIVADO `report-photos`
```

**Por qué así**
- El navegador solo conoce la *publishable key*, que está hecha para ser pública.
- La *secret key* solo vive en `backend/.env`.
- No hay microservicios: la IA corre dentro del mismo FastAPI, en segundo plano.
- Supabase-js en el navegador se encarga de renovar la sesión. Esto corrige el error del intento anterior, donde la sesión se caía cada hora.

## 2. Tablas

Convenciones:
- `id uuid` como clave primaria.
- `created_at` y `updated_at` en todas las tablas.
- Textos con longitud máxima.
- RLS activado siempre.

### 2.1 `profiles` — datos del usuario
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | = `auth.users.id` (FK, ON DELETE CASCADE) |
| display_name | text ≤ 80 | nombre visible |
| phone | text ≤ 40, opcional | **privado**: solo se comparte tras confirmar una coincidencia |
| created_at, updated_at | timestamptz | |

Se crea automáticamente con un *trigger* cuando alguien se registra.

### 2.2 `species` — especies (extensible)
| Columna | Tipo | Notas |
|---|---|---|
| code | text PK | `dog`, `cat` (mañana `rabbit`, etc.) |
| name_es | text | "Perro", "Gato" |
| active | boolean | permite ocultar una especie sin borrarla |

Agregar una especie = insertar una fila, sin cambiar el código.

### 2.3 `pets` — identidad de la mascota (separada de los reportes)
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid FK → profiles | |
| name | text ≤ 80, opcional | |
| species | text FK → species | |
| breed | text ≤ 80, opcional | raza opcional |
| color | text ≤ 80 | |
| size | text | `small` / `medium` / `large` |
| distinctive_features | text ≤ 1000 | rasgos particulares |

Una mascota puede perderse varias veces: **una mascota tiene muchos reportes.**

### 2.4 `reports` — reporte de perdida o encontrada
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK → profiles | quien publica |
| pet_id | uuid FK → pets, nullable | **obligatorio si `type = lost`**, vacío si `found` |
| type | text | `lost` / `found` |
| status | text | ver §3 |
| species | text FK → species | |
| breed, color, size, distinctive_features | | descripción *tal como se vio* (copia editable) |
| event_at | timestamptz | fecha en que se perdió / se encontró |
| location_label | text ≤ 160 | p. ej. "Parque de Suba, Bogotá" |
| approx_lat, approx_lng | numeric(7,4) → **redondeado a 2 decimales (~1 km)** | ubicación pública aproximada, usada para la distancia |
| published_at, resolved_at | timestamptz | |

Restricciones:
- `CHECK`: si el tipo es `lost`, el reporte debe tener `pet_id`; si es `found`, no debe tenerlo.
- `CHECK` de rangos de latitud y longitud.

### 2.5 `report_private` — datos sensibles del reporte
| Columna | Tipo | Notas |
|---|---|---|
| report_id | uuid PK, FK → reports (CASCADE) | |
| exact_lat, exact_lng | numeric(9,6) | ubicación exacta |
| contact_phone, contact_email | text | contacto para este reporte |

Solo el dueño del reporte la ve. La otra persona recibe el contacto **solo cuando se confirma una coincidencia** (lo hace el backend).

### 2.6 `report_photos` — fotos
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| report_id | uuid FK → reports (CASCADE) | |
| user_id | uuid FK → profiles | |
| storage_path | text UNIQUE | `<user_id>/<report_id>/<photo_id>.jpg` |
| status | text | `pending` → `ready` / `failed` |
| width, height, byte_size | int | |

Reglas de las fotos:
- Máximo 5 fotos por reporte.
- El backend valida y recodifica cada foto a JPEG sin metadatos, reutilizando `images.py` del respaldo.
- Las fotos se ven con **URLs firmadas** de pocos minutos.

### 2.7 `photo_embeddings` — "huella" visual de cada foto
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| photo_id | uuid FK → report_photos (CASCADE) | |
| model_name | text | p. ej. `dinov2_vitb14`, `megadescriptor_b224` |
| embedding | `vector` (pgvector) | sin dimensión fija → permite cambiar de modelo |
| crop_box | jsonb, opcional | recorte del animal usado |
| UNIQUE (photo_id, model_name) | | no se repite la huella de una foto con el mismo modelo |

Con pocos miles de fotos, la búsqueda exacta (sin índice aproximado) es rápida. Si el sistema crece, se agrega un índice HNSW por modelo.

### 2.8 `matches` — posibles coincidencias
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| lost_report_id | uuid FK → reports | |
| found_report_id | uuid FK → reports | |
| model_name | text | modelo que la generó |
| visual_score | real 0–1 | mejor similitud entre sus fotos |
| distance_km | real | entre ubicaciones aproximadas |
| total_score | real 0–1 | puntaje combinado (§4) |
| status | text | `suggested` / `confirmed` / `discarded` |
| decided_by, decided_at | | quién y cuándo confirmó o descartó |
| **UNIQUE (lost_report_id, found_report_id)** | | **la misma pareja nunca se duplica** |

Si el motor vuelve a calcular una pareja existente, solo **actualiza los puntajes**. Una pareja descartada no reaparece.

### 2.9 `notifications` — avisos dentro de la app
| Columna | Tipo | Notas |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK → profiles | destinatario |
| match_id | uuid FK → matches (CASCADE) | |
| kind | text | `new_match` / `match_confirmed` / `match_discarded` |
| read_at | timestamptz | null = no leída |
| **UNIQUE (user_id, match_id, kind)** | | **evita notificaciones duplicadas** |

Las notificaciones por correo quedan como posible mejora en la etapa 8.

### Relaciones (resumen)
```
auth.users 1─1 profiles 1─N pets 1─N reports(lost)
                profiles 1─N reports(found)
reports 1─1 report_private
reports 1─N report_photos 1─N photo_embeddings (una por modelo)
reports(lost) N─N reports(found)  a través de  matches 1─N notifications
```

## 3. Estados

**Reporte:** `draft` → `active` → `resolved` | `withdrawn`
- `draft`: recién creado y sin foto lista; no lo ve nadie más.
- `active`: tiene al menos una foto `ready`; se publica y entra al motor de coincidencias.
- `resolved`: se confirmó una coincidencia (la mascota apareció).
- `withdrawn`: el usuario lo retira.

**Coincidencia:** `suggested` → `confirmed` | `discarded`
- Al **confirmar**, ambos reportes pasan a `resolved` y el backend comparte los contactos entre las dos personas.
- El sistema **nunca afirma** que es el mismo animal; la interfaz dice "posible coincidencia".

## 4. Puntaje de coincidencia (inicial, se calibra en etapas 6–7)

Filtros duros (si no se cumplen, no se compara):
- Misma especie.
- Un reporte `lost` contra uno `found`, ambos `active`, de usuarios distintos.
- Fecha de encontrado ≥ fecha de pérdida − 1 día.
- Distancia ≤ 50 km.

Fórmula:
```
visual = máxima similitud coseno entre las fotos de ambos reportes (0–1)
geo    = exp(−distancia_km / 5)          → 1 si están al lado, ~0,37 a 5 km
total  = 0,75 · visual + 0,25 · geo
```

Los pesos (0,75 / 0,25), la escala (5 km) y el umbral de notificación son **valores iniciales sin medir**. Se ajustarán con las fotos de evaluación; no hay entrenamiento del modelo, solo calibración.

Se notifica solo si `total ≥ umbral` y la pareja es nueva.

## 5. Seguridad (RLS) — quién puede hacer qué

| Tabla | Leer | Crear / editar |
|---|---|---|
| profiles | el propio usuario | el propio usuario |
| species | todos los usuarios con sesión | nadie desde la app (solo migraciones) |
| pets | el dueño | el dueño |
| reports | el dueño (todos sus reportes), y cualquier usuario **con sesión y cuenta** (no invitado, D5) si está `active` (D1) | el dueño, solo campos descriptivos; **el estado solo cambia mediante funciones del backend** |
| report_private | el dueño | el dueño |
| report_photos | el dueño, y otros usuarios si el reporte está `active` | solo el backend |
| photo_embeddings | nadie desde el navegador | solo el backend |
| matches | los dueños de los dos reportes | solo el backend (confirmar o descartar pasa por la API) |
| notifications | el destinatario | solo el backend crea; el destinatario solo marca como leída |
| Storage `report-photos` | nadie directo; solo con URL firmada | solo el backend |

## 6. Flujo principal

1. Usuario crea un reporte (`draft`) → sube fotos → el backend valida, guarda en Storage, marca la foto `ready`.
2. El reporte pasa a `active`.
3. **En segundo plano**, el backend:
   - recorta al animal;
   - calcula el embedding y lo guarda;
   - busca reportes del tipo contrario que cumplan los filtros;
   - calcula el puntaje y guarda o actualiza `matches`;
   - crea notificaciones para las parejas nuevas que superen el umbral.
4. El usuario ve sus posibles coincidencias ordenadas por `total_score` → confirma o descarta.

## 7. API prevista (FastAPI)

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/health` | comprobar que el servidor vive |
| GET / PATCH | `/api/me` | ver y editar mi perfil |
| GET | `/api/species` | especies activas (para el formulario) — *añadida en etapa 4* |
| GET / POST | `/api/pets` · PATCH `/api/pets/{id}` | mis mascotas |
| GET | `/api/reports?type=&species=` | reportes activos (con filtros) |
| GET | `/api/reports/mine` | mis reportes |
| POST | `/api/reports` · PATCH `/api/reports/{id}` | crear y editar |
| POST | `/api/reports/{id}/photos` | subir foto |
| POST | `/api/reports/{id}/publish` · `/withdraw` | cambiar estado |
| GET | `/api/photos/{id}/url` | URL firmada temporal |
| DELETE | `/api/photos/{id}` | borrar una foto (un reporte publicado conserva al menos una) — *añadida en etapa 4* |
| GET | `/api/reports/{id}/matches` | posibles coincidencias, ordenadas |
| GET | `/api/matches/{id}` | detalle; si está confirmada, incluye el contacto de la otra persona — *añadida en etapa 4* |
| POST | `/api/matches/{id}/confirm` · `/discard` | decidir |
| GET | `/api/notifications` · POST `/api/notifications/{id}/read` | avisos |
| POST | `/api/ads/extract` | leer el texto de un anuncio de redes con Gemini (opcional, D6) — *añadida 2026-11-12* |

## 8. Estructura de carpetas prevista

```
proyecto_peta-ert_ia/
├─ index.html, img/            (landing, se conserva su diseño)
├─ app.html                    (aplicación: login, reportes, mapa, coincidencias, avisos) — etapa 5
├─ css/  estilos.css (CSS original de index.html, compartido) · app.css
├─ css/  reporte-rapido.css · js/ reporte-rapido.js  (formulario "Encontré una mascota", D5)
├─ js/   sesion.js · registro.js · mapa.js · app.js
├─ backend/
│  ├─ app/  main.py, config.py, auth.py, routers/, services/
│  ├─ ia/   base.py (interfaz), dinov2.py, megadescriptor.py, recorte.py
│  ├─ coincidencias/ motor.py
│  ├─ tests/
│  ├─ requirements.txt, .env.example
├─ supabase/migrations/        (SQL versionado)
├─ evaluacion/                 (scripts de la etapa 6; las fotos van en datos_evaluacion/, fuera de git)
├─ docs/arquitectura.md
├─ docker-compose.yml, Dockerfile   (etapa 9)
└─ PROGRESO.md
```

## 9. Decisiones tomadas (aprobadas por Daniela, 2026-10-23)

- **D1 — Visibilidad:** solo los usuarios **con sesión** ven los reportes activos. Los visitantes sin cuenta ven únicamente la landing page.
- **D2 — Confirmación:** solo el **dueño de la mascota perdida** puede confirmar una coincidencia. Cualquiera de los dos puede descartarla.
- **D3 — Ubicación:** se marca en un **mapa** (Leaflet + OpenStreetMap, gratis y sin clave).
  - Al guardar, el backend redondea las coordenadas públicas a ~1 km y guarda las exactas en `report_private`.
  - Antes de instalar Leaflet (etapa 5) se verificarán su versión y licencia (BSD-2), y la política de uso de los mapas de OpenStreetMap.
- **D4 — Fotos:** máximo **5 fotos por reporte**.
- **D5 — Reporte rápido sin cuenta (aprobada por Daniela, 2026-11-12):** quien encuentra una mascota puede reportarla desde la página principal **sin registrarse**, con foto, especie, ubicación y un teléfono o correo.
  - Técnica: **usuario anónimo de Supabase Auth** (`signInAnonymously`; su token lleva `is_anonymous = true`). Así cada reporte sigue teniendo dueño y no cambian las reglas anteriores.
  - Límites para invitados (migración 4 + backend): solo reportes `found`; no registran mascotas; deben dejar contacto para publicar; **no ven reportes ni fotos ajenos** (D1 se mantiene) y no usan `app.html`.
  - En los reportes `found`, `color` y `size` pasan a ser opcionales (en `lost` siguen obligatorios).
  - El dueño de la mascota perdida confirma (D2) y entonces ve el contacto del invitado.
  - Riesgos aceptados para el prototipo (D5): los usuarios anónimos se acumulan (limpieza pendiente) y el spam solo lo frena el límite de Supabase (~30 invitados/hora por IP). Antes de la nube: añadir CAPTCHA (Turnstile/hCaptcha).
- **D6 — Leer anuncios de redes con Gemini (aprobada por Daniela, 2026-11-12):** en el formulario rápido, la persona puede pegar el **texto** de un anuncio que vio en redes. Gemini extrae especie, color, tamaño, raza, señas, lugar y fecha para llenar el reporte.
  - Es un extra **opcional**: solo aparece si `GEMINI_API_KEY` está en `backend/.env`. El requisito general ("no se necesita LLM generativo") se mantiene: el núcleo (coincidencias) no depende de Gemini.
  - **Plan gratuito** de la API de Gemini: Google puede usar y leer lo que se envía. Por eso solo se envía texto (nunca fotos ni capturas) y el backend **borra teléfonos, correos, enlaces y @usuarios antes de enviarlo** (`backend/app/anuncios.py`).
  - Llamada desde el backend (`POST /api/ads/extract`, requiere sesión, máximo 10 por persona por hora). La clave nunca llega al navegador.
  - El plan gratuito a veces responde 503 "high demand" (visto en la prueba real del 2026-11-12). El backend reintenta 2 veces, con 1 s y 2 s de pausa. Si sigue fallando, pide intentar luego o llenar a mano. El 429 (cuota agotada) no se reintenta.
  - La respuesta tiene un formato fijo (JSON con valores permitidos) y se valida. El texto del anuncio se trata como datos, no como instrucciones. Nada se publica sin que la persona lo revise.
  - No se pueden leer automáticamente las redes: Facebook cerró el acceso a grupos (2024), y el scraping viola sus condiciones y la Ley 1581 de 2012.
