// Kapittel 4.17 i Haug (2007): barriereopsjoner på ett underliggende.
//   standardBarrier      Merton (1973), Reiner og Rubinstein (1991): 8 typer med rabatt K
//   discreteBarrier      Broadie, Glasserman og Kou (1997): justering for diskret overvåking
//   doubleBarrier        Ikeda og Kunitomo (1992): dobbel barriere med krumning δ1, δ2
//   partialTimeBarrier   Heynen og Kat (1994): barriere bare i deler av levetiden (A, B1, B2)
//   lookBarrier          Bermin (1996): barriere i [0, t1], fast-strike lookback i [t1, T2]
//   softBarrier          Hart og Ross (1994): gradvis inn-/utslag mellom L og U
//
// Notasjon som i boka: S spot, X innløsningskurs, H barriere, K rabatt, T tid til forfall,
// r risikofri rente, b cost of carry, v volatilitet σ, type = 'call' | 'put'.
// Står spot allerede på feil side av en barriere, returneres den økonomiske verdien
// (knock-out: rabatten/0, knock-in: tilsvarende vanilla) i stedet for å kaste.

import { cnd, cbnd } from '../math/normal.js';
import { gaussLegendre, gaussLegendreComposite } from '../math/integrate.js';
import { gbsm, isCall, probabilityOfEverInTheMoney } from './bsm.js';

// --- Numeriske hjelpere -----------------------------------------------------------

const LOG_SQRT2PI = 0.5 * Math.log(2 * Math.PI);

// ln N(x), også langt ute i venstre hale (asymptotisk rekke for x < −35).
export function logCnd(x) {
  if (x === Infinity) return 0;
  if (x === -Infinity) return -Infinity;
  if (x > -35) return Math.log(cnd(x));
  const x2 = x * x;
  const s = 1 - 1 / x2 + 3 / (x2 * x2) - 15 / (x2 * x2 * x2) + 105 / (x2 * x2 * x2 * x2);
  return -0.5 * x2 - Math.log(-x) - LOG_SQRT2PI + Math.log(s);
}

// e^a · N(x) uten overflow/underflow i mellomregningen.
export function expCnd(a, x) {
  if (a === -Infinity) return 0;
  const n = cnd(x);
  if (n > 1e-280 && Math.abs(a) < 700) return Math.exp(a) * n;
  return Math.exp(a + logCnd(x));
}

// ln(N(hi) − N(lo)) for hi > lo, regnet i halene for å unngå kansellering.
function logDiffCnd(hi, lo) {
  if (lo >= 0) {
    const l1 = logCnd(-lo);
    return l1 + Math.log1p(-Math.exp(logCnd(-hi) - l1));
  }
  if (hi <= 0) {
    const l1 = logCnd(hi);
    return l1 + Math.log1p(-Math.exp(logCnd(lo) - l1));
  }
  return Math.log(cnd(hi) - cnd(lo));
}

// e^a · (N(x) − N(y)), stabil også når faktoren er enorm og differansen bitteliten.
export function expDiffCnd(a, x, y) {
  if (x === y || a === -Infinity) return 0;
  return x > y ? Math.exp(a + logDiffCnd(x, y)) : -Math.exp(a + logDiffCnd(y, x));
}

function checkPositive(value, message) {
  if (!(value > 0) || !Number.isFinite(value)) throw new Error(message);
}

function checkCommon({ S, T, v }) {
  checkPositive(S, 'Spotprisen S må være positiv.');
  checkPositive(v, 'Volatiliteten σ må være positiv.');
  if (!(T >= 0)) throw new Error('Tid til forfall T kan ikke være negativ.');
}

// Interpolerer lineært over b = 0 for formler med leddet σ²/(2b) (hevbar singularitet).
function smoothInB(f, b, eps = 1e-5) {
  if (Math.abs(b) >= eps) return f(b);
  const lo = f(-eps);
  const hi = f(eps);
  return lo + (hi - lo) * (b + eps) / (2 * eps);
}

