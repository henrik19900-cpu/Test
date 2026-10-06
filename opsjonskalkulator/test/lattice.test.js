// Kapittel 7: binomial- og trinomialtrær, tredimensjonalt tre, implisitt tre og finite difference.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  crrTree, binomialTree, trinomialTree, threeDimTree, dermanKaniTree, buildDermanKani, crrEuropeanSum,
  margrabe, stulzMinMax, twoAssetPayoff, linearSkewVol,
} from '../src/models/lattice.js';
import { finiteDifference } from '../src/models/finite-difference.js';
import { bawAmerican, bsAmerican2002 } from '../src/models/american.js';
import { gbsm, gbsmGreeks } from '../src/models/bsm.js';
import { close, withinMC, mcTwoAssets } from './helpers.js';

const CASES = [
  { type: 'call', S: 100, X: 95, T: 0.5, r: 0.08, b: 0.08, v: 0.3 },
  { type: 'put', S: 100, X: 105, T: 0.75, r: 0.06, b: 0.02, v: 0.3 },
  { type: 'call', S: 110, X: 100, T: 1, r: 0.05, b: -0.03, v: 0.2 },
  { type: 'put', S: 90, X: 100, T: 0.25, r: 0.1, b: 0, v: 0.4 },
];

test('CRR: europeisk pris og Greeks fra treet konvergerer mot GBSM', () => {
  for (const p of CASES) {
    const g = gbsmGreeks(p);
    const coarse = crrTree({ ...p, exercise: 'european', n: 200 });
    const fine = crrTree({ ...p, exercise: 'european', n: 2000 });
    const tag = `${p.type} S=${p.S} X=${p.X}`;
    close(fine.price, g.price, 4e-3, `pris ${tag}`);
    assert.ok(Math.abs(fine.price - g.price) < Math.abs(coarse.price - g.price) + 1e-4, `konvergens ${tag}`);
    close(fine.delta, g.delta, 1e-3, `delta ${tag}`);
    close(fine.gamma, g.gamma, 2e-4, `gamma ${tag}`);
    close(fine.theta, g.theta, 0.02, `theta ${tag}`);
  }
});

test('Leisen-Reimer og Rendleman-Bartter mot GBSM', () => {
  for (const p of CASES) {
    const g = gbsmGreeks(p);
    const lr = binomialTree({ ...p, method: 'lr', exercise: 'european', n: 301 });
    close(lr.price, g.price, 2e-5, `LR pris ${p.type} X=${p.X}`);
    close(lr.delta, g.delta, 5e-4, `LR delta ${p.type} X=${p.X}`);
    assert.equal(binomialTree({ ...p, method: 'lr', exercise: 'european', n: 300 }).steps, 301);
    const rb = binomialTree({ ...p, method: 'rb', exercise: 'european', n: 2000 });
    close(rb.price, g.price, 5e-3, `RB pris ${p.type} X=${p.X}`);
  }
});

test('Trinomialtre (Boyle): europeisk pris og Greeks mot GBSM', () => {
  for (const p of CASES) {
    const g = gbsmGreeks(p);
    const t = trinomialTree({ ...p, exercise: 'european', n: 1000 });
    const tag = `${p.type} X=${p.X}`;
    close(t.price, g.price, 3e-3, `pris ${tag}`);
    close(t.delta, g.delta, 1e-3, `delta ${tag}`);
    close(t.gamma, g.gamma, 2e-4, `gamma ${tag}`);
    close(t.theta, g.theta, 0.03, `theta ${tag}`);
    close(t.pu + t.pm + t.pd, 1, 1e-14);
  }
});

test('Finite difference: europeisk pris og Greeks mot GBSM', () => {
  for (const p of CASES) {
    const g = gbsmGreeks(p);
    const tag = `${p.type} X=${p.X}`;
    const cn = finiteDifference({ ...p, method: 'cn', exercise: 'european', M: 400, N: 400 });
    close(cn.price, g.price, 5e-4, `CN pris ${tag}`);
    close(cn.delta, g.delta, 2e-4, `CN delta ${tag}`);
    close(cn.gamma, g.gamma, 5e-5, `CN gamma ${tag}`);
    close(cn.theta, g.theta, 0.02, `CN theta ${tag}`);
    const ex = finiteDifference({ ...p, method: 'explicit', exercise: 'european', M: 400, N: 10 });
    assert.ok(ex.steps > 10, 'eksplisitt metode skal øke antall tidssteg');
    close(ex.price, g.price, 1e-3, `eksplisitt pris ${tag}`);
    const im = finiteDifference({ ...p, method: 'implicit', exercise: 'european', M: 400, N: 2000 });
    close(im.price, g.price, 1e-3, `implisitt pris ${tag}`);
  }
});

