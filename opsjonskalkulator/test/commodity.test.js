// Tester for kapittel 10: energiswapper, energiswapsjoner, Miltersen-Schwartz og Schwartz (1997).
// Uavhengige kontroller: Monte Carlo-simulering av modellene, numerisk integrasjon, paritet og grensetilfeller.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';
import { gaussLegendreComposite } from '../src/math/integrate.js';
import { gbsm } from '../src/models/bsm.js';
import {
  energySwap, energySwaption, miltersenSchwartz, miltersenSchwartzMoments,
  miltersenSchwartzMomentsClosed, miltersenSchwartzMomentsQuad,
  schwartz1fFutures, schwartz1fOption, schwartz2fFutures, schwartz2fOption, schwartz2fVariance,
  decay, decayInt, decaySqInt,
} from '../src/models/commodity.js';
import catalog from '../src/catalog/ch10-commodity.js';
import { defaultParams } from '../src/catalog/params.js';
import { close, withinMC, mcTerminal } from './helpers.js';

const black = (type, F, X, T, r, v) => gbsm({ type, S: F, X, T, r, b: 0, v });

function stats(sum, sumSq, n) {
  const mean = sum / n;
  return { mean, se: Math.sqrt(Math.max(sumSq / n - mean * mean, 0) / n) };
}

// --- Hjelpefunksjonene for mean reversion ----------------------------------------------------

test('g(κ,x), ∫g og ∫g² mot numerisk integrasjon, også for små κ', () => {
  for (const k of [0, 1e-9, 1e-5, 5e-4, 2e-3, 0.3, 1.7, 6]) {
    for (const w of [0.1, 1, 4.5]) {
      // Referanse: rekkeutvikling når kx er liten, ellers den direkte formelen.
      const g = (x) => (k * x < 1e-4 ? x * (1 - k * x / 2 + (k * x) ** 2 / 6) : (1 - Math.exp(-k * x)) / k);
      const i1 = gaussLegendreComposite(g, 0, w, 8, 16);
      const i2 = gaussLegendreComposite((x) => g(x) ** 2, 0, w, 8, 16);
      close(decay(k, w), g(w), 1e-12 * Math.max(1, w), `g k=${k} w=${w}`);
      close(decayInt(k, w) / i1, 1, 1e-10, `∫g k=${k} w=${w}`);
      close(decaySqInt(k, w) / i2, 1, 1e-10, `∫g² k=${k} w=${w}`);
    }
  }
});

// --- Energiswapper -----------------------------------------------------------------------

test('energiswap: nåverdi, swappris og flat rente', () => {
  const times = [0.25, 0.5, 0.75, 1];
  const forwards = [45.3, 42.1, 48.7, 51.2];
  const s = energySwap({ times, forwards, rates: [0.04], X: 46, Q: 2 });
  let manual = 0;
  let ann = 0;
  for (let i = 0; i < 4; i++) {
    manual += 2 * (forwards[i] - 46) * Math.exp(-0.04 * times[i]);
    ann += 2 * Math.exp(-0.04 * times[i]);
  }
  close(s.value, manual, 1e-12);
  close(s.annuity, ann, 1e-12);
  // Swapprisen gir verdi null, og verdien er lineær i X.
  close(energySwap({ times, forwards, rates: [0.04], X: s.swapPrice, Q: 2 }).value, 0, 1e-10);
  close(s.value, (s.swapPrice - 46) * s.annuity, 1e-10);
  // Én rente per oppgjør med like verdier = flat rente.
  const s2 = energySwap({ times, forwards, rates: [0.04, 0.04, 0.04, 0.04], X: 46, Q: 2 });
  close(s2.value, s.value, 1e-12);
  // Stigende rentekurve: hver kontantstrøm diskonteres med sin egen rente.
  const rates = [0.03, 0.035, 0.04, 0.045];
  const s3 = energySwap({ times, forwards, rates, X: 46 });
  close(s3.value, forwards.reduce((acc, f, i) => acc + (f - 46) * Math.exp(-rates[i] * times[i]), 0), 1e-12);
  assert.throws(() => energySwap({ times, forwards: [1, 2], rates: [0.04], X: 46 }), /like mange/);
  assert.throws(() => energySwap({ times, forwards, rates: [0.04, 0.05], X: 46 }), /flat rente/);
});

