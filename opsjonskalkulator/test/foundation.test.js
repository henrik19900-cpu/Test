import test from 'node:test';
import assert from 'node:assert/strict';
import { cnd, nd, cndInv, cbnd } from '../src/math/normal.js';
import { brent, bisection } from '../src/math/solvers.js';
import { gaussLegendre, gaussLegendreComposite, adaptiveSimpson } from '../src/math/integrate.js';
import { lnGamma, gammaP, gammaQ, ncx2cdf } from '../src/math/special.js';
import { createRng, halton } from '../src/math/rng.js';
import {
  gbsm, gbsmGreeks, impliedVolGBSM, strikeFromDelta, probabilityOfEverInTheMoney, bachelier,
} from '../src/models/bsm.js';
import { close, withinMC, mcTerminal, bridgeHitProb } from './helpers.js';

test('N(x) mot kjente verdier', () => {
  close(cnd(0), 0.5, 1e-15);
  close(cnd(1.96), 0.9750021048517795, 1e-14);
  close(cnd(-1), 0.15865525393145707, 1e-14);
  close(cnd(3), 0.9986501019683699, 1e-14);
  // Hart-algoritmen (som boka bruker) har full absolutt presisjon; i dype haler er relativ presisjon ~1e-9.
  close(cnd(-6), 9.865876450377012e-10, 1e-17);
  close(cnd(-10), 7.619853024160593e-24, 1e-30);
  close(nd(0), 1 / Math.sqrt(2 * Math.PI), 1e-16);
});

test('N⁻¹(p) er invers av N(x)', () => {
  for (const p of [1e-12, 1e-8, 1e-4, 0.01, 0.02425, 0.3, 0.5, 0.77, 0.975, 0.99, 1 - 1e-6]) {
    const x = cndInv(p);
    close(cnd(x) / p, 1, 1e-12, `p=${p}`);
  }
  close(cndInv(0.975), 1.959963984540054, 1e-12);
});

test('M(a,b;ρ) mot spesialtilfeller og numerisk integrasjon', () => {
  close(cbnd(0, 0, 0.5), 0.25 + Math.asin(0.5) / (2 * Math.PI), 1e-14);
  close(cbnd(0.3, -0.7, 0), cnd(0.3) * cnd(-0.7), 1e-15);
  close(cbnd(0.3, -0.7, 1), cnd(-0.7), 1e-15);
  close(cbnd(0.3, 0.7, -1), cnd(0.3) + cnd(0.7) - 1, 1e-15);
  const exact = (a, b, rho) => {
    const s = Math.sqrt(1 - rho * rho);
    return gaussLegendreComposite((x) => nd(x) * cnd((b - rho * x) / s), -12, a, 400, 20);
  };
  for (const rho of [-0.999, -0.95, -0.8, -0.5, -0.2, 0.1, 0.3, 0.6, 0.9, 0.93, 0.99]) {
    for (const [a, b] of [[-2, -1], [-0.5, 0.4], [0, 0], [1.2, -0.3], [2.5, 1.5], [-3, 2], [0.7, 0.7]]) {
      close(cbnd(a, b, rho), exact(a, b, rho), 2e-10, `a=${a} b=${b} rho=${rho}`);
    }
  }
});

test('Løsere og integrasjon', () => {
  const f = (x) => x ** 3 - 2 * x - 5;
  close(brent(f, 2, 3), 2.0945514815423265, 1e-12);
  close(bisection(f, 2, 3), 2.0945514815423265, 1e-10);
  close(gaussLegendre((x) => x ** 5, 0, 1, 8), 1 / 6, 1e-15);
  close(adaptiveSimpson(Math.sin, 0, Math.PI), 2, 1e-10);
});

