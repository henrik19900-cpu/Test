// Kapittel 11: rentederivater.
//
//   Pengemarked:   moneyMarketRates (enkel rente, diskonteringsrente, kontinuerlig, dagtelling),
//                  fra, futuresConvexity / futuresToForward (konveksitetsjustering)
//   Obligasjoner:  bondCashflows, bondFromYield (pris, durasjon, konveksitet), bondYield
//   Black-76:      moneyMarketFuturesOption, caplet, capFloor, swaption, bondOptionBlack
//   Schaefer og Schwartz (1987): prisvolatilitet proporsjonal med durasjonen (finite difference)
//   Ett-faktor:    vasicekBond, vasicekOption, vasicekCouponOption (Jamshidian 1989),
//                  hoLeeOption, hullWhiteOption, rendlemanBartter (tre), bdtCalibrate / bdtOption
//
// Renter og volatiliteter er desimaltall (0,08 = 8 %). Tider er i år.

import { cnd } from '../math/normal.js';
import { brent } from '../math/solvers.js';
import { gbsm, isCall } from './bsm.js';
import { decay, decaySqInt } from './commodity.js';

// Udiskontert eller diskontert Black-76 via GBSM med b = 0.
function black76({ type, F, X, T, r = 0, v }) {
  return gbsm({ type, S: F, X, T, r, b: 0, v });
}

// Finn rot i en avtagende funksjon f ved å utvide [lo, hi] til fortegnet skifter.
function rootDecreasing(f, lo, hi, { lower = -Infinity, upper = Infinity, tol = 1e-14 } = {}) {
  let flo = f(lo);
  let fhi = f(hi);
  for (let i = 0; i < 200 && flo < 0; i++) {
    lo = Number.isFinite(lower) ? lower + (lo - lower) / 2 : lo - 2 * Math.max(1, Math.abs(lo));
    flo = f(lo);
  }
  for (let i = 0; i < 200 && fhi > 0; i++) {
    hi = Number.isFinite(upper) ? upper - (upper - hi) / 2 : hi + 2 * Math.max(1, Math.abs(hi));
    fhi = f(hi);
  }
  if (!(flo >= 0 && fhi <= 0)) throw new Error('Fant ingen løsning.');
  return brent(f, lo, hi, { tol });
}

// --- Pengemarked -------------------------------------------------------------------------

// Gjør om én rente til alle de andre konvensjonene via diskonteringsfaktoren for perioden.
// Enkel rente og diskonteringsrente bruker valgt dagtelling (ACT/360 eller ACT/365);
// kontinuerlig og årlig/m-vis rente bruker ACT/365.
export function moneyMarketRates({ from, rate, days, basis = 360, m = 2 }) {
  if (!(days > 0)) throw new Error('Antall dager må være positivt.');
  const t365 = days / 365;
  const tau = days / basis;
  let df;
  if (from === 'simple') df = 1 / (1 + rate * tau);
  else if (from === 'discount') df = 1 - rate * tau;
  else if (from === 'cont') df = Math.exp(-rate * t365);
  else if (from === 'comp') df = 1 + rate / m > 0 ? (1 + rate / m) ** (-m * t365) : NaN;
  else throw new Error('Ukjent rentekonvensjon.');
  if (!(df > 0) || !Number.isFinite(df)) throw new Error('Renten gir en diskonteringsfaktor som ikke er positiv.');
  const growth = 1 / df;
  return {
    df,
    simple360: (growth - 1) / (days / 360),
    simple365: (growth - 1) / (days / 365),
    discount: (1 - df) / tau,
    cont: Math.log(growth) / t365,
    annual: growth ** (1 / t365) - 1,
    comp: m * (growth ** (1 / (m * t365)) - 1),
  };
}

