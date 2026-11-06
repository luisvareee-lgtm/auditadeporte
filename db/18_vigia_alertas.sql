-- 18) Vigía: alertas objetivas y explicadas para el administrador (privadas, nunca se publican solas)
-- Correr después de 16 y 17. Se puede correr más de una vez.
--
-- normas_vistas          número y año de cada decreto / resolución / ordenanza que los agentes vieron publicado
-- adjudicaciones_vistas  adjudicaciones y compras leídas en los boletines (proveedor, monto, modalidad)
-- alertas_vigia          lo que el vigía marca, con la regla, la norma, la evidencia y qué podría explicarlo
-- Todo es privado: solo el bot (clave secreta) escribe y solo un administrador lee, por funciones del panel.

create table if not exists public.normas_vistas (
  id          bigint generated always as identity primary key,
  visto_en    timestamptz not null default now(),
  juris_slug  text not null,
  tipo        text not null check (tipo in ('decreto', 'resolucion', 'ordenanza')),
  numero      int  not null check (numero > 0),
  anio        int  not null check (anio between 1990 and 2100),
  url         text not null,
  pagina      int,
  unique (juris_slug, tipo, numero, anio)
);

create table if not exists public.adjudicaciones_vistas (
  id          bigint generated always as identity primary key,
  visto_en    timestamptz not null default now(),
  juris_slug  text not null,
  proveedor   text not null,
  proveedor_n text not null,                    -- normalizado para agrupar
  monto       numeric(16,2) not null check (monto > 0),
  fecha       date,
  modalidad   text,
  norma       text,
  url         text not null,
  pagina      int,
  extracto    text,
  unique (juris_slug, proveedor_n, monto, url)
);

create table if not exists public.alertas_vigia (
  id          uuid primary key default gen_random_uuid(),
  creado_en   timestamptz not null default now(),
  actualizado_en timestamptz not null default now(),
  regla       text not null,
  clave       text not null unique,             -- la misma situación no genera dos alertas
  juris_slug  text,
  gravedad    text not null default 'media' check (gravedad in ('baja', 'media', 'alta')),
  titulo      text not null,
  explicacion jsonb not null,                   -- {que, por_que, norma, puede_explicarse, que_hacer}
  evidencia   jsonb not null default '[]'::jsonb,
  estado      text not null default 'nueva' check (estado in ('nueva', 'vista', 'confirmada', 'descartada')),
  resuelta_por text,
  nota        text
);

alter table public.normas_vistas enable row level security;
alter table public.adjudicaciones_vistas enable row level security;
alter table public.alertas_vigia enable row level security;
revoke all on public.normas_vistas, public.adjudicaciones_vistas, public.alertas_vigia from anon, authenticated;

create or replace function public.panel_alertas_vigia(p_todas boolean default false) returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return jsonb_build_object(
    'alertas', coalesce((select jsonb_agg(to_jsonb(a) order by (a.estado = 'nueva') desc, a.creado_en desc)
                           from public.alertas_vigia a
                          where p_todas or a.estado in ('nueva', 'vista')), '[]'::jsonb),
    -- cuánto acierta cada regla según lo que resolvió una persona (sirve para ajustarlas)
    'precision', coalesce((select jsonb_agg(jsonb_build_object('regla', regla, 'confirmadas', conf, 'descartadas', desc_, 'abiertas', abiertas))
                             from (select regla, count(*) filter (where estado = 'confirmada') conf,
                                          count(*) filter (where estado = 'descartada') desc_,
                                          count(*) filter (where estado in ('nueva', 'vista')) abiertas
                                     from public.alertas_vigia group by regla) r), '[]'::jsonb),
    'cobertura', coalesce((select jsonb_agg(jsonb_build_object('juris', juris_slug, 'tipo', tipo, 'anio', anio, 'vistas', n, 'desde', mn, 'hasta', mx))
                             from (select juris_slug, tipo, anio, count(*) n, min(numero) mn, max(numero) mx
                                     from public.normas_vistas group by 1, 2, 3 order by 1, 2, 3 desc) c), '[]'::jsonb));
end $$;
revoke all on function public.panel_alertas_vigia(boolean) from public, anon;
grant execute on function public.panel_alertas_vigia(boolean) to authenticated;

create or replace function public.panel_alerta_resolver(p_id uuid, p_estado text, p_nota text default null) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  if p_estado not in ('vista', 'confirmada', 'descartada') then raise exception 'Estado inválido.'; end if;
  if p_estado in ('confirmada', 'descartada') and char_length(coalesce(btrim(p_nota), '')) < 5 then
    raise exception 'Contá en pocas palabras qué verificaste: así el vigía aprende qué reglas aciertan.'; end if;
  update public.alertas_vigia set estado = p_estado, nota = left(nullif(btrim(p_nota), ''), 1000),
         resuelta_por = public.panel_revisor(), actualizado_en = now() where id = p_id;
  if not found then raise exception 'No existe esa alerta.'; end if;
  perform public.panel_log('alerta_' || p_estado, p_id::text, p_nota);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_alerta_resolver(uuid, text, text) from public, anon;
grant execute on function public.panel_alerta_resolver(uuid, text, text) to authenticated;

notify pgrst, 'reload schema';

select 'normas_vistas' t, count(*) from public.normas_vistas
union all select 'adjudicaciones_vistas', count(*) from public.adjudicaciones_vistas
union all select 'alertas_vigia', count(*) from public.alertas_vigia;
