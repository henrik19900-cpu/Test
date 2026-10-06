// Kapittel 9: opsjoner på aksjer med diskrete utbytter.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  dividendSchedule, pvDividends, escrowedDividend, simpleVolAdjustment, haugHaugVol, bgsVol, bosVandermark,
  hhlEuropean, hhlAmericanCall, rollGeskeWhaley, blackPseudoAmerican, dividendTree,
} from '../src/models/dividends.js';
import { gbsm } from '../src/models/bsm.js';
import { adaptiveSimpson } from '../src/math/integrate.js';
import { close, withinMC, mcPaths } from './helpers.js';

const BASE = { S: 100, X: 100, T: 1, r: 0.06, v: 0.3 };
const ONE = [{ t: 0.5, D: 7 }];
const TWO = [{ t: 0.25, D: 4 }, { t: 0.75, D: 4 }];
const phi = (z) => Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI);

// Uavhengig nøstet integrasjon (adaptiv Simpson) over utbyttedatoene, med oppdeling ved knekken.
function nestedReference(type, { S, X, T, r, v }, divs, american = false) {
  const mu = r - 0.5 * v * v;
  const zero = (tau) => (type === 'call' ? 0 : X * Math.exp(-r * tau));
  function after(k, s, t) {
    // Verdi på tid t rett etter utbytte k − 1 (eller i dag) med kurs s.
    if (k === divs.length) return s > 0 ? gbsm({ type, S: s, X, T: T - t, r, b: r, v }) : zero(T - t);
    const { t: tk, D } = divs[k];
    const dt = tk - t;
    const sd = v * Math.sqrt(dt);
    const g = (z) => {
      const cum = s * Math.exp(mu * dt + sd * z);
      const cont = cum > D ? after(k + 1, cum - D, tk) : zero(T - tk);
      return (american ? Math.max(cum - X, cont) : cont) * phi(z);
    };
    // Knekk (utglattet hvis tid gjenstår) rundt kursen der opsjonen er i pengene etter utbyttet.
    const zk = (Math.log(X + D) - Math.log(s) - mu * dt) / sd;
    const pts = [-9, zk - 1, zk - 0.1, zk, zk + 0.1, zk + 1, 9].filter((x) => x >= -9 && x <= 9).sort((a, b) => a - b);
    let tot = 0;
    for (let i = 0; i < pts.length - 1; i++) tot += adaptiveSimpson(g, pts[i], pts[i + 1], { eps: divs.length > 1 ? 1e-7 : 1e-11, maxDepth: 30 });
    return Math.exp(-r * dt) * tot;
  }
  return after(0, S, 0);
}

// Monte Carlo i den faktiske modellen: utbyttet trekkes fra aksjekursen på utbyttedatoen.
// Stiene simuleres på et jevnt gitter der utbyttedatoene ligger på gitterpunkter.
function mcDividend(type, p, divs, steps, n = 200000, seed = 3) {
  const dt = p.T / steps;
  const idx = divs.map((d) => Math.round(d.t / dt));
  divs.forEach((d, i) => assert.ok(Math.abs(idx[i] * dt - d.t) < 1e-12, 'utbyttedato må ligge på gitteret'));
  return mcPaths({
    S: p.S, T: p.T, r: p.r, b: p.r, v: p.v, steps, n, seed,
    payoff: (path) => {
      let s = p.S;
      let k = 0;
      for (let j = 1; j <= steps; j++) {
        s *= path[j] / path[j - 1];
        while (k < divs.length && idx[k] === j) {
          s = Math.max(s - divs[k].D, 0);
          k++;
        }
      }
      return Math.max(type === 'call' ? s - p.X : p.X - s, 0);
    },
  });
}

test('Utbytteplan: validering, sortering og sammenslåing', () => {
  assert.deepEqual(dividendSchedule({ tD: [0.75, 0.25, 0.25, 2], D: [3, 1, 2, 5], T: 1 }), [{ t: 0.25, D: 3 }, { t: 0.75, D: 3 }]);
  assert.throws(() => dividendSchedule({ tD: [0.5], D: [1, 2], T: 1 }), /like mange/);
  assert.throws(() => dividendSchedule({ tD: [-0.1], D: [1], T: 1 }), /etter i dag/);
  assert.throws(() => dividendSchedule({ tD: [0.5], D: [-1], T: 1 }), /negative/);
  close(pvDividends(TWO, 0.06), 4 * Math.exp(-0.015) + 4 * Math.exp(-0.045), 1e-14);
});

