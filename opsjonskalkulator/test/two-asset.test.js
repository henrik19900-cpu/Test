// Kapittel 5: eksotiske opsjoner på to underliggende.
// Hver formel kontrolleres mot bokas tall (der de er kjent), en uavhengig numerisk metode
// (Monte Carlo, brownsk bro for barrierer, binomialtrær, numerisk integrasjon) og strukturelle identiteter.
import test from 'node:test';
import assert from 'node:assert/strict';
import { close, withinMC, mcTwoAssets, mcTwoAssetPaths, bridgeHitProb } from './helpers.js';
import { cnd } from '../src/math/normal.js';
import { createRng } from '../src/math/rng.js';
import { gaussLegendreComposite } from '../src/math/integrate.js';
import { brent } from '../src/math/solvers.js';
import { gbsm } from '../src/models/bsm.js';
import * as M from '../src/models/two-asset.js';
import catalog from '../src/catalog/ch05-two-asset.js';
import { defaultParams } from '../src/catalog/params.js';

const vanilla = (type, S, X, T, r, b, v) => gbsm({ type, S, X, T, r, b, v });
const BASE = { S1: 100, S2: 95, T: 0.75, r: 0.05, b1: 0.02, b2: 0.04, v1: 0.25, v2: 0.35, rho: 0.4 };

// --- Hjelpere ------------------------------------------------------------------------

// Rabatt for standard barriereopsjoner (Reiner og Rubinstein 1991): inn-opsjoner får K ved T hvis
// barrieren aldri treffes, ut-opsjoner får K når barrieren treffes.
function rebate(kind, S, H, K, T, r, b, v) {
  const eta = kind.startsWith('down') ? 1 : -1;
  const vst = v * Math.sqrt(T);
  const mu = (b - v * v / 2) / (v * v);
  const lam = Math.sqrt(mu * mu + 2 * r / (v * v));
  const x2 = Math.log(S / H) / vst + (1 + mu) * vst;
  const y2 = Math.log(H / S) / vst + (1 + mu) * vst;
  const z = Math.log(H / S) / vst + lam * vst;
  if (kind.endsWith('in')) {
    return K * Math.exp(-r * T) * (cnd(eta * (x2 - vst)) - (H / S) ** (2 * mu) * cnd(eta * (y2 - vst)));
  }
  return K * ((H / S) ** (mu + lam) * cnd(eta * z) + (H / S) ** (mu - lam) * cnd(eta * z - 2 * eta * lam * vst));
}

// Cox-Ross-Rubinstein for amerikanske opsjoner; snitt av n og n + 1 steg demper oscillasjonene.
function crr({ type, S, X, T, r, b, v }, n = 2000) {
  const one = (m) => {
    const dt = T / m;
    const u = Math.exp(v * Math.sqrt(dt));
    const d = 1 / u;
    const p = (Math.exp(b * dt) - d) / (u - d);
    const disc = Math.exp(-r * dt);
    const pay = (s) => Math.max(type === 'call' ? s - X : X - s, 0);
    const V = new Float64Array(m + 1);
    for (let i = 0; i <= m; i++) V[i] = pay(S * u ** (2 * i - m));
    for (let k = m - 1; k >= 0; k--) {
      for (let i = 0; i <= k; i++) V[i] = Math.max(disc * (p * V[i + 1] + (1 - p) * V[i]), pay(S * u ** (2 * i - k)));
    }
    return V[0];
  };
  return 0.5 * (one(n) + one(n + 1));
}

// Todimensjonalt binomialtre (Rubinstein 1994) for bytteopsjonen max(Q1·S1 − Q2·S2, 0).
function tree2D({ S1, S2, Q1 = 1, Q2 = 1, T, r, b1, b2, v1, v2, rho, american }, n = 200) {
  const dt = T / n;
  const sq = Math.sqrt(dt);
  const nu1 = b1 - 0.5 * v1 * v1;
  const nu2 = b2 - 0.5 * v2 * v2;
  const c = Math.sqrt(1 - rho * rho);
  const disc = Math.exp(-r * dt) / 4;
  const pay = (k, i, j) => Math.max(
    Q1 * S1 * Math.exp(k * nu1 * dt + v1 * sq * (2 * i - k))
    - Q2 * S2 * Math.exp(k * nu2 * dt + v2 * sq * (rho * (2 * i - k) + c * (2 * j - k))), 0);
  let V = new Float64Array((n + 1) * (n + 1));
  for (let i = 0; i <= n; i++) for (let j = 0; j <= n; j++) V[i * (n + 1) + j] = pay(n, i, j);
  for (let k = n - 1; k >= 0; k--) {
    const W = new Float64Array((k + 1) * (k + 1));
    const s = k + 2;
    for (let i = 0; i <= k; i++) {
      for (let j = 0; j <= k; j++) {
        const cont = disc * (V[(i + 1) * s + j + 1] + V[(i + 1) * s + j] + V[i * s + j + 1] + V[i * s + j]);
        W[i * (k + 1) + j] = american ? Math.max(cont, pay(k, i, j)) : cont;
      }
    }
    V = W;
  }
  return V[0];
}

// Sannsynligheten for at en GBM (carry b, vol v) ikke treffer H før tiden t.
function survivalProb(S, H, t, b, v) {
  const mu = b - v * v / 2;
  const vst = v * Math.sqrt(t);
  const h = Math.log(H / S);
  if (H < S) return cnd((-h + mu * t) / vst) - Math.exp(2 * mu * h / (v * v)) * cnd((h + mu * t) / vst);
  return cnd((h - mu * t) / vst) - Math.exp(2 * mu * h / (v * v)) * cnd((-h - mu * t) / vst);
}