// --- Standard barriereopsjoner (Reiner og Rubinstein 1991) -----------------------------

const BARRIER_KINDS = {
  do: { down: true, out: true },
  uo: { down: false, out: true },
  di: { down: true, out: false },
  ui: { down: false, out: false },
};

export function barrierKind(barrier) {
  const k = BARRIER_KINDS[barrier];
  if (!k) throw new Error(`Ukjent barrieretype: ${barrier}`);
  return k;
}

// Byggeklossene A–F i Reiner og Rubinstein (1991) med φ = ±1 (call/put) og η = ±1 (ned/opp).
function rrTerms(phi, eta, S, X, H, K, T, r, b, v) {
  const v2 = v * v;
  const vst = v * Math.sqrt(T);
  const mu = (b - v2 / 2) / v2;
  const lnHS = Math.log(H / S);
  const lnSX = Math.log(S / X);
  const lnShare = Math.log(S) + (b - r) * T;
  const lnCash = Math.log(X) - r * T;
  const share = Math.exp(lnShare);
  const cash = Math.exp(lnCash);

  const x1 = lnSX / vst + (1 + mu) * vst;
  const x2 = -lnHS / vst + (1 + mu) * vst;
  const y1 = (2 * lnHS + lnSX) / vst + (1 + mu) * vst;
  const y2 = lnHS / vst + (1 + mu) * vst;
  const pS = 2 * (mu + 1) * lnHS; // ln (H/S)^{2(μ+1)}
  const pX = 2 * mu * lnHS; // ln (H/S)^{2μ}

  const A = phi * (share * cnd(phi * x1) - cash * cnd(phi * (x1 - vst)));
  const B = phi * (share * cnd(phi * x2) - cash * cnd(phi * (x2 - vst)));
  const C = phi * (expCnd(lnShare + pS, eta * y1) - expCnd(lnCash + pX, eta * (y1 - vst)));
  const D = phi * (expCnd(lnShare + pS, eta * y2) - expCnd(lnCash + pX, eta * (y2 - vst)));
  let E = 0;
  let F = 0;
  if (K !== 0) {
    E = K * Math.exp(-r * T) * (cnd(eta * (x2 - vst)) - expCnd(pX, eta * (y2 - vst)));
    F = K * hitDiscountValue({ a: lnHS, nu: b - v2 / 2, v, rate: r, T });
  }
  return { A, B, C, D, E, F };
}

// ∫ f(t) dt over [tMin, T] på logaritmisk tidsakse (tettheter med topp nær t = 0).
export function integrateLogTime(f, tMin, T) {
  if (!(T > tMin)) return 0;
  const s0 = Math.log(tMin);
  const s1 = Math.log(T);
  const panels = Math.max(8, Math.ceil(4 * (s1 - s0)));
  return gaussLegendreComposite((s) => {
    const t = Math.exp(s);
    return f(t) * t;
  }, s0, s1, panels, 16);
}

// E[e^{−ρτ}; τ ≤ T] der τ er første treff av nivået a = ln(H/S) og ln S har drift ν.
// Lukket form (leddet F hos Reiner og Rubinstein) når μ² + 2ρ/σ² ≥ 0; ellers (negativ rente)
// numerisk integrasjon av førstepasseringstettheten. numeric = true tvinger integrasjonen.
export function hitDiscountValue({ a, nu, v, rate, T, numeric = false }) {
  if (a === 0) return 1;
  if (!(T > 0)) return 0;
  const v2 = v * v;
  const mu = nu / v2;
  const lam2 = mu * mu + 2 * rate / v2;
  if (lam2 >= 0 && !numeric) {
    const eta = a < 0 ? 1 : -1;
    const vst = v * Math.sqrt(T);
    const lam = Math.sqrt(lam2);
    const z = a / vst + lam * vst;
    return expCnd((mu + lam) * a, eta * z) + expCnd((mu - lam) * a, eta * (z - 2 * lam * vst));
  }
  const dens = (t) => Math.abs(a) / (v * Math.sqrt(2 * Math.PI * t * t * t))
    * Math.exp(-rate * t - (a - nu * t) ** 2 / (2 * v2 * t));
  return integrateLogTime(dens, a * a / (200 * v2), T);
}

