// Tester for barriereopsjonene i kapittel 4.17: bokas tabeller, Monte Carlo med brownsk bro
// (kontinuerlig overvåking), numerisk integrasjon og strukturelle identiteter.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRng } from '../src/math/rng.js';
import { cnd } from '../src/math/normal.js';
import { gaussLegendre, gaussLegendreComposite } from '../src/math/integrate.js';
import { gbsm } from '../src/models/bsm.js';
import {
  standardBarrier, barrierHitProbability, discreteBarrier, bgkAdjustedBarrier, doubleBarrier,
  partialTimeBarrier, PARTIAL_TIME_KINDS, lookBarrier, partialFixedLookback, softBarrier,
} from '../src/models/barriers.js';
import { close, withinMC, bridgeHitProb } from './helpers.js';

// --- Hjelpere ---------------------------------------------------------------------

// Akkumulerer gjennomsnitt og standardfeil.
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

const payoff = (type, ST, X) => Math.max(type === 'call' ? ST - X : X - ST, 0);

// Ekstremverdien til en brownsk bro fra x0 til x1 med varians s2 (maks hvis upper, ellers min).
function bridgeExtreme(x0, x1, s2, u, upper) {
  const root = Math.sqrt((x1 - x0) ** 2 - 2 * s2 * Math.log(u));
  return upper ? 0.5 * (x0 + x1 + root) : 0.5 * (x0 + x1 - root);
}

// P(lo < bro < hi) for en brownsk bro fra x0 til x1 med varians s2 (bilderekke, eksakt).
function bridgeSurvival2(x0, x1, lo, hi, s2) {
  if (x0 <= lo || x0 >= hi || x1 <= lo || x1 >= hi) return 0;
  const d = hi - lo;
  let p = 0;
  for (let n = -4; n <= 4; n++) {
    p += Math.exp(-2 * n * d * (n * d + x1 - x0) / s2) - Math.exp(-2 * (x0 - lo + n * d) * (x1 - lo + n * d) / s2);
  }
  return Math.min(1, Math.max(0, p));
}

// Tettheten til første treff av nivået a = ln(H/S) for ln S med drift ν (invers gauss).
const firstPassageDensity = (t, a, nu, v) => Math.abs(a) / (v * Math.sqrt(2 * Math.PI * t ** 3)) * Math.exp(-((a - nu * t) ** 2) / (2 * v * v * t));

// --- Standard barriereopsjoner -----------------------------------------------------

test('Standard barriere: bokas tabell (S = 100, K = 3, T = 0,5, r = 0,08, b = 0,04)', () => {
  const book = {
    0.25: {
      'call do 95': [9.0246, 6.7924, 4.8759], 'call do 100': [3, 3, 3], 'call uo 105': [2.6789, 2.358, 2.3453],
      'call di 95': [7.7627, 4.0109, 2.0576], 'call di 100': [13.8333, 7.8494, 3.9795], 'call ui 105': [14.1112, 8.4482, 4.591],
      'put do 95': [2.2798, 2.2947, 2.6252], 'put uo 105': [3.776, 5.4932, 7.5187],
      'put di 95': [2.9586, 6.5677, 11.9752], 'put di 100': [2.2845, 5.9085, 11.6465], 'put ui 105': [1.4653, 3.3721, 7.0846],
    },
    0.3: {
      'call do 95': [8.8334, 7.0285, 5.4137], 'call uo 105': [2.6341, 2.4389, 2.4315],
      'call di 95': [9.0093, 5.137, 2.8517], 'call di 100': [14.8816, 9.2045, 5.3043], 'call ui 105': [15.2098, 9.7278, 5.835],
      'put do 95': [2.417, 2.4258, 2.6246], 'put uo 105': [4.2293, 5.8032, 7.5649],
      'put di 95': [3.8769, 7.7989, 13.3078], 'put di 100': [3.3328, 7.2636, 12.9713], 'put ui 105': [2.0658, 4.4226, 8.3686],
    },
  };
  for (const [v, rows] of Object.entries(book)) {
    for (const [key, vals] of Object.entries(rows)) {
      const [type, barrier, H] = key.split(' ');
      [90, 100, 110].forEach((X, i) => {
        const val = standardBarrier({ type, barrier, S: 100, X, H: Number(H), K: 3, T: 0.5, r: 0.08, b: 0.04, v: Number(v) });
        close(val, vals[i], 1e-4, `${key} X=${X} σ=${v}`);
      });
    }
  }
});

