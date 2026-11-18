-- PET Alert · Migración 6: "Es mi mascota", protección del contacto y comentarios.
--
-- Decisiones de Daniela (2026-11-18):
--   1. Botón "Es mi mascota" también en reportes encontrados que la IA no sugirió (origen 'claim').
--      Antes de enviarlo se muestra una advertencia y se pide una SEÑA que solo el dueño conoce.
--   2. Si quien encontró TIENE CUENTA, debe ACEPTAR la solicitud. Mientras no acepte, el dueño
--      solo ve su CORREO; el teléfono se comparte al aceptar.
--   3. Si quien encontró NO TIENE CUENTA (reporte rápido), no puede aceptar: se aplican los filtros
--      y, si los pasa, el dueño ve su teléfono.
--   4. Filtros para pedir un contacto: reporte de mascota perdida PUBLICADO, de la misma especie,
--      con foto propia (no casi idéntica a la de quien encontró), seña obligatoria y
--      máximo 3 solicitudes cada 24 horas.
--   5. Cualquier persona puede VER como máximo 3 teléfonos distintos cada 24 horas.
--   6. Comentarios en los reportes publicados. Se permiten teléfonos; no correos ni enlaces de chat.
--
-- Todo lo que decide quién ve qué vive aquí (en la base), no solo en la API.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. matches: nuevo estado 'requested' (esperando que quien encontró acepte)
-- ---------------------------------------------------------------------------
ALTER TABLE public.matches DROP CONSTRAINT matches_status_check;
ALTER TABLE public.matches DROP CONSTRAINT matches_decision;
ALTER TABLE public.matches
    ADD CONSTRAINT matches_status_check
        CHECK (status IN ('suggested', 'requested', 'confirmed', 'discarded')),
    ADD CONSTRAINT matches_decision
        CHECK ((status IN ('suggested', 'requested')) = (decided_at IS NULL));

-- 'ai' = la sugirió el motor; 'claim' = el dueño la pidió desde Explorar.
ALTER TABLE public.matches
    ADD COLUMN origin       text NOT NULL DEFAULT 'ai',
    ADD COLUMN claim_note   text,
    ADD COLUMN requested_at timestamptz;
ALTER TABLE public.matches
    ADD CONSTRAINT matches_origin_check CHECK (origin IN ('ai', 'claim')),
    ADD CONSTRAINT matches_claim_note_check
        CHECK (claim_note IS NULL OR char_length(claim_note) BETWEEN 8 AND 300),
    ADD CONSTRAINT matches_requested_fields
        CHECK (status <> 'requested' OR (requested_at IS NOT NULL AND claim_note IS NOT NULL));

-- Una solicitud manual puede no tener puntaje visual (p. ej. si la IA está apagada).
ALTER TABLE public.matches ALTER COLUMN visual_score DROP NOT NULL;
ALTER TABLE public.matches ALTER COLUMN total_score  DROP NOT NULL;