test('Amerikanske verdier: CRR, trinomialtre og alle FD-metodene stemmer overens', () => {
  for (const p of CASES) {
    const tag = `${p.type} S=${p.S} X=${p.X} b=${p.b}`;
    const ref = 0.5 * (crrTree({ ...p, n: 3000 }).price + crrTree({ ...p, n: 3001 }).price);
    close(trinomialTree({ ...p, n: 1500 }).price, ref, 1.5e-3, `trinomial ${tag}`);
    close(binomialTree({ ...p, method: 'lr', n: 1001 }).price, ref, 1.5e-3, `Leisen-Reimer ${tag}`);
    close(finiteDifference({ ...p, method: 'cn', M: 800, N: 800 }).price, ref, 1e-3, `CN ${tag}`);
    close(finiteDifference({ ...p, method: 'explicit', M: 600, N: 100 }).price, ref, 1.5e-3, `eksplisitt ${tag}`);
    close(finiteDifference({ ...p, method: 'implicit', M: 800, N: 3000 }).price, ref, 2e-3, `implisitt ${tag}`);
    // Mot de analytiske tilnærmingene i kapittel 3 (grovere, se american.test.js for detaljer).
    close(bawAmerican(p).price, ref, 0.06, `BAW ${tag}`);
    close(bsAmerican2002(p).price, ref, 0.06, `BS 2002 ${tag}`);
    // Amerikansk ≥ europeisk, og ≥ innløsningsverdien.
    const eu = 0.5 * (crrTree({ ...p, exercise: 'european', n: 3000 }).price + crrTree({ ...p, exercise: 'european', n: 3001 }).price);
    assert.ok(ref >= eu - 1e-9 && ref >= Math.max(p.type === 'call' ? p.S - p.X : p.X - p.S, 0), tag);
  }
  // Call uten tidlig innløsning (b ≥ r): amerikansk = europeisk i treet og i PDE-en.
  const c = { type: 'call', S: 100, X: 100, T: 1, r: 0.05, b: 0.05, v: 0.25 };
  close(crrTree({ ...c, n: 500 }).price, crrTree({ ...c, exercise: 'european', n: 500 }).price, 1e-12);
  close(finiteDifference({ ...c, method: 'cn' }).price, finiteDifference({ ...c, method: 'cn', exercise: 'european' }).price, 1e-9);
});

test('Finite difference: put-call-paritet og amerikansk put over innløsningsverdien', () => {
  const p = { S: 100, X: 100, T: 1, r: 0.05, b: 0.01, v: 0.25 };
  const c = finiteDifference({ ...p, type: 'call', method: 'cn', exercise: 'european', M: 600, N: 600 }).price;
  const put = finiteDifference({ ...p, type: 'put', method: 'cn', exercise: 'european', M: 600, N: 600 }).price;
  close(c - put, p.S * Math.exp((p.b - p.r) * p.T) - p.X * Math.exp(-p.r * p.T), 5e-4);
  for (const S of [60, 80, 100, 120]) {
    const am = finiteDifference({ ...p, S, type: 'put', method: 'implicit', M: 400, N: 400 }).price;
    assert.ok(am >= Math.max(p.X - S, 0) - 1e-12, `S=${S}`);
  }
});

// ---------------------------------------------------------------------------
// Tredimensjonalt tre
// ---------------------------------------------------------------------------

const TWO = { S1: 100, S2: 95, Q1: 1, Q2: 1, T: 0.75, r: 0.06, b1: 0.02, b2: 0.04, v1: 0.25, v2: 0.3, rho: 0.4 };

