-- PET Alert · Migración 2 de 3: permisos, RLS y funciones de cambio de estado.
-- Principio: el navegador (roles anon/authenticated) solo recibe lo mínimo.
-- El backend usa la secret key (rol service_role, que salta RLS) solo para
-- fotos, embeddings, coincidencias y notificaciones.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Quitar los permisos amplios que Supabase da por defecto a tablas nuevas.
-- ---------------------------------------------------------------------------
REVOKE ALL ON TABLE
    public.profiles, public.species, public.pets, public.reports, public.report_private,
    public.report_photos, public.photo_embeddings, public.matches, public.notifications
FROM PUBLIC, anon, authenticated;

-- Las funciones de trigger nunca se llaman directamente.
REVOKE ALL ON FUNCTION public.set_updated_at()      FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.enforce_photo_limit() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.check_match_pair()    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.handle_new_user()     FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. Activar RLS en todas las tablas (sin política = nadie ve nada).
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.species          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pets             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_private   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_photos    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.photo_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.matches          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications    ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 3. Permisos por columna + políticas por fila, tabla por tabla.
--    anon (visitante sin sesión) no recibe nada: decisión D1.
-- ---------------------------------------------------------------------------

-- profiles: cada uno ve y edita solo su perfil. Se crea por trigger.
GRANT SELECT ON public.profiles TO authenticated;
GRANT UPDATE (display_name, phone) ON public.profiles TO authenticated;
CREATE POLICY profiles_select_own ON public.profiles
    FOR SELECT TO authenticated USING (id = (SELECT auth.uid()));
CREATE POLICY profiles_update_own ON public.profiles
    FOR UPDATE TO authenticated
    USING (id = (SELECT auth.uid())) WITH CHECK (id = (SELECT auth.uid()));

-- species: catálogo de solo lectura.
GRANT SELECT ON public.species TO authenticated;
CREATE POLICY species_select_all ON public.species
    FOR SELECT TO authenticated USING (true);

-- pets: solo el dueño. owner_id lo pone la base (DEFAULT auth.uid()).
-- La especie no se puede cambiar después de crear la mascota.
GRANT SELECT ON public.pets TO authenticated;
GRANT INSERT (name, species, breed, color, size, distinctive_features) ON public.pets TO authenticated;
GRANT UPDATE (name, breed, color, size, distinctive_features) ON public.pets TO authenticated;
CREATE POLICY pets_select_own ON public.pets
    FOR SELECT TO authenticated USING (owner_id = (SELECT auth.uid()));
CREATE POLICY pets_insert_own ON public.pets
    FOR INSERT TO authenticated WITH CHECK (owner_id = (SELECT auth.uid()));
CREATE POLICY pets_update_own ON public.pets
    FOR UPDATE TO authenticated
    USING (owner_id = (SELECT auth.uid())) WITH CHECK (owner_id = (SELECT auth.uid()));

-- reports: el dueño ve todos los suyos; los demás usuarios con sesión, solo los activos.
-- user_id y status NO se pueden escribir desde la app: el estado cambia solo con las
-- funciones de la sección 4. Solo se edita mientras está en draft o active.
GRANT SELECT ON public.reports TO authenticated;
GRANT INSERT (pet_id, type, species, breed, color, size, distinctive_features,
              event_at, location_label, approx_lat, approx_lng)
    ON public.reports TO authenticated;
GRANT UPDATE (breed, color, size, distinctive_features, event_at, location_label,
              approx_lat, approx_lng)
    ON public.reports TO authenticated;
CREATE POLICY reports_select_own_or_active ON public.reports
    FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid()) OR status = 'active');
CREATE POLICY reports_insert_own_draft ON public.reports
    FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT auth.uid()) AND status = 'draft');
CREATE POLICY reports_update_own_open ON public.reports
    FOR UPDATE TO authenticated
    USING (user_id = (SELECT auth.uid()) AND status IN ('draft', 'active'))
    WITH CHECK (user_id = (SELECT auth.uid()) AND status IN ('draft', 'active'));

-- report_private: solo el dueño del reporte.
GRANT SELECT ON public.report_private TO authenticated;
GRANT INSERT (report_id, exact_lat, exact_lng, contact_phone, contact_email)
    ON public.report_private TO authenticated;
GRANT UPDATE (exact_lat, exact_lng, contact_phone, contact_email)
    ON public.report_private TO authenticated;
CREATE POLICY report_private_select_own ON public.report_private
    FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.reports r
                    WHERE r.id = report_id AND r.user_id = (SELECT auth.uid())));
CREATE POLICY report_private_insert_own ON public.report_private
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.reports r
                         WHERE r.id = report_id AND r.user_id = (SELECT auth.uid())
                           AND r.status IN ('draft', 'active')));
CREATE POLICY report_private_update_own ON public.report_private
    FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.reports r
                    WHERE r.id = report_id AND r.user_id = (SELECT auth.uid())
                      AND r.status IN ('draft', 'active')))
    WITH CHECK (EXISTS (SELECT 1 FROM public.reports r
                         WHERE r.id = report_id AND r.user_id = (SELECT auth.uid())
                           AND r.status IN ('draft', 'active')));

-- report_photos: lectura de metadatos (sin la ruta interna de Storage).
-- Crear, marcar como lista o borrar fotos lo hace solo el backend.
GRANT SELECT (id, report_id, status, width, height, created_at) ON public.report_photos TO authenticated;
CREATE POLICY report_photos_select_own_or_active ON public.report_photos
    FOR SELECT TO authenticated
    USING (
        user_id = (SELECT auth.uid())
        OR (status = 'ready' AND EXISTS (
            SELECT 1 FROM public.reports r WHERE r.id = report_id AND r.status = 'active'))
    );

