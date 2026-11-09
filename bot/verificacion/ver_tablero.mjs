// Inicio (mapa + mi club + tablero) en escritorio, celular y celular en modo oscuro: errores, ancho y capturas.
import { chromium } from 'playwright';
const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
const imprimir = (nom, buf) => { const b64 = buf.toString('base64'); for (let i = 0; i < b64.length; i += 8000) console.log(`IMG ${nom} ${i / 8000} ${b64.slice(i, i + 8000)}`); };
for (const [n, vp, oscuro] of [['escritorio', { width: 1366, height: 900 }, false], ['celular', { width: 390, height: 844 }, false], ['oscuro', { width: 390, height: 844 }, true]]) {
  const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1 });
  if (oscuro) await ctx.addInitScript(() => localStorage.setItem('ad_oscuro', '1'));
  const p = await ctx.newPage(); const err = [];
  p.on('pageerror', e => err.push(e.message)); p.on('console', m => m.type() === 'error' && !/404/.test(m.text()) && err.push(m.text()));
  await p.goto('https://auditadeporte.vercel.app/', { waitUntil: 'load', timeout: 60000 });
  await p.waitForTimeout(3000);
  console.log(n, 'pestañas:', (await p.locator('[role=tab]').allInnerTexts()).map(t => t.trim()).join(' | '));
  console.log(n, 'oscuro activo:', await p.evaluate(() => document.documentElement.classList.contains('oscuro')));
  await p.selectOption('#ml-club', { index: 1 }); await p.waitForTimeout(1500);
  console.log(n, 'mi club:', (await p.locator('#ml-ficha').innerText()).replace(/\s+/g, ' ').slice(0, 260));
  await p.locator('#inicio-tablero').scrollIntoViewIfNeeded(); await p.waitForTimeout(6000);
  console.log(n, 'mapa 3D:', await p.locator('#tb-3d canvas').count(), 'lienzo(s) · semáforo', await p.locator('#tb-semaforo > div').count(), 'filas');
  const ancho = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  console.log(n, 'se sale del ancho:', ancho, '| errores:', JSON.stringify(err));
  if (n !== 'escritorio') imprimir(`inicio-${n}`, await p.screenshot({ type: 'jpeg', quality: 50, fullPage: true }));
  await p.locator('[data-tbzoom^="-58.45"]').click(); await p.waitForTimeout(3500);
  const dd = await p.locator('#tb-3d').boundingBox();
  await p.mouse.move(dd.x + dd.width / 2, dd.y + dd.height / 2); await p.mouse.wheel(0, -600); await p.waitForTimeout(2500);
  imprimir(`mapa3d-${n}`, await p.locator('#tb-3d').screenshot({ type: 'jpeg', quality: 70 }));
  await ctx.close();
}
await b.close();