// Standard barriereopsjon. barrier = 'do' | 'uo' | 'di' | 'ui' (ned/opp, ut/inn).
// Rabatten K utbetales ved treff for knock-out og ved forfall (hvis barrieren aldri
// treffes) for knock-in, som i boka.
export function standardBarrier({ type = 'call', barrier = 'do', S, X, H, K = 0, T, r, b, v }) {
  const call = isCall(type);
  const { down, out } = barrierKind(barrier);
  checkCommon({ S, T, v });
  checkPositive(X, 'Innløsningskursen X må være positiv.');
  checkPositive(H, 'Barrieren H må være positiv.');
  if (down ? S <= H : S >= H) return out ? K : gbsm({ type, S, X, T, r, b, v });
  if (T === 0) return out ? Math.max(call ? S - X : X - S, 0) : K;

  const { A, B, C, D, E, F } = rrTerms(call ? 1 : -1, down ? 1 : -1, S, X, H, K, T, r, b, v);
  const high = X >= H;
  if (call && down) return out ? (high ? A - C + F : B - D + F) : (high ? C + E : A - B + D + E);
  if (call && !down) return out ? (high ? F : A - B + C - D + F) : (high ? A + E : B - C + D + E);
  if (!call && down) return out ? (high ? A - B + C - D + F : F) : (high ? B - C + D + E : A + E);
  return out ? (high ? B - D + F : A - C + F) : (high ? A - B + D + E : C + E);
}

// Risikonøytral sannsynlighet for at barrieren H treffes før T (kontinuerlig overvåking).
export function barrierHitProbability({ S, H, T, b, v }) {
  if (S === H) return 1;
  return probabilityOfEverInTheMoney({ type: H > S ? 'call' : 'put', S, X: H, T, b, v });
}

// --- Diskret overvåking (Broadie, Glasserman og Kou 1997) ------------------------------

// β = −ζ(1/2)/√(2π) ≈ 0,5826, som i boka.
export const BGK_BETA = 0.5826;

// Barrieren flyttes bort fra spot: H·e^{−βσ√Δt} for ned-barriere, H·e^{+βσ√Δt} for opp-barriere.
export function bgkAdjustedBarrier({ H, v, dt, down }) {
  checkPositive(dt, 'Tiden mellom observasjonene Δt må være positiv.');
  return H * Math.exp((down ? -1 : 1) * BGK_BETA * v * Math.sqrt(dt));
}

// Standard barriereopsjon med diskret overvåking hver Δt år (BGK-korreksjon av barrieren).
export function discreteBarrier(p) {
  const { down } = barrierKind(p.barrier ?? 'do');
  if (down ? p.S <= p.H : p.S >= p.H) return standardBarrier(p);
  return standardBarrier({ ...p, H: bgkAdjustedBarrier({ H: p.H, v: p.v, dt: p.dt, down }) });
}

// --- Dobbel barriere (Ikeda og Kunitomo 1992) ------------------------------------------

