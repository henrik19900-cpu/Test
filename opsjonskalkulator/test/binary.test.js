// Tester for de binære opsjonene i kapittel 4.19: bokas eksempler, Monte Carlo (med brownsk bro
// for barrierene), numerisk integrasjon, paritet mellom inn og ut, og to uavhengige rekker.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';
import { gaussLegendreComposite } from '../src/math/integrate.js';
import {
  gapOption, cashOrNothing, assetOrNothing, supershare, binaryBarrier,
  huiKnockOut, firstHitValue, doubleBarrierBinary, DOUBLE_BINARY_KINDS,
} from '../src/models/binary.js';
import { ikedaKunitomoProb } from '../src/models/barriers.js';
import { close, withinMC, mcTerminal, bridgeHitProb } from './helpers.js';

function accumulator() {
  let s = 0;
  let s2 = 0;
  let n = 0;
  return {
    add(y) { s += y; s2 += y * y; n++; },
    result(df = 1) {
      const m = s / n;
      return { mean: m * df, se: Math.sqrt(Math.max(s2 / n - m * m, 0) / n) * df };
    },
  };
}

// --- Gap, cash-or-nothing, asset-or-nothing og supershare ---------------------------

test('Enkle binære: bokas eksempler', () => {
  close(gapOption({ type: 'call', S: 50, X1: 50, X2: 57, T: 0.5, r: 0.09, b: 0.09, v: 0.2 }), -0.0053, 1e-4, 'gap call');
  close(cashOrNothing({ type: 'put', S: 100, X: 80, K: 10, T: 0.75, r: 0.06, b: 0, v: 0.35 }), 2.671, 1e-4, 'cash-or-nothing put');
  close(assetOrNothing({ type: 'put', S: 70, X: 65, T: 0.5, r: 0.07, b: 0.02, v: 0.27 }), 20.2069, 1e-4, 'asset-or-nothing put');
  close(supershare({ S: 100, XL: 90, XH: 110, T: 0.25, r: 0.1, b: 0, v: 0.2 }), 0.7389, 1e-4, 'supershare');
});

test('Enkle binære mot MC', () => {
  const p = { S: 100, T: 0.75, r: 0.06, b: 0.02, v: 0.3, n: 400000 };
  let seed = 1;
  for (const type of ['call', 'put']) {
    const itm = (ST, X) => (type === 'call' ? ST > X : ST < X);
    withinMC(mcTerminal({ ...p, seed: seed++, payoff: (ST) => (itm(ST, 95) ? (type === 'call' ? ST - 105 : 105 - ST) : 0) }),
      gapOption({ ...p, type, X1: 95, X2: 105 }), 4, 0, `gap ${type}`);
    withinMC(mcTerminal({ ...p, seed: seed++, payoff: (ST) => (itm(ST, 104) ? 7 : 0) }),
      cashOrNothing({ ...p, type, X: 104, K: 7 }), 4, 0, `cash-or-nothing ${type}`);
    withinMC(mcTerminal({ ...p, seed: seed++, payoff: (ST) => (itm(ST, 92) ? ST : 0) }),
      assetOrNothing({ ...p, type, X: 92 }), 4, 0, `asset-or-nothing ${type}`);
  }
  withinMC(mcTerminal({ ...p, seed: seed++, payoff: (ST) => (ST >= 90 && ST < 115 ? ST / 90 : 0) }),
    supershare({ ...p, XL: 90, XH: 115 }), 4, 0, 'supershare');
});

