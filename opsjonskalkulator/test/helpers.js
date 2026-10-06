// Testhjelpere: toleransesammenligning og Monte Carlo-motorer for uavhengig kontroll av formler.
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';

export function close(actual, expected, tol = 1e-4, msg = '') {
  assert.ok(Number.isFinite(actual), `${msg} fikk ikke-endelig verdi ${actual}`);
  assert.ok(
    Math.abs(actual - expected) <= tol,
    `${msg} forventet ${expected}, fikk ${actual} (avvik ${(actual - expected).toExponential(3)}, toleranse ${tol})`,
  );
}

// Monte Carlo-estimat skal ligge innenfor k standardfeil (pluss en liten absolutt slakk).
export function withinMC(estimate, exact, k = 4, abs = 0, msg = '') {
  const { mean, se } = estimate;
  assert.ok(
    Math.abs(mean - exact) <= k * se + abs,
    `${msg} MC ${mean.toFixed(5)} ± ${se.toFixed(5)} mot formel ${exact} (avvik ${(mean - exact).toFixed(5)} = ${((mean - exact) / se).toFixed(2)} SE)`,
  );
}

function stats(sum, sumSq, n) {
  const mean = sum / n;
  const variance = Math.max(sumSq / n - mean * mean, 0);
  return { mean, se: Math.sqrt(variance / n) };
}

// Europeisk payoff av S_T under GBM med cost of carry b. Antitetiske par.
// payoff(ST) er udiskontert; resultatet diskonteres med e^{−rT}.
export function mcTerminal({ S, T, r, b, v, n = 200000, seed = 1, payoff }) {
  const rng = createRng(seed);
  const drift = (b - 0.5 * v * v) * T;
  const sd = v * Math.sqrt(T);
  const df = Math.exp(-r * T);
  let sum = 0;
  let sumSq = 0;
  const pairs = Math.floor(n / 2);
  for (let i = 0; i < pairs; i++) {
    const z = rng.normal();
    const y = 0.5 * (payoff(S * Math.exp(drift + sd * z)) + payoff(S * Math.exp(drift - sd * z)));
    sum += y;
    sumSq += y * y;
  }
  const s = stats(sum, sumSq, pairs);
  return { mean: s.mean * df, se: s.se * df };
}

// Stidavhengig payoff under GBM. payoff(path) får en Float64Array med steps+1 punkter
// (path[0] = S, path[i] = S ved tid i·T/steps). Antitetiske par.
export function mcPaths({ S, T, r, b, v, steps, n = 50000, seed = 1, payoff, discount = true }) {
  const rng = createRng(seed);
  const dt = T / steps;
  const drift = (b - 0.5 * v * v) * dt;
  const sd = v * Math.sqrt(dt);
  const df = discount ? Math.exp(-r * T) : 1;
  const p1 = new Float64Array(steps + 1);
  const p2 = new Float64Array(steps + 1);
  let sum = 0;
  let sumSq = 0;
  const pairs = Math.floor(n / 2);
  for (let i = 0; i < pairs; i++) {
    p1[0] = S;
    p2[0] = S;
    let l1 = Math.log(S);
    let l2 = l1;
    for (let j = 1; j <= steps; j++) {
      const z = rng.normal();
      l1 += drift + sd * z;
      l2 += drift - sd * z;
      p1[j] = Math.exp(l1);
      p2[j] = Math.exp(l2);
    }
    const y = 0.5 * (payoff(p1) + payoff(p2));
    sum += y;
    sumSq += y * y;
  }
  const s = stats(sum, sumSq, pairs);
  return { mean: s.mean * df, se: s.se * df };
}

// To korrelerte GBM-er ved forfall. payoff(S1T, S2T) udiskontert.
export function mcTwoAssets({ S1, S2, T, r, b1, b2, v1, v2, rho, n = 200000, seed = 1, payoff }) {
  const rng = createRng(seed);
  const sq = Math.sqrt(T);
  const m1 = (b1 - 0.5 * v1 * v1) * T;
  const m2 = (b2 - 0.5 * v2 * v2) * T;
  const c = Math.sqrt(1 - rho * rho);
  const df = Math.exp(-r * T);
  let sum = 0;
  let sumSq = 0;
  const pairs = Math.floor(n / 2);
  for (let i = 0; i < pairs; i++) {
    const z1 = rng.normal();
    const z2 = rho * z1 + c * rng.normal();
    const a = payoff(S1 * Math.exp(m1 + v1 * sq * z1), S2 * Math.exp(m2 + v2 * sq * z2));
    const bb = payoff(S1 * Math.exp(m1 - v1 * sq * z1), S2 * Math.exp(m2 - v2 * sq * z2));
    const y = 0.5 * (a + bb);
    sum += y;
    sumSq += y * y;
  }
  const s = stats(sum, sumSq, pairs);
  return { mean: s.mean * df, se: s.se * df };
}

// To korrelerte GBM-stier. payoff(path1, path2) udiskontert, steps+1 punkter hver.
export function mcTwoAssetPaths({ S1, S2, T, r, b1, b2, v1, v2, rho, steps, n = 50000, seed = 1, payoff }) {
  const rng = createRng(seed);
  const dt = T / steps;
  const sq = Math.sqrt(dt);
  const m1 = (b1 - 0.5 * v1 * v1) * dt;
  const m2 = (b2 - 0.5 * v2 * v2) * dt;
  const c = Math.sqrt(1 - rho * rho);
  const df = Math.exp(-r * T);
  const a1 = new Float64Array(steps + 1);
  const a2 = new Float64Array(steps + 1);
  const b1p = new Float64Array(steps + 1);
  const b2p = new Float64Array(steps + 1);
  let sum = 0;
  let sumSq = 0;
  const pairs = Math.floor(n / 2);
  for (let i = 0; i < pairs; i++) {
    let x1 = Math.log(S1);
    let x2 = Math.log(S2);
    let y1 = x1;
    let y2 = x2;
    a1[0] = S1; b1p[0] = S1; a2[0] = S2; b2p[0] = S2;
    for (let j = 1; j <= steps; j++) {
      const z1 = rng.normal();
      const z2 = rho * z1 + c * rng.normal();
      x1 += m1 + v1 * sq * z1;
      x2 += m2 + v2 * sq * z2;
      y1 += m1 - v1 * sq * z1;
      y2 += m2 - v2 * sq * z2;
      a1[j] = Math.exp(x1); a2[j] = Math.exp(x2);
      b1p[j] = Math.exp(y1); b2p[j] = Math.exp(y2);
    }
    const y = 0.5 * (payoff(a1, a2) + payoff(b1p, b2p));
    sum += y;
    sumSq += y * y;
  }
  const s = stats(sum, sumSq, pairs);
  return { mean: s.mean * df, se: s.se * df };
}

// Sannsynligheten for at en brownsk bro mellom to logpriser krysser en barriere (i log)
// mellom to observasjoner. Brukes til å gjøre diskret simulerte stier kontinuerlig overvåket.
export function bridgeHitProb(x0, x1, logH, sigma, dt) {
  const a = x0 - logH;
  const c = x1 - logH;
  if (a * c <= 0) return 1;
  return Math.exp(-2 * a * c / (sigma * sigma * dt));
}
