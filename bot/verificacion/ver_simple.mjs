// Captura la pestaña Explicado fácil (claro) y lista textos con poco contraste contra su fondo real.
import { chromium } from 'playwright';
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' });
const p = await ctx.newPage();
await p.goto('https://auditadeporte.vercel.app/#simple', { waitUntil: 'load', timeout: 60000 }); await p.waitForTimeout(3500);
const bajos = await p.evaluate(() => {
  const rgb = c => (c.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const fondo = el => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c.length >= 3 && (c[3] === undefined || c[3] > 0.5)) return c; } return [255, 255, 255]; };
  const out = [];
  for (const el of document.querySelectorAll('#s-simple *')) {
    if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 3)) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    if (getComputedStyle(el).backgroundImage !== 'none' || [...Array(6)].some((_, i) => { let e = el; for (let k = 0; k < i && e; k++) e = e.parentElement; return e && getComputedStyle(e).backgroundImage !== 'none'; })) continue;
    const c = rgb(getComputedStyle(el).color), f = fondo(el), L1 = lum(c), L2 = lum(f);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    if (ratio < 4.5) out.push(`${ratio.toFixed(2)} | ${el.tagName.toLowerCase()}.${[...el.classList].join('.')} | "${el.textContent.trim().slice(0, 70)}"`);
  }
  return out.slice(0, 40);
});
console.log('POCO CONTRASTE:\n' + bajos.join('\n'));
const buf = await p.screenshot({ type: 'jpeg', quality: 55, fullPage: true });
const b64 = buf.toString('base64'); for (let i = 0; i < b64.length; i += 8000) console.log(`IMG simple ${i / 8000} ${b64.slice(i, i + 8000)}`);
await b.close();
