-- 26) Avance del rastreo de punta a punta de sitios oficiales (primero: Subsecretaría de Deportes de la Nación).
-- Cada fila es una página o documento: pendiente, visto, bloqueado (401/403/429 o robots.txt) o error.
-- Privada: solo la usa el bot. Lo que encuentra va a cola_revision y lo decide una persona. Correr después de 25.
create table if not exists public.rastreo_paginas (
  sitio        text not null,
  url          text not null check (url ~ '^https?://'),
  profundidad  int not null default 0,
  estado       text not null default 'pendiente' check (estado in ('pendiente', 'visto', 'bloqueado', 'error')),
  http         int,
  sha256       text,
  temas        text[] not null default '{}',
  visto_en     timestamptz,
  primary key (sitio, url)
);
create index if not exists idx_rastreo_pend on public.rastreo_paginas(sitio, estado, profundidad);
alter table public.rastreo_paginas enable row level security;
revoke all on public.rastreo_paginas from anon, authenticated;

create or replace function public.panel_rastreo_sitios() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(x) from (
    select sitio, count(*) filter (where estado = 'visto') vistas, count(*) filter (where estado = 'pendiente') pendientes,
           count(*) filter (where estado = 'bloqueado') bloqueadas, count(*) filter (where cardinality(temas) > 0) con_temas,
           max(visto_en) ultima
      from public.rastreo_paginas group by sitio) x), '[]'::jsonb);
end $$;
revoke all on function public.panel_rastreo_sitios() from public, anon;
grant execute on function public.panel_rastreo_sitios() to authenticated;

notify pgrst, 'reload schema';
select count(*) as paginas_en_rastreo from public.rastreo_paginas;