test('Enkle binære: identiteter og paritet', () => {
  const p = { S: 100, T: 0.6, r: 0.05, b: -0.01, v: 0.25 };
  for (const X of [80, 100, 125]) {
    close(cashOrNothing({ ...p, type: 'call', X, K: 3 }) + cashOrNothing({ ...p, type: 'put', X, K: 3 }), 3 * Math.exp(-p.r * p.T), 1e-12);
    close(assetOrNothing({ ...p, type: 'call', X }) + assetOrNothing({ ...p, type: 'put', X }), p.S * Math.exp((p.b - p.r) * p.T), 1e-12);
    for (const type of ['call', 'put']) {
      // Gap call = asset-or-nothing − X2 · cash-or-nothing, gap put = X2 · cash-or-nothing − asset-or-nothing.
      const sign = type === 'call' ? 1 : -1;
      close(gapOption({ ...p, type, X1: X, X2: 97 }), sign * (assetOrNothing({ ...p, type, X }) - cashOrNothing({ ...p, type, X, K: 97 })), 1e-12, `gap ${type}`);
    }
  }
  close(supershare({ ...p, XL: 90, XH: 110 }), (assetOrNothing({ ...p, type: 'call', X: 90 }) - assetOrNothing({ ...p, type: 'call', X: 110 })) / 90, 1e-12, 'supershare');
  // Gap med X1 = X2 er en vanlig opsjon (positiv), og X2 > X1 kan gi negativ pris.
  assert.ok(gapOption({ ...p, type: 'call', X1: 50, X2: 57, S: 50 }) > 0);
  assert.ok(gapOption({ type: 'call', S: 50, X1: 50, X2: 57, T: 0.5, r: 0.09, b: 0.09, v: 0.2 }) < 0);
});

// --- Binære barriereopsjoner ------------------------------------------------------------

const BB = { H: 100, K: 15, T: 0.5, r: 0.1, b: 0.1, v: 0.2 };
const spotFor = (kind) => (kind % 2 === 1 ? 105 : 95);

test('Binær barriere: bokas tabell (H = 100, K = 15, T = 0,5, r = b = 0,1, σ = 0,2)', () => {
  // [X = 102, X = 98]. S = 105 for ned-typer (odde) og S = 95 for opp-typer (like).
  // Utelatt: type 3 (usikker trykt verdi; testet som (1)·H/K under) og X = 102 for type 14 og 20,
  // der tallene vi husker fra boka (5,3710 og 38,7533) bryter inn + ut-pariteten (mistenkt trykkfeil).
  const book = {
    1: [9.7264, 9.7264], 2: [11.6553, 11.6553], 4: [77.7017, 77.7017], 5: [9.3604, 9.3604], 6: [11.2223, 11.2223],
    7: [64.8426, 64.8426], 8: [77.7017, 77.7017], 9: [4.9081, 4.9081], 10: [3.0461, 3.0461], 11: [40.1574, 40.1574],
    12: [17.2983, 17.2983], 13: [4.9289, 6.215], 14: [null, 7.4519], 15: [37.2782, 45.853], 16: [44.5294, 54.9262],
    17: [4.4314, 3.1454], 18: [5.3297, 3.7704], 19: [27.5644, 18.9896], 20: [null, 22.7755], 21: [4.8758, 4.9081],
    22: [0, 0.0407], 23: [39.9391, 40.1574], 24: [0, 0.2676], 25: [0.0323, 0], 26: [3.0461, 3.0054],
    27: [0.2183, 0], 28: [17.2983, 17.0306],
  };
  for (const [kind, vals] of Object.entries(book)) {
    [102, 98].forEach((X, i) => {
      if (vals[i] === null) return;
      close(binaryBarrier({ ...BB, kind: Number(kind), S: spotFor(Number(kind)), X }), vals[i], 1.01e-4, `type ${kind} X=${X}`);
    });
  }
  // Type 3 (aktiva ved treff, verdi H) er type 1 skalert med H/K.
  close(binaryBarrier({ ...BB, kind: 3, S: 105, X: 102 }), binaryBarrier({ ...BB, kind: 1, S: 105, X: 102 }) * BB.H / BB.K, 1e-12);
});

test('Binær barriere: inn + ut = binær uten barriere (alle par)', () => {
  const sets = [{ ...BB }, { H: 90, K: 4, T: 1.3, r: 0.04, b: -0.03, v: 0.35 }];
  for (const s of sets) {
    for (const X of [s.H * 1.05, s.H * 0.95]) {
      for (let kind = 5; kind <= 20; kind++) {
        if (kind >= 9 && kind <= 12) continue;
        const S = kind % 2 === 1 ? s.H * 1.08 : s.H * 0.93;
        const outKind = kind <= 8 ? kind + 4 : kind + 8;
        const sum = binaryBarrier({ ...s, kind, S, X }) + binaryBarrier({ ...s, kind: outKind, S, X });
        let expected;
        if (kind <= 6) expected = s.K * Math.exp(-s.r * s.T);
        else if (kind <= 8) expected = S * Math.exp((s.b - s.r) * s.T);
        else {
          const type = kind <= 16 ? 'call' : 'put';
          const cash = [13, 14, 17, 18].includes(kind);
          expected = cash ? cashOrNothing({ ...s, type, S, X }) : assetOrNothing({ ...s, type, S, X });
        }
        close(sum, expected, 1e-10, `type ${kind} + ${outKind}, X=${X}`);
      }
    }
  }
});

