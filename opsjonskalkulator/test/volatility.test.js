// Kapittel 12: volatilitet og korrelasjon. Estimatorene sjekkes for forventningsretthet på simulerte
// data med kjent σ, intervallene for dekningsgrad, og tilnærmingene mot eksakt implisitt volatilitet.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';
import { cnd, cndInv } from '../src/math/normal.js';
import { chi2cdf, lnGamma } from '../src/math/special.js';
import { gbsm } from '../src/models/bsm.js';
import { heston, hestonExpectedVariance } from '../src/models/alternatives.js';
import {
  closeToCloseVol, ewmaVol, parkinsonVol, garmanKlassVol, rogersSatchellVol, yangZhangVol, chi2inv,
  volConfidenceInterval, impliedVolApproximations, impliedForwardVol, pearson, historicalCorrelation,
  corrDensity, corrCdf, corrMean, impliedCorrelationFX, impliedIndexCorrelation, varianceSwapStrike,
} from '../src/models/volatility.js';
import { close, withinMC } from './helpers.js';

function meanSe(xs) {
  const n = xs.length;
  const m = xs.reduce((a, x) => a + x, 0) / n;
  const v = xs.reduce((a, x) => a + (x - m) ** 2, 0) / (n - 1);
  return { mean: m, se: Math.sqrt(v / n) };
}

// Simulerer dager med åpning, høy, lav og slutt. Innen dagen er log-kursen brownsk med drift
// (mu − σ²/2) og volatilitet sigma; høy og lav trekkes eksakt per delsteg fra brownsk bro
// (maks/min gitt endepunktene). Natten gir et normalfordelt hopp med volatilitet sigmaOn.
function simulateOHLC(rng, { days, sigma, mu = 0, sigmaOn = 0, sub = 64, dt = 1 / 252 }) {
  const O = [];
  const Hs = [];
  const Ls = [];
  const C = [];
  const h = dt / sub;
  const s2h = sigma * sigma * h;
  let x = Math.log(100);
  for (let d = 0; d < days; d++) {
    x += sigmaOn * Math.sqrt(dt) * rng.normal() - 0.5 * sigmaOn * sigmaOn * dt;
    O.push(Math.exp(x));
    let hi = x;
    let lo = x;
    for (let k = 0; k < sub; k++) {
      const nx = x + (mu - 0.5 * sigma * sigma) * h + sigma * Math.sqrt(h) * rng.normal();
      const dd = (nx - x) ** 2;
      hi = Math.max(hi, 0.5 * (x + nx + Math.sqrt(dd - 2 * s2h * Math.log(rng.uniform()))));
      lo = Math.min(lo, 0.5 * (x + nx - Math.sqrt(dd - 2 * s2h * Math.log(rng.uniform()))));
      x = nx;
    }
    Hs.push(Math.exp(hi));
    Ls.push(Math.exp(lo));
    C.push(Math.exp(x));
  }
  return { O, H: Hs, L: Ls, C };
}

test('Historisk volatilitet: håndregnede eksempler', () => {
  const a = Math.log(1.1);
  const cc = closeToCloseVol([100, 110, 100, 110, 100], 252);
  close(cc.sigmaPeriod, a * Math.sqrt(4 / 3), 1e-14, 'sluttkurser');
  close(cc.sigma, a * Math.sqrt(4 / 3 * 252), 1e-13, 'årlig');
  const c = 0.03;
  const dlog = 0.01;
  const Hs = [100 * Math.exp(c), 50 * Math.exp(c)];
  const Ls = [100, 50];
  close(parkinsonVol(Hs, Ls, 1).sigmaPeriod ** 2, c * c / (4 * Math.LN2), 1e-15, 'Parkinson');
  const O = [100.5, 50.2];
  const H2 = [O[0] * Math.exp(0.02), O[1] * Math.exp(0.02)];
  const L2 = [O[0] * Math.exp(-0.015), O[1] * Math.exp(-0.015)];
  const C2 = [O[0] * Math.exp(dlog), O[1] * Math.exp(dlog)];
  close(garmanKlassVol(O, H2, L2, C2, 1).sigmaPeriod ** 2, 0.5 * 0.035 ** 2 - (2 * Math.LN2 - 1) * dlog ** 2, 1e-15, 'Garman-Klass');
  close(rogersSatchellVol(O, H2, L2, C2, 1).sigmaPeriod ** 2, (0.02 - dlog) * 0.02 + (0.015 + dlog) * 0.015, 1e-15, 'Rogers-Satchell');
  // EWMA: konstant |u| gir σ = |u|, λ = 1 gir ukorrigert gjennomsnitt av u².
  close(ewmaVol([100, 110, 100, 110, 100, 110], 0.94, 1).sigmaPeriod, a, 1e-14, 'EWMA konstant');
  const u = [Math.log(101 / 100), Math.log(99 / 101), Math.log(104 / 99)];
  close(ewmaVol([100, 101, 99, 104], 1, 1).sigmaPeriod ** 2, (u[0] ** 2 + u[1] ** 2 + u[2] ** 2) / 3, 1e-15, 'EWMA λ = 1');
  close(ewmaVol([100, 101, 99, 104], 0.9, 1).weightLatest, 0.1 / (1 - 0.9 ** 3), 1e-15, 'vekt på siste');
  assert.throws(() => parkinsonVol([100, 99], [101, 98]), /høykursen/);
  assert.throws(() => closeToCloseVol([100, -1, 3]));
});

