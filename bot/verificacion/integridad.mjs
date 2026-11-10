// Revisa que cada librería externa del sitio tenga versión fija y que su huella (integrity) coincida con lo que
// hoy entrega el servidor. Si una no tiene huella, la imprime para poder agregarla.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
let mal = 0;
for (const pagina of ['index.html', 'admin.html']) {
  const html = readFileSync(new URL('../../' + pagina, import.meta.url), 'utf8');
  for (const m of html.matchAll(/<(?:script|link)\b[^>]*?(?:src|href)="(https:\/\/[^"]+)"[^>]*>/g)) {
    const etiqueta = m[0], url = m[1];
    if (/rel="(preconnect|dns-prefetch|canonical|alternate)"/.test(etiqueta) || !/\.(js|css)(\?|$)/.test(url) && !/tailwindcss/.test(url)) continue;
    if (/cdn\.tailwindcss\.com/.test(url)) { console.log(`AVISO ${pagina}: ${url} se genera en el momento y no admite huella`); continue; }
    const r = await fetch(url);
    const huella = 'sha384-' + createHash('sha384').update(Buffer.from(await r.arrayBuffer())).digest('base64');
    const declarada = (etiqueta.match(/integrity="([^"]+)"/) || [])[1];
    if (!/@\d+\.\d+\.\d+/.test(url)) { console.log(`MAL ${pagina}: ${url} no tiene versión fija`); mal++; }
    if (!declarada) { console.log(`FALTA ${pagina}: ${url} integrity="${huella}"`); mal++; }
    else if (declarada !== huella) { console.log(`MAL ${pagina}: ${url} declara ${declarada} y el servidor entrega ${huella}`); mal++; }
    else console.log(`OK ${pagina}: ${url}`);
  }
}
process.exit(mal ? 1 : 0);
