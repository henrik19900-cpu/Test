// Kapittel 8: Monte Carlo-simulering.
//
//   mcEuropean          europeisk opsjon med antitetiske trekk og pathwise delta/vega
//   qmcEuropean         kvasi-tilfeldig (Halton) europeisk opsjon, med randomiserte skift for feilestimat
//   geometricAsianDiscrete  lukket form for diskret geometrisk gjennomsnitt (kontrollvariat)
//   mcAsianArithmetic   aritmetisk asiatisk opsjon med geometrisk kontrollvariat
//   mcTwoAsset          spread, maks og min på to korrelerte aktiva
//   stulz, margrabe, kirk  analytiske referanser for to aktiva
//   longstaffSchwartz   amerikanske opsjoner med minste kvadraters regresjon (Longstaff og Schwartz 2001)
//
// Alle simuleringene bruker fast seed, slik at samme input gir samme svar.

import { createRng, halton } from '../math/rng.js';
import { cnd, cndInv, cbnd } from '../math/normal.js';
import { gbsm, isCall } from './bsm.js';

export const Z975 = 1.959963984540054;

// Gjennomsnitt og standardfeil (forventningsrett utvalgsvarians).
function stats(sum, sumSq, n) {
  const mean = sum / n;
  const variance = n > 1 ? Math.max((sumSq - n * mean * mean) / (n - 1), 0) : 0;
  return { mean, se: Math.sqrt(variance / n) };
}

function checkPaths(paths, min = 100) {
  if (!(paths >= min)) throw new Error(`Antall stier må være minst ${min}.`);
  if (paths > 5e6) throw new Error('Antall stier er begrenset til 5 millioner.');
}

const withCI = (o) => ({ ...o, lo: o.price - Z975 * o.se, hi: o.price + Z975 * o.se });

// --- Europeisk opsjon --------------------------------------------------------------------
// Antitetiske par (z, −z). Pathwise derivater:
//   delta = e^{−rT} 1{ITM} · (±S_T/S),  vega = e^{−rT} 1{ITM} · (±S_T(√T z − σT)).
export function mcEuropean({ type = 'call', S, X, T, r, b, v, paths = 50000, seed = 1 }) {
  checkPaths(paths);
  const call = isCall(type);
  const sign = call ? 1 : -1;
  const pairs = Math.floor(paths / 2);
  const rng = createRng(seed);
  const sqT = Math.sqrt(T);
  const drift = (b - 0.5 * v * v) * T;
  const sd = v * sqT;
  const df = Math.exp(-r * T);
  let sP = 0;
  let sP2 = 0;
  let sD = 0;
  let sD2 = 0;
  let sV = 0;
  let sV2 = 0;
  for (let i = 0; i < pairs; i++) {
    const z = rng.normal();
    let p = 0;
    let d = 0;
    let g = 0;
    for (let k = 0; k < 2; k++) {
      const zz = k === 0 ? z : -z;
      const ST = S * Math.exp(drift + sd * zz);
      const pay = sign * (ST - X);
      if (pay > 0) {
        p += pay;
        d += sign * ST / S;
        g += sign * ST * (sqT * zz - v * T);
      }
    }
    p *= 0.5;
    d *= 0.5;
    g *= 0.5;
    sP += p;
    sP2 += p * p;
    sD += d;
    sD2 += d * d;
    sV += g;
    sV2 += g * g;
  }
  const P = stats(sP, sP2, pairs);
  const D = stats(sD, sD2, pairs);
  const V = stats(sV, sV2, pairs);
  return withCI({
    price: df * P.mean, se: df * P.se,
    delta: df * D.mean, deltaSe: df * D.se,
    vega: df * V.mean, vegaSe: df * V.se,
    n: 2 * pairs,
  });
}

