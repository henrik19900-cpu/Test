// Kapittel 10: råvare- og energiderivater.
//
//   energySwap            verdi av en energiswap (fastpris mot forwardpriser) og swapprisen
//   energySwaption        europeisk energiswapsjon: Black (1976) på swapprisen
//   miltersenSchwartz     Miltersen og Schwartz (1998): opsjon på råvarefutures med stokastisk
//                         rente og stokastisk convenience yield (gaussiske HJM-faktorer)
//   schwartz1f*           Schwartz (1997) én-faktor: ln S følger en Ornstein-Uhlenbeck-prosess
//   schwartz2f*           Gibson og Schwartz (1990) / Schwartz (1997) to-faktor: stokastisk
//                         convenience yield med mean reversion
//
// Notasjon som i Haug: T er opsjonens løpetid, T2 futureskontraktens forfall (T2 ≥ T).

import { gbsm } from './bsm.js';
import { gaussLegendreComposite } from '../math/integrate.js';

const SMALL = 1e-3;

// g(κ, x) = (1 − e^{−κx})/κ, med grenseverdien x når κ → 0.
export function decay(k, x) {
  return k === 0 ? x : -Math.expm1(-k * x) / k;
}

// ∫_0^w g(κ, x) dx = (w − g(κ, w))/κ, med rekkeutvikling for små κw.
export function decayInt(k, w) {
  const z = k * w;
  if (Math.abs(z) < SMALL) return w * w * (0.5 - z / 6 + z * z / 24 - z * z * z / 120);
  return (w - decay(k, w)) / k;
}

// ∫_0^w g(κ, x)² dx = (w − 2g(κ, w) + g(2κ, w))/κ², med rekkeutvikling for små κw.
export function decaySqInt(k, w) {
  const z = k * w;
  if (Math.abs(z) < SMALL) return w ** 3 * (1 / 3 - z / 4 + 7 * z * z / 60 - z * z * z / 24);
  return (w - 2 * decay(k, w) + decay(2 * k, w)) / (k * k);
}

// Udiskontert eller diskontert Black-76 via GBSM med b = 0.
function black76({ type, F, X, T, r, v }) {
  return gbsm({ type, S: F, X, T, r, b: 0, v });
}

// --- Energiswapper ------------------------------------------------------------------

// Fastpris X mot flytende pris med oppgjør ved tidspunktene T_i. Forventet flytende pris
// ved T_i er forwardprisen F_i, så verdien for den som betaler fastpris er
//   V = Σ Q (F_i − X) e^{−r_i T_i},
// og swapprisen (fastprisen som gir V = 0) er Σ F_i e^{−r_i T_i} / Σ e^{−r_i T_i}.
export function energySwap({ times, forwards, rates, X, Q = 1 }) {
  const n = times.length;
  if (n === 0) throw new Error('Oppgi minst ett oppgjørstidspunkt.');
  if (forwards.length !== n) throw new Error('Det må være like mange forwardpriser som oppgjørstidspunkter.');
  if (rates.length !== 1 && rates.length !== n) {
    throw new Error('Oppgi én flat rente eller én rente per oppgjørstidspunkt.');
  }
  let annuity = 0;
  let pvFloat = 0;
  for (let i = 0; i < n; i++) {
    if (!(times[i] >= 0)) throw new Error('Oppgjørstidspunktene kan ikke være negative.');
    const r = rates.length === 1 ? rates[0] : rates[i];
    const df = Math.exp(-r * times[i]);
    annuity += Q * df;
    pvFloat += Q * forwards[i] * df;
  }
  return {
    value: pvFloat - X * annuity,
    swapPrice: pvFloat / annuity,
    annuity,
    pvFloat,
    pvFixed: X * annuity,
  };
}

// Europeisk energiswapsjon: retten til å gå inn i en swap med fastpris X ved tid T.
// Swapprisen F antas lognormal (Black-76). Swappen har n oppgjør, j per år, det første
// 1/j år etter T. Annuiteten er A = Σ_{i=1..n} Q e^{−r(T + i/j)}, og
//   payer = A [F N(d1) − X N(d2)],  receiver = A [X N(−d2) − F N(−d1)].
export function energySwaption({ type = 'call', F, X, T, n, j, r, v, Q = 1 }) {
  if (!(n >= 1)) throw new Error('Swappen må ha minst ett oppgjør.');
  if (!(j > 0)) throw new Error('Antall oppgjør per år må være positivt.');
  let annuity = 0;
  for (let i = 1; i <= n; i++) annuity += Q * Math.exp(-r * (T + i / j));
  const undiscounted = black76({ type, F, X, T, r: 0, v });
  return { price: annuity * undiscounted, annuity, forwardValue: annuity * (F - X) };
}

