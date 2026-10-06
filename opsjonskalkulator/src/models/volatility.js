// Kapittel 12: Volatilitet og korrelasjon.
//
//   Historisk volatilitet: sluttkurser (close-to-close), EWMA, Parkinson (1980), Garman og Klass (1980),
//     Rogers og Satchell (1991), Yang og Zhang (2000)
//   Konfidensintervall for volatilitetsestimat (kjikvadrat)
//   Tilnærminger til implisitt volatilitet: Brenner og Subrahmanyam (1988), Corrado og Miller (1996),
//     Bharadia, Christofides og Salkin (1996), startverdien til Manaster og Koehler (1982)
//   Implisitt forward-volatilitet
//   Historisk korrelasjon og fordelingen til empirisk korrelasjonskoeffisient (Fisher 1915)
//   Implisitt korrelasjon fra valutavolatiliteter og gjennomsnittlig implisitt indekskorrelasjon
//   Variance swap: rettferdig variansstrike ved statisk replikasjon (Demeterfi m.fl. 1999)

import { cndInv, cnd } from '../math/normal.js';
import { chi2cdf, lnGamma } from '../math/special.js';
import { brent } from '../math/solvers.js';
import { gaussLegendreComposite } from '../math/integrate.js';
import { gbsm, isCall, impliedVolGBSM } from './bsm.js';

const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;

function checkPrices(prices, name, min = 3) {
  if (!Array.isArray(prices) || prices.length < min) throw new Error(`${name}: trenger minst ${min} priser.`);
  if (prices.some((p) => !(p > 0) || !Number.isFinite(p))) throw new Error(`${name}: alle priser må være positive tall.`);
}

export function logReturns(prices) {
  const u = new Array(prices.length - 1);
  for (let i = 1; i < prices.length; i++) u[i - 1] = Math.log(prices[i] / prices[i - 1]);
  return u;
}

// Utvalgsvarians med n − 1 i nevneren.
function sampleVariance(xs) {
  const m = mean(xs);
  return xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1);
}

// --- Historisk volatilitet -------------------------------------------------------------------

// Close-to-close: σ = √(periodsPerYear · 1/(n−1) Σ(u_i − ū)²), u_i = ln(C_i/C_{i−1}).
export function closeToCloseVol(closes, periodsPerYear = 252) {
  checkPrices(closes, 'Sluttkursene');
  const u = logReturns(closes);
  const s2 = sampleVariance(u);
  return { sigma: Math.sqrt(s2 * periodsPerYear), sigmaPeriod: Math.sqrt(s2), n: u.length, mean: mean(u) };
}

// Eksponentielt vektet: σ² = Σ λ^{i} u²_{n−i} / Σ λ^{i} (nyeste avkastning har størst vekt).
export function ewmaVol(closes, lambda = 0.94, periodsPerYear = 252) {
  checkPrices(closes, 'Sluttkursene', 2);
  if (!(lambda > 0 && lambda <= 1)) throw new Error('Vektfaktoren λ må ligge i (0, 1].');
  const u = logReturns(closes);
  let num = 0;
  let den = 0;
  let w = 1;
  for (let i = u.length - 1; i >= 0; i--) {
    num += w * u[i] * u[i];
    den += w;
    w *= lambda;
  }
  const s2 = num / den;
  return { sigma: Math.sqrt(s2 * periodsPerYear), sigmaPeriod: Math.sqrt(s2), n: u.length, weightLatest: 1 / den };
}

function checkOHLC(o, h, l, c, needOpen = true) {
  const n = h.length;
  if (n < 2) throw new Error('Trenger minst to perioder med høy- og lavkurser.');
  if (l.length !== n || (c && c.length !== n) || (needOpen && o.length !== n)) {
    throw new Error('Rekkene for åpning, høy, lav og slutt må ha like mange tall.');
  }
  for (const [arr, name] of [[o, 'Åpningskursene'], [h, 'Høykursene'], [l, 'Lavkursene'], [c, 'Sluttkursene']]) {
    if (arr && arr.some((p) => !(p > 0) || !Number.isFinite(p))) throw new Error(`${name}: alle priser må være positive tall.`);
  }
  for (let i = 0; i < n; i++) {
    const hi = Math.max(o ? o[i] : -Infinity, c ? c[i] : -Infinity, l[i]);
    const lo = Math.min(o ? o[i] : Infinity, c ? c[i] : Infinity, h[i]);
    if (h[i] < hi || l[i] > lo) throw new Error(`Periode ${i + 1}: høykursen må være størst og lavkursen minst.`);
  }
}

