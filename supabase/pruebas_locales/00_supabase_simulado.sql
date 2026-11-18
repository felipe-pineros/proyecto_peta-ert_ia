-- Imitación mínima de lo que Supabase trae de fábrica, solo para probar las migraciones.
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
CREATE SCHEMA auth;
CREATE SCHEMA extensions;
CREATE SCHEMA storage;
CREATE TABLE auth.users (
    id uuid PRIMARY KEY,
    email text,
    is_anonymous boolean NOT NULL DEFAULT false,
    raw_user_meta_data jsonb NOT NULL DEFAULT '{}'
);
CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE AS
$$ SELECT coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb) $$;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(auth.jwt() ->> 'sub', '')::uuid $$;
CREATE TABLE storage.buckets (id text PRIMARY KEY, name text, public boolean,
                              file_size_limit bigint, allowed_mime_types text[]);
GRANT USAGE ON SCHEMA public, auth, extensions TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION auth.uid(), auth.jwt() TO anon, authenticated, service_role;
-- Como Supabase: permisos amplios por defecto (las migraciones los recortan).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