// --- Miltersen og Schwartz (1998) -----------------------------------------------------
//
// Futuresprisen F(t, T2) er lognormal under Q med volatilitetsvektor
//   σ_S e_S + a_f(u) e_f − a_E(u) e_E,   a_f(u) = σ_f g(κ_f, T2 − u),  a_E(u) = σ_E g(κ_E, T2 − u),
// der forwardrentene og forward convenience yield har volatilitet σ e^{−κ(s−u)}.
// Under T-forwardmålet får futuresprisen driften −σ_xz, og
//   c = P(0,T) [F e^{−σ_xz} N(d1) − X N(d2)],  d1 = [ln(F/X) − σ_xz + σ_z²/2]/σ_z,  d2 = d1 − σ_z.

// Lukkede uttrykk for σ_z² og σ_xz (som i Haug). t = opsjonens løpetid, Tf = futuresforfall.
export function miltersenSchwartzMomentsClosed({ T: t, T2: Tf, vS, vE, vf, rhoSE, rhoSf, rhoEf, kE, kf }) {
  const tau = Tf - t;
  // E1(κ) = e^{−κTf}(e^{κt} − 1), E2(κ) = e^{−2κTf}(e^{2κt} − 1), skrevet uten overflyt.
  const E1 = (k) => Math.exp(-k * tau) * -Math.expm1(-k * t);
  const E2 = (k) => Math.exp(-2 * k * tau) * -Math.expm1(-2 * k * t);
  const I1 = (k) => t - E1(k) / k;
  const I2 = (k) => t - 2 * E1(k) / k + E2(k) / (2 * k);
  let varZ = vS * vS * t;
  let sxz = 0;
  if (vE !== 0) {
    varZ += -2 * vS * (vE / kE) * rhoSE * I1(kE) + (vE / kE) ** 2 * I2(kE);
  }
  if (vf !== 0) {
    varZ += 2 * vS * (vf / kf) * rhoSf * I1(kf) + (vf / kf) ** 2 * I2(kf);
    const J1 = t + Math.expm1(-kf * t) / kf;
    const J2 = J1 - E1(kf) / kf + Math.exp(-kf * tau) * -Math.expm1(-2 * kf * t) / (2 * kf);
    sxz = (vf / kf) * (rhoSf * vS * J1 + (vf / kf) * J2);
    if (vE !== 0) {
      const ks = kE + kf;
      const I12 = t - E1(kE) / kE - E1(kf) / kf + Math.exp(-ks * tau) * -Math.expm1(-ks * t) / ks;
      varZ += -2 * rhoEf * (vE / kE) * (vf / kf) * I12;
      const J3 = J1 - E1(kE) / kE + Math.exp(-kE * tau) * -Math.expm1(-ks * t) / ks;
      sxz -= (vf / kf) * rhoEf * (vE / kE) * J3;
    }
  }
  return { varZ, sxz };
}

// Samme størrelser ved numerisk integrasjon av definisjonene (brukes når κ er svært liten).
export function miltersenSchwartzMomentsQuad({ T: t, T2: Tf, vS, vE, vf, rhoSE, rhoSf, rhoEf, kE, kf }) {
  const panels = Math.min(400, Math.max(4, Math.ceil(Math.max(kE, kf, 0) * Tf / 2)));
  const varZ = gaussLegendreComposite((u) => {
    const af = vf * decay(kf, Tf - u);
    const aE = vE * decay(kE, Tf - u);
    return vS * vS + af * af + aE * aE + 2 * rhoSf * vS * af - 2 * rhoSE * vS * aE - 2 * rhoEf * af * aE;
  }, 0, t, panels, 16);
  const sxz = gaussLegendreComposite((u) => {
    const bf = vf * decay(kf, t - u);
    const af = vf * decay(kf, Tf - u);
    const aE = vE * decay(kE, Tf - u);
    return bf * (rhoSf * vS + af - rhoEf * aE);
  }, 0, t, panels, 16);
  return { varZ, sxz };
}

export function miltersenSchwartzMoments(p) {
  const small = (vol, k) => vol !== 0 && !(k * p.T2 >= SMALL);
  if (small(p.vE, p.kE) || small(p.vf, p.kf)) return miltersenSchwartzMomentsQuad(p);
  return miltersenSchwartzMomentsClosed(p);
}