// MC for to-aktiva-barrierer: barrieren på S2 overvåkes kontinuerlig til t1 via brownsk bro.
function mcTwoAssetBarrier(p, { steps = 20, n = 40000, seed = 7 } = {}) {
  const { type, kind, X, H, T } = p;
  const t1 = p.t1 ?? T;
  const dt = T / steps;
  const m = Math.round(t1 / dt);
  assert.ok(Math.abs(m * dt - t1) < 1e-12, 't1 må ligge i tidsgitteret');
  const lh = Math.log(H);
  const out = kind.endsWith('out');
  return mcTwoAssetPaths({
    ...p, steps, n, seed,
    payoff: (a, b) => {
      let surv = 1;
      for (let j = 0; j < m; j++) surv *= 1 - bridgeHitProb(Math.log(b[j]), Math.log(b[j + 1]), lh, p.v2, dt);
      const pay = Math.max(type === 'call' ? a[steps] - X : X - a[steps], 0);
      return pay * (out ? surv : 1 - surv);
    },
  });
}

const KINDS = ['down-out', 'up-out', 'down-in', 'up-in'];
const npdf = (z) => Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI);

// Uavhengig beregning av to-aktiva-barrierer ved numerisk integrasjon: speilingsprinsippet gir
// tettheten til x = ln(S2(t1)/S2) for stier som ikke har truffet H, og gitt W2(t1) er ln S1(T)
// normalfordelt, så den indre forventningen er en Black-Scholes-formel. Ingen bivariat normal.
function barrierByIntegration({ type, kind, S1, S2, X, H, T, t1 = T, r, b1, b2, v1, v2, rho }) {
  const down = kind.startsWith('down');
  const mu1 = b1 - v1 * v1 / 2;
  const mu2 = b2 - v2 * v2 / 2;
  const h = Math.log(H / S2);
  const sd = v2 * Math.sqrt(t1);
  const s = v1 * Math.sqrt(T - rho * rho * t1);
  const img = Math.exp(2 * mu2 * h / (v2 * v2));
  const f = (x) => {
    const q = (npdf((x - mu2 * t1) / sd) - img * npdf((x - 2 * h - mu2 * t1) / sd)) / sd;
    const m = Math.log(S1) + mu1 * T + v1 * rho * (x - mu2 * t1) / v2;
    const d = (m - Math.log(X) + s * s) / s;
    const fwd = Math.exp(m + s * s / 2);
    return q * (type === 'call' ? fwd * cnd(d) - X * cnd(d - s) : X * cnd(s - d) - fwd * cnd(-d));
  };
  const span = 12 * sd + Math.abs(mu2) * t1;
  const out = Math.exp(-r * T) * (down ? gaussLegendreComposite(f, h, h + span, 60, 20) : gaussLegendreComposite(f, h - span, h, 60, 20));
  return kind.endsWith('out') ? out : vanilla(type, S1, X, T, r, b1, v1) - out;
}

// --- Bokas eksempler ------------------------------------------------------------------------

test('Bokas eksempler: korrelasjonsopsjon, produktopsjon og Kirk', () => {
  close(M.twoAssetCorrelation({ type: 'call', S1: 52, S2: 65, X1: 50, X2: 70, T: 0.5, r: 0.1, b1: 0.1, b2: 0.1, v1: 0.2, v2: 0.3, rho: 0.75 }), 4.7073, 1e-4);
  const prod = { type: 'call', S1: 100, S2: 105, X: 15000, T: 0.1, r: 0.07, b1: 0.02, b2: 0.05 };
  close(M.productOption({ ...prod, v1: 0.2, v2: 0.3, rho: -0.5 }).price, 0.0028, 1e-4);
  close(M.productOption({ ...prod, v1: 0.3, v2: 0.3, rho: 0 }).price, 2.4026, 1e-4);
  close(M.kirkSpread({ type: 'call', S1: 28, S2: 20, X: 7, T: 0.25, r: 0.05, b1: 0, b2: 0, v1: 0.29, v2: 0.36, rho: 0.42 }).price, 2.167, 1e-4);
  const kirk = { type: 'call', S1: 122, S2: 120, X: 3, T: 0.1, r: 0.1, b1: 0, b2: 0, v1: 0.2, v2: 0.2 };
  close(M.kirkSpread({ ...kirk, rho: -0.5 }).price, 4.753, 1e-4);
  close(M.kirkSpread({ ...kirk, rho: 0 }).price, 3.797, 1e-4);
  close(M.kirkSpread({ ...kirk, rho: 0.5 }).price, 2.5537, 1e-4);
});

test('Standard barriere-motoren (brukes av Margrabe-barrieren) mot Haugs barrieretabell', () => {
  // S = 100, T = 0,5, r = 0,08, b = 0,04, σ = 0,25, rabatt 3; X = 90, 100, 110.
  const book = {
    'call down-out 95': [9.0246, 6.7924, 4.8759], 'call up-out 105': [2.6789, 2.358, 2.3453],
    'call down-in 95': [7.7627, 4.0109, 2.0576], 'call up-in 105': [14.1112, 8.4482, 4.591],
    'put down-in 95': [2.9586, 6.5677, 11.9752], 'put up-in 105': [1.4653, 3.3721, 7.0846],
    'put down-out 95': [2.2798, 2.2947, 2.6252], 'put up-out 105': [3.776, 5.4932, 7.5187],
  };
  for (const [key, vals] of Object.entries(book)) {
    const [type, kind, Hs] = key.split(' ');
    const H = Number(Hs);
    [90, 100, 110].forEach((X, i) => {
      const val = M.standardBarrier({ type, kind, S: 100, X, H, T: 0.5, r: 0.08, b: 0.04, v: 0.25 })
        + rebate(kind, 100, H, 3, 0.5, 0.08, 0.04, 0.25);
      close(val, vals[i], 1e-4, `${key} X=${X}`);
    });
  }
});

// --- Kvotient, produkt og korrelasjon ---------------------------------------------------

