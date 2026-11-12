# PET Alert

Plataforma web para encontrar mascotas perdidas. Las personas publican reportes de
mascotas **perdidas** o **encontradas** con fotos y ubicación, y el sistema sugiere
**posibles** coincidencias (nunca afirma que es el mismo animal).

- **Frontend:** `index.html` (página principal) y `app.html` (aplicación), en HTML, CSS y JavaScript sin framework.
- **Backend:** Python + FastAPI (`backend/`). El mismo servidor entrega las páginas y la API.
- **Base de datos, cuentas y fotos:** Supabase (PostgreSQL, Auth y Storage privado).

> Estado actual: ver [PROGRESO.md](PROGRESO.md). El motor que **calcula** las coincidencias
> con visión artificial todavía no está hecho (etapas 6 y 7).

---

## 1. Requisitos

| Qué | Para qué | Cómo comprobarlo |
|---|---|---|
| Windows 10/11 | sistema del proyecto | — |
| Python 3.12 o superior | ejecutar el backend | `python --version` |
| Git | descargar y guardar cambios | `git --version` |
| Un proyecto de Supabase | base de datos, cuentas y fotos | [supabase.com](https://supabase.com) |
| Microsoft Edge | solo para las pruebas del navegador | viene con Windows |

No se necesita GPU ni Node.js.

---

## 2. Instalación (solo la primera vez)

Todos los comandos se ejecutan en **PowerShell**, desde la carpeta del proyecto.

### 2.1 Crear el entorno de Python e instalar dependencias

```powershell
python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt
```

- `requirements.txt`: lo que necesita el servidor (~15 MB).
- `requirements-dev.txt`: lo que necesitan las pruebas (~45 MB). Si solo vas a usar la app, puedes omitirlo.

### 2.2 Configurar las claves de Supabase

1. Copia la plantilla:
   ```powershell
   Copy-Item backend\.env.example backend\.env
   ```
2. Abre `backend\.env` y completa los 3 valores. Están en **Supabase → Project Settings → API Keys**:
   - `SUPABASE_URL`: la dirección del proyecto (`https://xxxx.supabase.co`).
   - `SUPABASE_PUBLISHABLE_KEY`: la clave pública (`sb_publishable_...`).
   - `SUPABASE_SECRET_KEY`: la clave secreta (`sb_secret_...`).

Opcional: `GEMINI_API_KEY`, para la opción "¿Lo viste en un anuncio de redes?" del formulario rápido.
Se crea gratis en [Google AI Studio](https://aistudio.google.com/apikey). Sin ella, esa opción no aparece.
En el plan gratuito Google puede usar lo que se envía; por eso solo se envía texto y antes se borran
teléfonos, correos y enlaces.

Opcional: `PUBLIC_SITE_URL` (la dirección pública, p. ej. `https://tu-dominio.com`). En tu computador
déjala vacía; en la nube es la que aparece en Google y en la vista previa al compartir el enlace.

> ⚠️ `backend\.env` **nunca** se sube a git (está en `.gitignore`). La clave secreta no se comparte
> con nadie ni se pega en el frontend.

### 2.3 Preparar la base de datos (una sola vez por proyecto de Supabase)

En **Supabase → SQL Editor**, ejecuta **en orden** el contenido de estos archivos:

1. `supabase/migrations/20261023000001_esquema_base.sql`
2. `supabase/migrations/20261023000002_seguridad_rls.sql`
3. `supabase/migrations/20261023000003_storage.sql`
4. `supabase/migrations/20261112000004_reporte_rapido_anonimo.sql` (reporte rápido sin cuenta)

### 2.4 Configurar el inicio de sesión en Supabase

En **Supabase → Authentication → URL Configuration**:
- **Site URL:** `http://localhost:8000`
- **Redirect URLs:** agrega `http://localhost:8000/app.html`

En **Supabase → Authentication → Sign In / Providers**, activa **Allow anonymous sign-ins**.
Lo usa el formulario "Encontré una mascota" de la página principal para que alguien reporte
sin crear cuenta (Supabase le crea un usuario invitado, sin correo ni contraseña).

---

## 3. Encender el proyecto ▶️

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000 --reload --reload-dir backend
```

Cuando veas `Application startup complete.`, abre en el navegador:

| Dirección | Qué es |
|---|---|
| http://localhost:8000 | página principal (registro) |
| http://localhost:8000/app.html | aplicación (iniciar sesión, reportes, mapa, avisos) |
| http://localhost:8000/docs | lista interactiva de las rutas de la API |

- `--reload` reinicia el servidor solo cuando cambias código de `backend/`.
  Los cambios en HTML, CSS o JS se ven con solo recargar la página (F5).
- **Para apagarlo:** en la ventana de PowerShell presiona `Ctrl + C`.

---

## 4. Probar la aplicación paso a paso

0. **Sin cuenta:** en http://localhost:8000, sección **Encontré una mascota**, sube una foto, marca el
   lugar en el mapa, deja un teléfono o correo y presiona **Publicar reporte**.
1. Entra a http://localhost:8000 y crea una cuenta en el formulario **Registro**.
2. Si Supabase pide confirmar el correo, abre el enlace que te llega (revisa el spam).
3. Inicia sesión en http://localhost:8000/app.html.
4. **Nuevo reporte:** elige perdida o encontrada, completa los datos, marca el lugar en el mapa,
   sube de 1 a 5 fotos y presiona **Publicar reporte**.
5. Con una **segunda cuenta** (otro correo, o una ventana de incógnito) verás ese reporte en **Explorar**.

> Las coincidencias **todavía no aparecen solas**: el motor que las calcula llegará en las etapas 6 y 7.

---

## 5. Ejecutar las pruebas

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -v
```

Necesitan internet y `backend\.env`. Crean usuarios temporales en Supabase y **los borran al terminar**
(con sus fotos). Hay 44 pruebas:

- `test_seguridad_supabase.py`: reglas de seguridad de la base de datos (RLS).
- `test_api.py`: la API de punta a punta.
- `test_reporte_anonimo.py`: el reporte rápido sin cuenta y los límites de los invitados.
- `test_anuncios.py`: lectura de anuncios con Gemini (Gemini se simula: no gasta cuota).
- `test_frontend_e2e.py`: la página en un navegador real (Edge).

Si el modo invitado está desactivado en Supabase, las pruebas del reporte sin cuenta salen
como **skipped** (omitidas), no como aprobadas.

---

## 6. Problemas frecuentes

| Problema | Solución |
|---|---|
| `Faltan SUPABASE_URL...` al encender | falta completar `backend\.env` (paso 2.2) |
| `[WinError 10048]` o "address already in use" | el puerto 8000 está ocupado: cierra el otro servidor o usa `--port 8001` (el registro por correo espera el 8000) |
| La página dice "No se pudo conectar con el servidor" | el backend no está encendido (paso 3) |
| No llega el correo de confirmación | el correo gratuito de Supabase envía muy pocos por hora: espera, o para pruebas desactiva **Authentication → Sign In / Providers → Email → Confirm email** |
| "Correo o contraseña incorrectos" | revisa los datos o crea la cuenta primero |
| "El reporte sin cuenta está desactivado" | activa **Allow anonymous sign-ins** (paso 2.4) |
| "Usar mi ubicación" no funciona en el celular | el navegador solo da la ubicación en `localhost` o `https`; marca el punto en el mapa |
| `python` no se reconoce | instala Python desde python.org y marca "Add python to PATH" |

---

## 7. Estructura del proyecto

```
proyecto_peta-ert_ia/
├─ index.html          página principal (landing + registro)
├─ app.html            aplicación
├─ css/                estilos (estilos.css compartido, app.css de la app)
├─ js/                 sesion.js · registro.js · reporte-rapido.js · mapa.js · app.js
├─ img/                imágenes
├─ backend/
│  ├─ app/             API FastAPI (main.py, routers/, schemas.py, supabase.py…)
│  ├─ tests/           pruebas
│  ├─ requirements.txt · requirements-dev.txt
│  └─ .env.example     plantilla de configuración (el .env real no se sube)
├─ supabase/migrations/ SQL de la base de datos
├─ docs/arquitectura.md diseño del sistema
└─ PROGRESO.md         qué está hecho, qué falta y cómo verificarlo
```