// Q(ingen treff av L·e^{δ2 t} eller U·e^{δ1 t}, lo < S_T < hi) ved bildeserien til Ikeda og
// Kunitomo. share = true gir sannsynligheten under aksjemålet (drift b + σ²/2), som ganges
// med S·e^{(b−r)T}; share = false gir den risikonøytrale (drift b − σ²/2), som ganges med
// X·e^{−rT}. Summerer n = 0, ±1, ±2, … til leddene er neglisjerbare.
export function ikedaKunitomoProb({ S, lo, hi, L, U, T, b, v, delta1 = 0, delta2 = 0, share }) {
  if (!(hi > lo)) return 0;
  const v2 = v * v;
  const vst = v * Math.sqrt(T);
  const lnUL = Math.log(U / L);
  const lnLS = Math.log(L / S);
  const drift = (b + (share ? 0.5 : -0.5) * v2) * T;
  const ex = share ? 0 : -2;
  const lnSlo = Math.log(S / lo);
  const lnShi = Math.log(S / hi);
  const dd = delta1 - delta2;
  const term = (n) => {
    const mu1 = 2 * (b - delta2 - n * dd) / v2 + 1 + ex;
    const mu2 = 2 * n * dd / v2;
    const mu3 = 2 * (b - delta2 + n * dd) / v2 + 1 + ex;
    const a = (lnS) => (lnS + 2 * n * lnUL + drift) / vst;
    const c = (lnS) => (2 * lnLS + lnS - 2 * n * lnUL + drift) / vst;
    return expDiffCnd(n * mu1 * lnUL + mu2 * lnLS, a(lnSlo), a(lnShi))
      - expDiffCnd(mu3 * (lnLS - n * lnUL), c(lnSlo), c(lnShi));
  };
  let sum = term(0);
  let small = 0;
  for (let n = 1; n <= 5000; n++) {
    const pair = term(n) + term(-n);
    sum += pair;
    small = Math.abs(pair) < 1e-17 ? small + 1 : 0;
    if (small >= 2 && n >= 3) break;
  }
  return sum;
}

// Dobbel barriereopsjon. kind = 'out' (knock-out når L·e^{δ2 t} eller U·e^{δ1 t} treffes)
// eller 'in' (knock-in = vanilla − knock-out). δ1, δ2 er krumningen til barrierene.
export function doubleBarrier({ type = 'call', kind = 'out', S, X, L, U, T, r, b, v, delta1 = 0, delta2 = 0 }) {
  const call = isCall(type);
  if (kind !== 'out' && kind !== 'in') throw new Error(`Ukjent type dobbel barriere: ${kind}`);
  checkCommon({ S, T, v });
  checkPositive(X, 'Innløsningskursen X må være positiv.');
  if (!(L > 0 && U > L)) throw new Error('Barrierene må oppfylle 0 < L < U.');
  const vanilla = () => gbsm({ type, S, X, T, r, b, v });
  if (S <= L || S >= U) return kind === 'out' ? 0 : vanilla();
  const E = L * Math.exp(delta2 * T);
  const F = U * Math.exp(delta1 * T);
  if (!(F > E)) throw new Error('Barrierene krysser hverandre før forfall (krever L·e^{δ2·T} < U·e^{δ1·T}).');
  let out;
  if (T === 0) {
    out = Math.max(call ? S - X : X - S, 0);
  } else {
    const q = { S, L, U, T, b, v, delta1, delta2 };
    const share = S * Math.exp((b - r) * T);
    const cash = X * Math.exp(-r * T);
    const Xc = Math.min(Math.max(X, E), F); // utbetalingen er bare positiv mellom E og F
    out = call
      ? share * ikedaKunitomoProb({ ...q, lo: Xc, hi: F, share: true }) - cash * ikedaKunitomoProb({ ...q, lo: Xc, hi: F, share: false })
      : cash * ikedaKunitomoProb({ ...q, lo: E, hi: Xc, share: false }) - share * ikedaKunitomoProb({ ...q, lo: E, hi: Xc, share: true });
  }
  return kind === 'out' ? out : vanilla() - out;
}

// --- Partial-time barriereopsjoner (Heynen og Kat 1994) --------------------------------
//
// Type A: barrieren overvåkes i [0, t1] (start-out/start-in), ned eller opp.
// Type B1: barrieren overvåkes i [t1, T2]; enhver berøring eller kryssing slår ut (ingen retning).
// Type B2: barrieren overvåkes i [t1, T2]; ned-og-ut slås ut så snart S er under H
//          (også hvis S allerede er under H ved t1), opp-og-ut tilsvarende over H.
// Inn-variantene er vanilla − ut. Puts fås fra samme overlevelsessannsynligheter
// (paritet for knock-out: c − p = S e^{(b−r)T2} Q^S(overlever) − X e^{−rT2} Q(overlever)).

