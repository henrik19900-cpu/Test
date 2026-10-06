// Kapittel 9: Opsjoner på aksjer med diskrete (kontante) utbytter.
//
//   dividendSchedule       validerer og sorterer utbytter (tidspunkt i år, beløp)
//   escrowedDividend       S erstattes av S minus nåverdien av utbyttene (escrowed dividend-modellen)
//   simpleVolAdjustment    σ·S / (S − PV(D)) på hele løpetiden
//   haugHaugVol            tidsvektet volatilitetsjustering (Haug og Haug)
//   bgsVol                 Bos, Gairat og Shepeleva (2003)
//   bosVandermark          Bos og Vandermark (2002): justering av spot og innløsningskurs
//   hhlEuropean            Haug, Haug og Lewis (2003): eksakt europeisk pris ved numerisk integrasjon
//   hhlAmericanCall        HHL for amerikansk call (innløsning bare rett før utbyttedatoer)
//   rollGeskeWhaley        Roll (1977), Geske (1979, 1981), Whaley (1981): amerikansk call, ett utbytte
//   blackPseudoAmerican    Black (1975)
//   dividendTree           binomialtre (CRR) med diskrete utbytter, faktisk eller escrowed modell
//
// I den «faktiske» modellen følger aksjen en geometrisk brownsk bevegelse med volatilitet σ mellom
// utbyttene og faller med utbyttet D på utbyttedatoen (hvis kursen er lavere enn D, faller den til 0).
// I escrowed-modellen er det S minus nåverdien av gjenværende utbytter som er lognormal.
// Aksjen har ellers ingen løpende utbytteavkastning, så b = r.

import { cnd, cbnd } from '../math/normal.js';
import { brent } from '../math/solvers.js';
import { gaussLegendreNodes } from '../math/integrate.js';
import { gbsm, isCall } from './bsm.js';
import { isAmerican } from './lattice.js';

// ---------------------------------------------------------------------------
// Utbytteplan
// ---------------------------------------------------------------------------

// Returnerer [{ t, D }] sortert etter tid, kun utbytter med 0 < t < T og D > 0.
// Utbytter på samme dato slås sammen. Utbytter på eller etter forfall påvirker ikke opsjonen.
export function dividendSchedule({ tD = [], D = [], T }) {
  if (!Array.isArray(tD) || !Array.isArray(D)) throw new Error('Utbyttene må oppgis som tallrekker.');
  if (tD.length !== D.length) throw new Error('Det må være like mange utbyttetidspunkter som utbyttebeløp.');
  const list = [];
  for (let i = 0; i < tD.length; i++) {
    const t = tD[i];
    const d = D[i];
    if (!Number.isFinite(t) || !Number.isFinite(d)) throw new Error('Utbyttetidspunkter og -beløp må være tall.');
    if (!(t > 0)) throw new Error('Utbyttetidspunktene må være etter i dag (t > 0).');
    if (d < 0) throw new Error('Utbyttebeløpene kan ikke være negative.');
    if (t < T && d > 0) list.push({ t, D: d });
  }
  list.sort((a, b) => a.t - b.t);
  const merged = [];
  for (const x of list) {
    const last = merged[merged.length - 1];
    if (last && Math.abs(last.t - x.t) < 1e-12) last.D += x.D;
    else merged.push({ ...x });
  }
  return merged;
}

// Nåverdi på tidspunkt `at` av utbytter betalt etter `at` (og før `until`).
export function pvDividends(divs, r, at = 0, until = Infinity) {
  let s = 0;
  for (const { t, D } of divs) if (t > at && t < until) s += D * Math.exp(-r * (t - at));
  return s;
}

function checkCommon({ S, X, T, v }) {
  if (!(S > 0) || !(X > 0)) throw new Error('Spot og innløsningskurs må være positive.');
  if (!(T > 0)) throw new Error('Tid til forfall må være positiv.');
  if (!(v > 0)) throw new Error('Volatiliteten må være positiv.');
}

