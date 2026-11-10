-- 29) Tres cosas:
--   a) Escudos: se guarda la huella sha256 del archivo publicado (el archivo ya vive en nuestro almacenamiento, en .webp).
--   b) "Quiero que publiquen": apoyo anónimo por organismo. Solo un número: no hay nombres, correos ni firmas.
--   c) Memoria léxica para que el bot aprenda de tus decisiones: por posteo se guarda qué términos de un DICCIONARIO
--      CERRADO aparecieron y qué decidiste. Nunca el texto, ni nombres, ni palabras fuera de esa lista. Es privada.
-- Se puede correr más de una vez. Correr después de 28.

-- ───────────────────────────── a) escudos con huella
alter table public.escudos_propuestos add column if not exists sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$');
alter table public.clubes add column if not exists logo_sha256 text check (logo_sha256 is null or logo_sha256 ~ '^[0-9a-f]{64}$');

create or replace function public.panel_escudos() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(jsonb_build_object('club_id', e.club_id, 'nombre', c.nombre, 'actual', c.logo_url,
                                                       'url', e.url, 'fuente', e.fuente, 'propuesto_en', e.propuesto_en, 'sha256', e.sha256) order by c.nombre)
                     from public.escudos_propuestos e join public.clubes c on c.id = e.club_id), '[]'::jsonb);
end $$;

create or replace function public.panel_escudo_decidir(p_club uuid, p_ok boolean) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare e record;
begin
  perform public.panel_exige_admin();
  select * into e from public.escudos_propuestos where club_id = p_club;
  if not found then raise exception 'No hay escudo propuesto para ese club.'; end if;
  if p_ok then
    update public.clubes set logo_url = e.url, logo_fuente = e.fuente, logo_fecha = now()::date, logo_sha256 = e.sha256 where id = p_club;
  end if;
  delete from public.escudos_propuestos where club_id = p_club;
  perform public.panel_log(case when p_ok then 'aprobar_escudo' else 'descartar_escudo' end, p_club::text,
                           case when p_ok then e.sha256 end);
  return jsonb_build_object('ok', true);
end $$;

drop function if exists public.panel_escudo_manual(uuid, text, text);
create or replace function public.panel_escudo_manual(p_club uuid, p_url text, p_fuente text, p_sha256 text default null) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  if p_url !~ '^https://[a-z0-9-]+\.supabase\.co/storage/v1/object/public/capturas-publicas/escudos/' then
    raise exception 'El escudo tiene que estar subido al almacenamiento del sitio.';
  end if;
  if length(trim(coalesce(p_fuente, ''))) < 4 then raise exception 'Indicá de dónde sale el escudo.'; end if;
  insert into public.escudos_propuestos (club_id, url, fuente, sha256) values (p_club, p_url, trim(p_fuente), p_sha256)
  on conflict (club_id) do update set url = excluded.url, fuente = excluded.fuente, sha256 = excluded.sha256, propuesto_en = now();
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_escudo_manual(uuid, text, text, text) from public, anon;
grant execute on function public.panel_escudo_manual(uuid, text, text, text) to authenticated;

-- ───────────────────────────── b) "Quiero que publiquen"
create table if not exists public.apoyos_publicacion (
  id          bigint generated always as identity primary key,
  creado_en   timestamptz not null default now(),
  juris_slug  text not null check (juris_slug ~ '^(muni|prov|nac)-[a-z0-9-]{2,80}$')
);
create index if not exists idx_apoyos_juris on public.apoyos_publicacion(juris_slug, creado_en);
alter table public.apoyos_publicacion enable row level security;
revoke all on public.apoyos_publicacion from anon, authenticated;
grant insert on public.apoyos_publicacion to anon, authenticated;
drop policy if exists inserta_apoyo on public.apoyos_publicacion;
create policy inserta_apoyo on public.apoyos_publicacion for insert to anon, authenticated with check (true);

create or replace function public.freno_apoyos() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if (select count(*) from public.apoyos_publicacion where juris_slug = new.juris_slug and creado_en > now() - interval '1 hour') >= 30 then
    raise exception 'Demasiados apoyos para este lugar en la última hora. Probá más tarde.';
  end if;
  new.creado_en := now();
  return new;
end $$;
drop trigger if exists trg_freno_apoyos on public.apoyos_publicacion;
create trigger trg_freno_apoyos before insert on public.apoyos_publicacion for each row execute function public.freno_apoyos();

create or replace function public.contar_apoyos_publicacion() returns table(juris_slug text, total bigint)
language sql stable security definer set search_path = public, pg_temp as $$
  select a.juris_slug, count(*) from public.apoyos_publicacion a group by a.juris_slug
$$;
revoke all on function public.contar_apoyos_publicacion() from public;
grant execute on function public.contar_apoyos_publicacion() to anon, authenticated;