// Ett steg med brownsk bro er eksakt for alle typene som betaler ved forfall (5–28).
function mcBinaryBarrier({ kind, S, X, H, K, T, r, b, v, n, seed }) {
  const rng = createRng(seed);
  const sd = v * Math.sqrt(T);
  const x0 = Math.log(S);
  const m = x0 + (b - v * v / 2) * T;
  const lnH = Math.log(H);
  const acc = accumulator();
  const call = [13, 14, 15, 16, 21, 22, 23, 24].includes(kind);
  const cash = kind <= 12 ? [5, 6, 9, 10].includes(kind) : [13, 14, 17, 18, 21, 22, 25, 26].includes(kind);
  const knockIn = kind <= 8 || (kind >= 13 && kind <= 20);
  for (let i = 0; i < n / 2; i++) {
    const z = rng.normal();
    let y = 0;
    for (const x1 of [m + sd * z, m - sd * z]) {
      const ST = Math.exp(x1);
      const surv = 1 - bridgeHitProb(x0, x1, lnH, v, T);
      const itm = kind <= 12 ? true : (call ? ST > X : ST < X);
      if (itm) y += 0.5 * (knockIn ? 1 - surv : surv) * (cash ? K : ST);
    }
    acc.add(y);
  }
  return acc.result(Math.exp(-r * T));
}

test('Binær barriere mot MC med brownsk bro (type 5–28) og førstepasseringsintegral (type 1–4)', () => {
  let seed = 50;
  for (const s of [{ ...BB, v: 0.3 }, { H: 90, K: 4, T: 1.3, r: 0.04, b: -0.03, v: 0.35 }]) {
    for (let kind = 5; kind <= 28; kind++) {
      const S = kind % 2 === 1 ? s.H * 1.06 : s.H * 0.94;
      for (const X of kind <= 12 ? [s.H] : [s.H * 1.04, s.H * 0.96]) {
        const p = { ...s, kind, S, X };
        withinMC(mcBinaryBarrier({ ...p, n: 100000, seed: seed++ }), binaryBarrier(p), 4, 1e-6, `type ${kind} X=${X}`);
      }
    }
    // Betaling ved treff: K · ∫ e^{−rt} f(t) dt med f tettheten til første treff.
    for (const kind of [1, 2, 3, 4]) {
      const S = kind % 2 === 1 ? s.H * 1.06 : s.H * 0.94;
      const a = Math.log(s.H / S);
      const nu = s.b - s.v * s.v / 2;
      const f = (t) => Math.abs(a) / (s.v * Math.sqrt(2 * Math.PI * t ** 3)) * Math.exp(-((a - nu * t) ** 2) / (2 * s.v * s.v * t));
      const pay = kind <= 2 ? s.K : s.H;
      const integral = gaussLegendreComposite((t) => Math.exp(-s.r * t) * f(t), 1e-12, s.T, 2000, 16);
      close(binaryBarrier({ ...s, kind, S, X: s.H }), pay * integral, 1e-9, `type ${kind}`);
    }
  }
});