// Parkinson (1980): σ² = 1/(4n ln 2) Σ ln²(H_i/L_i).
export function parkinsonVol(highs, lows, periodsPerYear = 252) {
  checkOHLC(null, highs, lows, null, false);
  const n = highs.length;
  let s = 0;
  for (let i = 0; i < n; i++) s += Math.log(highs[i] / lows[i]) ** 2;
  const s2 = s / (4 * n * Math.LN2);
  return { sigma: Math.sqrt(s2 * periodsPerYear), sigmaPeriod: Math.sqrt(s2), n };
}

// Garman og Klass (1980): σ² = 1/n Σ [½ ln²(H/L) − (2 ln 2 − 1) ln²(C/O)].
// Uten åpningskurser (opens = null) brukes forrige sluttkurs som åpning (høy-lav-slutt-varianten),
// og første periode faller bort.
export function garmanKlassVol(opens, highs, lows, closes, periodsPerYear = 252) {
  checkOHLC(opens, highs, lows, closes, Boolean(opens));
  const k = 2 * Math.LN2 - 1;
  let s = 0;
  let n = 0;
  for (let i = opens ? 0 : 1; i < highs.length; i++) {
    const o = opens ? opens[i] : closes[i - 1];
    s += 0.5 * Math.log(highs[i] / lows[i]) ** 2 - k * Math.log(closes[i] / o) ** 2;
    n++;
  }
  const s2 = Math.max(s / n, 0);
  return { sigma: Math.sqrt(s2 * periodsPerYear), sigmaPeriod: Math.sqrt(s2), n };
}

// Rogers og Satchell (1991): σ² = 1/n Σ [ln(H/C) ln(H/O) + ln(L/C) ln(L/O)], upåvirket av drift.
export function rogersSatchellVol(opens, highs, lows, closes, periodsPerYear = 252) {
  checkOHLC(opens, highs, lows, closes);
  const n = highs.length;
  let s = 0;
  for (let i = 0; i < n; i++) s += rsTerm(opens[i], highs[i], lows[i], closes[i]);
  const s2 = Math.max(s / n, 0);
  return { sigma: Math.sqrt(s2 * periodsPerYear), sigmaPeriod: Math.sqrt(s2), n };
}

function rsTerm(o, h, l, c) {
  return Math.log(h / c) * Math.log(h / o) + Math.log(l / c) * Math.log(l / o);
}

// Yang og Zhang (2000): σ² = σ²_natt + k σ²_åpen-slutt + (1 − k) σ²_RS, k = 0,34/(1,34 + (m+1)/(m−1)),
// der m er antall perioder med kjent forrige sluttkurs (første periode brukes bare som utgangspunkt).
export function yangZhangVol(opens, highs, lows, closes, periodsPerYear = 252) {
  checkOHLC(opens, highs, lows, closes);
  const n = highs.length;
  if (n < 3) throw new Error('Yang-Zhang trenger minst tre perioder.');
  const on = [];
  const oc = [];
  let rs = 0;
  for (let i = 1; i < n; i++) {
    on.push(Math.log(opens[i] / closes[i - 1]));
    oc.push(Math.log(closes[i] / opens[i]));
    rs += rsTerm(opens[i], highs[i], lows[i], closes[i]);
  }
  const m = on.length;
  const k = 0.34 / (1.34 + (m + 1) / (m - 1));
  const s2 = Math.max(sampleVariance(on) + k * sampleVariance(oc) + (1 - k) * rs / m, 0);
  return { sigma: Math.sqrt(s2 * periodsPerYear), sigmaPeriod: Math.sqrt(s2), n: m, k };
}

// --- Konfidensintervall ---------------------------------------------------------------------------