test('Gamma og ikke-sentral kjikvadrat', () => {
  close(Math.exp(lnGamma(5)), 24, 1e-10);
  close(Math.exp(lnGamma(0.5)), Math.sqrt(Math.PI), 1e-12);
  close(gammaP(1, 2.3), 1 - Math.exp(-2.3), 1e-14);
  let sumK = 0;
  let term = 1;
  for (let k = 0; k < 7; k++) {
    sumK += term;
    term *= 30 / (k + 1);
  }
  close(gammaQ(7, 30) / (Math.exp(-30) * sumK), 1, 1e-13);
  close(gammaP(7, 4.2), 1 - Math.exp(-4.2) * [0, 1, 2, 3, 4, 5, 6].reduce((acc, k) => acc + 4.2 ** k / [1, 1, 2, 6, 24, 120, 720][k], 0), 1e-14);
  close(gammaP(0.5, 1.7), 2 * cnd(Math.sqrt(3.4)) - 1, 1e-14);
  // MC: χ'²(k=3, λ=2) = (Z1+√2)² + Z2² + Z3²
  const rng = createRng(7);
  const n = 400000;
  let hits = 0;
  for (let i = 0; i < n; i++) {
    const a = rng.normal() + Math.SQRT2;
    const b = rng.normal();
    const c = rng.normal();
    if (a * a + b * b + c * c <= 5) hits++;
  }
  const pHat = hits / n;
  const se = Math.sqrt(pHat * (1 - pHat) / n);
  withinMC({ mean: pHat, se }, ncx2cdf(5, 3, 2), 4);
  close(ncx2cdf(5, 3, 0), gammaP(1.5, 2.5), 1e-14);
});

test('RNG og Halton', () => {
  const rng = createRng(42);
  let s = 0;
  let s2 = 0;
  const n = 200000;
  for (let i = 0; i < n; i++) {
    const z = rng.normal();
    s += z;
    s2 += z * z;
  }
  assert.ok(Math.abs(s / n) < 0.01);
  assert.ok(Math.abs(s2 / n - 1) < 0.01);
  close(halton(1, 2), 0.5, 1e-15);
  close(halton(3, 3), 1 / 9, 1e-15);
});

const H = (type, S, X, T, r, b, v) => ({ type, S, X, T, r, b, v });

test('GBSM: bokas eksempler', () => {
  close(gbsm(H('call', 60, 65, 0.25, 0.08, 0.08, 0.3)), 2.1334);
  close(gbsm(H('put', 100, 95, 0.5, 0.1, 0.05, 0.2)), 2.4648);
  close(gbsm(H('put', 19, 19, 0.75, 0.1, 0, 0.28)), 1.7011);
  close(gbsm(H('call', 19, 19, 0.75, 0.1, 0, 0.28)), 1.7011);
  close(gbsm(H('call', 1.56, 1.6, 0.5, 0.06, -0.02, 0.12)), 0.0291);
  close(gbsm(H('put', 75, 70, 0.5, 0.1, 0.05, 0.35)), 4.087);
});

test('GBSM: et utvalg europeiske verdier med b = 0 fra boka', () => {
  // Noen få punkter fra bokas sammenligningstabell for amerikanske opsjoner (X = 100, r = 0,10).
  const points = [
    ['call', 90, 0.1, 0.15, 0.0205],
    ['call', 110, 0.5, 0.35, 15.3086],
    ['put', 100, 0.1, 0.25, 3.1217],
    ['put', 90, 0.5, 0.25, 12.2149],
  ];
  for (const [type, S, T, v, expected] of points) {
    close(gbsm(H(type, S, 100, T, 0.1, 0, v)), expected, 1e-4, `${type} S=${S} T=${T} v=${v}`);
  }
});

test('Greeks: bokas eksempler', () => {
  close(gbsmGreeks(H('call', 105, 100, 0.5, 0.1, 0, 0.36)).delta, 0.5946);
  close(gbsmGreeks(H('put', 105, 100, 0.5, 0.1, 0, 0.36)).delta, -0.3566);
  close(gbsmGreeks(H('put', 105, 100, 0.5, 0.1, 0, 0.36)).elasticity, -4.8775);
  close(gbsmGreeks(H('call', 55, 60, 0.75, 0.1, 0.1, 0.3)).gamma, 0.0278);
  close(gbsmGreeks(H('call', 55, 60, 0.75, 0.1, 0.1, 0.3)).vega, 18.9358);
  close(gbsmGreeks(H('put', 430, 405, 1 / 12, 0.07, 0.02, 0.2)).theta, -31.1924);
  close(gbsmGreeks(H('put', 430, 405, 1 / 12, 0.07, 0.02, 0.2)).thetaDay, -0.0855);
  close(gbsmGreeks(H('call', 72, 75, 1, 0.09, 0.09, 0.19)).rho, 38.7325);
  close(gbsmGreeks(H('put', 500, 490, 0.25, 0.08, 0.03, 0.15)).phi, 42.2254);
});