test('energiswapsjon: paritet, annuitet, σ → 0 og Monte Carlo', () => {
  const base = { F: 52, X: 50, T: 0.75, n: 6, j: 12, r: 0.05, v: 0.3, Q: 10 };
  const payer = energySwaption({ ...base, type: 'call' });
  const receiver = energySwaption({ ...base, type: 'put' });
  let ann = 0;
  for (let i = 1; i <= 6; i++) ann += 10 * Math.exp(-0.05 * (0.75 + i / 12));
  close(payer.annuity, ann, 1e-12);
  close(payer.price - receiver.price, ann * (52 - 50), 1e-10, 'payer − receiver');
  close(energySwaption({ ...base, type: 'call', v: 1e-9 }).price, ann * 2, 1e-8, 'σ → 0');
  close(energySwaption({ ...base, type: 'put', v: 1e-9 }).price, 0, 1e-8, 'σ → 0 receiver');
  // MC: swapprisen er lognormal med volatilitet σ; utbetalingen ganges med annuiteten.
  for (const type of ['call', 'put']) {
    const mc = mcTerminal({
      S: 52, T: 0.75, r: 0, b: 0, v: 0.3, n: 200000, seed: 11,
      payoff: (FT) => Math.max(type === 'call' ? FT - 50 : 50 - FT, 0),
    });
    withinMC({ mean: mc.mean * ann, se: mc.se * ann }, energySwaption({ ...base, type }).price, 4, 0, type);
  }
});

// --- Miltersen og Schwartz (1998) --------------------------------------------------------------

const msBase = {
  F: 95, X: 80, T: 0.5, T2: 1, r: 0.05, vS: 0.266, vE: 0.249, vf: 0.0096,
  rhoSE: 0.805, rhoSf: 0.0805, rhoEf: 0.1243, kE: 1.045, kf: 0.2,
};

test('Miltersen-Schwartz: lukkede uttrykk for σ_z² og σ_xz mot numerisk integrasjon', () => {
  const sets = [
    msBase,
    { ...msBase, T: 2, T2: 3, vf: 0.03, kf: 0.05, rhoSf: 0.6, rhoEf: -0.4 },
    { ...msBase, T: 1, T2: 1, kE: 8, kf: 3 },
    { ...msBase, T: 5, T2: 10, kE: 0.01, kf: 2, rhoSE: -0.3 },
    { ...msBase, T: 0.1, T2: 7, kE: 25, kf: 0.002 },
  ];
  for (const p of sets) {
    const a = miltersenSchwartzMomentsClosed(p);
    const b = miltersenSchwartzMomentsQuad(p);
    close(a.varZ / b.varZ, 1, 1e-11, `varZ ${JSON.stringify(p)}`);
    close(a.sxz, b.sxz, 1e-13 + 1e-10 * Math.abs(b.sxz), `sxz ${JSON.stringify(p)}`);
  }
  // Rundt terskelen for små κ (bytte til kvadratur) er verdiene kontinuerlige.
  const lo = miltersenSchwartzMoments({ ...msBase, kE: 0.99e-3, kf: 0.99e-3 });
  const hi = miltersenSchwartzMoments({ ...msBase, kE: 1.01e-3, kf: 1.01e-3 });
  close(lo.varZ, hi.varZ, 1e-7);
  close(lo.sxz, hi.sxz, 1e-9);
  // κ = 0: konstante volatiliteter, σ_F(u) = σ_S e_S + σ_f (T2 − u) e_f − σ_E (T2 − u) e_E.
  const z = miltersenSchwartzMoments({ ...msBase, kE: 0, kf: 0 });
  const q = miltersenSchwartzMomentsQuad({ ...msBase, kE: 0, kf: 0 });
  close(z.varZ, q.varZ, 1e-14);
  close(z.sxz, q.sxz, 1e-16);
});