// Kvantil i kjikvadratfordelingen med k frihetsgrader.
export function chi2inv(p, k) {
  if (!(p > 0 && p < 1)) throw new Error('Sannsynligheten må ligge strengt mellom 0 og 1.');
  if (!(k > 0)) throw new Error('Antall frihetsgrader må være positivt.');
  // Wilson-Hilferty som startpunkt, deretter Brent på et intervall med fortegnsskifte.
  const z = cndInv(p);
  const a = 2 / (9 * k);
  let x0 = k * Math.max(1 - a + z * Math.sqrt(a), 0.01) ** 3;
  if (!(x0 > 0)) x0 = 0.5 * k;
  const f = (x) => chi2cdf(x, k) - p;
  let lo = x0;
  let hi = x0;
  while (f(lo) > 0 && lo > 1e-300) lo /= 2;
  while (f(hi) < 0) hi *= 2;
  return brent(f, lo, hi, { tol: 1e-14 * Math.max(1, x0) });
}

// (n − 1)σ̂²/σ² ~ χ²(n − 1): σ̂√((n−1)/χ²_{1−α/2}) ≤ σ ≤ σ̂√((n−1)/χ²_{α/2}).
export function volConfidenceInterval({ sigma, n, conf = 0.95 }) {
  if (!(n >= 2)) throw new Error('Trenger minst to observasjoner.');
  if (!(conf > 0 && conf < 1)) throw new Error('Konfidensnivået må ligge strengt mellom 0 og 1.');
  const df = n - 1;
  const alpha = 1 - conf;
  return {
    lower: sigma * Math.sqrt(df / chi2inv(1 - alpha / 2, df)),
    upper: sigma * Math.sqrt(df / chi2inv(alpha / 2, df)),
  };
}

// --- Implisitt volatilitet: tilnærminger -------------------------------------------------------------
// Alle uttrykt med diskontert forward: S' = S e^{(b−r)T}, X' = X e^{−rT}. En put gjøres om til call
// med put-call-pariteten.
export function impliedVolApproximations({ type = 'call', S, X, T, r, b, price }) {
  const sc = S * Math.exp((b - r) * T);
  const xd = X * Math.exp(-r * T);
  const c = isCall(type) ? price : price + sc - xd;
  const k = Math.sqrt(2 * Math.PI / T);
  const brennerSubrahmanyam = k * c / sc;
  const h = c - 0.5 * (sc - xd);
  const disc = h * h - (sc - xd) ** 2 / Math.PI;
  const corradoMiller = k / (sc + xd) * (h + Math.sqrt(Math.max(disc, 0)));
  const delta = 0.5 * (sc - xd);
  const bcs = k * (c - delta) / (sc - delta);
  const manasterKoehler = Math.sqrt(Math.abs(Math.log(S / X) + b * T) * 2 / T);
  let exact = NaN;
  try {
    exact = impliedVolGBSM({ type, S, X, T, r, b, price });
  } catch {
    exact = NaN;
  }
  return { exact, brennerSubrahmanyam, corradoMiller, bcs, manasterKoehler, cmNegativeRoot: disc < 0 };
}

// --- Implisitt forward-volatilitet ---------------------------------------------------------------
// Total varians er additiv: σ_F² (T2 − T1) = σ2² T2 − σ1² T1.
export function impliedForwardVol({ v1, T1, v2, T2 }) {
  if (!(T1 > 0 && T2 > T1)) throw new Error('Løpetidene må oppfylle 0 < T1 < T2.');
  const fv = (v2 * v2 * T2 - v1 * v1 * T1) / (T2 - T1);
  if (fv < 0) throw new Error('Total varians avtar med løpetiden, så forward-variansen blir negativ (kalenderarbitrasje).');
  return Math.sqrt(fv);
}

// --- Korrelasjon -----------------------------------------------------------------------------------

export function pearson(x, y) {
  const mx = mean(x);
  const my = mean(y);
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < x.length; i++) {
    sxy += (x[i] - mx) * (y[i] - my);
    sxx += (x[i] - mx) ** 2;
    syy += (y[i] - my) ** 2;
  }
  if (!(sxx > 0 && syy > 0)) throw new Error('Minst én av rekkene har ingen variasjon.');
  return sxy / Math.sqrt(sxx * syy);
}

