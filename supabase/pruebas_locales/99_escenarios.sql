-- Escenarios de la migración 6 (se ejecuta DESPUÉS de las migraciones 1–6).
\set ON_ERROR_STOP 1
\set QUIET 1

CREATE SCHEMA t;
GRANT USAGE ON SCHEMA t TO authenticated, service_role;
CREATE FUNCTION t.expect_error(q text, pat text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE q;
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM !~* pat THEN
            RAISE EXCEPTION 'Error inesperado en [%]: %', q, SQLERRM;
        END IF;
        RAISE NOTICE 'OK (falla esperada): %', left(SQLERRM, 110);
        RETURN;
    END;
    RAISE EXCEPTION 'Debió fallar y no falló: %', q;
END $$;
CREATE FUNCTION t.ok(cond boolean, msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF NOT coalesce(cond, false) THEN RAISE EXCEPTION 'FALLÓ: %', msg; END IF;
    RAISE NOTICE 'OK: %', msg;
END $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA t TO authenticated, service_role;

-- Crea un reporte publicado con una foto lista y su huella (vector de 3 números).
CREATE FUNCTION t.report(p_owner uuid, p_type text, p_vec text, p_species text DEFAULT 'dog')
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE v_pet uuid; v_rep uuid; v_photo uuid := gen_random_uuid();
BEGIN
    IF p_type = 'lost' THEN
        INSERT INTO public.pets (owner_id, species, color, size) VALUES (p_owner, p_species, 'café', 'medium')
        RETURNING id INTO v_pet;
    END IF;
    INSERT INTO public.reports (user_id, pet_id, type, status, species, color, size, event_at,
                                approx_lat, approx_lng, published_at)
    VALUES (p_owner, v_pet, p_type, 'active', p_species, 'café', 'medium',
            now() - CASE WHEN p_type = 'lost' THEN interval '2 days' ELSE interval '1 hour' END,
            4.65, -74.06, now())
    RETURNING id INTO v_rep;
    INSERT INTO public.report_photos (id, report_id, user_id, storage_path, status, width, height, byte_size)
    VALUES (v_photo, v_rep, p_owner, p_owner || '/' || v_rep || '/' || v_photo || '.jpg', 'ready', 10, 10, 100);
    INSERT INTO public.photo_embeddings (photo_id, model_name, embedding)
    VALUES (v_photo, 'dinov2_s', p_vec::extensions.vector);
    RETURN v_rep;
END $$;

-- Personas: ana y eve pierden; beto y fabio encuentran con cuenta; guest encuentra SIN cuenta.
INSERT INTO auth.users (id, email, is_anonymous, raw_user_meta_data) VALUES
    ('00000000-0000-0000-0000-0000000000a1', 'ana@x.co',   false, '{"display_name":"Ana"}'),
    ('00000000-0000-0000-0000-0000000000b1', 'beto@x.co',  false, '{"display_name":"Beto"}'),
    ('00000000-0000-0000-0000-0000000000c1', NULL,         true,  '{}'),
    ('00000000-0000-0000-0000-0000000000e1', 'eve@x.co',   false, '{"display_name":"Eve"}'),
    ('00000000-0000-0000-0000-0000000000f1', 'fabio@x.co', false, '{"display_name":"Fabio"}');

SELECT t.report('00000000-0000-0000-0000-0000000000a1', 'lost',  '[1,0,0]')     AS ana_lost    \gset
SELECT t.report('00000000-0000-0000-0000-0000000000a1', 'lost',  '[1,0,0]')     AS ana_lost2   \gset
SELECT t.report('00000000-0000-0000-0000-0000000000b1', 'found', '[0.8,0.6,0]') AS beto_found  \gset
SELECT t.report('00000000-0000-0000-0000-0000000000c1', 'found', '[0.6,0.8,0]') AS guest_found \gset
SELECT t.report('00000000-0000-0000-0000-0000000000e1', 'lost',  '[0,0,1]')     AS eve_lost    \gset
SELECT t.report('00000000-0000-0000-0000-0000000000f1', 'found', '[0,0,1]')     AS copia       \gset
SELECT t.report('00000000-0000-0000-0000-0000000000f1', 'found', '[0.5,0.5,0.7]') AS f1 \gset
SELECT t.report('00000000-0000-0000-0000-0000000000f1', 'found', '[0.5,0.5,0.7]') AS f2 \gset
SELECT t.report('00000000-0000-0000-0000-0000000000b1', 'found', '[0.5,0.5,0.7]') AS f3 \gset
SELECT t.report('00000000-0000-0000-0000-0000000000b1', 'found', '[0.5,0.5,0.7]') AS f4 \gset

\echo '--- 1. Ana pide el contacto de Beto (con cuenta) desde Explorar'
SET ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","is_anonymous":false}', false);
SELECT t.expect_error(format('SELECT * FROM public.claim_found_report(%L, %L, %L, %L)', :'beto_found', :'ana_lost', 'corto', 'dinov2_s'), 'seña');
SELECT match_id AS m_beto, status AS st FROM public.claim_found_report(:'beto_found', :'ana_lost', 'collar rojo con placa', 'dinov2_s') \gset
SELECT t.ok(:'st' = 'requested', 'con cuenta → queda esperando que acepte (requested)');
SELECT t.ok((SELECT origin = 'claim' AND abs(visual_score - 0.8) < 0.01 AND total_score IS NOT NULL
               FROM public.matches WHERE id = :'m_beto'), 'origen claim, parecido 0,8 calculado con las huellas');
SELECT t.expect_error(format('SELECT * FROM public.claim_found_report(%L, %L, %L, %L)', :'beto_found', :'ana_lost', 'collar rojo con placa', 'dinov2_s'), 'Ya existe');
SELECT t.expect_error(format('SELECT public.answer_match_request(%L, true)', :'m_beto'), 'no disponible');
SELECT t.expect_error(format('SELECT public.confirm_match(%L)', :'m_beto'), 'permission denied');
RESET ROLE;
SELECT t.ok((SELECT count(*) = 1 FROM public.notifications
              WHERE match_id = :'m_beto' AND kind = 'match_requested'
                AND user_id = '00000000-0000-0000-0000-0000000000b1'), 'Beto recibe el aviso match_requested');

\echo '--- 2. Beto ve la solicitud con la seña y acepta'
SET ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b1","is_anonymous":false}', false);
SELECT t.ok((SELECT claim_note = 'collar rojo con placa' FROM public.matches WHERE id = :'m_beto'), 'Beto ve la seña (RLS)');
SELECT t.ok(public.answer_match_request(:'m_beto', true) = 'confirmed', 'Beto acepta → confirmed');
SELECT t.expect_error(format('SELECT public.answer_match_request(%L, true)', :'m_beto'), 'pendiente');
RESET ROLE;
SELECT t.ok((SELECT status FROM public.reports WHERE id = :'ana_lost') = 'resolved', 'el reporte de Ana queda resuelto');
SELECT t.ok((SELECT count(*) = 1 FROM public.notifications WHERE match_id = :'m_beto' AND kind = 'match_accepted'
              AND user_id = '00000000-0000-0000-0000-0000000000a1'), 'Ana recibe match_accepted');

\echo '--- 3. Ana pide el contacto de un invitado (sin cuenta): pasa los filtros → confirmado'
SET ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","is_anonymous":false}', false);
SELECT match_id AS m_guest, status AS st FROM public.claim_found_report(:'guest_found', :'ana_lost2', 'mancha blanca en el pecho', 'dinov2_s') \gset
SELECT t.ok(:'st' = 'confirmed', 'sin cuenta → confirmado directo');

\echo '--- 4. El invitado no puede pedir contactos ni comentar'
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c1","is_anonymous":true}', false);
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'eve_lost', 'lo vi ayer'), 'iniciar sesión');
SELECT t.ok((SELECT count(*) = 0 FROM public.report_comments), 'el invitado no ve comentarios');

