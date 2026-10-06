// Kapittel 1–2: Generalisert Black-Scholes-Merton (GBSM), spesialtilfellene,
// modellene før Black-Scholes, alle analytiske Greeks og implisitt volatilitet.
//
// Felles notasjon (som i Haug):
//   S spot, X innløsningskurs, T tid til forfall i år, r risikofri rente,
//   b cost of carry, v volatilitet (σ). type = 'call' | 'put'.
//   b = r       Black-Scholes (1973), aksje uten utbytte
//   b = r − q   Merton (1973), kontinuerlig utbytte q
//   b = 0       Black (1976), opsjoner på futures/forwards
//   b = 0, r = 0  Asay (1982), opsjoner på futures med margin
//   b = r − rf  Garman og Kohlhagen (1983), valutaopsjoner

import { cnd, nd, cndInv } from '../math/normal.js';
import { brent } from '../math/solvers.js';

export function isCall(type) {
  if (type === 'call' || type === 'c') return true;
  if (type === 'put' || type === 'p') return false;
  throw new Error(`Ukjent opsjonstype: ${type}`);
}

export function d1d2(S, X, T, b, v) {
  const vst = v * Math.sqrt(T);
  const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / vst;
  return [d1, d1 - vst];
}

// Generalisert Black-Scholes-Merton.
export function gbsm({ type = 'call', S, X, T, r, b, v }) {
  const call = isCall(type);
  if (T <= 0) return Math.max(call ? S - X : X - S, 0);
  const carry = Math.exp((b - r) * T);
  const disc = Math.exp(-r * T);
  if (v <= 0) {
    const fwd = S * carry - X * disc;
    return Math.max(call ? fwd : -fwd, 0);
  }
  const [d1, d2] = d1d2(S, X, T, b, v);
  if (call) return S * carry * cnd(d1) - X * disc * cnd(d2);
  return X * disc * cnd(-d2) - S * carry * cnd(-d1);
}

export const blackScholes = ({ type, S, X, T, r, v }) => gbsm({ type, S, X, T, r, b: r, v });
export const merton73 = ({ type, S, X, T, r, q, v }) => gbsm({ type, S, X, T, r, b: r - q, v });
export const black76 = ({ type, F, X, T, r, v }) => gbsm({ type, S: F, X, T, r, b: 0, v });
export const asay82 = ({ type, F, X, T, v }) => gbsm({ type, S: F, X, T, r: 0, b: 0, v });
export const garmanKohlhagen = ({ type, S, X, T, r, rf, v }) => gbsm({ type, S, X, T, r, b: r - rf, v });

// Put-call-paritet: c − p = S e^{(b−r)T} − X e^{−rT}.
export function putCallParity({ given = 'call', price, S, X, T, r, b }) {
  const fwdPv = S * Math.exp((b - r) * T) - X * Math.exp(-r * T);
  return isCall(given) ? price - fwdPv : price + fwdPv;
}

// --- Før Black-Scholes-Merton -------------------------------------------------

// Bachelier (normalfordelt underliggende) med diskontering: σn er absolutt volatilitet
// i prisenheter per √år. Med r = b = 0 får man Bacheliers originalformel fra 1900.
export function bachelier({ type = 'call', S, X, T, r = 0, b = 0, v }) {
  const call = isCall(type);
  const F = S * Math.exp(b * T);
  const disc = Math.exp(-r * T);
  const sd = v * Math.sqrt(T);
  if (sd <= 0) return disc * Math.max(call ? F - X : X - F, 0);
  const d = (F - X) / sd;
  if (call) return disc * ((F - X) * cnd(d) + sd * nd(d));
  return disc * ((X - F) * cnd(-d) + sd * nd(d));
}

// Sprenkle (1964): ρ er forventet vekstrate i aksjen, k grad av risikoaversjon.
export function sprenkle({ type = 'call', S, X, T, rho, k, v }) {
  const vst = v * Math.sqrt(T);
  const d1 = (Math.log(S / X) + (rho + 0.5 * v * v) * T) / vst;
  const d2 = d1 - vst;
  if (isCall(type)) return S * Math.exp(rho * T) * cnd(d1) - (1 - k) * X * cnd(d2);
  return (1 - k) * X * cnd(-d2) - S * Math.exp(rho * T) * cnd(-d1);
}

// Boness (1964): ρ er forventet avkastning på aksjen.
export function boness({ type = 'call', S, X, T, rho, v }) {
  const vst = v * Math.sqrt(T);
  const d1 = (Math.log(S / X) + (rho + 0.5 * v * v) * T) / vst;
  const d2 = d1 - vst;
  if (isCall(type)) return S * cnd(d1) - X * Math.exp(-rho * T) * cnd(d2);
  return X * Math.exp(-rho * T) * cnd(-d2) - S * cnd(-d1);
}

