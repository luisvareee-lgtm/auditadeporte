-- 19) Carga masiva y otros formatos (Word, planillas, imágenes escaneadas). Correr después de 16, 17 y 18.
-- Se puede correr más de una vez.
-- El bot convierte cada archivo a PDF para leerlo página por página y sacar capturas; el original queda guardado
-- con su huella SHA-256.

update storage.buckets
   set file_size_limit = 52428800,
       allowed_mime_types = array[
         'application/pdf',
         'application/msword',
         'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'application/vnd.oasis.opendocument.text',
         'application/rtf', 'text/rtf',
         'application/vnd.ms-excel',
         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         'application/vnd.oasis.opendocument.spreadsheet',
         'text/csv', 'text/plain',
         'image/jpeg', 'image/png', 'image/tiff', 'image/webp',
         'application/octet-stream']
 where id = 'documentos-cargados';

alter table public.documentos_cargados drop constraint if exists documentos_cargados_ruta_check;
alter table public.documentos_cargados add constraint documentos_cargados_ruta_check
  check (ruta ~ '^[a-z0-9-]+/[0-9a-f]{64}\.(pdf|doc|docx|odt|rtf|xls|xlsx|ods|csv|txt|jpg|jpeg|png|tif|tiff|webp)$');
alter table public.documentos_cargados add column if not exists formato text;
alter table public.documentos_cargados add column if not exists lote text;          -- carga masiva: mismo lote

drop function if exists public.panel_cargar_documento(text, text, text, text, text, text);
create or replace function public.panel_cargar_documento(p_juris text, p_url text, p_titulo text, p_ruta text, p_sha text,
                                                         p_club text default null, p_formato text default 'pdf', p_lote text default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id uuid; v_ext text := lower(coalesce(nullif(p_formato, ''), 'pdf'));
begin
  perform public.panel_exige_admin();
  if p_ruta <> p_juris || '/' || p_sha || '.' || v_ext then raise exception 'La ruta no coincide con la huella del archivo.'; end if;
  if p_url !~* '^https?://[^/]+/[^?#]+' then
    raise exception 'Pegá el enlace de la página donde está publicado el documento (no la portada del sitio).'; end if;
  if nullif(p_club, '') is not null and not exists (select 1 from public.clubes where slug = p_club) then
    raise exception 'Ese club no está en el mapa.'; end if;
  insert into public.documentos_cargados(juris_slug, club_slug, url_original, titulo, ruta, sha256, cargado_por, formato, lote)
  values (p_juris, nullif(p_club, ''), p_url, left(btrim(p_titulo), 200), p_ruta, p_sha, public.panel_revisor(), v_ext, left(p_lote, 60))
  on conflict (ruta) do update set estado = 'pendiente', url_original = excluded.url_original, titulo = excluded.titulo,
                                   club_slug = excluded.club_slug, formato = excluded.formato, lote = excluded.lote
  returning id into v_id;
  perform public.panel_log('cargar_documento', v_id::text, p_url);
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;
revoke all on function public.panel_cargar_documento(text, text, text, text, text, text, text, text) from public, anon;
grant execute on function public.panel_cargar_documento(text, text, text, text, text, text, text, text) to authenticated;

-- la lista del panel muestra también el formato
create or replace function public.panel_documentos_cargados() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(to_jsonb(d) - 'resultado' || jsonb_build_object(
            'hallazgos', jsonb_array_length(coalesce(d.resultado -> 'hallazgos', '[]'::jsonb)),
            'paginas', d.resultado -> 'paginas', 'error', d.resultado ->> 'error') order by d.creado_en desc)
     from (select * from public.documentos_cargados order by creado_en desc limit 300) d), '[]'::jsonb);
end $$;

notify pgrst, 'reload schema';

select id, array_length(allowed_mime_types, 1) as formatos from storage.buckets where id = 'documentos-cargados';
