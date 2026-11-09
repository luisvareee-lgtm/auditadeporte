// Inicio con el mapa único: logos y grupos, vistas 3D, municipios, globos; escritorio, celular y oscuro.
import { chromium } from 'playwright';
const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
const imprimir = (nom, buf) => { const b64 = buf.toString('base64'); for (let i = 0; i < b64.length; i += 8000) console.log(`IMG ${nom} ${i / 8000} ${b64.slice(i, i + 8000)}`); };
for (const [n, vp, oscuro] of [['escritorio', { width: 1366, height: 900 }, false], ['celular', { width: 390, height: 844 }, false], ['oscuro', { width: 390, height: 844 }, true]]) {
  const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1 });
  if (oscuro) await ctx.addInitScript(() => localStorage.setItem('ad_oscuro', '1'));
  const p = await ctx.newPage(); const err = [];
  p.on('pageerror', e => err.push(e.message)); p.on('console', m => m.type() === 'error' && !/404/.test(m.text()) && err.push(m.text()));
  await p.goto('https://auditadeporte.vercel.app/', { waitUntil: 'load', timeout: 60000 });
  await p.waitForTimeout(5000);
  console.log(n, 'logos:', await p.locator('#map .pin').count(), '· grupos:', await p.locator('#map .grupo-pin').count());
  if (n === 'escritorio') imprimir('mapa-clubes', await p.locator('#map').screenshot({ type: 'jpeg', quality: 70 }));
  await p.locator('.grupo-pin').first().click().catch(() => {}); await p.waitForTimeout(2500);
  console.log(n, 'tras tocar un grupo, logos:', await p.locator('#map .pin').count());
  for (const v of ['colectas', 'm_transparencia', 'publicaciones']) {
    await p.locator(`[data-vista="${v}"]`).click(); await p.waitForTimeout(3500);
    console.log(n, v, '→', (await p.locator('#mapa-nota').innerText()).slice(0, 150));
    if (n !== 'celular' && v === 'm_transparencia') { await p.locator('[data-action="volar"][data-z="9"]').first().click(); await p.waitForTimeout(3500); imprimir(`mapa-${v}-${n}`, await p.locator('#map').screenshot({ type: 'jpeg', quality: 70 })); }
  }
  const ancho = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  console.log(n, 'se sale del ancho:', ancho, '| errores:', JSON.stringify(err));
  if (n === 'celular') imprimir('inicio-celular', await p.screenshot({ type: 'jpeg', quality: 50, fullPage: false }));
  await ctx.close();
}
await b.close();
