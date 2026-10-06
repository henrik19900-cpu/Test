// Kapittel 6: justeringer og alternativer til BSM. Hver modell sjekkes mot en uavhengig metode
// (Monte Carlo med fast seed) og mot grensetilfeller/identiteter.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';
import { cnd } from '../src/math/normal.js';
import { gammaP, ncx2cdf } from '../src/math/special.js';
import { gbsm, d1d2 } from '../src/models/bsm.js';
import {
  tradingDaysBSM, mertonJumpDiffusion, batesJumpDiffusion, leland, averageVarianceMoments, hullWhite87,
  hullWhite88, sabrVol, sabr, cev, cevExpectedSpot, displacedDiffusion, heston, hestonExpectedVariance,
  gammaPRobust, ncx2cdfLarge,
} from '../src/models/alternatives.js';
import { close, withinMC } from './helpers.js';

const parity = (p) => p.S * Math.exp((p.b - p.r) * p.T) - p.X * Math.exp(-p.r * p.T);

// --- Tilfeldige tall til simuleringene ----------------------------------------------------------
function poisson(rng, m) {
  // Invers transformasjon, start i null (brukes bare for moderat m).
  const u = rng.uniform();
  let k = 0;
  let p = Math.exp(-m);
  let F = p;
  while (u > F && k < 10000) {
    k++;
    p *= m / k;
    F += p;
  }
  return k;
}

function gammaVariate(rng, shape) {
  // Marsaglia og Tsang (2000), shape ≥ 1.
  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);
  for (;;) {
    let x;
    let v;
    do {
      x = rng.normal();
      v = 1 + c * x;
    } while (v <= 0);
    v = v * v * v;
    const u = rng.uniform();
    if (Math.log(u) < 0.5 * x * x + d - d * v + d * Math.log(v)) return d * v;
  }
}

function meanSe(sum, sumSq, n) {
  const mean = sum / n;
  return { mean, se: Math.sqrt(Math.max(sumSq / n - mean * mean, 0) / n) };
}

// Monte Carlo av en terminal utbetaling der sampleST(rng) trekker S_T. Diskonterer med e^{−rT}.
function mcPrice({ n, seed, r, T, sampleST, payoff }) {
  const rng = createRng(seed);
  let s = 0;
  let s2 = 0;
  for (let i = 0; i < n; i++) {
    const y = payoff(sampleST(rng));
    s += y;
    s2 += y * y;
  }
  const { mean, se } = meanSe(s, s2, n);
  const df = Math.exp(-r * T);
  return { mean: mean * df, se: se * df };
}

const callPay = (X) => (ST) => Math.max(ST - X, 0);
const putPay = (X) => (ST) => Math.max(X - ST, 0);

// --- French (1984) --------------------------------------------------------------------------------
test('Handelsdager (French): lik GBSM med effektiv volatilitet, og mot MC', () => {
  for (const [type, S, X, Tc, td, r, b, v] of [
    ['call', 100, 100, 60 / 365, 42 / 252, 0.05, 0.05, 0.2],
    ['put', 80, 90, 0.75, 180 / 252, 0.08, 0.02, 0.35],
    ['call', 50, 45, 30 / 365, 20 / 252, 0.03, -0.01, 0.5],
  ]) {
    const price = tradingDaysBSM({ type, S, X, T: Tc, t: td, r, b, v });
    close(price, gbsm({ type, S, X, T: Tc, r, b, v: v * Math.sqrt(td / Tc) }), 1e-12, `${type} effektiv vol`);
    // ln S_T ~ N(ln S + bT − σ²t/2, σ²t), diskontering over kalendertid.
    const est = mcPrice({
      n: 200000, seed: 5, r, T: Tc,
      sampleST: (rng) => S * Math.exp(b * Tc - 0.5 * v * v * td + v * Math.sqrt(td) * rng.normal()),
      payoff: type === 'call' ? callPay(X) : putPay(X),
    });
    withinMC(est, price, 4, 0, `French ${type}`);
  }
  // t = T gir vanlig BSM.
  close(tradingDaysBSM({ type: 'put', S: 100, X: 105, T: 0.4, t: 0.4, r: 0.05, b: 0.03, v: 0.25 }),
    gbsm({ type: 'put', S: 100, X: 105, T: 0.4, r: 0.05, b: 0.03, v: 0.25 }), 1e-13);
});