test('Relative outperformance og produktopsjon mot MC', () => {
  for (const type of ['call', 'put']) {
    const X = 1.05;
    withinMC(mcTwoAssets({ ...BASE, payoff: (a, b) => Math.max(type === 'call' ? a / b - X : X - a / b, 0) }),
      M.relativeOutperformance({ type, ...BASE, X }).price, 4, 0, `kvotient ${type}`);
    const Xp = 9800;
    withinMC(mcTwoAssets({ ...BASE, rho: -0.3, seed: 2, payoff: (a, b) => Math.max(type === 'call' ? a * b - Xp : Xp - a * b, 0) }),
      M.productOption({ type, ...BASE, rho: -0.3, X: Xp }).price, 4, 0, `produkt ${type}`);
  }
  // Paritet: c − p = e^{−rT}(F − X).
  const c = M.relativeOutperformance({ type: 'call', ...BASE, X: 1.1 });
  const p = M.relativeOutperformance({ type: 'put', ...BASE, X: 1.1 });
  close(c.price - p.price, Math.exp(-BASE.r * BASE.T) * (c.F - 1.1), 1e-12);
});

test('Two-asset correlation mot MC og grensetilfeller', () => {
  for (const rho of [-0.6, 0.75]) {
    for (const type of ['call', 'put']) {
      const p = { ...BASE, rho, X1: 102, X2: 90 };
      const payoff = (a, b) => (type === 'call' ? (a > p.X1 ? Math.max(b - p.X2, 0) : 0) : (a < p.X1 ? Math.max(p.X2 - b, 0) : 0));
      withinMC(mcTwoAssets({ ...p, seed: 3, payoff }), M.twoAssetCorrelation({ type, ...p }), 4, 0, `${type} ρ=${rho}`);
    }
  }
  // ρ = 0: uavhengige, så prisen er P(S1 > X1) ganger vanilla på S2.
  const p = { ...BASE, rho: 0, X1: 102, X2: 90 };
  const pr = cnd((Math.log(p.S1 / p.X1) + (p.b1 - p.v1 * p.v1 / 2) * p.T) / (p.v1 * Math.sqrt(p.T)));
  close(M.twoAssetCorrelation({ type: 'call', ...p }), pr * vanilla('call', p.S2, p.X2, p.T, p.r, p.b2, p.v2), 1e-12);
  // X1 → 0: betingelsen er alltid oppfylt for call, så prisen er vanilla på S2.
  close(M.twoAssetCorrelation({ type: 'call', ...p, rho: 0.5, X1: 1e-12 }), vanilla('call', p.S2, p.X2, p.T, p.r, p.b2, p.v2), 1e-10);
});

// --- Bytteopsjoner og spread ----------------------------------------------------------------

test('Margrabe mot MC og identiteter', () => {
  const Q1 = 1.2;
  const Q2 = 1.1;
  withinMC(mcTwoAssets({ ...BASE, payoff: (a, b) => Math.max(Q1 * a - Q2 * b, 0) }), M.exchangeOption({ ...BASE, Q1, Q2 }).price);
  // Bytte-paritet: max(S1 − S2, 0) − max(S2 − S1, 0) = S1 − S2.
  const swap = { ...BASE, S1: BASE.S2, S2: BASE.S1, b1: BASE.b2, b2: BASE.b1, v1: BASE.v2, v2: BASE.v1 };
  close(M.exchangeOption(BASE).price - M.exchangeOption(swap).price,
    BASE.S1 * Math.exp((BASE.b1 - BASE.r) * BASE.T) - BASE.S2 * Math.exp((BASE.b2 - BASE.r) * BASE.T), 1e-10);
  // Kirk med X = 0 er eksakt lik Margrabe.
  close(M.kirkSpread({ type: 'call', ...BASE, X: 0 }).price, M.exchangeOption(BASE).price, 1e-12);
  // Analytiske deltaer mot numeriske.
  const e = M.exchangeOption({ ...BASE, Q1, Q2 });
  const h = 1e-4;
  close(e.delta1, (M.exchangeOption({ ...BASE, Q1, Q2, S1: BASE.S1 + h }).price - M.exchangeOption({ ...BASE, Q1, Q2, S1: BASE.S1 - h }).price) / (2 * h), 1e-7);
  close(e.delta2, (M.exchangeOption({ ...BASE, Q1, Q2, S2: BASE.S2 + h }).price - M.exchangeOption({ ...BASE, Q1, Q2, S2: BASE.S2 - h }).price) / (2 * h), 1e-7);
});

test('Spreadopsjon: eksakt integrasjon mot MC, Kirk nær eksakt, paritet', () => {
  for (const [rho, X] of [[0.4, 4], [-0.3, 10], [0.9, 2]]) {
    const p = { ...BASE, rho, X };
    for (const type of ['call', 'put']) {
      const exact = M.spreadExact({ type, ...p });
      withinMC(mcTwoAssets({ ...p, seed: 4, payoff: (a, b) => Math.max(type === 'call' ? a - b - X : X - a + b, 0) }), exact, 4, 0, `${type} ρ=${rho}`);
      const kirk = M.kirkSpread({ type, ...p }).price;
      assert.ok(Math.abs(kirk - exact) < 0.005 * exact + 0.01, `Kirk ${kirk} langt fra eksakt ${exact}`);
    }
    const fwd = Math.exp(-p.r * p.T) * (p.S1 * Math.exp(p.b1 * p.T) - p.S2 * Math.exp(p.b2 * p.T) - X);
    close(M.spreadExact({ type: 'call', ...p }) - M.spreadExact({ type: 'put', ...p }), fwd, 1e-9);
    close(M.kirkSpread({ type: 'call', ...p }).price - M.kirkSpread({ type: 'put', ...p }).price, fwd, 1e-10);
  }
  // Bokas eksempel: Kirk 2,1670 mot eksakt verdi.
  const book = { type: 'call', S1: 28, S2: 20, X: 7, T: 0.25, r: 0.05, b1: 0, b2: 0, v1: 0.29, v2: 0.36, rho: 0.42 };
  close(M.spreadExact(book), M.kirkSpread(book).price, 0.005);
  // Med X = 0 er spreaden en bytteopsjon.
  close(M.spreadExact({ type: 'call', ...BASE, X: 0 }), M.exchangeOption(BASE).price, 1e-9);
  assert.throws(() => M.kirkSpread({ type: 'call', ...BASE, X: -200 }), /F2 \+ X/);
});

