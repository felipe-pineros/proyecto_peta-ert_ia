-- PET Alert · Migración 1 de 3: tablas, restricciones, índices y triggers.
-- Basado en docs/arquitectura.md (aprobado 2026-10-23).
-- Se ejecuta dentro de una transacción: si algo falla, no queda nada a medias.

BEGIN;

-- pgvector guarda los embeddings (la "huella" visual de cada foto).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ---------------------------------------------------------------------------
-- Utilidad: mantener updated_at al día en cada UPDATE.
-- ---------------------------------------------------------------------------
CREATE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- profiles: un perfil por usuario de Supabase Auth.
-- ---------------------------------------------------------------------------
CREATE TABLE public.profiles (
    id           uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    display_name text CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 80),
    phone        text CHECK (phone IS NULL OR char_length(phone) <= 40),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- species: catálogo extensible (agregar una especie = insertar una fila).
-- ---------------------------------------------------------------------------
CREATE TABLE public.species (
    code       text PRIMARY KEY CHECK (code ~ '^[a-z_]{2,30}$'),
    name_es    text NOT NULL CHECK (char_length(name_es) BETWEEN 1 AND 40),
    active     boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.species (code, name_es) VALUES
    ('dog', 'Perro'),
    ('cat', 'Gato');

-- ---------------------------------------------------------------------------
-- pets: identidad de la mascota, separada de los reportes.
-- ---------------------------------------------------------------------------
CREATE TABLE public.pets (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id             uuid NOT NULL DEFAULT auth.uid() REFERENCES public.profiles (id) ON DELETE CASCADE,
    name                 text CHECK (name IS NULL OR char_length(name) BETWEEN 1 AND 80),
    species              text NOT NULL REFERENCES public.species (code),
    breed                text CHECK (breed IS NULL OR char_length(breed) <= 80),
    color                text NOT NULL CHECK (char_length(color) BETWEEN 1 AND 80),
    size                 text NOT NULL CHECK (size IN ('small', 'medium', 'large')),
    distinctive_features text CHECK (distinctive_features IS NULL OR char_length(distinctive_features) <= 1000),
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    -- Permite que reports compruebe con una FK que la mascota es del mismo dueño y especie.
    CONSTRAINT pets_id_owner_species_key UNIQUE (id, owner_id, species)
);

-- ---------------------------------------------------------------------------
-- reports: reporte de mascota perdida (lost) o encontrada (found).
-- ---------------------------------------------------------------------------
CREATE TABLE public.reports (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid NOT NULL DEFAULT auth.uid() REFERENCES public.profiles (id) ON DELETE CASCADE,
    pet_id               uuid,
    type                 text NOT NULL CHECK (type IN ('lost', 'found')),
    status               text NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft', 'active', 'resolved', 'withdrawn')),
    species              text NOT NULL REFERENCES public.species (code),
    breed                text CHECK (breed IS NULL OR char_length(breed) <= 80),
    color                text NOT NULL CHECK (char_length(color) BETWEEN 1 AND 80),
    size                 text NOT NULL CHECK (size IN ('small', 'medium', 'large')),
    distinctive_features text CHECK (distinctive_features IS NULL OR char_length(distinctive_features) <= 1000),
    event_at             timestamptz NOT NULL,
    location_label       text CHECK (location_label IS NULL OR char_length(location_label) <= 160),
    -- Ubicación PÚBLICA aproximada: 2 decimales ≈ 1,1 km. La exacta va en report_private.
    approx_lat           numeric(5, 2) NOT NULL CHECK (approx_lat BETWEEN -90 AND 90),
    approx_lng           numeric(5, 2) NOT NULL CHECK (approx_lng BETWEEN -180 AND 180),
    published_at         timestamptz,
    resolved_at          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reports_id_user_key UNIQUE (id, user_id),
    -- La mascota debe ser del mismo usuario y de la misma especie que el reporte.
    CONSTRAINT reports_pet_fk FOREIGN KEY (pet_id, user_id, species)
        REFERENCES public.pets (id, owner_id, species) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT reports_pet_by_type CHECK (
        (type = 'lost' AND pet_id IS NOT NULL) OR (type = 'found' AND pet_id IS NULL)
    ),
    -- withdrawn puede venir de draft (nunca publicado), por eso no se exige ahí.
    CONSTRAINT reports_published_at CHECK (status NOT IN ('active', 'resolved') OR published_at IS NOT NULL),
    CONSTRAINT reports_resolved_at CHECK (status <> 'resolved' OR resolved_at IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- report_private: datos sensibles, solo para el dueño del reporte.
-- ---------------------------------------------------------------------------
CREATE TABLE public.report_private (
    report_id     uuid PRIMARY KEY REFERENCES public.reports (id) ON DELETE CASCADE,
    exact_lat     numeric(9, 6) CHECK (exact_lat BETWEEN -90 AND 90),
    exact_lng     numeric(9, 6) CHECK (exact_lng BETWEEN -180 AND 180),
    contact_phone text CHECK (contact_phone IS NULL OR char_length(contact_phone) <= 40),
    contact_email text CHECK (contact_email IS NULL OR char_length(contact_email) <= 254),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT report_private_coords_pair CHECK ((exact_lat IS NULL) = (exact_lng IS NULL))
);

-- ---------------------------------------------------------------------------
-- report_photos: metadatos de las fotos (el archivo vive en Storage privado).
-- ---------------------------------------------------------------------------
CREATE TABLE public.report_photos (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id    uuid NOT NULL,
    user_id      uuid NOT NULL,
    storage_path text NOT NULL UNIQUE,
    status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
    width        integer CHECK (width IS NULL OR width > 0),
    height       integer CHECK (height IS NULL OR height > 0),
    byte_size    integer CHECK (byte_size IS NULL OR byte_size BETWEEN 1 AND 10485760),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    -- La foto pertenece al mismo usuario que creó el reporte.
    CONSTRAINT report_photos_report_fk FOREIGN KEY (report_id, user_id)
        REFERENCES public.reports (id, user_id) ON DELETE CASCADE,
    -- Ruta fija: <user_id>/<report_id>/<photo_id>.jpg (no se puede apuntar a archivos ajenos).
    CONSTRAINT report_photos_path CHECK (
        storage_path = user_id::text || '/' || report_id::text || '/' || id::text || '.jpg'
    ),
    CONSTRAINT report_photos_ready_fields CHECK (
        status <> 'ready' OR (width IS NOT NULL AND height IS NOT NULL AND byte_size IS NOT NULL)
    )
);

-- Máximo 5 fotos (no fallidas) por reporte (decisión D4).
CREATE FUNCTION public.enforce_photo_limit()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    -- Bloquea el reporte para que dos subidas simultáneas no superen el límite.
    PERFORM 1 FROM public.reports WHERE id = NEW.report_id FOR UPDATE;
    IF (SELECT count(*) FROM public.report_photos
         WHERE report_id = NEW.report_id AND status <> 'failed') >= 5 THEN
        RAISE EXCEPTION 'Un reporte admite máximo 5 fotos';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER report_photos_limit
    BEFORE INSERT ON public.report_photos
    FOR EACH ROW EXECUTE FUNCTION public.enforce_photo_limit();

-- ---------------------------------------------------------------------------
-- photo_embeddings: huella visual por foto y por modelo.
-- ---------------------------------------------------------------------------
CREATE TABLE public.photo_embeddings (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    photo_id   uuid NOT NULL REFERENCES public.report_photos (id) ON DELETE CASCADE,
    model_name text NOT NULL CHECK (model_name ~ '^[a-z0-9_.-]{2,60}$'),
    -- Sin dimensión fija para poder cambiar de modelo (384, 768, 1024...).
    embedding  extensions.vector NOT NULL,
    crop_box   jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT photo_embeddings_photo_model_key UNIQUE (photo_id, model_name)
);

-- ---------------------------------------------------------------------------
-- matches: posibles coincidencias perdida ↔ encontrada (sin duplicados).
-- ---------------------------------------------------------------------------
CREATE TABLE public.matches (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lost_report_id  uuid NOT NULL REFERENCES public.reports (id) ON DELETE CASCADE,
    found_report_id uuid NOT NULL REFERENCES public.reports (id) ON DELETE CASCADE,
    model_name      text NOT NULL CHECK (model_name ~ '^[a-z0-9_.-]{2,60}$'),
    visual_score    real NOT NULL CHECK (visual_score BETWEEN 0 AND 1),
    distance_km     real NOT NULL CHECK (distance_km >= 0),
    total_score     real NOT NULL CHECK (total_score BETWEEN 0 AND 1),
    status          text NOT NULL DEFAULT 'suggested'
                    CHECK (status IN ('suggested', 'confirmed', 'discarded')),
    decided_by      uuid REFERENCES public.profiles (id) ON DELETE SET NULL,
    decided_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT matches_pair_key UNIQUE (lost_report_id, found_report_id),
    CONSTRAINT matches_distinct_reports CHECK (lost_report_id <> found_report_id),
    CONSTRAINT matches_decision CHECK ((status = 'suggested') = (decided_at IS NULL))
);

-- La pareja debe ser un reporte lost + uno found, misma especie, de usuarios distintos.
CREATE FUNCTION public.check_match_pair()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_lost  public.reports%ROWTYPE;
    v_found public.reports%ROWTYPE;
BEGIN
    SELECT * INTO v_lost  FROM public.reports WHERE id = NEW.lost_report_id;
    SELECT * INTO v_found FROM public.reports WHERE id = NEW.found_report_id;
    IF v_lost.type <> 'lost' OR v_found.type <> 'found' THEN
        RAISE EXCEPTION 'Una coincidencia une un reporte perdido con uno encontrado';
    END IF;
    IF v_lost.species <> v_found.species THEN
        RAISE EXCEPTION 'Los reportes de una coincidencia deben ser de la misma especie';
    END IF;
    IF v_lost.user_id = v_found.user_id THEN
        RAISE EXCEPTION 'Una coincidencia no puede unir dos reportes del mismo usuario';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER matches_check_pair
    BEFORE INSERT OR UPDATE OF lost_report_id, found_report_id ON public.matches
    FOR EACH ROW EXECUTE FUNCTION public.check_match_pair();

-- ---------------------------------------------------------------------------
-- notifications: avisos dentro de la app (sin duplicados).
-- ---------------------------------------------------------------------------
CREATE TABLE public.notifications (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    match_id   uuid NOT NULL REFERENCES public.matches (id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('new_match', 'match_confirmed', 'match_discarded')),
    read_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notifications_once_key UNIQUE (user_id, match_id, kind)
);

-- ---------------------------------------------------------------------------
-- Índices para las consultas frecuentes (y para las claves foráneas).
-- ---------------------------------------------------------------------------
CREATE INDEX pets_owner_idx            ON public.pets (owner_id, created_at DESC);
CREATE INDEX reports_active_feed_idx   ON public.reports (species, type, published_at DESC) WHERE status = 'active';
CREATE INDEX reports_user_idx          ON public.reports (user_id, created_at DESC);
CREATE INDEX reports_pet_idx           ON public.reports (pet_id) WHERE pet_id IS NOT NULL;
CREATE INDEX report_photos_report_idx  ON public.report_photos (report_id, user_id, status);
CREATE INDEX matches_lost_idx          ON public.matches (lost_report_id, total_score DESC);
CREATE INDEX matches_found_idx         ON public.matches (found_report_id, total_score DESC);
CREATE INDEX notifications_user_idx    ON public.notifications (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- updated_at automático.
-- ---------------------------------------------------------------------------
CREATE TRIGGER profiles_updated_at         BEFORE UPDATE ON public.profiles         FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER species_updated_at          BEFORE UPDATE ON public.species          FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER pets_updated_at             BEFORE UPDATE ON public.pets             FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER reports_updated_at          BEFORE UPDATE ON public.reports          FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER report_private_updated_at   BEFORE UPDATE ON public.report_private   FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER report_photos_updated_at    BEFORE UPDATE ON public.report_photos    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER photo_embeddings_updated_at BEFORE UPDATE ON public.photo_embeddings FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER matches_updated_at          BEFORE UPDATE ON public.matches          FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER notifications_updated_at    BEFORE UPDATE ON public.notifications    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Crear el perfil automáticamente cuando alguien se registra.
-- ---------------------------------------------------------------------------
CREATE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    INSERT INTO public.profiles (id, display_name)
    VALUES (NEW.id, NULLIF(left(trim(NEW.raw_user_meta_data ->> 'display_name'), 80), ''));
    RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Usuarios que ya existían antes de esta migración (p. ej. cuentas de prueba).
INSERT INTO public.profiles (id)
SELECT id FROM auth.users
ON CONFLICT (id) DO NOTHING;

COMMIT;