// --- Hopp-diffusjon ----------------------------------------------------------------------------------
test('Merton hopp-diffusjon: bokas eksempel, grensetilfeller og paritet', () => {
  const p = { S: 45, X: 55, T: 0.25, r: 0.1, b: 0.1, v: 0.25, lambda: 3, gamma: 0.4 };
  close(mertonJumpDiffusion({ ...p, type: 'call' }), 0.2417, 1e-4, 'Haug-eksempel');
  const c = mertonJumpDiffusion({ ...p, type: 'call' });
  const pt = mertonJumpDiffusion({ ...p, type: 'put' });
  close(c - pt, parity(p), 1e-12, 'put-call-paritet');
  const bs = gbsm({ ...p, type: 'call' });
  close(mertonJumpDiffusion({ ...p, type: 'call', lambda: 0 }), bs, 1e-15, 'λ = 0');
  close(mertonJumpDiffusion({ ...p, type: 'call', gamma: 0 }), bs, 1e-15, 'γ = 0');
  // Med γ fast blir hoppene sjeldne men store når λ → 0; grensen er BSM med diffusjonsvolatiliteten.
  close(mertonJumpDiffusion({ ...p, type: 'call', lambda: 1e-8 }), gbsm({ ...p, type: 'call', v: p.v * Math.sqrt(1 - p.gamma) }), 1e-6, 'λ → 0');
  // Mange små hopp nærmer seg en ren diffusjon med samme totale varians.
  close(mertonJumpDiffusion({ ...p, type: 'call', lambda: 5000 }), bs, 2e-4, 'λ → ∞');
  // Merton er Bates med k̄ = 0, δ² = γσ²/λ og diffusjonsvolatilitet σ√(1 − γ).
  close(c, batesJumpDiffusion({
    ...p, type: 'call', v: p.v * Math.sqrt(1 - p.gamma), kbar: 0, delta: Math.sqrt(p.gamma * p.v * p.v / p.lambda),
  }), 1e-13, 'Merton = Bates(k̄ = 0)');
});

function jumpSampler({ S, T, b, v, lambda, kbar, delta }) {
  const g = Math.log1p(kbar) - 0.5 * delta * delta; // forventet log-hopp
  const drift = (b - lambda * kbar - 0.5 * v * v) * T;
  return (rng) => {
    const N = poisson(rng, lambda * T);
    let x = drift + v * Math.sqrt(T) * rng.normal();
    if (N > 0) x += N * g + delta * Math.sqrt(N) * rng.normal();
    return S * Math.exp(x);
  };
}

test('Merton hopp-diffusjon mot Monte Carlo med eksplisitte hopp', () => {
  for (const [type, p] of [
    ['call', { S: 45, X: 55, T: 0.25, r: 0.1, b: 0.1, v: 0.25, lambda: 3, gamma: 0.4 }],
    ['put', { S: 100, X: 90, T: 1, r: 0.05, b: 0.02, v: 0.3, lambda: 1, gamma: 0.7 }],
  ]) {
    const delta = Math.sqrt(p.gamma * p.v * p.v / p.lambda);
    const est = mcPrice({
      n: 400000, seed: 11, r: p.r, T: p.T,
      sampleST: jumpSampler({ S: p.S, T: p.T, b: p.b, v: p.v * Math.sqrt(1 - p.gamma), lambda: p.lambda, kbar: 0, delta }),
      payoff: type === 'call' ? callPay(p.X) : putPay(p.X),
    });
    withinMC(est, mertonJumpDiffusion({ ...p, type }), 4, 0, `Merton ${type}`);
  }
});

test('Generalisert hopp-diffusjon (Bates) mot Monte Carlo, paritet og grensetilfeller', () => {
  const cases = [
    ['call', { S: 100, X: 100, T: 0.5, r: 0.08, b: 0.08, v: 0.2, lambda: 1, kbar: -0.1, delta: 0.3 }],
    ['put', { S: 100, X: 110, T: 0.75, r: 0.04, b: 0.01, v: 0.15, lambda: 3, kbar: 0.05, delta: 0.1 }],
    ['put', { S: 50, X: 40, T: 1, r: 0.03, b: 0.03, v: 0.25, lambda: 0.5, kbar: -0.3, delta: 0.2 }],
  ];
  for (const [type, p] of cases) {
    const price = batesJumpDiffusion({ ...p, type });
    const est = mcPrice({
      n: 400000, seed: 13, r: p.r, T: p.T, sampleST: jumpSampler(p),
      payoff: type === 'call' ? callPay(p.X) : putPay(p.X),
    });
    withinMC(est, price, 4, 0, `Bates ${type} k̄=${p.kbar}`);
    const other = batesJumpDiffusion({ ...p, type: type === 'call' ? 'put' : 'call' });
    close(type === 'call' ? price - other : other - price, parity(p), 1e-12, 'paritet');
    close(batesJumpDiffusion({ ...p, type, lambda: 0 }), gbsm({ ...p, type }), 1e-15, 'λ = 0');
  }
});

