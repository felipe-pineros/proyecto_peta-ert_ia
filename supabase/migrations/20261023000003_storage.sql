-- PET Alert · Migración 3 de 3: bucket PRIVADO para las fotos.
-- No se crea ninguna política sobre storage.objects para este bucket:
-- el navegador no puede leer ni subir archivos directamente. Solo el backend
-- (secret key) sube fotos y genera URLs firmadas de pocos minutos.

BEGIN;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('report-photos', 'report-photos', false, 10485760, ARRAY['image/jpeg'])
ON CONFLICT (id) DO UPDATE
SET public             = false,
    file_size_limit    = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

COMMIT;