test('Miltersen-Schwartz: grensetilfeller og put-call-paritet', () => {
  // Uten stokastisk rente og convenience yield er modellen Black-76.
  for (const type of ['call', 'put']) {
    const m = miltersenSchwartz({ ...msBase, type, vE: 0, vf: 0 });
    close(m.price, black(type, 95, 80, 0.5, 0.05, 0.266), 1e-12, type);
    close(m.sxz, 0, 0);
  }
  // Uten rentevolatilitet er σ_xz = 0 og variansen den samme som i Schwartz to-faktor.
  const m0 = miltersenSchwartz({ ...msBase, T: 1.5, T2: 4, vf: 0 });
  close(m0.sxz, 0, 0);
  const v2 = schwartz2fVariance({ T: 1.5, T2: 4, kappa: msBase.kE, v1: msBase.vS, v2: msBase.vE, rho: msBase.rhoSE });
  close(m0.vz ** 2, v2, 1e-13);
  // Paritet: c − p = P(0,T)(F e^{−σ_xz} − X).
  const p = { ...msBase, vf: 0.02, rhoSf: 0.5 };
  const c = miltersenSchwartz({ ...p, type: 'call' });
  const pu = miltersenSchwartz({ ...p, type: 'put' });
  close(c.price - pu.price, Math.exp(-p.r * p.T) * (p.F * Math.exp(-c.sxz) - p.X), 1e-11);
  // Futures med forfall lik opsjonen og ingen convenience yield: kun spot- og rentevolatilitet.
  assert.throws(() => miltersenSchwartz({ ...msBase, T2: 0.4 }), /T2/);
});

