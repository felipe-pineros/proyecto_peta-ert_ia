-- PET Alert · Migración 5: motor de coincidencias (etapa 7).
--
-- Dos funciones que SOLO usa el backend (rol service_role, con la secret key):
--   1. find_match_candidates: aplica los filtros de docs/arquitectura.md §4 y devuelve,
--      por cada reporte candidato, la MEJOR similitud entre sus fotos y la distancia.
--   2. save_match_suggestion: guarda una posible coincidencia SIN duplicados.
--      Si la pareja ya existe y sigue 'suggested', solo actualiza los puntajes;
--      si fue confirmada o descartada, NO la toca (una descartada no reaparece).
--
-- Distancia: se usa la ubicación PÚBLICA aproximada (~1 km), nunca el punto exacto,
-- porque la distancia se muestra a las dos personas.

BEGIN;

-- Índice para encontrar rápido las huellas de las fotos de un reporte con un modelo.
CREATE INDEX IF NOT EXISTS photo_embeddings_model_photo_idx
    ON public.photo_embeddings (model_name, photo_id);

-- ---------------------------------------------------------------------------
-- 1. Candidatos para un reporte
-- ---------------------------------------------------------------------------
CREATE FUNCTION public.find_match_candidates(
    p_report_id uuid,
    p_model     text,
    p_max_km    double precision DEFAULT 50
)
RETURNS TABLE (
    lost_report_id  uuid,
    found_report_id uuid,
    similarity      double precision,   -- coseno: 1 = idénticas
    distance_km     double precision
)
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    WITH me AS (
        SELECT r.* FROM public.reports r
        WHERE r.id = p_report_id AND r.status = 'active'
    ),
    others AS (
        SELECT o.id, o.type,
               -- fórmula del semiverseno (haversine), radio terrestre 6371 km
               6371 * 2 * asin(sqrt(
                   power(sin(radians((o.approx_lat - me.approx_lat)::double precision) / 2), 2)
                   + cos(radians(me.approx_lat::double precision)) * cos(radians(o.approx_lat::double precision))
                   * power(sin(radians((o.approx_lng - me.approx_lng)::double precision) / 2), 2)
               )) AS km
        FROM public.reports o
        CROSS JOIN me
        WHERE o.status = 'active'
          AND o.species = me.species
          AND o.type <> me.type
          AND o.user_id <> me.user_id
          -- la mascota se encontró después de perderse (con 1 día de margen)
          AND CASE WHEN me.type = 'lost'
                   THEN o.event_at  >= me.event_at - interval '1 day'
                   ELSE me.event_at >= o.event_at - interval '1 day' END
    ),
    mine AS (
        SELECT e.embedding FROM public.report_photos ph
        JOIN public.photo_embeddings e ON e.photo_id = ph.id AND e.model_name = p_model
        WHERE ph.report_id = p_report_id AND ph.status = 'ready'
    )
    SELECT CASE WHEN o.type = 'lost' THEN o.id ELSE p_report_id END,
           CASE WHEN o.type = 'found' THEN o.id ELSE p_report_id END,
           max(1 - (m.embedding OPERATOR(extensions.<=>) e.embedding)),
           o.km
    FROM others o
    JOIN public.report_photos ph ON ph.report_id = o.id AND ph.status = 'ready'
    JOIN public.photo_embeddings e ON e.photo_id = ph.id AND e.model_name = p_model
    CROSS JOIN mine m
    WHERE o.km <= p_max_km
    GROUP BY o.id, o.type, o.km;
$$;

-- ---------------------------------------------------------------------------
-- 2. Guardar una sugerencia sin duplicados
-- ---------------------------------------------------------------------------
CREATE FUNCTION public.save_match_suggestion(
    p_lost_report_id  uuid,
    p_found_report_id uuid,
    p_model           text,
    p_visual_score    real,
    p_distance_km     real,
    p_total_score     real
)
RETURNS TABLE (match_id uuid, is_new boolean, status text)
LANGUAGE plpgsql
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    INSERT INTO public.matches AS m
        (lost_report_id, found_report_id, model_name, visual_score, distance_km, total_score)
    VALUES (p_lost_report_id, p_found_report_id, p_model, p_visual_score, p_distance_km, p_total_score)
    ON CONFLICT (lost_report_id, found_report_id) DO UPDATE
        SET model_name   = EXCLUDED.model_name,
            visual_score = EXCLUDED.visual_score,
            distance_km  = EXCLUDED.distance_km,
            total_score  = EXCLUDED.total_score
        WHERE m.status = 'suggested'          -- confirmadas y descartadas no se tocan
    RETURNING m.id, (m.xmax = 0), m.status;   -- xmax = 0 → fila recién insertada
END;
$$;

-- Solo el backend (service_role) puede ejecutarlas.
REVOKE ALL ON FUNCTION public.find_match_candidates(uuid, text, double precision) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.save_match_suggestion(uuid, uuid, text, real, real, real) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.find_match_candidates(uuid, text, double precision) TO service_role;
GRANT EXECUTE ON FUNCTION public.save_match_suggestion(uuid, uuid, text, real, real, real) TO service_role;

COMMIT;
