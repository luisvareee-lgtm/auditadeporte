-- 16) Capturas de documentos (con el pasaje resaltado) y carga manual de PDFs
-- Se puede correr más de una vez. Correr entero en el editor SQL de Supabase.
--
-- Por qué: algunos municipios (por ejemplo Almirante Brown, brown.gob.ar) rechazan toda consulta que llega desde
-- servidores (HTTP 403, incluso a robots.txt). No se fuerza ese bloqueo. En su lugar, una persona del equipo baja
-- el PDF desde el sitio oficial como cualquier vecino, lo carga en el panel con su enlace de origen, y el analista
-- lo lee página por página (con OCR si es un escaneo).
--
-- Depósitos (Storage):
--   documentos-cargados  privado: PDFs que carga el equipo. Solo administradores y el bot.
--   capturas             privado: capturas que arma el bot. Nadie las ve hasta que una persona las revisa.
--   capturas-publicas    público: solo las capturas que una persona eligió publicar al aprobar un documento.

-- ---------- 1) depósitos ----------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('documentos-cargados', 'documentos-cargados', false, 52428800, array['application/pdf']),
  ('capturas', 'capturas', false, 5242880, array['image/jpeg', 'image/png']),
  ('capturas-publicas', 'capturas-publicas', true, 5242880, array['image/jpeg', 'image/png'])
on conflict (id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists admin_lee_cargados on storage.objects;
create policy admin_lee_cargados on storage.objects for select to authenticated
  using (bucket_id in ('documentos-cargados', 'capturas', 'capturas-publicas') and public.es_admin());
drop policy if exists admin_sube_cargados on storage.objects;
create policy admin_sube_cargados on storage.objects for insert to authenticated
  with check (bucket_id in ('documentos-cargados', 'capturas-publicas') and public.es_admin());
drop policy if exists admin_borra_publicas on storage.objects;
create policy admin_borra_publicas on storage.objects for delete to authenticated
  using (bucket_id = 'capturas-publicas' and public.es_admin());

-- ---------- 2) documentos cargados a mano ----------
create table if not exists public.documentos_cargados (
  id           uuid primary key default gen_random_uuid(),
  creado_en    timestamptz not null default now(),
  juris_slug   text not null check (juris_slug ~ '^(muni|prov|nac)-[a-z0-9-]{2,80}$'),
  url_original text not null check (url_original ~* '^https?://'),
  titulo       text not null check (char_length(titulo) between 3 and 200),
  ruta         text not null unique check (ruta ~ '^[a-z0-9-]+/[0-9a-f]{64}\.pdf$'),
  sha256       text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  cargado_por  text,
  estado       text not null default 'pendiente' check (estado in ('pendiente', 'procesado', 'error')),
  resultado    jsonb
);
alter table public.documentos_cargados enable row level security;
revoke all on public.documentos_cargados from anon, authenticated;

create or replace function public.panel_cargar_documento(p_juris text, p_url text, p_titulo text, p_ruta text, p_sha text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id uuid;
begin
  perform public.panel_exige_admin();
  if p_ruta <> p_juris || '/' || p_sha || '.pdf' then raise exception 'La ruta no coincide con la huella del archivo.'; end if;
  insert into public.documentos_cargados(juris_slug, url_original, titulo, ruta, sha256, cargado_por)
  values (p_juris, p_url, btrim(p_titulo), p_ruta, p_sha, public.panel_revisor())
  on conflict (ruta) do update set estado = 'pendiente', url_original = excluded.url_original, titulo = excluded.titulo
  returning id into v_id;
  perform public.panel_log('cargar_documento', v_id::text, p_url);
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;
revoke all on function public.panel_cargar_documento(text, text, text, text, text) from public, anon;
grant execute on function public.panel_cargar_documento(text, text, text, text, text) to authenticated;

create or replace function public.panel_documentos_cargados() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(to_jsonb(d) - 'resultado' || jsonb_build_object(
            'hallazgos', jsonb_array_length(coalesce(d.resultado -> 'hallazgos', '[]'::jsonb)),
            'paginas', d.resultado -> 'paginas', 'error', d.resultado ->> 'error') order by d.creado_en desc)
     from (select * from public.documentos_cargados order by creado_en desc limit 100) d), '[]'::jsonb);
end $$;
revoke all on function public.panel_documentos_cargados() from public, anon;
grant execute on function public.panel_documentos_cargados() to authenticated;

-- ---------- 3) capturas y temas en los documentos publicados ----------
alter table public.documentos_fuente add column if not exists temas text[] not null default '{}';
alter table public.documentos_fuente add column if not exists capturas jsonb not null default '[]'::jsonb;
alter table public.documentos_fuente drop constraint if exists docfuente_capturas_publicas;
alter table public.documentos_fuente add constraint docfuente_capturas_publicas check (
  jsonb_typeof(capturas) = 'array' and jsonb_array_length(capturas) <= 6 and
  not jsonb_path_exists(capturas, '$[*] ? (!(@.url like_regex "^https://[a-z0-9]+\\.supabase\\.co/storage/v1/object/public/capturas-publicas/"))'));

-- Después de aprobar un documento, el panel copia las capturas elegidas al depósito público y las asocia acá.
create or replace function public.panel_capturas_documento(p_cola_id uuid, p_capturas jsonb) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare c public.cola_revision; n int;
begin
  perform public.panel_exige_admin();
  select * into c from public.cola_revision where id = p_cola_id and estado = 'aprobada';
  if not found then raise exception 'Primero aprobá el documento.'; end if;
  update public.documentos_fuente
     set capturas = coalesce(p_capturas, '[]'::jsonb),
         temas = coalesce((select array_agg(distinct x) from jsonb_array_elements_text(c.propuesta -> 'temas') x), '{}')
   where url_fuente = c.url_fuente and hash_sha256 = c.hash_sha256;
  get diagnostics n = row_count;
  if n = 0 then raise exception 'No se encontró el documento publicado.'; end if;
  perform public.panel_log('capturas_documento', p_cola_id::text, jsonb_array_length(coalesce(p_capturas, '[]'::jsonb))::text);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_capturas_documento(uuid, jsonb) from public, anon;
grant execute on function public.panel_capturas_documento(uuid, jsonb) to authenticated;

-- control
select id, public from storage.buckets where id in ('documentos-cargados', 'capturas', 'capturas-publicas') order by id;

-- que la API vea las funciones nuevas sin esperar
notify pgrst, 'reload schema';
