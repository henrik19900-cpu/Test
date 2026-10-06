// Kapittel 4: Lookback-opsjoner med kontinuerlig overvåking.
//   Flytende innløsningskurs: Goldman, Sosin og Gatto (1979)
//   Fast innløsningskurs: Conze og Viswanathan (1991)
//   Delvis lookback (partial-time), flytende og fast: Heynen og Kat (1994)
//   Extreme spread og omvendt extreme spread: Bermin (1996)
//
// Observert minimum/maksimum som er «passert» av spot, oppdateres til spot (S_min = min(S_min, S),
// S_max = max(S_max, S)), slik at prisen er definert for alle S. Leddene σ²/(2b)·[…] har en hevbar
// singularitet i b = 0, som håndteres med regularInB.

import { cnd, cbnd } from '../math/normal.js';
import { isCall } from './bsm.js';
import { powCnd, powTimes, regularInB } from './exotics.js';

function checkPositive(T) {
  if (!(T > 0)) throw new Error('Tid til forfall T må være positiv.');
}

// --- Flytende innløsningskurs -------------------------------------------------------------
// Call: S_T − min, put: max − S_T.

function floatingCall(S, Smin, T, r, b, v) {
  const vst = v * Math.sqrt(T);
  const a1 = (Math.log(S / Smin) + (b + 0.5 * v * v) * T) / vst;
  const a2 = a1 - vst;
  const k = v * v / (2 * b);
  const reflect = powCnd(S / Smin, -2 * b / (v * v), -a1 + 2 * b * Math.sqrt(T) / v);
  return S * Math.exp((b - r) * T) * cnd(a1) - Smin * Math.exp(-r * T) * cnd(a2)
    + S * Math.exp(-r * T) * k * (reflect - Math.exp(b * T) * cnd(-a1));
}

function floatingPut(S, Smax, T, r, b, v) {
  const vst = v * Math.sqrt(T);
  const b1 = (Math.log(S / Smax) + (b + 0.5 * v * v) * T) / vst;
  const b2 = b1 - vst;
  const k = v * v / (2 * b);
  const reflect = powCnd(S / Smax, -2 * b / (v * v), b1 - 2 * b * Math.sqrt(T) / v);
  return Smax * Math.exp(-r * T) * cnd(-b2) - S * Math.exp((b - r) * T) * cnd(-b1)
    + S * Math.exp(-r * T) * k * (-reflect + Math.exp(b * T) * cnd(b1));
}

export function floatingStrikeLookback({ type, S, Smin = S, Smax = S, T, r, b, v }) {
  checkPositive(T);
  if (isCall(type)) {
    const m = Math.min(Smin, S);
    return regularInB((bb) => floatingCall(S, m, T, r, bb, v), b);
  }
  const M = Math.max(Smax, S);
  return regularInB((bb) => floatingPut(S, M, T, r, bb, v), b);
}

// --- Fast innløsningskurs -----------------------------------------------------------------
// Call: max(S_max − X, 0), put: max(X − S_min, 0).

function fixedCall(S, X, Smax, T, r, b, v) {
  const vst = v * Math.sqrt(T);
  const k = v * v / (2 * b);
  const df = Math.exp(-r * T);
  const carry = S * Math.exp((b - r) * T);
  if (X > Smax) {
    const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / vst;
    const d2 = d1 - vst;
    return carry * cnd(d1) - X * df * cnd(d2)
      + S * df * k * (-powCnd(S / X, -2 * b / (v * v), d1 - 2 * b * Math.sqrt(T) / v) + Math.exp(b * T) * cnd(d1));
  }
  const e1 = (Math.log(S / Smax) + (b + 0.5 * v * v) * T) / vst;
  const e2 = e1 - vst;
  return df * (Smax - X) + carry * cnd(e1) - Smax * df * cnd(e2)
    + S * df * k * (-powCnd(S / Smax, -2 * b / (v * v), e1 - 2 * b * Math.sqrt(T) / v) + Math.exp(b * T) * cnd(e1));
}

function fixedPut(S, X, Smin, T, r, b, v) {
  const vst = v * Math.sqrt(T);
  const k = v * v / (2 * b);
  const df = Math.exp(-r * T);
  const carry = S * Math.exp((b - r) * T);
  if (X < Smin) {
    const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / vst;
    const d2 = d1 - vst;
    return X * df * cnd(-d2) - carry * cnd(-d1)
      + S * df * k * (powCnd(S / X, -2 * b / (v * v), -d1 + 2 * b * Math.sqrt(T) / v) - Math.exp(b * T) * cnd(-d1));
  }
  const f1 = (Math.log(S / Smin) + (b + 0.5 * v * v) * T) / vst;
  const f2 = f1 - vst;
  return df * (X - Smin) - carry * cnd(-f1) + Smin * df * cnd(-f2)
    + S * df * k * (powCnd(S / Smin, -2 * b / (v * v), -f1 + 2 * b * Math.sqrt(T) / v) - Math.exp(b * T) * cnd(-f1));
}