export const PARTIAL_TIME_KINDS = ['A-do', 'A-uo', 'A-di', 'A-ui', 'B1-o', 'B1-i', 'B2-do', 'B2-uo', 'B2-di', 'B2-ui'];

// Sannsynligheten for å overleve og ende i pengene (ψ = 1: S_T > X, ψ = −1: S_T < X) når
// ln S har drift ν. Bildeleddet bruker (H/S)^{2ν/σ²}; ν = b + σ²/2 gir aksjemålet.
function partialSurvival(event, psi, nu, c) {
  const { h, k, t1, T2, sd1, sdT, rho, v2 } = c;
  const img = Math.exp(2 * nu * h / v2);
  // Over H ved t1 og aldri under H i [t1, T2], med S_T > e^{kk}·S (kk ≥ h).
  const aboveGt = (kk) => cbnd((-kk + nu * T2) / sdT, (-h + nu * t1) / sd1, rho)
    - img * cbnd((2 * h - kk + nu * T2) / sdT, -(h + nu * t1) / sd1, -rho);
  // Under H ved t1 og aldri over H i [t1, T2], med S_T < e^{kk}·S (kk ≤ h).
  const belowLt = (kk) => cbnd((kk - nu * T2) / sdT, (h - nu * t1) / sd1, rho)
    - img * cbnd((kk - 2 * h - nu * T2) / sdT, (h + nu * t1) / sd1, -rho);
  const above = () => (psi > 0 ? aboveGt(Math.max(k, h)) : (k > h ? aboveGt(h) - aboveGt(k) : 0));
  const below = () => (psi < 0 ? belowLt(Math.min(k, h)) : (k < h ? belowLt(h) - belowLt(k) : 0));
  switch (event) {
    case 'A-down':
    case 'A-up': {
      const eta = event === 'A-down' ? 1 : -1;
      return cbnd(psi * (-k + nu * T2) / sdT, eta * (-h + nu * t1) / sd1, eta * psi * rho)
        - img * cbnd(psi * (2 * h - k + nu * T2) / sdT, eta * (h + nu * t1) / sd1, eta * psi * rho);
    }
    case 'above': return above();
    case 'below': return below();
    case 'either': return above() + below();
    default: throw new Error(`Ukjent hendelse: ${event}`);
  }
}

export function partialTimeBarrier({ type = 'call', kind = 'A-do', S, X, H, t1, T2, r, b, v }) {
  const call = isCall(type);
  if (!PARTIAL_TIME_KINDS.includes(kind)) throw new Error(`Ukjent partial-time-type: ${kind}`);
  checkCommon({ S, T: T2, v });
  checkPositive(X, 'Innløsningskursen X må være positiv.');
  checkPositive(H, 'Barrieren H må være positiv.');
  if (!(t1 > 0 && t1 <= T2)) throw new Error('Tidspunktet t1 må ligge i (0, T2].');
  const vanilla = () => gbsm({ type, S, X, T: T2, r, b, v });
  const [group, dir] = kind.split('-');
  const knockIn = dir.endsWith('i');
  let event;
  if (group === 'A') {
    const down = dir[0] === 'd';
    if (down ? S <= H : S >= H) return knockIn ? vanilla() : 0;
    event = down ? 'A-down' : 'A-up';
  } else if (group === 'B1') {
    event = 'either';
  } else {
    event = dir[0] === 'd' ? 'above' : 'below';
  }
  const v2 = v * v;
  const c = {
    h: Math.log(H / S), k: Math.log(X / S), t1, T2, v2,
    sd1: v * Math.sqrt(t1), sdT: v * Math.sqrt(T2), rho: Math.sqrt(t1 / T2),
  };
  const psi = call ? 1 : -1;
  const share = S * Math.exp((b - r) * T2) * partialSurvival(event, psi, b + v2 / 2, c);
  const cash = X * Math.exp(-r * T2) * partialSurvival(event, psi, b - v2 / 2, c);
  const out = psi * (share - cash);
  return knockIn ? vanilla() - out : out;
}