\echo '--- 5. Eve: foto copiada y límite de 3 solicitudes en 24 h'
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000e1","is_anonymous":false}', false);
SELECT t.expect_error(format('SELECT * FROM public.claim_found_report(%L, %L, %L, %L)', :'copia', :'eve_lost', 'es mi perro de verdad', 'dinov2_s'), 'casi idéntica');
SELECT match_id AS m1 FROM public.claim_found_report(:'f1', :'eve_lost', 'tiene collar azul', 'dinov2_s') \gset
SELECT match_id AS m2 FROM public.claim_found_report(:'f2', :'eve_lost', 'tiene collar azul', 'dinov2_s') \gset
SELECT match_id AS m3 FROM public.claim_found_report(:'f3', :'eve_lost', 'tiene collar azul', 'dinov2_s') \gset
SELECT t.expect_error(format('SELECT * FROM public.claim_found_report(%L, %L, %L, %L)', :'f4', :'eve_lost', 'tiene collar azul', 'dinov2_s'), '3 solicitudes');
SELECT t.ok((SELECT count(*) = 0 FROM public.matches WHERE found_report_id = :'f4'), 'la solicitud rechazada no deja rastro');
\echo '    Eve cancela una solicitud'
SELECT public.discard_match(:'m1');
SELECT t.ok((SELECT status FROM public.matches WHERE id = :'m1') = 'discarded', 'cancelar → discarded');
SELECT t.expect_error('SELECT * FROM public.contact_views', 'permission denied');
SELECT t.expect_error(format('SELECT * FROM public.reveal_phone(%L, %L)', '00000000-0000-0000-0000-0000000000e1', :'m2'), 'permission denied');