export function fixedStrikeLookback({ type, S, X, Smin = S, Smax = S, T, r, b, v }) {
  checkPositive(T);
  if (isCall(type)) {
    const M = Math.max(Smax, S);
    return regularInB((bb) => fixedCall(S, X, M, T, r, bb, v), b);
  }
  const m = Math.min(Smin, S);
  return regularInB((bb) => fixedPut(S, X, m, T, r, bb, v), b);
}

// --- Delvis lookback med flytende innløsningskurs (Heynen og Kat 1994) -----------------------
// Lookback-perioden er [0, t1], forfall T > t1. Call: max(S_T − λ·S_min, 0) (typisk λ ≥ 1),
// put: max(λ·S_max − S_T, 0) (typisk λ ≤ 1).

function partialFloatingCall(S, Smin, lambda, t1, T, r, b, v) {
  const sT = v * Math.sqrt(T);
  const st1 = v * Math.sqrt(t1);
  const tau = T - t1;
  const stau = v * Math.sqrt(tau);
  const d1 = (Math.log(S / Smin) + (b + 0.5 * v * v) * T) / sT;
  const d2 = d1 - sT;
  const f1 = (Math.log(S / Smin) + (b + 0.5 * v * v) * t1) / st1;
  const f2 = f1 - st1;
  const e1 = (b + 0.5 * v * v) * tau / stau;
  const e2 = e1 - stau;
  const g1 = Math.log(lambda) / sT;
  const g2 = Math.log(lambda) / stau;
  const rho = Math.sqrt(t1 / T);
  const rho2 = Math.sqrt(1 - t1 / T);
  const k = v * v / (2 * b);
  const q = 2 * b / (v * v);
  const carry = S * Math.exp((b - r) * T);
  const df = Math.exp(-r * T);
  return carry * cnd(d1 - g1) - lambda * Smin * df * cnd(d2 - g1)
    + S * df * lambda * k * (
      powTimes(S / Smin, -q, cbnd(-f1 + 2 * b * Math.sqrt(t1) / v, -d1 + 2 * b * Math.sqrt(T) / v - g1, rho))
      - Math.exp(b * T) * powTimes(lambda, q, cbnd(-d1 - g1, e1 + g2, -rho2)))
    + carry * cbnd(-d1 + g1, e1 - g2, -rho2)
    + lambda * Smin * df * cbnd(-f2, d2 - g1, -rho)
    - Math.exp(-b * tau) * (1 + k) * lambda * carry * cnd(e2 - g2) * cnd(-f1);
}

function partialFloatingPut(S, Smax, lambda, t1, T, r, b, v) {
  const sT = v * Math.sqrt(T);
  const st1 = v * Math.sqrt(t1);
  const tau = T - t1;
  const stau = v * Math.sqrt(tau);
  const d1 = (Math.log(S / Smax) + (b + 0.5 * v * v) * T) / sT;
  const d2 = d1 - sT;
  const f1 = (Math.log(S / Smax) + (b + 0.5 * v * v) * t1) / st1;
  const f2 = f1 - st1;
  const e1 = (b + 0.5 * v * v) * tau / stau;
  const e2 = e1 - stau;
  const g1 = Math.log(lambda) / sT;
  const g2 = Math.log(lambda) / stau;
  const rho = Math.sqrt(t1 / T);
  const rho2 = Math.sqrt(1 - t1 / T);
  const k = v * v / (2 * b);
  const q = 2 * b / (v * v);
  const carry = S * Math.exp((b - r) * T);
  const df = Math.exp(-r * T);
  return lambda * Smax * df * cnd(-d2 + g1) - carry * cnd(-d1 + g1)
    + S * df * lambda * k * (
      -powTimes(S / Smax, -q, cbnd(f1 - 2 * b * Math.sqrt(t1) / v, d1 - 2 * b * Math.sqrt(T) / v + g1, rho))
      + Math.exp(b * T) * powTimes(lambda, q, cbnd(d1 + g1, -e1 - g2, -rho2)))
    - carry * cbnd(d1 - g1, -e1 + g2, -rho2)
    - lambda * Smax * df * cbnd(f2, -d2 + g1, -rho)
    + Math.exp(-b * tau) * (1 + k) * lambda * carry * cnd(-e2 + g2) * cnd(f1);
}

function checkPartial(t1, T) {
  checkPositive(T);
  if (!(t1 > 0 && t1 < T)) throw new Error('Tidspunktet t1 må ligge strengt mellom 0 og forfall T.');
}

export function partialFloatingLookback({ type, S, Smin = S, Smax = S, lambda = 1, t1, T, r, b, v }) {
  checkPartial(t1, T);
  if (!(lambda > 0)) throw new Error('Multiplikatoren λ må være positiv.');
  if (isCall(type)) {
    const m = Math.min(Smin, S);
    return regularInB((bb) => partialFloatingCall(S, m, lambda, t1, T, r, bb, v), b);
  }
  const M = Math.max(Smax, S);
  return regularInB((bb) => partialFloatingPut(S, M, lambda, t1, T, r, bb, v), b);
}