test('3D-tre: europeiske varianter mot lukkede formler', () => {
  const n = 200;
  // Bytteopsjon mot Margrabe.
  close(threeDimTree({ ...TWO, payoff: 'exchange', exercise: 'european', n }).price, margrabe(TWO), 3e-3, 'bytte');
  // Produkt og kvote er lognormale.
  const vp = Math.sqrt(TWO.v1 ** 2 + TWO.v2 ** 2 + 2 * TWO.rho * TWO.v1 * TWO.v2);
  const vq = Math.sqrt(TWO.v1 ** 2 + TWO.v2 ** 2 - 2 * TWO.rho * TWO.v1 * TWO.v2);
  for (const type of ['call', 'put']) {
    const prod = gbsm({ type, S: TWO.S1 * TWO.S2, X: 9500, T: TWO.T, r: TWO.r, b: TWO.b1 + TWO.b2 + TWO.rho * TWO.v1 * TWO.v2, v: vp });
    close(threeDimTree({ ...TWO, type, payoff: 'product', X1: 9500, exercise: 'european', n }).price, prod, 0.4, `produkt ${type}`);
    const quot = gbsm({ type, S: TWO.S1 / TWO.S2, X: 1, T: TWO.T, r: TWO.r, b: TWO.b1 - TWO.b2 + TWO.v2 ** 2 - TWO.rho * TWO.v1 * TWO.v2, v: vq });
    close(threeDimTree({ ...TWO, type, payoff: 'outperformance', X1: 1, exercise: 'european', n }).price, quot, 5e-4, `kvote ${type}`);
  }
  // Maks og min mot Stulz, og identiteten c_max + c_min = c(S1) + c(S2).
  for (const kind of ['max', 'min']) {
    for (const type of ['call', 'put']) {
      const tr = threeDimTree({ ...TWO, type, payoff: kind, X1: 100, exercise: 'european', n }).price;
      close(tr, stulzMinMax({ ...TWO, kind, type, X: 100 }), 6e-3, `${kind} ${type}`);
    }
  }
  const cmax = stulzMinMax({ ...TWO, kind: 'max', type: 'call', X: 100 });
  const cmin = stulzMinMax({ ...TWO, kind: 'min', type: 'call', X: 100 });
  const c1 = gbsm({ type: 'call', S: TWO.S1, X: 100, T: TWO.T, r: TWO.r, b: TWO.b1, v: TWO.v1 });
  const c2 = gbsm({ type: 'call', S: TWO.S2, X: 100, T: TWO.T, r: TWO.r, b: TWO.b2, v: TWO.v2 });
  close(cmax + cmin, c1 + c2, 1e-9, 'Stulz: maks + min');
});

test('3D-tre og Stulz mot Monte Carlo', () => {
  const mc = (f) => mcTwoAssets({ ...TWO, n: 300000, seed: 7, payoff: f });
  const n = 200;
  for (const [kind, X1, X2] of [['spread', 4, 0], ['dual', 105, 100], ['reverse', 105, 90], ['portfolio', 195, 0], ['max', 100, 0], ['min', 100, 0]]) {
    for (const type of ['call', 'put']) {
      const f = twoAssetPayoff(kind, type === 'call', { Q1: 1, Q2: 1, X1, X2 });
      const est = mc(f);
      const tr = threeDimTree({ ...TWO, type, payoff: kind, X1, X2, exercise: 'european', n }).price;
      // Treet har diskretiseringsfeil ~ 1e-2; MC-feilen er 4 standardfeil.
      withinMC(est, tr, 4, 0.012, `tre ${kind} ${type}`);
      if (kind === 'max' || kind === 'min') withinMC(est, stulzMinMax({ ...TWO, kind, type, X: X1 }), 4, 0, `Stulz ${kind} ${type}`);
    }
  }
});

