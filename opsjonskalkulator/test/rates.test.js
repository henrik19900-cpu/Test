// Tester for kapittel 11: pengemarked, FRA, obligasjonsmatematikk, Black-76 for renteopsjoner,
// Schaefer-Schwartz, Vasicek, Jamshidian, Ho-Lee, Hull-White, Rendleman-Bartter og Black-Derman-Toy.
// Uavhengige kontroller: Monte Carlo-simulering av kortrenten, finite difference, numeriske
// deriverte, paritet (cap − floor = swap, payer − receiver = forward swap) og grensetilfeller.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';
import { gbsm } from '../src/models/bsm.js';
import * as R from '../src/models/rates.js';
import catalog from '../src/catalog/ch11-rates.js';
import { defaultParams } from '../src/catalog/params.js';
import { close, withinMC, mcTerminal } from './helpers.js';

const black = (type, F, X, T, v) => gbsm({ type, S: F, X, T, r: 0, b: 0, v });

function stats(sum, sumSq, n) {
  const mean = sum / n;
  return { mean, se: Math.sqrt(Math.max(sumSq / n - mean * mean, 0) / n) };
}

// --- Pengemarked og FRA ------------------------------------------------------------------

test('pengemarkedsrenter: kjente verdier og rundtur mellom konvensjonene', () => {
  const c = R.moneyMarketRates({ from: 'simple', rate: 0.05, days: 90, basis: 360, m: 2 });
  close(c.df, 1 / 1.0125, 1e-15);
  close(c.simple365, 0.05 * 365 / 360, 1e-14, 'samme rentebeløp med ACT/365');
  close(c.cont, Math.log(1.0125) * 365 / 90, 1e-14);
  close(c.discount, 0.05 / 1.0125, 1e-14, 'diskonteringsrente d = r/(1 + rτ)');
  close(c.annual, 1.0125 ** (365 / 90) - 1, 1e-14);
  for (const [from, rate, basis] of [
    ['simple', c.simple360, 360], ['simple', c.simple365, 365], ['discount', c.discount, 360],
    ['cont', c.cont, 360], ['comp', c.comp, 365],
  ]) {
    close(R.moneyMarketRates({ from, rate, days: 90, basis, m: 2 }).df, c.df, 1e-15, from);
  }
  close(R.moneyMarketRates({ from: 'simple', rate: 0.05, days: 90, basis: 360, m: 1 }).comp, c.annual, 1e-14);
  // m forrentninger ↔ kontinuerlig er uavhengig av periodelengden: r_c = m ln(1 + r_m/m).
  close(R.moneyMarketRates({ from: 'comp', rate: 0.08, days: 200, basis: 365, m: 4 }).cont, 4 * Math.log(1.02), 1e-14);
  assert.throws(() => R.moneyMarketRates({ from: 'discount', rate: 5, days: 90, basis: 360 }), /positiv/);
});

test('FRA: arbitrasjefri forwardrente, verdi og oppgjør', () => {
  const p = { r1: 0.05, d1: 90, r2: 0.055, d2: 270, basis: 360, X: 0.06, N: 1e6, L: 0.065 };
  const f = R.fra(p);
  close((1 + 0.05 * 0.25) * (1 + f.F * 0.5), 1 + 0.055 * 0.75, 1e-15);
  close(f.F, (1.04125 / 1.0125 - 1) / 0.5, 1e-14);
  close(f.value, 1e6 * 0.5 * (f.F - 0.06) / 1.04125, 1e-8);
  close(R.fra({ ...p, X: f.F }).value, 0, 1e-9, 'verdi null til FRA-renten');
  close(f.settlement, 1e6 * 0.005 * 0.5 / (1 + 0.065 * 0.5), 1e-8);
  // Fikseres renten til F, er oppgjøret diskontert til i dag lik verdien i dag.
  const g = R.fra({ ...p, L: f.F });
  close(g.settlement * g.df1, g.value, 1e-8);
  assert.throws(() => R.fra({ ...p, d2: 80 }), /d2 > d1/);
});

test('konveksitetsjustering: Hulls eksempel, Ho-Lee-grensen og forventet rente i Hull-White', () => {
  // Hull: futurespris 94, t1 = 8, τ = 0,25, σ = 0,012 gir justering 0,4752 % og forward 5,48 %.
  const c = R.futuresToForward({ Pf: 94, t1: 8, tau: 0.25, v: 0.012, a: 0 });
  close(c.adj, 0.5 * 0.012 ** 2 * 8 * 8.25, 1e-16);
  close(c.forwardCont, 0.054802, 1e-6);
  close(R.futuresConvexity({ t1: 8, t2: 8.25, v: 0.012, a: 1e-9 }), c.adj, 1e-10);
  // Uavhengig kontroll: futuresrenten er E^Q[R(t1,t2)], R = −ln P(t1,t2)/τ. I Hull-White er
  // ln P(t1,t2) = ln A − B r(t1). Forventet kortrente finnes ved å løse dm/dt = θ(t) − a m
  // numerisk (RK4), der θ(t) = a f + σ²(1 − e^{−2at})/(2a) tilpasser modellen til flat kurve f.
  const f0 = 0.05;
  for (const [a, v, t1, tau] of [[0.1, 0.01, 5, 0.25], [0.5, 0.015, 2, 0.5], [0, 0.012, 8, 0.25], [0.03, 0.02, 10, 1]]) {
    const theta = (t) => (a > 0 ? a * f0 + v * v * (1 - Math.exp(-2 * a * t)) / (2 * a) : v * v * t);
    const steps = 4000;
    const h = t1 / steps;
    let m = f0;
    for (let k = 0; k < steps; k++) {
      const t = k * h;
      const k1 = theta(t) - a * m;
      const k2 = theta(t + h / 2) - a * (m + h / 2 * k1);
      const k3 = theta(t + h / 2) - a * (m + h / 2 * k2);
      const k4 = theta(t + h) - a * (m + h * k3);
      m += h / 6 * (k1 + 2 * k2 + 2 * k3 + k4);
    }
    const B = a > 0 ? (1 - Math.exp(-a * tau)) / a : tau;
    const varTerm = a > 0 ? v * v * (1 - Math.exp(-2 * a * t1)) * B * B / (4 * a) : v * v * t1 * B * B / 2;
    const lnA = -f0 * tau + B * f0 - varTerm;
    const futuresRate = (-lnA + B * m) / tau;
    close(futuresRate - f0, R.futuresConvexity({ t1, t2: t1 + tau, v, a }), 1e-12, `a=${a}`);
  }
});

