// Abre el Tablero en celular y escritorio, informa errores y guarda capturas (se suben como artefacto de la corrida).
import { chromium } from 'playwright';
import fs from 'fs';
fs.mkdirSync('capturas', { recursive: true });
const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
for (const [n, vp] of [['celular', { width: 390, height: 844 }], ['escritorio', { width: 1366, height: 900 }]]) {
  const p = await b.newPage({ viewport: vp, deviceScaleFactor: 1 }); const err = [];
  p.on('pageerror', e => err.push(e.message)); p.on('console', m => m.type() === 'error' && err.push(m.text()));
  await p.goto('https://auditadeporte.vercel.app/#tablero', { waitUntil: 'load', timeout: 60000 });
  await p.waitForTimeout(6000);
  console.log(n, 'KPIs:', (await p.locator('#tb-kpis').innerText()).replace(/\s+/g, ' '));
  console.log(n, 'mapa 3D:', await p.locator('#tb-3d canvas').count(), 'lienzo(s) ·', await p.locator('#tb-3d-nota').innerText());
  const ancho = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  console.log(n, 'se sale del ancho:', ancho, '| errores:', JSON.stringify(err));
  await p.screenshot({ path: `capturas/tablero-${n}.png`, fullPage: true });
  await p.locator('[data-tb3="clubes"]').click(); await p.waitForTimeout(2500);
  await p.locator('#tb-3d').screenshot({ path: `capturas/mapa3d-${n}.png` });
  for (const [nom, buf] of [[`tablero-${n}`, await p.screenshot({ type: 'jpeg', quality: 55, fullPage: true })], [`mapa3d-${n}`, await p.locator('#tb-3d').screenshot({ type: 'jpeg', quality: 70 })]]) {
    const b64 = buf.toString('base64');
    for (let i = 0; i < b64.length; i += 8000) console.log(`IMG ${nom} ${i / 8000} ${b64.slice(i, i + 8000)}`);
  }
  await p.close();
}
await b.close();
