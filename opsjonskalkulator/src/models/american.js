// Kapittel 3: Analytiske tilnærminger for amerikanske opsjoner.
//
//   bawAmerican          Barone-Adesi og Whaley (1987), kvadratisk tilnærming
//   bsAmerican1993       Bjerksund og Stensland (1993), flat innløsningsgrense
//   bsAmerican2002       Bjerksund og Stensland (2002), grense i to trinn
//   perpetualAmerican    Evigvarende opsjoner, McKean (1965) og Merton (1973)
//   putCallTransform     P(S, X, T, r, b, σ) = C(X, S, T, r − b, −b, σ)
//
// Notasjon som i Haug: S spot, X innløsningskurs, T tid i år, r rente, b cost of carry,
// v volatilitet, type 'call' | 'put'. Alle funksjonene returnerer et objekt med
// minst { price, european, premium }.

import { cnd, cbnd } from '../math/normal.js';
import { brent } from '../math/solvers.js';
import { gbsm, isCall } from './bsm.js';

function checkInputs({ S, X, T, v }) {
  if (!(S > 0) || !(X > 0)) throw new Error('Spot og innløsningskurs må være positive.');
  if (!(T >= 0)) throw new Error('Tid til forfall kan ikke være negativ.');
  if (!(v > 0)) throw new Error('Volatiliteten må være positiv.');
}

// Put-call-transformasjonen for amerikanske opsjoner (Bjerksund og Stensland 1993):
// en put med (S, X, r, b) har samme verdi som en call med (X, S, r − b, −b).
export function putCallTransform({ S, X, T, r, b, v }) {
  return { S: X, X: S, T, r: r - b, b: -b, v };
}

function result(price, european, extra = {}) {
  return { price, european, premium: price - european, ...extra };
}

// ---------------------------------------------------------------------------
// Barone-Adesi og Whaley (1987)
// ---------------------------------------------------------------------------

// 2r / (σ² (1 − e^{−rT})), med grenseverdien 2 / (σ² T) når r = 0.
function mOverK(r, T, v2) {
  if (Math.abs(r * T) < 1e-12) return 2 / (v2 * T);
  return 2 * r / (v2 * -Math.expm1(-r * T));
}

function d1Of(S, X, T, b, v) {
  return (Math.log(S / X) + (b + 0.5 * v * v) * T) / (v * Math.sqrt(T));
}

// Kritisk spotpris S* for BAW-call: S* − X = c(S*) + (1 − e^{(b−r)T} N(d1(S*))) S*/q2.
export function bawCriticalCall({ X, T, r, b, v }) {
  const v2 = v * v;
  const nn = 2 * b / v2;
  const q2 = (-(nn - 1) + Math.sqrt((nn - 1) ** 2 + 4 * mOverK(r, T, v2))) / 2;
  const carry = Math.exp((b - r) * T);
  const f = (s) => s - X - gbsm({ type: 'call', S: s, X, T, r, b, v }) - (1 - carry * cnd(d1Of(s, X, T, b, v))) * s / q2;
  let hi = 2 * X;
  for (let i = 0; i < 200 && f(hi) <= 0; i++) hi *= 1.5;
  if (!(f(hi) > 0)) throw new Error('Fant ikke kritisk pris i Barone-Adesi-Whaley.');
  const crit = brent(f, X, hi, { tol: 1e-12 * X });
  return { crit, q2 };
}

