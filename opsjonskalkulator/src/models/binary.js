// Kapittel 4.19 i Haug (2007): binære opsjoner.
//   gapOption            Reiner og Rubinstein (1991)
//   cashOrNothing        Reiner og Rubinstein (1991)
//   assetOrNothing       Cox og Rubinstein (1985)
//   supershare           Hakansson (1976)
//   binaryBarrier        Reiner og Rubinstein (1991): de 28 typene i bokas tabell
//   doubleBarrierBinary  Hui (1996): dobbel-barriere binære, også asymmetriske varianter
//
// Notasjon som i boka: S spot, X innløsningskurs, K kontantbeløp, H barriere, L/U nedre/øvre
// barriere, T tid, r rente, b cost of carry, v volatilitet σ.

import { cnd } from '../math/normal.js';
import { isCall, d1d2 } from './bsm.js';
import { expCnd, ikedaKunitomoProb } from './barriers.js';

function checkCommon({ S, T, v }) {
  if (!(S > 0)) throw new Error('Spotprisen S må være positiv.');
  if (!(v > 0)) throw new Error('Volatiliteten σ må være positiv.');
  if (!(T >= 0)) throw new Error('Tid til forfall T kan ikke være negativ.');
}

// --- Enkle binære opsjoner ---------------------------------------------------------

// Gap-opsjon: call betaler S_T − X2 hvis S_T > X1, put betaler X2 − S_T hvis S_T < X1.
export function gapOption({ type = 'call', S, X1, X2, T, r, b, v }) {
  const call = isCall(type);
  checkCommon({ S, T, v });
  if (!(X1 > 0)) throw new Error('Utløsningskursen X1 må være positiv.');
  if (T === 0) return call ? (S > X1 ? S - X2 : 0) : (S < X1 ? X2 - S : 0);
  const [d1, d2] = d1d2(S, X1, T, b, v);
  const share = S * Math.exp((b - r) * T);
  const cash = X2 * Math.exp(-r * T);
  return call ? share * cnd(d1) - cash * cnd(d2) : cash * cnd(-d2) - share * cnd(-d1);
}

// Cash-or-nothing: betaler K hvis S_T > X (call) eller S_T < X (put).
export function cashOrNothing({ type = 'call', S, X, K, T, r, b, v }) {
  const call = isCall(type);
  checkCommon({ S, T, v });
  if (!(X > 0)) throw new Error('Innløsningskursen X må være positiv.');
  if (T === 0) return (call ? S > X : S < X) ? K : 0;
  const [, d2] = d1d2(S, X, T, b, v);
  return K * Math.exp(-r * T) * cnd(call ? d2 : -d2);
}

// Asset-or-nothing: betaler S_T hvis S_T > X (call) eller S_T < X (put).
export function assetOrNothing({ type = 'call', S, X, T, r, b, v }) {
  const call = isCall(type);
  checkCommon({ S, T, v });
  if (!(X > 0)) throw new Error('Innløsningskursen X må være positiv.');
  if (T === 0) return (call ? S > X : S < X) ? S : 0;
  const [d1] = d1d2(S, X, T, b, v);
  return S * Math.exp((b - r) * T) * cnd(call ? d1 : -d1);
}

// Supershare: betaler S_T / XL hvis XL ≤ S_T < XH.
export function supershare({ S, XL, XH, T, r, b, v }) {
  checkCommon({ S, T, v });
  if (!(XL > 0 && XH > XL)) throw new Error('Grensene må oppfylle 0 < XL < XH.');
  if (T === 0) return S >= XL && S < XH ? S / XL : 0;
  const [d1] = d1d2(S, XL, T, b, v);
  const [d2] = d1d2(S, XH, T, b, v);
  return S * Math.exp((b - r) * T) / XL * (cnd(d1) - cnd(d2));
}

// --- Binære barriereopsjoner (Reiner og Rubinstein 1991) ----------------------------