CREATE INDEX matches_requested_at_idx ON public.matches (requested_at) WHERE requested_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. Comentarios en reportes
-- ---------------------------------------------------------------------------
CREATE TABLE public.report_comments (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id  uuid NOT NULL REFERENCES public.reports (id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    body       text NOT NULL CHECK (char_length(btrim(body)) BETWEEN 2 AND 500),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX report_comments_report_idx ON public.report_comments (report_id, created_at);
CREATE INDEX report_comments_user_idx   ON public.report_comments (user_id, created_at DESC);
CREATE TRIGGER report_comments_updated_at BEFORE UPDATE ON public.report_comments
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.report_comments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.report_comments FROM PUBLIC, anon, authenticated;
GRANT SELECT, DELETE ON public.report_comments TO authenticated;

-- Se ven donde se ve el reporte (la política de reports se aplica dentro del EXISTS).
-- Los invitados (reporte rápido) no ven comentarios, igual que no ven reportes ajenos.
CREATE POLICY report_comments_select ON public.report_comments
    FOR SELECT TO authenticated
    USING (NOT (SELECT public.is_anonymous_user())
           AND EXISTS (SELECT 1 FROM public.reports r WHERE r.id = report_id));
-- Borra su autor o el dueño del reporte.
CREATE POLICY report_comments_delete ON public.report_comments
    FOR DELETE TO authenticated
    USING (user_id = (SELECT auth.uid())
           OR EXISTS (SELECT 1 FROM public.reports r
                       WHERE r.id = report_id AND r.user_id = (SELECT auth.uid())));
-- Crear: solo con add_report_comment (revisa contacto y límite de ritmo).

-- ---------------------------------------------------------------------------
-- 3. notifications: avisos de solicitud, aceptación y comentarios
-- ---------------------------------------------------------------------------
ALTER TABLE public.notifications DROP CONSTRAINT notifications_kind_check;
ALTER TABLE public.notifications ALTER COLUMN match_id DROP NOT NULL;
ALTER TABLE public.notifications
    ADD COLUMN report_id  uuid REFERENCES public.reports (id) ON DELETE CASCADE,
    ADD COLUMN comment_id uuid REFERENCES public.report_comments (id) ON DELETE CASCADE;
ALTER TABLE public.notifications
    ADD CONSTRAINT notifications_kind_check CHECK (kind IN (
        'new_match', 'match_requested', 'match_accepted', 'match_confirmed',
        'match_discarded', 'new_comment')),
    ADD CONSTRAINT notifications_target CHECK (
        CASE WHEN kind = 'new_comment' THEN comment_id IS NOT NULL AND report_id IS NOT NULL
             ELSE match_id IS NOT NULL END);
CREATE UNIQUE INDEX notifications_comment_once ON public.notifications (user_id, comment_id)
    WHERE comment_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. Registro de teléfonos vistos (límite: 3 distintos cada 24 horas)
-- ---------------------------------------------------------------------------
CREATE TABLE public.contact_views (
    viewer_id  uuid NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    match_id   uuid NOT NULL REFERENCES public.matches (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (viewer_id, match_id)
);
CREATE INDEX contact_views_recent_idx ON public.contact_views (viewer_id, created_at DESC);
ALTER TABLE public.contact_views ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.contact_views FROM PUBLIC, anon, authenticated;   -- solo backend

-- Volver a ver un teléfono ya visto no gasta cupo. Devuelve si se permite y, si no, desde cuándo.
CREATE FUNCTION public.reveal_phone(p_viewer uuid, p_match_id uuid)
RETURNS TABLE (allowed boolean, views_left integer, next_at timestamptz)
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_count  integer;
    v_oldest timestamptz;
BEGIN
    -- Una petición a la vez por persona, para que dos clics simultáneos no pasen el límite.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_viewer::text, 6));
    SELECT count(*), min(created_at) INTO v_count, v_oldest
      FROM public.contact_views
     WHERE viewer_id = p_viewer AND created_at > now() - interval '24 hours';
    IF EXISTS (SELECT 1 FROM public.contact_views WHERE viewer_id = p_viewer AND match_id = p_match_id) THEN
        RETURN QUERY SELECT true, greatest(3 - v_count, 0), NULL::timestamptz;
        RETURN;
    END IF;
    IF v_count >= 3 THEN
        RETURN QUERY SELECT false, 0, v_oldest + interval '24 hours';
        RETURN;
    END IF;
    INSERT INTO public.contact_views (viewer_id, match_id) VALUES (p_viewer, p_match_id);
    RETURN QUERY SELECT true, 3 - v_count - 1, NULL::timestamptz;
END;
$$;

-- ---------------------------------------------------------------------------
-- 5. Pedir el contacto ("Es mi mascota")
-- ---------------------------------------------------------------------------
-- Lógica común. NO se concede a nadie: la llaman request_match y claim_found_report.
CREATE FUNCTION public.match_request_internal(p_match_id uuid, p_uid uuid, p_note text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_note        text := btrim(coalesce(p_note, ''));
    v_status      text;
    v_visual      real;
    v_lost_id     uuid;
    v_found_id    uuid;
    v_lost_owner  uuid;
    v_found_owner uuid;
    v_lost_st     text;
    v_found_st    text;
    v_found_anon  boolean;
BEGIN
    SELECT m.status, m.visual_score, m.lost_report_id, m.found_report_id,
           lr.user_id, fr.user_id, lr.status, fr.status
      INTO v_status, v_visual, v_lost_id, v_found_id,
           v_lost_owner, v_found_owner, v_lost_st, v_found_st
      FROM public.matches m
      JOIN public.reports lr ON lr.id = m.lost_report_id
      JOIN public.reports fr ON fr.id = m.found_report_id
     WHERE m.id = p_match_id
       FOR UPDATE OF m, lr, fr;
    IF NOT FOUND OR v_lost_owner <> p_uid THEN
        RAISE EXCEPTION 'Coincidencia no disponible' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'suggested' THEN
        RAISE EXCEPTION 'Esta coincidencia ya fue solicitada o decidida';
    END IF;
    IF v_lost_st <> 'active' OR v_found_st <> 'active' THEN
        RAISE EXCEPTION 'Tu reporte de mascota perdida y el de quien la encontró deben estar publicados';
    END IF;

    -- Filtros (decisión 4)
    IF char_length(v_note) < 8 OR char_length(v_note) > 300 THEN
        RAISE EXCEPTION 'Escribe una seña particular de tu mascota (entre 8 y 300 caracteres)';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.report_photos
                    WHERE report_id = v_lost_id AND status = 'ready') THEN
        RAISE EXCEPTION 'Tu reporte de mascota perdida necesita al menos una foto tuya';
    END IF;
    IF v_visual IS NOT NULL AND v_visual >= 0.97 THEN
        RAISE EXCEPTION 'La foto de tu reporte es casi idéntica a la de quien la encontró. Sube una foto propia de tu mascota';
    END IF;
    IF (SELECT count(*) FROM public.matches m
          JOIN public.reports lr ON lr.id = m.lost_report_id
         WHERE lr.user_id = p_uid AND m.requested_at > now() - interval '24 hours') >= 3 THEN
        RAISE EXCEPTION 'Ya hiciste 3 solicitudes de contacto en las últimas 24 horas. Intenta más tarde';
    END IF;

    SELECT coalesce(u.is_anonymous, false) INTO v_found_anon
      FROM auth.users u WHERE u.id = v_found_owner;

    IF coalesce(v_found_anon, false) THEN
        -- Sin cuenta no puede aceptar: pasó los filtros, así que se confirma (decisión 3).
        UPDATE public.matches
           SET status = 'confirmed', claim_note = v_note, requested_at = now(),
               decided_by = p_uid, decided_at = now()
         WHERE id = p_match_id;
        UPDATE public.reports SET status = 'resolved', resolved_at = now()
         WHERE id IN (v_lost_id, v_found_id);
        INSERT INTO public.notifications (user_id, match_id, kind)
        VALUES (v_found_owner, p_match_id, 'match_confirmed')
        ON CONFLICT (user_id, match_id, kind) DO NOTHING;
        RETURN 'confirmed';
    END IF;

    UPDATE public.matches
       SET status = 'requested', claim_note = v_note, requested_at = now()
     WHERE id = p_match_id;
    INSERT INTO public.notifications (user_id, match_id, kind)
    VALUES (v_found_owner, p_match_id, 'match_requested')
    ON CONFLICT (user_id, match_id, kind) DO NOTHING;
    RETURN 'requested';
END;
$$;

-- Desde una coincidencia sugerida por la IA.
CREATE FUNCTION public.request_match(p_match_id uuid, p_note text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF auth.uid() IS NULL OR public.is_anonymous_user() THEN
        RAISE EXCEPTION 'Debes iniciar sesión con tu cuenta' USING ERRCODE = '42501';
    END IF;
    RETURN public.match_request_internal(p_match_id, auth.uid(), p_note);
END;
$$;

-- Desde Explorar: el dueño señala un reporte encontrado que la IA no le sugirió.
CREATE FUNCTION public.claim_found_report(
    p_found_report_id uuid,
    p_lost_report_id  uuid,
    p_note            text,
    p_model           text
)
RETURNS TABLE (match_id uuid, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
DECLARE
    v_uid      uuid := auth.uid();
    v_lost     public.reports%ROWTYPE;
    v_found    public.reports%ROWTYPE;
    v_existing public.matches%ROWTYPE;
    v_visual   double precision;
    v_km       double precision;
    v_id       uuid;
BEGIN
    IF v_uid IS NULL OR public.is_anonymous_user() THEN
        RAISE EXCEPTION 'Debes iniciar sesión con tu cuenta' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_lost  FROM public.reports WHERE id = p_lost_report_id;
    SELECT * INTO v_found FROM public.reports WHERE id = p_found_report_id;
    IF v_lost.id IS NULL OR v_lost.user_id <> v_uid OR v_lost.type <> 'lost' THEN
        RAISE EXCEPTION 'Elige uno de tus reportes de mascota perdida' USING ERRCODE = '42501';
    END IF;
    IF v_found.id IS NULL OR v_found.type <> 'found' OR v_found.status <> 'active' THEN
        RAISE EXCEPTION 'Este reporte ya no está disponible' USING ERRCODE = '42501';
    END IF;
    IF v_lost.status <> 'active' THEN
        RAISE EXCEPTION 'Publica tu reporte de mascota perdida antes de pedir el contacto';
    END IF;
    IF v_lost.species <> v_found.species THEN
        RAISE EXCEPTION 'Tu reporte y este son de especies distintas';
    END IF;
    IF v_found.user_id = v_uid THEN
        RAISE EXCEPTION 'Este reporte es tuyo';
    END IF;

    SELECT * INTO v_existing FROM public.matches
     WHERE lost_report_id = p_lost_report_id AND found_report_id = p_found_report_id;
    IF v_existing.id IS NOT NULL THEN
        IF v_existing.status <> 'suggested' THEN
            RAISE EXCEPTION 'Ya existe una solicitud o decisión para esta pareja de reportes';
        END IF;
        v_id := v_existing.id;
    ELSE
        -- Parecido de fotos (si hay huellas) y distancia aproximada, como el motor.
        SELECT max(1 - (a.embedding OPERATOR(extensions.<=>) b.embedding)) INTO v_visual
          FROM public.report_photos pa
          JOIN public.photo_embeddings a ON a.photo_id = pa.id AND a.model_name = p_model
          CROSS JOIN public.report_photos pb
          JOIN public.photo_embeddings b ON b.photo_id = pb.id AND b.model_name = p_model
         WHERE pa.report_id = p_lost_report_id AND pa.status = 'ready'
           AND pb.report_id = p_found_report_id AND pb.status = 'ready';
        v_km := 6371 * 2 * asin(sqrt(
              power(sin(radians((v_found.approx_lat - v_lost.approx_lat)::double precision) / 2), 2)
            + cos(radians(v_lost.approx_lat::double precision)) * cos(radians(v_found.approx_lat::double precision))
            * power(sin(radians((v_found.approx_lng - v_lost.approx_lng)::double precision) / 2), 2)));
        -- Ojo: greatest(NULL, 0) da 0 en PostgreSQL; sin huellas debe quedar NULL.
        IF v_visual IS NOT NULL THEN
            v_visual := least(greatest(v_visual, 0), 1);
        END IF;
        INSERT INTO public.matches (lost_report_id, found_report_id, model_name, origin,
                                    visual_score, distance_km, total_score)
        VALUES (p_lost_report_id, p_found_report_id, p_model, 'claim', v_visual, v_km,
                CASE WHEN v_visual IS NULL THEN NULL
                     ELSE least(0.75 * v_visual + 0.25 * exp(-v_km / 5), 1) END)
        RETURNING id INTO v_id;
    END IF;

    RETURN QUERY SELECT v_id, public.match_request_internal(v_id, v_uid, p_note);
END;
$$;

-- Quien encontró (con cuenta) acepta o rechaza la solicitud.
CREATE FUNCTION public.answer_match_request(p_match_id uuid, p_accept boolean)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_uid         uuid := auth.uid();
    v_status      text;
    v_lost_id     uuid;
    v_found_id    uuid;
    v_lost_owner  uuid;
    v_found_owner uuid;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Debes iniciar sesión' USING ERRCODE = '42501';
    END IF;
    SELECT m.status, m.lost_report_id, m.found_report_id, lr.user_id, fr.user_id
      INTO v_status, v_lost_id, v_found_id, v_lost_owner, v_found_owner
      FROM public.matches m
      JOIN public.reports lr ON lr.id = m.lost_report_id
      JOIN public.reports fr ON fr.id = m.found_report_id
     WHERE m.id = p_match_id
       FOR UPDATE OF m, lr, fr;
    IF NOT FOUND OR v_found_owner <> v_uid THEN
        RAISE EXCEPTION 'Coincidencia no disponible' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'requested' THEN
        RAISE EXCEPTION 'No hay una solicitud pendiente para esta coincidencia';
    END IF;
    IF p_accept THEN
        UPDATE public.matches SET status = 'confirmed', decided_by = v_uid, decided_at = now()
         WHERE id = p_match_id;
        UPDATE public.reports SET status = 'resolved', resolved_at = now()
         WHERE id IN (v_lost_id, v_found_id) AND status = 'active';
        INSERT INTO public.notifications (user_id, match_id, kind)
        VALUES (v_lost_owner, p_match_id, 'match_accepted')
        ON CONFLICT (user_id, match_id, kind) DO NOTHING;
        RETURN 'confirmed';
    END IF;
    UPDATE public.matches SET status = 'discarded', decided_by = v_uid, decided_at = now()
     WHERE id = p_match_id;
    INSERT INTO public.notifications (user_id, match_id, kind)
    VALUES (v_lost_owner, p_match_id, 'match_discarded')
    ON CONFLICT (user_id, match_id, kind) DO NOTHING;
    RETURN 'discarded';
END;
$$;

-- Descartar: ahora también sirve para que el dueño CANCELE una solicitud pendiente.
CREATE OR REPLACE FUNCTION public.discard_match(p_match_id uuid)
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
    IF v_status NOT IN ('suggested', 'requested') THEN
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

-- ---------------------------------------------------------------------------
-- 6. Agregar un comentario (sin correos ni enlaces de chat, con límite de ritmo)
-- ---------------------------------------------------------------------------
CREATE FUNCTION public.add_report_comment(p_report_id uuid, p_body text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_uid   uuid := auth.uid();
    v_body  text := btrim(coalesce(p_body, ''));
    v_owner uuid;
    v_st    text;
    v_id    uuid;
BEGIN
    IF v_uid IS NULL OR public.is_anonymous_user() THEN
        RAISE EXCEPTION 'Debes iniciar sesión con tu cuenta' USING ERRCODE = '42501';
    END IF;
    SELECT user_id, status INTO v_owner, v_st FROM public.reports WHERE id = p_report_id;
    IF v_owner IS NULL OR (v_st <> 'active' AND v_owner <> v_uid) THEN
        RAISE EXCEPTION 'Reporte no disponible' USING ERRCODE = '42501';
    END IF;
    IF v_st <> 'active' THEN
        RAISE EXCEPTION 'Solo se puede comentar en reportes publicados';
    END IF;
    IF char_length(v_body) < 2 OR char_length(v_body) > 500 THEN
        RAISE EXCEPTION 'El comentario debe tener entre 2 y 500 caracteres';
    END IF;
    -- Correos y enlaces de chat. Los teléfonos SÍ se permiten (decisión de Daniela).
    IF v_body ~* '[a-z0-9._%+\-]+\s*(@|\(at\)|\[at\]|\sarroba\s)\s*[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}'
       OR v_body ~* '(wa\.me|whatsapp\.com|t\.me/|api\.whatsapp)' THEN
        RAISE EXCEPTION 'No escribas correos ni enlaces de chat en los comentarios: el contacto se comparte de forma segura con "Es mi mascota"';
    END IF;
    IF (SELECT count(*) FROM public.report_comments
         WHERE user_id = v_uid AND created_at > now() - interval '10 minutes') >= 5 THEN
        RAISE EXCEPTION 'Escribiste muchos comentarios seguidos. Espera unos minutos';
    END IF;
    INSERT INTO public.report_comments (report_id, user_id, body)
    VALUES (p_report_id, v_uid, v_body)
    RETURNING id INTO v_id;
    IF v_owner <> v_uid THEN
        INSERT INTO public.notifications (user_id, report_id, comment_id, kind)
        VALUES (v_owner, p_report_id, v_id, 'new_comment');
    END IF;
    RETURN v_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- 7. Permisos
-- ---------------------------------------------------------------------------
-- confirm_match ya no se usa desde la app: confirmar pasa por request_match (con filtros).
REVOKE EXECUTE ON FUNCTION public.confirm_match(uuid) FROM authenticated;

REVOKE ALL ON FUNCTION public.match_request_internal(uuid, uuid, text)             FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reveal_phone(uuid, uuid)                             FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.request_match(uuid, text)                            FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.claim_found_report(uuid, uuid, text, text)           FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.answer_match_request(uuid, boolean)                  FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.add_report_comment(uuid, text)                       FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.reveal_phone(uuid, uuid)                    TO service_role;
GRANT EXECUTE ON FUNCTION public.request_match(uuid, text)                   TO authenticated;
GRANT EXECUTE ON FUNCTION public.claim_found_report(uuid, uuid, text, text)  TO authenticated;
GRANT EXECUTE ON FUNCTION public.answer_match_request(uuid, boolean)         TO authenticated;
GRANT EXECUTE ON FUNCTION public.add_report_comment(uuid, text)              TO authenticated;

COMMIT;
