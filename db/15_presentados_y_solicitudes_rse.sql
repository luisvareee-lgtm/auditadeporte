-- 15) Contador anónimo "ya lo presenté" y pedidos de patrocinio de equipos y deportistas
-- Se puede correr más de una vez. Correr entero en el editor SQL de Supabase.
--
-- 1. pedidos_presentados: una persona avisa que presentó un pedido de información a una jurisdicción.
--    No se guarda nombre, correo, IP ni texto: solo el lugar y la fecha. El público solo puede insertar;
--    el conteo se lee con una función que devuelve totales, nunca filas.
-- 2. tips acepta el tipo 'solicitud_rse': un equipo o deportista cuenta qué necesita (silla, viajes, etc.).
--    Llega a la Bandeja como cualquier mensaje privado. Si el equipo de revisión lo aprueba, se crea un
--    BORRADOR de pliego (no publicado) con panel_tip_a_pliego, y se publica desde Borradores como siempre.

-- ---------- 1) contador anónimo ----------
create table if not exists public.pedidos_presentados (
  id          bigint generated always as identity primary key,
  creado_en   timestamptz not null default now(),
  juris_slug  text not null check (juris_slug ~ '^(muni|prov|nac)-[a-z0-9-]{2,80}$')
);
create index if not exists idx_pedidos_presentados_juris on public.pedidos_presentados(juris_slug, creado_en);

alter table public.pedidos_presentados enable row level security;
revoke all on public.pedidos_presentados from anon, authenticated;
grant insert on public.pedidos_presentados to anon, authenticated;
drop policy if exists inserta_presentado on public.pedidos_presentados;
create policy inserta_presentado on public.pedidos_presentados for insert to anon, authenticated
  with check (creado_en > now() - interval '1 minute' and creado_en < now() + interval '1 minute');

-- freno a cargas masivas: como máximo 20 avisos por lugar por hora
create or replace function public.freno_pedidos_presentados() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if (select count(*) from public.pedidos_presentados
       where juris_slug = new.juris_slug and creado_en > now() - interval '1 hour') >= 20 then
    raise exception 'Demasiados avisos para este lugar en la última hora. Probá más tarde.';
  end if;
  new.creado_en := now();
  return new;
end $$;
drop trigger if exists trg_freno_pedidos_presentados on public.pedidos_presentados;
create trigger trg_freno_pedidos_presentados before insert on public.pedidos_presentados
  for each row execute function public.freno_pedidos_presentados();

-- conteo público: solo totales por lugar
create or replace function public.contar_pedidos_presentados()
returns table(juris_slug text, total bigint, ultimo date)
language sql stable security definer set search_path = public, pg_temp as $$
  select p.juris_slug, count(*), max(p.creado_en)::date
    from public.pedidos_presentados p
   group by p.juris_slug
$$;
revoke all on function public.contar_pedidos_presentados() from public;
grant execute on function public.contar_pedidos_presentados() to anon, authenticated;

-- ---------- 2) pedidos de patrocinio (solicitud_rse) ----------
alter table public.tips drop constraint if exists tips_tipo_check;
alter table public.tips add constraint tips_tipo_check
  check (tipo in ('documento','dato','correccion','replica','solicitud_rse'));

create or replace function public.panel_tip_a_pliego(p_id bigint, p_rubro text, p_titulo text, p_descripcion text) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare t public.tips; v_club uuid; v_id uuid;
begin
  perform public.panel_exige_admin();
  select * into t from public.tips where id = p_id and tipo = 'solicitud_rse' and estado in ('nuevo','en_revision') for update;
  if not found then raise exception 'No hay un pedido de patrocinio abierto con ese id.'; end if;
  select id into v_club from public.clubes where slug = t.club_slug;
  if v_club is null then raise exception 'El pedido necesita un club del mapa. Elegí el club antes de crear el pliego.'; end if;
  if char_length(coalesce(p_titulo, '')) < 5 then raise exception 'Poné un título de al menos 5 letras.'; end if;
  insert into public.pliegos_rse(codigo, club_id, rubro, titulo, descripcion, monto_referencial_ars, contraprestacion, publicado)
  values ('SOL-' || upper(left(t.club_slug, 12)) || '-' || to_char(now(), 'YYYYMMDD') || '-' || p_id,
          v_club, coalesce(nullif(left(p_rubro, 40), ''), 'a_definir'), left(p_titulo, 150),
          nullif(left(p_descripcion, 1000), ''), 0, 'A definir entre el equipo y la empresa', false)
  returning id into v_id;
  update public.tips set estado = 'verificado',
         notas_internas = left(coalesce(notas_internas || ' · ', '') || 'Borrador de pliego ' || v_id || ' por ' || public.panel_revisor(), 1000)
   where id = p_id;
  perform public.panel_log('tip_a_pliego', p_id::text, v_id::text);
  return jsonb_build_object('ok', true, 'pliego_id', v_id);
end $$;
revoke all on function public.panel_tip_a_pliego(bigint, text, text, text) from public, anon;
grant execute on function public.panel_tip_a_pliego(bigint, text, text, text) to authenticated;

-- control
select 'pedidos_presentados' as objeto, count(*) as filas from public.pedidos_presentados
union all
select 'tipos de tips', count(*) from pg_constraint where conname = 'tips_tipo_check';