// --- Obligasjonsmatematikk -----------------------------------------------------------------

test('obligasjoner: pariobligasjon, nullkupong og påløpte renter', () => {
  const b = R.bondFromYield({ y: 0.08, c: 0.08, m: 1, T: 10, L: 100 });
  close(b.dirty, 100, 1e-10);
  close(b.macaulay, (1.08 / 0.08) * (1 - 1.08 ** -10), 1e-12, 'Macaulay for pariobligasjon');
  close(b.macaulay, 7.2469, 1e-4);
  close(b.modified, b.macaulay / 1.08, 1e-14);
  // Halvårlige kuponger: D = (1 + y/m)/y · [1 − (1 + y/m)^{−mT}].
  const s = R.bondFromYield({ y: 0.06, c: 0.06, m: 2, T: 7, L: 100 });
  close(s.dirty, 100, 1e-10);
  close(s.macaulay, (1.03 / 0.06) * (1 - 1.03 ** -14), 1e-12);
  // Nullkupong: Macaulay = T og konveksitet = T(T + 1/m)/(1 + y/m)².
  const z = R.bondFromYield({ y: 0.05, c: 0, m: 2, T: 6, L: 100 });
  close(z.dirty, 100 * 1.025 ** -12, 1e-12);
  close(z.macaulay, 6, 1e-12);
  close(z.convexity, 6 * 6.5 / 1.025 ** 2, 1e-12);
  // Påløpte renter: neste kupong om 0,25 år av en halvårsperiode, så halve kupongen er påløpt.
  const a = R.bondFromYield({ y: 0.07, c: 0.08, m: 2, T: 9.75, L: 100 });
  close(a.accrued, 2, 1e-12);
  close(a.clean + a.accrued, a.dirty, 1e-12);
});

test('obligasjoner: durasjon og konveksitet mot numeriske deriverte, og yield fra pris', () => {
  for (const q of [
    { y: 0.08, c: 0.08, m: 1, T: 10, L: 100 },
    { y: 0.035, c: 0.05, m: 2, T: 9.75, L: 100 },
    { y: 0.12, c: 0.02, m: 4, T: 3.1, L: 1000 },
  ]) {
    const b = R.bondFromYield(q);
    const at = (dy) => R.bondFromYield({ ...q, y: q.y + dy }).dirty;
    const h1 = 1e-6;
    const slope = (at(h1) - at(-h1)) / (2 * h1);
    close(-slope / b.dirty, b.modified, 1e-7, 'modifisert durasjon');
    const h2 = 1e-4;
    close((at(h2) - 2 * b.dirty + at(-h2)) / (h2 * h2) / b.dirty, b.convexity, 1e-4, 'konveksitet');
    close(b.dv01, -slope * 1e-4, 1e-9);
    for (const priceType of ['clean', 'dirty']) {
      const price = priceType === 'clean' ? b.clean : b.dirty;
      close(R.bondYield({ ...q, price, priceType }).y, q.y, 1e-12, `yield fra ${priceType}`);
    }
  }
  // Kurs over summen av kontantstrømmene (10 · 3 + 100 = 130) krever negativ yield;
  // ved kurs 130 er yielden nøyaktig 0.
  close(R.bondYield({ price: 130, c: 0.03, m: 1, T: 10, L: 100 }).y, 0, 1e-12);
  const neg = R.bondYield({ price: 132, c: 0.03, m: 1, T: 10, L: 100 });
  assert.ok(neg.y < 0);
  close(R.bondFromYield({ y: neg.y, c: 0.03, m: 1, T: 10, L: 100 }).clean, 132, 1e-9);
});

// --- Black-76 for renteopsjoner ---------------------------------------------------------------

