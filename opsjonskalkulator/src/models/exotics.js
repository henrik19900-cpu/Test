// Kapittel 4: Eksotiske opsjoner på ett underliggende (unntatt barriere- og binære opsjoner).
// Lookback-opsjoner ligger i lookback.js og asiatiske opsjoner i asian.js.
//
// Notasjon som i Haug: S spot, X innløsningskurs, T tid til forfall, r rente, b cost of carry,
// v volatilitet (σ), type = 'call' | 'put'. Alle funksjoner tar ett parameterobjekt.

import { cnd, nd, cbnd, cndInv } from '../math/normal.js';
import { brent } from '../math/solvers.js';
import { gbsm, isCall } from './bsm.js';

// --- Hjelpefunksjoner (brukes også av lookback.js og asian.js) -------------------------

const LN_SQRT2PI = 0.5 * Math.log(2 * Math.PI);

// ln N(x) som også virker langt ute i venstre hale (asymptotisk rekke når N(x) underflyter).
export function logCnd(x) {
  if (x > -30) return Math.log(cnd(x));
  const z = 1 / (x * x);
  return -0.5 * x * x - Math.log(-x) - LN_SQRT2PI + Math.log(1 - z + 3 * z * z - 15 * z * z * z);
}

// base^expo · N(x) regnet i log-rom, så ∞ · 0 ikke gir NaN for ekstreme parametre.
export function powCnd(base, expo, x) {
  return Math.exp(expo * Math.log(base) + logCnd(x));
}

// base^expo · m der m er en sannsynlighet (f.eks. M(a, b; ρ)).
export function powTimes(base, expo, m) {
  if (m <= 0) return 0;
  return Math.exp(expo * Math.log(base) + Math.log(m));
}

// Mange formler har leddet σ²/(2b)·[…] med en hevbar singularitet i b = 0. For |b| < eps
// interpoleres f med et tredjegradspolynom gjennom b = ±eps og ±2·eps (feil ~1e-10).
export function regularInB(f, b, eps = 1e-5) {
  if (Math.abs(b) >= eps) return f(b);
  const xs = [-2 * eps, -eps, eps, 2 * eps];
  const ys = xs.map(f);
  let sum = 0;
  for (let i = 0; i < 4; i++) {
    let w = 1;
    for (let j = 0; j < 4; j++) if (j !== i) w *= (b - xs[j]) / (xs[i] - xs[j]);
    sum += w * ys[i];
  }
  return sum;
}

// (e^x − 1)/x, også for x ≈ 0.
export function expm1OverX(x) {
  if (Math.abs(x) < 1e-8) return 1 + 0.5 * x;
  return Math.expm1(x) / x;
}

function binomial(n, k) {
  let c = 1;
  for (let j = 1; j <= k; j++) c = c * (n - k + j) / j;
  return c;
}

// Nullpunkt for en monoton funksjon av en positiv variabel: leter geometrisk opp og ned fra
// `guess` til fortegnet skifter, og løser med Brent. Returnerer null hvis det ikke finnes.
export function solveMonotone(f, guess, { tol = 1e-12 } = {}) {
  const f0 = f(guess);
  if (f0 === 0) return guess;
  const s0 = Math.sign(f0);
  let lo = guess;
  let hi = guess;
  for (let i = 0; i < 400; i++) {
    hi *= 2;
    const fh = f(hi);
    if (Math.sign(fh) !== s0 && Number.isFinite(fh)) return brent(f, hi / 2, hi, { tol: tol * hi });
    lo /= 2;
    const fl = f(lo);
    if (Math.sign(fl) !== s0 && Number.isFinite(fl)) return brent(f, lo, lo * 2, { tol: tol * lo });
  }
  return null;
}

function requireOrder(a, b, msg) {
  if (!(a < b)) throw new Error(msg);
}