test('Binær barriere: spot forbi barrieren og barriere langt unna', () => {
  const s = { ...BB, X: 102 };
  close(binaryBarrier({ ...s, kind: 1, S: 99 }), 15, 0);
  close(binaryBarrier({ ...s, kind: 4, S: 101 }), 101, 0);
  close(binaryBarrier({ ...s, kind: 5, S: 99 }), 15 * Math.exp(-0.05), 1e-12);
  assert.equal(binaryBarrier({ ...s, kind: 9, S: 99 }), 0);
  close(binaryBarrier({ ...s, kind: 13, S: 99 }), cashOrNothing({ ...s, type: 'call', S: 99 }), 0);
  close(binaryBarrier({ ...s, kind: 20, S: 101 }), assetOrNothing({ ...s, type: 'put', S: 101 }), 0);
  assert.equal(binaryBarrier({ ...s, kind: 28, S: 100 }), 0);
  // Kontinuitet ved barrieren for typene som betaler ved treff.
  close(binaryBarrier({ ...s, kind: 1, S: 100 * (1 + 1e-10) }), 15, 1e-6);
  close(binaryBarrier({ ...s, kind: 3, S: 100 * (1 + 1e-10) }), 100, 1e-5);
  // Barriere langt unna: ut-typer blir vanlige binære, inn-typer verdiløse.
  close(binaryBarrier({ ...s, kind: 21, S: 100, H: 1 }), cashOrNothing({ ...s, type: 'call', S: 100 }), 1e-10);
  close(binaryBarrier({ ...s, kind: 28, S: 100, H: 1e4 }), assetOrNothing({ ...s, type: 'put', S: 100 }), 1e-10);
  close(binaryBarrier({ ...s, kind: 15, S: 100, H: 1 }), 0, 1e-10);
});

// --- Dobbel-barriere binære (Hui 1996) --------------------------------------------------

test('Dobbel-barriere binær: bokas tabell (knock-out, S = 100, K = 10, T = 0,25, r = 0,05, b = 0,03)', () => {
  const book = {
    '80 120': [9.8716, 8.9307, 6.3272, 1.9094],
    '85 115': [9.7961, 7.23, 3.71, 0.4271],
    '90 110': [8.9054, 3.6752, 0.796, 0.0059],
    '95 105': [3.6323, 0.0911, 0.0002, 0],
  };
  for (const [lu, vals] of Object.entries(book)) {
    const [L, U] = lu.split(' ').map(Number);
    [0.1, 0.2, 0.3, 0.5].forEach((v, i) => {
      const p = { S: 100, L, U, K: 10, T: 0.25, r: 0.05, b: 0.03, v };
      close(doubleBarrierBinary({ ...p, kind: 'ko' }), vals[i], 1e-4, `L=${L} U=${U} σ=${v}`);
      close(huiKnockOut(p), vals[i], 1e-4, `Hui-rekken L=${L} U=${U} σ=${v}`);
    });
  }
});

test('Dobbel-barriere binær: Huis egenfunksjonsrekke = bilderekken = 1 − P(øvre først) − P(nedre først)', () => {
  for (const [S, L, U, T, r, b, v] of [
    [100, 80, 120, 0.25, 0.05, 0.03, 0.2], [100, 95, 105, 2, 0.05, -0.04, 0.15], [50, 30, 90, 3, 0.02, 0.06, 0.45],
    [100, 99, 101, 0.01, 0.05, 0.03, 0.3], [100, 60, 101, 0.5, 0.1, 0.1, 0.25], [100, 98, 140, 1, 0.08, 0, 0.1],
  ]) {
    const p = { S, L, U, T, r, b, v };
    const hui = huiKnockOut({ ...p, K: 1 });
    const image = Math.exp(-r * T) * ikedaKunitomoProb({ S, lo: L, hi: U, L, U, T, b, v, share: false });
    const tag = `S=${S} L=${L} U=${U} T=${T}`;
    close(hui, image, 1e-12, `${tag} Hui mot bilderekke`);
    for (const method of ['image', 'eigen']) {
      const pu = firstHitValue({ ...p, upper: true, rate: 0, method });
      const pl = firstHitValue({ ...p, upper: false, rate: 0, method });
      close(Math.exp(-r * T) * (1 - pu - pl), hui, 1e-11, `${tag} ${method}: 1 − pU − pL`);
      for (const upper of [true, false]) {
        close(firstHitValue({ ...p, upper, rate: r, method }), firstHitValue({ ...p, upper, rate: r, method: method === 'image' ? 'eigen' : 'image' }), 1e-11, `${tag} ${upper ? 'øvre' : 'nedre'} ved treff`);
      }
    }
  }
});