test('Bjerksund-Stensland: 1993 er verdien av flat-grense-strategien, begge nær binomialtre', () => {
  // 1993-tilnærmingen er verdien av å innløse når S treffer I (eller ved T):
  // opp-og-ut-call med grense I pluss rabatten I − X betalt ved treff.
  for (const c of [
    { S: 100, X: 100, T: 0.1, r: 0.1, b: 0, v: 0.15 },
    { S: 90, X: 100, T: 2, r: 0.08, b: -0.04, v: 0.35 },
    { S: 110, X: 100, T: 0.5, r: 0.05, b: 0.02, v: 0.25 },
  ]) {
    const v2 = c.v * c.v;
    const beta = 0.5 - c.b / v2 + Math.sqrt((c.b / v2 - 0.5) ** 2 + 2 * c.r / v2);
    const BInf = beta / (beta - 1) * c.X;
    const B0 = Math.max(c.X, c.r / (c.r - c.b) * c.X);
    const I = B0 + (BInf - B0) * (1 - Math.exp(-(c.b * c.T + 2 * c.v * Math.sqrt(c.T)) * B0 / (BInf - B0)));
    const strategy = M.standardBarrier({ type: 'call', kind: 'up-out', ...c, H: I }) + rebate('up-out', c.S, I, I - c.X, c.T, c.r, c.b, c.v);
    close(M.bjerksundStensland1993({ type: 'call', ...c }), strategy, 1e-9);
  }
  for (const c of [
    { type: 'call', S: 100, X: 100, T: 0.5, r: 0.1, b: 0, v: 0.35 },
    { type: 'put', S: 90, X: 100, T: 0.5, r: 0.1, b: 0.1, v: 0.25 },
    { type: 'call', S: 110, X: 100, T: 1, r: 0.08, b: -0.04, v: 0.2 },
    { type: 'put', S: 100, X: 100, T: 1, r: 0.05, b: 0.02, v: 0.3 },
  ]) {
    const tree = crr(c);
    const a93 = M.bjerksundStensland1993(c);
    const a02 = M.bjerksundStensland2002(c);
    const tag = `${c.type} S=${c.S} T=${c.T}`;
    // Begge er verdien av en mulig (ikke optimal) innløsningsstrategi, altså nedre grenser.
    assert.ok(a93 <= a02 + 1e-9 && a02 <= tree * 1.001, `${tag}: 1993 ${a93}, 2002 ${a02}, tre ${tree}`);
    assert.ok(Math.abs(a02 - tree) < 0.012 * tree, `${tag}: 2002 ${a02} mot tre ${tree}`);
    assert.ok(Math.abs(a93 - tree) < 0.025 * tree, `${tag}: 1993 ${a93} mot tre ${tree}`);
  }
});

test('Bjerksund-Stensland 2002 er verdien av tograns-strategien (MC med brownsk bro)', () => {
  // Call som innløses når S treffer I2 før t1 = (√5 − 1)T/2, eller I1 etter t1, ellers ved T.
  const c = { S: 100, X: 90, T: 0.5, r: 0, b: -0.1, v: 0.25 };
  const v2 = c.v * c.v;
  const beta = 0.5 - c.b / v2 + Math.sqrt((c.b / v2 - 0.5) ** 2 + 2 * c.r / v2);
  const BInf = beta / (beta - 1) * c.X;
  const B0 = Math.max(c.X, c.r / (c.r - c.b) * c.X);
  const t1 = 0.5 * (Math.sqrt(5) - 1) * c.T;
  const bound = (t) => B0 + (BInf - B0) * (1 - Math.exp(-(c.b * t + 2 * c.v * Math.sqrt(t)) * c.X * c.X / ((BInf - B0) * B0)));
  const lI1 = Math.log(bound(t1));
  const lI2 = Math.log(bound(c.T));
  const steps = 100;
  const dt = c.T / steps;
  const rng = createRng(23);
  const n = 60000;
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    let x = Math.log(c.S);
    let val = 0;
    let alive = 1;
    for (let j = 0; j < steps; j++) {
      const nx = x + (c.b - v2 / 2) * dt + c.v * Math.sqrt(dt) * rng.normal();
      const lb = (j + 1) * dt <= t1 ? lI2 : lI1;
      if (x >= lb) {
        val += alive * (Math.exp(x) - c.X) * Math.exp(-c.r * j * dt);
        alive = 0;
        break;
      }
      const pHit = bridgeHitProb(x, nx, lb, c.v, dt);
      val += alive * pHit * (Math.exp(lb) - c.X) * Math.exp(-c.r * (j + 0.5) * dt);
      alive *= 1 - pHit;
      x = nx;
    }
    val += alive * Math.max(Math.exp(x) - c.X, 0) * Math.exp(-c.r * c.T);
    sum += val;
    sumSq += val * val;
  }
  const mean = sum / n;
  withinMC({ mean, se: Math.sqrt((sumSq / n - mean * mean) / n) }, M.bjerksundStensland2002({ type: 'call', ...c }));
});