test('Historisk volatilitet: sluttkurser er forventningsrett for variansen', () => {
  const rng = createRng(101);
  const sigma = 0.3;
  const dt = 1 / 252;
  const vars = [];
  for (let s = 0; s < 4000; s++) {
    const p = [100];
    for (let i = 0; i < 20; i++) p.push(p[i] * Math.exp(0.1 * dt + sigma * Math.sqrt(dt) * rng.normal()));
    vars.push(closeToCloseVol(p, 252).sigma ** 2);
  }
  withinMC(meanSe(vars), sigma * sigma, 4, 0, 'E[σ̂²]');
});

test('Parkinson og Garman-Klass er forventningsrette uten drift (simulert høy/lav)', () => {
  const rng = createRng(103);
  const sigma = 0.25;
  const target = sigma * sigma; // årlig varians
  const park = [];
  const gk = [];
  for (let s = 0; s < 1000; s++) {
    const { O, H, L, C } = simulateOHLC(rng, { days: 20, sigma });
    park.push(parkinsonVol(H, L, 252).sigma ** 2);
    gk.push(garmanKlassVol(O, H, L, C, 252).sigma ** 2);
  }
  const p = meanSe(park);
  const g = meanSe(gk);
  withinMC(p, target, 4, 0, 'Parkinson');
  withinMC(g, target, 4, 0, 'Garman-Klass');
  // Garman-Klass er mer effektiv enn Parkinson, som er mye mer effektiv enn sluttkurser.
  assert.ok(g.se < p.se, 'GK har lavere varians enn Parkinson');
});

test('Rogers-Satchell tåler drift; Parkinson gjør det ikke', () => {
  const rng = createRng(107);
  const sigma = 0.25;
  const rs = [];
  const park = [];
  for (let s = 0; s < 1000; s++) {
    const { O, H, L, C } = simulateOHLC(rng, { days: 20, sigma, mu: 3 });
    rs.push(rogersSatchellVol(O, H, L, C, 252).sigma ** 2);
    park.push(parkinsonVol(H, L, 252).sigma ** 2);
  }
  const r = meanSe(rs);
  const p = meanSe(park);
  withinMC(r, sigma * sigma, 4, 0, 'Rogers-Satchell med drift');
  assert.ok(p.mean - sigma * sigma > 6 * p.se, `Parkinson overvurderer med drift (${p.mean} mot ${sigma * sigma})`);
});

test('Yang-Zhang er forventningsrett for samlet varians med nattlige hopp og drift', () => {
  const rng = createRng(109);
  const sigma = 0.2;
  const sigmaOn = 0.12;
  const est = [];
  for (let s = 0; s < 1500; s++) {
    const { O, H, L, C } = simulateOHLC(rng, { days: 21, sigma, sigmaOn, mu: 0.5 });
    est.push(yangZhangVol(O, H, L, C, 252).sigma ** 2);
  }
  withinMC(meanSe(est), sigma * sigma + sigmaOn * sigmaOn, 4, 0, 'Yang-Zhang');
});

test('Kjikvadratkvantiler og konfidensintervall for volatilitet (dekningsgrad)', () => {
  for (const [p, k] of [[0.025, 19], [0.975, 19], [0.5, 3], [0.001, 2], [0.999, 250], [0.3, 0.5]]) {
    close(chi2cdf(chi2inv(p, k), k), p, 1e-12, `p=${p} k=${k}`);
  }
  // χ²(1) er kvadratet av en standardnormal.
  close(chi2inv(0.95, 1), cndInv(0.975) ** 2, 1e-10, 'χ²(1)');
  // χ²(2) er eksponentialfordelt med forventning 2.
  close(chi2inv(0.9, 2), -2 * Math.log(0.1), 1e-10, 'χ²(2)');
  // Dekningsgrad: simulerer 4000 utvalg med 20 avkastninger.
  const rng = createRng(113);
  const sigma = 0.3;
  const dt = 1 / 252;
  let hit = 0;
  const N = 4000;
  for (let s = 0; s < N; s++) {
    const p = [100];
    for (let i = 0; i < 20; i++) p.push(p[i] * Math.exp(sigma * Math.sqrt(dt) * rng.normal()));
    const est = closeToCloseVol(p, 252);
    const ci = volConfidenceInterval({ sigma: est.sigma, n: est.n, conf: 0.95 });
    if (ci.lower <= sigma && sigma <= ci.upper) hit++;
  }
  withinMC({ mean: hit / N, se: Math.sqrt(0.95 * 0.05 / N) }, 0.95, 4, 0, 'dekningsgrad');
});