// --- Kvasi-tilfeldig (Halton) ----------------------------------------------------------------
// Én dimensjon: S_T = S exp((b − σ²/2)T + σ√T N⁻¹(u_i)), u_i = Halton-tall i base 2.
// Ren Halton er deterministisk og har ikke noen standardfeil. Feilen anslås derfor med
// randomisert QMC: `shifts` uavhengige Cranley-Patterson-skift u → (u + U) mod 1 av de samme punktene.
export function qmcEuropean({ type = 'call', S, X, T, r, b, v, paths = 20000, seed = 1, shifts = 16 }) {
  checkPaths(paths, shifts * 10);
  const call = isCall(type);
  const sign = call ? 1 : -1;
  const N = Math.floor(paths);
  const per = Math.floor(N / shifts);
  const drift = (b - 0.5 * v * v) * T;
  const sd = v * Math.sqrt(T);
  const df = Math.exp(-r * T);
  const pay = (u) => Math.max(sign * (S * Math.exp(drift + sd * cndInv(u)) - X), 0);
  const u = new Float64Array(N);
  for (let i = 0; i < N; i++) u[i] = halton(i + 1, 2);
  let s = 0;
  for (let i = 0; i < N; i++) s += pay(u[i]);
  const plain = df * s / N;
  const rng = createRng(seed);
  let sum = 0;
  let sumSq = 0;
  for (let m = 0; m < shifts; m++) {
    const sh = rng.uniform();
    let sm = 0;
    for (let i = 0; i < per; i++) {
      let w = u[i] + sh;
      if (w >= 1) w -= 1;
      if (w <= 0) w = 1e-17;
      sm += pay(w);
    }
    const est = df * sm / per;
    sum += est;
    sumSq += est * est;
  }
  const R = stats(sum, sumSq, shifts);
  // Til sammenligning: standardfeil for vanlig (pseudo-tilfeldig) MC med like mange stier.
  let p = 0;
  let p2 = 0;
  for (let i = 0; i < N; i++) {
    const y = Math.max(sign * (S * Math.exp(drift + sd * rng.normal()) - X), 0);
    p += y;
    p2 += y * y;
  }
  const M = stats(p, p2, N);
  return withCI({ price: R.mean, se: R.se, plain, mcPrice: df * M.mean, mcSe: df * M.se, n: per * shifts });
}

// --- Asiatisk opsjon --------------------------------------------------------------------------
// Fikseringer ved t_i = iT/n, i = 1, …, n. ln G ~ N(ln S + (b − σ²/2)T(n+1)/(2n), σ²T(n+1)(2n+1)/(6n²)).
export function geometricAsianDiscrete({ type = 'call', S, X, T, r, b, v, n }) {
  const call = isCall(type);
  const mu = Math.log(S) + (b - 0.5 * v * v) * T * (n + 1) / (2 * n);
  const s2 = v * v * T * (n + 1) * (2 * n + 1) / (6 * n * n);
  const s = Math.sqrt(s2);
  const EG = Math.exp(mu + 0.5 * s2);
  const df = Math.exp(-r * T);
  if (!(s > 0)) return df * Math.max(call ? EG - X : X - EG, 0);
  const d1 = (mu - Math.log(X) + s2) / s;
  const d2 = d1 - s;
  return call ? df * (EG * cnd(d1) - X * cnd(d2)) : df * (X * cnd(-d2) - EG * cnd(-d1));
}

// Aritmetisk gjennomsnitt med det geometriske som kontrollvariat:
//   Ĉ = mean(f_A) − β̂ (mean(f_G) − E[f_G]),  β̂ = Cov(f_A, f_G)/Var(f_G).
export function mcAsianArithmetic({ type = 'call', S, X, T, r, b, v, n = 12, paths = 20000, seed = 1 }) {
  checkPaths(paths);
  if (!(n >= 1)) throw new Error('Antall fikseringer må være minst 1.');
  const call = isCall(type);
  const sign = call ? 1 : -1;
  const N = Math.floor(paths);
  const dt = T / n;
  const drift = (b - 0.5 * v * v) * dt;
  const sd = v * Math.sqrt(dt);
  const df = Math.exp(-r * T);
  const rng = createRng(seed);
  const lnS = Math.log(S);
  let sA = 0;
  let sA2 = 0;
  let sG = 0;
  let sG2 = 0;
  let sAG = 0;
  for (let i = 0; i < N; i++) {
    let x = lnS;
    let sumS = 0;
    let sumX = 0;
    for (let j = 0; j < n; j++) {
      x += drift + sd * rng.normal();
      sumS += Math.exp(x);
      sumX += x;
    }
    const fA = Math.max(sign * (sumS / n - X), 0);
    const fG = Math.max(sign * (Math.exp(sumX / n) - X), 0);
    sA += fA;
    sA2 += fA * fA;
    sG += fG;
    sG2 += fG * fG;
    sAG += fA * fG;
  }
  const mA = sA / N;
  const mG = sG / N;
  const varA = (sA2 - N * mA * mA) / (N - 1);
  const varG = (sG2 - N * mG * mG) / (N - 1);
  const cov = (sAG - N * mA * mG) / (N - 1);
  const geo = geometricAsianDiscrete({ type, S, X, T, r, b, v, n });
  const beta = varG > 0 ? cov / varG : 0;
  const cv = mA - beta * (mG - geo / df);
  const varCV = Math.max(varA - 2 * beta * cov + beta * beta * varG, 0);
  return withCI({
    price: df * cv,
    se: df * Math.sqrt(varCV / N),
    plain: df * mA,
    plainSe: df * Math.sqrt(Math.max(varA, 0) / N),
    geometric: geo,
    beta,
    n: N,
  });
}

