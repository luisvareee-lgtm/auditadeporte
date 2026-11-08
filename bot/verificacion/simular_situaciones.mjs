// Simula situaciones reales de uso del sitio publicado y anota cada problema que encuentra.
// No deja rastros: todo envío a la base se intercepta y se responde "ok" sin llegar a Supabase,
// salvo los que la base va a RECHAZAR (para probar sus validaciones), que nunca se guardan.
import { chromium } from 'playwright';
const SITIO = process.env.SITIO_URL || 'https://auditadeporte.vercel.app/';
const hallazgos = [];
const anotar = (gravedad, escenario, que) => { hallazgos.push({ gravedad, escenario, que }); console.log(`  [${gravedad}] ${que}`); };
const ok = (escenario, que) => console.log(`  [ok] ${que}`);
const RARO = /\bundefined\b|\bNaN\b|\[object Object\]|\bnull\b(?! *[,;:])/;

const nav = await chromium.launch();
async function pagina(vista = { width: 390, height: 844 }, { sinBase = false, dejarPasar = () => false } = {}) {
  const ctx = await nav.newContext({ viewport: vista });
  const p = await ctx.newPage();
  p.errores = [];
  p.on('pageerror', e => p.errores.push('JS: ' + e.message.slice(0, 160)));
  p.on('console', m => { if (m.type() === 'error') p.errores.push('consola: ' + m.text().slice(0, 160)); });
  await ctx.route(/supabase\.co/, async r => {
    if (sinBase) return r.abort('failed');
    const metodo = r.request().method();
    if (metodo === 'GET' || metodo === 'HEAD' || metodo === 'OPTIONS' || /\/rpc\/(contar|resumen)/.test(r.request().url())) return r.continue();
    if (dejarPasar(r.request())) return r.continue();
    p.envios = (p.envios || []).concat([{ url: r.request().url().replace(/\?.*/, ''), cuerpo: r.request().postData() }]);
    return r.fulfill({ status: 201, body: '', headers: { 'access-control-allow-origin': '*' } });
  });
  await p.goto(SITIO, { waitUntil: 'networkidle', timeout: 60000 });
  await p.waitForTimeout(2500);
  return p;
}
const texto = (p, sel) => p.inputValue(sel);
const toasts = p => p.evaluate(() => [...document.querySelectorAll('#toasts > div')].map(d => d.textContent));
async function revisarTexto(p, esc, nombre, t, debe = [], noDebe = []) {
  if (RARO.test(t)) anotar('alta', esc, `${nombre}: aparece "${t.match(RARO)[0]}" en el texto`);
  for (const d of debe) (t.includes(d) ? ok(esc, `${nombre} incluye "${d}"`) : anotar('alta', esc, `${nombre} NO incluye "${d}"`));
  for (const d of noDebe) if (t.includes(d)) anotar('media', esc, `${nombre} incluye "${d}" y no debería`);
}

// 1 ─ Deportista de Brown: las sillas del municipio están rotas y el municipio no responde
{
  const E = 'Deportista: sillas del municipio rotas, sin respuesta'; console.log('\n== ' + E);
  const p = await pagina();
  await p.click('#t-deportistas'); await p.click('[data-action="caso"][data-caso="sillas-municipio"]'); await p.click('[data-action="caso-nota"]');
  await p.fill('#nc-muni', 'Municipalidad de Almirante Brown'); await p.fill('#nc-nom', 'Juan Pérez'); await p.fill('#nc-dni', 'DNI 30.000.000');
  await p.locator('#nc-muni').dispatchEvent('input');
  await revisarTexto(p, E, 'Nota', await texto(p, '#nc-texto'), ['Almirante Brown', 'Juan Pérez', '30.5']);
  await p.evaluate(() => { document.querySelector('#nc-seguimiento').open = true; });
  await p.fill('#nc-fecha', '2026-09-01'); await p.fill('#nc-exp', 'Expte. 4059-1234/2026');
  await p.click('[data-action="caso-reiterar"]');
  await revisarTexto(p, E, 'Reiteración', await texto(p, '#nc-texto'), ['01/09/2026', 'Expte. 4059-1234/2026', 'Ordenanza General 267/80', 'Juan Pérez']);
  await p.click('[data-action="caso-control"][data-control="defensoria"]');
  await revisarTexto(p, E, 'Queja a la Defensoría', await texto(p, '#nc-texto'), ['Defensoría del Pueblo de la Provincia de Buenos Aires', 'Expte. 4059-1234/2026']);
  await p.uncheck('#nc-pba'); await p.click('[data-action="caso-reiterar"]');
  await revisarTexto(p, E, 'Reiteración fuera de PBA', await texto(p, '#nc-texto'), [], ['267/80']);
  const sinFecha = await pagina();
  await sinFecha.click('#t-deportistas'); await sinFecha.click('[data-action="caso"][data-caso="sillas-municipio"]');
  await sinFecha.click('[data-action="caso-reiterar"]');
  const t = await texto(sinFecha, '#nc-texto');
  (t.includes('[fecha en que presentaste la nota]') ? ok(E, 'sin datos, la reiteración deja los corchetes para completar') : anotar('media', E, 'sin datos, la reiteración no marca qué completar'));
  if (p.errores.length) anotar('alta', E, 'errores: ' + p.errores.join(' | '));
}

