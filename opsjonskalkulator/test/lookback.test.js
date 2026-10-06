// Lookback-opsjoner: bokas eksempel, Monte Carlo med eksakt kontinuerlig overvåking
// (ekstremverdien mellom to gitterpunkter trekkes fra fordelingen til maks/min av en brownsk bro),
// numerisk integrasjon og identiteter.
import test from 'node:test';
import assert from 'node:assert/strict';
import { close, withinMC } from './helpers.js';
import { createRng } from '../src/math/rng.js';
import { nd } from '../src/math/normal.js';
import { gaussLegendreComposite } from '../src/math/integrate.js';
import { gbsm } from '../src/models/bsm.js';
import {
  floatingStrikeLookback, fixedStrikeLookback, partialFloatingLookback, partialFixedLookback, extremeSpread,
  EXTREME_SPREAD_KINDS,
} from '../src/models/lookback.js';

// Simulerer ln S på gitteret `times` (starter i 0). For hvert steg k trekkes endepunktet og,
// gitt endepunktene, minimum og maksimum av broen (hver for seg eksakt fordelt).
// payoff(x, lo, hi) får Float64Array-er med ln S i gitterpunktene og ln min/ln maks per steg (indeks k ≥ 1).
function mcBridge({ S, r, b, v, times, n = 200000, seed = 1, payoff }) {
  const rng = createRng(seed);
  const K = times.length - 1;
  const x = new Float64Array(K + 1);
  const lo = new Float64Array(K + 1);
  const hi = new Float64Array(K + 1);
  const mu = b - 0.5 * v * v;
  let sum = 0;
  let sumSq = 0;
  for (let p = 0; p < n; p++) {
    x[0] = Math.log(S);
    for (let k = 1; k <= K; k++) {
      const dt = times[k] - times[k - 1];
      const var_ = v * v * dt;
      x[k] = x[k - 1] + mu * dt + Math.sqrt(var_) * rng.normal();
      const d = x[k] - x[k - 1];
      const ext1 = Math.sqrt(d * d - 2 * var_ * Math.log(rng.uniform()));
      const ext2 = Math.sqrt(d * d - 2 * var_ * Math.log(rng.uniform()));
      lo[k] = x[k - 1] + 0.5 * (d - ext1);
      hi[k] = x[k - 1] + 0.5 * (d + ext2);
    }
    const y = payoff(x, lo, hi);
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / n;
  const df = Math.exp(-r * times[K]);
  return { mean: mean * df, se: Math.sqrt(Math.max(sumSq / n - mean * mean, 0) / n) * df };
}

const E = Math.exp;

test('Bokas eksempel: flytende lookback call', () => {
  // S = 120, S_min = 100, T = 0,5, r = 10 %, utbytte 6 % (b = 0,04), σ = 30 % → 25,3533.
  close(floatingStrikeLookback({ type: 'call', S: 120, Smin: 100, T: 0.5, r: 0.1, b: 0.04, v: 0.3 }), 25.3533);
});

test('Flytende og fast lookback mot MC (eksakt kontinuerlig overvåking)', () => {
  const cases = [
    { S: 120, Smin: 100, Smax: 130, X: 125, T: 0.5, r: 0.1, b: 0.04, v: 0.3 },
    { S: 100, Smin: 100, Smax: 100, X: 95, T: 0.75, r: 0.05, b: 0, v: 0.25 },
    { S: 100, Smin: 97, Smax: 104, X: 102, T: 1, r: 0.03, b: -0.05, v: 0.4 },
  ];
  cases.forEach((p, k) => {
    const times = [0, p.T];
    const mc = (payoff, seed) => mcBridge({ ...p, times, n: 150000, seed, payoff });
    const mn = (x, lo) => Math.min(p.Smin, E(lo[1]));
    const mx = (x, lo, hi) => Math.max(p.Smax, E(hi[1]));
    withinMC(mc((x, lo) => E(x[1]) - mn(x, lo), 10 + k), floatingStrikeLookback({ type: 'call', ...p }), 4, 0, `flytende call #${k}`);
    withinMC(mc((x, lo, hi) => mx(x, lo, hi) - E(x[1]), 20 + k), floatingStrikeLookback({ type: 'put', ...p }), 4, 0, `flytende put #${k}`);
    for (const X of [p.X, 0.9 * p.Smin, 1.1 * p.Smax]) {
      withinMC(mc((x, lo, hi) => Math.max(mx(x, lo, hi) - X, 0), 30 + k), fixedStrikeLookback({ type: 'call', ...p, X }), 4, 0, `fast call X=${X} #${k}`);
      withinMC(mc((x, lo) => Math.max(X - mn(x, lo), 0), 40 + k), fixedStrikeLookback({ type: 'put', ...p, X }), 4, 0, `fast put X=${X} #${k}`);
    }
  });
});

test('Lookback-identiteter og b = 0', () => {
  const p = { S: 100, Smin: 92, Smax: 110, T: 0.8, r: 0.06, b: 0.02, v: 0.3 };
  const carry = p.S * E((p.b - p.r) * p.T);
  const df = E(-p.r * p.T);
  // Fast call med X ≤ S_max = flytende put + forward; fast put med X ≥ S_min = flytende call − forward.
  for (const X of [100, 110]) {
    close(fixedStrikeLookback({ type: 'call', ...p, X }), floatingStrikeLookback({ type: 'put', ...p }) + carry - X * df, 1e-10);
  }
  for (const X of [92, 105]) {
    close(fixedStrikeLookback({ type: 'put', ...p, X }), floatingStrikeLookback({ type: 'call', ...p }) - carry + X * df, 1e-10);
  }
  // b = 0 er en hevbar singularitet: verdien er glatt i b.
  for (const type of ['call', 'put']) {
    const at = (b) => floatingStrikeLookback({ type, ...p, b });
    close(at(0), 0.5 * (at(1e-4) + at(-1e-4)), 1e-6, `glatt i b = 0 (${type})`);
    close(at(5e-6), at(0) + 5e-6 * (at(1e-4) - at(-1e-4)) / 2e-4, 1e-8, `kontinuerlig nær 0 (${type})`);
  }
  // Spot under observert minimum oppdaterer minimum.
  close(floatingStrikeLookback({ type: 'call', ...p, S: 90 }), floatingStrikeLookback({ type: 'call', ...p, S: 90, Smin: 90 }), 1e-14);
  // Lookback er minst like mye verdt som en vanlig opsjon med innløsningskurs lik observert ekstremverdi.
  assert.ok(floatingStrikeLookback({ type: 'call', ...p }) > gbsm({ type: 'call', S: 100, X: 92, T: 0.8, r: 0.06, b: 0.02, v: 0.3 }));
});

// Referanse for delvis flytende lookback: e^{−r t1}·E[BSM(S_{t1}, λ·ekstrem, T − t1)], der ekstremverdien
// betinget på ln S_{t1} er minimum/maksimum av en brownsk bro (todimensjonal Gauss–Legendre).
function partialFloatingByIntegration({ type, S, Smin, Smax, lambda, t1, T, r, b, v }) {
  const tau = T - t1;
  const mu = (b - 0.5 * v * v) * t1;
  const q = v * Math.sqrt(t1);
  const V = q * q;
  const isCall = type === 'call';
  const e0 = isCall ? Math.log(Math.min(Smin, S) / S) : Math.log(Math.max(Smax, S) / S);
  const outer = (z) => {
    const x = mu + q * z;
    const St = S * E(x);
    const g = (y) => gbsm({ type, S: St, X: lambda * S * E(y), T: tau, r, b, v });
    // P(min ≤ y | x) = exp(−2y(y − x)/V) for y ≤ min(0, x); tilsvarende for maks.
    const tail = (y) => E(-2 * y * (y - x) / V);
    const dens = (y) => tail(y) * Math.abs(4 * y - 2 * x) / V;
    if (isCall) {
      const top = Math.min(e0, x);
      const mass = x >= e0 ? tail(e0) : 1;
      return nd(z) * (g(e0) * (1 - mass) + gaussLegendreComposite((y) => g(y) * dens(y), top - 12 * q, top, 120, 16));
    }
    const bot = Math.max(e0, x);
    const mass = x <= e0 ? tail(e0) : 1;
    return nd(z) * (g(e0) * (1 - mass) + gaussLegendreComposite((y) => g(y) * dens(y), bot, bot + 12 * q, 120, 16));
  };
  return E(-r * t1) * gaussLegendreComposite(outer, -10, 10, 120, 16);
}

test('Delvis lookback, flytende innløsningskurs: integrasjon og MC', () => {
  const cases = [
    { S: 90, Smin: 90, Smax: 90, lambda: 1, t1: 0.5, T: 1, r: 0.06, b: 0.06, v: 0.2 },
    { S: 100, Smin: 92, Smax: 110, lambda: 1.1, t1: 0.3, T: 0.8, r: 0.05, b: -0.02, v: 0.3 },
    { S: 100, Smin: 100, Smax: 100, lambda: 0.95, t1: 0.6, T: 1.2, r: 0.03, b: 0.08, v: 0.45 },
  ];
  cases.forEach((p, k) => {
    for (const type of ['call', 'put']) {
      const lambda = type === 'put' ? 2 - p.lambda : p.lambda; // call: λ ≥ 1 typisk, put: λ ≤ 1
      const q = { ...p, type, lambda };
      close(partialFloatingLookback(q), partialFloatingByIntegration(q), 1e-7, `integrasjon ${type} #${k}`);
    }
  });
  const p = { S: 100, Smin: 95, Smax: 108, t1: 0.4, T: 1, r: 0.06, b: 0.03, v: 0.25 };
  const times = [0, p.t1, p.T];
  for (const lambda of [1, 1.1]) {
    const mc = mcBridge({ ...p, times, n: 150000, seed: 50, payoff: (x, lo) => Math.max(E(x[2]) - lambda * Math.min(p.Smin, E(lo[1])), 0) });
    withinMC(mc, partialFloatingLookback({ type: 'call', ...p, lambda }), 4, 0, `MC call λ=${lambda}`);
  }
  for (const lambda of [1, 0.9]) {
    const mc = mcBridge({ ...p, times, n: 150000, seed: 51, payoff: (x, lo, hi) => Math.max(lambda * Math.max(p.Smax, E(hi[1])) - E(x[2]), 0) });
    withinMC(mc, partialFloatingLookback({ type: 'put', ...p, lambda }), 4, 0, `MC put λ=${lambda}`);
  }
  // Grensetilfeller: t1 → T gir vanlig lookback; t1 → 0 med S_min = S gir vanilla med X = λS.
  const g = { S: 100, Smin: 100, Smax: 100, T: 1, r: 0.05, b: 0.02, v: 0.3 };
  close(partialFloatingLookback({ type: 'call', ...g, lambda: 1, t1: 1 - 1e-10 }), floatingStrikeLookback({ type: 'call', ...g }), 1e-3);
  close(partialFloatingLookback({ type: 'put', ...g, lambda: 1, t1: 1 - 1e-10 }), floatingStrikeLookback({ type: 'put', ...g }), 1e-3);
  close(partialFloatingLookback({ type: 'call', ...g, lambda: 1.05, t1: 1e-10 }), gbsm({ type: 'call', S: 100, X: 105, T: 1, r: 0.05, b: 0.02, v: 0.3 }), 1e-3);
  assert.throws(() => partialFloatingLookback({ type: 'call', ...g, lambda: 1, t1: 1.5 }));
});

test('Delvis lookback, fast innløsningskurs: integrasjon og MC', () => {
  const cases = [
    { S: 100, X: 90, t1: 0.5, T: 1, r: 0.06, b: 0.06, v: 0.2 },
    { S: 100, X: 110, t1: 0.25, T: 0.75, r: 0.05, b: -0.03, v: 0.35 },
    { S: 95, X: 100, t1: 0.7, T: 1.1, r: 0.02, b: 0.07, v: 0.25 },
  ];
  // Referanse: betinget på S_{t1} er dette en vanlig lookback med fast innløsningskurs som starter i S_{t1}.
  for (const p of cases) {
    for (const type of ['call', 'put']) {
      const mu = (p.b - 0.5 * p.v * p.v) * p.t1;
      const q = p.v * Math.sqrt(p.t1);
      const g = (z) => {
        const s = p.S * E(mu + q * z);
        return nd(z) * fixedStrikeLookback({ type, S: s, X: p.X, Smin: s, Smax: s, T: p.T - p.t1, r: p.r, b: p.b, v: p.v });
      };
      const zk = (Math.log(p.X / p.S) - mu) / q;
      const ref = E(-p.r * p.t1) * (gaussLegendreComposite(g, -12, zk, 100, 16) + gaussLegendreComposite(g, zk, 12, 100, 16));
      close(partialFixedLookback({ type, ...p }), ref, 1e-9, `integrasjon ${type} X=${p.X}`);
    }
  }
  const p = { S: 100, X: 105, t1: 0.3, T: 0.8, r: 0.04, b: -0.02, v: 0.3 };
  const times = [0, p.t1, p.T];
  withinMC(mcBridge({ ...p, times, n: 150000, seed: 60, payoff: (x, lo, hi) => Math.max(E(hi[2]) - p.X, 0) }), partialFixedLookback({ type: 'call', ...p }), 4, 0, 'MC call');
  withinMC(mcBridge({ ...p, times, n: 150000, seed: 61, payoff: (x, lo) => Math.max(p.X - E(lo[2]), 0) }), partialFixedLookback({ type: 'put', ...p }), 4, 0, 'MC put');
  // t1 → 0 gir vanlig lookback med fast innløsningskurs; t1 → T gir vanilla.
  for (const type of ['call', 'put']) {
    close(partialFixedLookback({ type, ...p, t1: 1e-10 }), fixedStrikeLookback({ type, ...p }), 1e-3, `t1 → 0 ${type}`);
    close(partialFixedLookback({ type, ...p, t1: p.T - 1e-10 }), gbsm({ type, ...p }), 1e-3, `t1 → T ${type}`);
  }
  // b = 0
  close(partialFixedLookback({ type: 'call', ...p, b: 0 }),
    0.5 * (partialFixedLookback({ type: 'call', ...p, b: 1e-4 }) + partialFixedLookback({ type: 'call', ...p, b: -1e-4 })), 1e-6);
});

test('Extreme spread mot MC', () => {
  const p = { S: 100, Smin: 96, Smax: 104, t1: 0.25, T: 1, r: 0.1, b: 0.06, v: 0.3 };
  const times = [0, p.t1, p.T];
  const M1 = (hi) => Math.max(p.Smax, E(hi[1]));
  const m1 = (lo) => Math.min(p.Smin, E(lo[1]));
  const payoffs = {
    'call': (x, lo, hi) => Math.max(E(hi[2]) - M1(hi), 0),
    'put': (x, lo) => Math.max(m1(lo) - E(lo[2]), 0),
    'reverse-call': (x, lo) => Math.max(E(lo[2]) - m1(lo), 0),
    'reverse-put': (x, lo, hi) => Math.max(M1(hi) - E(hi[2]), 0),
  };
  EXTREME_SPREAD_KINDS.forEach((kind, k) => {
    const mc = mcBridge({ ...p, times, n: 150000, seed: 70 + k, payoff: payoffs[kind] });
    withinMC(mc, extremeSpread({ kind, ...p }), 4, 0, kind);
  });
  // Med b = 0 og negativ carry
  const q = { ...p, b: 0, Smin: 100, Smax: 100 };
  withinMC(mcBridge({ ...q, times, n: 150000, seed: 80, payoff: (x, lo, hi) => Math.max(E(hi[2]) - Math.max(100, E(hi[1])), 0) }),
    extremeSpread({ kind: 'call', ...q }), 4, 0, 'call b = 0');
  // ES call − omvendt ES put = e^{−rT}·E[M2 − M1], som er positiv her fordi andre periode er lengst.
  assert.ok(extremeSpread({ kind: 'call', ...q }) > extremeSpread({ kind: 'reverse-put', ...q }));
  assert.throws(() => extremeSpread({ kind: 'call', ...p, t1: 2 }));
});