// --- Look-barrier-opsjoner (Bermin 1996) -----------------------------------------------
//
// Opp-og-ut call: max(max_{t1≤u≤T2} S_u − X, 0) hvis S aldri når H i [0, t1], ellers 0.
// Ned-og-ut put:  max(X − min_{t1≤u≤T2} S_u, 0) hvis S aldri når H i [0, t1], ellers 0.
// Inn-variantene er partiell fast-strike lookback (Heynen og Kat 1994) minus ut-varianten.
// Formelen er verdien ved t1 av en fast-strike lookback over [t1, T2], integrert mot den
// utslåtte tettheten til S_{t1}. withBarrier = false gir den partielle lookbacken.

function lookBarrierCore(eta, S, X, H, t1, T2, r, b, v, withBarrier) {
  const v2 = v * v;
  const s1 = v * Math.sqrt(t1);
  const s2 = v * Math.sqrt(T2);
  const tau = T2 - t1;
  const mu1 = b - v2 / 2;
  const mu2 = b + v2 / 2;
  const rho = Math.sqrt(t1 / T2);
  const k = Math.log(X / S);
  const h = withBarrier ? Math.log(H / S) : 0;
  const m = withBarrier ? (eta > 0 ? Math.min(h, k) : Math.max(h, k)) : k;
  const img = (mu) => (withBarrier ? Math.exp(2 * mu * h / v2) : 0);
  const M = (x, y) => cbnd(x, y, -rho);
  // Sannsynligheten for å overleve [0, t1] og være i pengene for lookbacken ved t1.
  const g = (mu) => {
    const all = withBarrier ? cnd(eta * (h - mu * t1) / s1) - img(mu) * cnd(eta * (-h - mu * t1) / s1) : 1;
    const outside = cnd(eta * (m - mu * t1) / s1) - (withBarrier ? img(mu) * cnd(eta * (m - 2 * h - mu * t1) / s1) : 0);
    return all - outside;
  };
  const a = v2 / (2 * b);
  const share = S * Math.exp((b - r) * T2);
  const disc = Math.exp(-r * T2);
  const part1 = share * (1 + a) * (M(eta * (m - mu2 * t1) / s1, eta * (-k + mu2 * T2) / s2)
    - (withBarrier ? img(mu2) * M(eta * (m - 2 * h - mu2 * t1) / s1, eta * (2 * h - k + mu2 * T2) / s2) : 0));
  const part2 = -disc * X * (M(eta * (m - mu1 * t1) / s1, eta * (-k + mu1 * T2) / s2)
    - (withBarrier ? img(mu1) * M(eta * (m - 2 * h - mu1 * t1) / s1, eta * (2 * h - k + mu1 * T2) / s2) : 0));
  const part3 = -disc * a * (S * Math.pow(S / X, -2 * b / v2) * M(eta * (m + mu1 * t1) / s1, eta * (-k - mu1 * T2) / s2)
    - (withBarrier ? H * Math.pow(H / X, -2 * b / v2) * M(eta * (m - 2 * h + mu1 * t1) / s1, eta * (2 * h - k - mu1 * T2) / s2) : 0));
  const sq = v * Math.sqrt(tau);
  const nA = tau > 0 ? cnd(eta * mu2 * tau / sq) : 0.5;
  const nB = tau > 0 ? cnd(-eta * mu1 * tau / sq) : 0.5;
  const part4 = share * ((1 + a) * nA + Math.exp(-b * tau) * (1 - a) * nB) * g(mu2) - disc * X * g(mu1);
  return eta * (part1 + part2 + part3 + part4);
}