// --- To aktiva ------------------------------------------------------------------------------
const twoAssetPayoff = (kind, call) => {
  const sign = call ? 1 : -1;
  if (kind === 'spread') return (s1, s2, X) => Math.max(sign * (s1 - s2 - X), 0);
  if (kind === 'max') return (s1, s2, X) => Math.max(sign * (Math.max(s1, s2) - X), 0);
  if (kind === 'min') return (s1, s2, X) => Math.max(sign * (Math.min(s1, s2) - X), 0);
  throw new Error(`Ukjent utbetaling: ${kind}`);
};

export function mcTwoAsset({
  kind = 'spread', type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho, paths = 50000, seed = 1,
}) {
  checkPaths(paths);
  if (!(rho >= -1 && rho <= 1)) throw new Error('Korrelasjonen må ligge mellom −1 og 1.');
  const f = twoAssetPayoff(kind, isCall(type));
  const pairs = Math.floor(paths / 2);
  const rng = createRng(seed);
  const sq = Math.sqrt(T);
  const m1 = (b1 - 0.5 * v1 * v1) * T;
  const m2 = (b2 - 0.5 * v2 * v2) * T;
  const c = Math.sqrt(Math.max(1 - rho * rho, 0));
  const df = Math.exp(-r * T);
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < pairs; i++) {
    const z1 = rng.normal();
    const z2 = rho * z1 + c * rng.normal();
    const a = f(S1 * Math.exp(m1 + v1 * sq * z1), S2 * Math.exp(m2 + v2 * sq * z2), X);
    const bb = f(S1 * Math.exp(m1 - v1 * sq * z1), S2 * Math.exp(m2 - v2 * sq * z2), X);
    const y = 0.5 * (a + bb);
    sum += y;
    sumSq += y * y;
  }
  const s = stats(sum, sumSq, pairs);
  return withCI({ price: df * s.mean, se: df * s.se, n: 2 * pairs });
}

// Margrabe (1978): e^{−rT} E[max(S1_T − S2_T, 0)].
export function margrabe({ S1, S2, T, r, b1, b2, v1, v2, rho }) {
  const v = Math.sqrt(v1 * v1 + v2 * v2 - 2 * rho * v1 * v2);
  const a1 = S1 * Math.exp((b1 - r) * T);
  const a2 = S2 * Math.exp((b2 - r) * T);
  if (!(v > 0)) return Math.max(a1 - a2, 0);
  const d1 = (Math.log(S1 / S2) + (b1 - b2 + 0.5 * v * v) * T) / (v * Math.sqrt(T));
  return a1 * cnd(d1) - a2 * cnd(d1 - v * Math.sqrt(T));
}

