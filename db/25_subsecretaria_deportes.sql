-- 25) Subsecretaría de Deportes de la Nación como institución responsable (pasajes y apoyos a selecciones, becas).
-- Se puede correr más de una vez. Las autoridades se cargan solo con fuente oficial y fecha.
insert into public.instituciones (slug, sigla, nombre, ambito, sitio_web)
values ('subsecretaria-deportes', 'SUBSEC. DEPORTES', 'Subsecretaría de Deportes de la Nación', 'otro', null)
on conflict (slug) do update set nombre = excluded.nombre, sigla = excluded.sigla;

-- último titular informado: queda como histórico (no vigente), con su fuente
insert into public.autoridades (institucion_id, nombre, cargo, fuente_url, fecha_fuente, vigente, publicable)
select i.id, 'Diógenes de Urquiza', 'Subsecretario de Deportes (renunció el 31/07/2026)',
       'https://www.lanacion.com.ar/politica/el-subsecretario-de-deportes-renuncio-por-sus-diferencias-con-daniel-scioli-nid31072026/',
       date '2026-07-31', false, true
  from public.instituciones i
 where i.slug = 'subsecretaria-deportes'
   and not exists (select 1 from public.autoridades a where a.institucion_id = i.id and a.nombre = 'Diógenes de Urquiza');

select slug, sigla, nombre from public.instituciones where slug = 'subsecretaria-deportes';