// 2 ─ Deportista con silla propia (obra social) y traslados (CUD)
{
  const E = 'Deportista: silla propia y traslados'; console.log('\n== ' + E);
  const p = await pagina();
  await p.click('#t-deportistas'); await p.click('[data-action="caso"][data-caso="silla-propia"]');
  await p.click('[data-action="caso-control"][data-control="obra_social"]');
  await revisarTexto(p, E, 'Pedido a la obra social', await texto(p, '#nc-texto'), ['Ley 24.901', 'prescripción médica']);
  await p.click('[data-action="caso"][data-caso="traslados"]');
  await p.click('[data-action="caso-control"][data-control="transporte"]');
  await revisarTexto(p, E, 'Reclamo a la CNRT', await texto(p, '#nc-texto'), ['22.431', 'CNRT']);
  const vis = await p.locator('#caso-panel').innerText();
  (vis.includes('0800-333-0300') ? ok(E, 'muestra el teléfono de la CNRT') : anotar('baja', E, 'no muestra el teléfono de la CNRT'));
  (vis.includes('Borrador') ? ok(E, 'avisa que los modelos son borrador sin revisión legal') : anotar('media', E, 'no avisa que los modelos no están revisados'));
  if (p.errores.length) anotar('alta', E, 'errores: ' + p.errores.join(' | '));
}