test('Amerikansk bytteopsjon mot todimensjonalt binomialtre', () => {
  for (const e of [
    { S1: 22, S2: 20, T: 0.5, r: 0.1, b1: 0.04, b2: 0.06, v1: 0.2, v2: 0.25, rho: -0.5 },
    { S1: 110, S2: 100, Q1: 1, Q2: 1.05, T: 1, r: 0.05, b1: -0.03, b2: 0.05, v1: 0.25, v2: 0.25, rho: 0.5 },
  ]) {
    const eu = M.exchangeOption(e).price;
    close(tree2D({ ...e, american: false }), eu, 2e-3 * eu, 'europeisk 2D-tre mot Margrabe');
    const am2D = tree2D({ ...e, american: true });
    // Numerairebyttet: 1D-tre på forholdet med rente r − b2 og carry b1 − b2.
    const am1D = crr({ type: 'call', S: (e.Q1 ?? 1) * e.S1, X: (e.Q2 ?? 1) * e.S2, T: e.T, r: e.r - e.b2, b: e.b1 - e.b2, v: M.ratioVol(e.v1, e.v2, e.rho) });
    close(am2D, am1D, 3e-3 * am1D, '2D-tre mot 1D-tre på forholdet');
    const a93 = M.americanExchangeOption(e).price;
    const a02 = M.americanExchangeOption({ ...e, method: '2002' }).price;
    assert.ok(a93 >= eu && a93 <= am1D * 1.001 && Math.abs(a93 - am1D) < 0.025 * am1D, `1993: ${a93}, tre ${am1D}`);
    assert.ok(a02 >= a93 - 1e-9 && a02 <= am1D * 1.001 && Math.abs(a02 - am1D) < 0.012 * am1D, `2002: ${a02}, tre ${am1D}`);
  }
  // b1 ≥ r: aldri optimalt å innløse tidlig.
  const noEarly = { S1: 22, S2: 20, T: 0.5, r: 0.05, b1: 0.05, b2: 0.02, v1: 0.2, v2: 0.25, rho: 0.1 };
  close(M.americanExchangeOption(noEarly).price, M.exchangeOption(noEarly).price, 1e-12);
});

test('Bytteopsjon på bytteopsjon mot MC og paritet', () => {
  const p = { S1: 105, S2: 100, t1: 0.5, T2: 1, r: 0.06, b1: 0.03, b2: 0.05, v1: 0.25, v2: 0.3, rho: 0.2 };
  const tau = p.T2 - p.t1;
  const mkt = { S1: p.S1, S2: p.S2, T: p.t1, r: p.r, b1: p.b1, b2: p.b2, v1: p.v1, v2: p.v2, rho: p.rho };
  for (const Q of [0.05, 0.12]) {
    for (const kind of ['cc', 'pc', 'cp', 'pp']) {
      const under = kind[1] === 'c' ? 'call' : 'put';
      const est = mcTwoAssets({
        ...mkt, n: 100000, seed: 5,
        payoff: (a, b) => {
          const u = M.exchangeEuropean({ type: under, S1: a, S2: b, T: tau, r: p.r, b1: p.b1, b2: p.b2, v1: p.v1, v2: p.v2, rho: p.rho });
          return kind[0] === 'c' ? Math.max(u - Q * b, 0) : Math.max(Q * b - u, 0);
        },
      });
      withinMC(est, M.exchangeOnExchange({ kind, ...p, Q }).price, 4, 0, `${kind} Q=${Q}`);
    }
    // Paritet for sammensatte opsjoner: call − put = underliggende − Q·S2·e^{(b2−r)t1}.
    const pv = Q * p.S2 * Math.exp((p.b2 - p.r) * p.t1);
    const mar = (type) => M.exchangeEuropean({ type, S1: p.S1, S2: p.S2, T: p.T2, r: p.r, b1: p.b1, b2: p.b2, v1: p.v1, v2: p.v2, rho: p.rho });
    const val = (kind) => M.exchangeOnExchange({ kind, ...p, Q }).price;
    close(val('cc') - val('pc'), mar('call') - pv, 1e-9);
    close(val('cp') - val('pp'), mar('put') - pv, 1e-9);
  }
  // Numerisk integrasjon over forholdet P = S1/S2 ved t1 (aktivum 2 som numeraire).
  for (const Q of [0.03, 0.12, 0.4]) {
    for (const kind of ['cc', 'pc', 'cp', 'pp']) {
      const v = M.ratioVol(p.v1, p.v2, p.rho);
      const rr = p.r - p.b2;
      const bb = p.b1 - p.b2;
      const under = kind[1] === 'c' ? 'call' : 'put';
      const u = (z) => gbsm({ type: under, S: p.S1 / p.S2 * Math.exp((bb - v * v / 2) * p.t1 + v * Math.sqrt(p.t1) * z), X: 1, T: tau, r: rr, b: bb, v }) - Q;
      const g = (z) => npdf(z) * Math.max(kind[0] === 'c' ? u(z) : -u(z), 0);
      let integral;
      if (u(-12) * u(12) < 0) {
        const zs = brent(u, -12, 12);
        integral = gaussLegendreComposite(g, -12, zs, 40, 20) + gaussLegendreComposite(g, zs, 12, 40, 20);
      } else {
        integral = gaussLegendreComposite(g, -12, 12, 80, 20);
      }
      close(M.exchangeOnExchange({ kind, ...p, Q }).price, p.S2 * Math.exp(-rr * p.t1) * integral, 1e-9, `integrasjon ${kind} Q=${Q}`);
    }
  }
  // Q over maksverdien til den underliggende omvendte opsjonen: call på put er verdiløs.
  const big = M.exchangeOnExchange({ kind: 'cp', ...p, Q: 5 });
  assert.equal(big.price, 0);
  close(M.exchangeOnExchange({ kind: 'pp', ...p, Q: 5 }).price,
    5 * p.S2 * Math.exp((p.b2 - p.r) * p.t1) - M.exchangeEuropean({ type: 'put', S1: p.S1, S2: p.S2, T: p.T2, r: p.r, b1: p.b1, b2: p.b2, v1: p.v1, v2: p.v2, rho: p.rho }), 1e-10);
});

// --- Maks og min ---------------------------------------------------------------------------

test('Opsjoner på maks/min av to aktiva mot MC', () => {
  for (const p of [{ ...BASE, X: 97 }, { S1: 100, S2: 105, X: 98, T: 0.5, r: 0.05, b1: -0.01, b2: -0.04, v1: 0.11, v2: 0.16, rho: 0.63 }]) {
    for (const type of ['call', 'put']) {
      for (const kind of ['min', 'max']) {
        const g = kind === 'min' ? Math.min : Math.max;
        withinMC(mcTwoAssets({ ...p, seed: 6, payoff: (a, b) => Math.max(type === 'call' ? g(a, b) - p.X : p.X - g(a, b), 0) }),
          M.maxMinOption({ type, kind, ...p }), 4, 0, `${type} ${kind}`);
      }
    }
  }
});