// --- 4.1 Variable purchase options (Handley 2001) ---------------------------------------
// Innehaveren betaler et fast beløp X og får N = X/(S_T(1 − D)) aksjer, begrenset til
// [N_min, N_max] = [X/(U(1 − D)), X/(L(1 − D))].
export function variablePurchaseOption({ S, X, D, L, U, T, r, b, v }) {
  if (!(D >= 0 && D < 1)) throw new Error('Rabatten D må ligge i intervallet [0, 1).');
  if (!(L > 0)) throw new Error('Nedre grense L må være positiv.');
  requireOrder(L, U, 'Nedre grense L må være mindre enn øvre grense U.');
  const Nmin = X / (U * (1 - D));
  const Nmax = X / (L * (1 - D));
  const fixed = X * D / (1 - D) * Math.exp(-r * T);
  const price = fixed
    + Nmin * gbsm({ type: 'call', S, X: U, T, r, b, v })
    - Nmax * gbsm({ type: 'put', S, X: L, T, r, b, v })
    + Nmax * gbsm({ type: 'put', S, X: L * (1 - D), T, r, b, v });
  return { price, Nmin, Nmax, fixed };
}

// --- 4.2 Executive stock options (Jennergren og Näslund 1993) ----------------------------
// Opsjonen tapes hvis den ansatte slutter; sluttidspunktet er eksponentialfordelt med rate λ.
export function executiveStockOption({ type, S, X, T, r, b, v, lambda }) {
  if (!(lambda >= 0)) throw new Error('Hopprate λ kan ikke være negativ.');
  const vanilla = gbsm({ type, S, X, T, r, b, v });
  const keep = Math.exp(-lambda * T);
  return { price: keep * vanilla, vanilla, keep };
}

// --- 4.3 Moneyness-opsjoner --------------------------------------------------------------
// Vanlig opsjon der innløsningskursen er en andel av forwardprisen F. Call: L = X/F, verdien er
// per enhet F. Put: L = F/X, verdien er per enhet X. Begge: e^{−rT}[N(d1) − L·N(d2)],
// d1 = (−ln L + σ²T/2)/(σ√T), d2 = d1 − σ√T.
export function moneynessOption({ type, L, T, r, v }) {
  isCall(type);
  if (!(L > 0)) throw new Error('Moneyness L må være positiv.');
  const vst = v * Math.sqrt(T);
  const d1 = (-Math.log(L) + 0.5 * v * v * T) / vst;
  return Math.exp(-r * T) * (cnd(d1) - L * cnd(d1 - vst));
}

// --- 4.4 Potenskontrakter og potensopsjoner ----------------------------------------------

// Utbetaling (S_T/X)^i.
export function powerContract({ S, X, T, r, b, v, i }) {
  return Math.pow(S / X, i) * Math.exp(((b - 0.5 * v * v) * i - r + 0.5 * i * i * v * v) * T);
}

function powerTerms(S, X, T, b, v, i) {
  const vst = v * Math.sqrt(T);
  const d1 = (Math.log(S / Math.pow(X, 1 / i)) + (b + (i - 0.5) * v * v) * T) / vst;
  return { d1, d2: d1 - i * vst };
}

// Standard (asymmetrisk) potensopsjon: max(S_T^i − X, 0) / max(X − S_T^i, 0).
export function powerOption({ type, S, X, T, r, b, v, i }) {
  if (!(i > 0)) throw new Error('Potensen i må være positiv.');
  const call = isCall(type);
  const fwd = Math.pow(S, i) * Math.exp(((i - 1) * (r + 0.5 * i * v * v) - i * (r - b)) * T);
  const df = Math.exp(-r * T);
  const { d1, d2 } = powerTerms(S, X, T, b, v, i);
  if (call) return fwd * cnd(d1) - X * df * cnd(d2);
  return X * df * cnd(-d2) - fwd * cnd(-d1);
}