// --- Leland (1985) -----------------------------------------------------------------------------------
// Simulert diskret delta-sikring av en solgt call med kostnad k/2 per krone handlet ved hver
// rebalansering. Med Leland-prisen og Leland-deltaen skal forventet sikringsresultat være ≈ 0;
// med BSM-pris og BSM-delta taper sikreren omtrent Leland-tillegget.
function hedgeShortCall({ S, X, T, r, v, k, n, vh, price, paths, seed }) {
  const rng = createRng(seed);
  const dt = T / n;
  const delta = (s, tau) => cnd(d1d2(s, X, tau, r, vh)[0]);
  let sum = 0;
  let sumSq = 0;
  for (let p = 0; p < paths; p++) {
    let s = S;
    let d = delta(s, T);
    let cash = price - d * s;
    for (let i = 1; i <= n; i++) {
      s *= Math.exp((r - 0.5 * v * v) * dt + v * Math.sqrt(dt) * rng.normal());
      cash *= Math.exp(r * dt);
      if (i < n) {
        const nd = delta(s, T - i * dt);
        cash -= (nd - d) * s + 0.5 * k * Math.abs(nd - d) * s;
        d = nd;
      }
    }
    const y = (cash + d * s - Math.max(s - X, 0)) * Math.exp(-r * T);
    sum += y;
    sumSq += y * y;
  }
  return meanSe(sum, sumSq, paths);
}

test('Leland: grensetilfeller og simulert sikring med transaksjonskostnader', () => {
  const base = { type: 'call', S: 100, X: 100, T: 0.5, r: 0.1, b: 0.1, v: 0.3 };
  const bs = gbsm(base);
  close(leland({ ...base, k: 0, dt: 0.01 }).price, bs, 1e-15, 'k = 0');
  const short = leland({ ...base, k: 0.01, dt: 1 / 52 });
  const long = leland({ ...base, k: 0.01, dt: 1 / 52, position: 'long' });
  assert.ok(long.price < bs && bs < short.price, 'lang < BSM < kort');
  close(short.vA ** 2 + long.vA ** 2, 2 * base.v ** 2, 1e-15, 'symmetrisk justering av variansen');
  assert.throws(() => leland({ ...base, k: 0.2, dt: 1 / 52, position: 'long' }));

  const k = 0.01;
  const n = 26;
  const L = leland({ ...base, k, dt: base.T / n });
  const adj = L.price - bs;
  const hl = hedgeShortCall({ ...base, k, n, vh: L.vA, price: L.price, paths: 20000, seed: 3 });
  const hb = hedgeShortCall({ ...base, k, n, vh: base.v, price: bs, paths: 20000, seed: 3 });
  assert.ok(Math.abs(hl.mean) <= 4 * hl.se + 0.05 * adj, `Leland-sikring: ${hl.mean} ± ${hl.se}`);
  assert.ok(Math.abs(hb.mean + adj) <= 4 * hb.se + 0.1 * adj, `BSM-sikring taper ${hb.mean}, Leland-tillegg ${adj}`);
});

// --- Hull og White (1987) -----------------------------------------------------------------------------
test('Hull-White (1987): momentene til gjennomsnittsvariansen', () => {
  // Lukket form (μ = 0) mot den generelle kvadraturen.
  for (const k of [1e-6, 0.01, 0.4, 1.5, 3]) {
    const [m, va, th] = averageVarianceMoments(0.04, 0, Math.sqrt(k), 1);
    const [m2, va2, th2] = averageVarianceMoments(0.04, 1e-10, Math.sqrt(k), 1);
    close(m2 / m, 1, 1e-9, `E[V̄] k=${k}`);
    close(va2 / va, 1, 1e-8, `Var k=${k}`);
    close(th2 / th, 1, 1e-6, `M3 k=${k}`);
    // Haugs uttrykk for k ikke for liten
    if (k > 0.3) {
      close(va / 0.04 ** 2, 2 * (Math.exp(k) - k - 1) / (k * k) - 1, 1e-12, 'Var lukket');
      close(th / 0.04 ** 3, (Math.exp(3 * k) - (9 + 18 * k) * Math.exp(k) + 8 + 24 * k + 18 * k * k + 6 * k ** 3) / (3 * k ** 3), 1e-10, 'M3 lukket');
    }
  }
  // Monte Carlo av V̄ med eksakt simulert geometrisk brownsk varians (trapesregel i tid).
  for (const [mu, xi] of [[0, 0.8], [0.3, 0.6], [-0.5, 1]]) {
    const V0 = 0.04;
    const T = 1;
    const steps = 200;
    const dt = T / steps;
    const rng = createRng(17);
    const n = 40000;
    let s1 = 0;
    let s2 = 0;
    let s3 = 0;
    const vals = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      let V = V0;
      let acc = 0.5 * V;
      for (let j = 1; j <= steps; j++) {
        V *= Math.exp((mu - 0.5 * xi * xi) * dt + xi * Math.sqrt(dt) * rng.normal());
        acc += j === steps ? 0.5 * V : V;
      }
      vals[i] = acc * dt / T;
      s1 += vals[i];
    }
    const m = s1 / n;
    for (let i = 0; i < n; i++) {
      s2 += (vals[i] - m) ** 2;
      s3 += (vals[i] - m) ** 3;
    }
    const [em, ev] = averageVarianceMoments(V0, mu, xi, T);
    const sd = Math.sqrt(s2 / n);
    withinMC({ mean: m, se: sd / Math.sqrt(n) }, em, 4, 0, `E[V̄] μ=${mu}`);
    close(s2 / n / ev, 1, 0.05, `Var(V̄) μ=${mu}`);
  }
});

