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
  partialTimeBarrier, PARTIAL_TIME_KINDS, lookBarrier, partialFixedLookback, softBarrier, hitDiscountValue,
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

test('Standard barriere: én verdi per type fra bokas tabell (S = 100, K = 3, T = 0,5, r = 0,08, b = 0,04)', () => {
  const points = [
    ['call', 'do', 95, 90, 0.25, 9.0246],
    ['call', 'uo', 105, 100, 0.25, 2.358],
    ['call', 'di', 95, 110, 0.3, 2.8517],
    ['call', 'ui', 105, 90, 0.3, 15.2098],
    ['put', 'do', 95, 100, 0.25, 2.2947],
    ['put', 'uo', 105, 110, 0.3, 7.5649],
    ['put', 'di', 95, 90, 0.25, 2.9586],
    ['put', 'ui', 105, 100, 0.3, 4.4226],
  ];
  for (const [type, barrier, H, X, v, expected] of points) {
    const val = standardBarrier({ type, barrier, S: 100, X, H, K: 3, T: 0.5, r: 0.08, b: 0.04, v });
    close(val, expected, 1e-4, `${type} ${barrier} H=${H} X=${X} σ=${v}`);
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

test('Rabatt ved treff: numerisk integrasjon = lukket form, og negativ rente under terskelen', () => {
  for (const [a, nu, v, rate, T] of [[-0.05, 0.02, 0.25, 0.08, 0.5], [0.1, -0.03, 0.4, 0.03, 2], [-1e-6, 0.01, 0.2, 0.05, 1], [0.3, 0.05, 0.1, 0.1, 0.25]]) {
    close(hitDiscountValue({ a, nu, v, rate, T, numeric: true }), hitDiscountValue({ a, nu, v, rate, T }), 1e-12, `a=${a}`);
  }
  // Med b = 0 og σ = 0,1 er terskelen r = −μ²σ²/2 = −0,000125; prisen skal være glatt over den.
  const p = { type: 'call', barrier: 'do', S: 100, X: 100, H: 95, K: 3, T: 1, b: 0, v: 0.1 };
  const f = (r) => standardBarrier({ ...p, r });
  const h = 5e-5;
  const r0 = -0.000125;
  close(f(r0), 0.5 * (f(r0 - h) + f(r0 + h)), 1e-8, 'glatt over terskelen');
  // Og mot MC: rabatten ved treff med r = −0,02 (betydelig under terskelen).
  const q = { ...p, r: -0.02, X: 100 };
  const steps = 200;
  const dt = q.T / steps;
  const rng = createRng(91);
  const lnH = Math.log(q.H);
  const acc = accumulator();
  for (let i = 0; i < 10000; i++) {
    const zs = Array.from({ length: steps }, () => rng.normal());
    let y = 0;
    for (const sg of [1, -1]) {
      let x = Math.log(q.S);
      let surv = 1;
      let reb = 0;
      for (let j = 0; j < steps; j++) {
        const nx = x + (q.b - q.v * q.v / 2) * dt + q.v * Math.sqrt(dt) * sg * zs[j];
        const ph = bridgeHitProb(x, nx, lnH, q.v, dt);
        reb += surv * ph * q.K * Math.exp(-q.r * (j + 0.5) * dt);
        surv *= 1 - ph;
        x = nx;
      }
      y += 0.5 * reb;
    }
    acc.add(y);
  }
  withinMC(acc.result(), standardBarrier(q) - standardBarrier({ ...q, K: 0 }), 4, 1e-3, 'rabatt ved r = −0,02');
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

// --- Dobbel barriere ------------------------------------------------------------------

test('Dobbel barriere: et utvalg fra bokas tabell (call, S = X = 100, r = b = 0,1, flate barrierer)', () => {
  const points = [
    [50, 150, 0.25, 0.15, 4.3515],
    [70, 130, 0.5, 0.25, 4.0004],
    [80, 120, 0.25, 0.25, 2.6387],
    [90, 110, 0.25, 0.15, 1.2055],
  ];
  for (const [L, U, T, v, expected] of points) {
    close(doubleBarrier({ type: 'call', kind: 'out', S: 100, X: 100, L, U, T, r: 0.1, b: 0.1, v }), expected, 1e-4, `L=${L} U=${U} T=${T} σ=${v}`);
  }
});

// MC for dobbel barriere. Flate barrierer: ett steg med eksakt overlevelse for broen.
// Krumme barrierer (lineære i ln S): mange steg, eksakt bro mot hver rett linje for seg.
function mcDoubleBarrier({ type, kind, S, X, L, U, T, r, b, v, delta1 = 0, delta2 = 0, steps = 1, n, seed }) {
  const rng = createRng(seed);
  const dt = T / steps;
  const drift = (b - v * v / 2) * dt;
  const sd = v * Math.sqrt(dt);
  const s2 = v * v * dt;
  const lnL = Math.log(L);
  const lnU = Math.log(U);
  const acc = accumulator();
  const zs = new Float64Array(steps);
  for (let i = 0; i < n / 2; i++) {
    for (let j = 0; j < steps; j++) zs[j] = rng.normal();
    let y = 0;
    for (const sg of [1, -1]) {
      let x = Math.log(S);
      let surv = 1;
      for (let j = 0; j < steps; j++) {
        const nx = x + drift + sd * sg * zs[j];
        const t0 = j * dt;
        const t1 = t0 + dt;
        if (delta1 === 0 && delta2 === 0) {
          surv *= bridgeSurvival2(x, nx, lnL, lnU, s2);
        } else {
          const u0 = lnU + delta1 * t0 - x;
          const u1 = lnU + delta1 * t1 - nx;
          const l0 = x - lnL - delta2 * t0;
          const l1 = nx - lnL - delta2 * t1;
          surv *= (u0 > 0 && u1 > 0 && l0 > 0 && l1 > 0)
            ? (1 - Math.exp(-2 * u0 * u1 / s2)) * (1 - Math.exp(-2 * l0 * l1 / s2)) : 0;
        }
        x = nx;
      }
      y += payoff(type, Math.exp(x), X) * (kind === 'out' ? surv : 1 - surv);
    }
    acc.add(y / 2);
  }
  return acc.result(Math.exp(-r * T));
}

test('Dobbel barriere mot MC med brownsk bro (flate og krumme barrierer)', () => {
  let seed = 200;
  const flat = [
    { S: 100, X: 100, L: 80, U: 120, T: 0.5, r: 0.1, b: 0.1, v: 0.25 },
    { S: 100, X: 85, L: 90, U: 125, T: 1, r: 0.05, b: -0.03, v: 0.2 }, // X < L
    { S: 100, X: 130, L: 75, U: 125, T: 0.75, r: 0.05, b: 0.02, v: 0.3 }, // X > U
  ];
  for (const p of flat) {
    for (const type of ['call', 'put']) {
      for (const kind of ['out', 'in']) {
        const q = { ...p, type, kind };
        withinMC(mcDoubleBarrier({ ...q, n: 200000, seed: seed++ }), doubleBarrier(q), 4, 1e-4, `${type} ${kind} X=${p.X}`);
      }
    }
  }
  const curved = [
    { S: 100, X: 100, L: 80, U: 120, T: 0.5, r: 0.1, b: 0.1, v: 0.25, delta1: 0.1, delta2: -0.1 },
    { S: 100, X: 95, L: 85, U: 115, T: 0.5, r: 0.1, b: 0.05, v: 0.2, delta1: -0.1, delta2: 0.1 },
    { S: 100, X: 105, L: 80, U: 125, T: 1, r: 0.05, b: 0.05, v: 0.25, delta1: 0.15, delta2: 0.05 },
  ];
  for (const p of curved) {
    for (const type of ['call', 'put']) {
      const q = { ...p, type, kind: 'out' };
      withinMC(mcDoubleBarrier({ ...q, steps: 100, n: 40000, seed: seed++ }), doubleBarrier(q), 4, 5e-4, `${type} δ1=${p.delta1} δ2=${p.delta2}`);
    }
  }
});

test('Dobbel barriere: inn + ut = vanilla, og grensetilfeller mot enkel barriere', () => {
  const p = { S: 100, X: 100, T: 0.5, r: 0.08, b: 0.03, v: 0.3 };
  for (const type of ['call', 'put']) {
    const q = { ...p, type, L: 85, U: 120, delta1: 0.05, delta2: -0.02 };
    close(doubleBarrier({ ...q, kind: 'out' }) + doubleBarrier({ ...q, kind: 'in' }), gbsm({ ...p, type }), 1e-12, `${type} paritet`);
    // Nedre barriere svært langt unna: opp-og-ut. Øvre langt unna: ned-og-ut.
    close(doubleBarrier({ ...p, type, L: 1, U: 125 }), standardBarrier({ ...p, type, barrier: 'uo', H: 125, K: 0 }), 1e-10, `${type} som opp-og-ut`);
    close(doubleBarrier({ ...p, type, L: 82, U: 1e4 }), standardBarrier({ ...p, type, barrier: 'do', H: 82, K: 0 }), 1e-10, `${type} som ned-og-ut`);
    close(doubleBarrier({ ...p, type, L: 1, U: 1e4 }), gbsm({ ...p, type }), 1e-10, `${type} som vanilla`);
    // Spot utenfor korridoren.
    assert.equal(doubleBarrier({ ...p, type, L: 101, U: 130 }), 0);
    close(doubleBarrier({ ...p, type, kind: 'in', L: 70, U: 99 }), gbsm({ ...p, type }), 0);
  }
  assert.throws(() => doubleBarrier({ ...p, type: 'call', L: 90, U: 110, delta1: -1, delta2: 1, T: 1 }), /krysser/);
});

// --- Partial-time barrierer ------------------------------------------------------------

// To steg (0 → t1 → T2) med brownsk bro er eksakt for alle typene.
function mcPartialTime({ S, t1, T2, r, b, v, n, seed, cases }) {
  const rng = createRng(seed);
  const nu = b - v * v / 2;
  const sd1 = v * Math.sqrt(t1);
  const sd2 = v * Math.sqrt(T2 - t1);
  const x0 = Math.log(S);
  const accs = cases.map(() => accumulator());
  for (let i = 0; i < n / 2; i++) {
    const z1 = rng.normal();
    const z2 = rng.normal();
    const ys = new Float64Array(cases.length);
    for (const sg of [1, -1]) {
      const x1 = x0 + nu * t1 + sd1 * sg * z1;
      const x2 = x1 + nu * (T2 - t1) + sd2 * sg * z2;
      cases.forEach((c, k) => {
        const h = Math.log(c.H);
        const [group, dir] = c.kind.split('-');
        let surv;
        if (group === 'A') surv = 1 - bridgeHitProb(x0, x1, h, v, t1);
        else {
          const noTouch = 1 - bridgeHitProb(x1, x2, h, v, T2 - t1);
          if (group === 'B1') surv = noTouch;
          else surv = (dir[0] === 'd' ? x1 > h : x1 < h) ? noTouch : 0;
        }
        const w = dir.endsWith('i') ? 1 - surv : surv;
        ys[k] += 0.5 * w * payoff(c.type, Math.exp(x2), c.X);
      });
    }
    ys.forEach((y, k) => accs[k].add(y));
  }
  return accs.map((a) => a.result(Math.exp(-r * T2)));
}

test('Partial-time barriere mot MC (alle typer A, B1, B2, call og put)', () => {
  const base = { S: 100, t1: 0.4, T2: 1, r: 0.1, b: 0.05, v: 0.25 };
  const cases = [];
  for (const kind of PARTIAL_TIME_KINDS) {
    const hs = kind.startsWith('A') ? [kind[2] === 'd' ? 90 : 110] : [90, 110];
    for (const H of hs) for (const X of [85, 100, 115]) for (const type of ['call', 'put']) cases.push({ kind, H, X, type });
  }
  const mc = mcPartialTime({ ...base, n: 200000, seed: 300, cases });
  cases.forEach((c, k) => {
    withinMC(mc[k], partialTimeBarrier({ ...base, ...c }), 4, 1e-4, `${c.kind} ${c.type} H=${c.H} X=${c.X}`);
  });
  // Et sett med negativ carry og kort t1.
  const base2 = { S: 50, t1: 0.1, T2: 0.75, r: 0.03, b: -0.04, v: 0.35 };
  const cases2 = ['A-do', 'B1-o', 'B2-do', 'B2-uo'].flatMap((kind) => ['call', 'put'].map((type) => ({ kind, type, H: 45, X: 48 })));
  const mc2 = mcPartialTime({ ...base2, n: 200000, seed: 301, cases: cases2 });
  cases2.forEach((c, k) => withinMC(mc2[k], partialTimeBarrier({ ...base2, ...c }), 4, 1e-4, `sett 2 ${c.kind} ${c.type}`));
});

test('Partial-time barriere: grensetilfeller mot standard barriere og vanilla', () => {
  const p = { S: 100, H: 90, r: 0.1, b: 0.05, v: 0.25, T2: 1 };
  const std = (o) => standardBarrier({ ...p, T: 1, K: 0, ...o });
  for (const type of ['call', 'put']) {
    for (const X of [85, 100]) {
      // Type A med t1 = T2 er en vanlig barriereopsjon.
      close(partialTimeBarrier({ ...p, type, X, kind: 'A-do', t1: 1 }), std({ type, X, barrier: 'do' }), 1e-10, `A-do ${type} X=${X}`);
      close(partialTimeBarrier({ ...p, type, X, H: 115, kind: 'A-uo', t1: 1 }), std({ type, X, H: 115, barrier: 'uo' }), 1e-10, `A-uo ${type} X=${X}`);
      // Type B med t1 → 0 er en vanlig barriereopsjon (B1 med S > H er ned-og-ut).
      close(partialTimeBarrier({ ...p, type, X, kind: 'B2-do', t1: 1e-10 }), std({ type, X, barrier: 'do' }), 1e-6, `B2-do ${type} X=${X}`);
      close(partialTimeBarrier({ ...p, type, X, H: 115, kind: 'B2-uo', t1: 1e-10 }), std({ type, X, H: 115, barrier: 'uo' }), 1e-6, `B2-uo ${type} X=${X}`);
      close(partialTimeBarrier({ ...p, type, X, kind: 'B1-o', t1: 1e-10 }), std({ type, X, barrier: 'do' }), 1e-6, `B1 ${type} X=${X}`);
      // Inn + ut = vanilla, og barriere langt unna gir vanilla.
      const van = gbsm({ ...p, type, X, T: 1 });
      for (const [o, i] of [['A-do', 'A-di'], ['B1-o', 'B1-i'], ['B2-do', 'B2-di'], ['B2-uo', 'B2-ui']]) {
        close(partialTimeBarrier({ ...p, type, X, kind: o, t1: 0.3 }) + partialTimeBarrier({ ...p, type, X, kind: i, t1: 0.3 }), van, 1e-12, `${o}+${i}`);
      }
      close(partialTimeBarrier({ ...p, type, X, H: 1, kind: 'A-do', t1: 0.5 }), van, 1e-10, 'fjern barriere A');
      close(partialTimeBarrier({ ...p, type, X, H: 1, kind: 'B1-o', t1: 0.5 }), van, 1e-10, 'fjern barriere B1');
      // Allerede truffet for type A.
      assert.equal(partialTimeBarrier({ ...p, type, X, H: 101, kind: 'A-do', t1: 0.5 }), 0);
      close(partialTimeBarrier({ ...p, type, X, H: 101, kind: 'A-di', t1: 0.5 }), van, 0);
    }
  }
});

// --- Look-barrier ----------------------------------------------------------------------

// Fast-strike lookback (Conze og Viswanathan 1991) med løpende maks/min m. Uavhengig av modellkoden.
function fixedLookback(type, S, m, X, T, r, b, v) {
  const sq = v * Math.sqrt(T);
  const a = v * v / (2 * b);
  const p2 = -2 * b / (v * v);
  if (type === 'call') {
    const K = Math.max(X, m);
    const d1 = (Math.log(S / K) + (b + v * v / 2) * T) / sq;
    return Math.exp(-r * T) * Math.max(m - X, 0) + S * Math.exp((b - r) * T) * cnd(d1) - K * Math.exp(-r * T) * cnd(d1 - sq)
      + S * Math.exp(-r * T) * a * (-((S / K) ** p2) * cnd(d1 - 2 * b * Math.sqrt(T) / v) + Math.exp(b * T) * cnd(d1));
  }
  const K = Math.min(X, m);
  const d1 = (Math.log(S / K) + (b + v * v / 2) * T) / sq;
  return Math.exp(-r * T) * Math.max(X - m, 0) - S * Math.exp((b - r) * T) * cnd(-d1) + K * Math.exp(-r * T) * cnd(-d1 + sq)
    + S * Math.exp(-r * T) * a * ((S / K) ** p2 * cnd(-d1 + 2 * b * Math.sqrt(T) / v) - Math.exp(b * T) * cnd(-d1));
}

// Look-barrier som integral over S_{t1} av utslått tetthet ganger lookback-verdien ved t1.
function lookBarrierByIntegration({ kind, S, X, H, t1, T2, r, b, v }) {
  const call = kind[0] === 'c';
  const nu = b - v * v / 2;
  const s1 = v * Math.sqrt(t1);
  const h = Math.log(H / S);
  const k = Math.log(X / S);
  const dens = (y) => (Math.exp(-0.5 * ((y - nu * t1) / s1) ** 2)
    - Math.exp(2 * nu * h / (v * v)) * Math.exp(-0.5 * ((y - 2 * h - nu * t1) / s1) ** 2)) / (s1 * Math.sqrt(2 * Math.PI));
  const f = (y) => dens(y) * fixedLookback(call ? 'call' : 'put', S * Math.exp(y), S * Math.exp(y), X, T2 - t1, r, b, v);
  const far = nu * t1 + (call ? -12 : 12) * s1;
  const [lo, hi] = call ? [far, h] : [h, far];
  const mid = Math.min(Math.max(k, lo), hi); // knekk i lookback-verdien ved S_{t1} = X
  const I = gaussLegendreComposite(f, lo, mid, 40, 20) + gaussLegendreComposite(f, mid, hi, 40, 20);
  return Math.exp(-r * t1) * I;
}

// To steg med eksakt bro: overlevelse i [0, t1] og maks/min i [t1, T2] trukket fra broen.
function mcLookBarrier({ kind, S, X, H, t1, T2, r, b, v, n, seed }) {
  const rng = createRng(seed);
  const nu = b - v * v / 2;
  const tau = T2 - t1;
  const x0 = Math.log(S);
  const lnH = Math.log(H);
  const call = kind[0] === 'c';
  const knockIn = kind[2] === 'i';
  const acc = accumulator();
  for (let i = 0; i < n / 2; i++) {
    const z1 = rng.normal();
    const z2 = rng.normal();
    const u = rng.uniform();
    let y = 0;
    for (const sg of [1, -1]) {
      const x1 = x0 + nu * t1 + v * Math.sqrt(t1) * sg * z1;
      const x2 = x1 + nu * tau + v * Math.sqrt(tau) * sg * z2;
      const surv = 1 - bridgeHitProb(x0, x1, lnH, v, t1);
      const ext = Math.exp(bridgeExtreme(x1, x2, v * v * tau, u, call));
      y += 0.5 * (knockIn ? 1 - surv : surv) * payoff(call ? 'call' : 'put', ext, X);
    }
    acc.add(y);
  }
  return acc.result(Math.exp(-r * T2));
}

test('Look-barrier mot MC og mot numerisk integrasjon over S(t1)', () => {
  const sets = [
    { S: 100, X: 100, t1: 0.5, T2: 1, r: 0.1, b: 0.1, v: 0.15, Hc: 130, Hp: 80 },
    { S: 100, X: 95, t1: 0.25, T2: 1, r: 0.05, b: -0.03, v: 0.3, Hc: 120, Hp: 85 },
    { S: 100, X: 125, t1: 0.75, T2: 1.5, r: 0.03, b: 0.02, v: 0.25, Hc: 115, Hp: 90 }, // X > H for call
    { S: 100, X: 105, t1: 0.5, T2: 1, r: 0.06, b: 0, v: 0.2, Hc: 125, Hp: 85 }, // b = 0 (glattet)
  ];
  let seed = 400;
  for (const s of sets) {
    for (const kind of ['cuo', 'cui', 'pdo', 'pdi']) {
      const p = { ...s, kind, H: kind[0] === 'c' ? s.Hc : s.Hp };
      const val = lookBarrier(p);
      withinMC(mcLookBarrier({ ...p, n: 200000, seed: seed++ }), val, 4, 1e-4, `${kind} X=${s.X} b=${s.b}`);
      if (kind[2] === 'o' && s.b !== 0) close(val, lookBarrierByIntegration(p), 1e-8, `${kind} integrasjon X=${s.X}`);
    }
  }
});

test('Look-barrier: grensetilfeller (t1 → T2, t1 → 0, H → ∞) og inn + ut', () => {
  const p = { S: 100, X: 100, T2: 1, r: 0.1, b: 0.1, v: 0.2 };
  close(lookBarrier({ ...p, kind: 'cuo', H: 130, t1: 1 }), standardBarrier({ ...p, type: 'call', barrier: 'uo', H: 130, K: 0, T: 1 }), 1e-12, 't1 = T2 call');
  close(lookBarrier({ ...p, kind: 'pdo', H: 80, t1: 1 }), standardBarrier({ ...p, type: 'put', barrier: 'do', H: 80, K: 0, T: 1 }), 1e-12, 't1 = T2 put');
  // Kontinuitet mot t1 = T2 (lookback over et kort intervall gir bare et tillegg av orden σ√τ).
  close(lookBarrier({ ...p, kind: 'cuo', H: 130, t1: 1 - 1e-10 }), lookBarrier({ ...p, kind: 'cuo', H: 130, t1: 1 }), 1e-3, 't1 → T2');
  for (const type of ['call', 'put']) {
    // t1 → 0: partiell lookback blir en vanlig fast-strike lookback over [0, T2].
    close(partialFixedLookback({ ...p, type, t1: 1e-10 }), fixedLookback(type, 100, 100, 100, 1, 0.1, 0.1, 0.2), 1e-6, `${type} t1 → 0`);
    // Partiell lookback mot integral av lookback-verdien ved t1 (ingen barriere).
    for (const t1 of [0.3, 0.7]) {
      const nu = p.b - p.v * p.v / 2;
      const s1 = p.v * Math.sqrt(t1);
      const f = (z) => Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI)
        * fixedLookback(type, 100 * Math.exp(nu * t1 + s1 * z), 100 * Math.exp(nu * t1 + s1 * z), 100, 1 - t1, 0.1, 0.1, 0.2);
      const zk = -(nu * t1) / s1;
      const I = Math.exp(-0.1 * t1) * (gaussLegendreComposite(f, -12, zk, 40, 20) + gaussLegendreComposite(f, zk, 12, 40, 20));
      close(partialFixedLookback({ ...p, type, t1 }), I, 1e-8, `${type} partiell t1=${t1}`);
    }
  }
  for (const [o, i, H] of [['cuo', 'cui', 125], ['pdo', 'pdi', 85]]) {
    const q = { ...p, H, t1: 0.4 };
    const type = o[0] === 'c' ? 'call' : 'put';
    close(lookBarrier({ ...q, kind: o }) + lookBarrier({ ...q, kind: i }), partialFixedLookback({ ...q, type }), 1e-12, `${o}+${i}`);
    close(lookBarrier({ ...q, kind: o, H: o === 'cuo' ? 1e5 : 1e-3 }), partialFixedLookback({ ...q, type }), 1e-9, `${o} H → ∞`);
    // Allerede truffet: ut = 0, inn = partiell lookback.
    assert.equal(lookBarrier({ ...q, kind: o, H: 100 }), 0);
  }
  // b = 0 er en hevbar singularitet: glatt overgang.
  // Richardson-ekstrapolasjon av symmetriske gjennomsnitt rundt b = 0 fjerner O(h²)-leddet.
  const g = (bb) => lookBarrier({ ...p, b: bb, kind: 'cuo', H: 130, t1: 0.5 });
  const avg = (h) => 0.5 * (g(h) + g(-h));
  close(g(0), (4 * avg(2e-4) - avg(4e-4)) / 3, 1e-8, 'b = 0');
});

// --- Soft-barrier ----------------------------------------------------------------------

// Ett steg med eksakt bro-minimum/-maksimum gir eksakt andel innslått.
function mcSoftBarrier({ kind, S, X, U, L, T, r, b, v, n, seed }) {
  const rng = createRng(seed);
  const x0 = Math.log(S);
  const m = x0 + (b - v * v / 2) * T;
  const sd = v * Math.sqrt(T);
  const call = kind[0] === 'c';
  const acc = accumulator();
  for (let i = 0; i < n / 2; i++) {
    const z = rng.normal();
    const u = rng.uniform();
    let y = 0;
    for (const x1 of [m + sd * z, m - sd * z]) {
      const ext = Math.exp(bridgeExtreme(x0, x1, v * v * T, u, !call));
      const frac = Math.min(Math.max(call ? (U - ext) / (U - L) : (ext - L) / (U - L), 0), 1);
      y += 0.5 * (kind[2] === 'i' ? frac : 1 - frac) * payoff(call ? 'call' : 'put', Math.exp(x1), X);
    }
    acc.add(y);
  }
  return acc.result(Math.exp(-r * T));
}

test('Soft-barrier mot MC med brownsk bro', () => {
  const base = { S: 100, T: 0.5, r: 0.1, b: 0.05, v: 0.2 };
  const cases = [
    { kind: 'cdi', X: 100, U: 95, L: 85 }, { kind: 'cdo', X: 100, U: 95, L: 85 },
    { kind: 'cdi', X: 90, U: 95, L: 80 }, { kind: 'cdo', X: 90, U: 99, L: 70 }, // X inne i området
    { kind: 'pui', X: 100, U: 115, L: 105 }, { kind: 'puo', X: 100, U: 115, L: 105 },
    { kind: 'pui', X: 110, U: 120, L: 102 }, { kind: 'puo', X: 112, U: 125, L: 101 },
    { kind: 'cdi', X: 100, U: 105, L: 90 }, { kind: 'pui', X: 100, U: 110, L: 95 }, // spot inne i området
  ];
  cases.forEach((c, i) => {
    const p = { ...base, ...c };
    withinMC(mcSoftBarrier({ ...p, n: 200000, seed: 500 + i }), softBarrier(p), 4, 1e-4, `${c.kind} X=${c.X} U=${c.U} L=${c.L}`);
  });
  // b = 0 (singulær lukket form, integreres numerisk) og negativ carry.
  for (const [i, p] of [{ ...base, b: 0, kind: 'cdo', X: 100, U: 95, L: 85 }, { ...base, b: -0.05, kind: 'puo', X: 100, U: 112, L: 104 }].entries()) {
    withinMC(mcSoftBarrier({ ...p, n: 200000, seed: 520 + i }), softBarrier(p), 4, 1e-4, `${p.kind} b=${p.b}`);
  }
});

test('Soft-barrier: lukket form mot integral av harde barrierer, og L = U gir standard barriere', () => {
  const base = { S: 100, T: 0.75, r: 0.08, b: 0.03, v: 0.3 };
  for (const [kind, X, U, L] of [['cdi', 100, 95, 80], ['cdi', 88, 96, 75], ['pui', 100, 120, 105], ['pui', 112, 118, 103]]) {
    const call = kind[0] === 'c';
    const p = { ...base, kind, X, U, L };
    const hard = (H) => standardBarrier({ ...base, type: call ? 'call' : 'put', barrier: call ? 'di' : 'ui', X, H, K: 0 });
    const avg = gaussLegendreComposite(hard, L, U, 8, 20) / (U - L);
    close(softBarrier(p), avg, 1e-9, `${kind} X=${X}`);
    close(softBarrier({ ...p, kind: call ? 'cdo' : 'puo' }) + softBarrier(p), gbsm({ ...base, type: call ? 'call' : 'put', X }), 1e-12, `${kind} inn + ut`);
  }
  // To verdier fra bokas første rad (L = U = 95): ned-og-ut call, S = X = 100, r = 0,1, b = 0,05.
  for (const [T, v, expected] of [[0.5, 0.1, 3.8075], [1, 0.3, 5.23]]) {
    close(softBarrier({ kind: 'cdo', S: 100, X: 100, U: 95, L: 95, T, r: 0.1, b: 0.05, v }), expected, 1e-4, `L = U, T=${T} σ=${v}`);
  }
  // Kontinuitet når L → U: avviket er ε/2 · ∂c/∂H til første orden.
  const p = { ...base, kind: 'cdo', X: 100, U: 95 };
  const eps = 1e-5;
  const slope = (standardBarrier({ ...base, type: 'call', barrier: 'do', X: 100, H: 95 + 1e-3, K: 0 })
    - standardBarrier({ ...base, type: 'call', barrier: 'do', X: 100, H: 95 - 1e-3, K: 0 })) / 2e-3;
  close(softBarrier({ ...p, L: 95 - eps }), softBarrier({ ...p, L: 95 }) - eps / 2 * slope, 1e-9, 'L → U');
});