// Kritisk spotpris S** for BAW-put: X − S** = p(S**) − (1 − e^{(b−r)T} N(−d1(S**))) S**/q1.
export function bawCriticalPut({ X, T, r, b, v }) {
  const v2 = v * v;
  const nn = 2 * b / v2;
  const q1 = (-(nn - 1) - Math.sqrt((nn - 1) ** 2 + 4 * mOverK(r, T, v2))) / 2;
  const carry = Math.exp((b - r) * T);
  const f = (s) => X - s - gbsm({ type: 'put', S: s, X, T, r, b, v }) + (1 - carry * cnd(-d1Of(s, X, T, b, v))) * s / q1;
  let lo = 0.5 * X;
  for (let i = 0; i < 400 && f(lo) <= 0; i++) lo *= 0.5;
  if (!(f(lo) > 0)) throw new Error('Fant ikke kritisk pris i Barone-Adesi-Whaley.');
  const crit = brent(f, lo, X, { tol: 1e-12 * X });
  return { crit, q1 };
}

export function bawAmerican(p) {
  checkInputs(p);
  const { type = 'call', S, X, T, r, b, v } = p;
  const call = isCall(type);
  const european = gbsm({ type, S, X, T, r, b, v });
  // critical = null betyr at tidlig innløsning aldri lønner seg.
  if (T === 0) return result(european, european, { critical: X });
  // Call: aldri tidlig innløsning når b ≥ r. Put: aldri tidlig innløsning når r ≤ 0.
  if (call && b >= r) return result(european, european, { critical: null });
  if (!call && r <= 0) return result(european, european, { critical: null });
  const carry = Math.exp((b - r) * T);
  if (call) {
    const { crit, q2 } = bawCriticalCall({ X, T, r, b, v });
    if (S >= crit) return result(S - X, european, { critical: crit });
    const A2 = (crit / q2) * (1 - carry * cnd(d1Of(crit, X, T, b, v)));
    return result(european + A2 * (S / crit) ** q2, european, { critical: crit });
  }
  const { crit, q1 } = bawCriticalPut({ X, T, r, b, v });
  if (S <= crit) return result(X - S, european, { critical: crit });
  const A1 = -(crit / q1) * (1 - carry * cnd(-d1Of(crit, X, T, b, v)));
  return result(european + A1 * (S / crit) ** q1, european, { critical: crit });
}

// ---------------------------------------------------------------------------
// Bjerksund og Stensland (1993 og 2002)
// ---------------------------------------------------------------------------

// Grensefunksjonen I(T) = B0 + (B∞ − B0)(1 − e^{h(T)}) krever h(T) ≤ 0, dvs. bT + 2σ√T ≥ 0.
// Med negativ carry (call) eller positiv carry (put) og svært lang løpetid brytes dette.
const LONG_T = 'Bjerksund-Stensland-tilnærmingen er ikke gyldig her: med denne cost of carry er løpetiden for lang (krever bT + 2σ√T ≥ 0 i call-formen).';

function bsBeta(r, b, v2) {
  const disc = (b / v2 - 0.5) ** 2 + 2 * r / v2;
  if (!(disc >= 0)) throw new Error('Tilnærmingen er ikke definert for denne kombinasjonen av negativ rente og cost of carry.');
  const beta = 0.5 - b / v2 + Math.sqrt(disc);
  if (!(beta > 1)) throw new Error('Tilnærmingen er ikke definert for denne kombinasjonen av rente og cost of carry.');
  return beta;
}

// φ(S, T, γ, H, I): verdien av et krav som betaler S_T^γ hvis S_T ≤ H og S aldri har nådd I.
function phi(S, T, gamma, H, I, r, b, v) {
  const v2 = v * v;
  const sq = v * Math.sqrt(T);
  const lambda = (-r + gamma * b + 0.5 * gamma * (gamma - 1) * v2) * T;
  const d = -(Math.log(S / H) + (b + (gamma - 0.5) * v2) * T) / sq;
  const kappa = 2 * b / v2 + (2 * gamma - 1);
  return Math.exp(lambda) * S ** gamma * (cnd(d) - (I / S) ** kappa * cnd(d - 2 * Math.log(I / S) / sq));
}