test('Escrowed dividend-modellen er GBSM med S − PV(D)', () => {
  for (const type of ['call', 'put']) {
    const pv = pvDividends(TWO, BASE.r);
    close(escrowedDividend({ ...BASE, type, divs: TWO }).price, gbsm({ ...BASE, type, S: BASE.S - pv, b: BASE.r }), 1e-14);
  }
  assert.throws(() => escrowedDividend({ ...BASE, type: 'call', divs: [{ t: 0.5, D: 150 }] }), /Nåverdien/);
});

test('HHL europeisk: mot uavhengig nøstet integrasjon', () => {
  for (const divs of [ONE, TWO, [{ t: 0.05, D: 5 }], [{ t: 0.98, D: 5 }]]) {
    for (const type of ['call', 'put']) {
      for (const X of [80, 100, 125]) {
        const p = { ...BASE, X, type };
        const ref = nestedReference(type, p, divs);
        close(hhlEuropean({ ...p, divs }).price, ref, divs.length > 1 ? 2e-5 : 1e-7, `${type} X=${X} ${JSON.stringify(divs)}`);
      }
    }
  }
});

test('HHL europeisk: mot Monte Carlo med utbytte trukket fra på utbyttedatoen', () => {
  const cases = [
    [ONE, 4, BASE],
    [TWO, 4, BASE],
    [[{ t: 0.2, D: 2 }, { t: 0.4, D: 2 }, { t: 0.6, D: 2 }, { t: 0.8, D: 2 }], 5, BASE],
    [[{ t: 0.5, D: 30 }], 2, { ...BASE, v: 0.6 }],
  ];
  for (const [divs, steps, p] of cases) {
    for (const type of ['call', 'put']) {
      const est = mcDividend(type, p, divs, steps);
      withinMC(est, hhlEuropean({ ...p, type, divs }).price, 4, 0, `${type} ${JSON.stringify(divs)}`);
    }
  }
});

test('HHL europeisk: paritet og grensetilfeller', () => {
  for (const divs of [ONE, TWO]) {
    const c = hhlEuropean({ ...BASE, type: 'call', divs }).price;
    const p = hhlEuropean({ ...BASE, type: 'put', divs }).price;
    close(c - p, BASE.S - pvDividends(divs, BASE.r) - BASE.X * Math.exp(-BASE.r * BASE.T), 1e-7, 'put-call-paritet');
  }
  for (const type of ['call', 'put']) {
    // Ingen utbytter: GBSM.
    close(hhlEuropean({ ...BASE, type, divs: [] }).price, gbsm({ ...BASE, type, b: BASE.r }), 1e-14);
    // Utbytte rett etter i dag: escrowed-modellen er da eksakt.
    const early = [{ t: 1e-6, D: 5 }];
    close(hhlEuropean({ ...BASE, type, divs: early }).price, escrowedDividend({ ...BASE, type, divs: early }).price, 1e-4, `tidlig ${type}`);
    // Utbytte rett før forfall: som GBSM med innløsningskurs X + D.
    const late = [{ t: 1 - 1e-6, D: 5 }];
    close(hhlEuropean({ ...BASE, type, divs: late }).price, gbsm({ ...BASE, type, X: BASE.X + 5, b: BASE.r }), 1e-4, `sent ${type}`);
  }
});

test('Volatilitetsjusteringer og Bos-Vandermark mot eksakt HHL', () => {
  for (const divs of [ONE, TWO, [{ t: 0.1, D: 3 }], [{ t: 0.9, D: 5 }]]) {
    for (const type of ['call', 'put']) {
      for (const X of [70, 100, 130]) {
        const q = { ...BASE, X, type, divs };
        const exact = hhlEuropean(q).price;
        const tag = `${type} X=${X} ${JSON.stringify(divs)}`;
        close(bgsVol(q).price, exact, 2e-3, `BGS ${tag}`);
        close(bosVandermark(q).price, exact, 0.03, `Bos-Vandermark ${tag}`);
        close(haugHaugVol(q).price, exact, 0.05, `Haug-Haug ${tag}`);
        // Escrowed-modellen undervurderer både call og put.
        assert.ok(escrowedDividend(q).price < exact, `escrowed ${tag}`);
      }
    }
  }
  // Uten utbytter gir alle GBSM.
  for (const fn of [escrowedDividend, simpleVolAdjustment, haugHaugVol, bgsVol, bosVandermark]) {
    close(fn({ ...BASE, type: 'call', divs: [] }).price, gbsm({ ...BASE, type: 'call', b: BASE.r }), 1e-14, fn.name);
  }
  // Ett utbytte: Haug-Haug-variansen er tidsvektet mellom σ·S/(S − PV) og σ.
  const hh = haugHaugVol({ ...BASE, type: 'call', divs: ONE });
  const s1 = BASE.v * BASE.S / (BASE.S - 7 * Math.exp(-0.03));
  close(hh.vAdj ** 2, 0.5 * s1 * s1 + 0.5 * BASE.v * BASE.v, 1e-14);
});

