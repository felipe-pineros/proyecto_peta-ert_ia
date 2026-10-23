# Backend FastAPI de PETA-ERT-IA

Este backend añade autenticación por correo/contraseña, creación y consulta de reportes, validación de fotografías y transiciones protegidas. Sirve la página `index.html` y los recursos de `img/` en el mismo origen; no expone el resto del repositorio como archivos estáticos.

## Configuración local en Windows

1. Copia `backend/.env.example` como `backend/.env` y completa las variables desde la configuración de tu proyecto Supabase:
   - `SUPABASE_URL`: URL del proyecto.
   - `SUPABASE_ANON_KEY`: clave pública usada por Auth y por las consultas con JWT del usuario.
   - `SUPABASE_SERVICE_ROLE_KEY`: clave privada del servidor. No la pegues en `index.html`, archivos versionados, imágenes Docker ni mensajes/logs.
   - `PHOTO_SIGNED_URL_TTL_SECONDS`: vencimiento del enlace de imagen; el backend limita el valor a 30–900 segundos.
2. Desde PowerShell, en la raíz del repositorio:

   ```powershell
   py -m venv backend\.venv
   .\backend\.venv\Scripts\Activate.ps1
   python -m pip install -r backend\requirements.txt
   python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
   ```

3. Abre `http://127.0.0.1:8000/`. `/api/health` es una comprobación local sin conexión a Supabase.

La migración aún debe ser revisada y aplicada por separado en un entorno de desarrollo autorizado. Esta guía no ejecuta ni aplica SQL.

## Límite de confianza de `service_role`

FastAPI valida cada JWT consultando Supabase Auth y obtiene de esa respuesta el ID del usuario. Solo después invoca RPCs con nombres fijos. La clave `service_role` se usa dentro del servidor para:

- crear la fila de foto pendiente;
- subir y retirar objetos del bucket privado;
- marcar una foto `ready` tras decodificarla, limitarla y volverla a codificar con Pillow;
- publicar, resolver o retirar un reporte;
- comprobar acceso a una foto antes de crear una URL firmada.

Las funciones SQL vuelven a comparar el ID de usuario validado con la propiedad y el estado guardados. No hay endpoint de SQL/RPC arbitrario. `service_role` puede eludir RLS si la credencial se filtra; por eso solo vive en el proceso FastAPI y no en el navegador. La base recibe `p_user_id` de la API; su seguridad depende de que ningún endpoint permita al cliente elegir ese valor libremente.

El navegador puede registrarse e iniciar sesión a través de FastAPI y consultar sus reportes o reportes activos mediante el JWT del usuario y RLS. No escribe objetos de Storage, no marca fotos como listas, no cambia estados ni genera URLs firmadas directamente.

## Flujo de foto y recuperación

FastAPI registra `pending`, limita la lectura a 10 MiB, detecta el formato real con Pillow, verifica que se pueda decodificar, limita a 6000 píxeles por lado y 16 megapíxeles, aplica orientación EXIF y genera JPEG sin copiar metadatos EXIF. Después sube el archivo con una ruta UUID no reutilizable y pide la transición a `ready`. La publicación requiere una foto lista cuyo objeto exista.

PostgreSQL y Storage no comparten transacción. Ante un fallo, FastAPI intenta eliminar el objeto mediante Storage y finaliza el borrado del metadato solo si Storage ya no contiene el objeto. Si falla la limpieza, conserva el registro para reintentar mediante el endpoint autenticado de recuperación descrito abajo.

No se implementa eliminación de cuentas ni borrado de reportes. Las claves foráneas actuales impiden eliminar usuarios con reportes asociados.

## Límites y recuperación

El cuerpo multipart se limita antes de que Starlette procese el formulario: 10 MiB de imagen más 256 KiB para el contenedor multipart. Si `Content-Length` está presente, debe ser numérico, no negativo, estar dentro del máximo y coincidir con los bytes recibidos. Si el cliente se desconecta antes de completar el cuerpo, la solicitud no se entrega a FastAPI/Starlette. Sin `Content-Length`, el contador de bytes sigue imponiendo el máximo. El middleware permite como máximo tres solicitudes multipart simultáneas por proceso; con varios workers el límite total es tres por worker. Los cuerpos se mantienen temporalmente en memoria.

El proxy inverso o balanceador debe imponer su propio máximo de cuerpo de al menos el límite de la API (10 MiB + 256 KiB), rechazar longitudes inconsistentes y definir timeouts de recepción y respuesta acordes con la conexión y el procesamiento esperado. Esos valores dependen del proxy y deben validarse allí; el middleware de la aplicación no puede limitar bytes que el proxy ya haya aceptado. No hay un timeout de Pillow: `asyncio.to_thread` no puede detener un hilo de Pillow al cancelar el await. El await se protege con `shield` y, si se cancela la petición, espera a que termine el hilo antes de liberar el cupo de concurrencia. El tamaño del archivo, los píxeles y las dimensiones se limitan antes/durante la decodificación.

Ante un fallo conocido antes de iniciar la subida a Storage, FastAPI registra una intención `deleting`, borra solo la ruta UUID exacta y elimina el metadato cuando Storage confirma el borrado (o que el objeto ya no existe). Si la subida empezó y su resultado es incierto, conserva la fila `pending`; una carga que se queda `pending` por una caída del proceso también queda para revisión. Ninguna fila `pending` se borra por antigüedad. La RPC de recuperación solo reclama hasta 100 fotos `deleting` en borradores propios cuyo lease de limpieza expiró, con bloqueo de filas `SKIP LOCKED`; en cada reintento elimina la ruta exacta almacenada y finaliza el metadato solo tras confirmar que el objeto no existe. Las cargas `pending` se contabilizan como `pending_review` y no se alteran automáticamente. No se escanea ni elimina objetos sin metadatos; cualquier huérfano de Storage necesita una revisión explícita antes de actuar.

La respuesta de borrado de foto es idempotente para identificadores ausentes o ajenos: ambos producen el mismo resultado externo. El flujo de dos fases conserva el registro `deleting` si Storage o la finalización de PostgreSQL fallan, para permitir un reintento seguro.

La interfaz puede recuperar borradores propios tras recargar y continuar sus fotos. En esta fase los datos guardados se muestran bloqueados; editarlos requiere una futura operación específica. Las respuestas de la API omiten el UUID del creador y las consultas del navegador a `report_photos` solo reciben identificadores, el reporte y el estado; no se concede al rol del navegador acceso a las rutas internas de Storage.

Antes de aplicar la migración, revisa todas las políticas existentes sobre `storage.objects` para el bucket `pet-report-photos`. La migración solo elimina tres nombres conocidos y no presupone que sean las únicas políticas permisivas. Confirma que ninguna política restante permita a `anon` o `authenticated` leer, insertar, actualizar o eliminar objetos del bucket.