test('opsjon på pengemarkedsfutures: paritet, rentesymmetri, MC og σ → 0', () => {
  const p = { F: 94.5, X: 95, T: 0.5, r: 0.05, v: 0.2 };
  const c = R.moneyMarketFuturesOption({ ...p, type: 'call' }).price;
  const pu = R.moneyMarketFuturesOption({ ...p, type: 'put' }).price;
  close(c - pu, Math.exp(-0.025) * (94.5 - 95), 1e-12, 'paritet');
  close(c, gbsm({ type: 'put', S: 5.5, X: 5, T: 0.5, r: 0.05, b: 0, v: 0.2 }), 1e-14, 'call på pris = put på rente');
  const mc = mcTerminal({ S: 5.5, T: 0.5, r: 0.05, b: 0, v: 0.2, n: 200000, seed: 3, payoff: (Rt) => Math.max(100 - Rt - 95, 0) });
  withinMC(mc, c, 4, 0, 'MC');
  close(R.moneyMarketFuturesOption({ ...p, type: 'put', v: 1e-9 }).price, Math.exp(-0.025) * 0.5, 1e-9, 'σ → 0');
  assert.throws(() => R.moneyMarketFuturesOption({ ...p, F: 101 }), /under 100/);
});

test('caplet og floorlet: MC, paritet og σ → 0', () => {
  const p = { F: 0.07, X: 0.08, T: 1, tau: 0.25, r: 0.065, v: 0.2, N: 10000 };
  const df = Math.exp(-0.065) / (1 + 0.07 * 0.25);
  const cap = R.caplet({ ...p, type: 'call' });
  const flo = R.caplet({ ...p, type: 'put' });
  close(cap - flo, 10000 * 0.25 * df * (0.07 - 0.08), 1e-10, 'caplet − floorlet');
  for (const type of ['call', 'put']) {
    const mc = mcTerminal({
      S: 0.07, T: 1, r: 0, b: 0, v: 0.2, n: 200000, seed: 17,
      payoff: (L) => 10000 * 0.25 * df * Math.max(type === 'call' ? L - 0.08 : 0.08 - L, 0),
    });
    withinMC(mc, R.caplet({ ...p, type }), 4, 0, type);
  }
  close(R.caplet({ ...p, type: 'put', v: 1e-10 }), 10000 * 0.25 * df * 0.01, 1e-9, 'σ → 0');
});

test('cap og floor: summen av caplets og cap − floor = swap', () => {
  const times = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75];
  const forwards = [0.05, 0.052, 0.054, 0.055, 0.056, 0.057, 0.058];
  const p = { times, forwards, X: 0.055, tau: 0.25, r: 0.05, v: 0.2, N: 1e6 };
  const cap = R.capFloor({ ...p, type: 'call' });
  const floor = R.capFloor({ ...p, type: 'put' });
  let sum = 0;
  let swap = 0;
  for (let i = 0; i < times.length; i++) {
    const q = { F: forwards[i], X: 0.055, T: times[i], tau: 0.25, r: 0.05, v: 0.2, N: 1e6 };
    close(cap.parts[i], R.caplet({ ...q, type: 'call' }), 1e-10);
    sum += cap.parts[i];
    swap += 1e6 * 0.25 * (forwards[i] - 0.055) * Math.exp(-0.05 * times[i]) / (1 + forwards[i] * 0.25);
  }
  close(cap.price, sum, 1e-8);
  close(cap.price - floor.price, swap, 1e-8, 'cap − floor = swap');
  close(cap.swap, swap, 1e-8);
  close(cap.otherPrice, floor.price, 1e-8);
  // Når cap-renten er lik forwardrenten for hver periode er cap = floor (ATM-forward per periode).
  const atm = R.capFloor({ ...p, times: [1], forwards: [0.055] });
  close(atm.price, atm.otherPrice, 1e-12);
  assert.throws(() => R.capFloor({ ...p, forwards: [0.05] }), /like mange/);
});

test('swapsjon: bokas eksempel, annuitet, payer − receiver og MC', () => {
  const p = { F: 0.07, X: 0.075, T: 2, t1: 4, m: 2, r: 0.06, v: 0.2, N: 100 };
  const payer = R.swaption({ ...p, type: 'call' });
  const receiver = R.swaption({ ...p, type: 'put' });
  close(payer.price, 1.7964, 1e-4, 'Haug: 2 års payer-swapsjon på 4 års swap');
  let ann = 0;
  for (let i = 1; i <= 8; i++) ann += 0.5 / 1.035 ** i;
  close(payer.annuity, ann, 1e-13);
  close(payer.price - receiver.price, 100 * ann * Math.exp(-0.12) * (0.07 - 0.075), 1e-12, 'payer − receiver');
  close(payer.forwardValue, payer.price - receiver.price, 1e-12);
  const scale = 100 * ann * Math.exp(-0.12);
  for (const type of ['call', 'put']) {
    const mc = mcTerminal({
      S: 0.07, T: 2, r: 0, b: 0, v: 0.2, n: 200000, seed: 21,
      payoff: (F) => scale * Math.max(type === 'call' ? F - 0.075 : 0.075 - F, 0),
    });
    withinMC(mc, R.swaption({ ...p, type }).price, 4, 0, type);
  }
  close(R.swaption({ ...p, type: 'put', v: 1e-10 }).price, scale * 0.005, 1e-10, 'σ → 0');
  close(R.swaptionAnnuity(0, 4, 2), 4, 1e-15);
  close(R.swaptionAnnuity(1e-9, 4, 2), 4, 1e-7);
});

