# Base de datos (Supabase)

Las migraciones de `migrations/` crean todo lo descrito en `docs/arquitectura.md`.
Deben ejecutarse **en orden** y **una sola vez** por proyecto:

| Orden | Archivo | Qué crea |
|---|---|---|
| 1 | `20261023000001_esquema_base.sql` | tablas, restricciones, índices y triggers |
| 2 | `20261023000002_seguridad_rls.sql` | permisos, reglas RLS y funciones de estado |
| 3 | `20261023000003_storage.sql` | bucket privado `report-photos` |
| 4 | `20261112000004_reporte_rapido_anonimo.sql` | reporte rápido sin cuenta (invitados) |
| 5 | `20261117000005_motor_coincidencias.sql` | funciones del motor de coincidencias |
| 6 | `20261118000006_solicitudes_contacto_comentarios.sql` | "Es mi mascota" con aceptación, filtros y límite de 3 teléfonos cada 24 h; comentarios en reportes |

## Probarlas antes en tu computador (opcional)

Con Docker Desktop encendido, desde Git Bash en la raíz del repositorio:

```sh
sh supabase/pruebas_locales/probar.sh
```

Crea un PostgreSQL **temporal** que imita a Supabase, aplica todas las migraciones, prueba los
escenarios de `pruebas_locales/99_escenarios.sql` (solicitudes, aceptación, límites y comentarios)
y lo borra al terminar. Debe terminar con `=== TODOS LOS ESCENARIOS PASARON ===`. No toca tu Supabase real.

## Cómo aplicarlas (sin instalar nada)

1. En Supabase abre **SQL Editor** → **New query**.
2. Abre el archivo 1 en VS Code, copia **todo** su contenido (`Ctrl+A`, `Ctrl+C`), pégalo y pulsa **Run**.
3. Debe decir *Success. No rows returned*. Repite con los archivos 2 y 3.

Si un archivo da error, no se aplica nada de ese archivo (cada uno va dentro de `BEGIN … COMMIT`). En ese caso copia el mensaje de error y no sigas con el siguiente.

## Cómo verificar

Desde la raíz del repositorio, con las claves ya puestas en `backend/.env`:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -v
```

Las pruebas crean dos usuarios temporales (`prueba-rls-…@example.com`), comprueban los permisos y los borran al terminar.