-- ───────────────────────────── c) memoria léxica (privada)
create table if not exists public.memoria_lexica (
  permalink    text primary key check (permalink ~ '^https://'),
  cuenta       text not null,
  tipo_cuenta  text,
  fecha        date,
  terminos     text[] not null default '{}',      -- claves del diccionario cerrado del bot (p. ej. 'hospital', 'liga')
  huella       jsonb not null default '{}',        -- señales y marcas de contexto (letras), sin texto
  decision     text check (decision in ('aprobado', 'descartado')),
  motivo       text check (motivo is null or motivo in ('fuera_de_contexto', 'deporte_convencional', 'no_es_del_tipo', 'salud_o_persona', 'repetida', 'otro')),
  decidido_en  timestamptz,
  creado_en    timestamptz not null default now()
);
create index if not exists idx_memoria_decision on public.memoria_lexica(decision) where decision is not null;
alter table public.memoria_lexica enable row level security;
revoke all on public.memoria_lexica from anon, authenticated;       -- solo el bot (clave de servicio) y las funciones del panel

alter table public.publicaciones_relevantes add column if not exists puntaje smallint check (puntaje between 0 and 100);
alter table public.colectas_relevadas add column if not exists puntaje smallint check (puntaje between 0 and 100);

create or replace function public.memoria_anotar(p_permalink text, p_cuenta text, p_tipo text, p_fecha date, p_ok boolean, p_motivo text) returns void
language sql security definer set search_path = public, pg_temp as $$
  insert into public.memoria_lexica (permalink, cuenta, tipo_cuenta, fecha, decision, motivo, decidido_en)
  values (p_permalink, p_cuenta, p_tipo, p_fecha, case when p_ok then 'aprobado' else 'descartado' end, case when p_ok then null else coalesce(p_motivo, 'otro') end, now())
  on conflict (permalink) do update set decision = excluded.decision, motivo = excluded.motivo, decidido_en = now()
$$;
revoke all on function public.memoria_anotar(text, text, text, date, boolean, text) from public, anon, authenticated;

drop function if exists public.panel_publicacion_revisar(bigint, boolean);
create or replace function public.panel_publicacion_revisar(p_id bigint, p_ok boolean, p_motivo text default null) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare r public.publicaciones_relevantes;
begin
  perform public.panel_exige_admin();
  select * into r from public.publicaciones_relevantes where id = p_id;
  if not found then raise exception 'No existe esa publicación.'; end if;
  perform public.memoria_anotar(r.permalink, r.cuenta, r.tipo_cuenta, r.fecha, p_ok, p_motivo);
  if p_ok then update public.publicaciones_relevantes set revisada = true where id = p_id;
  else delete from public.publicaciones_relevantes where id = p_id; end if;
  perform public.panel_log(case when p_ok then 'aprobar_publicacion' else 'descartar_publicacion' end, p_id::text,
                           p_motivo);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_publicacion_revisar(bigint, boolean, text) from public, anon;
grant execute on function public.panel_publicacion_revisar(bigint, boolean, text) to authenticated;

drop function if exists public.panel_colecta_revisar(bigint, boolean);
create or replace function public.panel_colecta_revisar(p_id bigint, p_ok boolean, p_motivo text default null) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare r public.colectas_relevadas;
begin
  perform public.panel_exige_admin();
  select * into r from public.colectas_relevadas where id = p_id;
  if not found then raise exception 'No existe esa colecta.'; end if;
  if r.permalink ~ '^https://' then
    perform public.memoria_anotar(r.permalink, r.cuenta, r.tipo_cuenta, r.fecha, p_ok, p_motivo);
  end if;
  if p_ok then
    update public.colectas_relevadas set revisada = true, revisada_por = public.panel_revisor() where id = p_id;
  else
    delete from public.colectas_relevadas where id = p_id;
  end if;
  perform public.panel_log(case when p_ok then 'aprobar_colecta' else 'descartar_colecta' end, p_id::text,
                           p_motivo);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_colecta_revisar(bigint, boolean, text) from public, anon;
grant execute on function public.panel_colecta_revisar(bigint, boolean, text) to authenticated;

-- lo que ya aprobaste antes de esta migración también sirve para aprender (lo descartado se borró y no se puede recuperar)
insert into public.memoria_lexica (permalink, cuenta, tipo_cuenta, fecha, decision, decidido_en)
select permalink, cuenta, tipo_cuenta, fecha, 'aprobado', now() from public.publicaciones_relevantes where revisada and permalink ~ '^https://'
on conflict (permalink) do nothing;
insert into public.memoria_lexica (permalink, cuenta, tipo_cuenta, fecha, decision, decidido_en)
select permalink, cuenta, tipo_cuenta, fecha, 'aprobado', now() from public.colectas_relevadas where revisada and permalink ~ '^https://'
on conflict (permalink) do nothing;

notify pgrst, 'reload schema';
select (select count(*) from public.memoria_lexica) as memoria, (select count(*) from public.apoyos_publicacion) as apoyos;