test('Hull-White (1987): ξ → 0 gir BSM, rekken mot betinget Monte Carlo E[BSM(V̄)]', () => {
  const p = { S: 100, X: 105, T: 0.5, r: 0.05, b: 0.03, v: 0.25 };
  close(hullWhite87({ ...p, type: 'call', xi: 1e-8 }).price, gbsm({ ...p, type: 'call' }), 1e-10, 'ξ → 0');
  const c = hullWhite87({ ...p, type: 'call', xi: 0.9 }).price;
  const pt = hullWhite87({ ...p, type: 'put', xi: 0.9 }).price;
  close(c - pt, parity(p), 1e-12, 'paritet');
  // Ukorrelert: prisen er E[BSM(σ² = V̄)] eksakt (Hull og White 1987).
  for (const [type, X, xi, mu] of [['call', 105, 0.6, 0], ['put', 90, 0.9, 0], ['call', 100, 0.7, 0.2]]) {
    const q = { ...p, X, type };
    const steps = 100;
    const dt = q.T / steps;
    const rng = createRng(23);
    const n = 20000;
    let s = 0;
    let s2 = 0;
    for (let i = 0; i < n; i++) {
      let V = q.v * q.v;
      let acc = 0.5 * V;
      for (let j = 1; j <= steps; j++) {
        V *= Math.exp((mu - 0.5 * xi * xi) * dt + xi * Math.sqrt(dt) * rng.normal());
        acc += j === steps ? 0.5 * V : V;
      }
      const y = gbsm({ ...q, v: Math.sqrt(acc * dt / q.T) });
      s += y;
      s2 += y * y;
    }
    const est = meanSe(s, s2, n);
    const hw = hullWhite87({ ...q, xi, mu });
    withinMC(est, hw.price, 4, 2e-3, `HW87 ${type} X=${X} ξ=${xi} μ=${mu}`);
    // Korreksjonen er tydelig større enn usikkerheten, så testen skiller rekken fra BSM.
    assert.ok(Math.abs(hw.price - hw.bs) > 6 * est.se, 'korreksjonen er målbar');
  }
});

// --- Hull og White (1988) -----------------------------------------------------------------------------
// Betinget Monte Carlo (Romano og Touzi 1997): gitt variansbanen er ln S_T normal med
// S' = S exp(ρ∫√V dW₂ − ½ρ²∫V dt) og varians (1 − ρ²)∫V dt.
// Antitetiske variansbaner (z og −z) og S' − S som kontrollvariat: S' = S exp(ρI₁ − ½ρ²I₂) har
// forventning nøyaktig S også i Euler-diskretiseringen (hvert steg er en eksponentiell martingal).
// Standardfeilen regnes over parene.
function conditionalSV({ type, S, X, T, r, b, V0, steps, n, seed, rho, stepV }) {
  const rng = createRng(seed);
  const dt = T / steps;
  const sq = Math.sqrt(dt);
  const ys = [];
  const cs = [];
  const sp = (I1, I2) => S * Math.exp(rho * I1 - 0.5 * rho * rho * I2);
  const price = (I1, I2) => gbsm({ type, S: sp(I1, I2), X, T, r, b, v: Math.sqrt((1 - rho * rho) * I2 / T) });
  const pairs = Math.floor(n / 2);
  for (let i = 0; i < pairs; i++) {
    let Va = V0;
    let Vb = V0;
    let Ia1 = 0;
    let Ia2 = 0;
    let Ib1 = 0;
    let Ib2 = 0;
    for (let j = 0; j < steps; j++) {
      const z = rng.normal();
      const pa = Math.max(Va, 0);
      const pb = Math.max(Vb, 0);
      Ia1 += Math.sqrt(pa) * sq * z;
      Ia2 += pa * dt;
      Ib1 -= Math.sqrt(pb) * sq * z;
      Ib2 += pb * dt;
      Va = stepV(Va, z, dt);
      Vb = stepV(Vb, -z, dt);
    }
    ys.push(0.5 * (price(Ia1, Ia2) + price(Ib1, Ib2)));
    cs.push(0.5 * (sp(Ia1, Ia2) + sp(Ib1, Ib2)) - S);
  }
  const my = ys.reduce((a, x) => a + x, 0) / pairs;
  const mc = cs.reduce((a, x) => a + x, 0) / pairs;
  let cov = 0;
  let vc = 0;
  for (let i = 0; i < pairs; i++) {
    cov += (ys[i] - my) * (cs[i] - mc);
    vc += (cs[i] - mc) ** 2;
  }
  const beta = vc > 0 ? cov / vc : 0;
  let v = 0;
  for (let i = 0; i < pairs; i++) v += (ys[i] - my - beta * (cs[i] - mc)) ** 2;
  return { mean: my - beta * mc, se: Math.sqrt(v / (pairs - 1) / pairs) };
}