-- photo_embeddings: sin acceso desde el navegador (solo backend).

-- matches: las dos personas involucradas pueden verla. Decidir pasa por funciones.
GRANT SELECT ON public.matches TO authenticated;
CREATE POLICY matches_select_involved ON public.matches
    FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.reports r
         WHERE r.id IN (lost_report_id, found_report_id)
           AND r.user_id = (SELECT auth.uid())
    ));

-- notifications: el destinatario las ve y solo puede marcarlas como leídas.
GRANT SELECT ON public.notifications TO authenticated;
GRANT UPDATE (read_at) ON public.notifications TO authenticated;
CREATE POLICY notifications_select_own ON public.notifications
    FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
CREATE POLICY notifications_update_own ON public.notifications
    FOR UPDATE TO authenticated
    USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));

-- ---------------------------------------------------------------------------
-- 4. Funciones de cambio de estado (las llama el backend con el token del usuario).
--    SECURITY DEFINER: pueden cambiar status aunque el usuario no tenga permiso
--    directo, pero cada una comprueba primero auth.uid() y el estado actual.
-- ---------------------------------------------------------------------------

-- Publicar: draft → active. Requiere al menos una foto lista.
CREATE FUNCTION public.publish_report(p_report_id uuid)
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
    UPDATE public.reports SET status = 'active', published_at = now() WHERE id = p_report_id;
END;
$$;

-- Retirar: draft/active → withdrawn.
CREATE FUNCTION public.withdraw_report(p_report_id uuid)
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
    IF v_status NOT IN ('draft', 'active') THEN
        RAISE EXCEPTION 'Este reporte ya está cerrado';
    END IF;
    UPDATE public.reports SET status = 'withdrawn' WHERE id = p_report_id;
END;
$$;

-- Confirmar: solo el dueño del reporte PERDIDO (decisión D2).
-- La coincidencia pasa a confirmed y ambos reportes a resolved.
CREATE FUNCTION public.confirm_match(p_match_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_uid          uuid := auth.uid();
    v_status       text;
    v_lost_id      uuid;
    v_found_id     uuid;
    v_lost_owner   uuid;
    v_found_owner  uuid;
    v_lost_status  text;
    v_found_status text;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Debes iniciar sesión' USING ERRCODE = '42501';
    END IF;
    SELECT m.status, m.lost_report_id, m.found_report_id,
           lr.user_id, fr.user_id, lr.status, fr.status
      INTO v_status, v_lost_id, v_found_id,
           v_lost_owner, v_found_owner, v_lost_status, v_found_status
      FROM public.matches m
      JOIN public.reports lr ON lr.id = m.lost_report_id
      JOIN public.reports fr ON fr.id = m.found_report_id
     WHERE m.id = p_match_id
       FOR UPDATE OF m, lr, fr;
    IF NOT FOUND OR v_lost_owner <> v_uid THEN
        RAISE EXCEPTION 'Coincidencia no disponible' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'suggested' THEN
        RAISE EXCEPTION 'Esta coincidencia ya fue decidida';
    END IF;
    IF v_lost_status <> 'active' OR v_found_status <> 'active' THEN
        RAISE EXCEPTION 'Ambos reportes deben estar activos';
    END IF;
    UPDATE public.matches
       SET status = 'confirmed', decided_by = v_uid, decided_at = now()
     WHERE id = p_match_id;
    UPDATE public.reports
       SET status = 'resolved', resolved_at = now()
     WHERE id IN (v_lost_id, v_found_id);
    INSERT INTO public.notifications (user_id, match_id, kind)
    VALUES (v_found_owner, p_match_id, 'match_confirmed')
    ON CONFLICT (user_id, match_id, kind) DO NOTHING;
END;
$$;

-- Descartar: cualquiera de las dos personas. Se avisa a la otra.
CREATE FUNCTION public.discard_match(p_match_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_uid         uuid := auth.uid();
    v_status      text;
    v_lost_owner  uuid;
    v_found_owner uuid;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Debes iniciar sesión' USING ERRCODE = '42501';
    END IF;
    SELECT m.status, lr.user_id, fr.user_id
      INTO v_status, v_lost_owner, v_found_owner
      FROM public.matches m
      JOIN public.reports lr ON lr.id = m.lost_report_id
      JOIN public.reports fr ON fr.id = m.found_report_id
     WHERE m.id = p_match_id
       FOR UPDATE OF m;
    IF NOT FOUND OR v_uid NOT IN (v_lost_owner, v_found_owner) THEN
        RAISE EXCEPTION 'Coincidencia no disponible' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'suggested' THEN
        RAISE EXCEPTION 'Esta coincidencia ya fue decidida';
    END IF;
    UPDATE public.matches
       SET status = 'discarded', decided_by = v_uid, decided_at = now()
     WHERE id = p_match_id;
    INSERT INTO public.notifications (user_id, match_id, kind)
    VALUES (CASE WHEN v_uid = v_lost_owner THEN v_found_owner ELSE v_lost_owner END,
            p_match_id, 'match_discarded')
    ON CONFLICT (user_id, match_id, kind) DO NOTHING;
END;
$$;

REVOKE ALL ON FUNCTION public.publish_report(uuid)  FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.withdraw_report(uuid) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.confirm_match(uuid)   FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.discard_match(uuid)   FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.publish_report(uuid)  TO authenticated;
GRANT EXECUTE ON FUNCTION public.withdraw_report(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.confirm_match(uuid)   TO authenticated;
GRANT EXECUTE ON FUNCTION public.discard_match(uuid)   TO authenticated;

COMMIT;