test('Miltersen-Schwartz mot Monte Carlo-simulering av rente, convenience yield og spot', () => {
  // Gaussisk HJM: forwardrentene og forward convenience yield har volatilitet σ e^{−κ(s−u)}.
  // Flat startkurve f(0,u) = r0, så P(0,T) = e^{−r0 T}. Kortrenten er da
  //   r(u) = r0 + σ_f²(1 − e^{−κ_f u})²/(2κ_f²) + Y(u),  dY = −κ_f Y du + σ_f dW_f,
  // og futuresprisen er en martingal med volatilitet σ_S dW_S + a_f(u) dW_f − a_E(u) dW_E.
  const p = {
    F: 100, X: 100, T: 2, T2: 3, r: 0.04, vS: 0.3, vE: 0.25, vf: 0.03,
    rhoSE: 0.5, rhoSf: 0.6, rhoEf: -0.2, kE: 1.5, kf: 0.1,
  };
  const steps = 50;
  const dt = p.T / steps;
  const sq = Math.sqrt(dt);
  // Cholesky av korrelasjonsmatrisen for (W_S, W_E, W_f).
  const l21 = p.rhoSE;
  const l22 = Math.sqrt(1 - l21 * l21);
  const l31 = p.rhoSf;
  const l32 = (p.rhoEf - l31 * l21) / l22;
  const l33 = Math.sqrt(1 - l31 * l31 - l32 * l32);
  const rng = createRng(2024);
  const pairs = 30000;
  const sums = { call: [0, 0], put: [0, 0], disc: [0, 0] };
  const zs = new Float64Array(3 * steps);
  const ef = Math.exp(-p.kf * dt);
  for (let n = 0; n < pairs; n++) {
    for (let i = 0; i < 3 * steps; i++) zs[i] = rng.normal();
    const res = { call: 0, put: 0, disc: 0 };
    for (const sgn of [1, -1]) {
      let lnF = Math.log(p.F);
      let Y = 0;
      let rPrev = p.r;
      let I = 0;
      for (let k = 0; k < steps; k++) {
        const z1 = sgn * zs[3 * k];
        const z2 = sgn * zs[3 * k + 1];
        const z3 = sgn * zs[3 * k + 2];
        const dWS = sq * z1;
        const dWE = sq * (l21 * z1 + l22 * z2);
        const dWf = sq * (l31 * z1 + l32 * z2 + l33 * z3);
        const um = (k + 0.5) * dt;
        const af = p.vf * decay(p.kf, p.T2 - um);
        const aE = p.vE * decay(p.kE, p.T2 - um);
        const var1 = p.vS ** 2 + af * af + aE * aE + 2 * p.rhoSf * p.vS * af - 2 * p.rhoSE * p.vS * aE - 2 * p.rhoEf * af * aE;
        lnF += p.vS * dWS + af * dWf - aE * dWE - 0.5 * var1 * dt;
        Y = Y * ef + p.vf * Math.exp(-0.5 * p.kf * dt) * dWf;
        const u = (k + 1) * dt;
        const rNow = p.r + p.vf ** 2 * (1 - Math.exp(-p.kf * u)) ** 2 / (2 * p.kf ** 2) + Y;
        I += 0.5 * (rPrev + rNow) * dt;
        rPrev = rNow;
      }
      const D = Math.exp(-I);
      const FT = Math.exp(lnF);
      res.call += 0.5 * D * Math.max(FT - p.X, 0);
      res.put += 0.5 * D * Math.max(p.X - FT, 0);
      res.disc += 0.5 * D;
    }
    for (const key of Object.keys(sums)) {
      sums[key][0] += res[key];
      sums[key][1] += res[key] * res[key];
    }
  }
  const est = (key) => stats(sums[key][0], sums[key][1], pairs);
  withinMC(est('disc'), Math.exp(-p.r * p.T), 4, 2e-6, 'diskonteringsfaktor');
  for (const type of ['call', 'put']) {
    const exact = miltersenSchwartz({ ...p, type });
    const e = est(type);
    withinMC(e, exact.price, 4, 0.002, `MS ${type}`);
    // Justeringen σ_xz må være synlig i forhold til MC-usikkerheten, ellers sjekker testen lite.
    const noAdj = Math.exp(-p.r * p.T) * black(type, p.F, p.X, p.T, 0, exact.vz / Math.sqrt(p.T));
    assert.ok(Math.abs(noAdj - exact.price) > 8 * e.se, `σ_xz-effekten ${noAdj - exact.price} er for liten mot SE ${e.se}`);
  }
});

// --- Schwartz (1997) én-faktor -----------------------------------------------------------------

test('Schwartz én-faktor: futurespris og opsjoner mot eksakt simulering av ln S', () => {
  const p = { S: 20, X: 21, T: 0.75, T2: 2, r: 0.05, kappa: 0.8, alpha: 3.2, v: 0.4 };
  const rng = createRng(77);
  const n = 200000;
  // ln S_t er normalfordelt: middel e^{−κt} ln S + (1 − e^{−κt}) α*, varians σ²(1 − e^{−2κt})/(2κ).
  const mean = (t, x0) => Math.exp(-p.kappa * t) * x0 + (1 - Math.exp(-p.kappa * t)) * p.alpha;
  const sd = (t) => p.v * Math.sqrt((1 - Math.exp(-2 * p.kappa * t)) / (2 * p.kappa));
  let s1 = 0;
  let s2 = 0;
  const acc = { spotCall: [0, 0], futCall: [0, 0], futPut: [0, 0] };
  const add = (key, y) => { acc[key][0] += y; acc[key][1] += y * y; };
  for (let i = 0; i < n; i++) {
    const z = rng.normal();
    const y = Math.exp(mean(p.T2, Math.log(p.S)) + sd(p.T2) * z);
    s1 += y;
    s2 += y * y;
    const xT = mean(p.T, Math.log(p.S)) + sd(p.T) * rng.normal();
    add('spotCall', Math.max(Math.exp(xT) - p.X, 0));
    const FT = schwartz1fFutures({ S: Math.exp(xT), tau: p.T2 - p.T, kappa: p.kappa, alpha: p.alpha, v: p.v });
    add('futCall', Math.max(FT - p.X, 0));
    add('futPut', Math.max(p.X - FT, 0));
  }
  withinMC(stats(s1, s2, n), schwartz1fFutures({ S: p.S, tau: p.T2, kappa: p.kappa, alpha: p.alpha, v: p.v }), 4, 0, 'F(0,T2) = E[S_T2]');
  const df = Math.exp(-p.r * p.T);
  const scaled = (key) => {
    const s = stats(acc[key][0], acc[key][1], n);
    return { mean: s.mean * df, se: s.se * df };
  };
  withinMC(scaled('spotCall'), schwartz1fOption({ ...p, type: 'call', T2: p.T }).price, 4, 0, 'opsjon på spot');
  withinMC(scaled('futCall'), schwartz1fOption({ ...p, type: 'call' }).price, 4, 0, 'call på futures');
  withinMC(scaled('futPut'), schwartz1fOption({ ...p, type: 'put' }).price, 4, 0, 'put på futures');
});