test('obligasjonsopsjon med Black-76: Hulls eksempel, yield-volatilitet og paritet', () => {
  const p = { F: 939.68, X: 1000, T: 10 / 12, r: 0.1, v: 0.09 };
  // Hull (Options, Futures and Other Derivatives): 10 måneders call på 9,75 års obligasjon, pris 9,49.
  close(R.bondOptionBlack({ ...p, type: 'call' }).price, 9.49, 0.005);
  const c = R.bondOptionBlack({ ...p, type: 'call' }).price;
  const pu = R.bondOptionBlack({ ...p, type: 'put' }).price;
  close(c - pu, Math.exp(-p.r * p.T) * (p.F - p.X), 1e-10);
  // Yield-volatilitet 20 %, forward yield 8 % og modifisert durasjon 5,2 gir prisvolatilitet 8,32 %.
  const y = R.bondOptionBlack({ ...p, type: 'call', volType: 'yield', v: 0.2, y: 0.08, D: 5.2 });
  close(y.vPrice, 0.0832, 1e-15);
  close(y.price, R.bondOptionBlack({ ...p, type: 'call', v: 0.0832 }).price, 1e-12);
  close(R.bondOptionBlack({ ...p, v: 0.0832, y: 0.08, D: 5.2 }).vYield, 0.2, 1e-14);
});

// --- Schaefer og Schwartz (1987) -----------------------------------------------------------

test('Schaefer-Schwartz: finite difference mot lukket form for α = 1, paritet og T > D', () => {
  const base = { S: 100, T: 1, r: 0.05, v: 0.08, D: 5 };
  for (const X of [90, 97, 100, 104, 115]) {
    for (const type of ['call', 'put']) {
      const exact = R.schaeferSchwartzBSM({ ...base, X, type }).price;
      close(R.schaeferSchwartz({ ...base, X, type, alpha: 1 }), exact, 2e-4, `${type} X=${X}`);
    }
  }
  // T > D: volatiliteten er null etter D, og den lukkede formen gjelder fortsatt for α = 1.
  const q = { ...base, T: 3, D: 2, X: 105 };
  close(R.schaeferSchwartz({ ...q, type: 'call', alpha: 1 }), R.schaeferSchwartzBSM({ ...q, type: 'call' }).price, 2e-4);
  // Put-call-paritet for vilkårlig α.
  for (const alpha of [0, 0.5]) {
    const c = R.schaeferSchwartz({ ...base, X: 98, type: 'call', alpha });
    const p = R.schaeferSchwartz({ ...base, X: 98, type: 'put', alpha });
    close(c - p, 100 - 98 * Math.exp(-0.05), 2e-4, `paritet α=${alpha}`);
  }
  // σ → 0 gir diskontert indre verdi av forwarden.
  close(R.schaeferSchwartz({ ...base, X: 98, type: 'call', alpha: 0.5, v: 1e-12 }), 100 - 98 * Math.exp(-0.05), 1e-10);
});

test('Schaefer-Schwartz: α = 0 og α = 0,5 mot Monte Carlo', () => {
  const p = { S: 100, X: 85, T: 2, r: 0.04, v: 0.15, D: 6 };
  const steps = 100;
  const dt = p.T / steps;
  const sq = Math.sqrt(dt);
  const df = Math.exp(-p.r * p.T);
  const bsm = R.schaeferSchwartzBSM({ ...p, type: 'put' }).price;
  for (const alpha of [0, 0.5]) {
    const K = p.v * p.S ** (1 - alpha) / p.D;
    const rng = createRng(9 + alpha * 10);
    const pairs = 30000;
    const z = new Float64Array(steps);
    let s = 0;
    let s2 = 0;
    for (let i = 0; i < pairs; i++) {
      for (let k = 0; k < steps; k++) z[k] = rng.normal();
      let pay = 0;
      for (const sgn of [1, -1]) {
        let lnB = Math.log(p.S);
        for (let k = 0; k < steps; k++) {
          const sig = K * Math.exp((alpha - 1) * lnB) * Math.max(p.D - (k + 0.5) * dt, 0);
          lnB += (p.r - 0.5 * sig * sig) * dt + sig * sq * sgn * z[k];
        }
        pay += 0.5 * df * Math.max(p.X - Math.exp(lnB), 0);
      }
      s += pay;
      s2 += pay * pay;
    }
    const est = stats(s, s2, pairs);
    const fd = R.schaeferSchwartz({ ...p, type: 'put', alpha });
    withinMC(est, fd, 4, 0.002, `put α=${alpha}`);
    // Volatilitetsskjevheten (α < 1) må gi en tydelig forskjell fra lognormal modell.
    assert.ok(fd - bsm > 8 * est.se, `α=${alpha}: ${fd} mot BSM ${bsm}`);
  }
});

// --- Vasicek, Jamshidian, Ho-Lee og Hull-White ------------------------------------------------

// Simulerer kortrenten med eksakte Ornstein-Uhlenbeck-steg, dr = (θ(t) − κ r) dt + σ dz, der
// θ(t) er gitt som funksjon (konstant κθ i Vasicek). ∫r dt tas med trapesregelen.
// onExpiry(r_T, ∫_0^T r) returnerer den udiskonterte utbetalingen, som så diskonteres.
function simulateShortRate({ r0, kappa, theta, v, T, steps, pairs, seed, payoff }) {
  const rng = createRng(seed);
  const dt = T / steps;
  const e = Math.exp(-kappa * dt);
  const sd = v * Math.sqrt(kappa > 0 ? (1 - Math.exp(-2 * kappa * dt)) / (2 * kappa) : dt);
  const z = new Float64Array(steps);
  const n = payoff.length;
  const sums = Array.from({ length: n }, () => [0, 0]);
  for (let i = 0; i < pairs; i++) {
    for (let k = 0; k < steps; k++) z[k] = rng.normal();
    const y = new Float64Array(n);
    for (const sgn of [1, -1]) {
      let r = r0;
      let I = 0;
      for (let k = 0; k < steps; k++) {
        // Middelverdien av θ over steget (θ varierer langsomt).
        const th = theta((k + 0.5) * dt);
        const mean = kappa > 0 ? r * e + th * (1 - e) / kappa : r + th * dt;
        const rn = mean + sd * sgn * z[k];
        I += 0.5 * (r + rn) * dt;
        r = rn;
      }
      for (let j = 0; j < n; j++) y[j] += 0.5 * Math.exp(-I) * payoff[j](r);
    }
    for (let j = 0; j < n; j++) {
      sums[j][0] += y[j];
      sums[j][1] += y[j] * y[j];
    }
  }
  return sums.map(([a, b]) => stats(a, b, pairs));
}