// Potensopsjon med tak C: min(max(S_T^i − X, 0), C) / min(max(X − S_T^i, 0), C).
export function cappedPowerOption({ type, S, X, C, T, r, b, v, i }) {
  if (!(i > 0)) throw new Error('Potensen i må være positiv.');
  if (!(C > 0)) throw new Error('Taket C må være positivt.');
  const call = isCall(type);
  const fwd = Math.pow(S, i) * Math.exp(((i - 1) * (r + 0.5 * i * v * v) - i * (r - b)) * T);
  const df = Math.exp(-r * T);
  const { d1, d2 } = powerTerms(S, X, T, b, v, i);
  if (call) {
    const { d1: d3, d2: d4 } = powerTerms(S, X + C, T, b, v, i);
    return fwd * (cnd(d1) - cnd(d3)) - df * (X * cnd(d2) - (X + C) * cnd(d4));
  }
  // Put-utbetalingen er høyst X, så et tak C ≥ X binder aldri.
  if (C >= X) return X * df * cnd(-d2) - fwd * cnd(-d1);
  const { d1: d3, d2: d4 } = powerTerms(S, X - C, T, b, v, i);
  return df * (X * cnd(-d2) - (X - C) * cnd(-d4)) - fwd * (cnd(-d1) - cnd(-d3));
}

// Opphøyd opsjon (powered option): max(S_T − X, 0)^i / max(X − S_T, 0)^i, i positivt heltall.
export function poweredOption({ type, S, X, T, r, b, v, i }) {
  if (!(Number.isInteger(i) && i >= 1)) throw new Error('Potensen i må være et positivt heltall.');
  const call = isCall(type);
  const vst = v * Math.sqrt(T);
  let sum = 0;
  for (let j = 0; j <= i; j++) {
    const k = i - j;
    const d = (Math.log(S / X) + (b + (k - 0.5) * v * v) * T) / vst;
    const growth = Math.exp(((k - 1) * (r + 0.5 * k * v * v) - k * (r - b)) * T);
    const c = binomial(i, j);
    if (call) sum += c * Math.pow(S, k) * Math.pow(-X, j) * growth * cnd(d);
    else sum += c * Math.pow(-S, k) * Math.pow(X, j) * growth * cnd(-d);
  }
  return sum;
}

// --- 4.5 Logkontrakter og log-opsjoner -----------------------------------------------------

// Kontrakt som betaler ln(S_T/X).
export function logContract({ S, X, T, r, b, v }) {
  return Math.exp(-r * T) * (Math.log(S / X) + (b - 0.5 * v * v) * T);
}

// Kontrakt som betaler ln(S_T).
export function logSContract({ S, T, r, b, v }) {
  return Math.exp(-r * T) * (Math.log(S) + (b - 0.5 * v * v) * T);
}

// Log-opsjon (Wilmott 2000): max(ln(S_T/X), 0). Putten max(ln(X/S_T), 0) følger av samme fordeling.
export function logOption({ type, S, X, T, r, b, v }) {
  const call = isCall(type);
  const m = Math.log(S / X) + (b - 0.5 * v * v) * T;
  const s = v * Math.sqrt(T);
  const d2 = m / s;
  const df = Math.exp(-r * T);
  if (call) return df * (s * nd(d2) + m * cnd(d2));
  return df * (s * nd(d2) - m * cnd(-d2));
}

// --- 4.6 Forward start (Rubinstein 1990) ---------------------------------------------------
// Opsjonen starter ved t med innløsningskurs X = α·S_t og forfaller ved T.
export function forwardStart({ type, S, alpha, t, T, r, b, v }) {
  if (!(t >= 0)) throw new Error('Starttidspunktet t kan ikke være negativt.');
  requireOrder(t, T, 'Starttidspunktet t må være før forfall T.');
  if (!(alpha > 0)) throw new Error('Andelen α må være positiv.');
  return S * Math.exp((b - r) * t) * gbsm({ type, S: 1, X: alpha, T: T - t, r, b, v });
}

