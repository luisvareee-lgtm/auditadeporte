-- 17) Correcciones del panel. Correr DESPUÉS de 16 (si 16 da error, avisá el mensaje y no corras este).
-- Se puede correr más de una vez.
--
-- 1. La tabla tips guarda club_id (no club_slug): se corrige la función que crea un pliego desde un pedido de patrocinio.
-- 2. Carga manual de PDFs: se puede indicar también el club, no solo el municipio o la provincia.
-- 4. Bandeja e historial fallaban con "column t.club_slug does not exist": se leen por club_id.
-- 3. Revisión documental con enlace a una portada o menú: el panel permite reemplazarlo por el enlace concreto al
--    documento (por ejemplo, el PDF del balance) antes de aprobar. El enlace nuevo tiene que ser una página concreta.

-- ---------- 1) pedido de patrocinio -> borrador de pliego ----------
create or replace function public.panel_tip_a_pliego(p_id bigint, p_rubro text, p_titulo text, p_descripcion text) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare t public.tips; v_slug text; v_id uuid;
begin
  perform public.panel_exige_admin();
  select * into t from public.tips where id = p_id and tipo = 'solicitud_rse' and estado in ('nuevo','en_revision') for update;
  if not found then raise exception 'No hay un pedido de patrocinio abierto con ese id.'; end if;
  if t.club_id is null then raise exception 'El pedido no indica un club del mapa: no se puede crear el pliego.'; end if;
  select slug into v_slug from public.clubes where id = t.club_id;
  if char_length(coalesce(p_titulo, '')) < 5 then raise exception 'Poné un título de al menos 5 letras.'; end if;
  insert into public.pliegos_rse(codigo, club_id, rubro, titulo, descripcion, monto_referencial_ars, contraprestacion, publicado)
  values ('SOL-' || upper(left(coalesce(v_slug, 'club'), 12)) || '-' || to_char(now(), 'YYYYMMDD') || '-' || p_id,
          t.club_id, coalesce(nullif(left(p_rubro, 40), ''), 'a_definir'), left(p_titulo, 150),
          nullif(left(p_descripcion, 1000), ''), 0, 'A definir entre el equipo y la empresa', false)
  returning id into v_id;
  update public.tips set estado = 'verificado',
         notas_internas = left(coalesce(notas_internas || ' · ', '') || 'Borrador de pliego ' || v_id || ' por ' || public.panel_revisor(), 1000)
   where id = p_id;
  perform public.panel_log('tip_a_pliego', p_id::text, v_id::text);
  return jsonb_build_object('ok', true, 'pliego_id', v_id);
end $$;

-- ---------- 2) carga manual con club opcional ----------
alter table public.documentos_cargados add column if not exists club_slug text
  check (club_slug is null or club_slug ~ '^[a-z0-9-]{2,80}$');

