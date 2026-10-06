// Kapittel 5: eksotiske opsjoner på to underliggende.
//
// Notasjon som i Haug: S1, S2 spotpriser, b1, b2 cost of carry, v1, v2 volatiliteter,
// rho korrelasjonen mellom avkastningene, r risikofri rente, T tid til forfall.
// Q1, Q2 er antall enheter i bytteopsjoner. type = 'call' | 'put'.
//
// Mange av formlene følger av et numerairebytte: med aktivum 2 som numeraire er
// forholdet P = S1/S2 en geometrisk brownsk bevegelse med cost of carry b1 − b2,
// «rente» r − b2 og volatilitet σ = √(σ1² + σ2² − 2ρσ1σ2). En opsjon på P ganget med S2
// gir da Margrabe-, amerikanske bytte-, bytte-på-bytte- og Margrabe-barriereopsjoner.

import { cnd, cbnd } from '../math/normal.js';
import { brent } from '../math/solvers.js';
import { gaussLegendreComposite } from '../math/integrate.js';
import { gbsm, isCall } from './bsm.js';

// Volatiliteten til forholdet S1/S2.
export function ratioVol(v1, v2, rho) {
  return Math.sqrt(Math.max(0, v1 * v1 + v2 * v2 - 2 * rho * v1 * v2));
}

function requireRatioVol(v) {
  if (!(v > 1e-12)) {
    throw new Error('Forholdet S1/S2 har null volatilitet (σ1 = σ2 og ρ = 1), så formelen er ikke definert.');
  }
}

// --- Relative outperformance-opsjoner og produktopsjoner -------------------------