test('Hull-White (1988): grensetilfeller', () => {
  const p = { S: 100, X: 110, T: 0.5, r: 0.05, b: 0.05, v: 0.2, vLR: 0.3, kappa: 2 };
  // ξ = 0: BSM med forventet gjennomsnittsvarians.
  const w = 0.09 * 0.5 + (0.04 - 0.09) * (1 - Math.exp(-1)) / 2;
  close(hullWhite88({ ...p, type: 'call', xi: 0, rho: -0.5 }).price, gbsm({ ...p, type: 'call', v: Math.sqrt(w / 0.5) }), 1e-12, 'ξ = 0');
  // ρ = 0, κ = 0: andreordensleddet er Hull-White (1987) til ledende orden, ½ c_VV · V²ξ²T/3.
  const q = { ...p, kappa: 0, rho: 0, xi: 0.3 };
  const h88 = hullWhite88({ ...q, type: 'call' });
  const tiny = hullWhite87({ ...q, type: 'call', xi: 1e-4 }); // andreordensleddet er ∝ ξ² for liten ξ
  close(h88.second / (tiny.second * (0.3 / 1e-4) ** 2), 1, 1e-6, 'ξ²-ledd mot HW87');
  close(h88.first, 0, 1e-15, 'ingen førsteordensledd uten korrelasjon');
  const c = hullWhite88({ ...p, type: 'call', xi: 0.5, rho: -0.6 }).price;
  const pt = hullWhite88({ ...p, type: 'put', xi: 0.5, rho: -0.6 }).price;
  close(c - pt, parity(p), 1e-12, 'paritet');
});

test('Hull-White (1988): rekken mot betinget Monte Carlo med korrelasjon', () => {
  const base = { S: 100, T: 0.5, r: 0.05, b: 0.05, v: 0.2, vLR: 0.25, kappa: 1.5 };
  for (const [type, X, xi, rho, big] of [
    ['call', 110, 0.4, -0.6, true], ['put', 90, 0.4, -0.6, true], ['call', 100, 0.3, 0.5, false], ['call', 110, 0.8, -0.6, true],
  ]) {
    const p = { ...base, type, X, xi, rho };
    const th = p.vLR * p.vLR;
    // Log-Euler for V: d ln V = (κ(θ − V)/V − ξ²/2)dt + ξ dW₂.
    const stepV = (V, z, dt) => V * Math.exp((p.kappa * (th - V) / V - 0.5 * xi * xi) * dt + xi * Math.sqrt(dt) * z);
    const est = conditionalSV({ type, S: p.S, X, T: p.T, r: p.r, b: p.b, V0: p.v * p.v, steps: 200, n: 20000, seed: 29, rho, stepV });
    const hw = hullWhite88(p);
    withinMC(est, hw.price, 4, 3e-3, `HW88 ${type} X=${X} ξ=${xi} ρ=${rho}`);
    if (big) assert.ok(Math.abs(hw.price - hw.bs) > 8 * est.se, `korreksjonen er målbar (${hw.price - hw.bs} mot SE ${est.se})`);
  }
});

// --- SABR ----------------------------------------------------------------------------------------
test('SABR: grensetilfeller og ATM-kontinuitet', () => {
  // β = 1, ν = 0: Black med volatilitet α.
  close(sabrVol({ F: 100, X: 120, T: 2, alpha: 0.3, beta: 1, rho: -0.5, nu: 0 }), 0.3, 1e-15, 'β = 1, ν = 0');
  // ATM: formelen er kontinuerlig i X = F.
  const atm = sabrVol({ F: 100, X: 100, T: 1, alpha: 2, beta: 0.5, rho: -0.4, nu: 0.4 });
  for (const eps of [1e-6, -1e-6, 1e-9]) {
    close(sabrVol({ F: 100, X: 100 * (1 + eps), T: 1, alpha: 2, beta: 0.5, rho: -0.4, nu: 0.4 }), atm, 1e-6, `ATM ${eps}`);
  }
  // ν = 0 er CEV-modellen dF = αF^β dW (CEV med β_CEV = 2β), der Hagans formel bare har liten asymptotisk feil.
  for (const beta of [0, 0.3, 0.5, 0.8]) {
    for (const X of [70, 100, 130]) {
      const alpha = 0.25 * 100 ** (1 - beta);
      const s = sabr({ type: 'call', S: 100, X, T: 1, r: 0.05, b: 0, alpha, beta, rho: 0.3, nu: 0 }).price;
      const c = cev({ type: 'call', S: 100, X, T: 1, r: 0.05, b: 0, v: alpha, beta: 2 * beta });
      close(s, c, 3e-4, `SABR(ν=0) mot CEV β=${beta} X=${X}`);
    }
  }
});