test('Vasicek: nullkupongpris mot Haugs A·e^{−Br}, κ → 0 og Monte Carlo', () => {
  for (const q of [
    { r: 0.05, kappa: 0.2, theta: 0.06, v: 0.02, T: 5 },
    { r: 0.08, kappa: 1.5, theta: 0.04, v: 0.03, T: 12 },
    { r: 0.01, kappa: 0.05, theta: 0.07, v: 0.01, T: 0.5 },
  ]) {
    const { r, kappa: k, theta, v, T } = q;
    const B = (1 - Math.exp(-k * T)) / k;
    const A = Math.exp((B - T) * (k * k * theta - v * v / 2) / (k * k) - v * v * B * B / (4 * k));
    close(R.vasicekBond(q).P / (A * Math.exp(-B * r)), 1, 1e-13, JSON.stringify(q));
  }
  // κ → 0: dr = σ dz, P = exp(−rT + σ²T³/6).
  close(R.vasicekBond({ r: 0.05, kappa: 0, theta: 0.06, v: 0.02, T: 5 }).P, Math.exp(-0.25 + 0.0004 * 125 / 6), 1e-14);
  close(R.vasicekBond({ r: 0.05, kappa: 1e-7, theta: 0.06, v: 0.02, T: 5 }).P,
    R.vasicekBond({ r: 0.05, kappa: 0, theta: 0.06, v: 0.02, T: 5 }).P, 1e-7);
  // MC: E[e^{−∫r}] med eksakt simulering av kortrenten.
  const q = { r: 0.05, kappa: 0.3, theta: 0.07, v: 0.03, T: 4 };
  const [est] = simulateShortRate({
    r0: q.r, kappa: q.kappa, theta: () => q.kappa * q.theta, v: q.v, T: q.T, steps: 100, pairs: 20000, seed: 31,
    payoff: [() => 1],
  });
  withinMC(est, R.vasicekBond(q).P, 4, 2e-6, 'P(0,T)');
});

test('Vasicek: opsjon på nullkupongobligasjon mot MC, paritet og σ → 0', () => {
  const p = { L: 100, X: 88, T: 1.5, s: 4, r: 0.05, kappa: 0.25, theta: 0.06, v: 0.025 };
  const bondAtT = (rT) => p.L * R.vasicekBond({ r: rT, kappa: p.kappa, theta: p.theta, v: p.v, T: p.s - p.T }).P;
  const [c, pu] = simulateShortRate({
    r0: p.r, kappa: p.kappa, theta: () => p.kappa * p.theta, v: p.v, T: p.T, steps: 100, pairs: 40000, seed: 41,
    payoff: [(rT) => Math.max(bondAtT(rT) - p.X, 0), (rT) => Math.max(p.X - bondAtT(rT), 0)],
  });
  const call = R.vasicekOption({ ...p, type: 'call' });
  const put = R.vasicekOption({ ...p, type: 'put' });
  withinMC(c, call.price, 4, 2e-4, 'call');
  withinMC(pu, put.price, 4, 2e-4, 'put');
  close(call.price - put.price, p.L * call.P0s - p.X * call.P0T, 1e-12, 'paritet');
  const d = R.vasicekOption({ ...p, type: 'call', v: 1e-12 });
  close(d.price, Math.max(p.L * d.P0s - p.X * d.P0T, 0), 1e-9, 'σ → 0');
});

test('Jamshidian: opsjon på kupongobligasjon mot MC, nullkupong-spesialtilfellet og paritet', () => {
  const p = { L: 100, c: 0.06, m: 2, s: 5, X: 100, T: 1, r: 0.05, kappa: 0.2, theta: 0.06, v: 0.02 };
  const { times, amounts } = R.bondCashflows({ c: p.c, m: p.m, T: p.s, L: p.L });
  const bondAtT = (rT) => times.reduce((acc, t, i) => (t > p.T ? acc + amounts[i] *
    R.vasicekBond({ r: rT, kappa: p.kappa, theta: p.theta, v: p.v, T: t - p.T }).P : acc), 0);
  const [c, pu] = simulateShortRate({
    r0: p.r, kappa: p.kappa, theta: () => p.kappa * p.theta, v: p.v, T: p.T, steps: 100, pairs: 40000, seed: 51,
    payoff: [(rT) => Math.max(bondAtT(rT) - p.X, 0), (rT) => Math.max(p.X - bondAtT(rT), 0)],
  });
  const call = R.vasicekCouponOption({ ...p, type: 'call' });
  const put = R.vasicekCouponOption({ ...p, type: 'put' });
  withinMC(c, call.price, 4, 2e-4, 'call');
  withinMC(pu, put.price, 4, 2e-4, 'put');
  close(bondAtT(call.rStar), p.X, 1e-9, 'r* gir obligasjonsverdi X');
  close(call.price - put.price, call.bond - p.X * R.vasicekBond({ ...p, T: p.T }).P, 1e-10, 'paritet');
  // Uten kupong er det en vanlig nullkupongopsjon.
  const z = R.vasicekCouponOption({ ...p, c: 0, X: 85, type: 'call' });
  close(z.price, R.vasicekOption({ ...p, X: 85, type: 'call' }).price, 1e-12);
});