\echo '--- 6. Límite de 3 teléfonos cada 24 h (lo llama el backend)'
RESET ROLE;
SET ROLE service_role;
SELECT t.ok((SELECT allowed AND views_left = 2 FROM public.reveal_phone('00000000-0000-0000-0000-0000000000e1', :'m_beto')), '1.º teléfono: quedan 2');
SELECT t.ok((SELECT allowed AND views_left = 1 FROM public.reveal_phone('00000000-0000-0000-0000-0000000000e1', :'m_guest')), '2.º teléfono: queda 1');
SELECT t.ok((SELECT allowed AND views_left = 1 FROM public.reveal_phone('00000000-0000-0000-0000-0000000000e1', :'m_guest')), 'repetir uno ya visto no gasta cupo (sigue quedando 1)');
SELECT t.ok((SELECT allowed AND views_left = 0 FROM public.reveal_phone('00000000-0000-0000-0000-0000000000e1', :'m2')), '3.º teléfono: quedan 0');
SELECT t.ok((SELECT NOT allowed AND next_at > now() + interval '23 hours' FROM public.reveal_phone('00000000-0000-0000-0000-0000000000e1', :'m3')), '4.º teléfono: bloqueado ~24 h');
SELECT t.ok((SELECT allowed FROM public.reveal_phone('00000000-0000-0000-0000-0000000000e1', :'m_beto')), 'uno ya visto se sigue viendo');
RESET ROLE;

\echo '--- 7. Comentarios'
SET ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b1","is_anonymous":false}', false);
SELECT public.add_report_comment(:'eve_lost', 'Lo vi ayer cerca del parque') AS c1 \gset
SELECT public.add_report_comment(:'eve_lost', 'El 18/11/2026 estaba en la calle 72 con 11');
SELECT public.add_report_comment(:'eve_lost', 'llámame al 300 123 4567');  -- los teléfonos se permiten
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'eve_lost', 'escribe a juan.perez@gmail.com'), 'correos');
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'eve_lost', 'juan arroba gmail.com'), 'correos');
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'eve_lost', 'mira wa.me/abc'), 'correos');
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'eve_lost', 'x'), '2 y 500');
SELECT public.add_report_comment(:'eve_lost', 'comentario cuatro');
SELECT public.add_report_comment(:'eve_lost', 'comentario cinco');
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'eve_lost', 'comentario seis'), 'muchos comentarios');
SELECT t.expect_error(format('SELECT public.add_report_comment(%L, %L)', :'ana_lost', 'reporte resuelto'), 'publicados|no disponible');
SELECT t.expect_error(format('INSERT INTO public.report_comments (report_id, user_id, body) VALUES (%L, %L, %L)', :'eve_lost', '00000000-0000-0000-0000-0000000000b1', 'directo 3001234567'), 'permission denied');
\echo '    Ana no puede borrar el comentario de Beto; Eve (dueña del reporte) sí'
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","is_anonymous":false}', false);
SELECT t.ok((SELECT count(*) = 5 FROM public.report_comments WHERE report_id = :'eve_lost'), 'Ana ve los 5 comentarios (incluido el del teléfono)');
WITH d AS (DELETE FROM public.report_comments WHERE id = :'c1' RETURNING 1) SELECT t.ok((SELECT count(*) FROM d) = 0, 'Ana no borra comentarios ajenos');
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000e1","is_anonymous":false}', false);
WITH d AS (DELETE FROM public.report_comments WHERE id = :'c1' RETURNING 1) SELECT t.ok((SELECT count(*) FROM d) = 1, 'Eve borra en su reporte');
\echo '    Quien no participa no ve la coincidencia'
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000f1","is_anonymous":false}', false);
SELECT t.ok((SELECT count(*) = 0 FROM public.matches WHERE id = :'m_beto'), 'Fabio no ve la coincidencia Ana–Beto');
RESET ROLE;
SELECT t.ok((SELECT count(*) = 4 FROM public.notifications WHERE kind = 'new_comment'
              AND user_id = '00000000-0000-0000-0000-0000000000e1'), 'Eve recibió 4 avisos de comentario (uno se borró con su comentario)');

\echo '--- 8. El motor sigue funcionando igual (save_match_suggestion y find_match_candidates)'
SET ROLE service_role;
SELECT t.ok((SELECT is_new FROM public.save_match_suggestion(:'ana_lost2', :'f3', 'dinov2_s', 0.6, 1, 0.7)), 'el motor guarda una sugerencia nueva');
SELECT t.ok((SELECT count(*) >= 0 FROM public.find_match_candidates(:'eve_lost', 'dinov2_s', 50)), 'find_match_candidates corre');
RESET ROLE;
\echo '=== TODOS LOS ESCENARIOS PASARON ==='