// Partiell fast-strike lookback: lookback-perioden er [t1, T2] (Heynen og Kat 1994).
export function partialFixedLookback({ type = 'call', S, X, t1, T2, r, b, v }) {
  const eta = isCall(type) ? 1 : -1;
  if (!(t1 >= 0 && t1 < T2)) throw new Error('Tidspunktet t1 må ligge i [0, T2).');
  const t = Math.max(t1, 1e-12 * T2);
  return smoothInB((bb) => lookBarrierCore(eta, S, X, S, t, T2, r, bb, v, false), b);
}

export const LOOK_BARRIER_KINDS = ['cuo', 'cui', 'pdo', 'pdi'];

export function lookBarrier({ kind = 'cuo', S, X, H, t1, T2, r, b, v }) {
  if (!LOOK_BARRIER_KINDS.includes(kind)) throw new Error(`Ukjent look-barrier-type: ${kind}`);
  checkCommon({ S, T: T2, v });
  checkPositive(X, 'Innløsningskursen X må være positiv.');
  checkPositive(H, 'Barrieren H må være positiv.');
  if (!(t1 > 0 && t1 <= T2)) throw new Error('Tidspunktet t1 må ligge i (0, T2].');
  const call = kind[0] === 'c';
  const knockIn = kind[2] === 'i';
  const eta = call ? 1 : -1;
  const lookback = () => (t1 < T2
    ? partialFixedLookback({ type: call ? 'call' : 'put', S, X, t1, T2, r, b, v })
    : gbsm({ type: call ? 'call' : 'put', S, X, T: T2, r, b, v }));
  let out;
  if (call ? S >= H : S <= H) {
    out = 0;
  } else if (t1 === T2) {
    out = standardBarrier({ type: call ? 'call' : 'put', barrier: call ? 'uo' : 'do', S, X, H, K: 0, T: T2, r, b, v });
  } else {
    out = smoothInB((bb) => lookBarrierCore(eta, S, X, H, t1, T2, r, bb, v, true), b);
  }
  return knockIn ? lookback() - out : out;
}

// --- Soft-barrier-opsjoner (Hart og Ross 1994) -----------------------------------------
//
// Ned-og-inn call: andelen som er slått inn er (U − min S)/(U − L), begrenset til [0, 1].
// Opp-og-inn put: andelen er (max S − L)/(U − L). Ut-variantene er vanilla − inn.
// Verdien er gjennomsnittet av standard barriereopsjoner (uten rabatt) over H ∈ [L, U].
// Hart og Ross sin lukkede formel gjelder delen av [L, U] der barrieren ligger på samme side
// av X som spot ligger av barrieren (H ≤ X for call, H ≥ X for put); resten integreres numerisk.

export const SOFT_BARRIER_KINDS = ['cdi', 'cdo', 'pui', 'puo'];

