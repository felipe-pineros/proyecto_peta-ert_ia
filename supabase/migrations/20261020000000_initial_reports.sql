-- PETA-ERT-IA: initial report and private-photo schema.
-- Apply only after reviewing this migration and confirming the target project.

BEGIN;

CREATE TABLE public.pets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE RESTRICT,
    name text,
    species text NOT NULL CHECK (species IN ('dog', 'cat')),
    breed text,
    color text,
    size text CHECK (size IS NULL OR size IN ('small', 'medium', 'large', 'unknown')),
    distinctive_features text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pets_id_owner_unique UNIQUE (id, owner_id),
    CONSTRAINT pets_name_length CHECK (name IS NULL OR char_length(name) <= 120),
    CONSTRAINT pets_breed_length CHECK (breed IS NULL OR char_length(breed) <= 120),
    CONSTRAINT pets_color_length CHECK (color IS NULL OR char_length(color) <= 120),
    CONSTRAINT pets_features_length CHECK (distinctive_features IS NULL OR char_length(distinctive_features) <= 2000)
);

CREATE TABLE public.reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by uuid NOT NULL REFERENCES auth.users (id) ON DELETE RESTRICT,
    pet_id uuid,
    report_type text NOT NULL CHECK (report_type IN ('lost', 'found')),
    species text NOT NULL CHECK (species IN ('dog', 'cat')),
    animal_name text,
    breed text,
    color text,
    size text CHECK (size IS NULL OR size IN ('small', 'medium', 'large', 'unknown')),
    distinctive_features text,
    description text NOT NULL,
    location_label text,
    event_at timestamptz,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'resolved', 'withdrawn')),
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reports_id_owner_unique UNIQUE (id, created_by),
    CONSTRAINT reports_pet_owner_fk FOREIGN KEY (pet_id, created_by)
        REFERENCES public.pets (id, owner_id) ON DELETE RESTRICT,
    CONSTRAINT reports_lost_pet_required CHECK (
        (report_type = 'lost' AND pet_id IS NOT NULL)
        OR (report_type = 'found' AND pet_id IS NULL)
    ),
    CONSTRAINT reports_name_length CHECK (animal_name IS NULL OR char_length(animal_name) <= 120),
    CONSTRAINT reports_breed_length CHECK (breed IS NULL OR char_length(breed) <= 120),
    CONSTRAINT reports_color_length CHECK (color IS NULL OR char_length(color) <= 120),
    CONSTRAINT reports_features_length CHECK (distinctive_features IS NULL OR char_length(distinctive_features) <= 2000),
    CONSTRAINT reports_description_length CHECK (char_length(description) BETWEEN 1 AND 5000),
    CONSTRAINT reports_location_label_length CHECK (location_label IS NULL OR char_length(location_label) <= 160)
);

CREATE TABLE public.report_private (
    report_id uuid PRIMARY KEY REFERENCES public.reports (id) ON DELETE CASCADE,
    contact_phone text,
    contact_email text,
    precise_latitude numeric(9, 6),
    precise_longitude numeric(9, 6),
    CONSTRAINT report_private_phone_length CHECK (contact_phone IS NULL OR char_length(contact_phone) <= 40),
    CONSTRAINT report_private_email_length CHECK (contact_email IS NULL OR char_length(contact_email) <= 254),
    CONSTRAINT report_private_latitude_range CHECK (precise_latitude IS NULL OR precise_latitude BETWEEN -90 AND 90),
    CONSTRAINT report_private_longitude_range CHECK (precise_longitude IS NULL OR precise_longitude BETWEEN -180 AND 180),
    CONSTRAINT report_private_coordinates_pair CHECK (
        (precise_latitude IS NULL AND precise_longitude IS NULL)
        OR (precise_latitude IS NOT NULL AND precise_longitude IS NOT NULL)
    )
);