// Historisk korrelasjon mellom logavkastningene, med Fishers z-intervall: atanh(ρ̂) ± z_{α/2}/√(n − 3).
export function historicalCorrelation(prices1, prices2, conf = 0.95, periodsPerYear = 252) {
  checkPrices(prices1, 'Prisrekke 1', 5);
  checkPrices(prices2, 'Prisrekke 2', 5);
  if (prices1.length !== prices2.length) throw new Error('Prisrekkene må ha like mange tall.');
  if (!(conf > 0 && conf < 1)) throw new Error('Konfidensnivået må ligge strengt mellom 0 og 1.');
  const u1 = logReturns(prices1);
  const u2 = logReturns(prices2);
  const n = u1.length;
  const rho = pearson(u1, u2);
  const z = Math.atanh(rho);
  const zc = cndInv(1 - (1 - conf) / 2);
  const se = 1 / Math.sqrt(n - 3);
  return {
    rho,
    lower: Math.tanh(z - zc * se),
    upper: Math.tanh(z + zc * se),
    n,
    tStat: rho * Math.sqrt((n - 2) / (1 - rho * rho)),
    v1: Math.sqrt(sampleVariance(u1) * periodsPerYear),
    v2: Math.sqrt(sampleVariance(u2) * periodsPerYear),
  };
}

// Hypergeometrisk ₂F₁(a, b; c; z) ved rekke, |z| < 1.
function hyp2f1(a, b, c, z) {
  let term = 1;
  let sum = 1;
  for (let k = 0; k < 500000; k++) {
    term *= (a + k) * (b + k) / ((c + k) * (k + 1)) * z;
    sum += term;
    if (Math.abs(term) < 1e-17 * Math.abs(sum)) break;
  }
  return sum;
}

// Eksakt tetthet til empirisk korrelasjon ρ̂ fra n par fra en binormal fordeling med korrelasjon ρ:
//   f(r) = (n−2)Γ(n−1)(1−ρ²)^{(n−1)/2}(1−r²)^{(n−4)/2} / (√(2π) Γ(n−½) (1−ρr)^{n−3/2})
//          · ₂F₁(½, ½; n − ½; (1 + ρr)/2)
export function corrDensity(r, rho, n) {
  if (!(n >= 3)) throw new Error('Trenger minst tre observasjonspar.');
  if (!(rho > -1 && rho < 1)) throw new Error('Den sanne korrelasjonen må ligge strengt mellom −1 og 1.');
  if (!(r > -1 && r < 1)) return 0;
  const logF = Math.log(n - 2) + lnGamma(n - 1) + 0.5 * (n - 1) * Math.log1p(-rho * rho) +
    0.5 * (n - 4) * Math.log1p(-r * r) - 0.5 * Math.log(2 * Math.PI) - lnGamma(n - 0.5) -
    (n - 1.5) * Math.log1p(-rho * r);
  return Math.exp(logF) * hyp2f1(0.5, 0.5, n - 0.5, 0.5 * (1 + rho * r));
}

// Integrerer tettheten i Fishers z-rom (r = tanh ζ), der den er glatt og nesten normal.
function corrIntegrate(rho, n, upperR, g) {
  if (upperR <= -1) return 0;
  const zr = Math.atanh(rho);
  const zu = upperR >= 1 ? Infinity : Math.atanh(upperR);
  const width = n > 3 ? Math.max(38 / (n - 2), 10 / Math.sqrt(n - 3)) : 40;
  const lo = Math.min(zr, Number.isFinite(zu) ? zu : zr) - width;
  const hi = Math.min(zu, Math.max(zr, lo) + width);
  if (!(hi > lo)) return 0;
  const f = (z) => {
    const r = Math.tanh(z);
    const c = 1 / Math.cosh(z);
    return corrDensity(r, rho, n) * c * c * g(r);
  };
  return gaussLegendreComposite(f, lo, hi, 48, 16);
}

