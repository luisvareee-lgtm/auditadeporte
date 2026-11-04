-- ============================================================================
-- 10_REDES_CLUBES.sql  (ejecutar DESPUÉS de 09; se puede correr más de una vez)
-- Suma al panel la acción "actualizar_redes_club": cuando el relevador de FABA encuentra
-- Instagram / Facebook / sitio web de un club, vos lo verificás y lo aprobás desde la Bandeja.
-- Además permite el tipo de agente nuevo en las métricas (no cambia nada más).
-- ============================================================================
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