// Utbetaling max(S1/S2 − X, 0) / max(X − S1/S2, 0). Black-76 på forwarden til forholdet.
export function relativeOutperformance({ type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const v = ratioVol(v1, v2, rho);
  const F = S1 / S2 * Math.exp((b1 - b2 + v2 * v2 - rho * v1 * v2) * T);
  return { price: gbsm({ type, S: F, X, T, r, b: 0, v }), F, v };
}

// Utbetaling max(S1·S2 − X, 0) / max(X − S1·S2, 0).
export function productOption({ type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const v = Math.sqrt(Math.max(0, v1 * v1 + v2 * v2 + 2 * rho * v1 * v2));
  const F = S1 * S2 * Math.exp((b1 + b2 + rho * v1 * v2) * T);
  return { price: gbsm({ type, S: F, X, T, r, b: 0, v }), F, v };
}

// --- Two-asset correlation options (Zhang 1995) ------------------------------------

// Call: max(S2 − X2, 0) hvis S1 > X1 ved forfall. Put: max(X2 − S2, 0) hvis S1 < X1.
export function twoAssetCorrelation({ type = 'call', S1, S2, X1, X2, T, r, b1, b2, v1, v2, rho }) {
  const sT = Math.sqrt(T);
  const y1 = (Math.log(S1 / X1) + (b1 - 0.5 * v1 * v1) * T) / (v1 * sT);
  const y2 = (Math.log(S2 / X2) + (b2 - 0.5 * v2 * v2) * T) / (v2 * sT);
  const F2 = S2 * Math.exp((b2 - r) * T);
  const D = X2 * Math.exp(-r * T);
  if (isCall(type)) {
    return F2 * cbnd(y2 + v2 * sT, y1 + rho * v2 * sT, rho) - D * cbnd(y2, y1, rho);
  }
  return D * cbnd(-y2, -y1, rho) - F2 * cbnd(-y2 - v2 * sT, -y1 - rho * v2 * sT, rho);
}

// --- Bytteopsjoner ---------------------------------------------------------------

// Europeisk opsjon på å bytte Q2 enheter av S2 mot Q1 enheter av S1 (Margrabe 1978):
// utbetaling max(Q1·S1 − Q2·S2, 0).
export function exchangeOption({ S1, S2, Q1 = 1, Q2 = 1, T, r, b1, b2, v1, v2, rho }) {
  const v = ratioVol(v1, v2, rho);
  const price = gbsm({ type: 'call', S: Q1 * S1, X: Q2 * S2, T, r: r - b2, b: b1 - b2, v });
  let delta1;
  let delta2;
  if (v > 0) {
    const d1 = (Math.log(Q1 * S1 / (Q2 * S2)) + (b1 - b2 + 0.5 * v * v) * T) / (v * Math.sqrt(T));
    delta1 = Q1 * Math.exp((b1 - r) * T) * cnd(d1);
    delta2 = -Q2 * Math.exp((b2 - r) * T) * cnd(d1 - v * Math.sqrt(T));
  } else {
    const itm = Q1 * S1 * Math.exp((b1 - r) * T) > Q2 * S2 * Math.exp((b2 - r) * T);
    delta1 = itm ? Q1 * Math.exp((b1 - r) * T) : 0;
    delta2 = itm ? -Q2 * Math.exp((b2 - r) * T) : 0;
  }
  return { price, v, delta1, delta2 };
}

// Bjerksund og Stensland (1993): tilnærming for amerikanske opsjoner (flat grense).
// Put via put-call-transformasjonen P(S, X, T, r, b, σ) = C(X, S, T, r − b, −b, σ).
export function bjerksundStensland1993({ type = 'call', S, X, T, r, b, v }) {
  if (isCall(type)) return bs93Call(S, X, T, r, b, v);
  return bs93Call(X, S, T, r - b, -b, v);
}

function bs93Call(S, X, T, r, b, v) {
  if (b >= r) return gbsm({ type: 'call', S, X, T, r, b, v }); // aldri optimalt å innløse tidlig
  if (!(v > 1e-12)) return deterministicAmericanCall(S, X, T, r, b);
  const v2 = v * v;
  const disc = (b / v2 - 0.5) ** 2 + 2 * r / v2;
  if (disc < 0) throw new Error('Tilnærmingen er ikke definert for disse rentene og volatilitetene.');
  const beta = 0.5 - b / v2 + Math.sqrt(disc);
  const BInf = beta / (beta - 1) * X;
  const B0 = Math.max(X, r / (r - b) * X);
  const ht = -(b * T + 2 * v * Math.sqrt(T)) * B0 / (BInf - B0);
  const I = B0 + (BInf - B0) * (1 - Math.exp(ht));
  if (S >= I) return S - X;
  const alpha = (I - X) * I ** (-beta);
  const phi = (gamma, H) => bsPhi(S, T, gamma, H, I, r, b, v);
  return alpha * S ** beta - alpha * phi(beta, I) + phi(1, I) - phi(1, X) - X * phi(0, I) + X * phi(0, X);
}

function bsPhi(S, T, gamma, H, I, r, b, v) {
  const vst = v * Math.sqrt(T);
  const lambda = (-r + gamma * b + 0.5 * gamma * (gamma - 1) * v * v) * T;
  const d = -(Math.log(S / H) + (b + (gamma - 0.5) * v * v) * T) / vst;
  const kappa = 2 * b / (v * v) + (2 * gamma - 1);
  return Math.exp(lambda) * S ** gamma * (cnd(d) - (I / S) ** kappa * cnd(d - 2 * Math.log(I / S) / vst));
}

// Bjerksund og Stensland (2002): to flate grenser, I2 på [0, t1] og I1 på [t1, T],
// med t1 = (√5 − 1)T/2. Mer presis enn 1993-versjonen. Put via samme transformasjon.
export function bjerksundStensland2002({ type = 'call', S, X, T, r, b, v }) {
  if (isCall(type)) return bs02Call(S, X, T, r, b, v);
  return bs02Call(X, S, T, r - b, -b, v);
}

function bs02Call(S, X, T, r, b, v) {
  if (b >= r) return gbsm({ type: 'call', S, X, T, r, b, v });
  if (!(v > 1e-12)) return deterministicAmericanCall(S, X, T, r, b);
  const v2 = v * v;
  const disc = (b / v2 - 0.5) ** 2 + 2 * r / v2;
  if (disc < 0) throw new Error('Tilnærmingen er ikke definert for disse rentene og volatilitetene.');
  const beta = 0.5 - b / v2 + Math.sqrt(disc);
  const t1 = 0.5 * (Math.sqrt(5) - 1) * T;
  const BInf = beta / (beta - 1) * X;
  const B0 = Math.max(X, r / (r - b) * X);
  const h = (t) => -(b * t + 2 * v * Math.sqrt(t)) * X * X / ((BInf - B0) * B0);
  const I1 = B0 + (BInf - B0) * (1 - Math.exp(h(t1)));
  const I2 = B0 + (BInf - B0) * (1 - Math.exp(h(T)));
  if (S >= I2) return S - X;
  const alpha1 = (I1 - X) * I1 ** (-beta);
  const alpha2 = (I2 - X) * I2 ** (-beta);
  const phi = (gamma, H, I) => bsPhi(S, t1, gamma, H, I, r, b, v);
  const psi = (gamma, H) => bsPsi(S, T, gamma, H, I2, I1, t1, r, b, v);
  return alpha2 * S ** beta - alpha2 * phi(beta, I2, I2)
    + phi(1, I2, I2) - phi(1, I1, I2)
    - X * phi(0, I2, I2) + X * phi(0, I1, I2)
    + alpha1 * phi(beta, I1, I2) - alpha1 * psi(beta, I1)
    + psi(1, I1) - psi(1, X)
    - X * psi(0, I1) + X * psi(0, X);
}

// ψ: nåverdien av S_T^γ·1{S_T ≤ H} når S ikke treffer I2 før t1 og ikke I1 mellom t1 og T.
function bsPsi(S, T, gamma, H, I2, I1, t1, r, b, v) {
  const m = b + (gamma - 0.5) * v * v;
  const st1 = v * Math.sqrt(t1);
  const sT = v * Math.sqrt(T);
  const e1 = (Math.log(S / I1) + m * t1) / st1;
  const e2 = (Math.log(I2 * I2 / (S * I1)) + m * t1) / st1;
  const e3 = (Math.log(S / I1) - m * t1) / st1;
  const e4 = (Math.log(I2 * I2 / (S * I1)) - m * t1) / st1;
  const f1 = (Math.log(S / H) + m * T) / sT;
  const f2 = (Math.log(I2 * I2 / (S * H)) + m * T) / sT;
  const f3 = (Math.log(I1 * I1 / (S * H)) + m * T) / sT;
  const f4 = (Math.log(S * I1 * I1 / (H * I2 * I2)) + m * T) / sT;
  const rho = Math.sqrt(t1 / T);
  const lambda = -r + gamma * b + 0.5 * gamma * (gamma - 1) * v * v;
  const kappa = 2 * b / (v * v) + (2 * gamma - 1);
  return Math.exp(lambda * T) * S ** gamma * (
    cbnd(-e1, -f1, rho)
    - (I2 / S) ** kappa * cbnd(-e2, -f2, rho)
    - (I1 / S) ** kappa * cbnd(-e3, -f3, -rho)
    + (I1 / I2) ** kappa * cbnd(-e4, -f4, -rho));
}

// Null volatilitet: S vokser deterministisk, så velg beste innløsningstidspunkt i [0, T].
function deterministicAmericanCall(S, X, T, r, b) {
  const f = (t) => S * Math.exp((b - r) * t) - X * Math.exp(-r * t);
  const cand = [0, T];
  if (b !== 0 && r > 0) {
    const ts = Math.log(r * X / ((r - b) * S)) / b;
    if (ts > 0 && ts < T) cand.push(ts);
  }
  return Math.max(0, ...cand.map(f));
}

// Amerikansk bytteopsjon (Bjerksund og Stensland 1993): Q1·S1 − Q2·S2 når som helst før T.
// Opsjonen er en amerikansk call på forholdet med S = Q1·S1, X = Q2·S2, rente r − b2 og
// cost of carry b1 − b2. method: '1993' (flat grense) eller '2002' (to grenser).
export function americanExchangeOption({ S1, S2, Q1 = 1, Q2 = 1, T, r, b1, b2, v1, v2, rho, method = '1993' }) {
  const v = ratioVol(v1, v2, rho);
  const args = { type: 'call', S: Q1 * S1, X: Q2 * S2, T, r: r - b2, b: b1 - b2, v };
  const american = String(method) === '2002' ? bjerksundStensland2002(args) : bjerksundStensland1993(args);
  const european = gbsm(args);
  return { price: Math.max(american, european), european, v };
}

// Sammensatt opsjon (Geske 1979) med generell cost of carry. kind: 'cc' call på call,
// 'pc' put på call, 'cp' call på put, 'pp' put på put. X1 betales/mottas ved t1,
// den underliggende opsjonen har innløsningskurs X2 og forfall T2.
export function compoundOption({ kind, S, X1, X2, t1, T2, r, b, v }) {
  if (!(t1 > 0)) throw new Error('Tidspunktet t1 må være større enn null.');
  if (t1 > T2) throw new Error('Tidspunktet t1 må ligge før forfallet T2.');
  const underCall = kind[1] === 'c';
  const outerCall = kind[0] === 'c';
  const under = underCall ? 'call' : 'put';
  const tau = T2 - t1;
  const sqt1 = Math.sqrt(t1);
  const sqT2 = Math.sqrt(T2);
  const corr = Math.sqrt(t1 / T2);
  const value = (s) => gbsm({ type: under, S: s, X: X2, T: tau, r, b, v });

  let I;
  if (underCall) {
    // c(I) = X1, c øker fra 0 mot ∞.
    const hi = (X1 + X2 * Math.exp(-r * tau)) * Math.exp((r - b) * tau) * 1.01;
    I = Math.exp(brent((u) => value(Math.exp(u)) - X1, Math.log(hi) - 60, Math.log(hi), { tol: 1e-14 }));
  } else {
    // p(I) = X1, p synker fra X2·e^{−r·tau} mot 0.
    const pMax = X2 * Math.exp(-r * tau);
    if (X1 >= pMax) {
      // Den underliggende putten er aldri verdt X1: call på put utøves aldri, put på put alltid.
      if (outerCall) return { price: 0, I: 0 };
      return { price: X1 * Math.exp(-r * t1) - gbsm({ type: 'put', S, X: X2, T: T2, r, b, v }), I: 0 };
    }
    const lo = 0.5 * (pMax - X1) * Math.exp((r - b) * tau);
    let hiU = Math.log(Math.max(lo, X2)) + 1;
    for (let i = 0; i < 200 && value(Math.exp(hiU)) - X1 > 0; i++) hiU += 1;
    I = Math.exp(brent((u) => value(Math.exp(u)) - X1, Math.log(lo), hiU, { tol: 1e-14 }));
  }

  const y1 = (Math.log(S / I) + (b + 0.5 * v * v) * t1) / (v * sqt1);
  const y2 = y1 - v * sqt1;
  const z1 = (Math.log(S / X2) + (b + 0.5 * v * v) * T2) / (v * sqT2);
  const z2 = z1 - v * sqT2;
  const F = S * Math.exp((b - r) * T2);
  const D2 = X2 * Math.exp(-r * T2);
  const D1 = X1 * Math.exp(-r * t1);
  let price;
  switch (kind) {
    case 'cc': price = F * cbnd(z1, y1, corr) - D2 * cbnd(z2, y2, corr) - D1 * cnd(y2); break;
    case 'pc': price = D2 * cbnd(z2, -y2, -corr) - F * cbnd(z1, -y1, -corr) + D1 * cnd(-y2); break;
    case 'cp': price = D2 * cbnd(-z2, -y2, corr) - F * cbnd(-z1, -y1, corr) - D1 * cnd(-y2); break;
    case 'pp': price = F * cbnd(-z1, y1, -corr) - D2 * cbnd(-z2, y2, -corr) + D1 * cnd(y2); break;
    default: throw new Error(`Ukjent type sammensatt opsjon: ${kind}`);
  }
  return { price, I };
}

// Bytteopsjon på bytteopsjon (Carr 1988). Den underliggende bytteopsjonen forfaller ved T2;
// ved t1 betales eller mottas Q enheter av S2.
//   kind 'cc': rett til å betale Q·S2 ved t1 for opsjonen på å bytte S2 mot S1
//   kind 'pc': rett til å gi fra seg opsjonen på å bytte S2 mot S1 mot å få Q·S2
//   kind 'cp': rett til å betale Q·S2 ved t1 for opsjonen på å bytte S1 mot S2
//   kind 'pp': rett til å gi fra seg opsjonen på å bytte S1 mot S2 mot å få Q·S2
export function exchangeOnExchange({ kind = 'cc', S1, S2, Q, t1, T2, r, b1, b2, v1, v2, rho }) {
  const v = ratioVol(v1, v2, rho);
  requireRatioVol(v);
  const res = compoundOption({ kind, S: S1 / S2, X1: Q, X2: 1, t1, T2, r: r - b2, b: b1 - b2, v });
  const underlying = gbsm({ type: kind[1] === 'c' ? 'call' : 'put', S: S1 / S2, X: 1, T: T2, r: r - b2, b: b1 - b2, v });
  return { price: S2 * res.price, I: res.I, underlying: S2 * underlying, v };
}

// --- Opsjoner på maks eller min av to aktiva (Stulz 1982, Johnson 1987) ------------

// kind = 'max' | 'min'. Utbetaling for call: max(max/min(S1, S2) − X, 0).
export function maxMinOption({ type = 'call', kind = 'min', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const min = kind === 'min';
  if (!min && kind !== 'max') throw new Error(`Ukjent variant: ${kind}`);
  const sT = Math.sqrt(T);
  const v = ratioVol(v1, v2, rho);
  if (!(v > 1e-12)) {
    // σ1 = σ2 og ρ = 1: forholdet S1/S2 er deterministisk, så det er kjent hvilket aktivum som blir størst.
    const firstLargest = S1 * Math.exp(b1 * T) >= S2 * Math.exp(b2 * T);
    return firstLargest === !min
      ? gbsm({ type, S: S1, X, T, r, b: b1, v: v1 })
      : gbsm({ type, S: S2, X, T, r, b: b2, v: v2 });
  }
  const d = (Math.log(S1 / S2) + (b1 - b2 + 0.5 * v * v) * T) / (v * sT);
  const y1 = (Math.log(S1 / X) + (b1 + 0.5 * v1 * v1) * T) / (v1 * sT);
  const y2 = (Math.log(S2 / X) + (b2 + 0.5 * v2 * v2) * T) / (v2 * sT);
  const rho1 = Math.min(1, Math.max(-1, (v1 - rho * v2) / v));
  const rho2 = Math.min(1, Math.max(-1, (v2 - rho * v1) / v));
  const F1 = S1 * Math.exp((b1 - r) * T);
  const F2 = S2 * Math.exp((b2 - r) * T);
  const D = X * Math.exp(-r * T);
  let call;
  let zeroStrike; // nåverdien av max/min(S1, S2) ved forfall
  if (min) {
    call = F1 * cbnd(y1, -d, -rho1) + F2 * cbnd(y2, d - v * sT, -rho2) - D * cbnd(y1 - v1 * sT, y2 - v2 * sT, rho);
    zeroStrike = F1 - F1 * cnd(d) + F2 * cnd(d - v * sT);
  } else {
    call = F1 * cbnd(y1, d, rho1) + F2 * cbnd(y2, -d + v * sT, rho2) - D * (1 - cbnd(-y1 + v1 * sT, -y2 + v2 * sT, rho));
    zeroStrike = F2 + F1 * cnd(d) - F2 * cnd(d - v * sT);
  }
  if (isCall(type)) return call;
  return D - zeroStrike + call;
}

// Opsjoner på maks eller min av to geometriske gjennomsnitt (kontinuerlig snitt fra nå til T).
// Hvert snitt er lognormalt med volatilitet σ/√3 og cost of carry (b − σ²/6)/2, og
// korrelasjonen mellom snittene er ρ, så Stulz-formelen gir eksakt pris.
export function maxMinTwoAverages({ type = 'call', kind = 'min', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  return maxMinOption({
    type, kind, S1, S2, X, T, r,
    b1: 0.5 * (b1 - v1 * v1 / 6),
    b2: 0.5 * (b2 - v2 * v2 / 6),
    v1: v1 / Math.sqrt(3),
    v2: v2 / Math.sqrt(3),
    rho,
  });
}

// --- Spreadopsjoner ------------------------------------------------------------------

// Kirk (1995): utbetaling max(F1 − F2 − X, 0) / max(X − F1 + F2, 0), der Fi = Si·e^{bi·T}.
export function kirkSpread({ type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const F1 = S1 * Math.exp(b1 * T);
  const F2 = S2 * Math.exp(b2 * T);
  if (!(F2 + X > 0)) throw new Error('Kirks tilnærming krever at F2 + X er positiv.');
  const w = F2 / (F2 + X);
  const v = Math.sqrt(Math.max(0, v1 * v1 + (v2 * w) ** 2 - 2 * rho * v1 * v2 * w));
  const price = (F2 + X) * gbsm({ type, S: F1 / (F2 + X), X: 1, T, r, b: 0, v });
  return { price, v, F1, F2 };
}

// Eksakt pris for spreadopsjonen ved numerisk integrasjon: betinget på S2(T) er S1(T)
// lognormal, så den indre forventningen er en Black-Scholes-formel.
export function spreadExact({ type = 'call', S1, S2, X, T, r, b1, b2, v1, v2, rho }) {
  const call = isCall(type);
  const sT = Math.sqrt(T);
  const F1 = S1 * Math.exp(b1 * T);
  const F2 = S2 * Math.exp(b2 * T);
  const c = Math.sqrt(Math.max(0, 1 - rho * rho));
  const s = v1 * sT * c;
  const f = (z) => {
    const A = F1 * Math.exp(-0.5 * v1 * v1 * T * rho * rho + v1 * sT * rho * z); // E[S1(T) | z]
    const K = F2 * Math.exp(-0.5 * v2 * v2 * T + v2 * sT * z) + X;
    let payoff;
    if (K <= 0) {
      payoff = call ? A - K : 0;
    } else if (s < 1e-12) {
      payoff = Math.max(call ? A - K : K - A, 0);
    } else {
      const d1 = (Math.log(A / K) + 0.5 * s * s) / s;
      const d2 = d1 - s;
      payoff = call ? A * cnd(d1) - K * cnd(d2) : K * cnd(-d2) - A * cnd(-d1);
    }
    return Math.exp(-0.5 * z * z) * payoff;
  };
  const integral = gaussLegendreComposite(f, -10, 10, 40, 16) / Math.sqrt(2 * Math.PI);
  return Math.exp(-r * T) * integral;
}

// --- Barrierer på to aktiva ----------------------------------------------------------

function parseBarrierKind(kind) {
  const map = {
    'down-out': [true, true], 'up-out': [false, true], 'down-in': [true, false], 'up-in': [false, false],
  };
  if (!(kind in map)) throw new Error(`Ukjent barrieretype: ${kind}`);
  const [down, out] = map[kind];
  return { down, out };
}

// Ut-verdi når barrieren på S2 overvåkes kontinuerlig fra 0 til t1 (t1 = T gir Heynen og Kat).
// Som i Haug er S1 utbetalingsaktivumet og S2 barriereaktivumet. eta = 1 call, −1 put;
// phi = 1 opp, −1 ned.
function twoAssetOut(call, down, { S1, S2, X, H, T, t1, r, b1, b2, v1, v2, rho }) {
  const eta = call ? 1 : -1;
  const phi = down ? -1 : 1;
  const mu1 = b1 - 0.5 * v1 * v1;
  const mu2 = b2 - 0.5 * v2 * v2;
  const sT = Math.sqrt(T);
  const st1 = Math.sqrt(t1);
  const h = Math.log(H / S2);
  const d1 = (Math.log(S1 / X) + (mu1 + v1 * v1) * T) / (v1 * sT);
  const d2 = d1 - v1 * sT;
  const d3 = d1 + 2 * rho * h / (v2 * sT);
  const d4 = d2 + 2 * rho * h / (v2 * sT);
  const e1 = (h - (mu2 + rho * v1 * v2) * t1) / (v2 * st1);
  const e2 = e1 + rho * v1 * st1;
  const e3 = e1 - 2 * h / (v2 * st1);
  const e4 = e2 - 2 * h / (v2 * st1);
  const corr = -eta * phi * rho * Math.sqrt(t1 / T);
  const k1 = Math.exp(2 * (mu2 + rho * v1 * v2) * h / (v2 * v2));
  const k2 = Math.exp(2 * mu2 * h / (v2 * v2));
  return eta * S1 * Math.exp((b1 - r) * T) * (cbnd(eta * d1, phi * e1, corr) - k1 * cbnd(eta * d3, phi * e3, corr))
    - eta * X * Math.exp(-r * T) * (cbnd(eta * d2, phi * e2, corr) - k2 * cbnd(eta * d4, phi * e4, corr));
}

// To-aktiva-barriere (Heynen og Kat 1994): utbetalingen er max(S1 − X, 0) eller max(X − S1, 0),
// mens barrieren H gjelder S2. kind: 'down-out' | 'up-out' | 'down-in' | 'up-in'.
export function twoAssetBarrier({ type = 'call', kind, S1, S2, X, H, T, r, b1, b2, v1, v2, rho }) {
  return partialTwoAssetBarrier({ type, kind, S1, S2, X, H, T, t1: T, r, b1, b2, v1, v2, rho });
}

// Partial-time to-aktiva-barriere (Bermin 1996): barrieren på S2 overvåkes bare fra 0 til t1.
export function partialTwoAssetBarrier({ type = 'call', kind, S1, S2, X, H, T, t1, r, b1, b2, v1, v2, rho }) {
  const call = isCall(type);
  const { down, out } = parseBarrierKind(kind);
  if (!(t1 > 0)) throw new Error('Overvåkingsperioden t1 må være større enn null.');
  if (t1 > T) throw new Error('Overvåkingsperioden t1 kan ikke være lengre enn T.');
  const vanilla = gbsm({ type, S: S1, X, T, r, b: b1, v: v1 });
  if (down ? S2 <= H : S2 >= H) return out ? 0 : vanilla; // barrieren er allerede truffet
  const o = twoAssetOut(call, down, { S1, S2, X, H, T, t1, r, b1, b2, v1, v2, rho });
  return out ? o : vanilla - o;
}

// Standard barriereopsjon uten rabatt (Merton 1973, Reiner og Rubinstein 1991).
export function standardBarrier({ type = 'call', kind, S, X, H, T, r, b, v }) {
  const call = isCall(type);
  const { down, out } = parseBarrierKind(kind);
  const vanilla = gbsm({ type, S, X, T, r, b, v });
  if (down ? S <= H : S >= H) return out ? 0 : vanilla;
  const phi = call ? 1 : -1;
  const eta = down ? 1 : -1;
  const vst = v * Math.sqrt(T);
  const mu = (b - 0.5 * v * v) / (v * v);
  const x1 = Math.log(S / X) / vst + (1 + mu) * vst;
  const x2 = Math.log(S / H) / vst + (1 + mu) * vst;
  const y1 = Math.log(H * H / (S * X)) / vst + (1 + mu) * vst;
  const y2 = Math.log(H / S) / vst + (1 + mu) * vst;
  const Fw = S * Math.exp((b - r) * T);
  const Dx = X * Math.exp(-r * T);
  const hs = H / S;
  const pA = hs ** (2 * (mu + 1));
  const pB = hs ** (2 * mu);
  const A = phi * Fw * cnd(phi * x1) - phi * Dx * cnd(phi * (x1 - vst));
  const B = phi * Fw * cnd(phi * x2) - phi * Dx * cnd(phi * (x2 - vst));
  const C = phi * Fw * pA * cnd(eta * y1) - phi * Dx * pB * cnd(eta * (y1 - vst));
  const D = phi * Fw * pA * cnd(eta * y2) - phi * Dx * pB * cnd(eta * (y2 - vst));
  let o;
  if (call && down) o = X >= H ? A - C : B - D;
  else if (call) o = X >= H ? 0 : A - B + C - D;
  else if (down) o = X >= H ? A - B + C - D : 0;
  else o = X >= H ? B - D : A - C;
  o = Math.max(o, 0);
  return out ? o : vanilla - o;
}

// Margrabe-barriereopsjon: bytteopsjon (Q1·S1 mot Q2·S2) som slås inn eller ut når
// forholdet S1/S2 treffer H (kontinuerlig overvåket). type 'call' gir max(Q1·S1 − Q2·S2, 0),
// 'put' gir max(Q2·S2 − Q1·S1, 0).
export function margrabeBarrier({ type = 'call', kind, S1, S2, Q1 = 1, Q2 = 1, H, T, r, b1, b2, v1, v2, rho }) {
  const v = ratioVol(v1, v2, rho);
  requireRatioVol(v);
  return standardBarrier({ type, kind, S: Q1 * S1, X: Q2 * S2, H: Q1 * H * S2, T, r: r - b2, b: b1 - b2, v });
}

// Europeisk bytteopsjon i begge retninger (brukes som «vanilla» for Margrabe-barrierer).
export function exchangeEuropean({ type = 'call', S1, S2, Q1 = 1, Q2 = 1, T, r, b1, b2, v1, v2, rho }) {
  const v = ratioVol(v1, v2, rho);
  return gbsm({ type, S: Q1 * S1, X: Q2 * S2, T, r: r - b2, b: b1 - b2, v });
}

// --- Binære opsjoner på to aktiva ------------------------------------------------------

// Two-asset cash-or-nothing (Heynen og Kat 1996). Betaler K ved forfall hvis:
//   kind 1: S1 > X1 og S2 > X2     kind 2: S1 < X1 og S2 < X2
//   kind 3: S1 > X1 og S2 < X2     kind 4: S1 < X1 og S2 > X2
export function twoAssetCashOrNothing({ kind = 1, S1, S2, X1, X2, K, T, r, b1, b2, v1, v2, rho }) {
  const sT = Math.sqrt(T);
  const d1 = (Math.log(S1 / X1) + (b1 - 0.5 * v1 * v1) * T) / (v1 * sT);
  const d2 = (Math.log(S2 / X2) + (b2 - 0.5 * v2 * v2) * T) / (v2 * sT);
  const D = K * Math.exp(-r * T);
  switch (Number(kind)) {
    case 1: return D * cbnd(d1, d2, rho);
    case 2: return D * cbnd(-d1, -d2, rho);
    case 3: return D * cbnd(d1, -d2, -rho);
    case 4: return D * cbnd(-d1, d2, -rho);
    default: throw new Error(`Ukjent type: ${kind}`);
  }
}

// Best eller worst cash-or-nothing: betaler K hvis det beste (maks) eller dårligste (min)
// av de to aktivaene ender over (call) eller under (put) X.
export function bestWorstCashOrNothing({ type = 'call', kind = 'max', S1, S2, X, K, T, r, b1, b2, v1, v2, rho }) {
  const sT = Math.sqrt(T);
  const y1 = (Math.log(S1 / X) + (b1 - 0.5 * v1 * v1) * T) / (v1 * sT);
  const y2 = (Math.log(S2 / X) + (b2 - 0.5 * v2 * v2) * T) / (v2 * sT);
  const D = K * Math.exp(-r * T);
  const call = isCall(type);
  if (kind === 'max') return call ? D * (1 - cbnd(-y1, -y2, rho)) : D * cbnd(-y1, -y2, rho);
  if (kind === 'min') return call ? D * cbnd(y1, y2, rho) : D * (1 - cbnd(y1, y2, rho));
  throw new Error(`Ukjent variant: ${kind}`);
}