// --- 4.8 Ratchet/cliquet: en rekke forward start-opsjoner ---------------------------------
// times = [t_1, …, t_n]: periode i går fra t_{i−1} til t_i (t_0 = 0) med innløsningskurs α·S_{t_{i−1}}.
export function ratchet({ type, S, alpha, times, r, b, v }) {
  if (!Array.isArray(times) || times.length === 0) throw new Error('Oppgi minst ett tidspunkt.');
  let prev = 0;
  const parts = [];
  for (const ti of times) {
    if (!(ti > prev)) throw new Error('Tidspunktene må være positive og strengt stigende.');
    parts.push(forwardStart({ type, S, alpha, t: prev, T: ti, r, b, v }));
    prev = ti;
  }
  return { price: parts.reduce((a, x) => a + x, 0), parts };
}

// --- 4.7 Fade-in (Brockhaus m.fl. 1999) ----------------------------------------------------
// Utbetalingen er vanilla-utbetalingen ganget med andelen av n fikseringer (t_i = iT/n)
// der L < S_{t_i} < H.
export function fadeIn({ type, S, X, L, H, T, n, r, b, v }) {
  const call = isCall(type);
  if (!(L >= 0)) throw new Error('Nedre grense L kan ikke være negativ.');
  requireOrder(L, H, 'Nedre grense L må være mindre enn øvre grense H.');
  if (!(Number.isInteger(n) && n >= 1)) throw new Error('Antall fikseringer n må være et positivt heltall.');
  const vst = v * Math.sqrt(T);
  const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / vst;
  const d2 = d1 - vst;
  const fwd = S * Math.exp((b - r) * T);
  const df = X * Math.exp(-r * T);
  let sum = 0;
  let inside = 0;
  for (let i = 1; i <= n; i++) {
    const ti = i * T / n;
    const vsi = v * Math.sqrt(ti);
    const rho = Math.sqrt(ti / T);
    const d3 = L > 0 ? (Math.log(S / L) + (b + 0.5 * v * v) * ti) / vsi : Infinity;
    const d4 = d3 - vsi;
    const d5 = (Math.log(S / H) + (b + 0.5 * v * v) * ti) / vsi;
    const d6 = d5 - vsi;
    if (call) {
      sum += fwd * (cbnd(-d5, d1, -rho) - cbnd(-d3, d1, -rho)) - df * (cbnd(-d6, d2, -rho) - cbnd(-d4, d2, -rho));
    } else {
      sum += df * (cbnd(d4, -d2, -rho) - cbnd(d6, -d2, -rho)) - fwd * (cbnd(d3, -d1, -rho) - cbnd(d5, -d1, -rho));
    }
    inside += cnd(d4) - cnd(d6);
  }
  return { price: sum / n, insideShare: inside / n };
}

// --- 4.9–4.10 Reset strike (Gray og Whaley 1997, 1999) -------------------------------------

function resetTerms(S, X, tau, T, b, v) {
  const a1 = (Math.log(S / X) + (b + 0.5 * v * v) * tau) / (v * Math.sqrt(tau));
  const a2 = a1 - v * Math.sqrt(tau);
  const z1 = (b + 0.5 * v * v) * (T - tau) / (v * Math.sqrt(T - tau));
  const z2 = z1 - v * Math.sqrt(T - tau);
  const y1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / (v * Math.sqrt(T));
  const y2 = y1 - v * Math.sqrt(T);
  return { a1, a2, z1, z2, y1, y2, rho: Math.sqrt(tau / T) };
}

function checkReset(tau, T) {
  if (!(tau > 0)) throw new Error('Tilbakestillingstidspunktet τ må være positivt.');
  requireOrder(tau, T, 'Tilbakestillingstidspunktet τ må være før forfall T.');
}