// FRA fra to pengemarkedsrenter (enkel rente) med samme dagtelling:
//   (1 + r2 t2) = (1 + r1 t1)(1 + F τ),  τ = t2 − t1.
// Verdi i dag for kjøperen (betaler fast X, mottar flytende): N τ (F − X)/(1 + r2 t2).
// Oppgjør ved T1 når fiksingen blir L: N (L − X) τ/(1 + L τ).
export function fra({ r1, d1, r2, d2, basis = 360, X, N = 1, L }) {
  if (!(d2 > d1)) throw new Error('Slutten av FRA-perioden må komme etter starten (d2 > d1).');
  if (!(d1 >= 0)) throw new Error('Antall dager til start kan ikke være negativt.');
  const t1 = d1 / basis;
  const t2 = d2 / basis;
  const tau = t2 - t1;
  const df1 = 1 / (1 + r1 * t1);
  const df2 = 1 / (1 + r2 * t2);
  const F = (df1 / df2 - 1) / tau;
  return {
    F,
    value: N * tau * (F - X) * df2,
    settlement: L === undefined ? NaN : N * (L - X) * tau / (1 + L * tau),
    tau,
    df1,
    df2,
  };
}

// Konveksitetsjustering mellom futuresrente og forwardrente (kontinuerlig forrentning) for
// perioden [t1, t2] når kortrenten har absolutt volatilitet σ og mean reversion a:
//   Ho og Lee (a = 0):  σ² t1 t2 / 2
//   Hull og White:      [B(t1,t2)/(t2 − t1)] [B(t1,t2)(1 − e^{−2a t1}) + 2a B(0,t1)²] σ²/(4a)
export function futuresConvexity({ t1, t2, v, a = 0 }) {
  if (!(t2 > t1)) throw new Error('Renteperioden må ha positiv lengde.');
  if (!(a >= 0)) throw new Error('Mean reversion kan ikke være negativ.');
  const tau = t2 - t1;
  const Bt = decay(a, tau);
  return 0.5 * v * v * (Bt / tau) * (Bt * decay(2 * a, t1) + decay(a, t1) ** 2);
}

// Pengemarkedsfutures notert som 100 − rente (enkel rente for perioden τ).
export function futuresToForward({ Pf, t1, tau, v, a = 0 }) {
  const Rf = (100 - Pf) / 100;
  if (!(1 + Rf * tau > 0)) throw new Error('Futuresprisen gir en ugyldig rente.');
  const Rc = Math.log1p(Rf * tau) / tau;
  const adj = futuresConvexity({ t1, t2: t1 + tau, v, a });
  const Fc = Rc - adj;
  return { futuresRate: Rf, futuresCont: Rc, adj, forwardCont: Fc, forwardSimple: Math.expm1(Fc * tau) / tau };
}

// --- Obligasjonsmatematikk ---------------------------------------------------------------

// Kontantstrømmer for en kupongobligasjon med pålydende L, årlig kupongrente c og m kuponger
// per år som forfaller om T år. Første kupong kommer om T − ⌊…⌋/m år.
export function bondCashflows({ c, m, T, L = 100 }) {
  if (!(T > 0)) throw new Error('Tid til forfall må være positiv.');
  if (!(m >= 1)) throw new Error('Antall kuponger per år må være minst 1.');
  const C = L * c / m;
  const times = [];
  for (let k = 0; k < 100000; k++) {
    const t = T - k / m;
    if (t <= 1e-10) break;
    times.push(t);
  }
  times.reverse();
  const amounts = times.map((_, i) => C + (i === times.length - 1 ? L : 0));
  const accrued = C * (1 - m * times[0]);
  return { times, amounts, accrued, coupon: C };
}

// Pris (inkl. påløpte renter), Macaulay- og modifisert durasjon, konveksitet og DV01 når
// yielden y har m forrentninger per år: B = Σ a_i (1 + y/m)^{−m t_i}.
export function bondFromYield({ y, c, m, T, L = 100 }) {
  const { times, amounts, accrued } = bondCashflows({ c, m, T, L });
  const base = 1 + y / m;
  if (!(base > 0)) throw new Error('Yielden må være større enn −m.');
  let P = 0;
  let D = 0;
  let C2 = 0;
  for (let i = 0; i < times.length; i++) {
    const t = times[i];
    const pv = amounts[i] * base ** (-m * t);
    P += pv;
    D += t * pv;
    C2 += t * (t + 1 / m) * pv;
  }
  const macaulay = D / P;
  const modified = macaulay / base;
  return {
    dirty: P,
    clean: P - accrued,
    accrued,
    macaulay,
    modified,
    convexity: C2 / (P * base * base),
    dv01: modified * P * 1e-4,
  };
}