test('HHL amerikansk call: mot uavhengig integrasjon, binomialtre og europeisk verdi', () => {
  for (const X of [80, 100, 120]) {
    const p = { ...BASE, X };
    const am = hhlAmericanCall({ ...p, divs: ONE });
    close(am.price, nestedReference('call', p, ONE, true), 1e-6, `ett utbytte X=${X}`);
    assert.ok(am.price >= hhlEuropean({ ...p, type: 'call', divs: ONE }).price - 1e-12);
    for (const divs of [ONE, TWO]) {
      const tree = dividendTree({ ...p, type: 'call', exercise: 'american', divs, n: 2000 }).price;
      close(hhlAmericanCall({ ...p, divs }).price, tree, 5e-3, `tre X=${X} ${JSON.stringify(divs)}`);
    }
  }
  // Lite utbytte: tidlig innløsning lønner seg aldri, og verdien er den europeiske.
  const small = [{ t: 0.5, D: 0.5 }];
  const res = hhlAmericanCall({ ...BASE, divs: small });
  assert.ok(!Number.isFinite(res.critical[0]));
  close(res.price, hhlEuropean({ ...BASE, type: 'call', divs: small }).price, 1e-12);
  // Kritisk kurs: rett over den er innløsning verdt mer enn å beholde opsjonen.
  const crit = hhlAmericanCall({ ...BASE, divs: ONE }).critical[0];
  const tau = BASE.T - 0.5;
  close(crit - BASE.X, gbsm({ type: 'call', S: crit - 7, X: BASE.X, T: tau, r: BASE.r, b: BASE.r, v: BASE.v }), 1e-8, 'verdimatching');
});

test('Roll-Geske-Whaley: bokas eksempel, escrowed-integral og escrowed-tre', () => {
  const ex = { S: 80, X: 82, t1: 0.25, T: 1 / 3, r: 0.06, D: 4, v: 0.3 };
  close(rollGeskeWhaley(ex).price, 4.386, 1e-4, 'bokas eksempel');
  for (const p of [ex, { ...ex, X: 75 }, { ...ex, D: 2, T: 0.5 }, { S: 100, X: 100, t1: 0.5, T: 1, r: 0.06, D: 7, v: 0.3 }]) {
    const res = rollGeskeWhaley(p);
    // Escrowed-modellen: S* = S − D e^{−rt} er lognormal; innløsning rett før utbyttet gir S*_t + D − X.
    const Sx = p.S - p.D * Math.exp(-p.r * p.t1);
    const mu = p.r - 0.5 * p.v * p.v;
    const sd = p.v * Math.sqrt(p.t1);
    const g = (z) => {
      const s = Sx * Math.exp(mu * p.t1 + sd * z);
      return Math.max(s + p.D - p.X, gbsm({ type: 'call', S: s, X: p.X, T: p.T - p.t1, r: p.r, b: p.r, v: p.v })) * phi(z);
    };
    const zI = Number.isFinite(res.critical) ? (Math.log(res.critical - p.D) - Math.log(Sx) - mu * p.t1) / sd : 9;
    const integral = Math.exp(-p.r * p.t1) * (adaptiveSimpson(g, -10, zI, { eps: 1e-12 }) + adaptiveSimpson(g, zI, 10, { eps: 1e-12 }));
    close(res.price, integral, 1e-8, `integral ${JSON.stringify(p)}`);
    const tree = dividendTree({ type: 'call', exercise: 'american', S: p.S, X: p.X, T: p.T, r: p.r, v: p.v, divs: [{ t: p.t1, D: p.D }], n: 2000, model: 'escrowed' }).price;
    close(res.price, tree, 3e-3, `escrowed-tre ${JSON.stringify(p)}`);
  }
  // Lite utbytte: ingen tidlig innløsning, verdien er GBSM med S − PV(D).
  const small = { ...ex, D: 0.1 };
  const res = rollGeskeWhaley(small);
  assert.equal(res.earlyExercise, false);
  close(res.price, gbsm({ type: 'call', S: 80 - 0.1 * Math.exp(-0.015), X: 82, T: 1 / 3, r: 0.06, b: 0.06, v: 0.3 }), 1e-14);
});