export function corrCdf(r, rho, n) {
  if (r >= 1) return 1;
  return Math.min(1, Math.max(0, corrIntegrate(rho, n, r, () => 1)));
}

export function corrMean(rho, n) {
  return corrIntegrate(rho, n, 1, (r) => r);
}

// Implisitt korrelasjon fra tre valutavolatiliteter. Krysskursen er S1/S2 eller S1·S2:
//   S1/S2: σ₁₂² = σ₁² + σ₂² − 2ρσ₁σ₂,   S1·S2: σ₁₂² = σ₁² + σ₂² + 2ρσ₁σ₂.
export function impliedCorrelationFX({ v1, v2, v12, cross = 'ratio' }) {
  if (!(v1 > 0 && v2 > 0 && v12 >= 0)) throw new Error('Volatilitetene må være positive.');
  const num = v1 * v1 + v2 * v2 - v12 * v12;
  const rho = (cross === 'product' ? -num : num) / (2 * v1 * v2);
  if (rho > 1 + 1e-12 || rho < -1 - 1e-12) {
    throw new Error('Volatilitetene er innbyrdes inkonsistente: de gir en korrelasjon utenfor [−1, 1].');
  }
  return Math.max(-1, Math.min(1, rho));
}

// Gjennomsnittlig implisitt indekskorrelasjon (lik parvis korrelasjon ρ̄):
//   σ_I² = Σ w_i²σ_i² + ρ̄ Σ_{i≠j} w_i w_j σ_i σ_j.
export function impliedIndexCorrelation({ vIndex, weights, vols }) {
  if (!Array.isArray(weights) || !Array.isArray(vols) || weights.length !== vols.length || weights.length < 2) {
    throw new Error('Trenger like mange vekter og volatiliteter, minst to av hver.');
  }
  if (vols.some((x) => !(x >= 0))) throw new Error('Volatilitetene kan ikke være negative.');
  let own = 0;
  let lin = 0;
  for (let i = 0; i < vols.length; i++) {
    own += (weights[i] * vols[i]) ** 2;
    lin += weights[i] * vols[i];
  }
  const cross = lin * lin - own;
  if (!(Math.abs(cross) > 0)) throw new Error('Kryssleddene er null, så korrelasjonen er ikke bestemt.');
  return { rho: (vIndex * vIndex - own) / cross, vIndexUncorrelated: Math.sqrt(own), vIndexPerfect: Math.abs(lin) };
}

// --- Variance swap -----------------------------------------------------------------------------
// Rettferdig variansstrike ved replikasjon med OTM-opsjoner rundt forwarden F = S e^{bT}:
//   K_var = (2 e^{rT}/T) [∫₀^F P(K)/K² dK + ∫_F^∞ C(K)/K² dK]
// `vol(K)` gir smilet; standard er lineær skjevhet σ(K) = σ₀ − skew·(K − F)/F (Demeterfi m.fl.),
// som gir tilnærmingen K_var ≈ σ₀²(1 + 3T·skew²).
export function varianceSwapStrike({ S, T, r, b, vAtm, skew = 0, vol, minVol = 0.005 }) {
  if (!(T > 0)) throw new Error('Løpetiden må være positiv.');
  const F = S * Math.exp(b * T);
  const smile = vol ?? ((K) => Math.max(vAtm - skew * (K - F) / F, minVol));
  const g = (y, type) => {
    const K = F * Math.exp(y);
    return gbsm({ type, S, X: K, T, r, b, v: smile(K) }) * Math.exp(-y);
  };
  let vmax = 0;
  for (let y = -6; y <= 6; y += 0.05) vmax = Math.max(vmax, smile(F * Math.exp(y)));
  const L = Math.min(14 * vmax * Math.sqrt(T) + 0.5, 40);
  const puts = gaussLegendreComposite((y) => g(y, 'put'), -L, 0, 64, 16);
  const calls = gaussLegendreComposite((y) => g(y, 'call'), 0, L, 64, 16);
  const kvar = 2 * Math.exp(r * T) / (T * F) * (puts + calls);
  return { kvar, kvol: Math.sqrt(kvar), approx: vAtm * vAtm * (1 + 3 * T * skew * skew), F };
}