// Yield (m forrentninger per år) som gir en observert pris.
export function bondYield({ price, priceType = 'clean', c, m, T, L = 100 }) {
  const { accrued } = bondCashflows({ c, m, T, L });
  const dirty = priceType === 'clean' ? price + accrued : price;
  if (!(dirty > 0)) throw new Error('Prisen inkludert påløpte renter må være positiv.');
  const f = (y) => bondFromYield({ y, c, m, T, L }).dirty - dirty;
  const y = rootDecreasing(f, Math.max(-0.5 * m, -0.5), 0.5, { lower: -m });
  return { y, dirty, accrued, ...bondFromYield({ y, c, m, T, L }) };
}

// --- Black-76 for renteopsjoner ----------------------------------------------------------

// Opsjon på pengemarkedsfutures notert som 100 − rente. Futuresrenten F_r = 100 − F er
// lognormal, og en call på futuresprisen er en put på renten med innløsningsrente 100 − X.
export function moneyMarketFuturesOption({ type = 'call', F, X, T, r, v }) {
  const Fr = 100 - F;
  const Xr = 100 - X;
  if (!(Fr > 0) || !(Xr > 0)) throw new Error('Futures- og innløsningskurs må være under 100 (positiv rente).');
  const rateType = isCall(type) ? 'put' : 'call';
  return { price: black76({ type: rateType, F: Fr, X: Xr, T, r, v }), Fr, Xr };
}

// Caplet (call på renten) / floorlet (put). Renten for perioden [T, T + τ] fikseres ved T og
// betales ved T + τ. Diskontering: e^{−rT} til fiksering og 1/(1 + Fτ) videre til betaling.
export function caplet({ type = 'call', F, X, T, tau, r, v, N = 1 }) {
  const df = Math.exp(-r * T) / (1 + F * tau);
  return N * tau * df * black76({ type, F, X, T, v });
}

// Cap/floor som summen av caplets/floorlets med fikseringer T_i og forwardrenter F_i.
export function capFloor({ type = 'call', times, forwards, X, tau, r, v, N = 1 }) {
  if (times.length === 0) throw new Error('Oppgi minst én fiksering.');
  if (forwards.length !== times.length) throw new Error('Det må være like mange forwardrenter som fikseringer.');
  const call = isCall(type);
  const parts = [];
  const other = [];
  let swap = 0;
  for (let i = 0; i < times.length; i++) {
    if (!(times[i] > 0)) throw new Error('Fikseringstidspunktene må være positive.');
    const q = { F: forwards[i], X, T: times[i], tau, r, v, N };
    parts.push(caplet({ type, ...q }));
    other.push(caplet({ type: call ? 'put' : 'call', ...q }));
    swap += N * tau * (forwards[i] - X) * Math.exp(-r * times[i]) / (1 + forwards[i] * tau);
  }
  const sum = (a) => a.reduce((s, x) => s + x, 0);
  return { price: sum(parts), parts, otherPrice: sum(other), swap };
}

// Europeisk swapsjon (Haugs form): annuiteten beregnes med forward swaprenten selv,
//   A = [1 − (1 + F/m)^{−t1 m}]/F,  payer = A e^{−rT}[F N(d1) − X N(d2)].
export function swaptionAnnuity(F, t1, m) {
  if (Math.abs(F) < 1e-12) return t1;
  return -Math.expm1(-t1 * m * Math.log1p(F / m)) / F;
}

export function swaption({ type = 'call', F, X, T, t1, m, r, v, N = 1 }) {
  if (!(t1 > 0)) throw new Error('Swappens løpetid må være positiv.');
  const annuity = swaptionAnnuity(F, t1, m);
  const scale = N * annuity * Math.exp(-r * T);
  return { price: scale * black76({ type, F, X, T, v }), annuity, forwardValue: scale * (F - X) };
}

