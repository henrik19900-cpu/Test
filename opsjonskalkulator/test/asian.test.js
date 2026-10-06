// Asiatiske opsjoner: bokas eksempler, Monte Carlo og identiteter.
//
// MC-motoren simulerer ln S i gitte tidspunkter og bruker det geometriske gjennomsnittet med de samme
// vektene som kontrollvariat (dets forventning er eksakt lognormal), så standardfeilen blir liten nok
// til å måle feilen i de analytiske tilnærmingene. Kontinuerlig gjennomsnitt tilnærmes med
// trapesregelen på et fint gitter; for geometrisk gjennomsnitt er diskretiseringsfeilen < 1e-6.
//
// Målte avvik (formel − MC) under utviklingen, som testene under dokumenterer:
//   Turnbull–Wakeman = Levy (kontinuerlig): +0,007 (0,17 %) ved σ = 0,2; +0,16 (1,3 %) ved σ = 0,5 for ATM call;
//     −0,0002 (0,2 %) i Levys eksempel med σ = 0,14. Tilnærmingen overprises ved høy volatilitet.
//   Curran (diskret): under 0,004 (≈ 0,05 %) i alle tilfellene, også ved σ = 0,5.
//   Momenttilpasning HHM (diskret): +0,03 til +0,05 (0,4–0,6 %).
import test from 'node:test';
import assert from 'node:assert/strict';
import { close, withinMC } from './helpers.js';
import { createRng } from '../src/math/rng.js';
import { cnd } from '../src/math/normal.js';
import { gbsm } from '../src/models/bsm.js';
import {
  geometricAverage, turnbullWakeman, levy, curran, discreteArithmeticAverage, continuousAverageMoments,
  discreteAverageMoments,
} from '../src/models/asian.js';

// Eksakt pris på opsjon på G = exp(Σ w_j ln S_{t_j}).
function geometricWeighted(type, S, X, times, w, r, b, v, T) {
  let m = Math.log(S);
  let tail = w.reduce((a, x) => a + x, 0);
  let prefix = 0;
  let acc = 0;
  for (let j = 0; j < times.length; j++) {
    m += w[j] * (b - 0.5 * v * v) * times[j];
    prefix += w[j] * times[j];
    tail -= w[j];
    acc += w[j] * (prefix + times[j] * tail); // Σ_k w_k min(t_j, t_k)
  }
  const s2 = v * v * acc;
  const s = Math.sqrt(s2);
  const df = Math.exp(-r * T);
  const d1 = (m - Math.log(X) + s2) / s;
  const c = df * (Math.exp(m + 0.5 * s2) * cnd(d1) - X * cnd(d1 - s));
  return type === 'call' ? c : c - df * (Math.exp(m + 0.5 * s2) - X);
}

