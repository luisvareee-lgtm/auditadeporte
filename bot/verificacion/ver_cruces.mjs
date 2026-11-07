// Muestra el texto del cruce de cargos y de las autoridades de instituciones tal como lo ve un visitante.
import { chromium } from 'playwright';
const b = await chromium.launch(); const p = await b.newPage();
const errores = []; p.on('pageerror', e => errores.push(e.message));
await p.goto('https://auditadeporte.vercel.app/', { waitUntil: 'networkidle' });
await p.click('#t-inst'); await p.waitForTimeout(1500);
console.log('CRUCES:', (await p.locator('#inst-cruces').innerText()).slice(0, 1500));
console.log('INST:', (await p.locator('#inst-grid').innerText()).slice(0, 4000));
console.log('errores:', JSON.stringify(errores)); await b.close();