// Europeisk obligasjonsopsjon med Black-76 på forward obligasjonskurs. Yield-volatilitet
// gjøres om til prisvolatilitet med σ_P ≈ D · y · σ_y (D = modifisert durasjon ved T).
export function bondOptionBlack({ type = 'call', F, X, T, r, volType = 'price', v, y, D }) {
  const vp = volType === 'yield' ? v * y * D : v;
  const vy = volType === 'yield' ? v : (y * D > 0 ? v / (y * D) : NaN);
  return { price: black76({ type, F, X, T, r, v: vp }), vPrice: vp, vYield: vy };
}

// --- Schaefer og Schwartz (1987) ---------------------------------------------------------
//
// Obligasjonsprisen B har risikonøytral drift r og volatilitet σ(B, t) = K B^{α−1} D(t),
// der durasjonen avtar med tiden, D(t) = max(D − t, 0). K kalibreres slik at volatiliteten
// i dag er σ: K = σ B^{1−α}/D. For α = 1 er modellen lognormal med varians
// σ² [D³ − (D − T)³]/(3D²), og BSM med denne volatiliteten er eksakt.
export function schaeferSchwartzBSM({ type = 'call', S, X, T, r, v, D }) {
  const Dm = Math.max(D - T, 0);
  const veff = v * Math.sqrt((D ** 3 - Dm ** 3) / (3 * D * D * T));
  return { price: gbsm({ type, S, X, T, r, b: r, v: veff }), veff };
}

// Europeisk opsjon i Schaefer-Schwartz-modellen for vilkårlig α, løst med Crank-Nicolson
// (Rannacher-start) i forwardvariabelen y = ln(B e^{r(T−t)}). Der er driften −s²/2, så
// løsningen står stille når volatiliteten går mot null.
export function schaeferSchwartz({ type = 'call', S, X: Xin, T: Tin, r, v, D, alpha, J = 400, steps = 100 }) {
  const call = isCall(type);
  if (!(D > 0)) throw new Error('Durasjonen må være positiv.');
  // Etter t = D er volatiliteten null og obligasjonen vokser med r. En opsjon med forfall T > D
  // er derfor lik en opsjon med forfall D og innløsningskurs X e^{−r(T − D)}.
  const T = Math.min(Tin, D);
  const X = Xin * Math.exp(-r * (Tin - T));
  const disc = Math.exp(-r * T);
  const G0 = S / disc;
  const sbar = v * Math.sqrt(T);
  if (!(sbar > 1e-10)) return disc * Math.max(call ? G0 - X : X - G0, 0);
  const K = v * S ** (1 - alpha) / D;
  const y0 = Math.log(G0);
  const lnX = Math.log(X);
  const W = Math.max(7 * sbar, Math.abs(lnX - y0) + 5 * sbar);
  const h = W / J;
  const M = 2 * J + 1;
  const pw = new Float64Array(M);
  let U = new Float64Array(M);
  // Utbetalingen midles over hver celle [y_j − h/2, y_j + h/2], slik at knekken i X ikke gir
  // svingninger når X eller B flyttes i forhold til gitteret.
  const cellPayoff = (y) => {
    const a = y - h / 2;
    const b = y + h / 2;
    if (call) {
      if (b <= lnX) return 0;
      if (a >= lnX) return (Math.exp(b) - Math.exp(a)) / h - X;
      return (Math.exp(b) - X - X * (b - lnX)) / h;
    }
    if (a >= lnX) return 0;
    if (b <= lnX) return X - (Math.exp(b) - Math.exp(a)) / h;
    return (X * (lnX - a) - (X - Math.exp(a))) / h;
  };
  for (let j = 0; j < M; j++) {
    const y = y0 + (j - J) * h;
    pw[j] = Math.exp(2 * (alpha - 1) * y);
    U[j] = cellPayoff(y);
  }
  // Randverdier (martingal i forwardmålet): call = e^{y} − X øverst, put = X − e^{y} nederst.
  const uLow = call ? 0 : X - Math.exp(y0 - J * h);
  const uHigh = call ? Math.exp(y0 + J * h) - X : 0;
  U[0] = uLow;
  U[M - 1] = uHigh;
  const lo = new Float64Array(M);
  const di = new Float64Array(M);
  const up = new Float64Array(M);
  const rhs = new Float64Array(M);
  const cp = new Float64Array(M);
  const dp = new Float64Array(M);
  let Un = new Float64Array(M);
  // Operatoren L = (s²/2)(∂yy − ∂y), der s² = K² D(t)² e^{−2(α−1)r(T−t)} e^{2(α−1)y}.
  const h2 = h * h;
  const lA = 0.5 / h2 + 0.25 / h;
  const lB = -1 / h2;
  const lC = 0.5 / h2 - 0.25 / h;
  const level = (tau) => K * K * Math.max(D - (T - tau), 0) ** 2 * Math.exp(-2 * (alpha - 1) * r * tau);
  // Rannacher-start: de to første stegene erstattes av fire implisitte halvsteg.
  const dtau = T / steps;
  let tau = 0;
  for (let step = 0; step < steps + 2; step++) {
    const implicit = step < 4;
    const dt = implicit ? dtau / 2 : dtau;
    const theta = implicit ? 1 : 0.5;
    const fOld = level(tau) * (1 - theta) * dt;
    const fNew = level(tau + dt) * theta * dt;
    for (let j = 1; j < M - 1; j++) {
      rhs[j] = U[j] + fOld * pw[j] * (lA * U[j - 1] + lB * U[j] + lC * U[j + 1]);
      const sNew = fNew * pw[j];
      lo[j] = -sNew * lA;
      di[j] = 1 - sNew * lB;
      up[j] = -sNew * lC;
    }
    // Thomas-algoritmen med kjente randverdier.
    rhs[1] -= lo[1] * uLow;
    rhs[M - 2] -= up[M - 2] * uHigh;
    cp[1] = up[1] / di[1];
    dp[1] = rhs[1] / di[1];
    for (let j = 2; j < M - 1; j++) {
      const den = di[j] - lo[j] * cp[j - 1];
      cp[j] = up[j] / den;
      dp[j] = (rhs[j] - lo[j] * dp[j - 1]) / den;
    }
    Un[0] = uLow;
    Un[M - 1] = uHigh;
    Un[M - 2] = dp[M - 2];
    for (let j = M - 3; j >= 1; j--) Un[j] = dp[j] - cp[j] * Un[j + 1];
    const tmp = U;
    U = Un;
    Un = tmp;
    tau += dt;
  }
  return disc * U[J];
}