CREATE TABLE public.report_photos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id uuid NOT NULL,
    uploaded_by uuid NOT NULL,
    storage_path text NOT NULL UNIQUE,
    content_type text CHECK (content_type IS NULL OR content_type IN ('image/jpeg', 'image/png', 'image/webp')),
    byte_size bigint CHECK (byte_size IS NULL OR byte_size BETWEEN 1 AND 10485760),
    upload_status text NOT NULL DEFAULT 'pending' CHECK (upload_status IN ('pending', 'ready', 'deleting')),
    cleanup_started_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT report_photos_report_owner_fk FOREIGN KEY (report_id, uploaded_by)
        REFERENCES public.reports (id, created_by) ON DELETE CASCADE,
    CONSTRAINT report_photos_path_scope CHECK (
        split_part(storage_path, '/', 1) = uploaded_by::text
        AND split_part(storage_path, '/', 2) = report_id::text
        AND split_part(storage_path, '/', 3) <> ''
        AND array_length(string_to_array(storage_path, '/'), 1) = 3
    ),
    CONSTRAINT report_photos_validation_fields CHECK (
        (upload_status = 'ready' AND content_type IS NOT NULL AND byte_size IS NOT NULL)
        OR (upload_status IN ('pending', 'deleting') AND (
            (content_type IS NULL AND byte_size IS NULL)
            OR (content_type IS NOT NULL AND byte_size IS NOT NULL)
        ))
    ),
    CONSTRAINT report_photos_cleanup_state CHECK (upload_status = 'deleting' OR cleanup_started_at IS NULL)
);

CREATE INDEX reports_public_feed_idx ON public.reports (status, created_at DESC)
    WHERE status = 'active';
CREATE INDEX reports_species_type_status_idx ON public.reports (species, report_type, status);
CREATE INDEX reports_owner_status_idx ON public.reports (created_by, status, updated_at DESC);
CREATE INDEX reports_event_at_idx ON public.reports (event_at DESC) WHERE event_at IS NOT NULL;
CREATE INDEX pets_owner_idx ON public.pets (owner_id, created_at DESC);
CREATE INDEX report_photos_report_status_idx ON public.report_photos (report_id, upload_status, created_at);

ALTER TABLE public.pets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_private ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_photos ENABLE ROW LEVEL SECURITY;

-- Start from explicit least-privilege table grants; RLS policies below scope rows.
REVOKE ALL ON TABLE public.pets, public.reports, public.report_private, public.report_photos FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA public TO service_role;
GRANT USAGE ON SCHEMA storage TO service_role;

GRANT SELECT (id, owner_id, name, species, breed, color, size, distinctive_features, created_at, updated_at)
    ON TABLE public.pets TO authenticated;
GRANT INSERT (owner_id, name, species, breed, color, size, distinctive_features) ON TABLE public.pets TO authenticated;
GRANT UPDATE (name, species, breed, color, size, distinctive_features, updated_at) ON TABLE public.pets TO authenticated;
GRANT SELECT (id, report_type, species, animal_name, breed, color, size,
              distinctive_features, description, location_label, event_at, status,
              published_at, created_at, updated_at)
    ON TABLE public.reports TO authenticated;
GRANT INSERT (created_by, pet_id, report_type, species, animal_name, breed, color, size, distinctive_features, description, location_label, event_at)
    ON TABLE public.reports TO authenticated;
GRANT UPDATE (species, animal_name, breed, color, size, distinctive_features, description, location_label, event_at, updated_at)
    ON TABLE public.reports TO authenticated;
GRANT SELECT ON TABLE public.report_private TO authenticated;
GRANT INSERT (report_id, contact_phone, contact_email, precise_latitude, precise_longitude) ON TABLE public.report_private TO authenticated;
GRANT UPDATE (contact_phone, contact_email, precise_latitude, precise_longitude) ON TABLE public.report_private TO authenticated;
GRANT SELECT (id, report_id, upload_status) ON TABLE public.report_photos TO authenticated;