// Ett steg med brownsk bro er eksakt for barriereopsjoner uten rabatt.
function mcSingleBarrier({ type, barrier, S, X, H, T, r, b, v, n = 200000, seed = 1 }) {
  const rng = createRng(seed);
  const sd = v * Math.sqrt(T);
  const x0 = Math.log(S);
  const m = x0 + (b - v * v / 2) * T;
  const lnH = Math.log(H);
  const out = barrier[1] === 'o';
  const acc = accumulator();
  for (let i = 0; i < n / 2; i++) {
    const z = rng.normal();
    let y = 0;
    for (const x1 of [m + sd * z, m - sd * z]) {
      const surv = 1 - bridgeHitProb(x0, x1, lnH, v, T);
      y += payoff(type, Math.exp(x1), X) * (out ? surv : 1 - surv);
    }
    acc.add(y / 2);
  }
  return acc.result(Math.exp(-r * T));
}

test('Standard barriere uten rabatt mot MC med brownsk bro (alle 8 typer)', () => {
  const sets = [
    { S: 100, T: 0.5, r: 0.08, b: 0.04, v: 0.3, down: 95, up: 105 },
    { S: 100, T: 1.2, r: 0.05, b: -0.02, v: 0.2, down: 88, up: 115 },
  ];
  let seed = 10;
  for (const s of sets) {
    for (const type of ['call', 'put']) {
      for (const barrier of ['do', 'di', 'uo', 'ui']) {
        const H = barrier[0] === 'd' ? s.down : s.up;
        for (const X of [H - 7, H + 7]) {
          const p = { ...s, type, barrier, X, H };
          withinMC(mcSingleBarrier({ ...p, seed: seed++ }), standardBarrier({ ...p, K: 0 }), 4, 1e-4, `${type} ${barrier} X=${X} H=${H}`);
        }
      }
    }
  }
});

test('Standard barriere: inn + ut = vanilla, og grensetilfeller', () => {
  for (const [type, X] of [['call', 90], ['call', 110], ['put', 90], ['put', 110]]) {
    const p = { type, S: 100, X, T: 0.75, r: 0.06, b: 0.01, v: 0.35, K: 0 };
    const van = gbsm(p);
    close(standardBarrier({ ...p, barrier: 'di', H: 92 }) + standardBarrier({ ...p, barrier: 'do', H: 92 }), van, 1e-12, `${type} X=${X} ned`);
    close(standardBarrier({ ...p, barrier: 'ui', H: 108 }) + standardBarrier({ ...p, barrier: 'uo', H: 108 }), van, 1e-12, `${type} X=${X} opp`);
    // Barriere langt unna: ut = vanilla, inn = 0 (pluss rabatt ved forfall for inn).
    close(standardBarrier({ ...p, barrier: 'do', H: 1 }), van, 1e-10, 'ned-og-ut fjern barriere');
    close(standardBarrier({ ...p, barrier: 'uo', H: 1e4 }), van, 1e-10, 'opp-og-ut fjern barriere');
    close(standardBarrier({ ...p, barrier: 'di', H: 1, K: 2 }), 2 * Math.exp(-p.r * p.T), 1e-10, 'ned-og-inn fjern barriere');
    // Spot allerede forbi barrieren: ut gir rabatten, inn gir vanilla.
    close(standardBarrier({ ...p, barrier: 'do', H: 101, K: 2 }), 2, 0, 'allerede truffet ut');
    close(standardBarrier({ ...p, barrier: 'ui', H: 99, K: 2 }), van, 0, 'allerede truffet inn');
    // Kontinuitet når spot nærmer seg barrieren.
    close(standardBarrier({ ...p, barrier: 'do', H: 100 * (1 - 1e-9), K: 2 }), 2, 1e-6, 'ut ved barrieren');
    close(standardBarrier({ ...p, barrier: 'di', H: 100 * (1 - 1e-9), K: 2 }), van, 1e-6, 'inn ved barrieren');
  }
});

