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
  if (r.simple) {
    await p.click('#t-simple'); await p.waitForTimeout(1500);
    const s = await p.evaluate(() => ({
      texto: document.querySelector('#s-simple').innerText.slice(0, 1500),
      jurisdicciones: document.querySelectorAll('#lista-juris [data-juris]').length,
      noPublica: document.querySelectorAll('#lista-juris [data-estado="no_publica"]').length,
      anchoDoc: document.documentElement.scrollWidth,
    }));
    console.log(`[${nombre}] sección simple`, JSON.stringify(s));
  }
  console.log(`[${nombre}] errores:`, JSON.stringify(errores.slice(0, 8)));
  await p.close();
}
await navegador.close();