// Type 1 (Gray og Whaley 1997): prosentvis utbetaling max((S_T − X̃)/X̃, 0), der X̃ settes lik S_τ
// hvis opsjonen er ute av pengene ved τ.
export function resetStrikeType1({ type, S, X, tau, T, r, b, v }) {
  checkReset(tau, T);
  const { a1, a2, z1, z2, y1, y2, rho } = resetTerms(S, X, tau, T, b, v);
  const dfT = Math.exp(-r * T);
  const carryT = Math.exp((b - r) * T);
  const fwdPart = Math.exp((b - r) * (T - tau)) * Math.exp(-r * tau);
  if (isCall(type)) {
    return fwdPart * cnd(-a2) * cnd(z1) - dfT * cnd(-a2) * cnd(z2)
      - dfT * cbnd(a2, y2, rho) + (S / X) * carryT * cbnd(a1, y1, rho);
  }
  return dfT * cnd(a2) * cnd(-z2) - fwdPart * cnd(a2) * cnd(-z1)
    + dfT * cbnd(-a2, -y2, rho) - (S / X) * carryT * cbnd(-a1, -y1, rho);
}

// Type 2 (Gray og Whaley 1999): utbetaling max(S_T − X̃, 0) / max(X̃ − S_T, 0).
export function resetStrikeType2({ type, S, X, tau, T, r, b, v }) {
  checkReset(tau, T);
  const { a1, a2, z1, z2, y1, y2, rho } = resetTerms(S, X, tau, T, b, v);
  const carryT = S * Math.exp((b - r) * T);
  const carryTau = S * Math.exp((b - r) * tau) * Math.exp(-r * (T - tau));
  const dfX = X * Math.exp(-r * T);
  if (isCall(type)) {
    return carryT * cbnd(a1, y1, rho) - dfX * cbnd(a2, y2, rho)
      - carryTau * cnd(-a1) * cnd(z2) + carryT * cnd(-a1) * cnd(z1);
  }
  return carryTau * cnd(a1) * cnd(-z2) - carryT * cnd(a1) * cnd(-z1)
    + dfX * cbnd(-a2, -y2, rho) - carryT * cbnd(-a1, -y1, rho);
}

// --- 4.11 Time-switch (Pechtl 1995), diskret versjon --------------------------------------
// Innehaveren opptjener A·Δt for hver tidsenhet Δt der S er over (call) eller under (put) X.
// Fikseringer ved Δt, 2Δt, …, nΔt ≤ T; m tidsenheter er allerede opptjent. Betales ved T.
export function timeSwitch({ type, S, X, A, T, m = 0, dt, r, b, v }) {
  const call = isCall(type);
  if (!(dt > 0)) throw new Error('Tidsenheten Δt må være positiv.');
  if (!(m >= 0)) throw new Error('Antall opptjente tidsenheter m kan ikke være negativt.');
  const n = Math.floor(T / dt + 1e-9);
  let sum = 0;
  for (let i = 1; i <= n; i++) {
    const ti = i * dt;
    const d = (Math.log(S / X) + (b - 0.5 * v * v) * ti) / (v * Math.sqrt(ti));
    sum += cnd(call ? d : -d);
  }
  const df = Math.exp(-r * T);
  return { price: A * df * dt * (sum + m), expectedUnits: sum, n };
}

// --- 4.12 Chooser-opsjoner (Rubinstein 1991) ------------------------------------------------

// Enkel chooser: ved t velger innehaveren call eller put med samme X og forfall T.
export function simpleChooser({ S, X, t, T, r, b, v }) {
  requireOrder(t, T, 'Valgtidspunktet t må være før forfall T.');
  if (t <= 0) {
    return Math.max(gbsm({ type: 'call', S, X, T, r, b, v }), gbsm({ type: 'put', S, X, T, r, b, v }));
  }
  const d = (Math.log(S / X) + (b + 0.5 * v * v) * T) / (v * Math.sqrt(T));
  const y = (Math.log(S / X) + b * T + 0.5 * v * v * t) / (v * Math.sqrt(t));
  const carry = S * Math.exp((b - r) * T);
  const df = X * Math.exp(-r * T);
  return carry * cnd(d) - df * cnd(d - v * Math.sqrt(T)) - carry * cnd(-y) + df * cnd(-y + v * Math.sqrt(t));
}