test('Greeks: analytiske mot numeriske derivater', () => {
  const cases = [
    H('call', 105, 100, 0.5, 0.1, 0, 0.36), H('put', 105, 100, 0.5, 0.1, 0, 0.36),
    H('call', 90, 110, 1.3, 0.05, 0.02, 0.25), H('put', 120, 95, 0.4, 0.03, -0.04, 0.45),
  ];
  for (const p of cases) {
    const g = gbsmGreeks(p);
    const at = (o) => gbsmGreeks({ ...p, ...o });
    const tag = `${p.type} S=${p.S} X=${p.X}`;
    const hS = p.S * 1e-4;
    const hv = 1e-5;
    const hT = 1e-5;
    const hr = 1e-6;
    const dS = (f) => (f(at({ S: p.S + hS })) - f(at({ S: p.S - hS }))) / (2 * hS);
    const dv = (f) => (f(at({ v: p.v + hv })) - f(at({ v: p.v - hv }))) / (2 * hv);
    const dt = (f) => -(f(at({ T: p.T + hT })) - f(at({ T: p.T - hT }))) / (2 * hT);
    const rel = (a, e, msg) => close(a, e, 1e-5 * Math.max(1, Math.abs(e)), `${tag} ${msg}`);
    rel(g.delta, dS((x) => x.price), 'delta');
    rel(g.gamma, dS((x) => x.delta), 'gamma');
    rel(g.speed, dS((x) => x.gamma), 'speed');
    rel(g.speedP, dS((x) => x.gammaP), 'speedP');
    rel(g.vega, dv((x) => x.price), 'vega');
    rel(g.vanna, dv((x) => x.delta), 'vanna');
    rel(g.dvannaDvol, dv((x) => x.vanna), 'dvannaDvol');
    rel(g.zomma, dv((x) => x.gamma), 'zomma');
    rel(g.zommaP, dv((x) => x.gammaP), 'zommaP');
    rel(g.vomma, dv((x) => x.vega), 'vomma');
    rel(g.vommaP, p.v / 10 * g.vomma, 'vommaP');
    rel(g.ultima, dv((x) => x.vomma), 'ultima');
    rel(g.theta, dt((x) => x.price), 'theta');
    rel(g.charm, dt((x) => x.delta), 'charm');
    rel(g.color, dt((x) => x.gamma), 'color');
    rel(g.colorP, dt((x) => x.gammaP), 'colorP');
    rel(g.veta, dt((x) => x.vega), 'veta');
    rel(g.dzetaDvol, dv((x) => x.itmProb), 'dzetaDvol');
    rel(g.dzetaDtime, dt((x) => x.itmProb), 'dzetaDtime');
    rel(g.rho, (at({ r: p.r + hr, b: p.b + hr }).price - at({ r: p.r - hr, b: p.b - hr }).price) / (2 * hr), 'rho');
    rel(g.carryRho, (at({ b: p.b + hr }).price - at({ b: p.b - hr }).price) / (2 * hr), 'carry rho');
    rel(g.futuresRho, (at({ r: p.r + hr }).price - at({ r: p.r - hr }).price) / (2 * hr), 'futures rho');
    const hX = p.X * 1e-4;
    rel(g.strikeDelta, (at({ X: p.X + hX }).price - at({ X: p.X - hX }).price) / (2 * hX), 'strike delta');
    rel(g.rnd, (at({ X: p.X + hX }).price - 2 * g.price + at({ X: p.X - hX }).price) / (hX * hX), 'risikonøytral tetthet');
    // Variansgreeks: deriver med hensyn på w = σ².
    const hw = 1e-6;
    const w = p.v * p.v;
    const atW = (ww) => at({ v: Math.sqrt(ww) });
    rel(g.varianceVega, (atW(w + hw).price - atW(w - hw).price) / (2 * hw), 'variansvega');
    rel(g.ddeltaDvar, (atW(w + hw).delta - atW(w - hw).delta) / (2 * hw), 'dDelta/dvar');
    rel(g.varianceVomma, (atW(w + hw).varianceVega - atW(w - hw).varianceVega) / (2 * hw), 'variansvomma');
    rel(g.varianceUltima, (atW(w + hw).varianceVomma - atW(w - hw).varianceVomma) / (2 * hw), 'variansultima');
  }
});