test('SABR mot Monte Carlo', () => {
  // β = 1: betinget på volatilitetsbanen er ln F_T normal (betinget MC, lav varians).
  {
    const p = { F: 100, T: 1, alpha: 0.25, rho: -0.5, nu: 0.4 };
    const steps = 200;
    const dt = p.T / steps;
    const rng = createRng(31);
    for (const X of [80, 100, 125]) {
      let s = 0;
      let s2 = 0;
      const n = 20000;
      for (let i = 0; i < n; i++) {
        let a = p.alpha;
        let I2 = 0;
        for (let j = 0; j < steps; j++) {
          const an = a * Math.exp(-0.5 * p.nu * p.nu * dt + p.nu * Math.sqrt(dt) * rng.normal());
          I2 += 0.5 * (a * a + an * an) * dt; // trapes for ∫α² dt
          a = an;
        }
        // dα = να dW₂ gir Itô-integralet eksakt: ∫α dW₂ = (α_T − α₀)/ν.
        const I1 = (a - p.alpha) / p.nu;
        const Fp = p.F * Math.exp(p.rho * I1 - 0.5 * p.rho * p.rho * I2);
        const y = gbsm({ type: 'call', S: Fp, X, T: p.T, r: 0, b: 0, v: Math.sqrt((1 - p.rho ** 2) * I2 / p.T) });
        s += y;
        s2 += y * y;
      }
      const est = meanSe(s, s2, n);
      const h = sabr({ type: 'call', S: p.F, X, T: p.T, r: 0, b: 0, alpha: p.alpha, beta: 1, rho: p.rho, nu: p.nu }).price;
      // Hagans formel er en asymptotisk tilnærming; tillater 0,5 % avvik i tillegg til MC-feilen.
      withinMC(est, h, 4, 0.005 * h, `SABR β=1 X=${X}`);
    }
  }
  // β = 0,5: full simulering av F (log-Euler) og α (eksakt).
  {
    const p = { F: 100, T: 0.5, alpha: 2, beta: 0.5, rho: -0.3, nu: 0.3 };
    const steps = 100;
    const dt = p.T / steps;
    const rng = createRng(37);
    const n = 100000;
    const pays = [90, 100, 110].map((X) => ({ X, s: 0, s2: 0 }));
    const c = Math.sqrt(1 - p.rho * p.rho);
    for (let i = 0; i < n; i++) {
      let a = p.alpha;
      let x = Math.log(p.F);
      for (let j = 0; j < steps; j++) {
        const z2 = rng.normal();
        const z1 = p.rho * z2 + c * rng.normal();
        const loc = a * Math.exp((p.beta - 1) * x);
        x += -0.5 * loc * loc * dt + loc * Math.sqrt(dt) * z1;
        a *= Math.exp(-0.5 * p.nu * p.nu * dt + p.nu * Math.sqrt(dt) * z2);
      }
      const FT = Math.exp(x);
      for (const q of pays) {
        const y = Math.max(FT - q.X, 0);
        q.s += y;
        q.s2 += y * y;
      }
    }
    for (const q of pays) {
      const h = sabr({ type: 'call', S: p.F, X: q.X, T: p.T, r: 0, b: 0, alpha: p.alpha, beta: p.beta, rho: p.rho, nu: p.nu }).price;
      withinMC(meanSe(q.s, q.s2, n), h, 4, 0.005 * h, `SABR β=0,5 X=${q.X}`);
    }
  }
});

// --- CEV -----------------------------------------------------------------------------------------
test('Ikke-sentral kjikvadrat for store parametre', () => {
  for (const [a, z] of [[200, 185], [450, 470], [3000, 2900], [2e4, 2.01e4]]) {
    close(gammaPRobust(a, z), gammaP(a, z), 1e-11, `P(${a}, ${z})`);
  }
  for (const [x, k, l] of [[5, 3, 2], [91, 4, 91], [300, 20, 250], [1000, 2.5, 950], [0.5, 0.7, 3], [8900, 22, 8914]]) {
    close(ncx2cdfLarge(x, k, l), ncx2cdf(x, k, l), 1e-11, `χ'²(${x}; ${k}, ${l})`);
  }
  // Svært stor ikke-sentralitet: sammenlign med normaltilnærmingen til Poisson-blandingen via
  // E = k + λ og Var = 2(k + 2λ) (gyldig når begge er store; skjevheten er liten).
  const k = 2002;
  const l = 4e6;
  const m = k + l;
  const sd = Math.sqrt(2 * (k + 2 * l));
  close(ncx2cdfLarge(m + sd, k, l), cnd(1), 2e-3, 'stor λ, +1 sd');
  close(ncx2cdfLarge(m, k, l), 0.5, 2e-3, 'stor λ, median');
});

