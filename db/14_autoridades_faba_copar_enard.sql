-- ============================================================================
-- 14_AUTORIDADES_FABA_COPAR_ENARD.sql   (revisalo antes de correrlo; se puede correr más de una vez)
-- Actualiza las nóminas de las tres instituciones con la fuente y la fecha de cada dato.
-- Lo que deja de estar vigente NO se borra: queda como histórico (vigente = false).
--
-- FABA: la página oficial basquetadaptado.com.ar/autoridades/ muestra el mandato 2021-2023 (Pochettino) y no
--       se edita desde el 27/05/2022. La nómina posterior surge de prensa: Paradeportes, 24/02/2025
--       (Víctor Bava presidente). Fuente periodística: confirmala si podés (FABA, IGJ / DPPJ).
-- COPAR: fuente oficial actual, coparg.org.ar/nosotros/ ("Comité Ejecutivo 2026", editada el 29/09/2026).
--        Órgano de fiscalización: DeporTV (Secretaría de Deportes de la Nación), 23/11/2025.
-- ENARD: su web no permite la consulta automática (robots.txt) y se respeta. Directorio 2025-2029 según
--        prensa (Doble Amarilla, 30/04/2025). Confirmalo a mano en enard.org.ar/organizacion-y-estructura/.
-- ============================================================================
do $$
declare
  hist integer; act integer; nuevas integer;
begin
  create temporary table if not exists nomina14 (inst text, cargo text, nombre text, fuente_url text, fecha date);
  truncate nomina14;
  insert into nomina14 values
  -- FABA (prensa, 24/02/2025)
  ('faba', 'Presidente',          'Víctor Bava',               'https://paradeportes.com/basquet-adaptado-victor-bava-nuevo-presidente-de-faba/', '2025-02-24'),
  ('faba', 'Vicepresidenta',      'Silvina Pérez',             'https://paradeportes.com/basquet-adaptado-victor-bava-nuevo-presidente-de-faba/', '2025-02-24'),
  ('faba', 'Secretario',          'Jorge Pizarro',             'https://paradeportes.com/basquet-adaptado-victor-bava-nuevo-presidente-de-faba/', '2025-02-24'),
  ('faba', 'Tesorero',            'Ricardo Perdiguero',        'https://paradeportes.com/basquet-adaptado-victor-bava-nuevo-presidente-de-faba/', '2025-02-24'),
  ('faba', 'Revisor de cuentas',  'Eduardo Gómez',             'https://paradeportes.com/basquet-adaptado-victor-bava-nuevo-presidente-de-faba/', '2025-02-24'),
  -- COPAR (web oficial, Comité Ejecutivo 2026)
  ('copar', 'Presidente',         'Gustavo Borro',             'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vicepresidenta',     'Elba Acuña',                'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Secretario',         'Ricardo Perdiguero',        'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Prosecretaria',      'María Cristina Spara',      'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Tesorero',           'Miguel Ángel Arce',         'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Protesorero',        'Sergio Marino',             'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal titular 1°',   'Nicolás Stupenengo',        'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal titular 2°',   'Sergio Méndez',             'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal titular 3°',   'Carlos González',           'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal titular 4°',   'Jorge Pizarro',             'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal titular 5°',   'Javier Alberto Páez Neira', 'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal suplente 1°',  'Gustavo Cheppi',            'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal suplente 2°',  'Sergio Adrián Barreyra',    'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Vocal suplente 3°',  'Pablo Robledo',             'https://www.coparg.org.ar/nosotros/', '2026-09-29'),
  ('copar', 'Fiscalización, miembro titular 1°', 'David Mariño',    'https://deportv.gob.ar/polideportivo/gustavo-borro-asume-presidencia-copar-renueva-conduccion-deporte-paralimpico-argentino-nid:9155', '2025-11-23'),
  ('copar', 'Fiscalización, miembro titular 2°', 'José Montenegro', 'https://deportv.gob.ar/polideportivo/gustavo-borro-asume-presidencia-copar-renueva-conduccion-deporte-paralimpico-argentino-nid:9155', '2025-11-23'),
  ('copar', 'Fiscalización, miembro suplente',   'Marta Moraglio',  'https://deportv.gob.ar/polideportivo/gustavo-borro-asume-presidencia-copar-renueva-conduccion-deporte-paralimpico-argentino-nid:9155', '2025-11-23'),
  -- ENARD (prensa, directorio 2025-2029)
  ('enard', 'Presidente',         'Mario Moccia',              'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Vicepresidente',     'Daniel Alejandro Ridao',    'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Secretario',         'Víctor Sergio Groupierre',  'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Tesorero',           'Ignacio do Rego',           'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Director',           'Alicia Masoni de Morea',    'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Directora',          'Valentina Kogan',           'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Director',           'Pedro Ibarra',              'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30'),
  ('enard', 'Director',           'Francisco Irarrázaval',     'https://www.dobleamarilla.com.ar/mas-alla-del-futbol/mario-moccia-asumio-como-presidente-del-enard_a681366b638c74e248dee44b4', '2025-04-30');

  -- 1) lo que no figura en la nómina actual pasa a histórico (no se borra)
  update public.autoridades a set vigente = false, actualizado_en = now()
    from public.instituciones i
   where a.institucion_id = i.id and i.slug in (select distinct inst from nomina14) and a.vigente
     and not exists (select 1 from nomina14 n where n.inst = i.slug
                       and lower(n.nombre) = lower(a.nombre) and lower(n.cargo) = lower(a.cargo));
  get diagnostics hist = row_count;

  -- 2) lo que ya estaba con el mismo nombre y cargo: se actualiza la fuente
  update public.autoridades a set vigente = true, publicable = true, fuente_url = n.fuente_url,
         fecha_fuente = n.fecha, actualizado_en = now()
    from nomina14 n join public.instituciones i on i.slug = n.inst
   where a.institucion_id = i.id and lower(a.nombre) = lower(n.nombre) and lower(a.cargo) = lower(n.cargo);
  get diagnostics act = row_count;

  -- 3) lo nuevo se agrega
  insert into public.autoridades (institucion_id, nombre, cargo, fuente_url, fecha_fuente, vigente, publicable)
  select i.id, n.nombre, n.cargo, n.fuente_url, n.fecha, true, true
    from nomina14 n join public.instituciones i on i.slug = n.inst
   where not exists (select 1 from public.autoridades a where a.institucion_id = i.id
                       and lower(a.nombre) = lower(n.nombre) and lower(a.cargo) = lower(n.cargo));
  get diagnostics nuevas = row_count;

  drop table nomina14;
  raise notice 'Pasaron a histórico: %, actualizadas: %, agregadas: %', hist, act, nuevas;
end $$;

-- CONTROL: cómo queda cada nómina vigente
select i.slug, a.cargo, a.nombre, a.fecha_fuente, a.fuente_url
  from public.autoridades a join public.instituciones i on i.id = a.institucion_id
 where i.slug in ('faba','copar','enard') and a.vigente
 order by i.slug, a.cargo;
