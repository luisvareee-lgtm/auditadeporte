-- ============================================================================
-- 13_UNIFICAR_CLUBES_NOMBRE_DISTINTO.sql  (ejecutar DESPUÉS de 12)
-- Los mismos clubes cargados dos veces con el nombre escrito distinto en cada seed.
-- Misma lógica que 12: queda la ficha más nueva y recibe todo lo de la vieja. Si algo falla, no cambia nada.
-- ============================================================================

-- VISTA PREVIA
with pares(a, b) as (values
  ('adu', 'adu-san-fernando'), ('apri', 'apri-litoral'), ('crol', 'crol-rosario'),
  ('echeverria', 'escuela-municipal-echeverria'), ('prodea', 'prodea-parana'), ('sol-lago', 'sol-y-lago-rio-tercero'))
select ca.slug, ca.nombre, ca.creado_en::date, cb.slug, cb.nombre, cb.creado_en::date,
       case when ca.creado_en >= cb.creado_en then ca.slug else cb.slug end as "queda"
  from pares p join public.clubes ca on ca.slug = p.a join public.clubes cb on cb.slug = p.b;

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
    with pares(a, b) as (values
      ('adu', 'adu-san-fernando'), ('apri', 'apri-litoral'), ('crol', 'crol-rosario'),
      ('echeverria', 'escuela-municipal-echeverria'), ('prodea', 'prodea-parana'), ('sol-lago', 'sol-y-lago-rio-tercero')),
    x as (   -- de cada par queda la ficha más nueva (la del seed del 03/11, que usan los agentes)
      select ca.id ida, ca.slug sa, ca.creado_en fa, cb.id idb, cb.slug sb, cb.creado_en fb
        from pares p join public.clubes ca on ca.slug = p.a join public.clubes cb on cb.slug = p.b)
    select case when fa >= fb then idb else ida end as vieja_id, case when fa >= fb then sb else sa end as vieja_slug,
           case when fa >= fb then ida else idb end as queda_id, case when fa >= fb then sa else sb end as queda_slug
      from x
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

commit;

-- CONTROL
select slug, nombre, publicado, estado_afiliacion from public.clubes order by nombre;