// ψ(S, T, γ, H, I2, I1, t1): som φ, men med grense I2 på [0, t1] og I1 på [t1, T].
function psi(S, T, gamma, H, I2, I1, t1, r, b, v) {
  const v2 = v * v;
  const mu = b + (gamma - 0.5) * v2;
  const s1 = v * Math.sqrt(t1);
  const sT = v * Math.sqrt(T);
  const e1 = (Math.log(S / I1) + mu * t1) / s1;
  const e2 = (Math.log(I2 * I2 / (S * I1)) + mu * t1) / s1;
  const e3 = (Math.log(S / I1) - mu * t1) / s1;
  const e4 = (Math.log(I2 * I2 / (S * I1)) - mu * t1) / s1;
  const f1 = (Math.log(S / H) + mu * T) / sT;
  const f2 = (Math.log(I2 * I2 / (S * H)) + mu * T) / sT;
  const f3 = (Math.log(I1 * I1 / (S * H)) + mu * T) / sT;
  const f4 = (Math.log(S * I1 * I1 / (H * I2 * I2)) + mu * T) / sT;
  const rho = Math.sqrt(t1 / T);
  const lambda = -r + gamma * b + 0.5 * gamma * (gamma - 1) * v2;
  const kappa = 2 * b / v2 + (2 * gamma - 1);
  return Math.exp(lambda * T) * S ** gamma * (
    cbnd(-e1, -f1, rho)
    - (I2 / S) ** kappa * cbnd(-e2, -f2, rho)
    - (I1 / S) ** kappa * cbnd(-e3, -f3, -rho)
    + (I1 / I2) ** kappa * cbnd(-e4, -f4, -rho));
}

function bs1993Call(S, X, T, r, b, v) {
  const european = gbsm({ type: 'call', S, X, T, r, b, v });
  if (b >= r || T === 0) return { price: european, european, boundary: null };
  const v2 = v * v;
  const beta = bsBeta(r, b, v2);
  const Binf = beta / (beta - 1) * X;
  const B0 = Math.max(X, r / (r - b) * X);
  const hT = -(b * T + 2 * v * Math.sqrt(T)) * B0 / (Binf - B0);
  if (!(hT <= 0)) throw new Error(LONG_T);
  const I = B0 + (Binf - B0) * -Math.expm1(hT);
  if (S >= I) return { price: S - X, european, boundary: I };
  const alpha = (I - X) * I ** -beta;
  const price = alpha * S ** beta
    - alpha * phi(S, T, beta, I, I, r, b, v)
    + phi(S, T, 1, I, I, r, b, v)
    - phi(S, T, 1, X, I, r, b, v)
    - X * phi(S, T, 0, I, I, r, b, v)
    + X * phi(S, T, 0, X, I, r, b, v);
  return { price, european, boundary: I };
}

function bs2002Call(S, X, T, r, b, v) {
  const european = gbsm({ type: 'call', S, X, T, r, b, v });
  if (b >= r || T === 0) return { price: european, european, I1: null, I2: null, t1: null };
  const v2 = v * v;
  const t1 = 0.5 * (Math.sqrt(5) - 1) * T;
  const beta = bsBeta(r, b, v2);
  const Binf = beta / (beta - 1) * X;
  const B0 = Math.max(X, r / (r - b) * X);
  const scale = X * X / ((Binf - B0) * B0);
  const h1 = -(b * t1 + 2 * v * Math.sqrt(t1)) * scale;
  const h2 = -(b * T + 2 * v * Math.sqrt(T)) * scale;
  if (!(h2 <= 0)) throw new Error(LONG_T);
  const I1 = B0 + (Binf - B0) * -Math.expm1(h1);
  const I2 = B0 + (Binf - B0) * -Math.expm1(h2);
  if (S >= I2) return { price: S - X, european, I1, I2, t1 };
  const a1 = (I1 - X) * I1 ** -beta;
  const a2 = (I2 - X) * I2 ** -beta;
  const ph = (TT, g, H, I) => phi(S, TT, g, H, I, r, b, v);
  const ps = (g, H) => psi(S, T, g, H, I2, I1, t1, r, b, v);
  const price = a2 * S ** beta
    - a2 * ph(t1, beta, I2, I2)
    + ph(t1, 1, I2, I2)
    - ph(t1, 1, I1, I2)
    - X * ph(t1, 0, I2, I2)
    + X * ph(t1, 0, I1, I2)
    + a1 * ph(t1, beta, I1, I2)
    - a1 * ps(beta, I1)
    + ps(1, I1)
    - ps(1, X)
    - X * ps(0, I1)
    + X * ps(0, X);
  return { price, european, I1, I2, t1 };
}