test('CEV: β = 2 gir BSM, kontinuitet nær 2 og put-call-paritet', () => {
  const p = { S: 100, X: 100, T: 0.5, r: 0.1, b: 0.1 };
  close(cev({ ...p, type: 'call', v: 0.3, beta: 2 }), gbsm({ ...p, type: 'call', v: 0.3 }), 1e-15, 'β = 2');
  for (const beta of [1.9, 1.99, 1.999, 1.9999, 2.0001, 2.001, 2.01, 2.1]) {
    // Lokal volatilitet ved S holdes lik 30 %: prisen nærmer seg BSM når β → 2.
    const v = 0.3 * 100 ** (1 - beta / 2);
    close(cev({ ...p, type: 'call', v, beta }), gbsm({ ...p, type: 'call', v: 0.3 }), 2e-4 * Math.max(Math.abs(2 - beta) * 100, 0.05), `β=${beta}`);
  }
  for (const beta of [0, 0.5, 1, 1.5, 1.9]) {
    for (const X of [70, 100, 140]) {
      const q = { ...p, X, v: 0.3 * 100 ** (1 - beta / 2), beta };
      close(cev({ ...q, type: 'call' }) - cev({ ...q, type: 'put' }), parity(q), 1e-11, `paritet β=${beta} X=${X}`);
    }
  }
  // β > 2: prisprosessen er en strengt lokal martingal, E[S_T] < S e^{bT}. Put-formelen er forventet
  // utbetaling, så for stor X er p ≈ X e^{−rT} − e^{−rT}E[S_T].
  const q = { ...p, v: 0.3 / 10, beta: 3, T: 2 };
  const ES = cevExpectedSpot(q);
  assert.ok(ES < q.S * Math.exp(q.b * q.T), 'E[S_T] < S e^{bT}');
  const Xbig = 1e7;
  close((Xbig * Math.exp(-q.r * q.T) - cev({ ...q, X: Xbig, type: 'put' })) * Math.exp(q.r * q.T), ES, 1e-5, 'E[S_T] fra put med stor X');
});

test('CEV mot eksakt simulering (β = 1, med absorpsjon i null)', () => {
  // β = 1: Y_t = e^{−bt}S_t er en tidsskiftet BESQ(0): S_T = e^{bT}·2τ·Gamma(N), N ~ Poisson(S/(2τ)),
  // τ = σ²(1 − e^{−bT})/(4b). N = 0 betyr at kursen er absorbert i null.
  for (const [S, X, v, T, b, r] of [[100, 100, 3, 0.5, 0.1, 0.1], [100, 90, 12, 1, 0.05, 0.05], [100, 120, 6, 2, -0.02, 0.03]]) {
    const tau = v * v * (1 - Math.exp(-b * T)) / (4 * b);
    const sample = (rng) => {
      const N = poisson(rng, S / (2 * tau));
      return N === 0 ? 0 : Math.exp(b * T) * 2 * tau * gammaVariate(rng, N);
    };
    for (const type of ['call', 'put']) {
      const est = mcPrice({ n: 300000, seed: 41, r, T, sampleST: sample, payoff: type === 'call' ? callPay(X) : putPay(X) });
      withinMC(est, cev({ type, S, X, T, r, b, v, beta: 1 }), 4, 0, `CEV β=1 ${type} σ=${v}`);
    }
  }
});

test('CEV mot Euler-simulering (β = 0,5, 1,5 og 3)', () => {
  // Log-Euler: d ln S = (b − ½σ²S^{β−2})dt + σS^{β/2−1} dW. Lokal volatilitet 30 % ved S.
  for (const [beta, types] of [[0.5, ['call', 'put']], [1.5, ['call', 'put']], [3, ['put']]]) {
    const p = { S: 100, X: 95, T: 0.5, r: 0.05, b: 0.03, v: 0.3 * 100 ** (1 - beta / 2) };
    const steps = 250;
    const dt = p.T / steps;
    const rng = createRng(43);
    const n = 60000;
    const acc = { call: [0, 0], put: [0, 0] };
    for (let i = 0; i < n; i++) {
      let x1 = Math.log(p.S);
      let x2 = x1;
      for (let j = 0; j < steps; j++) {
        const z = rng.normal();
        const l1 = p.v * Math.exp((beta / 2 - 1) * x1);
        const l2 = p.v * Math.exp((beta / 2 - 1) * x2);
        x1 += (p.b - 0.5 * l1 * l1) * dt + l1 * Math.sqrt(dt) * z;
        x2 += (p.b - 0.5 * l2 * l2) * dt - l2 * Math.sqrt(dt) * z;
      }
      const s1 = Math.exp(x1);
      const s2 = Math.exp(x2);
      const c = 0.5 * (Math.max(s1 - p.X, 0) + Math.max(s2 - p.X, 0));
      const pp = 0.5 * (Math.max(p.X - s1, 0) + Math.max(p.X - s2, 0));
      acc.call[0] += c;
      acc.call[1] += c * c;
      acc.put[0] += pp;
      acc.put[1] += pp * pp;
    }
    const df = Math.exp(-p.r * p.T);
    for (const type of types) {
      const { mean, se } = meanSe(acc[type][0], acc[type][1], n);
      withinMC({ mean: mean * df, se: se * df }, cev({ ...p, type, beta }), 4, 3e-3, `CEV β=${beta} ${type}`);
    }
  }
});