test('Ho-Lee og Hull-White: MC-simulering av kortrenten tilpasset flat startkurve', () => {
  const r0 = 0.05;
  for (const [kappa, v] of [[0, 0.012], [0.15, 0.015]]) {
    const p = { L: 100, X: 87, T: 2, s: 5, r: r0, kappa, v };
    // θ(t) slik at modellen gjenskaper flat kurve: κ r0 + σ²(1 − e^{−2κt})/(2κ), og σ² t når κ = 0.
    const theta = (t) => (kappa > 0 ? kappa * r0 + v * v * (1 - Math.exp(-2 * kappa * t)) / (2 * kappa) : v * v * t);
    const tau = p.s - p.T;
    const B = kappa > 0 ? (1 - Math.exp(-kappa * tau)) / kappa : tau;
    const varTerm = kappa > 0 ? v * v * (1 - Math.exp(-2 * kappa * p.T)) * B * B / (4 * kappa) : v * v * p.T * B * B / 2;
    const bondAtT = (rT) => p.L * Math.exp(-r0 * tau + B * r0 - varTerm - B * rT);
    const [disc, bond, c, pu] = simulateShortRate({
      r0, kappa, theta, v, T: p.T, steps: 200, pairs: 30000, seed: 61 + kappa * 100,
      payoff: [() => 1, (rT) => bondAtT(rT), (rT) => Math.max(bondAtT(rT) - p.X, 0), (rT) => Math.max(p.X - bondAtT(rT), 0)],
    });
    const name = kappa > 0 ? 'Hull-White' : 'Ho-Lee';
    withinMC(disc, Math.exp(-r0 * p.T), 4, 2e-6, `${name} P(0,T)`);
    withinMC(bond, p.L * Math.exp(-r0 * p.s), 4, 2e-4, `${name} P(0,s)`);
    const f = kappa > 0 ? R.hullWhiteOption : R.hoLeeOption;
    withinMC(c, f({ ...p, type: 'call' }).price, 4, 2e-4, `${name} call`);
    withinMC(pu, f({ ...p, type: 'put' }).price, 4, 2e-4, `${name} put`);
  }
  // Hull-White med κ → 0 er Ho-Lee, og Vasicek-formelen med samme P(0,·) gir samme σ_P.
  const q = { type: 'call', L: 100, X: 87, T: 2, s: 5, r: r0, v: 0.012 };
  close(R.hullWhiteOption({ ...q, kappa: 0 }).price, R.hoLeeOption(q).price, 1e-13);
  close(R.hullWhiteOption({ ...q, kappa: 1e-8 }).price, R.hoLeeOption(q).price, 1e-7);
  close(R.hoLeeOption(q).sigmaP, 0.012 * 3 * Math.sqrt(2), 1e-15);
  const hw = R.hullWhiteOption({ ...q, kappa: 0.15 });
  const put = R.hullWhiteOption({ ...q, kappa: 0.15, type: 'put' });
  close(hw.price - put.price, 100 * Math.exp(-0.25) - 87 * Math.exp(-0.1), 1e-12, 'paritet');
});

// --- Rendleman-Bartter ---------------------------------------------------------------------

// Obligasjonsprisen P(t, s; r) i Rendleman-Bartter løst med Crank-Nicolson i x = ln r,
// som uavhengig kontroll av treet. Returnerer en interpolant i r.
function rbBondPDE({ mu, v, tau, rLo, rHi, nx = 1200, nt = 600 }) {
  const xLo = Math.log(rLo);
  const xHi = Math.log(rHi);
  const h = (xHi - xLo) / nx;
  const dt = tau / nt;
  const x = Float64Array.from({ length: nx + 1 }, (_, j) => xLo + j * h);
  let P = new Float64Array(nx + 1).fill(1);
  const a = mu - 0.5 * v * v;
  const d2 = 0.5 * v * v;
  const L = (j, V) => (a * (V[j + 1] - V[j - 1]) / (2 * h) + d2 * (V[j + 1] - 2 * V[j] + V[j - 1]) / (h * h) - Math.exp(x[j]) * V[j]);
  const edge = (xb, t) => Math.exp(-Math.exp(xb) * (Math.abs(mu) > 1e-12 ? Math.expm1(mu * t) / mu : t));
  const lo = new Float64Array(nx + 1);
  const di = new Float64Array(nx + 1);
  const up = new Float64Array(nx + 1);
  const rhs = new Float64Array(nx + 1);
  for (let k = 0; k < nt; k++) {
    const t1 = (k + 1) * dt;
    for (let j = 1; j < nx; j++) {
      rhs[j] = P[j] + 0.5 * dt * L(j, P);
      lo[j] = -0.5 * dt * (-a / (2 * h) + d2 / (h * h));
      di[j] = 1 - 0.5 * dt * (-2 * d2 / (h * h) - Math.exp(x[j]));
      up[j] = -0.5 * dt * (a / (2 * h) + d2 / (h * h));
    }
    const b0 = edge(x[0], t1);
    const b1 = edge(x[nx], t1);
    rhs[1] -= lo[1] * b0;
    rhs[nx - 1] -= up[nx - 1] * b1;
    for (let j = 2; j < nx; j++) {
      const w = lo[j] / di[j - 1];
      di[j] -= w * up[j - 1];
      rhs[j] -= w * rhs[j - 1];
    }
    const Pn = new Float64Array(nx + 1);
    Pn[0] = b0;
    Pn[nx] = b1;
    Pn[nx - 1] = rhs[nx - 1] / di[nx - 1];
    for (let j = nx - 2; j >= 1; j--) Pn[j] = (rhs[j] - up[j] * Pn[j + 1]) / di[j];
    P = Pn;
  }
  return (r) => {
    const u = (Math.log(r) - xLo) / h;
    const j = Math.min(nx - 1, Math.max(0, Math.floor(u)));
    const w = u - j;
    return (1 - w) * P[j] + w * P[j + 1];
  };
}