// 3 ─ Vecino pide información a distintas jurisdicciones (ley correcta en cada una)
{
  const E = 'Vecino: pedido de información según la jurisdicción'; console.log('\n== ' + E);
  const p = await pagina({ width: 1280, height: 900 });
  const casos = { 'muni-almirante-brown': ['Constitución Nacional'], 'muni-rosario': ['7249/2001'], 'prov-cordoba': ['8803'],
                  'prov-tucuman': ['Constitución Nacional'], 'caba': ['104'] };
  const slugs = await p.evaluate(() => JURIS.map(j => j.slug));
  for (const [slug, debe] of Object.entries(casos)) {
    const s = slugs.find(x => x === slug) || slugs.find(x => x.includes(slug.replace(/^(muni|prov)-/, '')));
    if (!s) { anotar('media', E, `no existe la jurisdicción ${slug} en el sitio`); continue; }
    await p.evaluate(sl => { const b = document.createElement('button'); b.dataset.action = 'pedir-juris'; b.dataset.slug = sl; document.body.appendChild(b); b.click(); b.remove(); }, s);
    await p.waitForTimeout(300);
    const t = await texto(p, '#p-texto');
    await revisarTexto(p, E, `Pedido a ${s}`, t, debe, s.startsWith('muni-') ? ['12.475 de acceso a documentos administrativos (Poder Ejecutivo'] : []);
    if (!/\[Nombre|\[DNI|\[Correo/.test(t)) anotar('baja', E, `Pedido a ${s}: no deja marcados los datos personales a completar`);
  }
  await p.click('#t-pedir'); await p.evaluate(() => { for (let a = document.querySelector('#r-fecha'); a; a = a.parentElement) if (a.tagName === 'DETAILS') a.open = true; });
  await p.locator('#r-fecha').scrollIntoViewIfNeeded();
  if (!(await p.locator('#r-fecha').isVisible())) { anotar('media', E, 'el formulario de pronto despacho no se ve sin pasos previos'); }
  else {
  await p.fill('#r-fecha', '2026-08-01'); await p.fill('#r-exp', 'Expte. 99/2026'); await p.click('#r-armar');
  await revisarTexto(p, E, 'Pronto despacho del pedido', await texto(p, '#p-texto'), ['01/08/2026', 'Expte. 99/2026', 'pronto despacho']);
  }
  if (p.errores.length) anotar('alta', E, 'errores: ' + p.errores.join(' | '));
}

// 4 ─ Club carga convocatorias: válida, al revés y con fecha futura (esta la rechaza la base: nunca se guarda)
{
  const E = 'Club: registro de convocatorias'; console.log('\n== ' + E);
  const p = await pagina(undefined, { dejarPasar: r => /convocatorias/.test(r.url()) && (r.postData() || '').includes('2030-01-01') });
  await p.click('#t-deportistas'); await p.locator('#cv-club').focus(); await p.waitForTimeout(300);
  const opciones = await p.locator('#cv-club option').count();
  (opciones > 5 ? ok(E, `el selector muestra ${opciones - 1} clubes`) : anotar('alta', E, `el selector de club tiene ${opciones} opciones`));
  const club = await p.locator('#cv-club option').nth(1).getAttribute('value');
  const cargar = async (aviso, torneo) => { await p.selectOption('#cv-club', club); await p.fill('#cv-aviso', aviso); await p.fill('#cv-torneo', torneo);
    await p.click('#form-convocatoria button'); await p.waitForTimeout(1500); return toasts(p); };
  let t = await cargar('2025-07-01', '2025-08-01');
  (t.some(x => /Gracias/.test(x)) ? ok(E, 'convocatoria válida: confirma con "Gracias"') : anotar('alta', E, 'convocatoria válida sin confirmación: ' + t));
  await p.waitForTimeout(3600);
  t = await cargar('2025-08-01', '2025-07-01');
  (t.some(x => /antes del aviso/.test(x)) ? ok(E, 'torneo antes del aviso: lo frena con un mensaje claro') : anotar('media', E, 'torneo antes del aviso no se frena: ' + t));
  await p.waitForTimeout(3600);
  t = await cargar('2030-01-01', '2030-02-01');
  (t.some(x => /futura/.test(x)) ? ok(E, 'aviso con fecha futura: la base lo rechaza y el mensaje lo explica') : anotar('media', E, 'aviso con fecha futura: mensaje poco claro: ' + JSON.stringify(t)));
  if (p.errores.filter(e => !/400|status of 4/.test(e)).length) anotar('alta', E, 'errores: ' + p.errores.join(' | '));
}

// 5 ─ Deportista manda un dato privado con datos personales o de salud
{
  const E = 'Deportista: envío de un dato con datos personales'; console.log('\n== ' + E);
  const p = await pagina();
  await p.click('#t-dato'); await p.selectOption('#d-tipo', 'dato');
  await p.fill('#d-texto', 'Mi DNI es 30.123.456 y mi teléfono 11 5555-1234. Tengo paraplejia y la silla del club está rota desde marzo.');
  await p.check('#d-ok'); await p.click('#d-enviar'); await p.waitForTimeout(1200);
  const est = await p.locator('#d-estado').innerText();
  const envio = (p.envios || []).find(e => /tips/.test(e.url));
  if (envio && /30\.123\.456|5555-1234|paraplejia/.test(envio.cuerpo || ''))
    anotar('alta', E, 'el formulario envía DNI, teléfono y salud sin advertir; quedan en la Bandeja del panel');
  else ok(E, 'advierte o no envía los datos personales: ' + est);
  await p.selectOption('#d-tipo', 'solicitud_rse'); await p.fill('#d-texto', 'Necesitamos cubiertas y rulemanes para las sillas del equipo antes del torneo de diciembre.');
  await p.check('#d-ok'); await p.click('#d-enviar'); await p.waitForTimeout(800);
  const e2 = await p.locator('#d-estado').innerText();
  (/contacto/i.test(e2) ? ok(E, 'patrocinio sin contacto: pide un contacto') : anotar('media', E, 'patrocinio sin contacto: ' + e2));
  if (p.errores.length) anotar('alta', E, 'errores: ' + p.errores.join(' | '));
}

// 6 ─ Se cae la base de datos (Supabase no responde)
{
  const E = 'Sin conexión con la base'; console.log('\n== ' + E);
  const p = await pagina(undefined, { sinBase: true });
  for (const t of ['#t-simple', '#t-deportistas', '#t-pedir', '#t-inst', '#t-transp', '#t-rse', '#t-dato', '#t-mapa']) { await p.click(t); await p.waitForTimeout(250); }
  const js = p.errores.filter(e => e.startsWith('JS:'));
  (js.length ? anotar('alta', E, 'errores de programa con la base caída: ' + js.join(' | ')) : ok(E, 'todas las pestañas abren sin errores de programa'));
  const clubes = await p.evaluate(() => (typeof CLUBES !== 'undefined' ? CLUBES.length : 0));
  (clubes ? ok(E, `muestra ${clubes} clubes de respaldo`) : anotar('alta', E, 'sin la base no se ve ningún club'));
  await p.click('#t-dato'); await p.fill('#d-texto', 'Texto de prueba con más de cuarenta caracteres para ver el aviso.'); await p.check('#d-ok');
  await p.click('#d-enviar'); await p.waitForTimeout(1500);
  ok(E, 'mensaje al enviar sin base: ' + (await p.locator('#d-estado').innerText()));
}

// 7 ─ Pantallas chicas: nada se sale del ancho y no aparecen "undefined"/"NaN" en ninguna pestaña
for (const [nombre, vista] of [['celular chico 320px', { width: 320, height: 640 }], ['escritorio', { width: 1366, height: 800 }]]) {
  const E = 'Pantalla ' + nombre; console.log('\n== ' + E);
  const p = await pagina(vista);
  for (const t of ['#t-simple', '#t-mapa', '#t-deportistas', '#t-pedir', '#t-inst', '#t-transp', '#t-rse', '#t-dato']) {
    await p.click(t); await p.waitForTimeout(400);
    const r = await p.evaluate(() => {
      const panel = document.querySelector('[role=tabpanel]:not(.hidden)') || document.body;
      const sale = [...panel.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
        if (!(b.width > 0 && b.right > document.documentElement.clientWidth + 2)) return false;
        for (let a = e.parentElement; a; a = a.parentElement) { const o = getComputedStyle(a).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
        return true; }).slice(0, 3).map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + [...e.classList].slice(0, 2).join('.'));
      return { sale, texto: panel.innerText, ancho: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2 };
    });
    if (r.ancho && r.sale.length) anotar('media', E, `${t}: se sale del ancho → ${r.sale.join(', ')}`);
    const raro = r.texto.match(/.{0,40}(\bundefined\b|\bNaN\b|\[object Object\]).{0,40}/);
    if (raro) anotar('alta', E, `${t}: texto roto "${raro[0].replace(/\s+/g, ' ')}"`);
  }
  if (!hallazgos.some(h => h.escenario === E)) ok(E, 'todas las pestañas entran en el ancho y sin textos rotos');
  if (p.errores.length) anotar('alta', E, 'errores: ' + p.errores.join(' | '));
}

// 8 ─ Enlaces a fuentes: los que no abren
{
  const E = 'Enlaces a fuentes'; console.log('\n== ' + E);
  const p = await pagina({ width: 1280, height: 900 });
  for (const t of ['#t-simple', '#t-deportistas', '#t-inst', '#t-pedir']) { await p.click(t); await p.waitForTimeout(300); }
  const urls = [...new Set(await p.evaluate(() => [...document.querySelectorAll('a[href^="http"]')].map(a => a.href.split('#')[0])))]
    .filter(u => !/instagram\.com|facebook\.com|wa\.me|twitter|x\.com|supabase|vercel\.app/.test(u)).slice(0, 80);
  let rotos = 0;
  for (const u of urls) {
    try { const r = await p.request.get(u, { timeout: 20000, maxRedirects: 5 });
      if (r.status() === 404 || r.status() === 410) { rotos++; anotar('media', E, `enlace roto (${r.status()}): ${u}`); } }
    catch (e) { console.log(`  [revisar] no respondió a tiempo: ${u}`); }
  }
  ok(E, `${urls.length} enlaces revisados, ${rotos} rotos`);
}

await nav.close();
console.log('\n===== RESUMEN =====');
for (const g of ['alta', 'media', 'baja']) {
  const hs = hallazgos.filter(h => h.gravedad === g);
  console.log(`${g.toUpperCase()}: ${hs.length}`);
  for (const h of hs) console.log(`  · [${h.escenario}] ${h.que}`);
}