drop function if exists public.panel_cargar_documento(text, text, text, text, text);
create or replace function public.panel_cargar_documento(p_juris text, p_url text, p_titulo text, p_ruta text, p_sha text,
                                                         p_club text default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id uuid;
begin
  perform public.panel_exige_admin();
  if p_ruta <> p_juris || '/' || p_sha || '.pdf' then raise exception 'La ruta no coincide con la huella del archivo.'; end if;
  if p_url !~* '^https?://[^/]+/[^?#]+' then
    raise exception 'Pegá el enlace de la página donde está publicado el documento (no la portada del sitio).'; end if;
  if nullif(p_club, '') is not null and not exists (select 1 from public.clubes where slug = p_club) then
    raise exception 'Ese club no está en el mapa.'; end if;
  insert into public.documentos_cargados(juris_slug, club_slug, url_original, titulo, ruta, sha256, cargado_por)
  values (p_juris, nullif(p_club, ''), p_url, btrim(p_titulo), p_ruta, p_sha, public.panel_revisor())
  on conflict (ruta) do update set estado = 'pendiente', url_original = excluded.url_original, titulo = excluded.titulo,
                                   club_slug = excluded.club_slug
  returning id into v_id;
  perform public.panel_log('cargar_documento', v_id::text, p_url);
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;
revoke all on function public.panel_cargar_documento(text, text, text, text, text, text) from public, anon;
grant execute on function public.panel_cargar_documento(text, text, text, text, text, text) to authenticated;

-- ---------- 3) reemplazar el enlace de un ítem pendiente por el del documento concreto ----------
create or replace function public.panel_cola_cambiar_url(p_id uuid, p_url text, p_motivo text default null) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare c public.cola_revision;
begin
  perform public.panel_exige_admin();
  select * into c from public.cola_revision where id = p_id and estado = 'pendiente' for update;
  if not found then raise exception 'No hay un ítem pendiente con ese id.'; end if;
  if p_url !~* '^https://[^/]+/[^?#]+' then
    raise exception 'El enlace nuevo tiene que ser https y llevar a una página o archivo concreto (no a la portada).'; end if;
  if exists (select 1 from public.cola_revision o where o.id <> p_id and o.url_fuente = p_url and o.hash_sha256 is not distinct from c.hash_sha256) then
    raise exception 'Ya hay otro ítem con ese mismo enlace.'; end if;
  update public.cola_revision
     set url_fuente = p_url,
         propuesta = coalesce(propuesta, '{}'::jsonb) || jsonb_build_object('url_original_del_agente', c.url_fuente,
                       'url_cambiada_por', public.panel_revisor(), 'motivo_cambio_url', left(coalesce(p_motivo, ''), 300))
   where id = p_id;
  perform public.panel_log('cola_cambiar_url', p_id::text, c.url_fuente || ' -> ' || p_url);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_cola_cambiar_url(uuid, text, text) from public, anon;
grant execute on function public.panel_cola_cambiar_url(uuid, text, text) to authenticated;

-- ---------- 4) bandeja e historial: tips guarda club_id ----------
create or replace function public.panel_bandeja(p_historial boolean default false) returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.creado_en) from (
    select 'cola'::text as origen, c.id::text as id, c.tipo, c.titulo, coalesce(cl.nombre, ins.sigla) as destino,
           c.url_fuente as url, c.creado_en, c.estado,
           case when c.estado = 'bloqueada_legal' then 'bloqueada'
                when c.veto_juridico is not null
                  or jsonb_array_length(coalesce(c.propuesta #> '{_mesa,observaciones}', '[]'::jsonb)) > 0 then 'observada'
                else 'limpia' end as semaforo
      from public.cola_revision c
      left join public.clubes cl on cl.id = c.club_id
      left join public.instituciones ins on ins.id = c.institucion_id
     where case when p_historial then c.estado in ('aprobada','rechazada') else c.estado in ('pendiente','bloqueada_legal') end
    union all
    select 'tip', t.id::text, t.tipo, left(t.texto, 90), ct.nombre, t.url, t.creado_en, t.estado, 'limpia'
      from public.tips t
      left join public.clubes ct on ct.id = t.club_id
     where case when p_historial then t.estado in ('verificado','descartado') else t.estado in ('nuevo','en_revision') end
    union all
    select 'postulacion', p.id::text, 'postulacion', p.empresa || ' → ' || p.pliego_codigo, p.pliego_codigo, null, p.creado_en, p.estado, 'limpia'
      from public.postulaciones_rse p
     where case when p_historial then p.estado in ('contactada','descartada') else p.estado = 'nueva' end
    union all
    select 'presentacion', pr.id::text, 'presentacion', pr.nombre || ' (' || pr.ciudad || ')', pr.club_slug, pr.web, pr.creado_en, pr.estado, 'limpia'
      from public.presentaciones_club pr
     where case when p_historial then pr.estado in ('aprobada','rechazada') else pr.estado in ('nueva','en_revision') end
    order by 7 desc limit 500
  ) x), '[]'::jsonb);
end $$;

-- control: tienen que aparecer las tres funciones
select proname from pg_proc where pronamespace = 'public'::regnamespace
   and proname in ('panel_tip_a_pliego', 'panel_cargar_documento', 'panel_cola_cambiar_url', 'panel_documentos_cargados')
 order by proname;

-- que la API vea las funciones nuevas sin esperar
notify pgrst, 'reload schema';