test('Maks/min mot numerisk integrasjon over S2(T)', () => {
  // Gitt S2(T) = s2 er S1(T) lognormal med forventning A og logvolatilitet s, så
  // E[(maks − X)⁺ | s2] og E[(min − X)⁺ | s2] er Black-Scholes-uttrykk.
  for (const p of [{ ...BASE, X: 97 }, { ...BASE, rho: -0.7, X: 110 }, { S1: 100, S2: 105, X: 98, T: 0.5, r: 0.05, b1: -0.01, b2: -0.04, v1: 0.11, v2: 0.16, rho: 0.63 }]) {
    const sT = Math.sqrt(p.T);
    const s = p.v1 * sT * Math.sqrt(1 - p.rho * p.rho);
    const A = (z) => p.S1 * Math.exp(p.b1 * p.T - 0.5 * p.v1 * p.v1 * p.T * p.rho * p.rho + p.v1 * sT * p.rho * z);
    const s2 = (z) => p.S2 * Math.exp((p.b2 - 0.5 * p.v2 * p.v2) * p.T + p.v2 * sT * z);
    const d1 = (a, K) => (Math.log(a / K) + 0.5 * s * s) / s;
    const part = (a, K) => a * cnd(d1(a, K)) - p.X * cnd(d1(a, K) - s); // E[(S1 − X)·1{S1 > K}], K ≥ X
    const fMax = (z) => {
      const a = A(z);
      const k = s2(z);
      return npdf(z) * (part(a, Math.max(p.X, k)) + Math.max(k - p.X, 0) * cnd(-(d1(a, k) - s)));
    };
    const fMin = (z) => {
      const a = A(z);
      const k = s2(z);
      if (k <= p.X) return 0;
      return npdf(z) * (part(a, p.X) - part(a, k) + (k - p.X) * cnd(d1(a, k) - s));
    };
    const zk = (Math.log(p.X / p.S2) - (p.b2 - 0.5 * p.v2 * p.v2) * p.T) / (p.v2 * sT); // s2(zk) = X
    const integ = (f) => Math.exp(-p.r * p.T) * (gaussLegendreComposite(f, -12, zk, 40, 20) + gaussLegendreComposite(f, zk, 12, 40, 20));
    close(M.maxMinOption({ type: 'call', kind: 'max', ...p }), integ(fMax), 1e-9, 'call på maks');
    close(M.maxMinOption({ type: 'call', kind: 'min', ...p }), integ(fMin), 1e-9, 'call på min');
  }
});

test('Maks/min: identiteter og Margrabe som spesialtilfelle', () => {
  for (const X of [80, 97, 120]) {
    for (const type of ['call', 'put']) {
      const sum = M.maxMinOption({ type, kind: 'max', ...BASE, X }) + M.maxMinOption({ type, kind: 'min', ...BASE, X });
      close(sum, vanilla(type, BASE.S1, X, BASE.T, BASE.r, BASE.b1, BASE.v1) + vanilla(type, BASE.S2, X, BASE.T, BASE.r, BASE.b2, BASE.v2), 1e-9, `${type} X=${X}`);
    }
  }
  // X → 0: max(S1, S2) = S2 + max(S1 − S2, 0) og min(S1, S2) = S1 − max(S1 − S2, 0).
  const F1 = BASE.S1 * Math.exp((BASE.b1 - BASE.r) * BASE.T);
  const F2 = BASE.S2 * Math.exp((BASE.b2 - BASE.r) * BASE.T);
  const mar = M.exchangeOption(BASE).price;
  for (const X of [0, 1e-9]) {
    close(M.maxMinOption({ type: 'call', kind: 'max', ...BASE, X }), F2 + mar, 1e-9);
    close(M.maxMinOption({ type: 'call', kind: 'min', ...BASE, X }), F1 - mar, 1e-9);
  }
  // σ1 = σ2, ρ = 1: forholdet er deterministisk og opsjonen er vanilla på det største/minste aktivumet.
  const det = { ...BASE, v2: BASE.v1, rho: 1, X: 97 };
  close(M.maxMinOption({ type: 'call', kind: 'max', ...det }), vanilla('call', det.S1, 97, det.T, det.r, det.b1, det.v1), 1e-12);
  close(M.maxMinOption({ type: 'put', kind: 'min', ...det }), vanilla('put', det.S2, 97, det.T, det.r, det.b2, det.v1), 1e-12);
  close(M.maxMinOption({ type: 'call', kind: 'max', ...det, rho: 0.99999999 }), M.maxMinOption({ type: 'call', kind: 'max', ...det }), 1e-3);
});

test('Maks/min av to geometriske gjennomsnitt mot MC', () => {
  const p = { ...BASE, X: 96 };
  const steps = 50;
  const avg = (path) => {
    let s = 0;
    for (let j = 0; j < steps; j++) s += 0.5 * (Math.log(path[j]) + Math.log(path[j + 1]));
    return Math.exp(s / steps);
  };
  for (const type of ['call', 'put']) {
    for (const kind of ['min', 'max']) {
      const g = kind === 'min' ? Math.min : Math.max;
      const est = mcTwoAssetPaths({ ...p, steps, n: 40000, seed: 8, payoff: (a, b) => {
        const m = g(avg(a), avg(b));
        return Math.max(type === 'call' ? m - p.X : p.X - m, 0);
      } });
      withinMC(est, M.maxMinTwoAverages({ type, kind, ...p }), 4, 0, `${type} ${kind}`);
    }
  }
  // maks + min = sum av opsjoner på hvert geometriske snitt.
  const geo = (S, b, v) => gbsm({ type: 'call', S, X: p.X, T: p.T, r: p.r, b: 0.5 * (b - v * v / 6), v: v / Math.sqrt(3) });
  close(M.maxMinTwoAverages({ type: 'call', kind: 'max', ...p }) + M.maxMinTwoAverages({ type: 'call', kind: 'min', ...p }),
    geo(p.S1, p.b1, p.v1) + geo(p.S2, p.b2, p.v2), 1e-9);
});

