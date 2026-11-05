-- ============================================================================
-- 11_ACTIVIDAD_REDES.sql  (ejecutar DESPUÉS de 10; se puede correr más de una vez)
-- 1) Tabla privada redes_actividad: una foto por cuenta y por día (seguidores, publicaciones,
--    último posteo, posteos en 90 días, si se pudo leer). No guarda textos ni fotos de posteos.
-- 2) Acción "actualizar_division_club" para aprobar desde el panel la división que un club
--    menciona en su Instagram oficial (con el enlace al posteo como respaldo).
-- ============================================================================
create table if not exists public.redes_actividad (
  id             bigint generated always as identity primary key,
  club_id        uuid references public.clubes(id) on delete cascade,
  institucion_id uuid references public.instituciones(id) on delete cascade,
  plataforma     text not null default 'instagram' check (plataforma in ('instagram','facebook','youtube')),
  cuenta         text not null check (cuenta ~ '^[a-z0-9._]{1,30}$'),
  fecha_consulta date not null default current_date,
  estado         text not null check (estado in ('ok','sin_acceso','no_profesional_o_inexistente','token_vencido',
                                                 'limite_meta','error')),
  seguidores     integer check (seguidores is null or seguidores >= 0),
  publicaciones  integer check (publicaciones is null or publicaciones >= 0),
  ultimo_posteo  date,
  posteos_90d    integer check (posteos_90d is null or posteos_90d >= 0),
  detalle        jsonb not null default '{}'::jsonb,
  creado_en      timestamptz not null default now(),
  constraint redes_actividad_un_destino check ((club_id is null) <> (institucion_id is null)),
  constraint redes_actividad_unica unique (cuenta, fecha_consulta)
);
create index if not exists idx_redes_actividad_club on public.redes_actividad(club_id, fecha_consulta desc);
alter table public.redes_actividad enable row level security;      -- sin políticas: solo service_role y el panel
revoke all on public.redes_actividad from anon, authenticated;
grant select, insert, update on public.redes_actividad to service_role;
grant usage, select on sequence public.redes_actividad_id_seq to service_role;

-- Última foto de cada cuenta, para el panel (solo administradores).
create or replace function public.panel_redes_actividad()
returns table (cuenta text, club text, institucion text, estado text, seguidores integer, publicaciones integer,
               ultimo_posteo date, dias_sin_publicar integer, posteos_90d integer, fecha_consulta date)
language plpgsql security definer set search_path = public as $$
begin
  perform public.panel_exige_admin();
  return query
    select distinct on (r.cuenta) r.cuenta, cl.nombre, i.nombre, r.estado, r.seguidores, r.publicaciones,
           r.ultimo_posteo, (current_date - r.ultimo_posteo)::integer, r.posteos_90d, r.fecha_consulta
      from public.redes_actividad r
      left join public.clubes cl on cl.id = r.club_id
      left join public.instituciones i on i.id = r.institucion_id
     order by r.cuenta, r.fecha_consulta desc;
end $$;
revoke execute on function public.panel_redes_actividad() from public, anon;
grant execute on function public.panel_redes_actividad() to authenticated;

