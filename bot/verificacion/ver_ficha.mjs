// Abre la ficha de un club y muestra el bloque "Lo auditado hasta hoy".
import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 390, height: 844 } }); const err = [];
p.on('pageerror', e => err.push(e.message));
await p.goto('https://auditadeporte.vercel.app/', { waitUntil: 'load', timeout: 60000 }); await p.waitForTimeout(4000);
await p.evaluate(() => abrirClub(CLUBES.find(c => /brown/i.test(c.id)).id)); await p.waitForTimeout(3000);
console.log('FICHA:', (await p.locator('#dlg-club').innerText()).replace(/\s+/g, ' ').slice(0, 1400));
console.log('errores:', JSON.stringify(err)); await b.close();