// Stulz (1982): call/put på minimum eller maksimum av to aktiva.
export function stulz({ kind = 'min', type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const call = isCall(type);
  const sqT = Math.sqrt(T);
  const v = Math.sqrt(v1 * v1 + v2 * v2 - 2 * rho * v1 * v2);
  if (!(v > 0)) throw new Error('Stulz-formelen krever at S1 og S2 ikke er perfekt korrelerte med lik volatilitet.');
  const a1 = S1 * Math.exp((b1 - r) * T);
  const a2 = S2 * Math.exp((b2 - r) * T);
  const xd = X * Math.exp(-r * T);
  const d = (Math.log(S1 / S2) + (b1 - b2 + 0.5 * v * v) * T) / (v * sqT);
  const y1 = (Math.log(S1 / X) + (b1 + 0.5 * v1 * v1) * T) / (v1 * sqT);
  const y2 = (Math.log(S2 / X) + (b2 + 0.5 * v2 * v2) * T) / (v2 * sqT);
  const rho1 = (v1 - rho * v2) / v;
  const rho2 = (v2 - rho * v1) / v;
  const cMin = a1 * cbnd(y1, -d, -rho1) + a2 * cbnd(y2, d - v * sqT, -rho2) -
    xd * cbnd(y1 - v1 * sqT, y2 - v2 * sqT, rho);
  const cMax = a1 * cbnd(y1, d, rho1) + a2 * cbnd(y2, -d + v * sqT, rho2) -
    xd * (1 - cbnd(-y1 + v1 * sqT, -y2 + v2 * sqT, rho));
  // Nåverdi av min(S1, S2) og max(S1, S2) ved forfall: min = S1 − max(S1 − S2, 0).
  const exch = margrabe({ S1, S2, T, r, b1, b2, v1, v2, rho });
  const pvMin = a1 - exch;
  const pvMax = a2 + exch;
  if (kind === 'min') return call ? cMin : xd - pvMin + cMin;
  if (kind === 'max') return call ? cMax : xd - pvMax + cMax;
  throw new Error(`Ukjent utbetaling: ${kind}`);
}

// Kirk (1995): tilnærming for spreadopsjon max(S1 − S2 − X, 0).
export function kirk({ type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const call = isCall(type);
  const F1 = S1 * Math.exp(b1 * T);
  const F2 = S2 * Math.exp(b2 * T);
  if (!(F2 + X > 0)) throw new Error('Kirks tilnærming krever F2 + X > 0.');
  const w = F2 / (F2 + X);
  const F = F1 / (F2 + X);
  const v = Math.sqrt(v1 * v1 + (v2 * w) ** 2 - 2 * rho * v1 * v2 * w);
  const df = Math.exp(-r * T);
  const d1 = (Math.log(F) + 0.5 * v * v * T) / (v * Math.sqrt(T));
  const d2 = d1 - v * Math.sqrt(T);
  return call ? (F2 + X) * df * (F * cnd(d1) - cnd(d2)) : (F2 + X) * df * (cnd(-d2) - F * cnd(-d1));
}

// --- Longstaff-Schwartz (2001) ----------------------------------------------------------------------
// Bermudisk tilnærming til amerikansk opsjon med `steps` utøvelsesdatoer. Fortsettelsesverdien
// estimeres ved regresjon av diskontert fremtidig kontantstrøm på 1, x, …, x^degree (x = S/X),
// bare over stier i pengene. Antitetiske par; standardfeilen regnes over parene.
function solveLinear(A, y) {
  const n = y.length;
  const M = A.map((row, i) => [...row, y[i]]);
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let i = c + 1; i < n; i++) if (Math.abs(M[i][c]) > Math.abs(M[p][c])) p = i;
    if (Math.abs(M[p][c]) < 1e-300) return null;
    [M[c], M[p]] = [M[p], M[c]];
    for (let i = c + 1; i < n; i++) {
      const f = M[i][c] / M[c][c];
      for (let j = c; j <= n; j++) M[i][j] -= f * M[c][j];
    }
  }
  const x = new Array(n).fill(0);
  for (let i = n - 1; i >= 0; i--) {
    let s = M[i][n];
    for (let j = i + 1; j < n; j++) s -= M[i][j] * x[j];
    x[i] = s / M[i][i];
  }
  return x;
}

