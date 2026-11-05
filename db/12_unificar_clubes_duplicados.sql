-- ============================================================================
-- 12_UNIFICAR_CLUBES_DUPLICADOS.sql
-- Los clubes quedaron cargados dos veces (seed del 31/10 y seed del 03/11) con slugs distintos.
-- Para cada club con el MISMO nombre y la MISMA ciudad:
--   * se conserva la ficha más nueva (la que usan los agentes: almirante-brown, cilsa-santa-fe, ...);
--   * se le pasa todo lo que colgaba de la vieja (autoridades, documentos, novedades, cola, fuentes...);
--   * se completan los datos vacíos de la nueva con los de la vieja (instagram, web, logo, ...);
--   * se borra la ficha vieja.
-- Todo corre en una sola transacción: si algo falla, no cambia nada.
--
-- PASO 1 (solo mirar): ejecutá únicamente el bloque "VISTA PREVIA" y revisá la lista.
-- PASO 2: ejecutá el archivo completo.
-- ============================================================================

-- ---------- VISTA PREVIA: qué ficha queda y cuál se elimina ----------
with g as (
  select id, slug, nombre, ciudad, creado_en,
         row_number()  over w as orden,
         first_value(slug) over w as queda
    from public.clubes
  window w as (partition by lower(btrim(nombre)), lower(btrim(ciudad)) order by creado_en desc, slug)
)
select queda as "queda", slug as "se elimina (sus datos pasan a la que queda)", nombre, ciudad
  from g where orden > 1 order by nombre;

-- ---------- UNIFICACIÓN ----------
begin;

do $$
declare
  par record;
  fk  record;
  fila record;
  movidas integer;
  total integer := 0;
begin
  for par in
    with g as (
      select id, slug, creado_en,
             row_number()  over w as orden,
             first_value(id) over w as queda_id,
             first_value(slug) over w as queda_slug
        from public.clubes
      window w as (partition by lower(btrim(nombre)), lower(btrim(ciudad)) order by creado_en desc, slug)
    )
    select id as vieja_id, slug as vieja_slug, queda_id, queda_slug from g where orden > 1
  loop
    -- 1) todo lo que apunta a la ficha vieja pasa a la que queda (todas las tablas con clave hacia clubes)
    for fk in
      select c.conrelid::regclass as tabla, a.attname as columna
        from pg_constraint c
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
       where c.contype = 'f' and c.confrelid = 'public.clubes'::regclass and array_length(c.conkey, 1) = 1
    loop
      begin
        execute format('update %s set %I = $1 where %I = $2', fk.tabla, fk.columna, fk.columna)
          using par.queda_id, par.vieja_id;
      exception when unique_violation then
        -- La ficha que queda ya tiene ese dato: se mueve fila por fila lo que no choca;
        -- lo repetido se va con la ficha vieja.
        movidas := 0;
        for fila in execute format('select ctid from %s where %I = $1', fk.tabla, fk.columna) using par.vieja_id loop
          begin
            execute format('update %s set %I = $1 where ctid = $2', fk.tabla, fk.columna) using par.queda_id, fila.ctid;
            movidas := movidas + 1;
          exception when unique_violation then
            execute format('delete from %s where ctid = $1', fk.tabla) using fila.ctid;
          end;
        end loop;
        raise notice '%: % filas movidas en % (las repetidas se descartaron)', par.vieja_slug, movidas, fk.tabla;
      end;
    end loop;

    -- 1b) mensajes y presentaciones que nombran al club por su slug (texto, no clave)
    --     (solo en las tablas que de verdad tienen esa columna)
    for fk in
      select format('public.%I', table_name) as tabla, column_name::name as columna
        from information_schema.columns
       where table_schema = 'public' and column_name = 'club_slug'
         and table_name in (select table_name from information_schema.tables
                             where table_schema = 'public' and table_type = 'BASE TABLE')
    loop
      execute format('update %s set club_slug = $1 where club_slug = $2', fk.tabla) using par.queda_slug, par.vieja_slug;
    end loop;

    -- 2) completar datos vacíos de la ficha que queda con los de la vieja
    update public.clubes k set
      instagram         = coalesce(k.instagram, v.instagram),
      facebook          = coalesce(k.facebook, v.facebook),
      web               = coalesce(k.web, v.web),
      logo_url          = coalesce(k.logo_url, v.logo_url),
      division          = coalesce(k.division, v.division),
      estado_nota       = coalesce(k.estado_nota, v.estado_nota),
      estado_fuente_url = coalesce(k.estado_fuente_url, v.estado_fuente_url),
      estado_fecha      = coalesce(k.estado_fecha, v.estado_fecha),
      actualizado_en    = now()
      from public.clubes v
     where k.id = par.queda_id and v.id = par.vieja_id;

    -- 3) borrar la ficha vieja
    delete from public.clubes where id = par.vieja_id;
    total := total + 1;
    raise notice 'Unificado: % -> %', par.vieja_slug, par.queda_slug;
  end loop;
  raise notice 'Fichas duplicadas eliminadas: %', total;
end $$;

-- ---------- SICA / Poeta Lugones: no compite más -> se retira del mapa (se conserva el historial) ----------
update public.clubes
   set estado_afiliacion = 'baja',
       publicado = false,
       estado_fecha = current_date,
       estado_nota = 'Retirado del mapa: el club no participa más de las competencias FABA (dato informado al equipo de AuditaDeporte).',
       actualizado_en = now()
 where slug = 'sica-poeta-lugones';

commit;

-- ---------- CONTROL: tiene que quedar una sola ficha por club ----------
select lower(btrim(nombre)) as club, lower(btrim(ciudad)) as ciudad, count(*) as fichas
  from public.clubes group by 1, 2 having count(*) > 1;
select slug, nombre, publicado, estado_afiliacion from public.clubes order by nombre;