test('Implisitt volatilitet og strike fra delta går tur-retur', () => {
  for (const p of [H('call', 59, 60, 0.25, 0.067, 0.067, 0.25), H('put', 100, 130, 2, 0.03, 0, 0.6), H('call', 100, 90, 0.1, 0.05, 0.05, 0.25)]) {
    const price = gbsm(p);
    close(impliedVolGBSM({ ...p, price }), p.v, 1e-8, `${p.type} X=${p.X}`);
  }
  assert.throws(() => impliedVolGBSM({ type: 'call', S: 100, X: 100, T: 1, r: 0.05, b: 0.05, price: 120 }));
  for (const [type, delta] of [['call', 0.25], ['put', -0.25], ['call', 0.8]]) {
    const K = strikeFromDelta({ type, S: 1.35, T: 0.5, r: 0.05, b: 0.02, v: 0.1, delta });
    close(gbsmGreeks({ type, S: 1.35, X: K, T: 0.5, r: 0.05, b: 0.02, v: 0.1 }).delta, delta, 1e-12);
  }
});

test('Sannsynlighet for å komme i pengene før forfall (MC med brownsk bro)', () => {
  for (const [type, S, X] of [['call', 100, 115], ['put', 100, 88]]) {
    const T = 0.75;
    const b = 0.03;
    const v = 0.3;
    const steps = 50;
    const dt = T / steps;
    const rng = createRng(11);
    const n = 40000;
    let sum = 0;
    let sumSq = 0;
    const lnX = Math.log(X);
    for (let i = 0; i < n; i++) {
      let x = Math.log(S);
      let survive = 1;
      for (let j = 0; j < steps; j++) {
        const nx = x + (b - 0.5 * v * v) * dt + v * Math.sqrt(dt) * rng.normal();
        survive *= 1 - bridgeHitProb(x, nx, lnX, v, dt);
        x = nx;
      }
      const hit = 1 - survive;
      sum += hit;
      sumSq += hit * hit;
    }
    const mean = sum / n;
    const se = Math.sqrt((sumSq / n - mean * mean) / n);
    withinMC({ mean, se }, probabilityOfEverInTheMoney({ type, S, X, T, b, v }), 4, 0, type);
  }
});

test('Bachelier mot MC', () => {
  const p = { type: 'call', S: 100, X: 105, T: 0.5, r: 0.03, b: 0.01, v: 18 };
  const rng = createRng(3);
  const F = p.S * Math.exp(p.b * p.T);
  let sum = 0;
  let sumSq = 0;
  const n = 400000;
  for (let i = 0; i < n; i++) {
    const y = Math.max(F + p.v * Math.sqrt(p.T) * rng.normal() - p.X, 0) * Math.exp(-p.r * p.T);
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / n;
  withinMC({ mean, se: Math.sqrt((sumSq / n - mean * mean) / n) }, bachelier(p));
});

test('GBSM mot MC (kontroll av testmotoren)', () => {
  const p = H('call', 100, 110, 0.8, 0.05, 0.02, 0.3);
  withinMC(mcTerminal({ ...p, payoff: (ST) => Math.max(ST - p.X, 0) }), gbsm(p));
});