test('Standard barriere: rabattleddene mot integral av førstepasseringstettheten', () => {
  for (const [S, H, T, r, b, v] of [[100, 95, 0.5, 0.08, 0.04, 0.25], [100, 112, 1, 0.03, -0.02, 0.4], [50, 40, 2, 0.1, 0.1, 0.2]]) {
    const a = Math.log(H / S);
    const nu = b - v * v / 2;
    const f = (t) => firstPassageDensity(t, a, nu, v);
    const atHit = gaussLegendreComposite((t) => Math.exp(-r * t) * f(t), 1e-12, T, 200, 16);
    const pHit = gaussLegendreComposite(f, 1e-12, T, 200, 16);
    close(pHit, barrierHitProbability({ S, H, T, b, v }), 1e-9, 'P(treff)');
    const down = H < S;
    for (const type of ['call', 'put']) {
      const p = { type, S, X: S, H, T, r, b, v };
      const out = down ? 'do' : 'uo';
      const inn = down ? 'di' : 'ui';
      const K = 3;
      close(standardBarrier({ ...p, barrier: out, K }) - standardBarrier({ ...p, barrier: out, K: 0 }), K * atHit, 1e-9, `${type} ${out} rabatt ved treff`);
      close(standardBarrier({ ...p, barrier: inn, K }) - standardBarrier({ ...p, barrier: inn, K: 0 }), K * Math.exp(-r * T) * (1 - pHit), 1e-9, `${type} ${inn} rabatt ved forfall`);
    }
  }
});

test('Standard barriere med rabatt ved treff mot MC med mange steg', () => {
  // Betinget MC: rabatten i steg j vektes med P(første treff i steget) fra brownsk bro.
  const p = { type: 'put', barrier: 'uo', S: 100, X: 105, H: 110, K: 4, T: 0.5, r: 0.08, b: 0.03, v: 0.3 };
  const steps = 100;
  const dt = p.T / steps;
  const rng = createRng(77);
  const lnH = Math.log(p.H);
  const drift = (p.b - p.v * p.v / 2) * dt;
  const sd = p.v * Math.sqrt(dt);
  const acc = accumulator();
  for (let i = 0; i < 20000; i++) {
    const zs = Array.from({ length: steps }, () => rng.normal());
    let y = 0;
    for (const sg of [1, -1]) {
      let x = Math.log(p.S);
      let surv = 1;
      let reb = 0;
      for (let j = 0; j < steps; j++) {
        const nx = x + drift + sd * sg * zs[j];
        const ph = bridgeHitProb(x, nx, lnH, p.v, dt);
        reb += surv * ph * p.K * Math.exp(-p.r * (j + 0.5) * dt);
        surv *= 1 - ph;
        x = nx;
      }
      y += reb + surv * payoff(p.type, Math.exp(x), p.X) * Math.exp(-p.r * p.T);
    }
    acc.add(y / 2);
  }
  withinMC(acc.result(), standardBarrier(p), 4, 2e-3, 'opp-og-ut put med rabatt');
});