-- The built-in service_role is used only by FastAPI's fixed RPC and Storage operations.
-- These table grants support those RPCs; service_role remains a powerful Supabase role.
GRANT SELECT ON TABLE public.reports, public.report_photos TO service_role;
GRANT INSERT (id, report_id, uploaded_by, storage_path) ON TABLE public.report_photos TO service_role;
GRANT UPDATE (upload_status, content_type, byte_size, cleanup_started_at) ON TABLE public.report_photos TO service_role;
GRANT DELETE ON TABLE public.report_photos TO service_role;
GRANT UPDATE (status, published_at, updated_at) ON TABLE public.reports TO service_role;
GRANT SELECT ON TABLE storage.objects TO service_role;

-- The browser cannot select reports.created_by. These narrow definer helpers are used only
-- inside RLS predicates that need to check ownership through report_private/report_photos.
CREATE FUNCTION public.owns_report(p_report_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.reports AS r
         WHERE r.id = p_report_id AND r.created_by = (SELECT auth.uid())
    );
$function$;
ALTER FUNCTION public.owns_report(uuid) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.owns_report(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.owns_report(uuid) TO authenticated;

CREATE FUNCTION public.owns_draft_report(p_report_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.reports AS r
         WHERE r.id = p_report_id AND r.created_by = (SELECT auth.uid()) AND r.status = 'draft'
    );
$function$;
ALTER FUNCTION public.owns_draft_report(uuid) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.owns_draft_report(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.owns_draft_report(uuid) TO authenticated;

CREATE POLICY pets_select_owner ON public.pets
    FOR SELECT TO authenticated
    USING (owner_id = (SELECT auth.uid()));
CREATE POLICY pets_insert_owner ON public.pets
    FOR INSERT TO authenticated
    WITH CHECK (owner_id = (SELECT auth.uid()));
CREATE POLICY pets_update_owner ON public.pets
    FOR UPDATE TO authenticated
    USING (owner_id = (SELECT auth.uid()))
    WITH CHECK (owner_id = (SELECT auth.uid()));

CREATE POLICY reports_select_owner_or_active ON public.reports
    FOR SELECT TO authenticated
    USING (created_by = (SELECT auth.uid()) OR status = 'active');
CREATE POLICY reports_insert_own_draft ON public.reports
    FOR INSERT TO authenticated
    WITH CHECK (created_by = (SELECT auth.uid()) AND status = 'draft');
CREATE POLICY reports_update_owner ON public.reports
    FOR UPDATE TO authenticated
    USING (created_by = (SELECT auth.uid()))
    WITH CHECK (created_by = (SELECT auth.uid()));

CREATE POLICY report_private_select_owner ON public.report_private
    FOR SELECT TO authenticated
    USING (public.owns_report(report_id));
CREATE POLICY report_private_insert_owner_draft ON public.report_private
    FOR INSERT TO authenticated
    WITH CHECK (public.owns_draft_report(report_id));
CREATE POLICY report_private_update_owner ON public.report_private
    FOR UPDATE TO authenticated
    USING (public.owns_report(report_id))
    WITH CHECK (public.owns_report(report_id));

CREATE POLICY report_photos_select_owner_or_active ON public.report_photos
    FOR SELECT TO authenticated
    USING (
        public.owns_report(report_id)
        OR EXISTS (
            SELECT 1 FROM public.reports r
            WHERE r.id = report_photos.report_id
              AND r.status = 'active' AND report_photos.upload_status = 'ready'
        )
    );

-- Fixed backend-only projection for the authenticated user's own report history.
-- The API passes only the ID obtained from the validated Supabase Auth JWT.
CREATE FUNCTION public.api_list_owned_reports(p_user_id uuid)
RETURNS TABLE(
    id uuid, report_type text, species text, animal_name text, breed text, color text,
    size text, distinctive_features text, description text, location_label text,
    event_at timestamptz, status text, published_at timestamptz,
    created_at timestamptz, updated_at timestamptz
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    SELECT r.id, r.report_type, r.species, r.animal_name, r.breed, r.color,
           r.size, r.distinctive_features, r.description, r.location_label,
           r.event_at, r.status, r.published_at, r.created_at, r.updated_at
      FROM public.reports AS r
     WHERE r.created_by = p_user_id
     ORDER BY r.created_at DESC
     LIMIT 100;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_list_owned_reports(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_list_owned_reports(uuid) TO service_role;

-- Private bucket: one object path is scoped to <user UUID>/<report UUID>/<photo UUID>.<ext>.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'pet-report-photos',
    'pet-report-photos',
    false,
    10485760,
    ARRAY['image/jpeg', 'image/png', 'image/webp']::text[]
)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    public = false,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- Remove the prior draft policies if this un-applied migration replaces an earlier
-- manual copy. No browser role receives a policy for this bucket in the revised design.
DROP POLICY IF EXISTS pet_report_photos_insert_pending_owner ON storage.objects;
DROP POLICY IF EXISTS pet_report_photos_select_authorized ON storage.objects;
DROP POLICY IF EXISTS pet_report_photos_delete_owner_draft ON storage.objects;

-- These backend-only RPCs execute as the existing Supabase service_role. The API must
-- authenticate the user's JWT first and pass only the verified Auth user id. Every RPC
-- repeats its ownership/state checks. Never expose the service_role key to a browser.
-- No Storage read/write policies are granted to anon/authenticated for this bucket;
-- FastAPI alone performs object operations and signs reads after api_authorize_photo_read.

CREATE FUNCTION public.api_register_pending_photo(
    p_user_id uuid, p_report_id uuid, p_photo_id uuid, p_storage_path text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_owner uuid;
    v_status text;
BEGIN
    IF p_user_id IS NULL OR p_photo_id IS NULL OR p_storage_path IS NULL THEN
        RAISE EXCEPTION 'Required photo fields are missing';
    END IF;
    SELECT r.created_by, r.status INTO v_owner, v_status
      FROM public.reports r WHERE r.id = p_report_id FOR UPDATE;
    IF NOT FOUND OR v_owner <> p_user_id OR v_status <> 'draft' THEN
        RAISE EXCEPTION 'Report is not an owned draft' USING ERRCODE = '42501';
    END IF;
    IF split_part(p_storage_path, '/', 1) <> p_user_id::text
       OR split_part(p_storage_path, '/', 2) <> p_report_id::text
       OR array_length(string_to_array(p_storage_path, '/'), 1) <> 3 THEN
        RAISE EXCEPTION 'Invalid photo storage path';
    END IF;
    INSERT INTO public.report_photos (id, report_id, uploaded_by, storage_path)
    VALUES (p_photo_id, p_report_id, p_user_id, p_storage_path);
    RETURN p_photo_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_register_pending_photo(uuid, uuid, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_register_pending_photo(uuid, uuid, uuid, text) TO service_role;

-- Called only by FastAPI after Pillow validated and normalized the image bytes and Storage upload succeeded.
CREATE FUNCTION public.api_mark_photo_ready(
    p_user_id uuid, p_photo_id uuid, p_content_type text, p_byte_size bigint
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_report_id uuid;
    v_owner uuid;
    v_report_status text;
    v_photo_status text;
    v_path text;
BEGIN
    IF p_user_id IS NULL OR p_content_type IS DISTINCT FROM 'image/jpeg'
       OR p_byte_size IS NULL OR p_byte_size NOT BETWEEN 1 AND 10485760 THEN
        RAISE EXCEPTION 'Invalid validated image metadata';
    END IF;
    SELECT r.id, r.created_by, r.status, p.upload_status, p.storage_path
      INTO v_report_id, v_owner, v_report_status, v_photo_status, v_path
      FROM public.report_photos p
      JOIN public.reports r ON r.id = p.report_id
     WHERE p.id = p_photo_id
     FOR UPDATE OF r, p;
    IF NOT FOUND OR v_owner <> p_user_id OR v_report_status <> 'draft' OR v_photo_status <> 'pending' THEN
        RAISE EXCEPTION 'Pending photo is not attached to an owned draft' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM storage.objects o
        WHERE o.bucket_id = 'pet-report-photos' AND o.name = v_path
    ) THEN
        RAISE EXCEPTION 'Validated photo object is missing';
    END IF;
    UPDATE public.report_photos
       SET upload_status = 'ready', content_type = p_content_type, byte_size = p_byte_size
     WHERE id = p_photo_id;
    RETURN p_photo_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_mark_photo_ready(uuid, uuid, text, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_mark_photo_ready(uuid, uuid, text, bigint) TO service_role;

CREATE FUNCTION public.api_publish_report(p_user_id uuid, p_report_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_owner uuid;
    v_status text;
BEGIN
    IF p_user_id IS NULL THEN RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501'; END IF;
    SELECT r.created_by, r.status INTO v_owner, v_status
      FROM public.reports r WHERE r.id = p_report_id FOR UPDATE;
    IF NOT FOUND OR v_owner <> p_user_id THEN
        RAISE EXCEPTION 'Report is not owned by this user' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'draft' THEN RAISE EXCEPTION 'Only drafts can be published'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.report_photos p
        JOIN storage.objects o ON o.bucket_id = 'pet-report-photos' AND o.name = p.storage_path
        WHERE p.report_id = p_report_id AND p.uploaded_by = p_user_id
          AND p.upload_status = 'ready' AND p.content_type = 'image/jpeg'
          AND p.byte_size BETWEEN 1 AND 10485760
    ) THEN
        RAISE EXCEPTION 'A validated, stored photo is required before publishing';
    END IF;
    -- Serialize publication with any in-flight upload or explicit deletion intent. Otherwise,
    -- the subsequent ready/delete transition could fail after the report became active.
    IF EXISTS (
        SELECT 1 FROM public.report_photos p
         WHERE p.report_id = p_report_id AND p.upload_status IN ('pending', 'deleting')
    ) THEN
        RAISE EXCEPTION 'Photo upload or cleanup must finish before publishing';
    END IF;
    UPDATE public.reports SET status = 'active', published_at = now(), updated_at = now()
     WHERE id = p_report_id;
    RETURN p_report_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_publish_report(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_publish_report(uuid, uuid) TO service_role;

CREATE FUNCTION public.api_transition_report(p_user_id uuid, p_report_id uuid, p_new_status text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_owner uuid;
    v_status text;
BEGIN
    IF p_user_id IS NULL THEN RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501'; END IF;
    IF p_new_status IS NULL OR p_new_status NOT IN ('resolved', 'withdrawn') THEN
        RAISE EXCEPTION 'Unsupported report transition';
    END IF;
    SELECT r.created_by, r.status INTO v_owner, v_status
      FROM public.reports r WHERE r.id = p_report_id FOR UPDATE;
    IF NOT FOUND OR v_owner <> p_user_id THEN
        RAISE EXCEPTION 'Report is not owned by this user' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'active' THEN RAISE EXCEPTION 'Only active reports can be closed'; END IF;
    UPDATE public.reports SET status = p_new_status, updated_at = now() WHERE id = p_report_id;
    RETURN p_report_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_transition_report(uuid, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_transition_report(uuid, uuid, text) TO service_role;

CREATE FUNCTION public.api_authorize_photo_read(p_user_id uuid, p_photo_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_path text;
BEGIN
    IF p_user_id IS NULL THEN RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501'; END IF;
    SELECT p.storage_path INTO v_path
      FROM public.report_photos p
      JOIN public.reports r ON r.id = p.report_id
     WHERE p.id = p_photo_id AND p.upload_status = 'ready'
       AND (r.created_by = p_user_id OR r.status = 'active')
       AND EXISTS (
           SELECT 1 FROM storage.objects o
           WHERE o.bucket_id = 'pet-report-photos' AND o.name = p.storage_path
       );
    IF NOT FOUND THEN RAISE EXCEPTION 'Photo is not available to this user' USING ERRCODE = '42501'; END IF;
    RETURN v_path;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_authorize_photo_read(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_authorize_photo_read(uuid, uuid) TO service_role;

-- Deletion is two phase because PostgreSQL and Storage do not share a transaction.
CREATE FUNCTION public.api_begin_photo_delete(p_user_id uuid, p_report_id uuid, p_photo_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_report_status text;
    v_photo_status text;
    v_owner uuid;
    v_path text;
BEGIN
    IF p_user_id IS NULL THEN RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501'; END IF;
    SELECT r.status, r.created_by, p.upload_status, p.storage_path
      INTO v_report_status, v_owner, v_photo_status, v_path
      FROM public.report_photos p JOIN public.reports r ON r.id = p.report_id
     WHERE p.id = p_photo_id AND r.id = p_report_id FOR UPDATE OF r, p;
    -- Missing and foreign photos have the same result; callers must not be able to enumerate IDs.
    IF NOT FOUND OR v_owner <> p_user_id THEN
        RETURN NULL;
    END IF;
    IF v_report_status <> 'draft' THEN
        RAISE EXCEPTION 'Photo is not in an editable draft' USING ERRCODE = '42501';
    END IF;
    -- A pending photo may have an upload request still in flight. Only ready photos and
    -- retries already marked deleting can enter automatic Storage cleanup.
    IF v_photo_status NOT IN ('ready', 'deleting') THEN
        RAISE EXCEPTION 'Photo upload is still pending' USING ERRCODE = '55000';
    END IF;
    UPDATE public.report_photos SET upload_status = 'deleting', cleanup_started_at = now() WHERE id = p_photo_id;
    RETURN v_path;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_begin_photo_delete(uuid, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_begin_photo_delete(uuid, uuid, uuid) TO service_role;

-- This RPC is used only when validation fails before FastAPI has attempted a Storage upload.
CREATE FUNCTION public.api_abandon_unuploaded_photo(p_user_id uuid, p_report_id uuid, p_photo_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_owner uuid;
    v_report_status text;
    v_photo_status text;
    v_path text;
BEGIN
    IF p_user_id IS NULL THEN RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501'; END IF;
    SELECT r.created_by, r.status, p.upload_status, p.storage_path
      INTO v_owner, v_report_status, v_photo_status, v_path
      FROM public.report_photos p JOIN public.reports r ON r.id = p.report_id
     WHERE p.id = p_photo_id AND r.id = p_report_id FOR UPDATE OF r, p;
    IF NOT FOUND OR v_owner <> p_user_id THEN RETURN NULL; END IF;
    IF v_report_status <> 'draft' OR v_photo_status <> 'pending' THEN
        RAISE EXCEPTION 'Photo cannot be abandoned in this state' USING ERRCODE = '55000';
    END IF;
    UPDATE public.report_photos SET upload_status = 'deleting', cleanup_started_at = now()
     WHERE id = p_photo_id;
    RETURN v_path;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_abandon_unuploaded_photo(uuid, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_abandon_unuploaded_photo(uuid, uuid, uuid) TO service_role;

CREATE FUNCTION public.api_finish_photo_delete(p_user_id uuid, p_photo_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_path text;
    v_owner uuid;
    v_report_status text;
BEGIN
    IF p_user_id IS NULL THEN RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501'; END IF;
    SELECT p.storage_path, r.created_by, r.status INTO v_path, v_owner, v_report_status
      FROM public.report_photos p JOIN public.reports r ON r.id = p.report_id
     WHERE p.id = p_photo_id AND p.upload_status = 'deleting'
     FOR UPDATE OF r, p;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF v_owner <> p_user_id OR v_report_status <> 'draft' THEN
        RAISE EXCEPTION 'Photo deletion is not authorized' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (SELECT 1 FROM storage.objects o WHERE o.bucket_id = 'pet-report-photos' AND o.name = v_path) THEN
        RAISE EXCEPTION 'Storage object still exists; metadata retained for retry';
    END IF;
    DELETE FROM public.report_photos WHERE id = p_photo_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_finish_photo_delete(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_finish_photo_delete(uuid, uuid) TO service_role;

-- Claim only rows with an explicit, recorded deletion intent. Pending uploads are never
-- reclaimed or deleted based solely on age; they remain available for manual review.
CREATE FUNCTION public.api_claim_stale_photos(p_user_id uuid)
RETURNS TABLE(photo_id uuid, storage_path text)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'Verified user id is required' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    WITH stale AS (
        SELECT p.id
          FROM public.report_photos p
          JOIN public.reports r ON r.id = p.report_id
         WHERE r.created_by = p_user_id
           AND r.status = 'draft'
           AND p.upload_status = 'deleting'
           AND (p.cleanup_started_at IS NULL OR p.cleanup_started_at < now() - interval '15 minutes')
         ORDER BY p.created_at
         FOR UPDATE OF p SKIP LOCKED
         LIMIT 100
    ), marked AS (
        UPDATE public.report_photos p
           SET upload_status = 'deleting', cleanup_started_at = now()
          FROM stale
         WHERE p.id = stale.id
        RETURNING p.id, p.storage_path
    )
    SELECT marked.id, marked.storage_path FROM marked;
END;
$function$;
REVOKE ALL ON FUNCTION public.api_claim_stale_photos(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_claim_stale_photos(uuid) TO service_role;

CREATE FUNCTION public.api_count_pending_photo_reviews(p_user_id uuid)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $function$
    SELECT count(*)
      FROM public.report_photos p
      JOIN public.reports r ON r.id = p.report_id
     WHERE p_user_id IS NOT NULL
       AND r.created_by = p_user_id
       AND r.status = 'draft'
       AND p.upload_status = 'pending';
$function$;
REVOKE ALL ON FUNCTION public.api_count_pending_photo_reviews(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_count_pending_photo_reviews(uuid) TO service_role;

-- One PostgREST RPC call executes these inserts in a single database transaction.
-- SECURITY INVOKER preserves authenticated grants and RLS; any failure rolls back all three inserts.
CREATE FUNCTION public.create_report_draft(
    p_report_type text,
    p_species text,
    p_animal_name text,
    p_breed text,
    p_color text,
    p_size text,
    p_distinctive_features text,
    p_description text,
    p_location_label text,
    p_event_at timestamptz,
    p_contact_phone text,
    p_contact_email text,
    p_precise_latitude numeric,
    p_precise_longitude numeric
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_user_id uuid := auth.uid();
    v_pet_id uuid;
    v_report_id uuid;
BEGIN
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
    END IF;
    IF p_report_type NOT IN ('lost', 'found') THEN
        RAISE EXCEPTION 'Invalid report type';
    END IF;
    IF p_species NOT IN ('dog', 'cat') THEN
        RAISE EXCEPTION 'Invalid species';
    END IF;

    IF p_report_type = 'lost' THEN
        INSERT INTO public.pets (owner_id, name, species, breed, color, size, distinctive_features)
        VALUES (v_user_id, p_animal_name, p_species, p_breed, p_color, p_size, p_distinctive_features)
        RETURNING id INTO v_pet_id;
    END IF;

    INSERT INTO public.reports (
        created_by, pet_id, report_type, species, animal_name, breed, color, size,
        distinctive_features, description, location_label, event_at
    ) VALUES (
        v_user_id, v_pet_id, p_report_type, p_species, p_animal_name, p_breed, p_color, p_size,
        p_distinctive_features, p_description, p_location_label, p_event_at
    )
    RETURNING id INTO v_report_id;

    INSERT INTO public.report_private (
        report_id, contact_phone, contact_email, precise_latitude, precise_longitude
    ) VALUES (
        v_report_id, p_contact_phone, p_contact_email, p_precise_latitude, p_precise_longitude
    );

    RETURN v_report_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.create_report_draft(text, text, text, text, text, text, text, text, text, timestamptz, text, text, numeric, numeric) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_report_draft(text, text, text, text, text, text, text, text, text, timestamptz, text, text, numeric, numeric) TO authenticated;

COMMIT;