export function longstaffSchwartz({ type = 'put', S, X, T, r, b, v, steps = 50, paths = 20000, seed = 1, degree = 3 }) {
  checkPaths(paths);
  if (!(steps >= 1)) throw new Error('Antall tidssteg må være minst 1.');
  if (!(degree >= 1 && degree <= 6)) throw new Error('Polynomgraden må ligge mellom 1 og 6.');
  const call = isCall(type);
  const sign = call ? 1 : -1;
  const pairs = Math.floor(paths / 2);
  const N = 2 * pairs;
  if (N * steps > 2e7) throw new Error('For mange stier ganger tidssteg (maks 20 millioner).');
  const dt = T / steps;
  const drift = (b - 0.5 * v * v) * dt;
  const sd = v * Math.sqrt(dt);
  const disc = Math.exp(-r * dt);
  const rng = createRng(seed);
  // Tidsordnet lagring: P[(j − 1)·N + i] er kursen på sti i ved tidssteg j (sti 2k og 2k + 1 er et
  // antitetisk par). Én tidsskive ligger da sammenhengende i minnet når vi regner baklengs.
  const P = new Float64Array(N * steps);
  const lnS = Math.log(S);
  for (let k = 0; k < pairs; k++) {
    let x1 = lnS;
    let x2 = lnS;
    for (let j = 0; j < steps; j++) {
      const z = rng.normal();
      x1 += drift + sd * z;
      x2 += drift - sd * z;
      P[j * N + 2 * k] = Math.exp(x1);
      P[j * N + 2 * k + 1] = Math.exp(x2);
    }
  }
  const val = new Float64Array(N);
  let euro = 0;
  let euro2 = 0;
  const last = (steps - 1) * N;
  for (let i = 0; i < N; i++) val[i] = Math.max(sign * (P[last + i] - X), 0);
  for (let k = 0; k < pairs; k++) {
    const y = 0.5 * (val[2 * k] + val[2 * k + 1]);
    euro += y;
    euro2 += y * y;
  }
  const nb = degree + 1;
  const basis = new Float64Array(nb);
  const A = new Float64Array(nb * nb);
  const yv = new Float64Array(nb);
  const idx = new Int32Array(N);
  const xs = new Float64Array(N);
  const exs = new Float64Array(N);
  for (let j = steps - 1; j >= 1; j--) {
    const off = (j - 1) * N;
    for (let i = 0; i < N; i++) val[i] *= disc;
    let count = 0;
    for (let i = 0; i < N; i++) {
      const s = P[off + i];
      const ex = sign * (s - X);
      if (ex > 0) {
        idx[count] = i;
        xs[count] = s / X;
        exs[count] = ex;
        count++;
      }
    }
    if (count <= nb) continue;
    A.fill(0);
    yv.fill(0);
    for (let c = 0; c < count; c++) {
      const x = xs[c];
      const y = val[idx[c]];
      basis[0] = 1;
      for (let q = 1; q < nb; q++) basis[q] = basis[q - 1] * x;
      for (let p = 0; p < nb; p++) {
        const bp = basis[p];
        yv[p] += bp * y;
        for (let q = p; q < nb; q++) A[p * nb + q] += bp * basis[q];
      }
    }
    const M = [];
    for (let p = 0; p < nb; p++) {
      const row = [];
      for (let q = 0; q < nb; q++) row.push(q >= p ? A[p * nb + q] : A[q * nb + p]);
      M.push(row);
    }
    const coef = solveLinear(M, Array.from(yv));
    if (!coef) continue;
    for (let c = 0; c < count; c++) {
      const x = xs[c];
      let cont = coef[nb - 1];
      for (let q = nb - 2; q >= 0; q--) cont = cont * x + coef[q];
      if (exs[c] > cont) val[idx[c]] = exs[c];
    }
  }
  let sum = 0;
  let sumSq = 0;
  for (let k = 0; k < pairs; k++) {
    const y = 0.5 * disc * (val[2 * k] + val[2 * k + 1]);
    sum += y;
    sumSq += y * y;
  }
  const st = stats(sum, sumSq, pairs);
  const eu = stats(euro, euro2, pairs);
  const df = Math.exp(-r * T);
  const immediate = Math.max(sign * (S - X), 0);
  return withCI({
    price: Math.max(st.mean, immediate),
    se: st.se,
    european: df * eu.mean,
    europeanSe: df * eu.se,
    bsm: gbsm({ type, S, X, T, r, b, v }),
    n: N,
  });
}