// MC med mange steg: i hvert steg vektes treff av øvre/nedre barriere med bro-sannsynlighetene.
function mcDoubleBinary({ S, L, U, T, r, b, v, steps, n, seed }) {
  const rng = createRng(seed);
  const dt = T / steps;
  const drift = (b - v * v / 2) * dt;
  const sd = v * Math.sqrt(dt);
  const lnL = Math.log(L);
  const lnU = Math.log(U);
  const keys = ['ko', 'upper-hit', 'lower-hit', 'upper-exp', 'lower-exp'];
  const accs = Object.fromEntries(keys.map((k) => [k, accumulator()]));
  const zs = new Float64Array(steps);
  for (let i = 0; i < n / 2; i++) {
    for (let j = 0; j < steps; j++) zs[j] = rng.normal();
    const sum = Object.fromEntries(keys.map((k) => [k, 0]));
    for (const sg of [1, -1]) {
      let x = Math.log(S);
      let surv = 1;
      for (let j = 0; j < steps && surv > 0; j++) {
        const nx = x + drift + sd * sg * zs[j];
        const pU = bridgeHitProb(x, nx, lnU, v, dt);
        const pL = bridgeHitProb(x, nx, lnL, v, dt);
        const qU = surv * pU * (1 - 0.5 * pL);
        const qL = surv * pL * (1 - 0.5 * pU);
        const disc = Math.exp(-r * (j + 0.5) * dt);
        sum['upper-hit'] += 0.5 * qU * disc;
        sum['lower-hit'] += 0.5 * qL * disc;
        sum['upper-exp'] += 0.5 * qU * Math.exp(-r * T);
        sum['lower-exp'] += 0.5 * qL * Math.exp(-r * T);
        surv *= (1 - pU) * (1 - pL);
        x = nx;
      }
      sum.ko += 0.5 * surv * Math.exp(-r * T);
    }
    for (const k of keys) accs[k].add(sum[k]);
  }
  return Object.fromEntries(keys.map((k) => [k, accs[k].result()]));
}

test('Dobbel-barriere binær mot MC med brownsk bro (alle typer)', () => {
  const sets = [
    { S: 100, L: 85, U: 115, K: 10, T: 0.25, r: 0.05, b: 0.03, v: 0.2 },
    { S: 100, L: 90, U: 125, K: 10, T: 1, r: 0.08, b: -0.04, v: 0.25 },
  ];
  sets.forEach((p, i) => {
    const mc = mcDoubleBinary({ ...p, steps: 200, n: 20000, seed: 700 + i });
    for (const kind of ['ko', 'upper-hit', 'lower-hit', 'upper-exp', 'lower-exp']) {
      const est = { mean: p.K * mc[kind].mean, se: p.K * mc[kind].se };
      withinMC(est, doubleBarrierBinary({ ...p, kind }), 4, 2e-3, `sett ${i} ${kind}`);
    }
    // Knock-out med ett eksakt brosteg (overlevelse i korridoren fra bilderekken).
    const rng = createRng(710 + i);
    const acc = accumulator();
    const x0 = Math.log(p.S);
    const m = x0 + (p.b - p.v * p.v / 2) * p.T;
    const sdT = p.v * Math.sqrt(p.T);
    const lo = Math.log(p.L);
    const hi = Math.log(p.U);
    const s2 = p.v * p.v * p.T;
    for (let k = 0; k < 100000; k++) {
      const z = rng.normal();
      let y = 0;
      for (const x1 of [m + sdT * z, m - sdT * z]) {
        if (x1 <= lo || x1 >= hi) continue;
        let surv = 0;
        for (let j = -4; j <= 4; j++) {
          const d = hi - lo;
          surv += Math.exp(-2 * j * d * (j * d + x1 - x0) / s2) - Math.exp(-2 * (x0 - lo + j * d) * (x1 - lo + j * d) / s2);
        }
        y += 0.5 * surv;
      }
      acc.add(y);
    }
    withinMC(acc.result(p.K * Math.exp(-p.r * p.T)), doubleBarrierBinary({ ...p, kind: 'ko' }), 4, 1e-6, `sett ${i} knock-out ett steg`);
  });
});