// Kompleks chooser: ved t velges call (Xc, Tc) eller put (Xp, Tp).
export function complexChooser({ S, Xc, Xp, t, Tc, Tp, r, b, v }) {
  if (!(t > 0)) throw new Error('Valgtidspunktet t må være positivt.');
  requireOrder(t, Tc, 'Valgtidspunktet t må være før forfall for callen Tc.');
  requireOrder(t, Tp, 'Valgtidspunktet t må være før forfall for putten Tp.');
  // Kritisk pris I: c(I, Xc, Tc − t) = p(I, Xp, Tp − t). Differansen øker strengt i I.
  const f = (s) => gbsm({ type: 'call', S: s, X: Xc, T: Tc - t, r, b, v })
    - gbsm({ type: 'put', S: s, X: Xp, T: Tp - t, r, b, v });
  const I = solveMonotone(f, Math.sqrt(Xc * Xp));
  if (I === null) throw new Error('Fant ikke den kritiske prisen I.');
  const st = v * Math.sqrt(t);
  const d1 = (Math.log(S / I) + (b + 0.5 * v * v) * t) / st;
  const d2 = d1 - st;
  const y1 = (Math.log(S / Xc) + (b + 0.5 * v * v) * Tc) / (v * Math.sqrt(Tc));
  const y2 = (Math.log(S / Xp) + (b + 0.5 * v * v) * Tp) / (v * Math.sqrt(Tp));
  const rho1 = Math.sqrt(t / Tc);
  const rho2 = Math.sqrt(t / Tp);
  const price = S * Math.exp((b - r) * Tc) * cbnd(d1, y1, rho1)
    - Xc * Math.exp(-r * Tc) * cbnd(d2, y1 - v * Math.sqrt(Tc), rho1)
    - S * Math.exp((b - r) * Tp) * cbnd(-d1, -y2, rho2)
    + Xp * Math.exp(-r * Tp) * cbnd(-d2, -y2 + v * Math.sqrt(Tp), rho2);
  return { price, I };
}

// --- 4.13 Opsjoner på opsjoner (Geske 1977, Rubinstein 1991) --------------------------------
// kind: 'call-call' | 'put-call' | 'call-put' | 'put-put' (opsjon på underliggende opsjon).
// X1 og T2: innløsningskurs og forfall for den underliggende opsjonen.
// X2 og t1: innløsningskurs og forfall for opsjonen på opsjonen (t1 < T2).
export const COMPOUND_KINDS = ['call-call', 'put-call', 'call-put', 'put-put'];

export function compoundOption({ kind, S, X1, X2, t1, T2, r, b, v }) {
  if (!COMPOUND_KINDS.includes(kind)) throw new Error(`Ukjent type: ${kind}`);
  if (!(t1 > 0)) throw new Error('Forfallet t1 må være positivt.');
  requireOrder(t1, T2, 'Opsjonen på opsjonen må forfalle før den underliggende opsjonen (t1 < T2).');
  const [outer, inner] = kind.split('-');
  const tau = T2 - t1;
  const underlying = gbsm({ type: inner, S, X: X1, T: T2, r, b, v });
  const g = (s) => gbsm({ type: inner, S: s, X: X1, T: tau, r, b, v }) - X2;
  // Kritisk pris I: verdien av den underliggende opsjonen ved t1 er lik X2. For en put er
  // verdien begrenset av X1·e^{−r(T2−t1)}, så I finnes bare når X2 er under denne grensen.
  let I = null;
  if (inner === 'call' || X1 * Math.exp(-r * tau) > X2) I = solveMonotone(g, X1);
  if (I === null) {
    // Putverdien ved t1 er alltid under X2: call på put innløses aldri, put på put alltid.
    const price = outer === 'call' ? 0 : X2 * Math.exp(-r * t1) - underlying;
    return { price, I: null, underlying };
  }
  const y1 = (Math.log(S / I) + (b + 0.5 * v * v) * t1) / (v * Math.sqrt(t1));
  const y2 = y1 - v * Math.sqrt(t1);
  const z1 = (Math.log(S / X1) + (b + 0.5 * v * v) * T2) / (v * Math.sqrt(T2));
  const z2 = z1 - v * Math.sqrt(T2);
  const rho = Math.sqrt(t1 / T2);
  const fS = S * Math.exp((b - r) * T2);
  const fX1 = X1 * Math.exp(-r * T2);
  const fX2 = X2 * Math.exp(-r * t1);
  let price;
  switch (kind) {
    case 'call-call':
      price = fS * cbnd(z1, y1, rho) - fX1 * cbnd(z2, y2, rho) - fX2 * cnd(y2);
      break;
    case 'put-call':
      price = fX1 * cbnd(z2, -y2, -rho) - fS * cbnd(z1, -y1, -rho) + fX2 * cnd(-y2);
      break;
    case 'call-put':
      price = fX1 * cbnd(-z2, -y2, rho) - fS * cbnd(-z1, -y1, rho) - fX2 * cnd(-y2);
      break;
    default: // put-put
      price = fS * cbnd(-z1, y1, -rho) - fX1 * cbnd(-z2, y2, -rho) + fX2 * cnd(y2);
  }
  return { price, I, underlying };
}