// --- Fortrengt diffusjon -----------------------------------------------------------------------------
test('Fortrengt diffusjon: a = 1 gir BSM, paritet og eksakt simulering', () => {
  const p = { S: 100, X: 95, T: 0.5, r: 0.05, b: 0.02, v: 0.3 };
  close(displacedDiffusion({ ...p, type: 'call', a: 1 }), gbsm({ ...p, type: 'call' }), 1e-15, 'a = 1');
  for (const a of [0.3, 0.6, 0.9]) {
    const c = displacedDiffusion({ ...p, type: 'call', a });
    const pt = displacedDiffusion({ ...p, type: 'put', a });
    close(c - pt, parity(p), 1e-12, `paritet a=${a}`);
    const F = p.S * Math.exp(p.b * p.T);
    for (const [type, pay] of [['call', callPay(p.X)], ['put', putPay(p.X)]]) {
      const est = mcPrice({
        n: 200000, seed: 47, r: p.r, T: p.T, payoff: pay,
        sampleST: (rng) => a * F * Math.exp(-0.5 * p.v * p.v * p.T + p.v * Math.sqrt(p.T) * rng.normal()) + (1 - a) * F,
      });
      withinMC(est, type === 'call' ? c : pt, 4, 0, `fortrengt ${type} a=${a}`);
    }
  }
  // Når X ≤ (1 − a)F er call alltid i pengene.
  const q = { ...p, X: 30, a: 0.5 };
  close(displacedDiffusion({ ...q, type: 'call' }), parity(q), 1e-12, 'alltid i pengene');
  close(displacedDiffusion({ ...q, type: 'put' }), 0, 0, 'put verdiløs');
});

// --- Heston (1993) ------------------------------------------------------------------------------------
test('Heston: litteraturverdi, grensetilfeller og paritet', () => {
  // Andersen (2008), case I: κ = 0,5, θ = v₀ = 0,04, σ_v = 1, ρ = −0,9, T = 10, S = X = 100, r = 0.
  close(heston({ type: 'call', S: 100, X: 100, T: 10, r: 0, b: 0, v0: 0.04, kappa: 0.5, theta: 0.04, sigma: 1, rho: -0.9 }), 13.0847, 1e-3, 'Andersen case I');
  const p = { S: 100, X: 110, T: 0.5, r: 0.03, b: 0.01, v0: 0.04, kappa: 2, theta: 0.06, rho: -0.7 };
  const vbar = hestonExpectedVariance(p);
  close(heston({ ...p, type: 'call', sigma: 1e-5 }), gbsm({ ...p, type: 'call', v: Math.sqrt(vbar) }), 1e-4, 'σ_v → 0');
  for (const X of [60, 100, 160]) {
    const c = heston({ ...p, X, type: 'call', sigma: 0.5 });
    const pt = heston({ ...p, X, type: 'put', sigma: 0.5 });
    close(c - pt, parity({ ...p, X }), 1e-11, `paritet X=${X}`);
    assert.ok(c > 0 && pt > 0, 'positive priser');
  }
});

test('Heston mot betinget Monte Carlo (full truncation Euler)', () => {
  const base = { S: 100, T: 0.5, r: 0.03, b: 0.03, v0: 0.04, kappa: 2, theta: 0.05, sigma: 0.3 };
  for (const [type, X, rho] of [['call', 110, -0.7], ['put', 90, -0.7], ['call', 100, 0.3]]) {
    const p = { ...base, type, X, rho };
    const stepV = (V, z, dt) => {
      const Vp = Math.max(V, 0);
      return V + p.kappa * (p.theta - Vp) * dt + p.sigma * Math.sqrt(Vp * dt) * z;
    };
    const est = conditionalSV({ type, S: p.S, X, T: p.T, r: p.r, b: p.b, V0: p.v0, steps: 200, n: 20000, seed: 53, rho, stepV });
    const h = heston(p);
    withinMC(est, h, 4, 2e-3, `Heston ${type} X=${X} ρ=${rho}`);
    const bs = gbsm({ ...p, v: Math.sqrt(hestonExpectedVariance(p)) });
    assert.ok(Math.abs(h - bs) > 8 * est.se, `stokastisk volatilitet gir målbart avvik fra BSM (${h - bs} mot SE ${est.se})`);
  }
});
