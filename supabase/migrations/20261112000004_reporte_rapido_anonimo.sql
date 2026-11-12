-- PET Alert · Migración 4: reporte rápido de mascota encontrada SIN crear cuenta.
--
-- Quien encuentra una mascota en la calle puede reportarla desde la página principal
-- con solo foto + ubicación + contacto. Por debajo, Supabase Auth le crea un usuario
-- ANÓNIMO (sin correo ni contraseña; claim `is_anonymous` = true en su token). Así
-- cada reporte sigue teniendo dueño y todas las reglas de las migraciones 1-3 siguen
-- valiendo. Esta migración solo añade límites para los usuarios anónimos:
--   1. Solo crean reportes de mascota ENCONTRADA (no registran mascotas ni reportes perdidos).
--   2. No ven los reportes ni las fotos de los demás (se mantiene la decisión D1).
--   3. No pueden publicar sin dejar un teléfono o un correo de contacto.
-- Además, color y tamaño pasan a ser opcionales en los reportes de mascota encontrada.
--
-- REQUISITO MANUAL: Supabase → Authentication → Sign In / Providers →
-- activar "Allow anonymous sign-ins".

BEGIN;

-- ---------------------------------------------------------------------------
-- ¿El usuario de esta petición es anónimo? (false para el backend con secret key)
-- ---------------------------------------------------------------------------
CREATE FUNCTION public.is_anonymous_user()
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    SELECT coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false);
$$;

REVOKE ALL ON FUNCTION public.is_anonymous_user() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_anonymous_user() TO authenticated;

-- ---------------------------------------------------------------------------
-- Color y tamaño: opcionales solo en reportes de mascota encontrada.
-- ---------------------------------------------------------------------------
ALTER TABLE public.reports ALTER COLUMN color DROP NOT NULL;
ALTER TABLE public.reports ALTER COLUMN size  DROP NOT NULL;
ALTER TABLE public.reports ADD CONSTRAINT reports_lost_needs_description
    CHECK (type = 'found' OR (color IS NOT NULL AND size IS NOT NULL));

-- ---------------------------------------------------------------------------
-- Políticas: se reemplazan las de la migración 2 añadiendo la condición anónima.
-- ---------------------------------------------------------------------------
DROP POLICY pets_insert_own ON public.pets;
CREATE POLICY pets_insert_own ON public.pets
    FOR INSERT TO authenticated
    WITH CHECK (owner_id = (SELECT auth.uid()) AND NOT (SELECT public.is_anonymous_user()));

DROP POLICY reports_select_own_or_active ON public.reports;
CREATE POLICY reports_select_own_or_active ON public.reports
    FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid())
           OR (status = 'active' AND NOT (SELECT public.is_anonymous_user())));

DROP POLICY reports_insert_own_draft ON public.reports;
CREATE POLICY reports_insert_own_draft ON public.reports
    FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT auth.uid()) AND status = 'draft'
                AND (type = 'found' OR NOT (SELECT public.is_anonymous_user())));

DROP POLICY report_photos_select_own_or_active ON public.report_photos;
CREATE POLICY report_photos_select_own_or_active ON public.report_photos
    FOR SELECT TO authenticated
    USING (
        user_id = (SELECT auth.uid())
        OR (status = 'ready' AND NOT (SELECT public.is_anonymous_user()) AND EXISTS (
            SELECT 1 FROM public.reports r WHERE r.id = report_id AND r.status = 'active'))
    );

-- ---------------------------------------------------------------------------
-- Publicar: igual que antes + un usuario anónimo debe dejar teléfono o correo.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.publish_report(p_report_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_uid    uuid := auth.uid();
    v_owner  uuid;
    v_status text;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Debes iniciar sesión' USING ERRCODE = '42501';
    END IF;
    SELECT user_id, status INTO v_owner, v_status
      FROM public.reports WHERE id = p_report_id FOR UPDATE;
    IF NOT FOUND OR v_owner <> v_uid THEN
        RAISE EXCEPTION 'Reporte no disponible' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'draft' THEN
        RAISE EXCEPTION 'Solo se puede publicar un borrador';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.report_photos
                    WHERE report_id = p_report_id AND status = 'ready') THEN
        RAISE EXCEPTION 'Agrega al menos una foto antes de publicar';
    END IF;
    IF public.is_anonymous_user() AND NOT EXISTS (
        SELECT 1 FROM public.report_private
         WHERE report_id = p_report_id
           AND (contact_phone IS NOT NULL OR contact_email IS NOT NULL)) THEN
        RAISE EXCEPTION 'Deja un teléfono o un correo para que el dueño pueda contactarte';
    END IF;
    UPDATE public.reports SET status = 'active', published_at = now() WHERE id = p_report_id;
END;
$$;

REVOKE ALL ON FUNCTION public.publish_report(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.publish_report(uuid) TO authenticated;

COMMIT;