// --- Ett-faktor rentemodeller ------------------------------------------------------------

// Opsjon på nullkupongobligasjon med pålydende L i gaussiske ett-faktormodeller:
//   c = L P(0,s) N(h) − X P(0,T) N(h − σ_P),  p = X P(0,T) N(σ_P − h) − L P(0,s) N(−h),
//   h = ln[L P(0,s)/(X P(0,T))]/σ_P + σ_P/2.
export function zcbOption({ type = 'call', L, X, P0T, P0s, sigmaP }) {
  const call = isCall(type);
  if (!(sigmaP > 0)) {
    const fwd = L * P0s - X * P0T;
    return Math.max(call ? fwd : -fwd, 0);
  }
  const h = Math.log(L * P0s / (X * P0T)) / sigmaP + sigmaP / 2;
  return call
    ? L * P0s * cnd(h) - X * P0T * cnd(h - sigmaP)
    : X * P0T * cnd(sigmaP - h) - L * P0s * cnd(-h);
}

// Vasicek (1977): dr = κ(θ − r) dt + σ dz. P(t,T) = A e^{−B r} med B = (1 − e^{−κτ})/κ og
//   ln A = (B − τ)(κ²θ − σ²/2)/κ² − σ²B²/(4κ),
// her regnet som −E[∫r] + Var[∫r]/2 slik at grensen κ → 0 blir stabil.
export function vasicekBond({ r, kappa, theta, v, T }) {
  const B = decay(kappa, T);
  const lnP = -(theta * T + (r - theta) * B) + 0.5 * v * v * decaySqInt(kappa, T);
  return { P: Math.exp(lnP), B, lnA: lnP + B * r };
}