// --- Delvis lookback med fast innløsningskurs (Heynen og Kat 1994) --------------------------
// Lookback-perioden er [t1, T]. Call: max(maks over [t1, T] − X, 0), put: max(X − min over [t1, T], 0).

function partialFixed(call, S, X, t1, T, r, b, v) {
  const sT = v * Math.sqrt(T);
  const st1 = v * Math.sqrt(t1);
  const tau = T - t1;
  const stau = v * Math.sqrt(tau);
  const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / sT;
  const d2 = d1 - sT;
  const f1 = (Math.log(S / X) + (b + 0.5 * v * v) * t1) / st1;
  const f2 = f1 - st1;
  const e1 = (b + 0.5 * v * v) * tau / stau;
  const e2 = e1 - stau;
  const rho = Math.sqrt(t1 / T);
  const rho2 = Math.sqrt(1 - t1 / T);
  const k = v * v / (2 * b);
  const q = 2 * b / (v * v);
  const carry = S * Math.exp((b - r) * T);
  const df = Math.exp(-r * T);
  const tail = Math.exp(-b * tau) * (1 - k) * carry;
  if (call) {
    return carry * cnd(d1) - X * df * cnd(d2)
      + S * df * k * (
        -powTimes(S / X, -q, cbnd(d1 - 2 * b * Math.sqrt(T) / v, -f1 + 2 * b * Math.sqrt(t1) / v, -rho))
        + Math.exp(b * T) * cbnd(e1, d1, rho2))
      - carry * cbnd(-e1, d1, -rho2)
      - X * df * cbnd(f2, -d2, -rho)
      + tail * cnd(f1) * cnd(-e2);
  }
  return X * df * cnd(-d2) - carry * cnd(-d1)
    + S * df * k * (
      powTimes(S / X, -q, cbnd(-d1 + 2 * b * Math.sqrt(T) / v, f1 - 2 * b * Math.sqrt(t1) / v, -rho))
      - Math.exp(b * T) * cbnd(-e1, -d1, rho2))
    + carry * cbnd(e1, -d1, -rho2)
    + X * df * cbnd(-f2, d2, -rho)
    - tail * cnd(-f1) * cnd(e2);
}

export function partialFixedLookback({ type, S, X, t1, T, r, b, v }) {
  checkPartial(t1, T);
  const call = isCall(type);
  return regularInB((bb) => partialFixed(call, S, X, t1, T, r, bb, v), b);
}

// --- Extreme spread (Bermin 1996) -------------------------------------------------------------
// Perioden [0, T] deles ved t1. M1/m1 er maks/min i første periode (inkludert det som er observert
// så langt), M2/m2 i andre periode [t1, T].
//   'call'          max(M2 − M1, 0)   extreme spread call
//   'put'           max(m1 − m2, 0)   extreme spread put
//   'reverse-call'  max(m2 − m1, 0)   omvendt extreme spread call
//   'reverse-put'   max(M1 − M2, 0)   omvendt extreme spread put
// Lukket form via (M2 − M1)⁺ = max(M1, M2) − M1 osv., dvs. lookback-formlene over [0, T] og [0, t1]
// samt en flytende lookback over [t1, T] som starter i S_{t1}.
export const EXTREME_SPREAD_KINDS = ['call', 'put', 'reverse-call', 'reverse-put'];

export function extremeSpread({ kind, S, Smin = S, Smax = S, t1, T, r, b, v }) {
  if (!EXTREME_SPREAD_KINDS.includes(kind)) throw new Error(`Ukjent type: ${kind}`);
  checkPartial(t1, T);
  const tau = T - t1;
  const M = Math.max(Smax, S);
  const m = Math.min(Smin, S);
  const p = { S, T, r, b, v };
  switch (kind) {
    case 'call':
      return fixedStrikeLookback({ ...p, type: 'call', X: M, Smax: M })
        - Math.exp(-r * tau) * fixedStrikeLookback({ ...p, T: t1, type: 'call', X: M, Smax: M });
    case 'put':
      return fixedStrikeLookback({ ...p, type: 'put', X: m, Smin: m })
        - Math.exp(-r * tau) * fixedStrikeLookback({ ...p, T: t1, type: 'put', X: m, Smin: m });
    case 'reverse-call': {
      // e^{−rT}E[m2] − e^{−rT}E[min(m, min over [0, T])]
      const em2 = S * Math.exp((b - r) * t1)
        * (Math.exp((b - r) * tau) - floatingStrikeLookback({ type: 'call', S: 1, Smin: 1, T: tau, r, b, v }));
      const emin = Math.exp(-r * T) * m - fixedStrikeLookback({ ...p, type: 'put', X: m, Smin: m });
      return em2 - emin;
    }
    default: {
      // e^{−rT}E[max(M, maks over [0, T])] − e^{−rT}E[M2]
      const emax = Math.exp(-r * T) * M + fixedStrikeLookback({ ...p, type: 'call', X: M, Smax: M });
      const eM2 = S * Math.exp((b - r) * t1)
        * (Math.exp((b - r) * tau) + floatingStrikeLookback({ type: 'put', S: 1, Smax: 1, T: tau, r, b, v }));
      return emax - eM2;
    }
  }
}