// --- Barrierer ---------------------------------------------------------------------------------

test('To-aktiva-barriere (Heynen og Kat) mot MC med brownsk bro', () => {
  for (const kind of KINDS) {
    for (const type of ['call', 'put']) {
      const H = kind.startsWith('down') ? 85 : 110;
      const p = { type, kind, ...BASE, X: 97, H };
      withinMC(mcTwoAssetBarrier(p), M.twoAssetBarrier(p), 4, 0, `${kind} ${type}`);
    }
  }
  for (const kind of ['down-out', 'up-out']) {
    const p = { type: 'call', kind, ...BASE, rho: -0.6, X: 97, H: kind === 'down-out' ? 85 : 110 };
    withinMC(mcTwoAssetBarrier({ ...p, seed: 11 }), M.twoAssetBarrier(p), 4, 0, `${kind} ρ=−0,6`);
  }
});

test('To-aktiva-barrierer (full og partial-time) mot numerisk integrasjon', () => {
  const mkt = { S1: 100, S2: 95, T: 0.75, r: 0.05, b1: 0.02, b2: 0.04, v1: 0.25, v2: 0.35 };
  for (const rho of [-0.8, 0, 0.6]) {
    for (const t1 of [0.3, 0.75]) {
      for (const kind of KINDS) {
        for (const type of ['call', 'put']) {
          for (const X of [80, 120]) {
            const p = { type, kind, ...mkt, rho, X, H: kind.startsWith('down') ? 88 : 110, t1 };
            close(M.partialTwoAssetBarrier(p), barrierByIntegration(p), 1e-9, `${kind} ${type} ρ=${rho} t1=${t1} X=${X}`);
          }
        }
      }
    }
  }
});

test('To-aktiva-barriere: identiteter', () => {
  for (const type of ['call', 'put']) {
    const van = vanilla(type, BASE.S1, 97, BASE.T, BASE.r, BASE.b1, BASE.v1);
    for (const [kindOut, kindIn, H] of [['down-out', 'down-in', 85], ['up-out', 'up-in', 110]]) {
      const p = { type, ...BASE, X: 97, H };
      close(M.twoAssetBarrier({ ...p, kind: kindOut }) + M.twoAssetBarrier({ ...p, kind: kindIn }), van, 1e-10, 'inn + ut');
      // ρ = 0: uavhengighet, ut = vanilla · P(S2 treffer ikke H).
      close(M.twoAssetBarrier({ ...p, rho: 0, kind: kindOut }), van * survivalProb(BASE.S2, H, BASE.T, BASE.b2, BASE.v2), 1e-10, 'ρ = 0');
      // Allerede truffet: ut = 0, inn = vanilla.
      const hit = kindOut === 'down-out' ? 80 : 120;
      assert.equal(M.twoAssetBarrier({ ...p, S2: hit, kind: kindOut }), 0);
      close(M.twoAssetBarrier({ ...p, S2: hit, kind: kindIn }), van, 1e-12);
      // Med t1 = T er partial-time-varianten lik den vanlige.
      close(M.partialTwoAssetBarrier({ ...p, kind: kindOut, t1: BASE.T }), M.twoAssetBarrier({ ...p, kind: kindOut }), 1e-14);
    }
    // Barriere langt unna: ut = vanilla.
    close(M.twoAssetBarrier({ type, kind: 'down-out', ...BASE, X: 97, H: 1e-3 }), van, 1e-9, 'fjern ned-barriere');
    close(M.twoAssetBarrier({ type, kind: 'up-out', ...BASE, X: 97, H: 1e5 }), van, 1e-9, 'fjern opp-barriere');
  }
});

test('Partial-time to-aktiva-barriere (Bermin) mot MC og identiteter', () => {
  for (const kind of KINDS) {
    for (const type of ['call', 'put']) {
      const p = { type, kind, ...BASE, rho: -0.5, X: 97, H: kind.startsWith('down') ? 88 : 110, t1: 0.3 };
      withinMC(mcTwoAssetBarrier({ ...p, seed: 9 }), M.partialTwoAssetBarrier(p), 4, 0, `${kind} ${type}`);
    }
  }
  const van = vanilla('call', BASE.S1, 97, BASE.T, BASE.r, BASE.b1, BASE.v1);
  const p = { type: 'call', kind: 'down-out', ...BASE, X: 97, H: 88 };
  close(M.partialTwoAssetBarrier({ ...p, rho: 0, t1: 0.3 }), van * survivalProb(BASE.S2, 88, 0.3, BASE.b2, BASE.v2), 1e-10, 'ρ = 0');
  close(M.partialTwoAssetBarrier({ ...p, t1: 1e-10 }), van, 1e-8, 't1 → 0');
  close(M.partialTwoAssetBarrier({ ...p, t1: 2 }), M.twoAssetBarrier(p), 1e-14, 't1 > T gir overvåking hele løpetiden');
  assert.throws(() => M.partialTwoAssetBarrier({ ...p, t1: 0 }), /t1/);
});