// Prisvolatiliteten σ_P for en opsjon med forfall T på en nullkupong med forfall s når
// kortrenten har Hull-White/Vasicek-dynamikk (κ = 0 gir Ho og Lee: σ (s − T) √T).
export function gaussianSigmaP({ v, kappa, T, s }) {
  return v * decay(kappa, s - T) * Math.sqrt(decay(2 * kappa, T));
}

function checkBondOption(T, s) {
  if (!(s > T)) throw new Error('Obligasjonen må forfalle etter opsjonen (s > T).');
}

export function vasicekOption({ type = 'call', L, X, T, s, r, kappa, theta, v }) {
  checkBondOption(T, s);
  const P0T = vasicekBond({ r, kappa, theta, v, T }).P;
  const P0s = vasicekBond({ r, kappa, theta, v, T: s }).P;
  const sigmaP = gaussianSigmaP({ v, kappa, T, s });
  return { price: zcbOption({ type, L, X, P0T, P0s, sigmaP }), P0T, P0s, sigmaP };
}

// Jamshidian (1989): opsjon på kupongobligasjon i Vasicek som en sum av opsjoner på
// nullkuponger. r* løser Σ a_i P(T, t_i; r*) = X, og delstrikene er K_i = a_i P(T, t_i; r*).
export function vasicekCouponOption({ type = 'call', L, c, m, s, X, T, r, kappa, theta, v }) {
  checkBondOption(T, s);
  const { times, amounts } = bondCashflows({ c, m, T: s, L });
  const flows = [];
  for (let i = 0; i < times.length; i++) if (times[i] > T + 1e-10 && amounts[i] > 0) flows.push([times[i], amounts[i]]);
  if (flows.length === 0) throw new Error('Obligasjonen har ingen kontantstrømmer etter opsjonens forfall.');
  const bondAt = (rr) => flows.reduce((acc, [t, a]) => acc + a * vasicekBond({ r: rr, kappa, theta, v, T: t - T }).P, 0);
  const rStar = rootDecreasing((rr) => bondAt(rr) - X, -0.5, 0.5);
  const P0T = vasicekBond({ r, kappa, theta, v, T }).P;
  let price = 0;
  let bond = 0;
  for (const [t, a] of flows) {
    const P0t = vasicekBond({ r, kappa, theta, v, T: t }).P;
    const Ki = a * vasicekBond({ r: rStar, kappa, theta, v, T: t - T }).P;
    price += zcbOption({ type, L: a, X: Ki, P0T, P0s: P0t, sigmaP: gaussianSigmaP({ v, kappa, T, s: t }) });
    bond += a * P0t;
  }
  return { price, rStar, bond, forward: bond / P0T, n: flows.length };
}

// Ho og Lee (1986) og Hull og White (1990) med flat startkurve P(0,t) = e^{−rt}.
export function hoLeeOption({ type = 'call', L, X, T, s, r, v }) {
  checkBondOption(T, s);
  const P0T = Math.exp(-r * T);
  const P0s = Math.exp(-r * s);
  const sigmaP = v * (s - T) * Math.sqrt(T);
  return { price: zcbOption({ type, L, X, P0T, P0s, sigmaP }), P0T, P0s, sigmaP };
}

export function hullWhiteOption({ type = 'call', L, X, T, s, r, kappa, v }) {
  checkBondOption(T, s);
  const P0T = Math.exp(-r * T);
  const P0s = Math.exp(-r * s);
  const sigmaP = gaussianSigmaP({ v, kappa, T, s });
  return { price: zcbOption({ type, L, X, P0T, P0s, sigmaP }), P0T, P0s, sigmaP };
}

