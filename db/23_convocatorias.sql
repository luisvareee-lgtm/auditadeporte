-- 23) Registro anónimo de convocatorias a torneos: con cuánta anticipación avisan, si la fecha cambió
-- y cuánto cubrió el municipio. Sirve para medir el problema del calendario y llevarlo a la asamblea de FABA.
-- No se guarda nombre, correo, IP ni texto libre. Se puede correr más de una vez. Correr después de 22.

create table if not exists public.convocatorias (
  id            bigint generated always as identity primary key,
  creado_en     timestamptz not null default now(),
  club_id       text not null check (club_id ~ '^[a-z0-9-]{2,80}$'),
  fecha_aviso   date not null check (fecha_aviso >= date '2015-01-01'),
  fecha_torneo  date not null check (fecha_torneo between date '2015-01-01' and date '2035-12-31'),
  cambio_fecha  boolean not null default false,
  canal         text not null check (canal in ('whatsapp', 'mail', 'ambos', 'otro')),
  cobertura     text not null check (cobertura in ('total', 'parcial', 'ninguna', 'no_aplica')),
  viajaron      text not null check (viajaron in ('todos', 'parte', 'nadie')),
  check (fecha_torneo >= fecha_aviso)
);
create index if not exists idx_convocatorias_club on public.convocatorias(club_id, fecha_torneo);

alter table public.convocatorias enable row level security;
revoke all on public.convocatorias from anon, authenticated;
grant insert on public.convocatorias to anon, authenticated;
drop policy if exists inserta_convocatoria on public.convocatorias;
create policy inserta_convocatoria on public.convocatorias for insert to anon, authenticated with check (true);

-- freno a cargas masivas: como máximo 10 avisos por club por hora
create or replace function public.freno_convocatorias() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if (select count(*) from public.convocatorias where club_id = new.club_id and creado_en > now() - interval '1 hour') >= 10 then
    raise exception 'Demasiados avisos para este club en la última hora. Probá más tarde.';
  end if;
  if new.fecha_aviso > now()::date + 1 then
    raise exception 'La fecha de aviso no puede ser futura.';
  end if;
  new.creado_en := now();
  return new;
end $$;
drop trigger if exists trg_freno_convocatorias on public.convocatorias;
create trigger trg_freno_convocatorias before insert on public.convocatorias
  for each row execute function public.freno_convocatorias();

-- resumen público: solo totales y promedios, nunca filas
create or replace function public.resumen_convocatorias() returns jsonb
language sql stable security definer set search_path = public, pg_temp as $$
  with c as (select *, fecha_torneo - fecha_aviso as dias from public.convocatorias),
  g as (select club_id, count(*) n, round(avg(dias)) prom, min(dias) minimo,
               count(*) filter (where dias < 30) menos_30, count(*) filter (where cambio_fecha) cambios,
               count(*) filter (where cobertura in ('parcial', 'ninguna')) sin_cobertura_total,
               count(*) filter (where viajaron <> 'todos') no_viajaron_todos
          from c group by club_id)
  select jsonb_build_object(
    'total', (select count(*) from c),
    'promedio_dias', (select round(avg(dias)) from c),
    'menos_30', (select count(*) filter (where dias < 30) from c),
    'cambios', (select count(*) filter (where cambio_fecha) from c),
    'sin_cobertura_total', (select count(*) filter (where cobertura in ('parcial', 'ninguna')) from c),
    'no_viajaron_todos', (select count(*) filter (where viajaron <> 'todos') from c),
    'por_canal', (select coalesce(jsonb_object_agg(canal, n), '{}'::jsonb) from (select canal, count(*) n from c group by canal) x),
    'por_club', (select coalesce(jsonb_agg(to_jsonb(g) order by g.n desc), '[]'::jsonb) from g))
$$;
revoke all on function public.resumen_convocatorias() from public;
grant execute on function public.resumen_convocatorias() to anon, authenticated;

-- panel: ver y borrar avisos cargados por error o de forma abusiva
create or replace function public.panel_convocatorias() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(to_jsonb(c) order by c.creado_en desc) from public.convocatorias c), '[]'::jsonb);
end $$;
revoke all on function public.panel_convocatorias() from public, anon;
grant execute on function public.panel_convocatorias() to authenticated;

create or replace function public.panel_borrar_convocatoria(p_id bigint) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  delete from public.convocatorias where id = p_id;
  if not found then raise exception 'No existe ese aviso.'; end if;
  perform public.panel_log('borrar_convocatoria', p_id::text, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_borrar_convocatoria(bigint) from public, anon;
grant execute on function public.panel_borrar_convocatoria(bigint) to authenticated;

notify pgrst, 'reload schema';
select public.resumen_convocatorias();