test('Margrabe-barriere mot MC (brownsk bro på S1/S2) og identiteter', () => {
  const p0 = { ...BASE, S2: 100, rho: 0.3, Q1: 1, Q2: 1.02 };
  const v = M.ratioVol(p0.v1, p0.v2, p0.rho);
  const steps = 20;
  const dt = p0.T / steps;
  for (const kind of KINDS) {
    for (const type of ['call', 'put']) {
      const H = kind.startsWith('down') ? 0.93 : 1.2;
      const lh = Math.log(H);
      const out = kind.endsWith('out');
      const est = mcTwoAssetPaths({ ...p0, steps, n: 40000, seed: 5, payoff: (a, b) => {
        let surv = 1;
        for (let j = 0; j < steps; j++) surv *= 1 - bridgeHitProb(Math.log(a[j] / b[j]), Math.log(a[j + 1] / b[j + 1]), lh, v, dt);
        const pay = Math.max(type === 'call' ? p0.Q1 * a[steps] - p0.Q2 * b[steps] : p0.Q2 * b[steps] - p0.Q1 * a[steps], 0);
        return pay * (out ? surv : 1 - surv);
      } });
      withinMC(est, M.margrabeBarrier({ type, kind, ...p0, H }), 4, 0, `${kind} ${type}`);
    }
  }
  for (const type of ['call', 'put']) {
    const mar = M.exchangeEuropean({ type, ...p0 });
    close(M.margrabeBarrier({ type, kind: 'down-out', ...p0, H: 0.93 }) + M.margrabeBarrier({ type, kind: 'down-in', ...p0, H: 0.93 }), mar, 1e-10);
    close(M.margrabeBarrier({ type, kind: 'up-out', ...p0, H: 1.2 }) + M.margrabeBarrier({ type, kind: 'up-in', ...p0, H: 1.2 }), mar, 1e-10);
    close(M.margrabeBarrier({ type, kind: 'down-out', ...p0, H: 1e-4 }), mar, 1e-9, 'fjern barriere');
    close(M.margrabeBarrier({ type, kind: 'up-out', ...p0, H: 1e4 }), mar, 1e-9, 'fjern barriere');
    assert.equal(M.margrabeBarrier({ type, kind: 'down-out', ...p0, H: 1.01 }), 0);
    close(M.margrabeBarrier({ type, kind: 'down-in', ...p0, H: 1.01 }), mar, 1e-12);
  }
  close(M.exchangeEuropean({ type: 'call', ...p0 }), M.exchangeOption(p0).price, 1e-12);
});

// --- Binære -------------------------------------------------------------------------------------

test('Two-asset cash-or-nothing mot MC og identiteter', () => {
  const p = { ...BASE, X1: 105, X2: 92, K: 10 };
  const conds = { 1: (a, b) => a > p.X1 && b > p.X2, 2: (a, b) => a < p.X1 && b < p.X2, 3: (a, b) => a > p.X1 && b < p.X2, 4: (a, b) => a < p.X1 && b > p.X2 };
  let sum = 0;
  for (const kind of [1, 2, 3, 4]) {
    const val = M.twoAssetCashOrNothing({ kind, ...p });
    sum += val;
    withinMC(mcTwoAssets({ ...p, seed: 10, payoff: (a, b) => (conds[kind](a, b) ? p.K : 0) }), val, 4, 0, `type ${kind}`);
  }
  close(sum, p.K * Math.exp(-p.r * p.T), 1e-12, 'summen av de fire typene');
  const d1 = (Math.log(p.S1 / p.X1) + (p.b1 - p.v1 * p.v1 / 2) * p.T) / (p.v1 * Math.sqrt(p.T));
  const d2 = (Math.log(p.S2 / p.X2) + (p.b2 - p.v2 * p.v2 / 2) * p.T) / (p.v2 * Math.sqrt(p.T));
  close(M.twoAssetCashOrNothing({ kind: 3, ...p, rho: 0 }), p.K * Math.exp(-p.r * p.T) * cnd(d1) * cnd(-d2), 1e-12, 'ρ = 0');
});

test('Best eller worst cash-or-nothing mot MC og identiteter', () => {
  const p = { ...BASE, X: 97, K: 10 };
  const D = p.K * Math.exp(-p.r * p.T);
  for (const type of ['call', 'put']) {
    for (const kind of ['max', 'min']) {
      const g = kind === 'min' ? Math.min : Math.max;
      withinMC(mcTwoAssets({ ...p, seed: 12, payoff: (a, b) => ((type === 'call' ? g(a, b) > p.X : g(a, b) < p.X) ? p.K : 0) }),
        M.bestWorstCashOrNothing({ type, kind, ...p }), 4, 0, `${type} ${kind}`);
    }
  }
  const v = (type, kind) => M.bestWorstCashOrNothing({ type, kind, ...p });
  close(v('call', 'max') + v('put', 'max'), D, 1e-12);
  close(v('call', 'min') + v('put', 'min'), D, 1e-12);
  const y = (S, b, s) => (Math.log(S / p.X) + (b - s * s / 2) * p.T) / (s * Math.sqrt(p.T));
  close(v('call', 'max') + v('call', 'min'), D * (cnd(y(p.S1, p.b1, p.v1)) + cnd(y(p.S2, p.b2, p.v2))), 1e-12);
  close(v('call', 'min'), M.twoAssetCashOrNothing({ kind: 1, ...p, X1: p.X, X2: p.X }), 1e-14);
  close(v('put', 'max'), M.twoAssetCashOrNothing({ kind: 2, ...p, X1: p.X, X2: p.X }), 1e-14);
});

// --- Katalogen ------------------------------------------------------------------------------------

test('Katalogen: alle typer gir endelige og glatte tall over grafområdet', () => {
  for (const c of catalog) {
    const p0 = defaultParams(c);
    let combos = [{}];
    for (const s of c.inputs.filter((i) => i.type === 'select')) {
      combos = combos.flatMap((cb) => s.options.map((o) => ({ ...cb, [s.key]: o.value })));
    }
    const key = ['S', 'F', 'S1'].find((k) => p0[k] !== undefined);
    for (const cb of combos) {
      const p = { ...p0, ...cb };
      const xs = key ? Array.from({ length: 31 }, (_, i) => p[key] * (0.5 + i / 30)) : [null];
      for (const x of xs) {
        const q = key ? { ...p, [key]: x } : p;
        const entries = Object.entries(c.compute(q));
        assert.ok(Number.isFinite(entries[0][1]), `${c.id} ${JSON.stringify(cb)} ${key}=${x}: hovedresultatet er ${entries[0][1]}`);
        for (const [label, val] of entries) {
          assert.ok(typeof val === 'string' || Number.isFinite(val), `${c.id} ${JSON.stringify(cb)} ${key}=${x}: «${label}» = ${val}`);
        }
      }
    }
  }
});