test('Schwartz én-faktor: grensetilfeller og paritet', () => {
  const p = { S: 20, X: 21, T: 0.75, T2: 2, r: 0.05, kappa: 0.8, alpha: 3.2, v: 0.4 };
  // κ → 0: ln S er en brownsk bevegelse uten drift, så F = S e^{σ²τ/2} og opsjonen er Black-76 med σ.
  const z = schwartz1fOption({ ...p, kappa: 0 });
  close(z.F, p.S * Math.exp(0.5 * p.v * p.v * p.T2), 1e-12);
  close(z.price, black('call', z.F, p.X, p.T, p.r, p.v), 1e-12);
  close(schwartz1fOption({ ...p, kappa: 1e-9 }).price, z.price, 1e-7);
  // F(0,0) = S, og langt fram nærmer futureskurven seg e^{α* + σ²/(4κ)}.
  close(schwartz1fFutures({ ...p, tau: 0 }), p.S, 1e-12);
  close(schwartz1fFutures({ ...p, tau: 60 }), Math.exp(p.alpha + p.v * p.v / (4 * p.kappa)), 1e-9);
  // Put-call-paritet på futures.
  const c = schwartz1fOption({ ...p, type: 'call' });
  const pu = schwartz1fOption({ ...p, type: 'put' });
  close(c.price - pu.price, Math.exp(-p.r * p.T) * (c.F - p.X), 1e-12);
  // σ → 0: utbetalingen er deterministisk.
  const d = schwartz1fOption({ ...p, v: 1e-10 });
  close(d.price, Math.exp(-p.r * p.T) * Math.max(d.F - p.X, 0), 1e-9);
});

// --- Gibson-Schwartz / Schwartz (1997) to-faktor ------------------------------------------------

test('Schwartz to-faktor: futuresprisen mot Schwartz sitt uttrykk for A(τ)', () => {
  for (const q of [
    { S: 20, delta: 0.05, r: 0.06, kappa: 1.2, alpha: 0.06, v1: 0.35, v2: 0.4, rho: 0.8 },
    { S: 55, delta: -0.02, r: 0.03, kappa: 0.3, alpha: 0.01, v1: 0.25, v2: 0.15, rho: -0.3 },
  ]) {
    for (const tau of [0.1, 1, 3.5, 12]) {
      const { kappa: k, alpha: a, v1, v2, rho, r } = q;
      const A = (r - a + 0.5 * v2 * v2 / (k * k) - rho * v1 * v2 / k) * tau +
        0.25 * v2 * v2 * (1 - Math.exp(-2 * k * tau)) / k ** 3 +
        (a * k + rho * v1 * v2 - v2 * v2 / k) * (1 - Math.exp(-k * tau)) / (k * k);
      const lit = q.S * Math.exp(-q.delta * (1 - Math.exp(-k * tau)) / k + A);
      close(schwartz2fFutures({ ...q, tau }) / lit, 1, 1e-12, `tau=${tau}`);
    }
  }
});

