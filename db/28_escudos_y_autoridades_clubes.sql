-- 28) Escudos de los clubes tomados de su cuenta oficial pública (foto de perfil) y autoridades de cada club con fuente.
-- El bot PROPONE el escudo; una persona lo aprueba en el panel (puede ser una foto de una persona y no un escudo).
-- Se puede correr más de una vez. Correr después de 27.

create table if not exists public.escudos_propuestos (
  club_id     uuid primary key references public.clubes(id) on delete cascade,
  url         text not null check (url ~ '^https://'),
  fuente      text not null,                -- p. ej. 'instagram:@clubx' o 'sitio FABA'
  propuesto_en timestamptz not null default now()
);
alter table public.escudos_propuestos enable row level security;
revoke all on public.escudos_propuestos from anon, authenticated;

alter table public.clubes add column if not exists logo_fuente text;
alter table public.clubes add column if not exists logo_fecha date;

create or replace function public.panel_escudos() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(jsonb_build_object('club_id', e.club_id, 'nombre', c.nombre, 'actual', c.logo_url,
                                                       'url', e.url, 'fuente', e.fuente, 'propuesto_en', e.propuesto_en) order by c.nombre)
                     from public.escudos_propuestos e join public.clubes c on c.id = e.club_id), '[]'::jsonb);
end $$;
revoke all on function public.panel_escudos() from public, anon;
grant execute on function public.panel_escudos() to authenticated;

create or replace function public.panel_escudo_decidir(p_club uuid, p_ok boolean) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare e record;
begin
  perform public.panel_exige_admin();
  select * into e from public.escudos_propuestos where club_id = p_club;
  if not found then raise exception 'No hay escudo propuesto para ese club.'; end if;
  if p_ok then
    update public.clubes set logo_url = e.url, logo_fuente = e.fuente, logo_fecha = now()::date where id = p_club;
  end if;
  delete from public.escudos_propuestos where club_id = p_club;
  perform public.panel_log(case when p_ok then 'aprobar_escudo' else 'descartar_escudo' end, p_club::text, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_escudo_decidir(uuid, boolean) from public, anon;
grant execute on function public.panel_escudo_decidir(uuid, boolean) to authenticated;

-- escudo subido a mano desde el panel (por ejemplo, descargado del sitio de FABA): queda propuesto como los demás
create or replace function public.panel_escudo_manual(p_club uuid, p_url text, p_fuente text) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  if p_url !~ '^https://[a-z0-9-]+\.supabase\.co/storage/v1/object/public/capturas-publicas/escudos/' then
    raise exception 'El escudo tiene que estar subido al almacenamiento del sitio.';
  end if;
  if length(trim(coalesce(p_fuente, ''))) < 4 then raise exception 'Indicá de dónde sale el escudo.'; end if;
  insert into public.escudos_propuestos (club_id, url, fuente) values (p_club, p_url, trim(p_fuente))
  on conflict (club_id) do update set url = excluded.url, fuente = excluded.fuente, propuesto_en = now();
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_escudo_manual(uuid, text, text) from public, anon;
grant execute on function public.panel_escudo_manual(uuid, text, text) to authenticated;

-- autoridades de un club (presidente, secretario, delegado ante FABA…), siempre con fuente pública y fecha
create or replace function public.panel_cargar_autoridad_club(p_club uuid, p_cargo text, p_nombre text, p_fuente text, p_fecha date)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id text;
begin
  perform public.panel_exige_admin();
  if p_fuente !~ '^https://' then raise exception 'La fuente tiene que ser un enlace https público.'; end if;
  if length(trim(p_nombre)) < 3 or length(trim(p_cargo)) < 3 then raise exception 'Faltan el cargo o el nombre.'; end if;
  update public.autoridades set vigente = false where club_id = p_club and lower(cargo) = lower(trim(p_cargo)) and vigente;
  insert into public.autoridades (club_id, nombre, cargo, fuente_url, fecha_fuente, vigente, publicable)
  values (p_club, trim(p_nombre), trim(p_cargo), trim(p_fuente), p_fecha, true, true) returning id::text into v_id;
  perform public.panel_log('cargar_autoridad_club', v_id, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_cargar_autoridad_club(uuid, text, text, text, date) from public, anon;
grant execute on function public.panel_cargar_autoridad_club(uuid, text, text, text, date) to authenticated;

notify pgrst, 'reload schema';
select count(*) as escudos_propuestos from public.escudos_propuestos;
