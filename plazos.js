// Reloj de plazos de un pedido de acceso a la información. Funciones puras (se prueban con node --test).
// Cuenta días hábiles administrativos: sin sábados, domingos ni feriados nacionales. NO conoce feriados provinciales
// o municipales ni asuetos: las fechas son orientativas y así se le avisa a quien las ve.
(function (raiz) {
  const iso = d => d.toISOString().slice(0, 10);
  const dia = s => new Date(s + 'T12:00:00Z');
  const mas = (d, n) => new Date(d.getTime() + n * 864e5);

  function pascua(anio) {                       // domingo de Pascua (calendario gregoriano)
    const a = anio % 19, b = Math.floor(anio / 100), c = anio % 100, d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25),
      g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4,
      l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451),
      mes = Math.floor((h + l - 7 * m + 114) / 31), di = ((h + l - 7 * m + 114) % 31) + 1;
    return new Date(Date.UTC(anio, mes - 1, di, 12));
  }
  // feriados trasladables (Ley 27.399): martes o miércoles pasan al lunes anterior; jueves o viernes, al lunes siguiente
  function trasladar(d) {
    const s = d.getUTCDay();
    return s === 2 ? mas(d, -1) : s === 3 ? mas(d, -2) : s === 4 ? mas(d, 4) : s === 5 ? mas(d, 3) : d;
  }
  // días no laborables con fines turísticos: los fija un decreto cada año; se cargan a mano cuando se publican
  const PUENTES = { 2026: ['2026-03-23', '2026-07-10', '2026-12-07'] };
  const cache = {};
  function feriados(anio) {
    if (cache[anio]) return cache[anio];
    const p = pascua(anio), f = (m, d) => new Date(Date.UTC(anio, m - 1, d, 12));
    const fijos = [f(1, 1), f(3, 24), f(4, 2), f(5, 1), f(5, 25), f(6, 20), f(7, 9), f(12, 8), f(12, 25)];
    const movibles = [f(6, 17), f(8, 17), f(10, 12), f(11, 20)].map(trasladar);
    const religiosos = [mas(p, -48), mas(p, -47), mas(p, -2)];               // lunes y martes de carnaval, Viernes Santo
    return (cache[anio] = new Set([...fijos, ...movibles, ...religiosos].map(iso).concat(PUENTES[anio] || [])));
  }
  function esHabil(s) {
    const d = dia(s), sem = d.getUTCDay();
    return sem !== 0 && sem !== 6 && !feriados(d.getUTCFullYear()).has(s);
  }
  // fecha en que se cumple el día hábil número n, contando desde el día siguiente a la presentación
  function sumarHabiles(desde, n) {
    let d = dia(desde), k = 0;
    while (k < n) { d = mas(d, 1); if (esHabil(iso(d))) k++; }
    return iso(d);
  }
  // días hábiles que faltan desde hoy hasta una fecha (negativo si ya pasó)
  function habilesHasta(hoy, hasta) {
    if (hoy === hasta) return 0;
    const signo = hoy < hasta ? 1 : -1;
    let d = dia(signo > 0 ? hoy : hasta), fin = signo > 0 ? hasta : hoy, n = 0;
    while (iso(d) < fin) { d = mas(d, 1); if (esHabil(iso(d))) n++; }
    return signo * n;
  }
  // plazo en números a partir del marco legal del organismo (o del texto, si todavía no trae los números)
  function plazoDe(marco) {
    const m = marco || {};
    if (typeof m.dias === 'number') return { dias: m.dias, prorroga: m.prorroga || 0, referencia: !!m.plazo_referencia, diceHabiles: m.dias_dice_habiles !== false };
    const a = /^(\d+) días( hábiles)?(?:[^,]*, prorrogables (?:una sola vez )?por (?:otros )?(\d+))?/.exec(m.plazo || '');
    return a ? { dias: +a[1], prorroga: +(a[3] || 0), referencia: false, diceHabiles: !!a[2] } : { dias: 15, prorroga: 0, referencia: true, diceHabiles: true };
  }
  /* Estado de un pedido. pedido = { fecha, prorroga?: true, pronto?: 'AAAA-MM-DD', respondido?: true }
     Devuelve { estado, vence, faltan, paso, texto } — estados: respondido · en_plazo · por_vencer · vencido · pronto_despacho · pronto_vencido */
  function estadoPedido(pedido, marco, hoy) {
    const pl = plazoDe(marco), total = pl.dias + (pedido.prorroga ? pl.prorroga : 0);
    const vence = sumarHabiles(pedido.fecha, total), faltan = habilesHasta(hoy, vence);
    const base = { vence, faltan, plazo: pl, total };
    if (pedido.respondido) return { ...base, estado: 'respondido', paso: 0, texto: 'Respondido' };
    if (pedido.pronto) {
      const v2 = sumarHabiles(pedido.pronto, 10), f2 = habilesHasta(hoy, v2);     // 10 días hábiles como espera razonable
      return f2 >= 0 ? { ...base, estado: 'pronto_despacho', vence2: v2, faltan2: f2, paso: 5, texto: 'Pronto despacho presentado' }
        : { ...base, estado: 'pronto_vencido', vence2: v2, faltan2: f2, paso: 6, texto: 'Sin respuesta al pronto despacho' };
    }
    if (faltan < 0) return { ...base, estado: 'vencido', paso: 4, texto: 'Plazo vencido sin respuesta' };
    if (faltan <= 3) return { ...base, estado: 'por_vencer', paso: 3, texto: 'Por vencer' };
    return { ...base, estado: 'en_plazo', paso: pedido.prorroga ? 3 : 2, texto: pedido.prorroga ? 'En plazo (con prórroga)' : 'En plazo' };
  }
  const api = { feriados, esHabil, sumarHabiles, habilesHasta, plazoDe, estadoPedido, pascua: a => iso(pascua(a)) };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else raiz.Plazos = api;
})(typeof window !== 'undefined' ? window : globalThis);
