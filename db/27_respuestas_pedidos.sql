-- 27) Respuestas a los pedidos de acceso a la información: quien presentó un pedido anota (sin nombre) cuándo lo
-- presentó, si le respondieron, cuándo y cómo. Con eso el Tablero muestra cuánto tarda cada organismo y cuánto responde.
-- Además, población (Censo 2022) y forma de cada municipio para comparar gasto por habitante y dibujar el mapa.
-- Se puede correr más de una vez. Correr después de 26.

create table if not exists public.respuestas_pedidos (
  id                bigint generated always as identity primary key,
  creado_en         timestamptz not null default now(),
  juris_slug        text not null check (juris_slug ~ '^(muni|prov|nac)-[a-z0-9-]{2,80}$'),
  fecha_presentado  date not null check (fecha_presentado >= date '2015-01-01'),
  resultado         text not null check (resultado in ('completa', 'parcial', 'denegada', 'sin_respuesta')),
  fecha_respuesta   date,
  check (fecha_respuesta is null or fecha_respuesta >= fecha_presentado),
  check ((resultado = 'sin_respuesta') = (fecha_respuesta is null))
);
create index if not exists idx_respuestas_juris on public.respuestas_pedidos(juris_slug);
alter table public.respuestas_pedidos enable row level security;
revoke all on public.respuestas_pedidos from anon, authenticated;
grant insert on public.respuestas_pedidos to anon, authenticated;
drop policy if exists inserta_respuesta on public.respuestas_pedidos;
create policy inserta_respuesta on public.respuestas_pedidos for insert to anon, authenticated with check (true);

create or replace function public.freno_respuestas() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if (select count(*) from public.respuestas_pedidos where juris_slug = new.juris_slug and creado_en > now() - interval '1 hour') >= 10 then
    raise exception 'Demasiadas respuestas para este organismo en la última hora. Probá más tarde.';
  end if;
  if new.fecha_presentado > now()::date or new.fecha_respuesta > now()::date then
    raise exception 'Las fechas no pueden ser futuras.';
  end if;
  new.creado_en := now();
  return new;
end $$;
drop trigger if exists trg_freno_respuestas on public.respuestas_pedidos;
create trigger trg_freno_respuestas before insert on public.respuestas_pedidos for each row execute function public.freno_respuestas();

-- resumen público por organismo: solo totales. "sin_respuesta" cuenta como vencido si pasaron más de 30 días hábiles (~42 corridos)
create or replace function public.resumen_respuestas() returns jsonb
language sql stable security definer set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(x order by x.respondidos::numeric / greatest(x.total, 1) desc, x.dias_promedio nulls last), '[]'::jsonb) from (
    select juris_slug, count(*) total,
           count(*) filter (where resultado in ('completa', 'parcial')) respondidos,
           count(*) filter (where resultado = 'completa') completas,
           count(*) filter (where resultado = 'denegada') denegadas,
           count(*) filter (where resultado = 'sin_respuesta' and fecha_presentado < now()::date - 42) vencidos,
           round(avg(fecha_respuesta - fecha_presentado) filter (where fecha_respuesta is not null)) dias_promedio
      from public.respuestas_pedidos group by juris_slug) x
$$;
revoke all on function public.resumen_respuestas() from public;
grant execute on function public.resumen_respuestas() to anon, authenticated;

create or replace function public.panel_borrar_respuesta(p_id bigint) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  delete from public.respuestas_pedidos where id = p_id;
  if not found then raise exception 'No existe esa respuesta.'; end if;
  perform public.panel_log('borrar_respuesta', p_id::text, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_borrar_respuesta(bigint) from public, anon;
grant execute on function public.panel_borrar_respuesta(bigint) to authenticated;

notify pgrst, 'reload schema';
select public.resumen_respuestas();