test('Rendleman-Bartter: treet mot finite difference og Monte Carlo', () => {
  const p = { L: 100, X: 90, T: 1, s: 3, r: 0.05, mu: 0.01, v: 0.15 };
  const width = 9 * p.v * Math.sqrt(p.s);
  const rLo = p.r * Math.exp(-width);
  const rHi = p.r * Math.exp(width);
  // Obligasjonsprisen i dag: tre mot PDE.
  const P0 = rbBondPDE({ mu: p.mu, v: p.v, tau: p.s, rLo, rHi })(p.r);
  const tree = R.rendlemanBartter({ ...p, type: 'put', n: 600 });
  close(tree.bond / p.L, P0, 5e-5, 'P(0,s) tre mot PDE');
  // Obligasjonsprisen mot MC (eksakt lognormal kortrente, trapesregel for ∫r).
  // Opsjonen: MC til T med P(T, s; r_T) fra PDE-en.
  const PT = rbBondPDE({ mu: p.mu, v: p.v, tau: p.s - p.T, rLo, rHi });
  const rng = createRng(71);
  const steps = 100;
  const dt = p.T / steps;
  const drift = (p.mu - 0.5 * p.v * p.v) * dt;
  const sd = p.v * Math.sqrt(dt);
  const pairs = 30000;
  const acc = { put: [0, 0], call: [0, 0], bond: [0, 0] };
  const z = new Float64Array(steps);
  for (let i = 0; i < pairs; i++) {
    for (let k = 0; k < steps; k++) z[k] = rng.normal();
    const y = { put: 0, call: 0, bond: 0 };
    for (const sgn of [1, -1]) {
      let x = Math.log(p.r);
      let I = 0;
      let rPrev = p.r;
      for (let k = 0; k < steps; k++) {
        x += drift + sd * sgn * z[k];
        const rn = Math.exp(x);
        I += 0.5 * (rPrev + rn) * dt;
        rPrev = rn;
      }
      const B = p.L * PT(rPrev);
      const D = Math.exp(-I);
      y.put += 0.5 * D * Math.max(p.X - B, 0);
      y.call += 0.5 * D * Math.max(B - p.X, 0);
      y.bond += 0.5 * D * B;
    }
    for (const key of Object.keys(acc)) {
      acc[key][0] += y[key];
      acc[key][1] += y[key] ** 2;
    }
  }
  const est = (key) => stats(acc[key][0], acc[key][1], pairs);
  withinMC(est('bond'), tree.bond, 4, 0.002, 'L P(0,s)');
  withinMC(est('put'), tree.price, 4, 0.002, 'europeisk put');
  withinMC(est('call'), R.rendlemanBartter({ ...p, type: 'call', n: 600 }).price, 4, 0.002, 'europeisk call');
});

test('Rendleman-Bartter: paritet, amerikansk ≥ europeisk, konvergens og kontinuitet i T', () => {
  const p = { L: 100, X: 90, T: 1, s: 3, r: 0.05, mu: 0.01, v: 0.15, n: 300 };
  const c = R.rendlemanBartter({ ...p, type: 'call' });
  const pu = R.rendlemanBartter({ ...p, type: 'put' });
  // P(0,T) fra samme tre: en obligasjon med forfall T og like lange steg.
  const P0T = R.rendlemanBartter({ ...p, s: p.T, T: 0.5 * p.T, n: 100, type: 'call', X: 1 }).bond / p.L;
  close(c.price - pu.price, c.bond - p.X * P0T, 1e-10, 'paritet i treet');
  const am = R.rendlemanBartter({ ...p, type: 'put', exercise: 'american' });
  assert.ok(am.price >= pu.price - 1e-12);
  assert.ok(R.rendlemanBartter({ ...p, X: 80, type: 'put', exercise: 'american' }).price >= Math.max(80 - c.bond, 0));
  close(R.rendlemanBartter({ ...p, type: 'put', n: 1200 }).price, pu.price, 2e-3, 'konvergens');
  // Interpolasjonen gjør prisen kontinuerlig når T flyttes forbi et tidssteg (dt = 0,01).
  const a = R.rendlemanBartter({ ...p, T: 1.005 - 1e-9, type: 'put' }).price;
  const b = R.rendlemanBartter({ ...p, T: 1.005 + 1e-9, type: 'put' }).price;
  close(a, b, 1e-6);
  // σ → 0 og μ = 0: renten er konstant, P = e^{−r s}.
  close(R.rendlemanBartter({ ...p, v: 1e-9, mu: 0, type: 'call', X: 1 }).bond, 100 * Math.exp(-0.15), 1e-8);
  assert.throws(() => R.rendlemanBartter({ ...p, mu: 5, n: 10 }), /antall steg/);
});