// Samuelson (1965): ρ forventet avkastning på aksjen, w forventet avkastning på opsjonen.
export function samuelson({ type = 'call', S, X, T, rho, w, v }) {
  const vst = v * Math.sqrt(T);
  const d1 = (Math.log(S / X) + (rho + 0.5 * v * v) * T) / vst;
  const d2 = d1 - vst;
  if (isCall(type)) return S * Math.exp((rho - w) * T) * cnd(d1) - X * Math.exp(-w * T) * cnd(d2);
  return X * Math.exp(-w * T) * cnd(-d2) - S * Math.exp((rho - w) * T) * cnd(-d1);
}

// --- Greeks (kapittel 2) --------------------------------------------------------
// Tidsderivater (theta, charm, color, veta, dZeta/dt) er per år når kalendertiden går,
// dvs. −∂/∂T. Rho flytter r og b sammen (b = r − q med q fast). Carry rho er ∂/∂b
// med r fast, phi er ∂/∂q = −carry rho.

export function gbsmGreeks({ type = 'call', S, X, T, r, b, v }) {
  const call = isCall(type);
  const sqT = Math.sqrt(T);
  const vst = v * sqT;
  const [d1, d2] = d1d2(S, X, T, b, v);
  const carry = Math.exp((b - r) * T);
  const disc = Math.exp(-r * T);
  const n1 = nd(d1);
  const n2 = nd(d2);
  const N1 = cnd(d1);
  const N2 = cnd(d2);
  const Nm1 = cnd(-d1);
  const Nm2 = cnd(-d2);

  const price = call ? S * carry * N1 - X * disc * N2 : X * disc * Nm2 - S * carry * Nm1;
  const delta = call ? carry * N1 : -carry * Nm1;
  const vanna = -carry * d2 / v * n1;
  const dvannaDvol = vanna * (1 / v) * (d1 * d2 - d1 / d2 - 1);
  const charmCommon = n1 * (b / vst - d2 / (2 * T));
  const charm = call ? -carry * (charmCommon + (b - r) * N1) : -carry * (charmCommon - (b - r) * Nm1);
  const elasticity = delta * S / price;

  const gamma = carry * n1 / (S * vst);
  const gammaP = S * gamma / 100;
  const zomma = gamma * (d1 * d2 - 1) / v;
  const zommaP = gammaP * (d1 * d2 - 1) / v;
  const speed = -gamma * (1 + d1 / vst) / S;
  const speedP = -gammaP * d1 / (S * vst);
  const color = gamma * (r - b + b * d1 / vst + (1 - d1 * d2) / (2 * T));
  const colorP = gammaP * (r - b + b * d1 / vst + (1 - d1 * d2) / (2 * T));

  const vega = S * carry * n1 * sqT;
  const vegaP = v / 10 * vega;
  const vegaLeverage = vega * v / price;
  const vomma = vega * d1 * d2 / v;
  const vommaP = vegaP * d1 * d2 / v;
  const ultima = vomma * (1 / v) * (d1 * d2 - d1 / d2 - d2 / d1 - 1);
  const veta = vega * (r - b + b * d1 / vst - (1 + d1 * d2) / (2 * T));

  const varianceVega = S * carry * n1 * sqT / (2 * v);
  const ddeltaDvar = -carry * n1 * d2 / (2 * v * v);
  const varianceVomma = S * carry * sqT / (4 * v ** 3) * n1 * (d1 * d2 - 1);
  const varianceUltima = S * carry * sqT / (8 * v ** 5) * n1 * ((d1 * d2 - 1) * (d1 * d2 - 3) - (d1 * d1 + d2 * d2));

  const driftlessTheta = -S * carry * n1 * v / (2 * sqT);
  const theta = call
    ? driftlessTheta - (b - r) * S * carry * N1 - r * X * disc * N2
    : driftlessTheta + (b - r) * S * carry * Nm1 + r * X * disc * Nm2;

  const rho = call ? T * X * disc * N2 : -T * X * disc * Nm2;
  const futuresRho = -T * price;
  const carryRho = call ? T * S * carry * N1 : -T * S * carry * Nm1;
  const phi = -carryRho;

  const itmProb = call ? N2 : Nm2;
  const dzetaDvol = call ? -n2 * d1 / v : n2 * d1 / v;
  const dzetaDtime = (call ? -1 : 1) * n2 * (b / vst - d1 / (2 * T));
  const rnd = disc * n2 / (X * vst);
  const strikeDelta = call ? -disc * N2 : disc * Nm2;

  return {
    price, delta, vanna, dvannaDvol, charm, elasticity,
    gamma, gammaP, zomma, zommaP, speed, speedP, color, colorP,
    vega, vegaP, vegaLeverage, vomma, vommaP, ultima, veta,
    varianceVega, ddeltaDvar, varianceVomma, varianceUltima,
    theta, thetaDay: theta / 365, driftlessTheta,
    rho, futuresRho, carryRho, phi,
    itmProb, dzetaDvol, dzetaDtime, rnd, strikeDelta,
    hitProb: probabilityOfEverInTheMoney({ type, S, X, T, b, v }),
    deltaMirrorStrike: S * S / X * Math.exp((2 * b + v * v) * T),
    maxGammaSpot: X * Math.exp((-b - 1.5 * v * v) * T),
    maxVegaSpot: X * Math.exp((-b + 0.5 * v * v) * T),
    d1, d2,
  };
}