// --- 4.14 Forlengbare opsjoner (Longstaff 1990) ---------------------------------------------

// Innehaveren kan ved t1 forlenge til T2 med ny innløsningskurs X2 mot et gebyr A.
// Verdien ved t1 er max(0, utbetaling, opsjon(X2, T2 − t1) − A). Områdene der forlengelse,
// innløsning eller ingenting er best finnes eksakt (Longstaffs kritiske priser I1 og I2),
// og verdien er summen av lukkede uttrykk over områdene.
export function holderExtendible({ type, S, X1, X2, t1, T2, A, r, b, v }) {
  const call = isCall(type);
  if (!(t1 > 0)) throw new Error('Tidspunktet t1 må være positivt.');
  requireOrder(t1, T2, 'Det forlengede forfallet T2 må være etter t1.');
  if (!(A >= 0)) throw new Error('Gebyret A kan ikke være negativt.');
  const tau = T2 - t1;
  const ext = (s) => gbsm({ type, S: s, X: X2, T: tau, r, b, v }) - A;
  const pay = (s) => (call ? s - X1 : X1 - s);
  const cross = (s) => ext(s) - pay(s); // konveks i s
  const scale = Math.max(X1, X2, A, 1e-12);
  const roots = [X1];
  const addRoot = (f, lo, hi) => {
    const flo = f(lo);
    const fhi = f(hi);
    if (Number.isFinite(flo) && Number.isFinite(fhi) && flo * fhi < 0) roots.push(brent(f, lo, hi, { tol: 1e-12 * scale }));
  };
  const tiny = scale * 1e-8;
  const huge = scale * 1e8;
  // 1) ext(s) = 0: ext er monoton i s.
  addRoot(ext, tiny, huge);
  // 2) ext(s) = utbetaling: konveks funksjon, maks to nullpunkter rundt minimumspunktet.
  let sMin = null;
  if (b > r) {
    // Minimum der |delta| = 1: call e^{(b−r)τ}N(d1) = 1, put e^{(b−r)τ}N(−d1) = 1.
    const p = Math.exp(-(b - r) * tau);
    const d1 = call ? cndInv(p) : -cndInv(p);
    sMin = X2 * Math.exp(d1 * v * Math.sqrt(tau) - (b + 0.5 * v * v) * tau);
  }
  if (sMin !== null && sMin > tiny && sMin < huge) {
    addRoot(cross, tiny, sMin);
    addRoot(cross, sMin, huge);
  } else {
    addRoot(cross, tiny, huge);
  }
  const pts = [...new Set(roots)].filter((x) => x > 0).sort((x, y) => x - y);
  // Klassifiser hvert intervall mellom brytpunktene og summer bidragene.
  const st1 = v * Math.sqrt(t1);
  const e1 = (K) => (K === 0 ? Infinity : K === Infinity ? -Infinity : (Math.log(S / K) + (b + 0.5 * v * v) * t1) / st1);
  const z1 = (Math.log(S / X2) + (b + 0.5 * v * v) * T2) / (v * Math.sqrt(T2));
  const z2 = z1 - v * Math.sqrt(T2);
  const rho = Math.sqrt(t1 / T2);
  const fS1 = S * Math.exp((b - r) * t1);
  const fS2 = S * Math.exp((b - r) * T2);
  const fX1 = X1 * Math.exp(-r * t1);
  const fX2 = X2 * Math.exp(-r * T2);
  const fA = A * Math.exp(-r * t1);
  const edges = [0, ...pts, Infinity];
  let price = 0;
  const extRegion = [];
  for (let k = 0; k < edges.length - 1; k++) {
    const lo = edges[k];
    const hi = edges[k + 1];
    const mid = lo === 0 ? hi / 2 : hi === Infinity ? lo * 2 : Math.sqrt(lo * hi);
    const vExt = ext(mid);
    const vPay = pay(mid);
    const a1 = e1(lo);
    const c1 = e1(hi);
    const a2 = a1 - st1;
    const c2 = c1 - st1;
    if (vExt > 0 && vExt >= vPay) {
      extRegion.push([lo, hi]);
      const pIn = cnd(a2) - cnd(c2);
      if (call) {
        price += fS2 * (cbnd(a1, z1, rho) - cbnd(c1, z1, rho)) - fX2 * (cbnd(a2, z2, rho) - cbnd(c2, z2, rho)) - fA * pIn;
      } else {
        price += fX2 * (cbnd(a2, -z2, -rho) - cbnd(c2, -z2, -rho)) - fS2 * (cbnd(a1, -z1, -rho) - cbnd(c1, -z1, -rho)) - fA * pIn;
      }
    } else if (vPay > 0) {
      const sign = call ? 1 : -1;
      price += sign * (fS1 * (cnd(a1) - cnd(c1)) - fX1 * (cnd(a2) - cnd(c2)));
    }
  }
  const vanilla = gbsm({ type, S, X: X1, T: t1, r, b, v });
  // Slå sammen tilstøtende intervaller (X1 er alltid et brytpunkt). Med b > r kan det være to
  // adskilte forlengelsesområder; I1 og I2 er grensene for det første (Longstaffs kritiske priser).
  const regions = [];
  for (const [lo, hi] of extRegion) {
    if (regions.length && regions[regions.length - 1][1] === lo) regions[regions.length - 1][1] = hi;
    else regions.push([lo, hi]);
  }
  const I1 = regions.length ? regions[0][0] : null;
  const I2 = regions.length ? regions[0][1] : null;
  return { price, vanilla, I1, I2, regions };
}