// ∫_a^c C(H) dH der C er RR-leddet C for ned-og-inn call (η = 1) eller opp-og-inn put (η = −1).
function hartRossIntegral(eta, a, c, S, X, T, r, b, v) {
  const v2 = v * v;
  const vst = v * Math.sqrt(T);
  const mu = (b + v2 / 2) / v2;
  if (Math.abs(mu - 0.5) < 1e-4 || Math.abs(mu + 0.5) < 1e-4 || c - a < 1e-3 * c) {
    // Lukket form er singulær (b ≈ 0 eller b ≈ −σ²) eller kansellerer (svært smalt
    // intervall): integrer standardformelen numerisk i stedet.
    const type = eta > 0 ? 'call' : 'put';
    const barrier = eta > 0 ? 'di' : 'ui';
    return gaussLegendre((H) => standardBarrier({ type, barrier, S, X, H, K: 0, T, r, b, v }), a, c, 48);
  }
  const lnXS = Math.log(X / S);
  const lnL1 = -0.5 * v2 * T * (mu + 0.5) * (mu - 0.5);
  const lnL2 = -0.5 * v2 * T * (mu - 0.5) * (mu - 1.5);
  // Antideriverte (Hart og Ross): S-ledd med μ ± 0,5 og X-ledd med μ − 1 ± 0,5.
  const sPart = (H) => {
    const d1 = Math.log(H * H / (S * X)) / vst + mu * vst;
    return expCnd(Math.log(H) + 2 * mu * Math.log(H / S), eta * d1)
      - expCnd(Math.log(S) + (mu + 0.5) * lnXS + lnL1, eta * (d1 - (mu + 0.5) * vst));
  };
  const xPart = (H) => {
    const d3 = Math.log(H * H / (S * X)) / vst + (mu - 1) * vst;
    return expCnd(Math.log(H) + (2 * mu - 2) * Math.log(H / S), eta * d3)
      - expCnd(Math.log(S) + (mu - 0.5) * lnXS + lnL2, eta * (d3 - (mu - 0.5) * vst));
  };
  return eta * S * Math.exp((b - r) * T) / (2 * mu + 1) * (sPart(c) - sPart(a))
    - eta * X * Math.exp(-r * T) / (2 * mu - 1) * (xPart(c) - xPart(a));
}

function softKnockIn(call, S, X, U, L, T, r, b, v) {
  const type = call ? 'call' : 'put';
  const barrier = call ? 'di' : 'ui';
  const vanilla = gbsm({ type, S, X, T, r, b, v });
  const hard = (H) => standardBarrier({ type, barrier, S, X, H, K: 0, T, r, b, v });
  const numeric = (a, c) => (c > a ? gaussLegendre(hard, a, c, 48) : 0);
  const eta = call ? 1 : -1;
  let total = 0;
  if (call) {
    // [L, min(U, X, S)]: lukket form, [max(L, X), min(U, S)]: numerisk, [max(L, S), U]: slått inn.
    const c1 = Math.min(U, X, S);
    if (c1 > L) total += hartRossIntegral(eta, L, c1, S, X, T, r, b, v);
    total += numeric(Math.max(L, X), Math.min(U, S));
    if (U > S) total += vanilla * (U - Math.max(L, S));
  } else {
    const a1 = Math.max(L, X, S);
    if (U > a1) total += hartRossIntegral(eta, a1, U, S, X, T, r, b, v);
    total += numeric(Math.max(L, S), Math.min(U, X));
    if (L < S) total += vanilla * (Math.min(U, S) - L);
  }
  return total / (U - L);
}

export function softBarrier({ kind = 'cdi', S, X, U, L, T, r, b, v }) {
  if (!SOFT_BARRIER_KINDS.includes(kind)) throw new Error(`Ukjent soft-barrier-type: ${kind}`);
  checkCommon({ S, T, v });
  checkPositive(X, 'Innløsningskursen X må være positiv.');
  if (!(L > 0 && U >= L)) throw new Error('Barriereområdet må oppfylle 0 < L ≤ U.');
  const call = kind[0] === 'c';
  const knockIn = kind[2] === 'i';
  const type = call ? 'call' : 'put';
  const vanilla = gbsm({ type, S, X, T, r, b, v });
  let inValue;
  if (T === 0) {
    const touched = call ? Math.min(Math.max((U - S) / (U - L || 1), 0), 1) : Math.min(Math.max((S - L) / (U - L || 1), 0), 1);
    inValue = touched * vanilla;
  } else if (U - L <= 1e-10 * U) {
    inValue = standardBarrier({ type, barrier: call ? 'di' : 'ui', S, X, H: U, K: 0, T, r, b, v });
  } else {
    inValue = softKnockIn(call, S, X, U, L, T, r, b, v);
  }
  return knockIn ? inValue : vanilla - inValue;
}