test('Schwartz to-faktor: futurespris og opsjon mot Euler-simulering av S og δ', () => {
  const p = { S: 20, X: 20, T: 0.5, T2: 1.5, r: 0.06, delta: 0.05, kappa: 1.2, alpha: 0.06, v1: 0.35, v2: 0.4, rho: 0.8 };
  const steps = 150;
  const dt = p.T2 / steps;
  const kOpt = Math.round(p.T / dt);
  const sq = Math.sqrt(dt);
  const c = Math.sqrt(1 - p.rho * p.rho);
  const rng = createRng(5);
  const pairs = 25000;
  let sF = 0;
  let sF2 = 0;
  const acc = { call: [0, 0], put: [0, 0] };
  for (let n = 0; n < pairs; n++) {
    const z1s = new Float64Array(steps);
    const z2s = new Float64Array(steps);
    for (let k = 0; k < steps; k++) {
      z1s[k] = rng.normal();
      z2s[k] = rng.normal();
    }
    let yF = 0;
    const yo = { call: 0, put: 0 };
    for (const sgn of [1, -1]) {
      let lnS = Math.log(p.S);
      let d = p.delta;
      for (let k = 0; k < steps; k++) {
        if (k === kOpt) {
          const FT = schwartz2fFutures({ ...p, S: Math.exp(lnS), delta: d, tau: p.T2 - p.T });
          yo.call += 0.5 * Math.max(FT - p.X, 0);
          yo.put += 0.5 * Math.max(p.X - FT, 0);
        }
        const z1 = sgn * z1s[k];
        const z2 = sgn * (p.rho * z1s[k] + c * z2s[k]);
        const dNew = d + p.kappa * (p.alpha - d) * dt + p.v2 * sq * z2;
        lnS += (p.r - 0.5 * (d + dNew) - 0.5 * p.v1 * p.v1) * dt + p.v1 * sq * z1;
        d = dNew;
      }
      yF += 0.5 * Math.exp(lnS);
    }
    sF += yF;
    sF2 += yF * yF;
    for (const key of ['call', 'put']) {
      acc[key][0] += yo[key];
      acc[key][1] += yo[key] ** 2;
    }
  }
  withinMC(stats(sF, sF2, pairs), schwartz2fFutures({ ...p, tau: p.T2 }), 4, 0.001, 'F(0,T2) = E[S_T2]');
  const df = Math.exp(-p.r * p.T);
  for (const type of ['call', 'put']) {
    const s = stats(acc[type][0], acc[type][1], pairs);
    withinMC({ mean: s.mean * df, se: s.se * df }, schwartz2fOption({ ...p, type }).price, 4, 0.0005, type);
  }
});

test('Schwartz to-faktor: paritet og grensetilfeller', () => {
  const p = { S: 20, X: 19, T: 0.5, T2: 1.5, r: 0.06, delta: 0.05, kappa: 1.2, alpha: 0.06, v1: 0.35, v2: 0.4, rho: 0.8 };
  const c = schwartz2fOption({ ...p, type: 'call' });
  const pu = schwartz2fOption({ ...p, type: 'put' });
  close(c.price - pu.price, Math.exp(-p.r * p.T) * (c.F - p.X), 1e-12);
  // σ2 = 0 og δ = α̂: konstant convenience yield, F = S e^{(r − δ)τ}, og opsjonen er Black-76 med σ1.
  const flat = schwartz2fOption({ ...p, v2: 0, delta: p.alpha });
  close(flat.F, p.S * Math.exp((p.r - p.alpha) * p.T2), 1e-12);
  close(flat.price, black('call', flat.F, p.X, p.T, p.r, p.v1), 1e-12);
  // κ → 0 er kontinuerlig.
  close(schwartz2fOption({ ...p, kappa: 1e-7 }).price, schwartz2fOption({ ...p, kappa: 0 }).price, 1e-6);
});

// --- Katalogen -----------------------------------------------------------------------------

test('kapittel 10-kalkulatorene virker også for andre valg enn standard', () => {
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
