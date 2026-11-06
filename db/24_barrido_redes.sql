-- 24) Barrido exhaustivo de cuentas oficiales de Instagram: avance por cuenta y publicaciones con señales útiles
-- que no son colectas (quién apoya, viajes, equipamiento nuevo, reclamos, avisos de torneo). Correr después de 23.
-- Se puede correr más de una vez. No se guardan textos, nombres de personas, alias ni CBU: solo rasgos y el enlace.

create table if not exists public.barrido_redes (
  cuenta        text primary key,
  cursor        text,                 -- dónde siguió la última corrida (null = terminó o empieza de nuevo)
  completo      boolean not null default false,
  posts_leidos  int not null default 0,
  mas_nuevo     date,
  actualizado   timestamptz not null default now()
);
alter table public.barrido_redes enable row level security;
revoke all on public.barrido_redes from anon, authenticated;

create table if not exists public.publicaciones_relevantes (
  id            bigint generated always as identity primary key,
  visto_en      timestamptz not null default now(),
  cuenta        text not null,
  nombre_cuenta text not null,
  tipo_cuenta   text not null check (tipo_cuenta in ('club', 'institucion', 'seleccion')),
  fecha         date not null,
  permalink     text not null unique check (permalink ~ '^https://(www\.)?(instagram\.com|facebook\.com)/'),
  senales       text[] not null default '{}',
  torneos       text[] not null default '{}',
  revisada      boolean not null default false
);
create index if not exists idx_pub_rel_cuenta on public.publicaciones_relevantes(cuenta, fecha);
alter table public.publicaciones_relevantes enable row level security;
revoke all on public.publicaciones_relevantes from anon, authenticated;

create or replace function public.panel_barrido_redes() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return jsonb_build_object(
    'cuentas', coalesce((select jsonb_agg(to_jsonb(b) - 'cursor' order by b.cuenta) from public.barrido_redes b), '[]'::jsonb),
    'publicaciones', coalesce((select jsonb_agg(to_jsonb(p) order by p.revisada, p.fecha desc)
                                 from (select * from public.publicaciones_relevantes order by revisada, fecha desc limit 300) p), '[]'::jsonb));
end $$;
revoke all on function public.panel_barrido_redes() from public, anon;
grant execute on function public.panel_barrido_redes() to authenticated;

create or replace function public.panel_publicacion_revisar(p_id bigint, p_ok boolean) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  if p_ok then update public.publicaciones_relevantes set revisada = true where id = p_id;
  else delete from public.publicaciones_relevantes where id = p_id; end if;
  if not found then raise exception 'No existe esa publicación.'; end if;
  perform public.panel_log(case when p_ok then 'aprobar_publicacion' else 'descartar_publicacion' end, p_id::text, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_publicacion_revisar(bigint, boolean) from public, anon;
grant execute on function public.panel_publicacion_revisar(bigint, boolean) to authenticated;

notify pgrst, 'reload schema';
select count(*) as cuentas_en_barrido from public.barrido_redes;