test('Implisitt volatilitet: tilnærmingene mot eksakt løsning', () => {
  // ATM-forward (X = S e^{bT}): alle tre formlene er like, med feil σ³T/24 til ledende orden.
  for (const [T, v] of [[0.25, 0.2], [0.5, 0.3], [1, 0.15]]) {
    const S = 100;
    const r = 0.05;
    const b = 0.02;
    const X = S * Math.exp(b * T);
    const price = gbsm({ type: 'call', S, X, T, r, b, v });
    const a = impliedVolApproximations({ type: 'call', S, X, T, r, b, price });
    close(a.exact, v, 1e-10, 'eksakt');
    close(a.corradoMiller, a.brennerSubrahmanyam, 1e-12, 'CM = BS ved ATM-forward');
    close(a.bcs, a.brennerSubrahmanyam, 1e-12, 'BCS = BS ved ATM-forward');
    close(v - a.brennerSubrahmanyam, v ** 3 * T / 24, 3e-3 * v ** 3 * T, 'feil σ³T/24');
  }
  // Nær pengene (|ln(F/X)| ≤ σ√T/2, σ√T ≤ 0,4): Corrado-Miller har under 1,5 % relativ feil og er
  // bedre enn de to andre. (Den relative feilen avhenger bare av ln(F/X)/(σ√T) og σ√T.)
  for (const T of [0.25, 1]) {
    for (const v of [0.2, 0.4]) {
      for (const z of [-0.5, -0.25, 0.25, 0.5]) {
        const S = 100;
        const r = 0.04;
        const b = 0.01;
        const X = S * Math.exp(b * T - z * v * Math.sqrt(T));
        for (const type of ['call', 'put']) {
          const price = gbsm({ type, S, X, T, r, b, v });
          const a = impliedVolApproximations({ type, S, X, T, r, b, price });
          const tag = `${type} T=${T} σ=${v} z=${z}`;
          assert.ok(Math.abs(a.corradoMiller - v) < 0.015 * v, `${tag}: CM ${a.corradoMiller}`);
          assert.ok(Math.abs(a.corradoMiller - v) < Math.abs(a.brennerSubrahmanyam - v), `${tag}: CM bedre enn BS`);
          assert.ok(Math.abs(a.corradoMiller - v) <= Math.abs(a.bcs - v), `${tag}: CM minst like god som BCS`);
        }
      }
    }
  }
  // En put gjøres om til call med pariteten, så tilnærmingene er like for call og put.
  const q = { S: 59, X: 60, T: 0.25, r: 0.067, b: 0.067 };
  const c = 2.82;
  const p = c - q.S * Math.exp((q.b - q.r) * q.T) + q.X * Math.exp(-q.r * q.T);
  const ac = impliedVolApproximations({ ...q, type: 'call', price: c });
  const ap = impliedVolApproximations({ ...q, type: 'put', price: p });
  close(ap.corradoMiller, ac.corradoMiller, 1e-12, 'put = call (CM)');
  close(ap.exact, ac.exact, 1e-9, 'put = call (eksakt)');
});

test('Implisitt forward-volatilitet', () => {
  close(impliedForwardVol({ v1: 0.2, T1: 0.5, v2: 0.2, T2: 1 }), 0.2, 1e-15, 'flat struktur');
  const f = impliedForwardVol({ v1: 0.2, T1: 0.5, v2: 0.25, T2: 1 });
  close(0.2 ** 2 * 0.5 + f * f * 0.5, 0.25 ** 2 * 1, 1e-15, 'additiv total varians');
  // Prisen på en opsjon med forfall T2 er lik om volatiliteten er σ2 hele veien eller σ1 og så σ_F.
  const S = 100;
  const tv = 0.2 ** 2 * 0.5 + f * f * 0.5;
  close(gbsm({ type: 'call', S, X: 105, T: 1, r: 0.03, b: 0.03, v: Math.sqrt(tv) }),
    gbsm({ type: 'call', S, X: 105, T: 1, r: 0.03, b: 0.03, v: 0.25 }), 1e-12, 'pris');
  assert.throws(() => impliedForwardVol({ v1: 0.3, T1: 0.5, v2: 0.2, T2: 1 }), /arbitrasje/);
});