// Typene 1–28 i bokas tabell. Odde numre har ned-barriere (S > H), like numre opp-barriere.
export const BINARY_BARRIER_TYPES = [
  { kind: 1, label: 'Ned-og-inn, kontant K ved treff' },
  { kind: 2, label: 'Opp-og-inn, kontant K ved treff' },
  { kind: 3, label: 'Ned-og-inn, aktiva ved treff (verdi H)' },
  { kind: 4, label: 'Opp-og-inn, aktiva ved treff (verdi H)' },
  { kind: 5, label: 'Ned-og-inn, kontant K ved forfall' },
  { kind: 6, label: 'Opp-og-inn, kontant K ved forfall' },
  { kind: 7, label: 'Ned-og-inn, aktiva ved forfall' },
  { kind: 8, label: 'Opp-og-inn, aktiva ved forfall' },
  { kind: 9, label: 'Ned-og-ut, kontant K ved forfall' },
  { kind: 10, label: 'Opp-og-ut, kontant K ved forfall' },
  { kind: 11, label: 'Ned-og-ut, aktiva ved forfall' },
  { kind: 12, label: 'Opp-og-ut, aktiva ved forfall' },
  { kind: 13, label: 'Ned-og-inn cash-or-nothing call' },
  { kind: 14, label: 'Opp-og-inn cash-or-nothing call' },
  { kind: 15, label: 'Ned-og-inn asset-or-nothing call' },
  { kind: 16, label: 'Opp-og-inn asset-or-nothing call' },
  { kind: 17, label: 'Ned-og-inn cash-or-nothing put' },
  { kind: 18, label: 'Opp-og-inn cash-or-nothing put' },
  { kind: 19, label: 'Ned-og-inn asset-or-nothing put' },
  { kind: 20, label: 'Opp-og-inn asset-or-nothing put' },
  { kind: 21, label: 'Ned-og-ut cash-or-nothing call' },
  { kind: 22, label: 'Opp-og-ut cash-or-nothing call' },
  { kind: 23, label: 'Ned-og-ut asset-or-nothing call' },
  { kind: 24, label: 'Opp-og-ut asset-or-nothing call' },
  { kind: 25, label: 'Ned-og-ut cash-or-nothing put' },
  { kind: 26, label: 'Opp-og-ut cash-or-nothing put' },
  { kind: 27, label: 'Ned-og-ut asset-or-nothing put' },
  { kind: 28, label: 'Opp-og-ut asset-or-nothing put' },
];

// Leddene A1–A5 og B1–B4 i boka for gitt η (1 ned, −1 opp) og φ (1 call, −1 put).
function bbTerms(eta, phi, S, X, H, K, T, r, b, v) {
  const v2 = v * v;
  const vst = v * Math.sqrt(T);
  const mu = (b - v2 / 2) / v2;
  const lnHS = Math.log(H / S);
  const lnShare = Math.log(S) + (b - r) * T;
  const share = Math.exp(lnShare);
  const cash = K * Math.exp(-r * T);
  const x1 = Math.log(S / X) / vst + (mu + 1) * vst;
  const x2 = -lnHS / vst + (mu + 1) * vst;
  const y1 = (2 * lnHS + Math.log(S / X)) / vst + (mu + 1) * vst;
  const y2 = lnHS / vst + (mu + 1) * vst;
  const pS = lnShare + 2 * (mu + 1) * lnHS;
  const pX = 2 * mu * lnHS;
  const t = {
    A1: share * cnd(phi * x1),
    B1: cash * cnd(phi * (x1 - vst)),
    A2: share * cnd(phi * x2),
    B2: cash * cnd(phi * (x2 - vst)),
    A3: expCnd(pS, eta * y1),
    B3: cash * expCnd(pX, eta * (y1 - vst)),
    A4: expCnd(pS, eta * y2),
    B4: cash * expCnd(pX, eta * (y2 - vst)),
  };
  // A5: K betalt ved treff, K·E[e^{−rτ}; τ ≤ T].
  t.A5 = (Km) => {
    const lam2 = mu * mu + 2 * r / v2;
    if (lam2 < 0) throw new Error('Betaling ved treff krever μ² + 2r/σ² ≥ 0 (for negativ rente r).');
    const lam = Math.sqrt(lam2);
    const z = lnHS / vst + lam * vst;
    return Km * (expCnd((mu + lam) * lnHS, eta * z) + expCnd((mu - lam) * lnHS, eta * (z - 2 * lam * vst)));
  };
  return t;
}

