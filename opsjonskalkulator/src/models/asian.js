// Kapittel 4: Asiatiske opsjoner (gjennomsnittsopsjoner med fast innløsningskurs).
//   Geometrisk gjennomsnitt, kontinuerlig: Kemna og Vorst (1990)
//   Aritmetisk gjennomsnitt, kontinuerlig: Turnbull og Wakeman (1991), Levy (1992)
//   Aritmetisk gjennomsnitt, diskret: Curran (1992), og momenttilpasning (Haug, Haug og Margrabe 2003)
//
// Allerede påbegynt gjennomsnittsperiode: den kjente delen SA veier inn i sluttgjennomsnittet, og
// opsjonen skrives om til en opsjon på den gjenstående delen med justert innløsningskurs.
// Blir den justerte innløsningskursen ≤ 0, er callen sikker på å bli innløst (verdi = nåverdien av
// forventet gjennomsnitt minus X) og putten verdiløs.

import { cnd } from '../math/normal.js';
import { gbsm, isCall } from './bsm.js';
import { expm1OverX } from './exotics.js';

// Geometrisk gjennomsnitt over [0, T] (Kemna og Vorst 1990).
export function geometricAverage({ type, S, X, T, r, b, v }) {
  const vA = v / Math.sqrt(3);
  const bA = 0.5 * (b - v * v / 6);
  return gbsm({ type, S, X, T, r, b: bA, v: vA });
}

// [φ(αL) − φ(βL)] / ((α − β)L) med φ(x) = (e^x − 1)/x, stabil også når α ≈ β.
function dividedDiff(alpha, beta, L) {
  const h = (alpha - beta) * L;
  if (Math.abs(h) > 1e-6) return (expm1OverX(alpha * L) - expm1OverX(beta * L)) / h;
  // φ'(x) = (e^x (x − 1) + 1)/x² (→ 1/2 i x = 0)
  const x = 0.5 * (alpha + beta) * L;
  if (Math.abs(x) < 1e-4) return 0.5 + x / 3;
  return (Math.exp(x) * (x - 1) + 1) / (x * x);
}

// Første og andre moment (delt på S og S²) av kontinuerlig gjennomsnitt over [t1, t1 + L].
export function continuousAverageMoments(b, v, t1, L) {
  const M1 = Math.exp(b * t1) * expm1OverX(b * L);
  const M2 = 2 * Math.exp((2 * b + v * v) * t1) * dividedDiff(2 * b + v * v, b, L);
  return { M1, M2 };
}

// Felles struktur for påbegynt periode. `price(Xadj)` er opsjonen på den gjenstående delen.
// weight = andel av gjennomsnittet som gjenstår, known = kjent bidrag til gjennomsnittet.
function seasoned({ call, X, weight, known, futureMeanPV, df, price }) {
  if (weight >= 1) return price(X);
  const Xadj = (X - known) / weight;
  if (Xadj <= 0) return call ? weight * futureMeanPV + df * (known - X) : 0;
  return weight * price(Xadj);
}

function checkAverage({ T, T2 }) {
  if (!(T > 0)) throw new Error('Tid til forfall T må være positiv.');
  if (!(T2 > 0)) throw new Error('Lengden på gjennomsnittsperioden T2 må være positiv.');
}

// Turnbull og Wakeman (1991). T2 = hele gjennomsnittsperiodens lengde; perioden slutter ved T.
// T2 < T: perioden starter om t1 = T − T2. T2 > T: perioden startet for T2 − T år siden, SA er
// gjennomsnittet så langt.
export function turnbullWakeman({ type, S, SA = S, X, T, T2, r, b, v }) {
  checkAverage({ T, T2 });
  const call = isCall(type);
  const t1 = Math.max(T - T2, 0);
  const L = T - t1;
  const { M1, M2 } = continuousAverageMoments(b, v, t1, L);
  const bA = Math.log(M1) / T;
  const vA = Math.sqrt(Math.max(Math.log(M2) / T - 2 * bA, 0));
  const df = Math.exp(-r * T);
  const weight = Math.min(T / T2, 1);
  const value = seasoned({
    call, X, weight, known: (1 - weight) * SA, futureMeanPV: S * M1 * df, df,
    price: (K) => gbsm({ type, S, X: K, T, r, b: bA, v: vA }),
  });
  return { price: value, bA, vA };
}