test('Historisk korrelasjon: Fishers intervall har riktig dekningsgrad', () => {
  const rng = createRng(127);
  const rho = 0.6;
  const n = 30;
  const N = 3000;
  let hit = 0;
  const zs = [];
  for (let s = 0; s < N; s++) {
    const a = [100];
    const b = [50];
    for (let i = 0; i < n; i++) {
      const z1 = rng.normal();
      const z2 = rho * z1 + Math.sqrt(1 - rho * rho) * rng.normal();
      a.push(a[i] * Math.exp(0.02 * z1));
      b.push(b[i] * Math.exp(0.015 * z2));
    }
    const res = historicalCorrelation(a, b, 0.95);
    if (res.lower <= rho && rho <= res.upper) hit++;
    zs.push(Math.atanh(res.rho));
  }
  withinMC({ mean: hit / N, se: Math.sqrt(0.95 * 0.05 / N) }, 0.95, 4, 0, 'dekningsgrad');
  // E[atanh ρ̂] ≈ atanh ρ + ρ/(2(n − 1)).
  withinMC(meanSe(zs), Math.atanh(rho) + rho / (2 * (n - 1)), 4, 0, 'Fisher z');
  // Håndregnet: Σdxdy = 10,75, Σdx² = 5, Σdy² = 23,1875.
  close(pearson([1, 2, 3, 4], [2, 4, 6, 8.5]), 10.75 / Math.sqrt(5 * 23.1875), 1e-14, 'Pearson');
});

test('Fordelingen til empirisk korrelasjon: normering, ρ = 0 og Monte Carlo', () => {
  for (const [rho, n] of [[0, 10], [0.5, 10], [-0.8, 25], [0.9, 50]]) {
    close(corrCdf(1, rho, n), 1, 1e-9, `normering ρ=${rho} n=${n}`);
  }
  // ρ = 0: f(r) = (1 − r²)^{(n−4)/2} / B(½, (n−2)/2), symmetrisk om null.
  for (const n of [4, 7, 20]) {
    const B = Math.exp(lnGamma(0.5) + lnGamma((n - 2) / 2) - lnGamma((n - 1) / 2));
    for (const r of [-0.6, 0.1, 0.5]) close(corrDensity(r, 0, n), (1 - r * r) ** ((n - 4) / 2) / B, 1e-12, `ρ=0 n=${n}`);
    close(corrCdf(0, 0, n), 0.5, 1e-10, 'median null');
  }
  // Eksakt forventning (Hotelling 1953): E[ρ̂] = 2/(n−1)·(Γ(n/2)/Γ((n−1)/2))²·ρ·₂F₁(½, ½; (n+1)/2; ρ²).
  const f21 = (c, z) => {
    let t = 1;
    let sum = 1;
    for (let k = 0; k < 5000 && Math.abs(t) > 1e-18; k++) {
      t *= (0.5 + k) ** 2 / ((c + k) * (k + 1)) * z;
      sum += t;
    }
    return sum;
  };
  for (const [rho, n] of [[0.6, 10], [-0.3, 6], [0.95, 40], [0.2, 4]]) {
    const hotelling = 2 / (n - 1) * Math.exp(2 * (lnGamma(n / 2) - lnGamma((n - 1) / 2))) * rho * f21((n + 1) / 2, rho * rho);
    close(corrMean(rho, n), hotelling, 1e-10, `E[ρ̂] ρ=${rho} n=${n}`);
  }
  // Monte Carlo: n par fra en binormal fordeling.
  const rng = createRng(131);
  for (const [rho, n] of [[0.6, 10], [-0.3, 6]]) {
    const N = 60000;
    const rs = new Float64Array(N);
    const x = new Float64Array(n);
    const y = new Float64Array(n);
    for (let s = 0; s < N; s++) {
      for (let i = 0; i < n; i++) {
        x[i] = rng.normal();
        y[i] = rho * x[i] + Math.sqrt(1 - rho * rho) * rng.normal();
      }
      rs[s] = pearson(x, y);
    }
    for (const r of [rho - 0.3, rho, rho + 0.2]) {
      const pHat = rs.filter((v) => v <= r).length / N;
      withinMC({ mean: pHat, se: Math.sqrt(pHat * (1 - pHat) / N) }, corrCdf(r, rho, n), 4, 0, `P(ρ̂ ≤ ${r}) ρ=${rho} n=${n}`);
    }
    withinMC(meanSe(Array.from(rs)), corrMean(rho, n), 4, 0, `E[ρ̂] ρ=${rho} n=${n}`);
  }
  // For stor n nærmer den eksakte fordelingen seg Fishers normaltilnærming.
  const n = 400;
  const fisher = cnd((Math.atanh(0.55) - Math.atanh(0.5)) * Math.sqrt(n - 3));
  close(corrCdf(0.55, 0.5, n), fisher, 5e-3, 'Fisher for stor n');
});