export function miltersenSchwartz(p) {
  const { type = 'call', F, X, T, T2, r } = p;
  if (!(T2 >= T)) throw new Error('Futureskontrakten kan ikke forfalle før opsjonen (krever T2 ≥ T).');
  for (const key of ['rhoSE', 'rhoSf', 'rhoEf']) {
    if (!(Math.abs(p[key]) <= 1)) throw new Error('Korrelasjonene må ligge mellom −1 og 1.');
  }
  const { varZ, sxz } = miltersenSchwartzMoments(p);
  if (!(varZ >= 0)) throw new Error('Korrelasjonene gir negativ varians; de er ikke en gyldig korrelasjonsmatrise.');
  const vz = Math.sqrt(varZ);
  const Fadj = F * Math.exp(-sxz);
  const price = black76({ type, F: Fadj, X, T, r, v: vz / Math.sqrt(T) });
  const d1 = (Math.log(F / X) - sxz + varZ / 2) / vz;
  return { price, vz, sxz, d1, d2: d1 - vz, Pt: Math.exp(-r * T), Fadj };
}

// --- Schwartz (1997) én-faktor --------------------------------------------------------
//
// Under Q: d ln S = κ(α* − ln S) dt + σ dz. Futuresprisen er
//   F(S, τ) = exp[e^{−κτ} ln S + (1 − e^{−κτ}) α* + σ²(1 − e^{−2κτ})/(4κ)],
// og ln F(t, T2) har volatilitet σ e^{−κ(T2 − t)}, så en europeisk opsjon på futures er
// Black-76 med varians σ² e^{−2κ(T2−T)} (1 − e^{−2κT})/(2κ). T2 = T gir opsjon på spot.
export function schwartz1fFutures({ S, tau, kappa, alpha, v }) {
  const e = Math.exp(-kappa * tau);
  return Math.exp(e * Math.log(S) - Math.expm1(-kappa * tau) * alpha + 0.5 * v * v * decay(2 * kappa, tau));
}

export function schwartz1fOption({ type = 'call', S, X, T, T2, r, kappa, alpha, v }) {
  if (!(T2 >= T)) throw new Error('Futureskontrakten kan ikke forfalle før opsjonen (krever T2 ≥ T).');
  const F = schwartz1fFutures({ S, tau: T2, kappa, alpha, v });
  const variance = v * v * Math.exp(-2 * kappa * (T2 - T)) * decay(2 * kappa, T);
  const veff = Math.sqrt(variance / T);
  return { price: black76({ type, F, X, T, r, v: veff }), F, veff, spotForward: schwartz1fFutures({ S, tau: T, kappa, alpha, v }) };
}

// --- Gibson og Schwartz (1990) / Schwartz (1997) to-faktor ----------------------------
//
// Under Q: dS/S = (r − δ) dt + σ1 dz1,  dδ = κ(α̂ − δ) dt + σ2 dz2,  dz1 dz2 = ρ dt,
// der α̂ = α − λ/κ er det risikojusterte langsiktige nivået for convenience yield. Futuresprisen:
//   ln F = ln S − δ (1 − e^{−κτ})/κ + A(τ),
//   A(τ) = (r − α̂ + σ2²/(2κ²) − ρσ1σ2/κ) τ + σ2²(1 − e^{−2κτ})/(4κ³)
//          + (α̂κ + ρσ1σ2 − σ2²/κ)(1 − e^{−κτ})/κ²  (her skrevet numerisk stabilt).
export function schwartz2fFutures({ S, delta, tau, r, kappa, alpha, v1, v2, rho }) {
  return Math.exp(Math.log(S) + (r - alpha) * tau - (delta - alpha) * decay(kappa, tau) +
    0.5 * v2 * v2 * decaySqInt(kappa, tau) - rho * v1 * v2 * decayInt(kappa, tau));
}

// Varians i ln F(·, T2) fra 0 til T (futuresvolatiliteten er σ1 e1 − σ2 g(κ, T2 − u) e2).
export function schwartz2fVariance({ T, T2, kappa, v1, v2, rho }) {
  return v1 * v1 * T -
    2 * rho * v1 * v2 * (decayInt(kappa, T2) - decayInt(kappa, T2 - T)) +
    v2 * v2 * (decaySqInt(kappa, T2) - decaySqInt(kappa, T2 - T));
}

export function schwartz2fOption({ type = 'call', S, X, T, T2, r, delta, kappa, alpha, v1, v2, rho }) {
  if (!(T2 >= T)) throw new Error('Futureskontrakten kan ikke forfalle før opsjonen (krever T2 ≥ T).');
  if (!(Math.abs(rho) <= 1)) throw new Error('Korrelasjonen må ligge mellom −1 og 1.');
  const F = schwartz2fFutures({ S, delta, tau: T2, r, kappa, alpha, v1, v2, rho });
  const variance = schwartz2fVariance({ T, T2, kappa, v1, v2, rho });
  const veff = Math.sqrt(Math.max(variance, 0) / T);
  return { price: black76({ type, F, X, T, r, v: veff }), F, veff };
}