// Utstederen forlenger opsjonen til T2 med ny innløsningskurs X2 hvis den er ute av pengene ved t1.
export function writerExtendible({ type, S, X1, X2, t1, T2, r, b, v }) {
  const call = isCall(type);
  if (!(t1 > 0)) throw new Error('Tidspunktet t1 må være positivt.');
  requireOrder(t1, T2, 'Det forlengede forfallet T2 må være etter t1.');
  const rho = Math.sqrt(t1 / T2);
  const z1 = (Math.log(S / X2) + (b + 0.5 * v * v) * T2) / (v * Math.sqrt(T2));
  const z2 = (Math.log(S / X1) + (b + 0.5 * v * v) * t1) / (v * Math.sqrt(t1));
  const vanilla = gbsm({ type, S, X: X1, T: t1, r, b, v });
  const fS = S * Math.exp((b - r) * T2);
  const fX = X2 * Math.exp(-r * T2);
  const s2 = v * Math.sqrt(T2);
  const s1 = v * Math.sqrt(t1);
  const extra = call
    ? fS * cbnd(z1, -z2, -rho) - fX * cbnd(z1 - s2, -z2 + s1, -rho)
    : fX * cbnd(-z1 + s2, z2 - s1, -rho) - fS * cbnd(-z1, z2, -rho);
  return { price: vanilla + extra, vanilla };
}
