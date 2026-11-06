// Abre el sitio publicado en un navegador real y cuenta lo que ve un visitante. Solo lectura.
import { chromium } from 'playwright';
const SITIO = process.env.SITIO_URL || 'https://auditadeporte.vercel.app/';
const navegador = await chromium.launch();
for (const [nombre, vista] of [['escritorio', { width: 1280, height: 900 }], ['celular', { width: 390, height: 844 }]]) {
  const p = await navegador.newPage({ viewport: vista });
  const errores = [];
  p.on('pageerror', e => errores.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errores.push(m.text().slice(0, 160)); });
  await p.goto(SITIO, { waitUntil: 'networkidle', timeout: 60000 });
  await p.waitForTimeout(4000);
  const r = await p.evaluate(() => ({
    clubes: (typeof CLUBES !== 'undefined' ? CLUBES : []).length,
    nombres: (typeof CLUBES !== 'undefined' ? CLUBES : []).map(c => c.id).sort(),
    pines: document.querySelectorAll('.pin, .marker-cluster').length,
    anchoDoc: document.documentElement.scrollWidth, anchoVentana: window.innerWidth,
    pestanas: [...document.querySelectorAll('[role=tab]')].map(b => b.textContent.trim()),
    simple: !!document.querySelector('#s-simple'),
  }));
  console.log(`[${nombre}]`, JSON.stringify(r));
  if (r.anchoDoc > r.anchoVentana) {
    const anchos = await p.evaluate(() => [...document.querySelectorAll('body *')].filter(e => {
      const b = e.getBoundingClientRect();
      if (!(b.right > window.innerWidth + 1 && b.width > 0)) return false;
      for (let a = e.parentElement; a; a = a.parentElement) { const o = getComputedStyle(a).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
      return true;
    }).slice(0, 12).map(e => `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].slice(0, 4).join('.')} right=${Math.round(e.getBoundingClientRect().right)}`));
    console.log(`[${nombre}] se salen del ancho:`, JSON.stringify(anchos));
  }
  if (r.simple) {
    await p.click('#t-simple'); await p.waitForTimeout(1500);
    const s = await p.evaluate(() => ({
      texto: document.querySelector('#s-simple').innerText.slice(0, 1500),
      jurisdicciones: document.querySelectorAll('#lista-juris [data-juris]').length,
      noPublica: document.querySelectorAll('#lista-juris [data-estado="no_publica"]').length,
      anchoDoc: document.documentElement.scrollWidth,
      checklists: document.querySelectorAll('#lista-juris [aria-label="Qué publica"]').length,
      botonesPresente: document.querySelectorAll('#lista-juris [data-action="ya-presente"]').length,
      contador: document.querySelector('#lista-juris [data-action="ya-presente"]')?.closest('li')?.querySelector('p.text-slate-600')?.textContent.trim(),
      deportista: !!document.querySelector('#simple-deportista'),
      anchos: [...document.querySelectorAll('#s-simple *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1).slice(0, 5).map(e => e.tagName + '.' + e.className.toString().slice(0, 40)),
    }));
    console.log(`[${nombre}] sección simple`, JSON.stringify({ ...s, texto: s.texto.slice(0, 200) }));
    if (nombre === 'celular') {
      const foto = await p.locator('#lista-juris > li').first().screenshot({ type: 'jpeg', quality: 45 });
      console.log('FOTO_SIMPLE_INICIO'); console.log(foto.toString('base64')); console.log('FOTO_SIMPLE_FIN');
      await p.click('#t-deportistas'); await p.waitForTimeout(500);
      const foto2 = (await p.locator('#dep-corresponde').screenshot({ type: 'jpeg', quality: 30 })).toString('base64');
      await p.click('#t-simple'); await p.waitForTimeout(500);
      console.log('FOTO_DEPORTISTA_INICIO');
      for (let i = 0; i < foto2.length; i += 8000) console.log(foto2.slice(i, i + 8000));
      console.log('FOTO_DEPORTISTA_FIN');
    }
    await p.click('#t-deportistas'); await p.waitForTimeout(500);
    // ensayo de situaciones: cada caso arma nota, pedido y patrocinio
    const ensayo = [];
    for (const id of await p.evaluate(() => CASOS.map(c => c.id))) {
      await p.click('#t-deportistas'); await p.click(`[data-action="caso"][data-caso="${id}"]`); await p.click('[data-action="caso-nota"]');
      await p.fill('#nc-muni', 'Municipalidad de Prueba');
      const nota = await p.inputValue('#nc-texto');
      await p.click('[data-action="caso-pedido"]');
      const items = await p.evaluate(() => document.querySelectorAll('.p-item:checked').length);
      await p.click('#t-deportistas'); await p.click('[data-action="caso-rse"]');
      const rubro = await p.inputValue('#d-rubro');
      ensayo.push({ id, nota: nota.includes('Municipalidad de Prueba') && nota.includes('Solicitamos'), items, rubro });
    }
    console.log(`[${nombre}] ensayo casos`, JSON.stringify(ensayo));
    // ensayo de la calculadora: 3 viajes x $2.000 x 44 semanas + cubiertas 120.000 + arreglos 80.000 + indumentaria 60.000
    // + torneos 150.000 + silla 3.000.000 / 5 años = $ 1.274.000 por año
    await p.click('#t-deportistas');
    for (const [k, v] of [['costo_viaje', 2000], ['cubiertas', 120000], ['arreglos', 80000], ['indumentaria', 60000], ['torneos', 150000], ['silla_precio', 3000000]])
      await p.fill(`[data-costo="${k}"]`, String(v));
    const total = await p.locator('#costo-resultado').innerText();
    await p.click('#costo-rse'); await p.waitForTimeout(300);
    console.log(`[${nombre}] ensayo calculadora`, JSON.stringify({ ok: total.includes('1.274.000'), tipo: await p.inputValue('#d-tipo'),
      texto: (await p.inputValue('#d-texto')).slice(0, 90) }));
    if (nombre === 'celular') {
      await p.click('#t-deportistas'); await p.click('[data-action="caso"][data-caso="sillas-municipio"]'); await p.waitForTimeout(300);
      const fc = (await p.locator('#dep-casos').screenshot({ type: 'jpeg', quality: 30 })).toString('base64');
      console.log('FOTO_CASOS_INICIO'); for (let i = 0; i < fc.length; i += 8000) console.log(fc.slice(i, i + 8000)); console.log('FOTO_CASOS_FIN');
    }
    await p.click('#t-deportistas'); await p.waitForTimeout(300);
    await p.locator('#dep-corresponde [data-action="pedir-deportista"]').click(); await p.waitForTimeout(500);
    console.log(`[${nombre}] pedido deportista`, JSON.stringify(await p.evaluate(() => ({ pestana: document.querySelector('[role=tab][aria-selected=true]')?.textContent.trim(),
      items: [...document.querySelectorAll('.p-item:checked')].map(i => i.value.slice(0, 30)) }))));
    await p.fill('#p-entidad', 'Municipalidad de Prueba'); await p.locator('details:has(#r-armar) summary').click();
    await p.fill('#r-fecha', '2026-10-01'); await p.fill('#r-exp', '4012-1/2026'); await p.click('#r-armar'); await p.waitForTimeout(300);
    console.log(`[${nombre}] reclamo`, JSON.stringify((await p.inputValue('#p-texto')).slice(0, 160)));
    await p.click('#t-transp'); await p.waitForTimeout(400);
    console.log(`[${nombre}] documentos`, JSON.stringify(await p.evaluate(() => ({ tarjetas: document.querySelectorAll('#cards-transp > li').length,
      ancho: document.documentElement.scrollWidth }))));
    await p.click('#t-deportistas'); await p.waitForTimeout(300);
    await p.locator('#s-deportistas #simple-deportista [data-action="pedir-rse"]').click(); await p.waitForTimeout(500);
    console.log(`[${nombre}] pedido rse`, JSON.stringify(await p.evaluate(() => ({
      pestana: document.querySelector('[role=tab][aria-selected=true]')?.textContent.trim(), tipo: document.querySelector('#d-tipo').value,
      rseVisible: !document.querySelector('#d-rse-wrap').classList.contains('hidden'),
      contactoVisible: !document.querySelector('#d-contacto-wrap').classList.contains('hidden') }))));
    await p.click('#t-rse'); await p.waitForTimeout(500);
    console.log(`[${nombre}] patrocinar`, JSON.stringify(await p.evaluate(() => ({ pliegos: document.querySelectorAll('#rse-grid article').length,
      banner: !!document.querySelector('#s-rse [data-action="pedir-rse"]') }))));
    await p.click('#t-simple'); await p.waitForTimeout(500);
    const boton = p.locator('#lista-juris [data-estado="no_publica"] [data-action="pedir-juris"]').first();
    if (await boton.count()) {
      await boton.click(); await p.waitForTimeout(800);
      const pedido = await p.evaluate(() => ({ pestana: document.querySelector('[role=tab][aria-selected=true]')?.textContent.trim(),
                                               entidad: document.querySelector('#p-entidad').value,
                                               texto: document.querySelector('#p-texto').value }));
      console.log(`[${nombre}] pedido`, JSON.stringify(pedido));
    }
  }
  console.log(`[${nombre}] errores:`, JSON.stringify(errores.slice(0, 8)));
  await p.close();
}
await navegador.close();
