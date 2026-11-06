/* AuditaDeporte · Panel de administración
 * Regla: el navegador NUNCA toca tablas privadas. Todo pasa por funciones panel_* de la base,
 * que vuelven a comprobar que quien llama es administradora (db/09). Esta página solo muestra y pide decisiones.
 * Todo texto que viene de la base se inserta como texto (nunca como HTML): puede haberlo escrito cualquiera. */
'use strict';

const CONFIG = {
  SUPABASE_URL: "https://tjlejedfjypntsylqpeq.supabase.co", // https://tjlejedfjypntsylqpeq.supabase.co
  SUPABASE_PUBLISHABLE_KEY: "sb_publishable_7Yk8oICpIHHKGyZxpocyNA_G0d7v3Di" //  (o la clave anon legacy). NUNCA la secret/service_role.
};

// ---------------------------------------------------------------- utilidades seguras
const $ = (s, r = document) => r.querySelector(s);
function el(tag, attrs = {}, ...hijos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (k === 'text') n.textContent = v;
    else n.setAttribute(k, v === true ? '' : String(v));
  }
  for (const h of hijos.flat()) if (h !== null && h !== undefined && h !== false) n.append(h instanceof Node ? h : String(h));
  return n;
}
function urlSegura(u) {
  try { const x = new URL(u); return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : null; } catch { return null; }
}
function enlace(u, texto) {
  const s = urlSegura(u);
  return s ? el('a', { href: s, target: '_blank', rel: 'noopener noreferrer nofollow' }, texto || s) : el('span', { class: 'meta' }, texto || u || '—');
}
const fecha = v => v ? new Date(v).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
const campo = (k, v) => el('p', { class: 'campo' }, el('b', {}, k), v === null || v === undefined || v === '' ? '—' : v);
function slugificar(t) {
  return (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
}
function aviso(msg, error = false) {
  const a = $('#aviso'); a.textContent = msg; a.className = 'toast' + (error ? ' error' : ''); a.hidden = false;
  clearTimeout(aviso.t); aviso.t = setTimeout(() => { a.hidden = true; }, error ? 9000 : 4500);
}
function confirmar(titulo, texto, etiqueta = 'Confirmar', peligro = false) {
  return new Promise(res => {
    const d = $('#dlg-confirmar');
    $('#dc-titulo').textContent = titulo; $('#dc-texto').textContent = texto;
    const si = $('#dc-si'); si.textContent = etiqueta; si.className = 'btn ' + (peligro ? 'peligro' : 'primario');
    d.addEventListener('close', () => res(d.returnValue === 'si'), { once: true });
    d.showModal();
  });
}
function tabla(cols, filas, vacio = 'Nada por acá.') {
  if (!filas || !filas.length) return el('p', { class: 'vacio' }, vacio);
  return el('div', { class: 'tabla-env' }, el('table', {},
    el('thead', {}, el('tr', {}, cols.map(c => el('th', { scope: 'col' }, c[0])))),
    el('tbody', {}, filas.map(f => el('tr', {}, cols.map(c => el('td', {}, c[1](f))))))));
}

// Lectura fácil: mismas reglas que el votante "lectura" de la mesa (bot/mesa.py).
const JERGA = ['devengado', 'erogacion', 'imputacion presupuestaria', 'partida presupuestaria', 'considerando',
  'visto el expediente', 'a saber', 'en virtud de', 'conforme lo normado'];
function pistasLectura(t) {
  const n = (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const p = [];
  const largas = (t || '').split(/[.!?;]\s+/).filter(f => f.trim().split(/\s+/).length > 35).length;
  if (largas) p.push(`${largas} frase(s) de más de 35 palabras: partilas.`);
  const j = JERGA.filter(x => n.includes(x)); if (j.length) p.push(`Jerga para reemplazar: ${j.join(', ')}.`);
  if (/\b(corrup|robo|estafa|fraude|ilegal|desvio de fondos)/.test(n)) p.push('Evitá calificativos o imputaciones: describí lo que dice el documento.');
  if (/\b\d{1,2}\.?\d{3}\.?\d{3}\b/.test(t || '')) p.push('Hay un número con forma de DNI: no lo publiques.');
  return p;
}
function areaConPistas(id, valor, max) {
  const ta = el('textarea', { id, maxlength: max || null }, valor || '');
  const ul = el('ul', { class: 'pistas', 'aria-live': 'polite' });
  const cont = el('p', { class: 'meta' });
  const upd = () => { ul.replaceChildren(...pistasLectura(ta.value).map(x => el('li', {}, x))); cont.textContent = `${ta.value.length}${max ? ' / ' + max : ''} caracteres`; };
  ta.addEventListener('input', upd); upd();
  return [ta, cont, ul];
}

// ---------------------------------------------------------------- conexión
let sb = null, yo = null, items = [], actual = null;

async function rpc(fn, args) {
  const { data, error } = await sb.rpc(fn, args || {});
  if (error) throw new Error(error.message || 'Error');
  return data;
}

async function iniciar() {
  if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_PUBLISHABLE_KEY || !window.supabase) { $('#aviso-config').hidden = false; return; }
  sb = window.supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_PUBLISHABLE_KEY,
    { auth: { persistSession: true, storage: window.sessionStorage, autoRefreshToken: true, detectSessionInUrl: false } });
  const { data } = await sb.auth.getSession();
  if (data && data.session) await despuesDeLogin(); else mostrarLogin();
}

function mostrarLogin(msg) {
  $('#v-login').hidden = false; $('#v-panel').hidden = true; $('#sesion').hidden = true;
  $('#f-login').hidden = false; $('#f-mfa').hidden = true;
  $('#login-estado').textContent = msg || '';
}

$('#f-login').addEventListener('submit', async ev => {
  ev.preventDefault();
  $('#login-estado').textContent = 'Ingresando…';
  const { error } = await sb.auth.signInWithPassword({ email: $('#l-email').value.trim(), password: $('#l-pass').value });
  $('#l-pass').value = '';
  if (error) { $('#login-estado').textContent = 'No se pudo ingresar: revisá el correo y la contraseña.'; return; }
  await despuesDeLogin();
});

$('#f-mfa').addEventListener('submit', async ev => {
  ev.preventDefault();
  const { data: f } = await sb.auth.mfa.listFactors();
  const factor = f && f.totp && f.totp.find(x => x.status === 'verified');
  if (!factor) { $('#login-estado').textContent = 'No hay un segundo factor verificado.'; return; }
  const { error } = await sb.auth.mfa.challengeAndVerify({ factorId: factor.id, code: $('#l-codigo').value.trim() });
  $('#l-codigo').value = '';
  if (error) { $('#login-estado').textContent = 'Código incorrecto o vencido.'; return; }
  await despuesDeLogin();
});

async function despuesDeLogin() {
  try {
    const aal = sb.auth.mfa && await sb.auth.mfa.getAuthenticatorAssuranceLevel();
    if (aal && aal.data && aal.data.nextLevel === 'aal2' && aal.data.currentLevel !== 'aal2') {
      $('#v-login').hidden = false; $('#f-login').hidden = true; $('#f-mfa').hidden = false;
      $('#login-estado').textContent = 'Falta el segundo factor.'; $('#l-codigo').focus(); return;
    }
    yo = await rpc('panel_yo');
  } catch (e) { mostrarLogin('Error al verificar la cuenta: ' + e.message); return; }
  if (!yo || !yo.admin) {
    await sb.auth.signOut();
    mostrarLogin(yo && yo.requiere_mfa ? 'Esta cuenta exige segundo factor.' : 'Esta cuenta no es administradora. Pedí el alta con el SQL de db/09.');
    return;
  }
  $('#v-login').hidden = true; $('#v-panel').hidden = false; $('#sesion').hidden = false;
  $('#yo-email').textContent = yo.email || '';
  await cargarBandeja(); cargarContadores();
  if (!(await pintarCuenta())) aviso('Recomendado: activá el segundo factor en la pestaña Cuenta.');
}

$('#btn-salir').addEventListener('click', async () => { await sb.auth.signOut(); yo = null; mostrarLogin('Sesión cerrada.'); });

// ---------------------------------------------------------------- pestañas
const CARGAS = { bandeja: cargarBandeja, borradores: cargarBorradores, publicados: cargarPublicados, fuentes: cargarFuentes,
  estado: cargarEstado, historial: cargarHistorial, cuenta: pintarCuenta, cargar: cargarCargados, alertas: cargarAlertas };