// --- Black-Derman-Toy ----------------------------------------------------------------------

const bdtInput = { maturities: [1, 2, 3, 4, 5], yields: [0.1, 0.11, 0.12, 0.125, 0.13], vols: [0.2, 0.19, 0.18, 0.17, 0.16] };

test('BDT: kalibreringen gjenskaper renter, yield-volatiliteter og treet i BDT (1990)', () => {
  const tree = R.bdtCalibrate(bdtInput);
  // De tre første radene i kortrentetreet i Black, Derman og Toy (1990), i prosent med to desimaler.
  const paper = [[10.0], [9.79, 14.32], [9.76, 13.77, 19.42]];
  paper.forEach((row, i) => row.forEach((x, j) => close(100 * tree.rates[i][j], x, 0.0051, `rad ${i} node ${j}`)));
  // Prisen på hver nullkupong fra treet og yield-volatiliteten fra opp- og nednoden etter ett år.
  const priceFrom = (i0, j0, mat) => {
    let V = new Float64Array(mat + 1).fill(1);
    for (let i = mat - 1; i >= i0; i--) {
      const next = new Float64Array(i + 1);
      for (let j = 0; j <= i; j++) next[j] = 0.5 * (V[j] + V[j + 1]) / (1 + tree.rates[i][j]);
      V = next;
    }
    return V[j0];
  };
  for (let mat = 1; mat <= 5; mat++) {
    close(priceFrom(0, 0, mat) ** (-1 / mat) - 1, bdtInput.yields[mat - 1], 1e-11, `yield ${mat}`);
    if (mat >= 2) {
      const yu = priceFrom(1, 1, mat) ** (-1 / (mat - 1)) - 1;
      const yd = priceFrom(1, 0, mat) ** (-1 / (mat - 1)) - 1;
      close(0.5 * Math.log(yu / yd), bdtInput.vols[mat - 1], 1e-10, `yield-volatilitet ${mat}`);
    }
  }
  // Treet er lognormalt: forholdet mellom nabonoder er konstant e^{2σ_i}.
  for (let i = 1; i < 5; i++) {
    for (let j = 1; j <= i; j++) close(tree.rates[i][j] / tree.rates[i][j - 1], Math.exp(2 * tree.sigmas[i]), 1e-12);
  }
  // Halvårlige steg: kalibreringen virker også med Δt = 0,5.
  const half = { maturities: [0.5, 1, 1.5, 2], yields: [0.04, 0.042, 0.045, 0.047], vols: [0.25, 0.24, 0.22, 0.2] };
  const t2 = R.bdtCalibrate(half);
  const o = R.bdtOption({ type: 'call', L: 100, X: 50, kT: 0, ks: 4, tree: t2 });
  close(o.bond, 100 * (1 + 0.047 * 0.5) ** -4, 1e-10);
  assert.throws(() => R.bdtCalibrate({ ...bdtInput, maturities: [1, 2, 3.5, 4, 5] }), /jevnt fordelt/);
});

test('BDT: opsjoner – paritet, amerikansk ≥ europeisk og grensetilfeller', () => {
  const tree = R.bdtCalibrate(bdtInput);
  const P = (k) => (1 + bdtInput.yields[k - 1]) ** -k;
  for (const [kT, ks, X] of [[2, 5, 65], [1, 3, 85], [3, 4, 88]]) {
    const c = R.bdtOption({ type: 'call', L: 100, X, kT, ks, tree });
    const p = R.bdtOption({ type: 'put', L: 100, X, kT, ks, tree });
    close(c.bond, 100 * P(ks), 1e-10);
    close(c.price - p.price, 100 * P(ks) - X * P(kT), 1e-10, `paritet kT=${kT} ks=${ks}`);
    const am = R.bdtOption({ type: 'put', exercise: 'american', L: 100, X, kT, ks, tree });
    assert.ok(am.price >= p.price - 1e-12);
  }
  // Med svært lav volatilitet er treet deterministisk og opsjonen lik diskontert indre verdi av forwarden.
  const flat = R.bdtCalibrate({ ...bdtInput, vols: bdtInput.vols.map(() => 1e-7) });
  const c = R.bdtOption({ type: 'call', L: 100, X: 65, kT: 2, ks: 5, tree: flat });
  close(c.price, Math.max(100 * P(5) - 65 * P(2), 0), 1e-5);
  assert.throws(() => R.bdtOption({ type: 'call', L: 100, X: 65, kT: 2, ks: 6, tree }), /siste løpetid/);
});

// --- Katalogen -----------------------------------------------------------------------------

test('kapittel 11-kalkulatorene virker også for andre valg enn standard', () => {
  for (const c of catalog) {
    const p = defaultParams(c);
    for (const inp of c.inputs.filter((i) => i.type === 'select')) {
      for (const o of inp.options) {
        const res = c.compute({ ...p, [inp.key]: o.value });
        const first = Object.values(res)[0];
        assert.ok(Number.isFinite(first), `${c.id} ${inp.key}=${o.value}`);
      }
    }
  }
});