// Rendleman og Bartter (1980): kortrenten følger dr = μ r dt + σ r dz. Binomialtre med
// u = e^{σ√Δt}, d = 1/u, p = (e^{μΔt} − d)/(u − d) og diskontering e^{−r Δt} i hver node.
// Treet går til obligasjonens forfall s med n steg. Når T ikke ligger på et steg,
// interpoleres det lineært mellom de to nærmeste forfallene, slik at prisen blir kontinuerlig i T.
export function rendlemanBartter({ type = 'call', exercise = 'european', L, X, T, s, r, mu, v, n }) {
  checkBondOption(T, s);
  if (!(n >= 1)) throw new Error('Antall steg må være minst 1.');
  const call = isCall(type);
  const american = exercise === 'american';
  const dt = s / n;
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp(mu * dt) - d) / (u - d);
  if (!(p > 0 && p < 1)) throw new Error('Sannsynligheten i treet havner utenfor (0, 1). Øk antall steg.');
  const kT = T / dt;
  const k0 = Math.min(Math.floor(kT + 1e-9), n);
  const w = Math.max(0, kT - k0);
  const k1 = w > 1e-12 ? Math.min(k0 + 1, n) : k0;
  // Diskonteringsfaktorene e^{−r_{i,j} Δt} i steg i, der r_{i,j} = r u^{2j − i}.
  const u2 = u * u;
  const discRow = (i) => {
    const row = new Float64Array(i + 1);
    let rate = r * u ** -i;
    for (let j = 0; j <= i; j++) {
      row[j] = Math.exp(-rate * dt);
      rate *= u2;
    }
    return row;
  };
  // Obligasjonsverdier bakover fra forfall. Lagrer steg 0..k1 (trengs for amerikansk innløsning).
  const bondSteps = new Array(k1 + 1);
  const discSteps = new Array(k1 + 1);
  let bond = new Float64Array(n + 1).fill(L);
  for (let i = n; i >= 0; i--) {
    if (i < n) {
      const dr = discRow(i);
      const next = new Float64Array(i + 1);
      for (let j = 0; j <= i; j++) next[j] = dr[j] * (p * bond[j + 1] + (1 - p) * bond[j]);
      bond = next;
      if (i <= k1) discSteps[i] = dr;
    }
    if (i <= k1) bondSteps[i] = bond;
  }
  const optionFrom = (k) => {
    const pay = (B) => Math.max(call ? B - X : X - B, 0);
    let V = Float64Array.from(bondSteps[k], pay);
    for (let i = k - 1; i >= 0; i--) {
      const dr = discSteps[i];
      const next = new Float64Array(i + 1);
      for (let j = 0; j <= i; j++) {
        const cont = dr[j] * (p * V[j + 1] + (1 - p) * V[j]);
        next[j] = american ? Math.max(cont, pay(bondSteps[i][j])) : cont;
      }
      V = next;
    }
    return V[0];
  };
  const v0 = optionFrom(k0);
  const price = k1 === k0 ? v0 : (1 - w) * v0 + w * optionFrom(k1);
  return { price, bond: bondSteps[0][0], p, dt };
}

