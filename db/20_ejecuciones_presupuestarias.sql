-- 20) Ejecuciones presupuestarias (reportes RAFAM) leídas por el bot. Correr después de 16 a 19.
-- Se puede correr más de una vez.
-- Privado por defecto: el sitio solo muestra la línea de Deporte de un reporte cuando una persona la publica
-- desde el panel (después de compararla con el PDF original).

create table if not exists public.ejecuciones_presupuestarias (
  id            uuid primary key default gen_random_uuid(),
  creado_en     timestamptz not null default now(),
  juris_slug    text not null,
  url           text not null,
  sha256        text not null unique check (sha256 ~ '^[0-9a-f]{64}$'),
  titulo        text,
  tipo          text not null check (tipo in ('gastos', 'recursos')),
  clasificacion text not null,
  ejercicio     int,
  desde         date,
  hasta         date,
  totales       jsonb,
  deporte       jsonb,               -- línea 346 Deporte y recreación (si el reporte es por función o programa)
  deporte_recursos jsonb,            -- ingresos con 'deport' o 'Juegos Bonaerenses' en la descripción
  credito       jsonb not null default '[]'::jsonb,   -- líneas con reservado+comprometido por encima del crédito
  cierre        jsonb not null default '[]'::jsonb,   -- líneas cuya aritmética no cierra
  lineas        int,
  filas         jsonb,
  publicado     boolean not null default false,
  publicado_por text,
  publicado_en  timestamptz
);
create index if not exists idx_ejec_juris on public.ejecuciones_presupuestarias(juris_slug, ejercicio, hasta);
alter table public.ejecuciones_presupuestarias enable row level security;
revoke all on public.ejecuciones_presupuestarias from anon, authenticated;

create or replace function public.panel_ejecuciones() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(to_jsonb(e) - 'filas' order by e.juris_slug, e.hasta desc, e.tipo)
                     from public.ejecuciones_presupuestarias e), '[]'::jsonb);
end $$;
revoke all on function public.panel_ejecuciones() from public, anon;
grant execute on function public.panel_ejecuciones() to authenticated;

create or replace function public.panel_publicar_ejecucion(p_id uuid, p_publicar boolean) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  update public.ejecuciones_presupuestarias
     set publicado = p_publicar, publicado_por = case when p_publicar then public.panel_revisor() end,
         publicado_en = case when p_publicar then now() end
   where id = p_id;
  if not found then raise exception 'No existe ese reporte.'; end if;
  perform public.panel_log(case when p_publicar then 'publicar_ejecucion' else 'retirar_ejecucion' end, p_id::text, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_publicar_ejecucion(uuid, boolean) from public, anon;
grant execute on function public.panel_publicar_ejecucion(uuid, boolean) to authenticated;

notify pgrst, 'reload schema';

select count(*) as reportes_leidos from public.ejecuciones_presupuestarias;