export function binaryBarrier({ kind = 1, S, X, H, K, T, r, b, v }) {
  const n = Number(kind);
  if (!(Number.isInteger(n) && n >= 1 && n <= 28)) throw new Error(`Ukjent type binær barriereopsjon: ${kind}`);
  checkCommon({ S, T, v });
  if (!(H > 0)) throw new Error('Barrieren H må være positiv.');
  if (n >= 13 && !(X > 0)) throw new Error('Innløsningskursen X må være positiv.');
  const down = n % 2 === 1;
  const eta = down ? 1 : -1;
  const hit = down ? S <= H : S >= H;
  const disc = Math.exp(-r * T);
  const carry = Math.exp((b - r) * T);
  // Spot allerede forbi barrieren: inn-typene er slått inn, ut-typene er verdiløse.
  if (hit) {
    if (n <= 2) return K;
    if (n <= 4) return S;
    if (n <= 6) return K * disc;
    if (n <= 8) return S * carry;
    if (n <= 12 || n >= 21) return 0;
    const call = n <= 16;
    const cashType = n === 13 || n === 14 || n === 17 || n === 18;
    const type = call ? 'call' : 'put';
    return cashType ? cashOrNothing({ type, S, X, K, T, r, b, v }) : assetOrNothing({ type, S, X, T, r, b, v });
  }
  if (T === 0) {
    if (n <= 8) return 0;
    const alive = n <= 12 || n >= 21;
    if (!alive) return 0;
    if (n <= 12) return n <= 10 ? K : S;
    const call = n <= 24;
    const cashType = [21, 22, 25, 26].includes(n);
    const itm = call ? S > X : S < X;
    return itm ? (cashType ? K : S) : 0;
  }
  const xGtH = X > H;
  const P = bbTerms(eta, 1, S, X, H, K, T, r, b, v); // φ = 1
  const M = bbTerms(eta, -1, S, X, H, K, T, r, b, v); // φ = −1
  switch (n) {
    case 1: case 2: return P.A5(K);
    case 3: case 4: return P.A5(H);
    case 5: return M.B2 + M.B4;
    case 6: return P.B2 + P.B4;
    case 7: return M.A2 + M.A4;
    case 8: return P.A2 + P.A4;
    case 9: return P.B2 - P.B4;
    case 10: return M.B2 - M.B4;
    case 11: return P.A2 - P.A4;
    case 12: return M.A2 - M.A4;
    case 13: return xGtH ? P.B3 : P.B1 - P.B2 + P.B4;
    case 14: return xGtH ? P.B1 : P.B2 - P.B3 + P.B4;
    case 15: return xGtH ? P.A3 : P.A1 - P.A2 + P.A4;
    case 16: return xGtH ? P.A1 : P.A2 - P.A3 + P.A4;
    case 17: return xGtH ? M.B2 - M.B3 + M.B4 : M.B1;
    case 18: return xGtH ? M.B1 - M.B2 + M.B4 : M.B3;
    case 19: return xGtH ? M.A2 - M.A3 + M.A4 : M.A1;
    case 20: return xGtH ? M.A1 - M.A2 + M.A4 : M.A3;
    case 21: return xGtH ? P.B1 - P.B3 : P.B2 - P.B4;
    case 22: return xGtH ? 0 : P.B1 - P.B2 + P.B3 - P.B4;
    case 23: return xGtH ? P.A1 - P.A3 : P.A2 - P.A4;
    case 24: return xGtH ? 0 : P.A1 - P.A2 + P.A3 - P.A4;
    case 25: return xGtH ? M.B1 - M.B2 + M.B3 - M.B4 : 0;
    case 26: return xGtH ? M.B2 - M.B4 : M.B1 - M.B3;
    case 27: return xGtH ? M.A1 - M.A2 + M.A3 - M.A4 : 0;
    default: return xGtH ? M.A2 - M.A4 : M.A1 - M.A3;
  }
}

// --- Dobbel-barriere binære opsjoner (Hui 1996) -------------------------------------
//
// x = ln(S/L), Z = ln(U/L). Knock-out betaler K ved forfall hvis verken L eller U er truffet
// (Huis egenfunksjonsrekke). For små σ√T/Z konvergerer bilderekken (Ikeda–Kunitomo med flate
// barrierer) raskere; begge er eksakte. De asymmetriske variantene betaler K hvis øvre
// (eller nedre) barriere treffes først, enten ved treff eller ved forfall.

export const DOUBLE_BINARY_KINDS = ['ko', 'ki', 'touch', 'upper-hit', 'lower-hit', 'upper-exp', 'lower-exp'];

// Huis formel: verdien av K ved forfall hvis ingen barriere er truffet.
export function huiKnockOut({ S, L, U, K, T, r, b, v }) {
  const v2 = v * v;
  const Z = Math.log(U / L);
  const alpha = -0.5 * (2 * b / v2 - 1);
  const beta = -0.25 * (2 * b / v2 - 1) ** 2 - 2 * r / v2;
  const x = Math.log(S / L);
  const fL = Math.pow(S / L, alpha);
  const fU = Math.pow(S / U, alpha);
  const scale = 1 + Math.abs(fL) + Math.abs(fU);
  let sum = 0;
  for (let i = 1; i <= 200000; i++) {
    const k = i * Math.PI / Z;
    const decay = Math.exp(-0.5 * (k * k - beta) * v2 * T);
    const sign = i % 2 === 0 ? 1 : -1; // (−1)^i
    sum += 2 * Math.PI * i * K / (Z * Z) * (fL - sign * fU) / (alpha * alpha + k * k) * Math.sin(k * x) * decay;
    if (i > 3 && Math.exp(-0.5 * k * k * v2 * T) * scale < 1e-18) break;
  }
  return sum;
}