// Levy (1992). T2 er gjennomsnittsperiodens totale lengde, som slutter ved T. Levys formel er laget
// for en periode som har startet (T2 ≥ T, der T2 = T betyr at den starter nå). For T2 < T brukes
// samme momenttilpasning på perioden [T − T2, T].
export function levy({ type, S, SA = S, X, T, T2, r, b, v }) {
  checkAverage({ T, T2 });
  const call = isCall(type);
  const df = Math.exp(-r * T);
  const t1 = Math.max(T - T2, 0);
  const L = T - t1;
  const w = L / T2; // andel av gjennomsnittet som gjenstår
  const { M1, M2 } = continuousAverageMoments(b, v, t1, L);
  // Y = w·(gjenstående gjennomsnitt): S_E = e^{−rT}E[Y], D = E[Y²] (Levys M/T2² når t1 = 0).
  const SE = w * S * M1 * df;
  const D = w * w * S * S * M2;
  const V = Math.max(Math.log(D) - 2 * (r * T + Math.log(SE)), 1e-300);
  const Xstar = X - SA * (1 - w);
  let price;
  if (Xstar <= 0) {
    price = call ? SE - Xstar * df : 0;
  } else {
    const d1 = (0.5 * Math.log(D) - Math.log(Xstar)) / Math.sqrt(V);
    const d2 = d1 - Math.sqrt(V);
    const c = SE * cnd(d1) - Xstar * df * cnd(d2);
    price = call ? c : c - SE + Xstar * df;
  }
  return { price, SE, Xstar };
}

// --- Diskret gjennomsnitt -----------------------------------------------------------------------
// n fikseringer totalt, m av dem er allerede gjort (gjennomsnitt SA). De n − m gjenstående
// ligger likt fordelt fra t1 (første gjenstående) til T: t_i = t1 + (i − 1)Δt, Δt = (T − t1)/(n − m − 1).

function discreteSetup({ T, t1, n, m }) {
  if (!(T > 0)) throw new Error('Tid til forfall T må være positiv.');
  if (!(Number.isInteger(n) && n >= 1)) throw new Error('Antall fikseringer n må være et positivt heltall.');
  if (!(Number.isInteger(m) && m >= 0 && m < n)) throw new Error('Antall gjorte fikseringer m må være et heltall fra 0 til n − 1.');
  const k = n - m;
  if (!(t1 >= 0 && t1 <= T)) throw new Error('Første gjenstående fiksering t1 må ligge mellom 0 og T.');
  if (k > 1 && !(t1 < T)) throw new Error('Med flere gjenstående fikseringer må t1 være før T.');
  const dt = k > 1 ? (T - t1) / (k - 1) : 0;
  const times = Array.from({ length: k }, (_, i) => (k === 1 ? T : t1 + i * dt));
  return { k, dt, times };
}