test('Implisitt korrelasjon fra valuta- og indeksvolatiliteter', () => {
  for (const rho of [-0.7, 0, 0.35, 0.9]) {
    const v1 = 0.1;
    const v2 = 0.14;
    close(impliedCorrelationFX({ v1, v2, v12: Math.sqrt(v1 * v1 + v2 * v2 - 2 * rho * v1 * v2), cross: 'ratio' }), rho, 1e-12, `kvotient ρ=${rho}`);
    close(impliedCorrelationFX({ v1, v2, v12: Math.sqrt(v1 * v1 + v2 * v2 + 2 * rho * v1 * v2), cross: 'product' }), rho, 1e-12, `produkt ρ=${rho}`);
  }
  assert.throws(() => impliedCorrelationFX({ v1: 0.1, v2: 0.1, v12: 0.3 }), /inkonsistente/);
  // Volatiliteten til krysskursen fra simulerte korrelerte valutakurser.
  const rng = createRng(137);
  const rho = 0.4;
  const N = 200000;
  let s = 0;
  for (let i = 0; i < N; i++) {
    const z1 = rng.normal();
    const z2 = rho * z1 + Math.sqrt(1 - rho * rho) * rng.normal();
    s += (0.1 * z1 - 0.12 * z2) ** 2;
  }
  const v12 = Math.sqrt(s / N);
  close(impliedCorrelationFX({ v1: 0.1, v2: 0.12, v12, cross: 'ratio' }), rho, 0.02, 'simulert krysskurs');
  // Indeks med lik parvis korrelasjon.
  const w = [0.5, 0.3, 0.2];
  const vs = [0.25, 0.2, 0.35];
  for (const rr of [0, 0.3, 1]) {
    let var_ = 0;
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) var_ += w[i] * w[j] * vs[i] * vs[j] * (i === j ? 1 : rr);
    const res = impliedIndexCorrelation({ vIndex: Math.sqrt(var_), weights: w, vols: vs });
    close(res.rho, rr, 1e-12, `indeks ρ=${rr}`);
    if (rr === 0) close(res.vIndexUncorrelated, Math.sqrt(var_), 1e-15, 'σ ved ρ = 0');
    if (rr === 1) close(res.vIndexPerfect, Math.sqrt(var_), 1e-15, 'σ ved ρ = 1');
  }
});

test('Variance swap: flatt smil gir σ², Heston-priser gir forventet gjennomsnittsvarians', () => {
  for (const [T, v, r, b] of [[1, 0.2, 0.05, 0.03], [0.25, 0.45, 0.02, -0.01]]) {
    close(varianceSwapStrike({ S: 100, T, r, b, vAtm: v, skew: 0 }).kvar, v * v, 1e-10, `flatt σ=${v}`);
  }
  // Replikasjonen er modelluavhengig for kontinuerlige baner: med Heston-priser skal strike bli
  // E[(1/T)∫v dt] = θ + (v₀ − θ)(1 − e^{−κT})/(κT).
  const h = { S: 100, T: 0.5, r: 0.03, b: 0.01, v0: 0.04, kappa: 1.5, theta: 0.09, sigma: 0.5, rho: -0.7 };
  const res = varianceSwapStrike({
    S: h.S, T: h.T, r: h.r, b: h.b, vAtm: 0.3,
    optionPrice: (K, type) => heston({ ...h, X: K, type }),
  });
  close(res.kvar, hestonExpectedVariance(h), 2e-6, 'Heston');
  // Lineær skjevhet: Demeterfi m.fl. sin tilnærming σ₀²(1 + 3T·skew²) for moderat skjevhet.
  for (const [T, skew] of [[1, 0.1], [0.5, 0.2]]) {
    const vs = varianceSwapStrike({ S: 100, T, r: 0.05, b: 0.05, vAtm: 0.2, skew });
    close(vs.kvar / vs.approx, 1, 5e-3, `skjevhet ${skew}`);
    assert.ok(vs.kvar > 0.04, 'skjevhet øker variansstrike');
  }
});
