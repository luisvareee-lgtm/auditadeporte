-- 22) Colectas ampliadas: tipo de pedido (rifa, venta, alias, evento…), a quién se pide, fecha límite,
-- fuente (Instagram, sitio de FABA o carga manual) y revisión humana antes de publicar. Correr después de 21.
-- Se puede correr más de una vez. Sigue sin guardarse ningún texto, nombre, alias, CBU ni titular.

alter table public.colectas_relevadas add column if not exists tipos_pedido  text[] not null default '{}';
alter table public.colectas_relevadas add column if not exists destinatarios text[] not null default '{}';
alter table public.colectas_relevadas add column if not exists fecha_limite  date;
alter table public.colectas_relevadas add column if not exists fuente        text not null default 'instagram';
alter table public.colectas_relevadas add column if not exists revisada      boolean;
alter table public.colectas_relevadas add column if not exists revisada_por  text;

-- lo que ya estaba publicado antes de esta versión queda como revisado; lo nuevo entra sin revisar
update public.colectas_relevadas set revisada = true where revisada is null;
alter table public.colectas_relevadas alter column revisada set default false;
alter table public.colectas_relevadas alter column revisada set not null;

alter table public.colectas_relevadas drop constraint if exists colectas_relevadas_fuente_check;
alter table public.colectas_relevadas add constraint colectas_relevadas_fuente_check
  check (fuente in ('instagram', 'faba_web', 'manual'));
-- enlaces solo a publicaciones de cuentas oficiales o al sitio de FABA
alter table public.colectas_relevadas drop constraint if exists colectas_relevadas_permalink_check;
alter table public.colectas_relevadas add constraint colectas_relevadas_permalink_check
  check (permalink ~ '^https://(www\.)?(instagram\.com|facebook\.com|basquetadaptado\.com\.ar)/');

create or replace function public.panel_colectas() returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  return coalesce((select jsonb_agg(to_jsonb(c) order by c.revisada, c.fecha desc) from public.colectas_relevadas c), '[]'::jsonb);
end $$;
revoke all on function public.panel_colectas() from public, anon;
grant execute on function public.panel_colectas() to authenticated;

-- aprobar (p_ok = true) o descartar (false: se borra, por ejemplo si era de salud o de una persona)
create or replace function public.panel_colecta_revisar(p_id bigint, p_ok boolean) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform public.panel_exige_admin();
  if p_ok then
    update public.colectas_relevadas set revisada = true, revisada_por = public.panel_revisor() where id = p_id;
  else
    delete from public.colectas_relevadas where id = p_id;
  end if;
  if not found then raise exception 'No existe esa colecta.'; end if;
  perform public.panel_log(case when p_ok then 'aprobar_colecta' else 'descartar_colecta' end, p_id::text, null);
  return jsonb_build_object('ok', true);
end $$;
revoke all on function public.panel_colecta_revisar(bigint, boolean) from public, anon;
grant execute on function public.panel_colecta_revisar(bigint, boolean) to authenticated;

-- carga manual de una colecta vista en una cuenta oficial (para cuentas que el bot todavía no puede leer)
create or replace function public.panel_cargar_colecta(p_cuenta text, p_nombre text, p_tipo_cuenta text, p_fecha date, p_permalink text,
  p_finalidades text[], p_tipos_pedido text[], p_destinatarios text[], p_torneos text[], p_monto numeric, p_moneda text, p_fecha_limite date)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id bigint;
begin
  perform public.panel_exige_admin();
  insert into public.colectas_relevadas (cuenta, nombre_cuenta, tipo_cuenta, fecha, permalink, finalidades, tipos_pedido, destinatarios,
                                          torneos, montos, fecha_limite, fuente, revisada, revisada_por)
  values (lower(trim(p_cuenta)), trim(p_nombre), p_tipo_cuenta, p_fecha, trim(p_permalink), coalesce(p_finalidades, '{}'),
          coalesce(p_tipos_pedido, '{}'), coalesce(p_destinatarios, '{}'), coalesce(p_torneos, '{}'),
          case when p_monto is null then '[]'::jsonb else jsonb_build_array(jsonb_build_object('moneda', coalesce(p_moneda, 'ARS'), 'valor', p_monto)) end,
          p_fecha_limite, 'manual', true, public.panel_revisor())
  on conflict (permalink) do update set finalidades = excluded.finalidades, tipos_pedido = excluded.tipos_pedido,
     destinatarios = excluded.destinatarios, torneos = excluded.torneos, montos = excluded.montos, fecha_limite = excluded.fecha_limite
  returning id into v_id;
  perform public.panel_log('cargar_colecta', v_id::text, null);
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;
revoke all on function public.panel_cargar_colecta(text, text, text, date, text, text[], text[], text[], text[], numeric, text, date) from public, anon;
grant execute on function public.panel_cargar_colecta(text, text, text, date, text, text[], text[], text[], text[], numeric, text, date) to authenticated;

notify pgrst, 'reload schema';
select fuente, revisada, count(*) from public.colectas_relevadas group by 1, 2;