// Sannsynlighet (risikonøytral) for at spot noen gang før T kommer i pengene.
export function probabilityOfEverInTheMoney({ type = 'call', S, X, T, b, v }) {
  const call = isCall(type);
  if ((call && S >= X) || (!call && S <= X)) return 1;
  const mu = b - 0.5 * v * v;
  const vst = v * Math.sqrt(T);
  const lnHS = Math.log(X / S);
  const k = 2 * mu / (v * v);
  if (call) {
    // P(maks ≥ X), X > S
    return cnd((-lnHS + mu * T) / vst) + Math.exp(k * lnHS) * cnd((-lnHS - mu * T) / vst);
  }
  // P(min ≤ X), X < S, lnHS < 0
  return cnd((lnHS - mu * T) / vst) + Math.exp(k * lnHS) * cnd((lnHS + mu * T) / vst);
}

// Innløsningskurs som gir en gitt delta (call: 0 < Δ < e^{(b−r)T}, put: −e^{(b−r)T} < Δ < 0).
export function strikeFromDelta({ type = 'call', S, T, r, b, v, delta }) {
  const carryInv = Math.exp((r - b) * T);
  const vst = v * Math.sqrt(T);
  if (isCall(type)) {
    const p = delta * carryInv;
    if (!(p > 0 && p < 1)) throw new Error('Delta for en call må ligge mellom 0 og e^{(b−r)T}.');
    return S * Math.exp(-cndInv(p) * vst + (b + 0.5 * v * v) * T);
  }
  const p = -delta * carryInv;
  if (!(p > 0 && p < 1)) throw new Error('Delta for en put må ligge mellom −e^{(b−r)T} og 0.');
  return S * Math.exp(cndInv(p) * vst + (b + 0.5 * v * v) * T);
}

// ATM-forward-tilnærminger (X = S e^{bT}).
export function atmForwardApprox({ S, T, r, b, v }) {
  const carry = Math.exp((b - r) * T);
  const sqT = Math.sqrt(T);
  const k = 1 / Math.sqrt(2 * Math.PI);
  return {
    price: k * S * carry * v * sqT,
    deltaCall: carry * (0.5 + 0.5 * k * v * sqT),
    deltaPut: -carry * (0.5 - 0.5 * k * v * sqT),
    gamma: k * carry / (S * v * sqT),
    vega: k * S * carry * sqT,
    thetaDriftless: -k * S * carry * v / (2 * sqT),
  };
}

// --- Implisitt volatilitet --------------------------------------------------------

export function impliedVolGBSM({ type = 'call', S, X, T, r, b, price }, { lo = 1e-7, hi = 10 } = {}) {
  const call = isCall(type);
  const carry = Math.exp((b - r) * T);
  const disc = Math.exp(-r * T);
  const lower = Math.max(call ? S * carry - X * disc : X * disc - S * carry, 0);
  const upper = call ? S * carry : X * disc;
  if (!(price > lower && price < upper)) {
    throw new Error('Prisen ligger utenfor arbitrasjegrensene, så ingen volatilitet gir denne prisen.');
  }
  const f = (sig) => gbsm({ type, S, X, T, r, b, v: sig }) - price;
  // Newton-start fra Brenner–Subrahmanyam, deretter Brent som sikkerhetsnett.
  let sig = Math.sqrt(2 * Math.PI / T) * price / (S * carry);
  if (!(sig > lo && sig < hi)) sig = 0.3;
  for (let i = 0; i < 50; i++) {
    const g = gbsmGreeks({ type, S, X, T, r, b, v: sig });
    const diff = g.price - price;
    if (Math.abs(diff) < 1e-12) return sig;
    if (!(g.vega > 1e-10)) break;
    const next = sig - diff / g.vega;
    if (!(next > lo && next < hi)) break;
    if (Math.abs(next - sig) < 1e-13) return next;
    sig = next;
  }
  return brent(f, lo, hi, { tol: 1e-14 });
}