function adjustedSpot(S, divs, r) {
  const pv = pvDividends(divs, r);
  const Sadj = S - pv;
  if (!(Sadj > 0)) throw new Error('Nåverdien av utbyttene er større enn aksjekursen.');
  return { Sadj, pv };
}

// ---------------------------------------------------------------------------
// Escrowed dividend-modellen og volatilitetsjusteringer
// ---------------------------------------------------------------------------

export function escrowedDividend({ type = 'call', S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  const { Sadj, pv } = adjustedSpot(S, divs, r);
  return { price: gbsm({ type, S: Sadj, X, T, r, b: r, v }), Sadj, pv, vAdj: v };
}

// Enkel justering: σ_adj = σ S / (S − PV(D)).
export function simpleVolAdjustment({ type = 'call', S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  const { Sadj, pv } = adjustedSpot(S, divs, r);
  const vAdj = v * S / Sadj;
  return { price: gbsm({ type, S: Sadj, X, T, r, b: r, v: vAdj }), Sadj, pv, vAdj };
}

// Haug og Haug: volatiliteten justeres bare for perioden før hvert utbytte,
// σ_adj² T = Σ_k σ_k² (t_{k+1} − t_k), σ_k = σ S / (S − PV av utbytter etter t_k).
export function haugHaugVol({ type = 'call', S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  const { Sadj, pv } = adjustedSpot(S, divs, r);
  let variance = 0;
  let prev = 0;
  for (let k = 0; k <= divs.length; k++) {
    const end = k < divs.length ? divs[k].t : T;
    // Nåverdi i dag av utbyttene som ennå ikke er betalt i perioden (prev, end]: nr. k og senere.
    let remaining = 0;
    for (let j = k; j < divs.length; j++) remaining += divs[j].D * Math.exp(-r * divs[j].t);
    const sk = v * S / (S - remaining);
    variance += sk * sk * (end - prev);
    prev = end;
  }
  const vAdj = Math.sqrt(variance / T);
  return { price: gbsm({ type, S: Sadj, X, T, r, b: r, v: vAdj }), Sadj, pv, vAdj };
}

// Bos, Gairat og Shepeleva (2003): volatilitetsjustering brukt sammen med S − PV(D).
// Justeringen er gjennomsnittet av den lokale variansen σ²(1 + PV_t/S*_t)² til escrowed-prosessen
// under en brownsk bro fra S* = S − PV(D) til X. Derfor er s = ln(S − PV(D)) og x = ln(X e^{−rT}).
export function bgsVol({ type = 'call', S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  const { Sadj, pv } = adjustedSpot(S, divs, r);
  const sqT = Math.sqrt(T);
  const s = Math.log(Sadj);
  const x = Math.log(X * Math.exp(-r * T));
  const z1 = (s - x) / (v * sqT) + v * sqT / 2;
  const z2 = (s - x) / (v * sqT) + v * sqT;
  let sum1 = 0;
  let sum2 = 0;
  for (const di of divs) {
    const pvi = di.D * Math.exp(-r * di.t);
    sum1 += pvi * (cnd(z1) - cnd(z1 - v * di.t / sqT));
    for (const dj of divs) {
      const pvj = dj.D * Math.exp(-r * dj.t);
      sum2 += pvi * pvj * (cnd(z2) - cnd(z2 - 2 * v * Math.min(di.t, dj.t) / sqT));
    }
  }
  const adj = v * Math.sqrt(Math.PI / (2 * T)) * (
    4 * Math.exp(z1 * z1 / 2 - s) * sum1 + Math.exp(z2 * z2 / 2 - 2 * s) * sum2);
  const v2 = v * v + adj;
  if (!(v2 > 0)) throw new Error('Den justerte variansen ble negativ.');
  const vAdj = Math.sqrt(v2);
  return { price: gbsm({ type, S: Sadj, X, T, r, b: r, v: vAdj }), Sadj, pv, vAdj };
}

// Bos og Vandermark (2002): utbyttene deles i en «nær» del som trekkes fra spot og en «fjern»
// del som legges til innløsningskursen: X_n = Σ (T − t_i)/T D_i e^{−r t_i}, X_f = Σ t_i/T D_i e^{−r t_i}.
export function bosVandermark({ type = 'call', S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  let Xn = 0;
  let Xf = 0;
  for (const { t, D } of divs) {
    const pvi = D * Math.exp(-r * t);
    Xn += (T - t) / T * pvi;
    Xf += t / T * pvi;
  }
  const Sadj = S - Xn;
  if (!(Sadj > 0)) throw new Error('Den justerte spotprisen ble negativ.');
  const Xadj = X + Xf * Math.exp(r * T);
  return { price: gbsm({ type, S: Sadj, X: Xadj, T, r, b: r, v }), Sadj, Xadj, Xn, Xf };
}

// ---------------------------------------------------------------------------
// Haug, Haug og Lewis (2003): rekursiv numerisk integrasjon over utbyttedatoene
// ---------------------------------------------------------------------------

// Naturlig kubisk spline på et jevnt gitter i y.
function makeSpline(y0, h, f) {
  const n = f.length;
  const M = new Float64Array(n);
  if (n > 2) {
    const cp = new Float64Array(n);
    const dp = new Float64Array(n);
    for (let i = 1; i < n - 1; i++) {
      const rhs = 6 * (f[i + 1] - 2 * f[i] + f[i - 1]) / (h * h);
      const m = 4 - (i > 1 ? cp[i - 1] : 0);
      cp[i] = 1 / m;
      dp[i] = (rhs - (i > 1 ? dp[i - 1] : 0)) / m;
    }
    for (let i = n - 2; i >= 1; i--) M[i] = dp[i] - cp[i] * M[i + 1];
  }
  return (y) => {
    let k = Math.floor((y - y0) / h);
    if (k < 0) k = 0;
    if (k > n - 2) k = n - 2;
    const a = y0 + (k + 1) * h - y;
    const b = y - (y0 + k * h);
    return (M[k] * a * a * a + M[k + 1] * b * b * b) / (6 * h) +
      (f[k] / h - M[k] * h / 6) * a + (f[k + 1] / h - M[k + 1] * h / 6) * b;
  };
}

const Z_MAX = 8.5;
const GL = gaussLegendreNodes(12);

// ∫ g(z) φ(z) dz over [−Z_MAX, Z_MAX], delt opp i paneler og ved knekkpunktene `cuts` (i z).
function normalIntegral(g, cuts) {
  const pts = [-Z_MAX, Z_MAX];
  for (const c of cuts) if (c > -Z_MAX && c < Z_MAX) pts.push(c);
  pts.sort((a, b) => a - b);
  let total = 0;
  for (let k = 0; k < pts.length - 1; k++) {
    const a = pts[k];
    const b = pts[k + 1];
    const panels = Math.max(1, Math.ceil((b - a) / 1.5));
    const w = (b - a) / panels;
    for (let p = 0; p < panels; p++) {
      const lo = a + p * w;
      const mid = lo + w / 2;
      for (let i = 0; i < GL.x.length; i++) {
        const z = mid + 0.5 * w * GL.x[i];
        total += 0.5 * w * GL.w[i] * g(z) * Math.exp(-0.5 * z * z);
      }
    }
  }
  return total / Math.sqrt(2 * Math.PI);
}

// Knekkpunkter for kvadraturen. Hver «egenskap» er et sted (kurs) der integranden har en knekk
// (scale = 0) eller en utglattet knekk med bredde `scale` i ln S. Smale egenskaper får tette paneler.
const CLUSTER = [-8, -4, -2, -1, 0, 1, 2, 4, 8];
function cutsFor(features, drift, sd) {
  const cuts = [];
  for (const f of features) {
    if (!(f.at > 0)) continue;
    const zc = (Math.log(f.at) - drift) / sd;
    if (f.scale === 0) {
      cuts.push(zc);
      continue;
    }
    const w = f.scale / sd;
    if (w >= 1.2 || zc < -Z_MAX - 8 * w || zc > Z_MAX + 8 * w) continue;
    for (const c of CLUSTER) cuts.push(zc + c * w);
  }
  return cuts;
}

// Felles motor. american = true gir amerikansk call (innløsning rett før hvert utbytte).
// Verdifunksjonen rett etter hvert utbytte lagres på et gitter i ln S (kubisk spline), og
// forventningen over neste periode regnes med Gauss-Legendre. Returnerer pris og de kritiske
// aksjekursene (cum utbytte) for tidlig innløsning.
function hhlEngine({ type, S, X, T, r, v, divs, american }) {
  const call = isCall(type);
  const n = divs.length;
  const mu = r - 0.5 * v * v;
  const zeroValue = (tau) => (call ? 0 : X * Math.exp(-r * tau));
  const tauLast = T - divs[n - 1].t;
  // Verdien rett etter siste utbytte er analytisk (GBSM); knekken i utbetalingen er glattet ut.
  let exValue = (s) => (s > 0 ? gbsm({ type, S: s, X, T: tauLast, r, b: r, v }) : zeroValue(tauLast));
  let exFeatures = [{ at: X * Math.exp(-mu * tauLast), scale: v * Math.sqrt(tauLast) }];
  const critical = new Array(n).fill(Infinity);

  for (let k = n - 1; k >= 0; k--) {
    const { D, t } = divs[k];
    const tau = T - t;
    const ex = exValue;
    // Kritisk kurs (cum) for amerikansk call: S − X = verdien av å beholde opsjonen.
    let crit = Infinity;
    if (american && call) {
      const f = (s) => s - X - (s > D ? ex(s - D) : zeroValue(tau));
      if (f(X) >= 0) {
        crit = X;
      } else {
        let hi = Math.max(2 * X, 2 * D);
        for (let i = 0; i < 80 && f(hi) <= 0; i++) hi *= 1.5;
        if (f(hi) > 0) crit = brent(f, X, hi, { tol: 1e-10 * X });
      }
    }
    critical[k] = crit;
    const cum = (s) => {
      const cont = s > D ? ex(s - D) : zeroValue(tau);
      return s >= crit ? Math.max(s - X, cont) : cont;
    };
    const cumFeatures = exFeatures.map((f) => ({ at: f.at + D, scale: f.scale * f.at / (f.at + D) }));
    cumFeatures.push({ at: D, scale: 0 });
    if (Number.isFinite(crit)) cumFeatures.push({ at: crit, scale: 0 });

    const t0 = k > 0 ? divs[k - 1].t : 0;
    const dt = t - t0;
    const sd = v * Math.sqrt(dt);
    const df = Math.exp(-r * dt);
    const expect = (s0) => {
      const drift = Math.log(s0) + mu * dt;
      return df * normalIntegral((z) => cum(Math.exp(drift + sd * z)), cutsFor(cumFeatures, drift, sd));
    };
    if (k === 0) {
      let price = expect(S);
      if (american && call) price = Math.max(price, S - X);
      return { price, critical };
    }

    // Gitter for kursen rett etter utbytte k−1, sentrert om terminkursen eks utbytte.
    const sdk = v * Math.sqrt(t0);
    const paid = divs.slice(0, k).reduce((acc, d) => acc + d.D * Math.exp(r * (t0 - d.t)), 0);
    const hiS = S * Math.exp(mu * t0 + 9 * sdk) - paid;
    const v0 = zeroValue(T - t0);
    if (!(hiS > 0)) {
      // Aksjen er så godt som sikkert likvidert; verdien er konstant.
      exValue = () => v0;
      exFeatures = [];
      continue;
    }
    const loS = Math.max(S * Math.exp(mu * t0 - 9 * sdk) - paid, hiS * 1e-4);
    exFeatures = cumFeatures.map((f) => ({ at: f.at * Math.exp(-mu * dt), scale: Math.hypot(f.scale, sd) }));
    // Gitteravstanden må løse opp den smaleste egenskapen innenfor gitteret.
    let minScale = Infinity;
    for (const f of exFeatures) if (f.at > loS && f.at < hiS) minScale = Math.min(minScale, f.scale);
    const y0 = Math.log(loS);
    const range = Math.log(hiS) - y0;
    const size = Math.min(4001, Math.max(241, Math.ceil(range / (minScale / 5)) + 1));
    const h = range / (size - 1);
    const vals = new Float64Array(size);
    for (let i = 0; i < size; i++) vals[i] = expect(Math.exp(y0 + i * h));
    const spline = makeSpline(y0, h, vals);
    const sHi = Math.exp(y0 + (size - 1) * h);
    const slopeHi = (vals[size - 1] - vals[size - 2]) / (sHi - Math.exp(y0 + (size - 2) * h));
    exValue = (s) => {
      if (!(s > 0)) return v0;
      if (s < loS) return v0 + (vals[0] - v0) * s / loS;
      if (s > sHi) return vals[size - 1] + slopeHi * (s - sHi);
      return spline(Math.log(s));
    };
  }
  throw new Error('Intern feil i HHL-rekursjonen.');
}

export function hhlEuropean({ type = 'call', S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  if (divs.length === 0) return { price: gbsm({ type, S, X, T, r, b: r, v }), critical: [] };
  return hhlEngine({ type, S, X, T, r, v, divs, american: false });
}

// Amerikansk call: uten løpende utbytte lønner det seg bare å innløse rett før en utbyttedato,
// så rekursjonen over utbyttedatoene gir eksakt verdi i den faktiske modellen.
export function hhlAmericanCall({ S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  if (r < 0) throw new Error('Metoden forutsetter ikke-negativ rente.');
  if (divs.length === 0) return { price: gbsm({ type: 'call', S, X, T, r, b: r, v }), critical: [] };
  return hhlEngine({ type: 'call', S, X, T, r, v, divs, american: true });
}

// ---------------------------------------------------------------------------
// Roll-Geske-Whaley og Black
// ---------------------------------------------------------------------------

// Amerikansk call med ett kontant utbytte D på tidspunkt t1 < T (escrowed-modellen).
export function rollGeskeWhaley({ S, X, t1, T, r, D, v }) {
  checkCommon({ S, X, T, v });
  if (!(t1 > 0)) throw new Error('Utbyttetidspunktet må være etter i dag.');
  if (D < 0) throw new Error('Utbyttet kan ikke være negativt.');
  if (t1 >= T || D === 0) {
    return { price: gbsm({ type: 'call', S, X, T, r, b: r, v }), critical: Infinity, earlyExercise: false };
  }
  const Sx = S - D * Math.exp(-r * t1);
  if (!(Sx > 0)) throw new Error('Nåverdien av utbyttet er større enn aksjekursen.');
  const tau = T - t1;
  if (D <= X * -Math.expm1(-r * tau)) {
    return { price: gbsm({ type: 'call', S: Sx, X, T, r, b: r, v }), critical: Infinity, earlyExercise: false };
  }
  if (D >= X) {
    // Innløsning rett før utbyttet er alltid optimal.
    return { price: S - X * Math.exp(-r * t1), critical: 0, earlyExercise: true };
  }
  // Kritisk kurs I (eks utbytte): c(I, X, T − t1) = I + D − X.
  const f = (I) => gbsm({ type: 'call', S: I, X, T: tau, r, b: r, v }) - I - D + X;
  let hi = 2 * X;
  for (let i = 0; i < 200 && f(hi) > 0; i++) hi *= 1.5;
  const I = brent(f, 1e-12 * X, hi, { tol: 1e-12 * X });
  const sT = v * Math.sqrt(T);
  const st1 = v * Math.sqrt(t1);
  const a1 = (Math.log(Sx / X) + (r + 0.5 * v * v) * T) / sT;
  const a2 = a1 - sT;
  const b1 = (Math.log(Sx / I) + (r + 0.5 * v * v) * t1) / st1;
  const b2 = b1 - st1;
  const rho = -Math.sqrt(t1 / T);
  const price = Sx * cnd(b1) + Sx * cbnd(a1, -b1, rho) - X * Math.exp(-r * T) * cbnd(a2, -b2, rho)
    - (X - D) * Math.exp(-r * t1) * cnd(b2);
  return { price, critical: I + D, earlyExercise: true };
}

// Black (1975): maks av europeiske call som forfaller rett før hvert utbytte og ved T,
// hver med spot minus nåverdien av utbyttene før det aktuelle forfallet.
export function blackPseudoAmerican({ S, X, T, r, v, divs }) {
  checkCommon({ S, X, T, v });
  const candidates = [];
  for (let k = 0; k < divs.length; k++) {
    const tk = divs[k].t;
    const Sk = S - pvDividends(divs, r, 0, tk);
    if (!(Sk > 0)) throw new Error('Nåverdien av utbyttene er større enn aksjekursen.');
    candidates.push({ label: k + 1, price: gbsm({ type: 'call', S: Sk, X, T: tk, r, b: r, v }) });
  }
  const { Sadj } = adjustedSpot(S, divs, r);
  const atT = gbsm({ type: 'call', S: Sadj, X, T, r, b: r, v });
  candidates.push({ label: 0, price: atT });
  let best = candidates[0];
  for (const c of candidates) if (c.price > best.price) best = c;
  return { price: best.price, europeanAtT: atT, bestDividend: best.label, candidates };
}

// ---------------------------------------------------------------------------
// Binomialtre med diskrete utbytter
// ---------------------------------------------------------------------------

// Kubisk Lagrange-interpolasjon i ln S over et jevnt logaritmisk gitter med noder
// lo·q^i, i = 0..m. Under laveste node interpoleres lineært mot verdien i S = 0.
function interpolateTree(vals, lo, logq, s, valueAtZero) {
  const m = vals.length - 1;
  if (!(s > 0)) return valueAtZero;
  if (s <= lo) return valueAtZero + (vals[0] - valueAtZero) * s / lo;
  const u = Math.log(s / lo) / logq;
  if (u >= m) {
    if (m === 0) return vals[0];
    const sTop = lo * Math.exp(m * logq);
    const sPrev = lo * Math.exp((m - 1) * logq);
    return vals[m] + (vals[m] - vals[m - 1]) / (sTop - sPrev) * (s - sTop);
  }
  if (m < 3) {
    const k = Math.min(Math.floor(u), m - 1);
    const w = u - k;
    return vals[k] * (1 - w) + vals[k + 1] * w;
  }
  let k = Math.floor(u) - 1;
  if (k < 0) k = 0;
  if (k > m - 3) k = m - 3;
  const t = u - k;
  const f0 = vals[k];
  const f1 = vals[k + 1];
  const f2 = vals[k + 2];
  const f3 = vals[k + 3];
  return f0 * (t - 1) * (t - 2) * (t - 3) / -6 + f1 * t * (t - 2) * (t - 3) / 2
    + f2 * t * (t - 1) * (t - 3) / -2 + f3 * t * (t - 1) * (t - 2) / 6;
}

// model = 'real': aksjen faller med D på utbyttedatoen (verdien hentes ved interpolasjon i
// treet, som hos Vellekoop og Nieuwenhuis 2006). Utbyttet legges på nærmeste tidssteg.
// model = 'escrowed': treet bygges for S − PV(utbytter); innløsningsverdien bruker
// S* + nåverdien av gjenværende utbytter.
export function dividendTree({ type = 'call', exercise = 'american', S, X, T, r, v, divs, n = 300, model = 'real' }) {
  checkCommon({ S, X, T, v });
  if (!Number.isInteger(n) || n < 3 || n > 5000) throw new Error('Antall tidssteg må være et heltall mellom 3 og 5000.');
  const call = isCall(type);
  const american = isAmerican(exercise);
  const z = call ? 1 : -1;
  const dt = T / n;
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp(r * dt) - d) / (u - d);
  if (!(p >= 0 && p <= 1)) throw new Error('Sannsynligheten i treet havner utenfor [0, 1]. Øk antall tidssteg.');
  const df = Math.exp(-r * dt);
  const u2 = u * u;
  const payoff = (s) => Math.max(z * (s - X), 0);

  if (model === 'escrowed') {
    const { Sadj } = adjustedSpot(S, divs, r);
    const pvAt = (j) => pvDividends(divs, r, j * dt);
    const V = new Float64Array(n + 1);
    let s = Sadj * d ** n;
    for (let i = 0; i <= n; i++) {
      V[i] = payoff(s);
      s *= u2;
    }
    for (let j = n - 1; j >= 0; j--) {
      const add = pvAt(j);
      s = Sadj * d ** j;
      for (let i = 0; i <= j; i++) {
        let val = df * (p * V[i + 1] + (1 - p) * V[i]);
        if (american) {
          const ex = payoff(s + add);
          if (ex > val) val = ex;
        }
        V[i] = val;
        s *= u2;
      }
    }
    return { price: V[0], model };
  }
  if (model !== 'real') throw new Error(`Ukjent modell: ${model}`);

  // Utbytte på tidssteg j (j ≥ 1): kursen faller med D i det steget.
  const divAt = new Map();
  for (const { t, D } of divs) {
    const j = Math.min(n, Math.max(1, Math.round(t / dt)));
    divAt.set(j, (divAt.get(j) ?? 0) + D);
  }
  const zeroValue = (j) => {
    if (call) return 0;
    return american ? X : X * Math.exp(-r * (T - j * dt));
  };
  // Gitteret utvides med K noder på hver side, slik at kursen etter et tidlig utbytte fortsatt
  // ligger innenfor nodene. Node a på steg j har kurs S·d^(j+2K)·u^(2a), a = 0..j+2K.
  const totalD = divs.reduce((acc, x) => acc + x.D, 0);
  const K = Math.min(n, Math.ceil(-Math.log(1 - Math.min(0.9, totalD / S)) / (2 * v * Math.sqrt(dt))) + 3);
  const width = n + 2 * K + 1;
  const V = new Float64Array(width);
  const C = new Float64Array(width);
  const Dn = divAt.get(n) ?? 0;
  let s = S * d ** (n + 2 * K);
  for (let a = 0; a < width; a++) {
    let val = payoff(s - Dn);
    if (american && Dn > 0) val = Math.max(val, payoff(s));
    V[a] = val;
    s *= u2;
  }
  const logq = Math.log(u2);
  for (let j = n - 1; j >= 0; j--) {
    const top = j + 2 * K;
    const lo = S * d ** top;
    s = lo;
    for (let a = 0; a <= top; a++) {
      let val = df * (p * V[a + 1] + (1 - p) * V[a]);
      if (american) {
        const ex = payoff(s);
        if (ex > val) val = ex;
      }
      C[a] = val;
      s *= u2;
    }
    const D = divAt.get(j) ?? 0;
    if (D > 0) {
      const cont = C.slice(0, top + 1);
      s = lo;
      for (let a = 0; a <= top; a++) {
        let val = interpolateTree(cont, lo, logq, s - D, zeroValue(j));
        if (american) {
          const ex = payoff(s);
          if (ex > val) val = ex;
        }
        V[a] = val;
        s *= u2;
      }
    } else {
      for (let a = 0; a <= top; a++) V[a] = C[a];
    }
  }
  return { price: V[K], model };
}