create or replace function public.aprobar_propuesta(p_cola_id uuid, p_revisor text) returns jsonb
language plpgsql security invoker set search_path = public as $$
declare c public.cola_revision; acc text; par jsonb; n int := 0; m int := 0; v_id uuid; v_slug text;
begin
  select * into c from public.cola_revision where id = p_cola_id and tipo = 'propuesta_cambio' and estado = 'pendiente' for update;
  if not found then raise exception 'No hay una propuesta pendiente con ese id.'; end if;
  acc := c.propuesta ->> 'accion';
  par := coalesce(c.propuesta -> 'parametros', '{}'::jsonb);
  case acc
    when 'borrador_pliego_rse' then      -- queda como BORRADOR: una persona completa montos y lo publica aparte
      if c.club_id is null then raise exception 'La propuesta de pliego necesita un club.'; end if;
      select slug into v_slug from public.clubes where id = c.club_id;
      insert into public.pliegos_rse(codigo, club_id, rubro, titulo, descripcion, monto_referencial_ars, contraprestacion, publicado)
      values ('RSE-' || upper(left(v_slug, 12)) || '-' || to_char(now(), 'YYYYMMDD') || '-' || left(md5(c.id::text), 4),
              c.club_id, coalesce(par ->> 'rubro', 'a_definir'), coalesce(par ->> 'titulo', c.titulo),
              par ->> 'descripcion', 0, 'A definir entre el club y la empresa', false)
      returning id into v_id;
    when 'marcar_no_vigente' then
      update public.autoridades set vigente = false
       where id = (par ->> 'autoridad_id')::uuid
         and club_id is not distinct from c.club_id and institucion_id is not distinct from c.institucion_id;
      get diagnostics n = row_count;
      if n = 0 then raise exception 'La autoridad no existe o no corresponde a esta entidad.'; end if;
    when 'reclamar_pedido' then           -- aprobar = "envié el reclamo"
      update public.pedidos_informacion set estado = 'apelado'
       where id = (par ->> 'pedido_id')::uuid and estado in ('enviado','prorrogado')
         and club_id is not distinct from c.club_id and institucion_id is not distinct from c.institucion_id;
      get diagnostics n = row_count;
      if n = 0 then raise exception 'El pedido no existe, ya no está pendiente o no corresponde a esta entidad.'; end if;
    when 'pausar_fuente' then
      update public.fuentes_monitoreadas set estado = 'pausada', nota = left('Pausada por propuesta: ' || c.titulo, 300)
       where id = (par ->> 'fuente_id')::uuid
         and club_id is not distinct from c.club_id and institucion_id is not distinct from c.institucion_id;
      get diagnostics n = row_count;
      if n = 0 then raise exception 'La fuente no existe.'; end if;
    when 'purgar_contactos' then          -- minimización de datos: borra contactos de casos cerrados
      if coalesce((par ->> 'dias')::int, 0) < 90 then raise exception 'La retención mínima es de 90 días.'; end if;
      update public.tips set contacto = null
       where contacto is not null and estado in ('verificado','descartado') and creado_en < now() - (par ->> 'dias')::int * interval '1 day';
      get diagnostics n = row_count;
      update public.presentaciones_club set contacto = '(eliminado por retención)'
       where contacto <> '(eliminado por retención)' and estado in ('aprobada','rechazada')
         and creado_en < now() - (par ->> 'dias')::int * interval '1 day';
      get diagnostics m = row_count;
      n := n + m;
      update public.postulaciones_rse set contacto = '(eliminado por retención)'
       where contacto <> '(eliminado por retención)' and estado = 'descartada'
         and creado_en < now() - (par ->> 'dias')::int * interval '1 day';
      get diagnostics m = row_count;
      n := n + m;
    when 'actualizar_redes_club' then     -- redes que publica la ficha oficial; una persona verifica que sean del club
      if c.club_id is null then raise exception 'La propuesta de redes necesita un club.'; end if;
      if par ? 'instagram' and (par ->> 'instagram') !~ '^[A-Za-z0-9._]{1,30}$' then
        raise exception 'Usuario de Instagram inválido.'; end if;
      if par ? 'facebook' and (par ->> 'facebook') !~* '^https://(www\.)?facebook\.com/[^\s]{3,200}$' then
        raise exception 'Enlace de Facebook inválido.'; end if;
      if par ? 'web' and (par ->> 'web') !~* '^https?://[^\s]{4,200}$' then
        raise exception 'Sitio web inválido.'; end if;
      update public.clubes set
        instagram = case when par ? 'instagram' then par ->> 'instagram' else instagram end,
        facebook  = case when par ? 'facebook'  then par ->> 'facebook'  else facebook  end,
        web       = case when par ? 'web'       then par ->> 'web'       else web       end,
        actualizado_en = now()
       where id = c.club_id;
      get diagnostics n = row_count;
    when 'actualizar_division_club' then  -- división que el club menciona en su cuenta oficial; una persona la confirma
      if c.club_id is null then raise exception 'La propuesta de división necesita un club.'; end if;
      if coalesce(par ->> 'division', '') not in ('1ra','2da','3ra','desarrollo') then
        raise exception 'División inválida.'; end if;
      if coalesce(par ->> 'fuente_url', '') !~* '^https://(www\.)?instagram\.com/' then
        raise exception 'Falta el enlace al posteo que lo respalda.'; end if;
      update public.clubes set
        division = par ->> 'division',
        estado_afiliacion = 'activo',
        estado_fuente_url = par ->> 'fuente_url',
        estado_fecha = coalesce((par ->> 'fecha')::date, current_date),
        estado_nota = 'División según la cuenta oficial del club en Instagram, verificada por una persona.',
        actualizado_en = now()
       where id = c.club_id;
      get diagnostics n = row_count;
    when 'solo_informativa' then          -- alertas de seguridad, cruces, revisión de código: aprobar = "lo tomo"
      null;
    else
      raise exception 'Acción fuera de la lista permitida: %', coalesce(acc, '(vacía)');
  end case;
  update public.cola_revision set estado='aprobada', revisada_por=p_revisor, revisada_en=now(), motivo_codigo='ok' where id=p_cola_id;
  return jsonb_build_object('accion', acc, 'filas', n, 'creado_id', v_id);
end $$;
revoke execute on function public.aprobar_propuesta(uuid, text) from public, anon, authenticated, service_role;

notify pgrst, 'reload schema';