// Bjerksund og Stensland (1993). Put via put-call-transformasjonen.
// boundary er den flate innløsningsgrensen (for put: i det opprinnelige spotrommet).
export function bsAmerican1993(p) {
  checkInputs(p);
  const { type = 'call', S, X, T, r, b, v } = p;
  if (isCall(type)) {
    const c = bs1993Call(S, X, T, r, b, v);
    return result(c.price, c.european, { boundary: c.boundary });
  }
  const q = putCallTransform({ S, X, T, r, b, v });
  const c = bs1993Call(q.S, q.X, q.T, q.r, q.b, q.v);
  // Call-grensen I i transformert rom svarer til put-grensen S·X / I.
  return result(c.price, c.european, { boundary: c.boundary === null ? null : S * X / c.boundary });
}

// Bjerksund og Stensland (2002). Put via put-call-transformasjonen.
// I2 er grensen fra nå til t1, I1 grensen fra t1 til forfall.
export function bsAmerican2002(p) {
  checkInputs(p);
  const { type = 'call', S, X, T, r, b, v } = p;
  if (isCall(type)) {
    const c = bs2002Call(S, X, T, r, b, v);
    return result(c.price, c.european, { I1: c.I1, I2: c.I2, t1: c.t1 });
  }
  const q = putCallTransform({ S, X, T, r, b, v });
  const c = bs2002Call(q.S, q.X, q.T, q.r, q.b, q.v);
  if (c.I1 === null) return result(c.price, c.european, { I1: null, I2: null, t1: null });
  return result(c.price, c.european, { I1: S * X / c.I1, I2: S * X / c.I2, t1: c.t1 });
}

// ---------------------------------------------------------------------------
// Evigvarende amerikanske opsjoner
// ---------------------------------------------------------------------------

export function perpetualAmerican({ type = 'call', S, X, r, b, v }) {
  if (!(S > 0) || !(X > 0)) throw new Error('Spot og innløsningskurs må være positive.');
  if (!(v > 0)) throw new Error('Volatiliteten må være positiv.');
  const v2 = v * v;
  const disc = (b / v2 - 0.5) ** 2 + 2 * r / v2;
  if (isCall(type)) {
    if (!(b < r)) throw new Error('En evigvarende call krever b < r; ellers lønner det seg aldri å innløse, og verdien er ikke endelig.');
    if (!(disc >= 0)) throw new Error('Ingen løsning for denne kombinasjonen av rente og cost of carry.');
    const y1 = 0.5 - b / v2 + Math.sqrt(disc);
    if (!(y1 > 1)) throw new Error('Ingen løsning for denne kombinasjonen av rente og cost of carry.');
    const boundary = y1 / (y1 - 1) * X;
    const price = S >= boundary ? S - X : X / (y1 - 1) * ((y1 - 1) / y1 * S / X) ** y1;
    return { price, boundary, exponent: y1 };
  }
  if (!(r > 0)) throw new Error('En evigvarende put krever positiv rente r.');
  const y2 = 0.5 - b / v2 - Math.sqrt(disc);
  const boundary = y2 / (y2 - 1) * X;
  const price = S <= boundary ? X - S : X / (1 - y2) * ((y2 - 1) / y2 * S / X) ** y2;
  return { price, boundary, exponent: y2 };
}
