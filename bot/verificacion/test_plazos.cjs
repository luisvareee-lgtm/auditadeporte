const test = require('node:test'), assert = require('node:assert');
const P = require('../../plazos.js');

test('feriados nacionales 2026 (fijos, trasladados, carnaval y Semana Santa)', () => {
  const f = P.feriados(2026);
  for (const d of ['2026-01-01', '2026-02-16', '2026-02-17', '2026-03-24', '2026-04-02', '2026-04-03', '2026-05-01', '2026-05-25',
    '2026-06-15', '2026-06-20', '2026-07-09', '2026-08-17', '2026-10-12', '2026-11-23', '2026-12-08', '2026-12-25']) assert.ok(f.has(d), d);
  assert.ok(!f.has('2026-06-17') && !f.has('2026-11-20'));
  assert.equal(P.pascua(2027), '2027-03-28');
});
test('no cuenta fines de semana ni feriados', () => {
  assert.equal(P.esHabil('2026-11-21'), false);          // sábado
  assert.equal(P.esHabil('2026-11-23'), false);          // feriado trasladado
  assert.equal(P.esHabil('2026-11-24'), true);
  assert.equal(P.sumarHabiles('2026-11-19', 1), '2026-11-20');
  assert.equal(P.sumarHabiles('2026-11-20', 1), '2026-11-24');   // salta sábado, domingo y lunes feriado
  assert.equal(P.sumarHabiles('2026-11-02', 15), '2026-11-24');
});
test('días que faltan, hacia adelante y hacia atrás', () => {
  assert.equal(P.habilesHasta('2026-11-09', '2026-11-13'), 4);
  assert.equal(P.habilesHasta('2026-11-13', '2026-11-09'), -4);
  assert.equal(P.habilesHasta('2026-11-09', '2026-11-09'), 0);
});
test('plazo desde el marco legal o desde su texto', () => {
  assert.deepEqual(P.plazoDe({ dias: 10, prorroga: 15 }), { dias: 10, prorroga: 15, referencia: false, diceHabiles: true });
  assert.equal(P.plazoDe({ plazo: '15 días hábiles, prorrogables por otros 15' }).prorroga, 15);
  assert.equal(P.plazoDe({ plazo: '8 días, prorrogables por 10' }).diceHabiles, false);
  assert.equal(P.plazoDe({ plazo: '10 días hábiles administrativos, prorrogables una sola vez por 10 más' }).prorroga, 10);
  assert.equal(P.plazoDe({ plazo: 'el que fije la ordenanza; si no hay, un plazo razonable' }).referencia, true);
  assert.equal(P.plazoDe(null).dias, 15);
});
test('estados del pedido', () => {
  const m = { dias: 15, prorroga: 15 }, p = { fecha: '2026-11-02' };
  assert.equal(P.estadoPedido(p, m, '2026-11-05').estado, 'en_plazo');
  assert.equal(P.estadoPedido(p, m, '2026-11-20').estado, 'por_vencer');
  assert.equal(P.estadoPedido(p, m, '2026-11-24').faltan, 0);
  assert.equal(P.estadoPedido(p, m, '2026-11-25').estado, 'vencido');
  assert.equal(P.estadoPedido({ ...p, prorroga: true }, m, '2026-11-25').estado, 'en_plazo');
  assert.equal(P.estadoPedido({ ...p, pronto: '2026-11-26' }, m, '2026-11-27').estado, 'pronto_despacho');
  assert.equal(P.estadoPedido({ ...p, pronto: '2026-11-26' }, m, '2027-01-15').estado, 'pronto_vencido');
  assert.equal(P.estadoPedido({ ...p, respondido: true }, m, '2027-01-15').estado, 'respondido');
});