// sinh(γp)/sinh(γq) for 0 ≤ p ≤ q uten overflow.
function sinhRatio(gamma, p, q) {
  if (gamma * q < 1e-8) return p / q;
  return Math.exp(gamma * (p - q)) * Math.expm1(-2 * gamma * p) / Math.expm1(-2 * gamma * q);
}

// E[e^{−ρτ}; barrieren (øvre hvis upper) treffes først og før T], ρ = rate.
export function firstHitValue({ upper, S, L, U, T, b, v, rate }) {
  const v2 = v * v;
  const c = (b - v2 / 2) / v2;
  const Z = Math.log(U / L);
  const x = Math.log(S / L);
  const g2 = (c * c * v2 + 2 * rate) / v2; // γ² = (ν² + 2ρσ²)/σ⁴
  if (g2 < 0) throw new Error('Betaling ved treff krever ν² + 2rσ² ≥ 0 (for negativ rente r).');
  const gamma = Math.sqrt(g2);
  const lnGirsanov = upper ? c * (Z - x) : -c * x;
  const sdT = v * Math.sqrt(T);
  if (sdT / Z < 0.5) {
    // Bilderekke: summen av førstepasseringsverdier for speilede startpunkter.
    const psi = (a) => expCnd(lnGirsanov - gamma * a, (-a + gamma * v2 * T) / sdT)
      + expCnd(lnGirsanov + gamma * a, (-a - gamma * v2 * T) / sdT);
    const dist = (n) => (upper ? (2 * n + 1) * Z - x : x + 2 * n * Z);
    const term = (n) => {
      const a = dist(n);
      return a === 0 ? 0 : Math.sign(a) * psi(Math.abs(a));
    };
    let sum = term(0);
    for (let n = 1; n <= 1000; n++) {
      const pair = term(n) + term(-n);
      sum += pair;
      if (n >= 2 && Math.abs(pair) < 1e-18) break;
    }
    return sum;
  }
  // Egenfunksjonsrekke: uendelig horisont minus bidraget fra treff etter T.
  const inf = Math.exp(lnGirsanov) * (upper ? sinhRatio(gamma, x, Z) : sinhRatio(gamma, Z - x, Z));
  let sum = 0;
  for (let n = 1; n <= 200000; n++) {
    const k = n * Math.PI / Z;
    const decay = Math.exp(-0.5 * v2 * (k * k + g2) * T);
    const sign = upper ? (n % 2 === 1 ? 1 : -1) : 1;
    sum += sign * k / (g2 + k * k) * Math.sin(k * x) * decay;
    if (n > 3 && decay < 1e-18) break;
  }
  return inf - 2 / Z * Math.exp(lnGirsanov) * sum;
}

export function doubleBarrierBinary({ kind = 'ko', S, L, U, K, T, r, b, v }) {
  if (!DOUBLE_BINARY_KINDS.includes(kind)) throw new Error(`Ukjent type dobbel-barriere binær: ${kind}`);
  checkCommon({ S, T, v });
  if (!(L > 0 && U > L)) throw new Error('Barrierene må oppfylle 0 < L < U.');
  const disc = Math.exp(-r * T);
  if (S <= L || S >= U) {
    const upperHit = S >= U;
    switch (kind) {
      case 'ko': return 0;
      case 'ki': return K * disc;
      case 'touch': return K;
      case 'upper-hit': return upperHit ? K : 0;
      case 'lower-hit': return upperHit ? 0 : K;
      case 'upper-exp': return upperHit ? K * disc : 0;
      default: return upperHit ? 0 : K * disc;
    }
  }
  if (T === 0) return kind === 'ko' ? K : 0;
  const knockOut = () => (v * Math.sqrt(T) / Math.log(U / L) >= 0.1
    ? huiKnockOut({ S, L, U, K, T, r, b, v })
    : K * disc * ikedaKunitomoProb({ S, lo: L, hi: U, L, U, T, b, v, share: false }));
  const hit = (upper, rate) => firstHitValue({ upper, S, L, U, T, b, v, rate });
  switch (kind) {
    case 'ko': return knockOut();
    case 'ki': return K * disc - knockOut();
    case 'touch': return K * (hit(true, r) + hit(false, r));
    case 'upper-hit': return K * hit(true, r);
    case 'lower-hit': return K * hit(false, r);
    case 'upper-exp': return K * disc * hit(true, 0);
    default: return K * disc * hit(false, 0);
  }
}