test('3D-tre: amerikansk bytteopsjon = S1 × amerikansk call på kvoten S2/S1', () => {
  for (const p of [TWO, { ...TWO, Q2: 1.1, b1: -0.02, rho: -0.3 }]) {
    const tr = threeDimTree({ ...p, payoff: 'exchange', exercise: 'american', n: 250 }).price;
    const vq = Math.sqrt(p.v1 ** 2 + p.v2 ** 2 - 2 * p.rho * p.v1 * p.v2);
    const ratio = { type: 'call', exercise: 'american', S: p.Q2 * p.S2 / (p.Q1 * p.S1), X: 1, T: p.T, r: p.r - p.b1, b: p.b2 - p.b1, v: vq };
    const oneDim = p.Q1 * p.S1 * 0.5 * (crrTree({ ...ratio, n: 2000 }).price + crrTree({ ...ratio, n: 2001 }).price);
    close(tr, oneDim, 6e-3, JSON.stringify(p));
    assert.ok(tr >= threeDimTree({ ...p, payoff: 'exchange', exercise: 'european', n: 250 }).price - 1e-12);
  }
  // Amerikansk spread-call på futures (b = 0) ≥ europeisk.
  const sp = { S1: 122, S2: 120, X1: 3, T: 0.1, r: 0.1, b1: 0, b2: 0, v1: 0.2, v2: 0.2, rho: -0.5, payoff: 'spread', n: 100 };
  assert.ok(threeDimTree({ ...sp, exercise: 'american' }).price > threeDimTree({ ...sp, exercise: 'european' }).price);
});

// ---------------------------------------------------------------------------
// Implisitt tre (Derman-Kani)
// ---------------------------------------------------------------------------

test('Derman-Kani: flat volatilitet gir nøyaktig CRR-treet', () => {
  for (const n of [5, 6, 30]) {
    const p = { S: 100, X: 95, T: 2, r: 0.05, b: 0.03, v: 0.2, n, skew: 0 };
    for (const [type, exercise] of [['put', 'american'], ['call', 'european'], ['put', 'european']]) {
      const dk = dermanKaniTree({ ...p, type, exercise });
      close(dk.price, crrTree({ ...p, type, exercise }).price, 1e-10, `n=${n} ${type} ${exercise}`);
      assert.equal(dk.tree.overrides, 0);
    }
  }
});

test('Derman-Kani med skjevhet: Arrow-Debreu, termin, kalibrering og paritet', () => {
  const p = { S: 100, T: 1, r: 0.05, b: 0.03, v: 0.2, skew: -0.001, n: 31 };
  const tree = buildDermanKani(p);
  const dt = p.T / p.n;
  for (let i = 0; i <= p.n; i++) {
    // Arrow-Debreu-prisene summerer til diskonteringsfaktoren.
    const lam = i === p.n ? tree.lambda : null;
    if (lam) close(lam.reduce((a, x) => a + x, 0), Math.exp(-p.r * p.T), 1e-12, 'Arrow-Debreu');
  }
  for (let i = 0; i < p.n; i++) {
    tree.nodes[i].forEach((s, j) => {
      const pr = tree.probs[i][j];
      assert.ok(pr > 0 && pr < 1, `sannsynlighet nivå ${i}`);
      close(pr * tree.nodes[i + 1][j + 1] + (1 - pr) * tree.nodes[i + 1][j], s * Math.exp(p.b * dt), 1e-9, 'termin');
    });
  }
  // n odde: ATM-call ved T gjenskapes eksakt (CRR-pris med σ(S)).
  close(dermanKaniTree({ ...p, type: 'call', X: 100, exercise: 'european' }).price,
    crrEuropeanSum(true, 100, 100, p.n, dt, p.r, p.b, linearSkewVol(100, 100, p.v, p.skew)), 1e-9, 'ATM-kalibrering');
  // Put-call-paritet holder eksakt i et treet som treffer terminprisene.
  for (const X of [85, 100, 115]) {
    const c = dermanKaniTree({ ...p, type: 'call', X, exercise: 'european' }).price;
    const q = dermanKaniTree({ ...p, type: 'put', X, exercise: 'european' }).price;
    close(c - q, p.S * Math.exp((p.b - p.r) * p.T) - X * Math.exp(-p.r * p.T), 1e-9, `paritet X=${X}`);
    // Prisen ligger nær GBSM med σ(X) (skjevheten er priset inn).
    const target = gbsm({ type: 'call', S: p.S, X, T: p.T, r: p.r, b: p.b, v: linearSkewVol(X, p.S, p.v, p.skew) });
    close(c, target, 0.12, `skjevhet X=${X}`);
  }
  // Skjevheten gir høyere pris på OTM-put enn flat volatilitet.
  const flat = dermanKaniTree({ ...p, skew: 0, type: 'put', X: 85, exercise: 'european' }).price;
  const skewed = dermanKaniTree({ ...p, type: 'put', X: 85, exercise: 'european' }).price;
  assert.ok(skewed > flat + 0.1);
});