test('Dobbel-barriere binær: grensetilfeller mot enkel barriere, uendelig horisont og paritet', () => {
  const p = { K: 10, T: 0.5, r: 0.1, b: 0.1, v: 0.2 };
  // Nedre barriere svært langt unna: øvre barriere alene (Reiner–Rubinstein type 2, 6 og 10).
  const up = { ...p, S: 95, L: 1e-3, U: 100 };
  const single = { ...p, H: 100, X: 100 };
  close(doubleBarrierBinary({ ...up, kind: 'upper-hit' }), binaryBarrier({ ...single, kind: 2, S: 95 }), 1e-10, 'type 2');
  close(doubleBarrierBinary({ ...up, kind: 'upper-exp' }), binaryBarrier({ ...single, kind: 6, S: 95 }), 1e-10, 'type 6');
  close(doubleBarrierBinary({ ...up, kind: 'ko' }), binaryBarrier({ ...single, kind: 10, S: 95 }), 1e-10, 'type 10');
  close(firstHitValue({ ...up, upper: true, rate: p.r, method: 'eigen' }) * p.K, binaryBarrier({ ...single, kind: 2, S: 95 }), 1e-9, 'type 2 egenfunksjoner');
  close(huiKnockOut(up), binaryBarrier({ ...single, kind: 10, S: 95 }), 1e-9, 'type 10 Hui');
  // Øvre barriere svært langt unna: nedre barriere alene (type 1, 5 og 9).
  const down = { ...p, S: 105, L: 100, U: 1e6 };
  close(doubleBarrierBinary({ ...down, kind: 'lower-hit' }), binaryBarrier({ ...single, kind: 1, S: 105 }), 1e-10, 'type 1');
  close(doubleBarrierBinary({ ...down, kind: 'lower-exp' }), binaryBarrier({ ...single, kind: 5, S: 105 }), 1e-10, 'type 5');
  close(doubleBarrierBinary({ ...down, kind: 'ko' }), binaryBarrier({ ...single, kind: 9, S: 105 }), 1e-10, 'type 9');
  // Uendelig horisont: K · e^{c(Z−x)} sinh(γx)/sinh(γZ), og «gambler's ruin» for sannsynligheten.
  const q = { S: 100, L: 80, U: 125, T: 200, b: 0.03, v: 0.25 };
  const c = (q.b - q.v * q.v / 2) / (q.v * q.v);
  const x = Math.log(q.S / q.L);
  const Z = Math.log(q.U / q.L);
  const gamma = Math.sqrt(c * c + 2 * 0.05 / (q.v * q.v));
  close(firstHitValue({ ...q, upper: true, rate: 0.05 }), Math.exp(c * (Z - x)) * Math.sinh(gamma * x) / Math.sinh(gamma * Z), 1e-12, 'uendelig horisont');
  close(firstHitValue({ ...q, upper: true, rate: 0 }), (1 - Math.exp(-2 * c * x)) / (1 - Math.exp(-2 * c * Z)), 1e-12, 'gambler\'s ruin');
  // Paritet: knock-in = K e^{−rT} − knock-out = forfallsvariantene summert; one-touch = sum ved treff.
  const s = { S: 100, L: 85, U: 120, K: 10, T: 0.75, r: 0.06, b: 0.01, v: 0.3 };
  const val = (kind) => doubleBarrierBinary({ ...s, kind });
  close(val('ki') + val('ko'), s.K * Math.exp(-s.r * s.T), 1e-12, 'inn + ut');
  close(val('ki'), val('upper-exp') + val('lower-exp'), 1e-11, 'knock-in = øvre + nedre ved forfall');
  close(val('touch'), val('upper-hit') + val('lower-hit'), 1e-12, 'one-touch');
  assert.ok(val('upper-hit') > val('upper-exp') && val('lower-hit') > val('lower-exp'), 'betaling ved treff er verdt mer enn ved forfall når r > 0');
  // Spot utenfor korridoren og T → 0.
  const out = { ...s, S: 130 };
  const expect = { ko: 0, ki: 10 * Math.exp(-0.045), touch: 10, 'upper-hit': 10, 'lower-hit': 0, 'upper-exp': 10 * Math.exp(-0.045), 'lower-exp': 0 };
  for (const kind of DOUBLE_BINARY_KINDS) close(doubleBarrierBinary({ ...out, kind }), expect[kind], 1e-12, `utenfor ${kind}`);
  close(doubleBarrierBinary({ ...s, T: 1e-8, kind: 'ko' }), s.K, 1e-6, 'T → 0 knock-out');
  close(doubleBarrierBinary({ ...s, T: 1e-8, kind: 'touch' }), 0, 1e-6, 'T → 0 one-touch');
});
