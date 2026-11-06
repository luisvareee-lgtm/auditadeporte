// Recorre cada pestaña del sitio publicado en un celular y saca una captura de página completa. Solo lectura.
import { chromium } from 'playwright';
const SITIO = process.env.SITIO_URL || 'https://auditadeporte.vercel.app/';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 390, height: 844 } });
await p.goto(SITIO, { waitUntil: 'networkidle', timeout: 60000 }); await p.waitForTimeout(3500);
const tabs = await p.evaluate(() => [...document.querySelectorAll('[role=tab]')].map(t => t.id.replace('t-', '')));
const imprimir = (nombre, buf) => { const s = buf.toString('base64'); console.log('FOTO_' + nombre + '_INICIO');
  for (let i = 0; i < s.length; i += 8000) console.log(s.slice(i, i + 8000)); console.log('FOTO_' + nombre + '_FIN'); };
imprimir('inicio', await p.screenshot({ type: 'jpeg', quality: 30 }));
for (const t of tabs) {
  await p.click('#t-' + t); await p.waitForTimeout(1200);
  const alto = await p.evaluate(() => document.documentElement.scrollHeight);
  console.log('PESTANA', t, 'alto', alto);
  imprimir(t, await p.screenshot({ type: 'jpeg', quality: 25, fullPage: true }));
}
await b.close();