// Curran (1992): betinger på det geometriske gjennomsnittet G. Gir call for k gjenstående,
// likt fordelte fikseringer t_i = t1 + iΔt (i = 0, …, k − 1).
function curranCall(S, X, times, dt, r, b, v, T) {
  const k = times.length;
  const t1 = times[0];
  const lnS = Math.log(S);
  const mu = lnS + (b - 0.5 * v * v) * (t1 + 0.5 * (k - 1) * dt);
  // Cov(ln S_ti, ln G) = σ²[t1 + Δt(i − i(i + 1)/(2k))], Var(ln G) = σ²[t1 + Δt(k − 1)(2k − 1)/(6k)]
  const sxi = new Float64Array(k);
  for (let i = 0; i < k; i++) sxi[i] = v * v * (t1 + dt * (i - i * (i + 1) / (2 * k)));
  const sx2 = v * v * (t1 + dt * (k - 1) * (2 * k - 1) / (6 * k));
  const sx = Math.sqrt(sx2);
  const df = Math.exp(-r * T);
  const mean = (i) => lnS + (b - 0.5 * v * v) * times[i];
  let EA = 0;
  for (let i = 0; i < k; i++) EA += S * Math.exp(b * times[i]) / k;
  if (!(sx > 0)) return df * Math.max(EA - X, 0);
  // X̂ = 2X − E[A | G = X] (lineær tilnærming)
  let condMean = 0;
  for (let i = 0; i < k; i++) {
    const si2 = v * v * times[i];
    condMean += Math.exp(mean(i) + sxi[i] / sx2 * (Math.log(X) - mu) + 0.5 * (si2 - sxi[i] * sxi[i] / sx2)) / k;
  }
  const Xh = 2 * X - condMean;
  if (Xh <= 0) return df * (EA - X);
  const z = (mu - Math.log(Xh)) / sx;
  let sum = 0;
  for (let i = 0; i < k; i++) sum += S * Math.exp(b * times[i]) * cnd(z + sxi[i] / sx) / k;
  return df * (sum - X * cnd(z));
}

function discreteMean(S, times, b) {
  return times.reduce((a, t) => a + S * Math.exp(b * t), 0) / times.length;
}

export function curran({ type, S, SA = S, X, T, t1, n, m = 0, r, b, v }) {
  const call = isCall(type);
  const { k, dt, times } = discreteSetup({ T, t1, n, m });
  const df = Math.exp(-r * T);
  const futureMean = discreteMean(S, times, b);
  const weight = k / n;
  const value = seasoned({
    call, X, weight, known: m * SA / n, futureMeanPV: futureMean * df, df,
    price: (K) => {
      const c = curranCall(S, K, times, dt, r, b, v, T);
      return call ? c : c - df * (futureMean - K);
    },
  });
  return { price: value, mean: (m * SA + k * futureMean) / n };
}

// Momenttilpasning for diskret aritmetisk gjennomsnitt (Haug, Haug og Margrabe 2003):
// E[A] og E[A²] regnes eksakt, og A tilnærmes lognormalt.
export function discreteAverageMoments(S, times, b, v) {
  const k = times.length;
  let EA = 0;
  let EA2 = 0;
  let tailSum = 0; // Σ_{j>i} e^{b t_j}
  for (let i = k - 1; i >= 0; i--) {
    const ebt = Math.exp(b * times[i]);
    EA += ebt;
    EA2 += Math.exp((b + v * v) * times[i]) * (ebt + 2 * tailSum);
    tailSum += ebt;
  }
  return { EA: S * EA / k, EA2: S * S * EA2 / (k * k) };
}

export function discreteArithmeticAverage({ type, S, SA = S, X, T, t1, n, m = 0, r, b, v }) {
  const call = isCall(type);
  const { k, times } = discreteSetup({ T, t1, n, m });
  const df = Math.exp(-r * T);
  const { EA, EA2 } = discreteAverageMoments(S, times, b, v);
  const varLog = Math.max(Math.log(EA2) - 2 * Math.log(EA), 0);
  const vA = Math.sqrt(varLog / T);
  const weight = k / n;
  const value = seasoned({
    call, X, weight, known: m * SA / n, futureMeanPV: EA * df, df,
    // Black-formel på forventet gjennomsnitt: GBSM med S = E[A], b = 0.
    price: (K) => gbsm({ type, S: EA, X: K, T, r, b: 0, v: vA }),
  });
  return { price: value, EA: (m * SA + k * EA) / n, vA };
}
