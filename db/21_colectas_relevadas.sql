-- 21) Colectas relevadas en cuentas OFICIALES de Instagram (clubes, instituciones, selecciones).
-- Solo datos objetivos: fecha, enlace, finalidad, torneo y montos que declara la propia cuenta.
-- No se guardan textos, nombres, alias, CBU ni titulares. Se puede correr más de una vez.

create table if not exists public.colectas_relevadas (
  id            bigint generated always as identity primary key,
  visto_en      timestamptz not null default now(),
  cuenta        text not null,
  nombre_cuenta text not null,
  tipo_cuenta   text not null check (tipo_cuenta in ('club', 'institucion', 'seleccion')),
  fecha         date not null,
  permalink     text not null unique check (permalink ~ '^https://(www\.)?instagram\.com/'),
  finalidades   text[] not null default '{}',
  torneos       text[] not null default '{}',
  montos        jsonb not null default '[]'::jsonb
);
alter table public.colectas_relevadas enable row level security;
revoke all on public.colectas_relevadas from anon, authenticated;

notify pgrst, 'reload schema';
select count(*) as colectas from public.colectas_relevadas;