// Black, Derman og Toy (1990): binomialtre for kortrenten kalibrert til nullkupongrenter og
// yield-volatiliteter. Rentene i steg i er r_{i,j} = a_i e^{2σ_i j √Δt} (j = 0..i), med
// diskontering 1/(1 + r Δt) og sannsynlighet ½. Nullkupongrentene y_k har én forrentning per
// Δt, P(0, kΔt) = (1 + y_k Δt)^{−k}. Yield-volatiliteten for løpetid kΔt er ln(y_u/y_d)/(2√Δt),
// der y_u og y_d er yieldene til den samme obligasjonen i opp- og nednoden etter ett steg.
export function bdtCalibrate({ maturities, yields, vols }) {
  const N = maturities.length;
  if (N < 2) throw new Error('Oppgi minst to løpetider.');
  if (yields.length !== N || vols.length !== N) {
    throw new Error('Det må være like mange renter og volatiliteter som løpetider.');
  }
  const dt = maturities[0];
  if (!(dt > 0)) throw new Error('Løpetidene må være positive.');
  for (let i = 0; i < N; i++) {
    if (Math.abs(maturities[i] - (i + 1) * dt) > 1e-9 * Math.max(1, maturities[i])) {
      throw new Error('Løpetidene må være jevnt fordelt: Δt, 2Δt, 3Δt, …');
    }
    if (!(yields[i] > 0)) throw new Error('Nullkupongrentene må være positive.');
    if (i > 0 && !(vols[i] > 0)) throw new Error('Yield-volatilitetene må være positive.');
  }
  const sq = Math.sqrt(dt);
  const P = yields.map((y, i) => (1 + y * dt) ** -(i + 1));
  const rates = [Float64Array.of(yields[0])];
  const sigmas = [NaN];
  const advance = (Q, row) => {
    const out = new Float64Array(row.length + 1);
    for (let j = 0; j < row.length; j++) {
      const x = 0.5 * Q[j] / (1 + row[j] * dt);
      out[j] += x;
      out[j + 1] += x;
    }
    return out;
  };
  let Qu = null;
  let Qd = null;
  for (let i = 1; i < N; i++) {
    // Mål for prisene i opp- og nednoden av obligasjonen som forfaller ved (i+1)Δt.
    const target = 2 * P[i] * (1 + rates[0][0] * dt);
    const ratio = Math.exp(2 * vols[i] * sq);
    const fy = (yd) => (1 + yd * ratio * dt) ** -i + (1 + yd * dt) ** -i - target;
    const yd = rootDecreasing(fy, 1e-6, 1, { lower: 0 });
    const Pu = (1 + yd * ratio * dt) ** -i;
    const Pd = (1 + yd * dt) ** -i;
    let row;
    let sigma;
    if (i === 1) {
      const rd = (1 / Pd - 1) / dt;
      const ru = (1 / Pu - 1) / dt;
      sigma = Math.log(ru / rd) / (2 * sq);
      row = Float64Array.of(rd, ru);
      Qu = Float64Array.of(0, 1);
      Qd = Float64Array.of(1, 0);
    } else {
      const priceFrom = (Q, a, s) => {
        let sum = 0;
        for (let j = 0; j <= i; j++) if (Q[j] !== 0) sum += Q[j] / (1 + a * Math.exp(2 * s * j * sq) * dt);
        return sum;
      };
      const aOf = (s) => rootDecreasing((a) => priceFrom(Qd, a, s) - Pd, 0, 1, { lower: 0 });
      const resid = (s) => priceFrom(Qu, aOf(s), s) - Pu;
      sigma = rootDecreasing(resid, 1e-4, 1, { lower: 0 });
      const a = aOf(sigma);
      row = Float64Array.from({ length: i + 1 }, (_, j) => a * Math.exp(2 * sigma * j * sq));
    }
    rates.push(row);
    sigmas.push(sigma);
    if (i < N - 1) {
      Qu = advance(Qu, row);
      Qd = advance(Qd, row);
    }
  }
  return { dt, rates, sigmas, P };
}

// Europeisk eller amerikansk opsjon på en nullkupongobligasjon i et kalibrert BDT-tre.
// kT og ks er antall steg à Δt til opsjonens og obligasjonens forfall.
export function bdtOption({ type = 'call', exercise = 'european', L, X, kT, ks, tree }) {
  const { dt, rates } = tree;
  if (!(ks <= rates.length)) throw new Error('Obligasjonen kan ikke forfalle etter siste løpetid i rentekurven.');
  if (!(kT >= 0 && kT < ks)) throw new Error('Opsjonen må forfalle før obligasjonen.');
  const call = isCall(type);
  const american = exercise === 'american';
  const bondSteps = new Array(ks + 1);
  bondSteps[ks] = new Float64Array(ks + 1).fill(L);
  for (let i = ks - 1; i >= 0; i--) {
    const next = new Float64Array(i + 1);
    for (let j = 0; j <= i; j++) next[j] = 0.5 * (bondSteps[i + 1][j] + bondSteps[i + 1][j + 1]) / (1 + rates[i][j] * dt);
    bondSteps[i] = next;
  }
  const pay = (B) => Math.max(call ? B - X : X - B, 0);
  let V = Float64Array.from(bondSteps[kT], pay);
  for (let i = kT - 1; i >= 0; i--) {
    const next = new Float64Array(i + 1);
    for (let j = 0; j <= i; j++) {
      const cont = 0.5 * (V[j] + V[j + 1]) / (1 + rates[i][j] * dt);
      next[j] = american ? Math.max(cont, pay(bondSteps[i][j])) : cont;
    }
    V = next;
  }
  return { price: V[0], bond: bondSteps[0][0], bondSteps };
}