document.querySelectorAll('[role="tab"]').forEach(b => b.addEventListener('click', () => abrirTab(b.dataset.tab)));
function abrirTab(t) {
  document.querySelectorAll('[role="tab"]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === t)));
  document.querySelectorAll('.pestana').forEach(p => { p.hidden = p.id !== 'p-' + t; });
  CARGAS[t]().catch(e => aviso(e.message, true));
}

async function cargarContadores() {
  try {
    const r = await rpc('panel_resumen');
    const p = r.pendientes;
    $('#c-bandeja').textContent = (p.cola + p.bloqueadas + p.tips + p.postulaciones + p.presentaciones) || '';
    $('#c-alertas').textContent = p.alertas || '';
    const b = await rpc('panel_borradores'); $('#c-borradores').textContent = b.length || '';
    try { const v = await rpc('panel_alertas_vigia', { p_todas: false }); $('#c-vigia').textContent = v.alertas.filter(a => a.estado === 'nueva').length || ''; } catch (e) { /* sin db/18 */ }
  } catch (e) { /* los contadores no son críticos */ }
}

// ---------------------------------------------------------------- bandeja
const NOMBRE_TIPO = {
  novedad_red: 'Novedad de red', documento_nuevo: 'Documento nuevo', documento_cambio: 'Documento modificado',
  autoridad_posible: 'Autoridad hallada', revision_sugerida: 'Revisión documental', propuesta_cambio: 'Propuesta de un especialista',
  documento: 'Mensaje: documento', dato: 'Mensaje: dato', correccion: 'Mensaje: corrección', replica: 'Derecho a réplica', solicitud_rse: 'Pedido de patrocinio',
  presentacion: 'Presentación de club', postulacion: 'Postulación de empresa'
};
const ACCIONES = {
  borrador_pliego_rse: ['Crear borrador de pliego RSE', 'Se crea un pliego NO publicado. Después completás montos y cotizaciones y lo publicás desde Borradores.'],
  marcar_no_vigente: ['Marcar autoridad como no vigente', 'La persona deja de mostrarse como autoridad vigente en el sitio.'],
  reclamar_pedido: ['Marcar pedido como reclamado', 'Aprobá después de enviar el reclamo desde tu correo. El pedido pasa a "apelado".'],
  pausar_fuente: ['Pausar fuente', 'Los agentes dejan de revisar esa fuente hasta que la reactives.'],
  purgar_contactos: ['Borrar contactos de casos cerrados', 'Se borran correos y teléfonos de mensajes, presentaciones y postulaciones ya cerrados. No se puede deshacer.'],
  solo_informativa: ['Marcar como tomado', 'No cambia nada en la base: queda registrado que lo viste.'],
  actualizar_redes_club: ['Guardar redes del club', 'Se guardan en la ficha del club. Abrí cada cuenta antes y confirmá que es del club y que sigue activa.']
};
const CHIP_SEMAFORO = { limpia: ['ok', 'Sin observaciones'], observada: ['obs', 'Con observaciones'], bloqueada: ['mal', 'Bloqueado por la mesa'] };

async function cargarBandeja() {
  items = await rpc('panel_bandeja', { p_historial: false });
  pintarLista();
}
['#f-origen', '#f-semaforo'].forEach(s => $(s).addEventListener('change', pintarLista));
$('#btn-recargar').addEventListener('click', () => { cargarBandeja().catch(e => aviso(e.message, true)); cargarContadores(); });

function pintarLista() {
  const o = $('#f-origen').value, s = $('#f-semaforo').value;
  const vis = items.filter(i => (!o || i.origen === o) && (!s || i.semaforo === s));
  const ul = $('#lista');
  if (!vis.length) { ul.replaceChildren(el('li', { class: 'vacio' }, 'No hay pendientes con este filtro.')); return; }
  ul.replaceChildren(...vis.map(i => {
    const [cls, txt] = CHIP_SEMAFORO[i.semaforo] || ['', ''];
    return el('li', {}, el('button', {
      class: i.semaforo, 'aria-current': actual && actual.id === i.id && actual.origen === i.origen ? 'true' : null,
      onclick: () => abrirDetalle(i)
    },
    el('strong', {}, i.titulo || '(sin título)'),
    el('span', { class: 'meta' }, el('span', { class: 'chip' }, NOMBRE_TIPO[i.tipo] || i.tipo), i.origen === 'cola' ? el('span', { class: 'chip ' + cls }, txt) : null,
      (i.destino || 'General') + ' · ' + fecha(i.creado_en))));
  }));
}

async function abrirDetalle(i) {
  actual = i; pintarLista();
  const box = $('#detalle'); box.replaceChildren(el('p', { class: 'vacio' }, 'Cargando…'));
  try {
    const d = await rpc('panel_detalle', { p_origen: i.origen, p_id: i.id });
    const vista = { cola: vistaCola, tip: vistaTip, postulacion: vistaPostulacion, presentacion: vistaPresentacion }[i.origen];
    box.replaceChildren(...vista(d));
    box.querySelector('h2') && box.querySelector('h2').focus();
  } catch (e) { box.replaceChildren(el('p', { class: 'aviso' }, e.message)); }
}

const NOMBRE_TEMA = { deporte_adaptado: 'Deporte adaptado', discapacidad_deporte: 'Discapacidad y deporte', instituto_deporte: 'Instituto Municipal del Deporte',
  juegos_bonaerenses: 'Juegos Bonaerenses', viajes_deportivos: 'Viajes deportivos', federaciones: 'FABA / COPAR / ENARD' };

// Copia las capturas elegidas del depósito privado al público y las asocia al documento publicado.
async function publicarCapturas(colaId, caps) {
  const pub = [];
  for (const c of caps) {
    try {
      const { data, error } = await sb.storage.from('capturas').download(c.ruta);
      if (error) throw error;
      const up = await sb.storage.from('capturas-publicas').upload(c.ruta, data, { contentType: 'image/jpeg', upsert: false });
      if (up.error && !/exists|duplicate/i.test(up.error.message || '')) throw up.error;
      pub.push({ url: sb.storage.from('capturas-publicas').getPublicUrl(c.ruta).data.publicUrl, pagina: c.pagina, temas: c.temas || [], ocr: !!c.ocr });
    } catch (e) { aviso('No se pudo publicar la captura de la pág. ' + c.pagina + ': ' + (e.message || e), true); }
  }
  if (pub.length) {
    try { await rpc('panel_capturas_documento', { p_cola_id: colaId, p_capturas: pub }); aviso(`Documento publicado con ${pub.length} captura(s).`); }
    catch (e) { aviso(e.message, true); }
  }
}

// ---------------------------------------------------------------- alertas del vigía
const REGLA = { huecos_numeracion: 'Huecos en la numeración', fraccionamiento: 'Posible fraccionamiento de compras',
  credito_excedido: 'Gasto por encima del crédito', modificaciones_presupuestarias: 'Modificaciones presupuestarias' };
const GRAVEDAD = { alta: 'mal', media: 'obs', baja: '' };
async function cargarAlertas() {
  let r;
  try { r = await rpc('panel_alertas_vigia', { p_todas: $('#al-todas').checked }); }
  catch (e) { $('#t-alertas').replaceChildren(el('p', { class: 'aviso' }, 'Falta correr db/18 en Supabase: ' + e.message)); return; }
  const secc = (t, v) => v ? el('div', {}, el('h4', {}, t), el('p', {}, v)) : null;
  $('#t-alertas').replaceChildren(...(r.alertas.length ? r.alertas.map(a => {
    const x = a.explicacion || {};
    const nota = el('input', { maxlength: 1000, placeholder: 'Qué verificaste (obligatorio para confirmar o descartar)' });
    const res = (estado, txt) => el('button', { class: 'btn chico' + (estado === 'descartada' ? ' peligro' : estado === 'confirmada' ? ' primario' : ''),
      onclick: async () => { try { await rpc('panel_alerta_resolver', { p_id: a.id, p_estado: estado, p_nota: nota.value }); aviso('Alerta: ' + estado + '.'); cargarAlertas(); cargarContadores(); } catch (e) { aviso(e.message, true); } } }, txt);
    return el('article', { class: 'tarjeta alerta-vigia' },
      el('p', {}, el('span', { class: 'chip ' + (GRAVEDAD[a.gravedad] || '') }, 'Gravedad ' + a.gravedad), el('span', { class: 'chip' }, REGLA[a.regla] || a.regla),
        el('span', { class: 'chip' }, a.juris_slug || 'general'), el('span', { class: 'chip' }, a.estado), ' ', fecha(a.creado_en)),
      el('h3', {}, a.titulo),
      secc('Qué encontré', x.que), secc('Por qué lo marco', x.por_que), secc('Qué dice la norma', x.norma),
      secc('Qué podría explicarlo sin que haya nada irregular', x.puede_explicarse), secc('Qué hacer', x.que_hacer),
      (a.evidencia || []).length ? el('div', {}, el('h4', {}, 'Evidencia'), el('ul', {}, a.evidencia.map(ev =>
        el('li', {}, enlace(ev.url), ev.pagina ? ` · pág. ${ev.pagina}` : '', ev.fecha ? ` · ${ev.fecha}` : '',
          ev.monto ? ` · $ ${Number(ev.monto).toLocaleString('es-AR')}` : '', ev.extracto ? el('p', { class: 'cita' }, ev.extracto) : null)))) : null,
      a.nota ? campo('Resolución', `${a.nota} (${a.resuelta_por || ''})`) : null,
      ['nueva', 'vista'].includes(a.estado) ? el('div', { class: 'bloque' }, nota, el('div', { class: 'acciones' },
        a.estado === 'nueva' ? res('vista', 'La estoy viendo') : null, res('confirmada', 'Confirmada: hay que pedir/publicar'), res('descartada', 'Descartar'))) : null);
  }) : [el('p', { class: 'vacio' }, 'No hay alertas abiertas.')]));
  $('#t-precision').replaceChildren(tabla([['Regla', x => REGLA[x.regla] || x.regla], ['Confirmadas', x => x.confirmadas], ['Descartadas', x => x.descartadas], ['Abiertas', x => x.abiertas],
    ['Acierto', x => (x.confirmadas + x.descartadas) ? Math.round(100 * x.confirmadas / (x.confirmadas + x.descartadas)) + '%' : '—']], r.precision, 'Todavía no hay alertas resueltas.'));
  $('#t-cobertura').replaceChildren(tabla([['Lugar', x => x.juris], ['Tipo', x => x.tipo], ['Año', x => x.anio], ['Leídas', x => x.vistas], ['Números', x => `${x.desde} a ${x.hasta}`]],
    r.cobertura, 'Todavía no se leyeron normas con encabezado numerado.'));
}
$('#al-todas').addEventListener('change', () => cargarAlertas());

// lista pública de clubes (para mostrar nombres y elegir club)
let _clubes = null;
async function clubesAdmin() {
  if (_clubes) return _clubes;
  const { data } = await sb.from('clubes').select('id,slug,nombre').order('nombre');
  _clubes = data || []; return _clubes;
}

// ---------------------------------------------------------------- carga manual de PDFs
async function sha256Hex(buf) {
  const h = await crypto.subtle.digest('SHA-256', buf);
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function cargarCargados() {
  if ($('#fc-juris').options.length < 2) {
    try {
      const r = await fetch('/datos/transparencia.json', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const grupo = (t, et) => el('optgroup', { label: et }, ...d.jurisdicciones.filter(j => j.tipo === t).map(j => el('option', { value: j.slug }, j.nombre)));
      $('#fc-juris').replaceChildren(el('option', { value: '' }, '— Elegí dónde se publicó —'), grupo('municipio', 'Municipios'),
        grupo('provincia', 'Provincias'), grupo('nacion', 'Nación'), grupo('universidad', 'Universidades'));
    } catch (e) { aviso('No se pudo cargar la lista de municipios: ' + e.message, true); }
  }
  if ($('#fc-club').options.length < 2) {
    try { $('#fc-club').replaceChildren(el('option', { value: '' }, '— Ninguno en particular —'),
      ...(await clubesAdmin()).map(c => el('option', { value: c.slug }, c.nombre))); }
    catch (e) { /* el club es opcional */ }
  }
  let l = [];
  try { l = await rpc('panel_documentos_cargados'); }
  catch (e) { $('#t-cargados').replaceChildren(el('p', { class: 'aviso' }, 'Falta correr db/16 y db/17 en Supabase: ' + e.message)); return; }
  cargarEjecuciones();
  cargarColectas();
  cargarConvocatoriasPanel();
  $('#t-cargados').replaceChildren(tabla([['Documento', x => el('span', {}, el('strong', {}, x.titulo), el('br'), enlace(x.url_original))],
    ['Lugar', x => x.juris_slug + (x.formato && x.formato !== 'pdf' ? ' · .' + x.formato : '')], ['Cargado', x => fecha(x.creado_en) + (x.cargado_por ? ' · ' + x.cargado_por : '')],
    ['Estado', x => el('span', { class: 'chip ' + ({ procesado: 'ok', error: 'mal' }[x.estado] || '') }, x.estado === 'pendiente' ? 'en espera (se analiza en menos de una hora)' : x.estado)],
    ['Resultado', x => x.error ? x.error : x.estado === 'procesado' ? `${x.paginas || '?'} páginas · ${x.hallazgos} hallazgo(s)` : '—']], l, 'Todavía no cargaste documentos.'));
}
const FORMATOS_OK = ['pdf', 'doc', 'docx', 'odt', 'rtf', 'xls', 'xlsx', 'ods', 'csv', 'txt', 'jpg', 'jpeg', 'png', 'tif', 'tiff', 'webp'];
const MIME = { pdf: 'application/pdf', doc: 'application/msword', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  odt: 'application/vnd.oasis.opendocument.text', rtf: 'application/rtf', xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', ods: 'application/vnd.oasis.opendocument.spreadsheet',
  csv: 'text/csv', txt: 'text/plain', jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', tif: 'image/tiff', tiff: 'image/tiff', webp: 'image/webp' };
const extDe = n => { const e = (n.split('.').pop() || '').toLowerCase(); return e === 'jpeg' ? 'jpg' : e === 'tiff' ? 'tif' : e; };
const tituloDe = n => n.replace(/\.[^.]+$/, '').replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();

// al elegir archivos: una fila por archivo con título editable y enlace directo opcional
$('#fc-archivo').addEventListener('change', () => {
  const fs = [...$('#fc-archivo').files];
  $('#fc-lista').replaceChildren(...fs.slice(0, 50).map((f, i) => {
    const e = extDe(f.name), mal = !FORMATOS_OK.includes(e) ? 'formato no admitido' : f.size > 50 * 1024 * 1024 ? 'supera 50 MB' : '';
    return el('div', { class: 'fila-lote' + (mal ? ' mal' : '') },
      el('span', { class: 'meta' }, `${i + 1}. ${f.name} · ${(f.size / 1048576).toFixed(1)} MB${mal ? ' · ' + mal : ''}`),
      el('input', { class: 'fl-titulo', maxlength: 200, value: tituloDe(f.name), 'aria-label': 'Título de ' + f.name, disabled: !!mal }),
      el('input', { class: 'fl-url', type: 'url', placeholder: 'Enlace directo al archivo (opcional)', 'aria-label': 'Enlace directo de ' + f.name, disabled: !!mal }));
  }));
  if (fs.length > 50) aviso('Se toman los primeros 50 archivos.', true);
});

const pesosAR = v => v === null || v === undefined ? '—' : '$ ' + Number(v).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
async function cargarEjecuciones() {
  let l;
  try { l = await rpc('panel_ejecuciones'); }
  catch (e) { $('#t-ejecuciones').replaceChildren(el('p', { class: 'aviso' }, 'Falta correr db/20 en Supabase: ' + e.message)); return; }
  $('#t-ejecuciones').replaceChildren(tabla([
    ['Reporte', x => el('span', {}, el('strong', {}, `${x.tipo} · ${(x.clasificacion || '').replace(/_/g, ' ')}`), el('br'), `${x.desde || '?'} al ${x.hasta || '?'} · ${x.juris_slug}`, el('br'), enlace(x.url))],
    ['Control', x => el('span', {}, (x.cierre || []).length ? el('span', { class: 'chip mal' }, `${x.cierre.length} cuenta(s) no cierran`) : el('span', { class: 'chip ok' }, 'La aritmética cierra'),
      (x.credito || []).length ? el('span', { class: 'chip obs' }, `${x.credito.length} línea(s) sobre el crédito`) : null)],
    ['Deporte y recreación', x => x.deporte ? el('span', {}, `Vigente ${pesosAR(x.deporte.vigente)}`, el('br'), `Devengado ${pesosAR(x.deporte.devengado)} (${x.deporte.porcentaje_devengado ?? '—'} %)`, el('br'), `Pagado ${pesosAR(x.deporte.pagado)}`)
      : x.tipo === 'gastos' ? 'No viene la línea (otra clasificación)' : (x.deporte_recursos || []).length ? `${x.deporte_recursos.length} ingreso(s) de deporte` : '—'],
    ['', x => x.deporte ? el('button', { class: 'btn chico' + (x.publicado ? '' : ' primario'), onclick: async () => {
      if (!x.publicado && !await confirmar('Publicar la línea de Deporte', 'Se va a mostrar en la tarjeta del municipio con enlace al reporte. ¿Comparaste los números con el PDF?', 'Publicar')) return;
      try { await rpc('panel_publicar_ejecucion', { p_id: x.id, p_publicar: !x.publicado }); aviso(x.publicado ? 'Retirado.' : 'Publicado. Aparece en el sitio con la próxima actualización del resumen.'); cargarEjecuciones(); }
      catch (e) { aviso(e.message, true); } } }, x.publicado ? 'Retirar del sitio' : 'Publicar línea de Deporte') : null]], l, 'Todavía no se leyó ningún reporte de ejecución.'));
}

const OPC_COLECTA = {
  'co-fin': { viaje_torneo: 'Viaje a torneo', inscripcion: 'Inscripción', silla_equipamiento: 'Silla o equipamiento', indumentaria: 'Indumentaria', general: 'Gastos generales' },
  'co-tipos': { rifa_sorteo: 'Rifa o sorteo', venta_comida: 'Venta de comida', evento: 'Evento (peña, bingo, partido)', transferencia: 'Transferencia o alias',
    campana_online: 'Campaña online', venta_merch: 'Venta de remeras u otros', pedido_empresas: 'Pedido a empresas', pedido_estado: 'Pedido al Estado' },
  'co-dest': { personas: 'Personas', empresas: 'Empresas', estado: 'Estado' },
  'co-tor': { liga_nacional: 'Liga o torneo nacional', juegos_bonaerenses: 'Juegos Bonaerenses', sudamericano: 'Sudamericano', copa_america: 'Copa América',
    parapanamericanos: 'Parapanamericanos', mundial: 'Mundial', repechaje: 'Repechaje', paralimpicos: 'Paralímpicos' } };
const ETIQ_COLECTA = Object.assign({}, ...Object.values(OPC_COLECTA));
for (const [id, opts] of Object.entries(OPC_COLECTA)) {
  const caja = document.getElementById(id);
  if (caja) caja.replaceChildren(...Object.entries(opts).map(([v, t]) => el('label', { class: 'check' }, el('input', { type: 'checkbox', value: v }), ' ' + t)));
}
const marcados = id => [...document.querySelectorAll('#' + id + ' input:checked')].map(i => i.value);
const etiquetas = l => (l || []).map(x => ETIQ_COLECTA[x] || x.replace(/_/g, ' ')).join(', ') || '—';

async function cargarColectas() {
  let l;
  try { l = await rpc('panel_colectas'); }
  catch (e) { $('#t-colectas').replaceChildren(el('p', { class: 'aviso' }, 'Falta correr db/21 y db/22 en Supabase: ' + e.message)); return; }
  $('#t-colectas').replaceChildren(tabla([
    ['Publicación', x => el('span', {}, el('strong', {}, x.nombre_cuenta), ` · ${x.fecha} · ${x.fuente}`, el('br'), enlace(x.permalink))],
    ['Para qué / cómo', x => el('span', {}, etiquetas(x.finalidades), el('br'), el('span', { class: 'meta' }, etiquetas(x.tipos_pedido)))],
    ['Torneo y monto', x => el('span', {}, etiquetas(x.torneos), el('br'), (x.montos || []).map(m => `${m.moneda} ${Number(m.valor).toLocaleString('es-AR')}`).join(' · ') || '—')],
    ['', x => x.revisada ? el('span', { class: 'chip ok' }, 'Aprobada') : el('span', {},
      el('button', { class: 'btn chico primario', onclick: () => revisarColecta(x, true) }, 'Aprobar'), ' ',
      el('button', { class: 'btn chico', onclick: () => revisarColecta(x, false) }, 'Descartar'))]], l, 'Todavía no hay colectas relevadas.'));
}
async function cargarConvocatoriasPanel() {
  let l;
  try { l = await rpc('panel_convocatorias'); }
  catch (e) { $('#t-convocatorias').replaceChildren(el('p', { class: 'aviso' }, 'Falta correr db/23 en Supabase: ' + e.message)); return; }
  const dias = x => Math.round((new Date(x.fecha_torneo) - new Date(x.fecha_aviso)) / 864e5);
  $('#t-convocatorias').replaceChildren(tabla([
    ['Club', x => x.club_id], ['Aviso → torneo', x => `${x.fecha_aviso} → ${x.fecha_torneo} (${dias(x)} días)${x.cambio_fecha ? ' · cambió' : ''}`],
    ['Canal', x => x.canal], ['Municipio / viajaron', x => `${x.cobertura} · ${x.viajaron}`], ['Cargado', x => fecha(x.creado_en)],
    ['', x => el('button', { class: 'btn chico', onclick: async () => {
      if (!await confirmar('Borrar el aviso', 'Se quita del promedio público. ¿Seguro?', 'Borrar')) return;
      try { await rpc('panel_borrar_convocatoria', { p_id: x.id }); aviso('Borrado.'); cargarConvocatoriasPanel(); } catch (e) { aviso(e.message, true); } } }, 'Borrar')]],
    l, 'Todavía no hay convocatorias cargadas.'));
}
async function revisarColecta(x, ok) {
  if (!ok && !await confirmar('Descartar la colecta', 'Se borra del relevamiento (por ejemplo, si es de salud o de una persona). ¿Seguro?', 'Descartar')) return;
  try { await rpc('panel_colecta_revisar', { p_id: x.id, p_ok: ok }); aviso(ok ? 'Aprobada: entra en el próximo resumen.' : 'Descartada.'); cargarColectas(); }
  catch (e) { aviso(e.message, true); }
}
$('#f-colecta')?.addEventListener('submit', async ev => {
  ev.preventDefault();
  const monto = $('#co-monto').value;
  try {
    await rpc('panel_cargar_colecta', { p_cuenta: $('#co-cuenta').value.replace(/^@/, ''), p_nombre: $('#co-nombre').value, p_tipo_cuenta: $('#co-tipo').value,
      p_fecha: $('#co-fecha').value, p_permalink: $('#co-url').value, p_finalidades: marcados('co-fin'), p_tipos_pedido: marcados('co-tipos'),
      p_destinatarios: marcados('co-dest'), p_torneos: marcados('co-tor'), p_monto: monto ? Number(monto) : null, p_moneda: $('#co-moneda').value,
      p_fecha_limite: $('#co-limite').value || null });
    aviso('Colecta guardada.'); ev.target.reset(); cargarColectas();
  } catch (e) { aviso(e.message, true); }
});

async function subirPdf(ev) {
  ev.preventDefault();
  const fs = [...$('#fc-archivo').files].slice(0, 50), url = $('#fc-url').value.trim(), juris = $('#fc-juris').value, club = $('#fc-club').value;
  if (!juris) { aviso('Elegí el municipio o la provincia donde están publicados.', true); return; }
  if (!fs.length) { aviso('Elegí uno o más archivos.', true); return; }
  if (!urlSegura(url) || !/^https?:\/\/[^/]+\/[^?#]+/i.test(url)) { aviso('Pegá el enlace de la página donde están publicados (no la portada del sitio).', true); return; }
  const filas = [...$('#fc-lista').children];
  const lote = 'lote-' + new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14);
  const btn = $('#fc-enviar'); btn.disabled = true;
  let ok = 0, repetidos = 0; const errores = [];
  for (let i = 0; i < fs.length; i++) {
    const f = fs[i], e = extDe(f.name), fila = filas[i];
    if (!FORMATOS_OK.includes(e) || f.size > 50 * 1024 * 1024) { errores.push(`${f.name}: formato o tamaño no admitido`); continue; }
    const titulo = ((fila && fila.querySelector('.fl-titulo').value) || tituloDe(f.name)).trim();
    const directo = ((fila && fila.querySelector('.fl-url').value) || '').trim();
    $('#fc-estado').textContent = `Subiendo ${i + 1} de ${fs.length}: ${f.name}…`;
    try {
      const buf = await f.arrayBuffer();
      if (e === 'pdf' && new TextDecoder().decode(buf.slice(0, 5)) !== '%PDF-') throw new Error('no es un PDF válido');
      const sha = await sha256Hex(buf), ruta = `${juris}/${sha}.${e}`;
      const up = await sb.storage.from('documentos-cargados').upload(ruta, new Blob([buf], { type: MIME[e] || 'application/octet-stream' }),
        { contentType: MIME[e] || 'application/octet-stream', upsert: false });
      if (up.error) { if (/exists|duplicate/i.test(up.error.message || '')) repetidos++; else throw up.error; }
      await rpc('panel_cargar_documento', { p_juris: juris, p_url: urlSegura(directo) ? directo : url, p_titulo: titulo.length >= 3 ? titulo : 'Documento ' + (i + 1),
        p_ruta: ruta, p_sha: sha, p_club: club || null, p_formato: e, p_lote: lote });
      ok++;
      if (fila) fila.classList.add('ok');
    } catch (err) { errores.push(`${f.name}: ${err.message || err}`); if (fila) fila.classList.add('mal'); }
  }
  btn.disabled = false;
  $('#fc-estado').textContent = `Listo: ${ok} cargado(s)${repetidos ? ` (${repetidos} ya estaban: se vuelven a analizar)` : ''}${errores.length ? ` · ${errores.length} con error` : ''}.`;
  if (errores.length) aviso('No se cargaron: ' + errores.slice(0, 5).join(' · ') + (errores.length > 5 ? '…' : ''), true);
  else { aviso(`${ok} documento(s) cargado(s). El analista los lee en la próxima hora y lo que encuentre aparece en la Bandeja.`); ev.target.reset(); $('#fc-lista').replaceChildren(); }
  cargarCargados();
}

async function hacer(fn, args, ok, recargar = true) {
  try {
    const r = await rpc(fn, args);
    aviso(ok);
    if (recargar) { $('#detalle').replaceChildren(el('p', { class: 'vacio' }, 'Listo. Elegí otro ítem.')); actual = null; await cargarBandeja(); cargarContadores(); }
    return r;
  } catch (e) { aviso(e.message, true); return null; }
}

function bloqueRechazo(id, conReabrir) {
  const sel = el('select', { id: 'r-motivo' }, [['fuente_debil', 'Fuente débil'], ['dato_personal', 'Dato personal'], ['lenguaje', 'Lenguaje'],
    ['duplicado', 'Duplicado'], ['fuera_de_alcance', 'Fuera de alcance'], ['desactualizado', 'Desactualizado'], ['otro', 'Otro']]
    .map(([v, t]) => el('option', { value: v }, t)));
  const nota = el('input', { id: 'r-nota', maxlength: 500, placeholder: 'Opcional: por qué' });
  const partes = [el('h3', {}, 'Rechazar'), el('label', { for: 'r-motivo' }, 'Motivo (entrena a los agentes)'), sel,
    el('label', { for: 'r-nota' }, 'Nota'), nota,
    el('div', { class: 'acciones' }, el('button', { class: 'btn peligro', onclick: async () => {
      if (await confirmar('Rechazar', 'El ítem no se publicará.', 'Rechazar', true))
        hacer('panel_rechazar_cola', { p_id: id, p_motivo: sel.value, p_nota: nota.value }, 'Rechazado.');
    } }, 'Rechazar'))];
  if (conReabrir) {
    const just = el('textarea', { id: 'r-just', placeholder: 'Por qué la mesa se equivocó (mín. 20 caracteres)' });
    partes.push(el('h3', {}, 'Reabrir (si la mesa se equivocó)'), el('label', { for: 'r-just' }, 'Justificación'), just,
      el('div', { class: 'acciones' }, el('button', { class: 'btn', onclick: () =>
        hacer('panel_reabrir_cola', { p_id: id, p_justificacion: just.value }, 'Reabierto: ahora podés revisarlo y aprobarlo.') }, 'Reabrir')));
  }
  return el('div', { class: 'bloque' }, partes);
}

function vistaCola(d) {
  const p = d.propuesta || {}, ind = p.indicadores || {};
  const out = [el('h2', { tabindex: '-1' }, d.titulo),
    el('p', {}, el('span', { class: 'chip' }, NOMBRE_TIPO[d.tipo] || d.tipo), el('span', { class: 'chip' }, 'Agente: ' + d.agente),
      d.estado === 'bloqueada_legal' ? el('span', { class: 'chip mal' }, 'Bloqueado por la mesa') : null),
    campo('Entidad', d.destino || 'General'), campo('Fuente', enlace(d.url_fuente)),
    campo('Hash SHA-256', el('code', {}, d.hash_sha256 || 'sin hash')), campo('Recibido', fecha(d.creado_en))];
  if (d.nota_revision) out.push(campo('Nota', d.nota_revision));
  if (d.veto_juridico) out.push(el('p', { class: 'aviso' }, 'Motivo del bloqueo: ' + d.veto_juridico));

  // votos de la mesa
  out.push(el('div', { class: 'bloque' }, el('h3', {}, 'Votos de la mesa'),
    tabla([['Agente', v => v.agente], ['Voto', v => el('span', { class: 'chip ' + ({ aprobar: 'ok', observar: 'obs', vetar: 'mal' }[v.voto] || '') }, v.voto)],
      ['Motivo', v => v.motivo || '—']], d.votos, 'Sin votos registrados.')));

  if (d.tipo === 'documento_nuevo' || d.tipo === 'documento_cambio') {
    const b = [el('h3', {}, 'Lo que encontró el analista documental')];
    if (p.requiere_ocr_o_revision_humana) b.push(el('p', { class: 'aviso' }, 'Sin texto legible (' + (p.motivo_revision || '') + '): abrí el documento y leelo vos.'));
    if (d.tipo === 'documento_cambio') b.push(el('p', { class: 'aviso' }, 'La página cambió desde la última vez. Hash anterior: ' + (p.hash_anterior || '—')));
    b.push(campo('Expedientes', (ind.expedientes || []).join(' · ') || '—'), campo('CUIT de entidades', (ind.cuits_entidades || []).join(' · ') || '—'));
    if (ind.contiene_posibles_dni) b.push(el('p', { class: 'aviso' }, 'El documento tiene números con forma de DNI: no los repitas en el resumen.'));
    if (p.paginas) b.push(campo('Páginas leídas', `${p.paginas}${p.paginas_ocr ? ` (${p.paginas_ocr} por OCR: el texto puede tener errores, verificalo en el original)` : ''}`));
    if (p.cargado_a_mano) b.push(el('p', { class: 'nota' }, 'PDF cargado a mano desde el sitio oficial. El enlace de la fuente es el original.'));
    if ((p.hallazgos || []).length) b.push(el('h3', {}, 'Dónde aparece cada tema'), el('ul', { class: 'hallazgos' }, p.hallazgos.map(h =>
      el('li', {}, el('strong', {}, (NOMBRE_TEMA[h.tema] || h.tema) + ` · pág. ${h.pagina}`), h.montos && h.montos.length ? ` · montos cerca: ${h.montos.join(', ')}` : '',
        el('p', { class: 'cita' }, h.extracto)))));
    if ((p.capturas || []).length) {
      d._caps = new Set();
      const cont = el('div', { class: 'capturas' });
      b.push(el('h3', {}, 'Capturas (privadas hasta que las publiques)'),
        el('p', { class: 'nota' }, 'Marcá las que quieras publicar junto al documento. Antes, compará cada una con el original: el resaltado lo hizo un programa.'), cont);
      p.capturas.forEach(async c => {
        const { data } = await sb.storage.from('capturas').createSignedUrl(c.ruta, 900);
        const chk = el('input', { type: 'checkbox', onchange: e => e.target.checked ? d._caps.add(c) : d._caps.delete(c) });
        cont.append(el('figure', {}, data ? el('a', { href: data.signedUrl, target: '_blank', rel: 'noopener' }, el('img', { src: data.signedUrl, alt: 'Captura de la página ' + c.pagina, loading: 'lazy' })) : el('p', { class: 'aviso' }, 'No se pudo abrir la captura.'),
          el('figcaption', {}, el('label', { class: 'check' }, chk, `Publicar · pág. ${c.pagina} · ${(c.temas || []).map(t => NOMBRE_TEMA[t] || t).join(', ')}`))));
      });
    }
    if (d.cruces && d.cruces.length) b.push(el('h3', {}, 'Cruces con otras fuentes'), el('ul', {}, d.cruces.map(c =>
      el('li', {}, c.expediente + ': ', ...c.otras_fuentes.map(u => el('span', {}, enlace(u), ' '))))));
    out.push(el('div', { class: 'bloque' }, b));
  }
  if (d.tipo === 'propuesta_cambio') {
    const [nom, expl] = ACCIONES[p.accion] || [p.accion, 'Acción desconocida: la base no la va a ejecutar.'];
    const b = [el('h3', {}, 'Propuesta: ' + nom), el('p', { class: 'nota' }, expl)];
    if (d.objetivo) b.push(campo('Sobre qué actúa', d.objetivo));
    else if (['reclamar_pedido', 'pausar_fuente', 'marcar_no_vigente'].includes(p.accion))
      b.push(el('p', { class: 'aviso' }, 'No se encontró el registro sobre el que actúa (o no corresponde a esta entidad): rechazala.'));
    if (p.detalle) b.push(el('p', { class: 'cita' }, p.detalle));
    if (p.parametros && Object.keys(p.parametros).length) b.push(campo('Parámetros', el('code', {}, JSON.stringify(p.parametros))));
    if (p.borrador_texto) b.push(el('h3', {}, 'Borrador para enviar (revisalo y envialo desde tu correo)'), el('p', { class: 'cita' }, p.borrador_texto),
      el('button', { class: 'btn chico', onclick: () => navigator.clipboard.writeText(p.borrador_texto).then(() => aviso('Copiado.')) }, 'Copiar borrador'));
    out.push(el('div', { class: 'bloque' }, b));
  }

  if (d.estado === 'pendiente') out.push(formAprobar(d));
  if (d.estado === 'pendiente' || d.estado === 'bloqueada_legal') out.push(bloqueRechazo(d.id, d.estado === 'bloqueada_legal'));
  return out;
}

function formAprobar(d) {
  const p = d.propuesta || {};
  const partes = [el('h3', {}, 'Aprobar')], datos = () => ({});
  let leer = datos, etiqueta = 'Aprobar y publicar', aviso_ = 'Esto se va a publicar en el sitio, con enlace a la fuente.';
  if (d.tipo === 'novedad_red') {
    const [ta, cont, ul] = areaConPistas('a-extracto', p.extracto, 280);
    partes.push(campo('Plataforma', p.plataforma), campo('Fecha de la publicación', p.fecha_posteo),
      p.captura_url ? campo('Captura', enlace(p.captura_url)) : null,
      el('label', { for: 'a-extracto' }, 'Extracto que se publica (cita textual; podés tachar datos personales)'), ta, cont, ul);
    leer = () => ({ extracto: ta.value });
  } else if (d.tipo === 'documento_nuevo' || d.tipo === 'documento_cambio') {
    const [ta, cont, ul] = areaConPistas('a-resumen', '', 1200);
    const norma = el('input', { id: 'a-norma', maxlength: 200, value: (p.indicadores && p.indicadores.expedientes || [])[0] || '' });
    partes.push(el('label', { for: 'a-resumen' }, 'Resumen en lenguaje simple (mín. 20 caracteres, sin adjetivos)'), ta, cont, ul,
      el('label', { for: 'a-norma' }, 'Expediente o norma (opcional)'), norma);
    leer = () => ({ resumen: ta.value, norma: norma.value });
  } else if (d.tipo === 'autoridad_posible') {
    const n = el('input', { id: 'a-nombre', value: p.nombre || '' }), c = el('input', { id: 'a-cargo', value: p.cargo || '' }),
      f = el('input', { id: 'a-fecha', type: 'date', value: p.fecha_fuente || '' });
    partes.push(el('p', { class: 'nota' }, p.nombre
        ? 'El agente precargó lo que leyó. Abrí la fuente y corregí nombre, cargo o fecha si no coinciden exactamente.'
        : 'Escribí nombre y cargo tal como figuran en la fuente, y la fecha de la fuente.'),
      p.linea_fuente ? campo('Texto en la fuente', p.linea_fuente) : null,
      el('label', { for: 'a-nombre' }, 'Nombre'), n, el('label', { for: 'a-cargo' }, 'Cargo'), c, el('label', { for: 'a-fecha' }, 'Fecha de la fuente'), f);
    leer = () => ({ nombre: n.value, cargo: c.value, fecha_fuente: f.value });
  } else if (d.tipo === 'revision_sugerida') {
    const cr = el('select', { id: 'a-crit' }, ['balance', 'autoridades', 'subsidios', 'inventario', 'padron_clubes', 'becas', 'convenios'].map(x => el('option', { value: x }, x)));
    const es = el('select', { id: 'a-est' }, el('option', { value: 'publicado' }, 'Publicado (la fuente lo muestra)'), el('option', { value: 'no_encontrado' }, 'No encontrado (lo busqué yo)'));
    const f = el('input', { id: 'a-frev', type: 'date', value: new Date().toISOString().slice(0, 10) }), nt = el('input', { id: 'a-nrev', maxlength: 300 });
    partes.push(el('label', { for: 'a-crit' }, 'Criterio'), cr, el('label', { for: 'a-est' }, 'Resultado'), es,
      el('label', { for: 'a-frev' }, 'Fecha de revisión'), f, el('label', { for: 'a-nrev' }, 'Nota'), nt);
    const portada = !/^https?:\/\/[^/]+\/[^/?#]+/i.test(d.url_fuente || '');
    const nu = el('input', { id: 'a-url', type: 'url', value: portada ? '' : d.url_fuente, placeholder: 'https://… (el PDF o la página exacta del documento)' });
    partes.push(el('label', { for: 'a-url' }, 'Enlace concreto al documento (obligatorio si marcás "Publicado")'), nu,
      portada ? el('p', { class: 'aviso' }, 'El agente dejó un enlace a una portada o menú: no sirve como respaldo. Buscá el documento y pegá su enlace exacto. Si el sitio solo tiene un menú sin el documento, marcá "No encontrado" (si lo buscaste vos) o rechazá el ítem.') : null);
    d._antesDeAprobar = async () => {
      const u = nu.value.trim();
      if (es.value === 'publicado' && u && u !== d.url_fuente) await rpc('panel_cola_cambiar_url', { p_id: d.id, p_url: u, p_motivo: 'reemplazo de portada por documento' });
    };
    leer = () => ({ criterio: cr.value, estado: es.value, fecha_revision: f.value, nota: nt.value });
    aviso_ = 'Que un bot no encuentre algo no prueba que no exista: marcá "no encontrado" solo si lo buscaste vos.';
  } else if (d.tipo === 'propuesta_cambio') {
    etiqueta = (ACCIONES[p.accion] || ['Aprobar'])[0]; aviso_ = (ACCIONES[p.accion] || ['', ''])[1];
  }
  partes.push(el('div', { class: 'acciones' }, el('button', { class: 'btn primario', onclick: async () => {
    if (!await confirmar(etiqueta, aviso_, etiqueta)) return;
    if (d._antesDeAprobar) { try { await d._antesDeAprobar(); } catch (e) { aviso(e.message, true); return; } }
    const r = await hacer('panel_aprobar_cola', { p_id: d.id, p_datos: leer() }, 'Hecho.');
    if (r && d._caps && d._caps.size) publicarCapturas(d.id, [...d._caps]);
  } }, etiqueta)));
  return el('div', { class: 'bloque' }, partes);
}

function contactoOculto(c) {
  if (!c) return '—';
  const s = el('span', { class: 'oculto-dato', tabindex: '0', role: 'button', 'aria-label': 'Mostrar contacto' }, c);
  const ver = () => { s.classList.remove('oculto-dato'); s.removeAttribute('role'); };
  s.addEventListener('click', ver); s.addEventListener('keydown', e => { if (e.key === 'Enter') ver(); });
  return s;
}

function vistaTip(t) {
  const out = [el('h2', { tabindex: '-1' }, NOMBRE_TIPO[t.tipo] || 'Mensaje'),
    campo('Recibido', fecha(t.creado_en)), campo('Club', el('span', { id: 't-club' }, t.club_id ? '…' : '— (ver el texto)')), campo('Enlace aportado', t.url ? enlace(t.url) : '—'),
    campo('Contacto (dato privado)', contactoOculto(t.contacto)), el('p', { class: 'cita' }, t.texto),
    t.notas_internas ? campo('Notas internas', t.notas_internas) : null];
  const notas = el('input', { id: 't-notas', maxlength: 1000, placeholder: 'Qué verificaste o qué falta' });
  out.push(el('div', { class: 'bloque' }, el('h3', {}, 'Resolver'), el('p', { class: 'nota' }, 'Un mensaje privado nunca se publica tal cual. Si aporta un documento, cargalo como fuente o como documento.'),
    el('label', { for: 't-notas' }, 'Notas internas'), notas,
    el('div', { class: 'acciones' },
      el('button', { class: 'btn', onclick: () => hacer('panel_tip_resolver', { p_id: Number(t.id), p_estado: 'en_revision', p_notas: notas.value }, 'Marcado en revisión.') }, 'En revisión'),
      el('button', { class: 'btn', onclick: () => hacer('panel_tip_resolver', { p_id: Number(t.id), p_estado: 'verificado', p_notas: notas.value }, 'Marcado como verificado.') }, 'Verificado'),
      el('button', { class: 'btn peligro', onclick: () => hacer('panel_tip_resolver', { p_id: Number(t.id), p_estado: 'descartado', p_notas: notas.value }, 'Descartado.') }, 'Descartar'))));
  if (t.club_id) clubesAdmin().then(cs => { const c = cs.find(x => x.id === t.club_id); const n = $('#t-club'); if (n) n.textContent = c ? `${c.nombre} (${c.slug})` : t.club_id; t._slug = c && c.slug; const r = $('#rp-slug'); if (r && !r.value && c) r.value = c.slug; });
  if (t.tipo === 'solicitud_rse' && ['nuevo', 'en_revision'].includes(t.estado)) {
    const rubro = (t.texto.match(/^\[Rubro: (\w+)\]/) || [])[1] || 'otro';
    const personal = /\[Para: personal\]/.test(t.texto);
    const tit = el('input', { id: 'sr-titulo', maxlength: 150, placeholder: 'Ej.: Cubiertas y rayos para el plantel' });
    const [ta, cont, ul] = areaConPistas('sr-desc', t.texto.replace(/^(\[[^\]]+\]\s*)+/, ''), 1000);
    out.push(el('div', { class: 'bloque' }, el('h3', {}, 'Crear borrador de pliego'),
      el('p', { class: 'nota' }, (personal ? 'Es un pedido PERSONAL: confirmá con la persona qué autoriza a publicar y no publiques su nombre sin su permiso. ' : '') +
        'Antes, confirmá por un canal oficial que el pedido viene del equipo. Se crea un pliego NO publicado del club elegido; después ponés el monto y lo publicás desde Borradores. Rubro: ' + rubro + '.'),
      el('label', { for: 'sr-titulo' }, 'Título público'), tit,
      el('label', { for: 'sr-desc' }, 'Descripción pública (sin datos personales ni de salud)'), ta, cont, ul,
      el('div', { class: 'acciones' }, el('button', { class: 'btn primario', onclick: async () => {
        if (await confirmar('Crear borrador', 'Se crea un pliego sin publicar y el mensaje queda como verificado.', 'Crear'))
          hacer('panel_tip_a_pliego', { p_id: Number(t.id), p_rubro: rubro, p_titulo: tit.value, p_descripcion: ta.value }, 'Borrador creado. Completalo en Borradores.');
      } }, 'Crear borrador'))));
  }
  if (t.tipo === 'replica') {
    const slug = el('input', { id: 'rp-slug', value: '' });
    const [ta, cont, ul] = areaConPistas('rp-texto', t.texto, 1500);
    const firm = el('input', { id: 'rp-firm', maxlength: 150, placeholder: 'Ej.: Comisión directiva del club' });
    const ref = el('input', { id: 'rp-ref', type: 'url', placeholder: 'https://… (lo que se responde o su respaldo)', value: t.url || '' });
    const ver = el('input', { id: 'rp-ver', type: 'checkbox' });
    out.push(el('div', { class: 'bloque' }, el('h3', {}, 'Publicar la réplica junto a la información'),
      el('p', { class: 'nota' }, 'Antes, contactá a quien escribió por un canal oficial de la entidad para confirmar que la representa.'),
      el('label', { for: 'rp-slug' }, 'Slug del club o institución'), slug,
      el('label', { for: 'rp-texto' }, 'Texto público (sin datos personales)'), ta, cont, ul,
      el('label', { for: 'rp-firm' }, 'Firmante (la entidad, no una persona)'), firm, el('label', { for: 'rp-ref' }, 'Referencia'), ref,
      el('label', { class: 'check' }, ver, 'Verifiqué que quien escribe representa a la entidad'),
      el('div', { class: 'acciones' }, el('button', { class: 'btn primario', onclick: async () => {
        if (await confirmar('Publicar réplica', 'La réplica se mostrará en la ficha de la entidad.', 'Publicar'))
          hacer('panel_publicar_replica', { p_tip_id: Number(t.id), p_slug: slug.value, p_texto: ta.value, p_firmante: firm.value,
            p_referencia_url: ref.value, p_fecha: null, p_verificada: ver.checked }, 'Réplica publicada.');
      } }, 'Publicar réplica'))));
  }
  return out;
}

function vistaPostulacion(p) {
  return [el('h2', { tabindex: '-1' }, 'Postulación: ' + p.empresa), campo('Pliego', (p.pliego_codigo || '') + (p.pliego ? ' — ' + p.pliego : '')),
    campo('Contacto (dato privado)', contactoOculto(p.contacto)), p.mensaje ? el('p', { class: 'cita' }, p.mensaje) : null, campo('Recibida', fecha(p.creado_en)),
    el('div', { class: 'bloque' }, el('p', { class: 'nota' }, 'Contactá a la empresa por fuera del sitio. Nada de esto se publica.'),
      el('div', { class: 'acciones' },
        el('button', { class: 'btn primario', onclick: () => hacer('panel_postulacion_resolver', { p_id: Number(p.id), p_estado: 'contactada' }, 'Marcada como contactada.') }, 'Ya la contacté'),
        el('button', { class: 'btn peligro', onclick: () => hacer('panel_postulacion_resolver', { p_id: Number(p.id), p_estado: 'descartada' }, 'Descartada.') }, 'Descartar')))];
}

function vistaPresentacion(p) {
  const nuevo = !p.club_existente;
  const slug = el('input', { id: 'pr-slug', value: p.club_slug || slugificar(p.nombre) });
  const tipo = el('select', { id: 'pr-tipo' }, ['asociacion_civil', 'fundacion', 'municipal', 'estatal_provincial', 'universitario', 'convenio_club'].map(x => el('option', { value: x }, x)));
  const div = el('select', { id: 'pr-div' }, ['', '1ra', '2da', '3ra', 'desarrollo'].map(x => el('option', { value: x, selected: x === (p.division || '') }, x || '—')));
  const lat = el('input', { id: 'pr-lat', inputmode: 'decimal', placeholder: '-34.60' }), lng = el('input', { id: 'pr-lng', inputmode: 'decimal', placeholder: '-58.38' });
  const notas = el('input', { id: 'pr-notas', maxlength: 1000 });
  return [el('h2', { tabindex: '-1' }, 'Presentación: ' + p.nombre),
    campo('Lugar', `${p.ciudad}, ${p.provincia}`), campo('División', p.division), campo('Instagram', p.instagram), campo('Facebook', p.facebook ? enlace(p.facebook) : '—'),
    campo('Web', p.web ? enlace(p.web) : '—'), campo('Logo', p.logo_url ? enlace(p.logo_url, 'ver logo') : '—'),
    campo('¿Autoriza usar el logo?', p.autoriza_logo ? 'Sí' : 'No'), campo('Contacto (dato privado)', contactoOculto(p.contacto)),
    p.descripcion ? el('p', { class: 'cita' }, p.descripcion) : null,
    campo('En el mapa', p.club_existente ? 'Ya existe: ' + p.club_existente + ' (se actualizan redes, web, logo y presentación)' : 'Club nuevo'),
    el('div', { class: 'bloque' }, el('h3', {}, 'Aprobar'),
      el('p', { class: 'nota' }, 'El club figurará con afiliación "a confirmar" hasta que FABA lo confirme. Verificá el contacto antes.'),
      el('label', { for: 'pr-slug' }, 'Slug'), slug,
      nuevo ? [el('label', { for: 'pr-tipo' }, 'Tipo de entidad'), tipo, el('label', { for: 'pr-div' }, 'División'), div,
        el('label', { for: 'pr-lat' }, 'Latitud'), lat, el('label', { for: 'pr-lng' }, 'Longitud'), lng] : null,
      el('div', { class: 'acciones' }, el('button', { class: 'btn primario', onclick: async () => {
        if (await confirmar('Aprobar presentación', nuevo ? 'El club aparecerá en el mapa.' : 'Se actualizarán los datos del club en el sitio.', 'Aprobar'))
          hacer('panel_aprobar_presentacion', { p_id: Number(p.id), p_datos: { slug: slug.value, tipo_entidad: tipo.value, division: div.value, lat: lat.value, lng: lng.value } }, 'Presentación aprobada.');
      } }, 'Aprobar y publicar'))),
    el('div', { class: 'bloque' }, el('label', { for: 'pr-notas' }, 'Notas internas'), notas,
      el('div', { class: 'acciones' },
        el('button', { class: 'btn', onclick: () => hacer('panel_presentacion_resolver', { p_id: Number(p.id), p_estado: 'en_revision', p_notas: notas.value }, 'En revisión.') }, 'En revisión'),
        el('button', { class: 'btn peligro', onclick: () => hacer('panel_presentacion_resolver', { p_id: Number(p.id), p_estado: 'rechazada', p_notas: notas.value }, 'Rechazada.') }, 'Rechazar')))];
}

// ---------------------------------------------------------------- borradores y publicados
const NOMBRE_TABLA = { revisiones_documentales: 'Revisión documental', autoridades: 'Autoridad', pedidos_informacion: 'Pedido de información',
  pliego_hitos: 'Hito de patrocinio', pliego_cotizaciones: 'Cotización', pliegos_rse: 'Pliego RSE', clubes: 'Club',
  novedades_redes: 'Novedad de red', documentos_fuente: 'Documento analizado', replicas: 'Réplica' };

async function cargarBorradores() {
  const f = await rpc('panel_borradores');
  $('#t-borradores').replaceChildren(tabla([['Tipo', x => NOMBRE_TABLA[x.tabla] || x.tabla], ['Qué', x => x.titulo], ['Entidad', x => x.destino || '—'],
    ['Respaldo', x => urlSegura(x.detalle) ? enlace(x.detalle, 'abrir') : (x.detalle || '—')], ['', x => el('button', { class: 'btn chico primario', onclick: async () => {
      const extra = x.tabla === 'revisiones_documentales' && / no_encontrado$/.test(x.titulo) ? '\n\nOjo: "no encontrado" se publica solo si lo buscaste vos.' : '';
      if (await confirmar('Publicar', `${NOMBRE_TABLA[x.tabla] || x.tabla}: ${x.titulo}\nComprobá el respaldo antes.${extra}`, 'Publicar')) {
        try { await rpc('panel_publicar', { p_tabla: x.tabla, p_id: x.id }); aviso('Publicado.'); cargarBorradores(); cargarContadores(); }
        catch (e) { aviso(e.message, true); }
      }
    } }, 'Publicar')]], f, 'No hay borradores.'));
}

async function cargarPublicados() {
  const f = await rpc('panel_publicados');
  $('#t-publicados').replaceChildren(tabla([['Tipo', x => NOMBRE_TABLA[x.tabla] || x.tabla], ['Qué', x => x.titulo], ['Entidad', x => x.destino || '—'],
    ['Fecha', x => fecha(x.creado_en)], ['', x => el('button', { class: 'btn chico peligro', onclick: async () => {
      const motivo = prompt('Motivo para retirarlo (mín. 10 caracteres). Queda registrado:');
      if (!motivo) return;
      try { await rpc('panel_despublicar', { p_tabla: x.tabla, p_id: x.id, p_motivo: motivo }); aviso('Retirado del sitio.'); cargarPublicados(); }
      catch (e) { aviso(e.message, true); }
    } }, 'Retirar')]], f, 'Todavía no hay nada publicado.'));
}

// ---------------------------------------------------------------- fuentes
const CHIP_FUENTE = { activa: 'ok', caida: 'obs', bloqueada_robots: 'mal', pausada: '' };
async function cargarFuentes() {
  const f = await rpc('panel_fuentes');
  $('#t-fuentes').replaceChildren(tabla([['Fuente', x => el('span', {}, el('strong', {}, x.nombre), el('br'), enlace(x.url))], ['Entidad', x => x.destino || '—'],
    ['Estado', x => el('span', { class: 'chip ' + (CHIP_FUENTE[x.estado] || '') }, x.estado)], ['Última revisión', x => fecha(x.ultima_revision) + (x.ultimo_status ? ` (HTTP ${x.ultimo_status})` : '')],
    ['Páginas vistas', x => `${x.urls_vistas}${x.sin_texto ? ` · ${x.sin_texto} sin texto` : ''}`],
    ['', x => el('span', { class: 'acciones' },
      el('button', { class: 'btn chico', onclick: () => editarFuente(x) }, 'Editar'),
      x.estado === 'activa'
        ? el('button', { class: 'btn chico', onclick: () => estadoFuente(x, 'pausada') }, 'Pausar')
        : el('button', { class: 'btn chico', onclick: () => estadoFuente(x, 'activa') }, x.estado === 'bloqueada_robots' ? 'Reactivar (ya consulté al sitio)' : 'Activar'))]], f, 'No hay fuentes cargadas.'));
}
async function estadoFuente(x, estado) {
  if (estado === 'activa' && x.estado === 'bloqueada_robots' &&
      !await confirmar('Reactivar fuente bloqueada', 'El sitio respondió que no quiere ser rastreado (robots.txt o 401/403/429). Reactivala solo si te dieron permiso o cambió su política.', 'Reactivar')) return;
  try { await rpc('panel_fuente_estado', { p_id: x.id, p_estado: estado, p_nota: null }); aviso('Fuente ' + estado + '.'); cargarFuentes(); }
  catch (e) { aviso(e.message, true); }
}
function editarFuente(x) {
  $('#d-fuente').open = true;
  const m = { 'ff-id': x.id, 'ff-nombre': x.nombre, 'ff-url': x.url, 'ff-slug': x.destino_slug, 'ff-tipo': x.tipo, 'ff-portal': x.portal_origen,
    'ff-frec': x.frecuencia_dias, 'ff-smurl': x.sitemap_url, 'ff-patron': x.patron_url, 'ff-resp': x.responsable_auditoria, 'ff-nota': x.nota };
  for (const [k, v] of Object.entries(m)) $('#' + k).value = v ?? '';
  $('#ff-sitemap').checked = !!x.usa_sitemap; $('#ff-nombre').focus();
}
$('#ff-limpiar').addEventListener('click', () => { $('#ff-id').value = ''; });
$('#f-fuente').addEventListener('submit', async ev => {
  ev.preventDefault();
  if (!urlSegura($('#ff-url').value)) { aviso('La URL debe empezar con https://', true); return; }
  const datos = { id: $('#ff-id').value, nombre: $('#ff-nombre').value, url: $('#ff-url').value, destino_slug: $('#ff-slug').value, tipo: $('#ff-tipo').value,
    portal_origen: $('#ff-portal').value, frecuencia_dias: $('#ff-frec').value, usa_sitemap: $('#ff-sitemap').checked, sitemap_url: $('#ff-smurl').value,
    patron_url: $('#ff-patron').value, responsable_auditoria: $('#ff-resp').value, nota: $('#ff-nota').value };
  try { await rpc('panel_fuente_guardar', { p_datos: datos }); aviso('Fuente guardada.'); ev.target.reset(); $('#ff-id').value = ''; cargarFuentes(); }
  catch (e) { aviso(e.message, true); }
});

// ---------------------------------------------------------------- estado y métricas
async function cargarEstado() {
  const [r, a] = await Promise.all([rpc('panel_resumen'), rpc('panel_alertas')]);
  const c = r.cobertura, pct = v => v === null || v === undefined ? '—' : v + '%';
  $('#estado-cobertura').replaceChildren(
    el('div', { class: 'kpi' }, el('b', {}, pct(c.pct_al_dia)), el('span', {}, `Fuentes revisadas a tiempo (${c.al_dia} de ${c.fuentes - c.pausadas})`)),
    el('div', { class: 'kpi' }, el('b', {}, pct(c.pct_caidas)), el('span', {}, `Fuentes caídas (${c.caidas})`)),
    el('div', { class: 'kpi' }, el('b', {}, String(c.bloqueadas)), el('span', {}, 'Fuentes que pidieron no ser rastreadas')),
    el('div', { class: 'kpi' }, el('b', {}, pct(c.pct_sin_texto)), el('span', {}, `Documentos sin texto legible (${c.sin_texto} de ${c.urls_vistas})`)),
    el('div', { class: 'kpi' }, el('b', {}, String(r.pendientes.cola + r.pendientes.bloqueadas)), el('span', {}, 'Ítems de agentes esperando tu decisión')));
  $('#estado-alertas').replaceChildren(
    el('h3', {}, 'Pedidos de información vencidos'),
    tabla([['Organismo', x => x.organismo], ['Asunto', x => x.asunto], ['Venció', x => x.fecha_limite], ['Días de atraso', x => x.dias_de_atraso]], a.pedidos_vencidos, 'Ninguno.'),
    el('h3', {}, 'Datos publicados con más de un año'),
    tabla([['Tipo', x => x.tipo], ['Dato', x => x.detalle], ['Fecha', x => x.fecha_dato], ['Días', x => x.dias]], a.hechos_vencidos, 'Ninguno.'));
  $('#estado-metricas').replaceChildren(tabla([['Votante', x => x.agente], ['Votos', x => x.votos], ['Aprobó y vos aprobaste', x => x.aprobo_y_humano_aprobo],
    ['Aprobó y vos rechazaste', x => x.aprobo_y_humano_rechazo], ['Frenó y vos aprobaste', x => x.freno_y_humano_aprobo], ['Frenó y vos rechazaste', x => x.freno_y_humano_rechazo]],
    r.metricas, 'Todavía no hay decisiones para comparar.'));
  $('#estado-proponentes').replaceChildren(tabla([['Agente', x => x.agente], ['Propuestas', x => x.propuestas], ['Aprobadas', x => x.aprobadas],
    ['Rechazadas', x => x.rechazadas], ['Sin resolver', x => x.sin_resolver], ['Aceptación', x => pct(x.pct_aceptacion)], ['Motivo de rechazo más común', x => x.motivo_rechazo_frecuente || '—']],
    r.proponentes, 'Sin datos.'));
  const ESTADO_RED = { ok: 'Leída', sin_acceso: 'Sin acceso', no_profesional_o_inexistente: 'No es cuenta profesional o no existe',
    token_vencido: 'Token vencido: hay que renovarlo', limite_meta: 'Límite de Meta: reintenta la próxima semana', error: 'Error' };
  let redes = [];
  try { redes = await rpc('panel_redes_actividad'); } catch (_) { redes = []; }
  $('#estado-redes').replaceChildren(tabla([['Cuenta', x => '@' + x.cuenta], ['Club o institución', x => x.club || x.institucion || '—'],
    ['Estado', x => ESTADO_RED[x.estado] || x.estado], ['Seguidores', x => x.seguidores ?? '—'], ['Último posteo', x => x.ultimo_posteo || '—'],
    ['Días sin publicar', x => x.dias_sin_publicar ?? '—'], ['Posteos en 90 días', x => x.posteos_90d ?? '—'], ['Leída el', x => x.fecha_consulta]],
    redes, 'Todavía no se leyó ninguna cuenta.'));
  $('#estado-ejecuciones').replaceChildren(tabla([['Agente', x => x.agente], ['Inicio', x => fecha(x.inicio)], ['Fin', x => fecha(x.fin)],
    ['OK', x => x.ok], ['Bloqueados', x => x.bloqueados], ['Errores', x => x.errores]], r.ejecuciones, 'Sin ejecuciones registradas.'));
  $('#estado-acciones').replaceChildren(tabla([['Cuándo', x => fecha(x.creado_en)], ['Quién', x => x.admin], ['Acción', x => x.accion], ['Ref.', x => x.ref || '—'], ['Detalle', x => x.detalle || '—']],
    r.acciones, 'Sin acciones.'));
}

async function cargarHistorial() {
  const h = await rpc('panel_bandeja', { p_historial: true });
  $('#t-historial').replaceChildren(tabla([['Tipo', x => NOMBRE_TIPO[x.tipo] || x.tipo], ['Qué', x => x.titulo], ['Entidad', x => x.destino || '—'],
    ['Estado', x => x.estado], ['Recibido', x => fecha(x.creado_en)]], h.slice().reverse(), 'Todavía no resolviste nada.'));
}

// ---------------------------------------------------------------- cuenta / segundo factor
let factorNuevo = null;
async function pintarCuenta() {
  if (!sb || !yo) return;
  const { data } = await sb.auth.mfa.listFactors();
  const verif = data && data.totp && data.totp.some(f => f.status === 'verified');
  $('#mfa-estado').textContent = verif ? 'Segundo factor activo: se pide en cada ingreso.' : 'Sin segundo factor: hoy alcanza con la contraseña para entrar. Activalo.';
  $('#btn-mfa-alta').hidden = !!verif;
  return verif;
}
$('#btn-mfa-alta').addEventListener('click', async () => {
  const { data, error } = await sb.auth.mfa.enroll({ factorType: 'totp', friendlyName: 'AuditaDeporte ' + new Date().toISOString().slice(0, 10) });
  if (error) { aviso(error.message, true); return; }
  factorNuevo = data.id;
  const qr = data.totp && data.totp.qr_code;
  if (qr && qr.startsWith('data:image/')) $('#mfa-qr').src = qr;
  $('#mfa-secreto').textContent = (data.totp && data.totp.secret) || '';
  $('#mfa-alta').hidden = false;
});
$('#f-mfa-alta').addEventListener('submit', async ev => {
  ev.preventDefault();
  const { error } = await sb.auth.mfa.challengeAndVerify({ factorId: factorNuevo, code: $('#mfa-codigo').value.trim() });
  if (error) { aviso('Código incorrecto.', true); return; }
  $('#mfa-alta').hidden = true; aviso('Segundo factor activado.');
  yo = await rpc('panel_yo'); pintarCuenta();
});

iniciar();
$('#f-cargar').addEventListener('submit', subirPdf);