test('Standard barriere: put-call-symmetri for b = 0 (statisk replikering)', () => {
  // Ned-og-inn call (X ≥ H) = (X/H) puts med innløsningskurs H²/X, og speilvendt for opp-og-inn put.
  for (const [S, X, H, T, r, v] of [[100, 100, 95, 0.5, 0.08, 0.25], [100, 120, 90, 1.5, 0.03, 0.4]]) {
    const q = { S, T, r, b: 0, v };
    close(standardBarrier({ ...q, type: 'call', barrier: 'di', X, H, K: 0 }), X / H * gbsm({ ...q, type: 'put', X: H * H / X }), 1e-12, 'cdi');
    const Hu = 2 * S - H;
    const Xu = Hu - (X - H) / 2;
    close(standardBarrier({ ...q, type: 'put', barrier: 'ui', X: Xu, H: Hu, K: 0 }), Xu / Hu * gbsm({ ...q, type: 'call', X: Hu * Hu / Xu }), 1e-12, 'pui');
  }
});

// --- Diskret overvåking (BGK) ----------------------------------------------------

function mcDiscreteBarrier({ type, barrier, S, X, H, T, r, b, v, m, n, seed }) {
  const rng = createRng(seed);
  const steps = Math.round(m * T);
  const dt = T / steps;
  const drift = (b - v * v / 2) * dt;
  const sd = v * Math.sqrt(dt);
  const lnH = Math.log(H);
  const down = barrier[0] === 'd';
  const out = barrier[1] === 'o';
  const acc = accumulator();
  const zs = new Float64Array(steps);
  for (let i = 0; i < n / 2; i++) {
    for (let j = 0; j < steps; j++) zs[j] = rng.normal();
    let y = 0;
    for (const sg of [1, -1]) {
      let x = Math.log(S);
      let hit = false;
      for (let j = 0; j < steps; j++) {
        x += drift + sd * sg * zs[j];
        if (down ? x <= lnH : x >= lnH) hit = true;
      }
      if (out ? !hit : hit) y += payoff(type, Math.exp(x), X);
    }
    acc.add(y / 2);
  }
  return acc.result(Math.exp(-r * T));
}

test('Diskret barriere: BGK-justeringen mot MC med diskret overvåking', () => {
  const cases = [
    { type: 'call', barrier: 'do', S: 100, X: 100, H: 95, T: 0.5, r: 0.08, b: 0.04, v: 0.25, m: 52 },
    { type: 'call', barrier: 'do', S: 100, X: 100, H: 95, T: 0.2, r: 0.1, b: 0.1, v: 0.3, m: 250 },
    { type: 'put', barrier: 'ui', S: 100, X: 100, H: 110, T: 0.5, r: 0.05, b: 0.02, v: 0.25, m: 12 },
  ];
  cases.forEach((c, i) => {
    const mc = mcDiscreteBarrier({ ...c, n: 60000, seed: 100 + i });
    const bgk = discreteBarrier({ ...c, K: 0, dt: 1 / c.m });
    const cont = standardBarrier({ ...c, K: 0 });
    // BGK er en tilnærming: tillat 2 % i tillegg til MC-støyen, og krev at den slår kontinuerlig pris klart.
    withinMC(mc, bgk, 4, 0.02 * mc.mean, `${c.type} ${c.barrier} m=${c.m}`);
    assert.ok(Math.abs(bgk - mc.mean) < 0.25 * Math.abs(cont - mc.mean), `${c.type} ${c.barrier}: BGK ${bgk} er ikke nærmere MC ${mc.mean} enn kontinuerlig ${cont}`);
  });
  // Justert barriere og grensetilfelle Δt → 0.
  close(bgkAdjustedBarrier({ H: 95, v: 0.25, dt: 1 / 52, down: true }), 95 * Math.exp(-0.5826 * 0.25 * Math.sqrt(1 / 52)), 1e-12);
  close(bgkAdjustedBarrier({ H: 105, v: 0.25, dt: 1 / 52, down: false }), 105 * Math.exp(0.5826 * 0.25 * Math.sqrt(1 / 52)), 1e-12);
  const p = { type: 'call', barrier: 'uo', S: 100, X: 100, H: 120, K: 1, T: 0.5, r: 0.05, b: 0.05, v: 0.2 };
  close(discreteBarrier({ ...p, dt: 1e-14 }), standardBarrier(p), 1e-6, 'Δt → 0');
});