// Opsjon på known + weight·A, der A = Σ w_j S_{t_j}; antitetiske par og geometrisk kontrollvariat
// (A erstattet med G i payoffen, eksakt forventning når known = 0 og weight = 1).
function mcAverage({ type, S, X, T, r, b, v, times, w, known = 0, weight = 1, n = 40000, seed = 1, control = true }) {
  const rng = createRng(seed);
  const useCv = control && known === 0 && weight === 1;
  const cv = useCv ? geometricWeighted(type, S, X, times, w, r, b, v, T) : 0;
  const pay = (a) => Math.max(type === 'call' ? known + weight * a - X : X - known - weight * a, 0);
  const lnS = Math.log(S);
  let sum = 0;
  let sumSq = 0;
  const pairs = Math.floor(n / 2);
  for (let p = 0; p < pairs; p++) {
    let x1 = lnS;
    let x2 = lnS;
    let t = 0;
    let a1 = 0;
    let a2 = 0;
    let g1 = 0;
    let g2 = 0;
    for (let j = 0; j < times.length; j++) {
      const dt = times[j] - t;
      t = times[j];
      const z = rng.normal();
      const mu = (b - 0.5 * v * v) * dt;
      const sd = v * Math.sqrt(dt);
      x1 += mu + sd * z;
      x2 += mu - sd * z;
      a1 += w[j] * Math.exp(x1);
      a2 += w[j] * Math.exp(x2);
      g1 += w[j] * x1;
      g2 += w[j] * x2;
    }
    let y = 0.5 * (pay(a1) + pay(a2));
    if (useCv) y -= 0.5 * (pay(Math.exp(g1)) + pay(Math.exp(g2)));
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / pairs;
  const df = Math.exp(-r * T);
  return { mean: mean * df + cv, se: Math.sqrt(Math.max(sumSq / pairs - mean * mean, 0) / pairs) * df };
}

// Trapesvekter for kontinuerlig gjennomsnitt over [t1, t2] med N intervaller.
function trapezoid(t1, t2, N) {
  const times = [];
  const w = [];
  for (let j = 0; j <= N; j++) {
    times.push(t1 + j * (t2 - t1) / N);
    w.push((j === 0 || j === N ? 0.5 : 1) / N);
  }
  return { times, w };
}

// Likt fordelte fikseringer t1, …, T (k stykker), som i Curran-/HHM-formlene.
function fixings(t1, T, k) {
  const dt = k > 1 ? (T - t1) / (k - 1) : 0;
  return { times: Array.from({ length: k }, (_, i) => (k > 1 ? t1 + i * dt : T)), w: Array(k).fill(1 / k) };
}

test('Bokas eksempler: geometrisk (Kemna-Vorst) og Levy', () => {
  close(geometricAverage({ type: 'put', S: 80, X: 85, T: 0.25, r: 0.05, b: 0.08, v: 0.2 }), 4.6922);
  close(levy({ type: 'call', S: 6.8, SA: 6.8, X: 6.9, T: 0.5, T2: 0.5, r: 0.07, b: -0.02, v: 0.14 }).price, 0.0944);
});

test('Geometrisk gjennomsnitt mot MC og diskret grense', () => {
  for (const p of [
    { type: 'put', S: 80, X: 85, T: 0.25, r: 0.05, b: 0.08, v: 0.2 },
    { type: 'call', S: 100, X: 95, T: 1, r: 0.03, b: -0.01, v: 0.45 },
  ]) {
    const { times, w } = trapezoid(0, p.T, 250);
    // Ren MC uten kontrollvariat: payoff på exp(trapes-integralet av ln S).
    const rng = createRng(5);
    const n = 100000;
    let sum = 0;
    let sumSq = 0;
    for (let i = 0; i < n; i++) {
      let x = Math.log(p.S);
      let lg = w[0] * x;
      for (let j = 1; j < times.length; j++) {
        const dt = times[j] - times[j - 1];
        x += (p.b - 0.5 * p.v * p.v) * dt + p.v * Math.sqrt(dt) * rng.normal();
        lg += w[j] * x;
      }
      const y = Math.max(p.type === 'call' ? Math.exp(lg) - p.X : p.X - Math.exp(lg), 0) * Math.exp(-p.r * p.T);
      sum += y;
      sumSq += y * y;
    }
    const mean = sum / n;
    withinMC({ mean, se: Math.sqrt((sumSq / n - mean * mean) / n) }, geometricAverage(p), 4, 0, `${p.type} MC`);
    // Tett diskret geometrisk gjennomsnitt konvergerer mot den kontinuerlige formelen.
    const fine = trapezoid(0, p.T, 5000);
    close(geometricWeighted(p.type, p.S, p.X, fine.times, fine.w, p.r, p.b, p.v, p.T), geometricAverage(p), 1e-6, `${p.type} grense`);
  }
});

test('Turnbull-Wakeman og Levy: identiteter', () => {
  const cases = [
    { S: 6.8, SA: 6.8, X: 6.9, T: 0.5, T2: 0.5, r: 0.07, b: -0.02, v: 0.14 },
    { S: 90, SA: 88, X: 95, T: 0.25, T2: 0.5, r: 0.07, b: 0.02, v: 0.25 },
    { S: 100, SA: 100, X: 100, T: 1, T2: 0.6, r: 0.05, b: 0, v: 0.3 },
  ];
  for (const p of cases) {
    for (const type of ['call', 'put']) {
      // To-moments lognormal tilnærming: Levy og TW er samme formel skrevet på to måter.
      close(levy({ type, ...p }).price, turnbullWakeman({ type, ...p }).price, 1e-10, `TW = Levy ${type} T2=${p.T2}`);
    }
    // Put-call-paritet: c − p = e^{−rT}(E[A] − X), der E[A] veier sammen kjent og forventet gjennomsnitt.
    const t1 = Math.max(p.T - p.T2, 0);
    const { M1 } = continuousAverageMoments(p.b, p.v, t1, p.T - t1);
    const wgt = Math.min(p.T / p.T2, 1);
    const EA = (1 - wgt) * p.SA + wgt * p.S * M1;
    close(turnbullWakeman({ type: 'call', ...p }).price - turnbullWakeman({ type: 'put', ...p }).price,
      Math.exp(-p.r * p.T) * (EA - p.X), 1e-10, `paritet T2=${p.T2}`);
  }
  // Med σ → 0 er gjennomsnittet deterministisk.
  const d = { S: 100, SA: 100, X: 95, T: 1, T2: 1, r: 0.05, b: 0.03, v: 1e-6 };
  const EA = 100 * Math.expm1(0.03) / 0.03;
  close(turnbullWakeman({ type: 'call', ...d }).price, Math.exp(-0.05) * (EA - 95), 1e-6);
  // Påbegynt periode der justert innløsningskurs blir negativ: callen innløses sikkert, putten er verdiløs.
  const deep = { S: 100, SA: 300, X: 100, T: 0.2, T2: 1, r: 0.05, b: 0.02, v: 0.3 };
  const { M1: m1 } = continuousAverageMoments(0.02, 0.3, 0, 0.2);
  close(turnbullWakeman({ type: 'call', ...deep }).price, Math.exp(-0.01) * (0.8 * 300 + 0.2 * 100 * m1 - 100), 1e-10);
  assert.equal(turnbullWakeman({ type: 'put', ...deep }).price, 0);
  close(levy({ type: 'call', ...deep }).price, turnbullWakeman({ type: 'call', ...deep }).price, 1e-10);
});

test('Turnbull-Wakeman/Levy mot MC (kontinuerlig gjennomsnitt, dokumentert avvik)', (t) => {
  const cases = [
    // [parametre, toleranse]: tilnærmingen er god for moderat volatilitet og svakere ved høy volatilitet.
    [{ type: 'call', S: 100, X: 100, T: 0.5, r: 0.05, b: 0.05, v: 0.2 }, 0.02],
    [{ type: 'call', S: 6.8, X: 6.9, T: 0.5, r: 0.07, b: -0.02, v: 0.14 }, 0.001],
    [{ type: 'call', S: 100, X: 100, T: 1, r: 0.05, b: 0.05, v: 0.5 }, 0.25],
    [{ type: 'put', S: 100, X: 105, T: 1, r: 0.05, b: 0, v: 0.5 }, 0.15],
  ];
  cases.forEach(([p, tol], k) => {
    const { times, w } = trapezoid(0, p.T, 200);
    const mc = mcAverage({ ...p, times, w, n: 20000, seed: 100 + k });
    const tw = turnbullWakeman({ ...p, SA: p.S, T2: p.T }).price;
    t.diagnostic(`TW #${k}: formel ${tw.toFixed(5)}, MC ${mc.mean.toFixed(5)} ± ${mc.se.toFixed(5)}, avvik ${(tw - mc.mean).toFixed(5)}`);
    assert.ok(mc.se < tol / 4, 'MC-en er presis nok til å måle avviket');
    close(tw, mc.mean, tol, `TW #${k}`);
  });
  // Ved σ = 0,5 overpriser tilnærmingen ATM-callen tydelig (kjent svakhet): avviket er > 0,1.
  const hv = { type: 'call', S: 100, X: 100, T: 1, r: 0.05, b: 0.05, v: 0.5 };
  const { times, w } = trapezoid(0, 1, 200);
  assert.ok(turnbullWakeman({ ...hv, T2: 1 }).price - mcAverage({ ...hv, times, w, n: 20000, seed: 102 }).mean > 0.1);
});

test('Turnbull-Wakeman med gjennomsnittsperiode som har startet eller ikke startet (MC)', () => {
  // Startet: 0,25 år igjen av en periode på 0,5 år, gjennomsnitt hittil 88.
  const p = { type: 'put', S: 90, SA: 88, X: 95, T: 0.25, T2: 0.5, r: 0.07, b: 0.02, v: 0.25 };
  const { times, w } = trapezoid(0, p.T, 200);
  const mc = mcAverage({ ...p, times, w, known: 0.5 * p.SA, weight: 0.5, n: 40000, seed: 7 });
  close(turnbullWakeman(p).price, mc.mean, 4 * mc.se + 0.01, 'startet');
  // Ikke startet: perioden er [0,4; 1].
  const q = { type: 'call', S: 100, SA: 100, X: 100, T: 1, T2: 0.6, r: 0.05, b: 0.02, v: 0.25 };
  const fut = trapezoid(0.4, 1, 200);
  const mc2 = mcAverage({ ...q, times: fut.times, w: fut.w, n: 20000, seed: 8 });
  close(turnbullWakeman(q).price, mc2.mean, 4 * mc2.se + 0.02, 'ikke startet');
});

test('Curran og momenttilpasning (HHM) mot MC med diskrete fikseringer (dokumentert avvik)', (t) => {
  const cases = [
    { type: 'call', S: 100, X: 100, T: 1, t1: 0.1, n: 10, r: 0.05, b: 0.05, v: 0.3 },
    { type: 'put', S: 100, X: 100, T: 1, t1: 0.1, n: 10, r: 0.05, b: 0.05, v: 0.3 },
    { type: 'call', S: 100, X: 110, T: 1, t1: 1 / 12, n: 12, r: 0.05, b: 0, v: 0.5 },
    { type: 'call', S: 100, X: 90, T: 1, t1: 1 / 52, n: 52, r: 0.05, b: 0.03, v: 0.2 },
  ];
  cases.forEach((p, k) => {
    const { times, w } = fixings(p.t1, p.T, p.n);
    const mc = mcAverage({ ...p, times, w, n: 40000, seed: 200 + k });
    const cu = curran(p).price;
    const hh = discreteArithmeticAverage(p).price;
    t.diagnostic(`#${k} ${p.type} σ=${p.v}: MC ${mc.mean.toFixed(5)} ± ${mc.se.toFixed(5)}, Curran ${(cu - mc.mean).toFixed(5)}, HHM ${(hh - mc.mean).toFixed(5)}`);
    close(cu, mc.mean, 0.01, `Curran #${k}`); // målt: |avvik| < 0,004
    close(hh, mc.mean, 0.012 * mc.mean, `HHM #${k}`); // målt: 0,4–0,6 %
  });
});

test('Diskret gjennomsnitt: påbegynt periode, spesialtilfeller og grenser', () => {
  // m = 4 av n = 10 fikseringer er gjort med snitt 104; 6 gjenstår fra t1 = 0,05 til T = 0,55.
  const p = { type: 'call', S: 100, SA: 104, X: 102, T: 0.55, t1: 0.05, n: 10, m: 4, r: 0.04, b: 0.01, v: 0.35 };
  const { times, w } = fixings(p.t1, p.T, 6);
  for (const type of ['call', 'put']) {
    const mc = mcAverage({ ...p, type, times, w, known: 0.4 * p.SA, weight: 0.6, n: 60000, seed: 300 });
    close(curran({ ...p, type }).price, mc.mean, 4 * mc.se + 0.01, `Curran påbegynt ${type}`);
    close(discreteArithmeticAverage({ ...p, type }).price, mc.mean, 4 * mc.se + 0.05, `HHM påbegynt ${type}`);
  }
  // Én fiksering (ved T): eksakt BSM for begge.
  const one = { S: 100, X: 97, T: 0.7, t1: 0.7, n: 1, r: 0.05, b: 0.02, v: 0.3 };
  for (const type of ['call', 'put']) {
    close(curran({ type, ...one }).price, gbsm({ type, S: 100, X: 97, T: 0.7, r: 0.05, b: 0.02, v: 0.3 }), 1e-10, `Curran n=1 ${type}`);
    close(discreteArithmeticAverage({ type, ...one }).price, gbsm({ type, S: 100, X: 97, T: 0.7, r: 0.05, b: 0.02, v: 0.3 }), 1e-10, `HHM n=1 ${type}`);
  }
  // Justert innløsningskurs ≤ 0: callen er sikker, putten verdiløs.
  const deep = { ...p, SA: 400 };
  const { EA } = discreteAverageMoments(p.S, times, p.b, p.v);
  close(curran(deep).price, Math.exp(-p.r * p.T) * (0.4 * 400 + 0.6 * EA - p.X), 1e-10);
  assert.equal(discreteArithmeticAverage({ ...deep, type: 'put' }).price, 0);
  // Mange fikseringer: momenttilpasningen nærmer seg Turnbull-Wakeman (samme metode, kontinuerlig).
  const many = { S: 100, X: 100, T: 1, r: 0.05, b: 0.03, v: 0.3 };
  const N = 20000;
  close(discreteArithmeticAverage({ type: 'call', ...many, t1: 1 / N, n: N }).price,
    turnbullWakeman({ type: 'call', ...many, T2: 1 }).price, 2e-3, 'HHM → TW');
  // Curran: put via paritet c − p = e^{−rT}(E[A] − X).
  const q = { S: 100, X: 105, T: 1, t1: 0.25, n: 4, r: 0.05, b: 0.03, v: 0.3 };
  const ea = discreteAverageMoments(100, fixings(0.25, 1, 4).times, 0.03, 0.3).EA;
  close(curran({ type: 'call', ...q }).price - curran({ type: 'put', ...q }).price, Math.exp(-0.05) * (ea - 105), 1e-10);
  assert.throws(() => curran({ type: 'call', ...q, m: 4 }));
});