test('Blacks tilnærming er maks av de europeiske kandidatene', () => {
  const p = { S: 80, X: 82, T: 1 / 3, r: 0.06, v: 0.3, divs: [{ t: 0.25, D: 4 }] };
  const res = blackPseudoAmerican(p);
  const atT = gbsm({ type: 'call', S: 80 - 4 * Math.exp(-0.015), X: 82, T: 1 / 3, r: 0.06, b: 0.06, v: 0.3 });
  const beforeDiv = gbsm({ type: 'call', S: 80, X: 82, T: 0.25, r: 0.06, b: 0.06, v: 0.3 });
  close(res.price, Math.max(atT, beforeDiv), 1e-14);
  assert.equal(res.bestDividend, beforeDiv > atT ? 1 : 0);
  // To utbytter: kandidaten før utbytte nr. 2 bruker S minus nåverdien av utbytte nr. 1.
  const two = blackPseudoAmerican({ ...BASE, divs: TWO });
  close(two.candidates[1].price, gbsm({ type: 'call', S: 100 - 4 * Math.exp(-0.015), X: 100, T: 0.75, r: 0.06, b: 0.06, v: 0.3 }), 1e-14);
  assert.ok(two.price >= escrowedDividend({ ...BASE, type: 'call', divs: TWO }).price);
});

// Ikke-rekombinerende CRR-tre for én dividende (uavhengig kontroll av interpolasjonstreet).
function nonRecombiningTree({ type, S, X, T, r, v, t1, D, n }) {
  const dt = T / n;
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp(r * dt) - d) / (u - d);
  const df = Math.exp(-r * dt);
  const z = type === 'call' ? 1 : -1;
  const m = Math.round(t1 / dt);
  const sub = (s0, steps) => {
    if (!(s0 > 0)) return type === 'call' ? 0 : X;
    const V = new Float64Array(steps + 1);
    for (let i = 0; i <= steps; i++) V[i] = Math.max(z * (s0 * u ** (2 * i - steps) - X), 0);
    for (let j = steps - 1; j >= 0; j--) {
      for (let i = 0; i <= j; i++) V[i] = Math.max(df * (p * V[i + 1] + (1 - p) * V[i]), z * (s0 * u ** (2 * i - j) - X));
    }
    return V[0];
  };
  const V = new Float64Array(m + 1);
  for (let i = 0; i <= m; i++) {
    const cum = S * u ** (2 * i - m);
    V[i] = Math.max(z * (cum - X), sub(cum - D, n - m));
  }
  for (let j = m - 1; j >= 0; j--) {
    for (let i = 0; i <= j; i++) V[i] = Math.max(df * (p * V[i + 1] + (1 - p) * V[i]), z * (S * u ** (2 * i - j) - X));
  }
  return V[0];
}

test('Binomialtre med diskrete utbytter', () => {
  // Europeisk, faktisk modell: mot eksakt HHL.
  for (const divs of [ONE, TWO, [{ t: 0.0004, D: 7 }]]) {
    for (const type of ['call', 'put']) {
      const tree = dividendTree({ ...BASE, type, exercise: 'european', divs, n: 1500 }).price;
      close(tree, hhlEuropean({ ...BASE, type, divs }).price, 3e-3, `europeisk ${type} ${JSON.stringify(divs)}`);
    }
  }
  // Europeisk, escrowed-modell: mot GBSM med S − PV(D).
  for (const type of ['call', 'put']) {
    close(dividendTree({ ...BASE, type, exercise: 'european', divs: TWO, n: 1500, model: 'escrowed' }).price,
      escrowedDividend({ ...BASE, type, divs: TWO }).price, 3e-3, `escrowed ${type}`);
  }
  // Amerikansk put, faktisk modell: mot ikke-rekombinerende tre. Begge har CRR-feil av orden 1/n
  // (≈ 3e-3 ved n = 600) med ulik konstant, så toleransen er 5e-3.
  for (const [X, D] of [[100, 7], [110, 3], [90, 10]]) {
    const p = { ...BASE, X, type: 'put' };
    const nr = nonRecombiningTree({ ...p, t1: 0.5, D, n: 600 });
    const tree = dividendTree({ ...p, exercise: 'american', divs: [{ t: 0.5, D }], n: 600 }).price;
    close(tree, nr, 5e-3, `amerikansk put X=${X} D=${D}`);
    assert.ok(tree >= dividendTree({ ...p, exercise: 'european', divs: [{ t: 0.5, D }], n: 600 }).price);
  }
  // Amerikansk call, faktisk modell: mot ikke-rekombinerende tre.
  const nrc = nonRecombiningTree({ ...BASE, type: 'call', t1: 0.5, D: 7, n: 600 });
  close(dividendTree({ ...BASE, type: 'call', exercise: 'american', divs: ONE, n: 600 }).price, nrc, 5e-3, 'amerikansk call');
});
