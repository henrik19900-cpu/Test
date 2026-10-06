// Kapittel 4 (unntatt barrierer, binære, lookback og asiatiske): bokas eksempler, Monte Carlo,
// numerisk integrasjon og strukturelle identiteter.
import test from 'node:test';
import assert from 'node:assert/strict';
import { close, withinMC, mcTerminal, mcPaths } from './helpers.js';
import { createRng } from '../src/math/rng.js';
import { nd } from '../src/math/normal.js';
import { gaussLegendreComposite } from '../src/math/integrate.js';
import { gbsm } from '../src/models/bsm.js';
import {
  variablePurchaseOption, executiveStockOption, moneynessOption, powerContract, powerOption,
  cappedPowerOption, poweredOption, logContract, logSContract, logOption, forwardStart, ratchet,
  fadeIn, resetStrikeType1, resetStrikeType2, timeSwitch, simpleChooser, complexChooser,
  compoundOption, holderExtendible, writerExtendible, COMPOUND_KINDS,
} from '../src/models/exotics.js';

const call = (o) => ({ type: 'call', ...o });
const put = (o) => ({ type: 'put', ...o });

// To observasjoner av GBM: S_{t1} og S_{T}. payoff(St1, ST) udiskontert, diskonteres med e^{−rT}.
// Antitetiske par.
function mcTwoDates({ S, t1, T, r, b, v, n = 200000, seed = 3, payoff }) {
  const rng = createRng(seed);
  const m1 = (b - 0.5 * v * v) * t1;
  const s1 = v * Math.sqrt(t1);
  const m2 = (b - 0.5 * v * v) * (T - t1);
  const s2 = v * Math.sqrt(T - t1);
  let sum = 0;
  let sumSq = 0;
  const pairs = Math.floor(n / 2);
  for (let i = 0; i < pairs; i++) {
    const z1 = rng.normal();
    const z2 = rng.normal();
    const a = S * Math.exp(m1 + s1 * z1);
    const a2 = S * Math.exp(m1 - s1 * z1);
    const y = 0.5 * (payoff(a, a * Math.exp(m2 + s2 * z2)) + payoff(a2, a2 * Math.exp(m2 - s2 * z2)));
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / pairs;
  const df = Math.exp(-r * T);
  return { mean: mean * df, se: Math.sqrt(Math.max(sumSq / pairs - mean * mean, 0) / pairs) * df };
}

// e^{−r t}·E[g(S_t)] ved Gauss–Legendre over standardnormal z, med valgfrie knekkpunkter i S.
function integrateAt({ S, t, r, b, v, g, kinks = [], panels = 400 }) {
  const mu = (b - 0.5 * v * v) * t;
  const sd = v * Math.sqrt(t);
  const zs = [-11, ...kinks.map((K) => (Math.log(K / S) - mu) / sd).filter((z) => z > -11 && z < 11).sort((a, c) => a - c), 11];
  let sum = 0;
  for (let i = 0; i < zs.length - 1; i++) {
    sum += gaussLegendreComposite((z) => nd(z) * g(S * Math.exp(mu + sd * z)), zs[i], zs[i + 1], panels, 16);
  }
  return Math.exp(-r * t) * sum;
}

test('Bokas eksempler (kapittel 4)', () => {
  close(executiveStockOption(call({ S: 60, X: 64, T: 2, r: 0.07, b: 0.04, v: 0.38, lambda: 0.15 })).price, 9.1244);
  close(forwardStart(call({ S: 60, alpha: 1.1, t: 0.25, T: 1, r: 0.08, b: 0.04, v: 0.3 })), 4.4064);
  close(simpleChooser({ S: 50, X: 50, t: 0.25, T: 0.5, r: 0.08, b: 0.08, v: 0.25 }), 6.1071);
  // Boka oppgir Tp = 0,5833 (7 måneder) og kritisk pris I = 51,1158. Med Tp = 7/12 treffer vi begge.
  close(complexChooser({ S: 50, Xc: 55, Xp: 48, t: 0.25, Tc: 0.5, Tp: 0.5833, r: 0.1, b: 0.05, v: 0.35 }).price, 6.0508);
  const cc = complexChooser({ S: 50, Xc: 55, Xp: 48, t: 0.25, Tc: 0.5, Tp: 7 / 12, r: 0.1, b: 0.05, v: 0.35 });
  close(cc.price, 6.0508, 5e-5);
  close(cc.I, 51.1158, 5e-5);
  // Put på call: boka trykker 21,1965. Formelen (og numerisk integrasjon, se under) gir 21,19635;
  // avviket på 1,5e-4 skyldes trolig bokas tilnærming til M(a, b; ρ).
  close(compoundOption({ kind: 'put-call', S: 500, X1: 520, X2: 50, t1: 0.25, T2: 0.5, r: 0.08, b: 0.05, v: 0.35 }).price, 21.1965, 2e-4);
  close(writerExtendible(call({ S: 80, X1: 90, X2: 82, t1: 0.5, T2: 0.75, r: 0.1, b: 0.1, v: 0.3 })).price, 6.8238);
  close(timeSwitch(call({ S: 100, X: 110, A: 5, T: 1, m: 0, dt: 1 / 365, r: 0.06, b: 0.06, v: 0.26 })).price, 1.375);
});

test('VPO mot MC og grensetilfeller', () => {
  const p = { S: 100, X: 100, D: 0.1, L: 80, U: 120, T: 1, r: 0.05, b: 0.03, v: 0.3 };
  const res = variablePurchaseOption(p);
  close(res.Nmin, 100 / (120 * 0.9), 1e-12);
  close(res.Nmax, 100 / (80 * 0.9), 1e-12);
  const shares = (ST) => Math.min(Math.max(p.X / (ST * (1 - p.D)), res.Nmin), res.Nmax);
  withinMC(mcTerminal({ ...p, n: 300000, seed: 5, payoff: (ST) => Math.max(shares(ST) * ST - p.X, 0) }), res.price, 4, 0, 'VPO');
  // Uten grenser er utbetalingen alltid X·D/(1 − D).
  const wide = variablePurchaseOption({ ...p, L: 1e-6, U: 1e9 });
  close(wide.price, p.X * p.D / (1 - p.D) * Math.exp(-p.r * p.T), 1e-8);
  // Uten rabatt: bare N_min calls med innløsningskurs U.
  close(variablePurchaseOption({ ...p, D: 0 }).price, 100 / 120 * gbsm(call({ S: 100, X: 120, T: 1, r: 0.05, b: 0.03, v: 0.3 })), 1e-10);
  assert.throws(() => variablePurchaseOption({ ...p, L: 130 }));
});

test('Ansatteopsjon: MC med tilfeldig fratredelse', () => {
  const p = call({ S: 60, X: 64, T: 2, r: 0.07, b: 0.04, v: 0.38, lambda: 0.15 });
  const rng = createRng(17);
  const n = 200000;
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    const exit = -Math.log(rng.uniform()) / p.lambda; // eksponentialfordelt sluttidspunkt
    const ST = p.S * Math.exp((p.b - 0.5 * p.v * p.v) * p.T + p.v * Math.sqrt(p.T) * rng.normal());
    const y = exit > p.T ? Math.max(ST - p.X, 0) * Math.exp(-p.r * p.T) : 0;
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / n;
  withinMC({ mean, se: Math.sqrt((sumSq / n - mean * mean) / n) }, executiveStockOption(p).price);
  close(executiveStockOption({ ...p, lambda: 0 }).price, gbsm(p), 1e-12);
});

test('Moneyness-opsjon er Black-76 per enhet forward (call) eller innløsningskurs (put)', () => {
  const T = 0.7;
  const r = 0.04;
  const v = 0.27;
  const F = 105;
  for (const L of [0.8, 1, 1.2]) {
    // Call: X = L·F, verdien er per enhet F.
    close(F * moneynessOption({ type: 'call', L, T, r, v }), gbsm({ type: 'call', S: F, X: L * F, T, r, b: 0, v }), 1e-10, `call L=${L}`);
    // Put: F = L·X, verdien er per enhet X.
    const X = F / L;
    close(X * moneynessOption({ type: 'put', L, T, r, v }), gbsm({ type: 'put', S: F, X, T, r, b: 0, v }), 1e-10, `put L=${L}`);
  }
  // Samme tall for call og put med samme L (c = p i bokas notasjon).
  close(moneynessOption({ type: 'call', L: 1.2, T, r, v }), moneynessOption({ type: 'put', L: 1.2, T, r, v }), 1e-15);
  withinMC(mcTerminal({ S: 1, T, r, b: 0, v, n: 200000, seed: 9, payoff: (FT) => Math.max(FT - 1.2, 0) }),
    moneynessOption({ type: 'call', L: 1.2, T, r, v }), 4, 0, 'MC');
});

test('Potenskontrakter og potensopsjoner mot MC og identiteter', () => {
  const base = { S: 10, X: 100, T: 0.5, r: 0.08, b: 0.06, v: 0.3, i: 2 };
  const mc = (payoff, seed) => mcTerminal({ S: base.S, T: base.T, r: base.r, b: base.b, v: base.v, n: 300000, seed, payoff });
  withinMC(mc((ST) => (ST / 11) ** 3, 1), powerContract({ ...base, X: 11, i: 3 }), 4, 0, 'potenskontrakt');
  withinMC(mc((ST) => Math.max(ST ** 2 - 100, 0), 2), powerOption(call(base)), 4, 0, 'potens call');
  withinMC(mc((ST) => Math.max(100 - ST ** 2, 0), 3), powerOption(put(base)), 4, 0, 'potens put');
  withinMC(mc((ST) => Math.min(Math.max(ST ** 2 - 100, 0), 20), 4), cappedPowerOption(call({ ...base, C: 20 })), 4, 0, 'tak call');
  withinMC(mc((ST) => Math.min(Math.max(100 - ST ** 2, 0), 20), 5), cappedPowerOption(put({ ...base, C: 20 })), 4, 0, 'tak put');
  // i = 1 gir vanlig BSM og vanlig forward.
  const p1 = { S: 100, X: 95, T: 0.75, r: 0.05, b: 0.02, v: 0.25, i: 1 };
  close(powerOption(call(p1)), gbsm(call(p1)), 1e-12);
  close(powerOption(put(p1)), gbsm(put(p1)), 1e-12);
  close(powerContract(p1), 100 / 95 * Math.exp((0.02 - 0.05) * 0.75), 1e-12);
  // Put-call-paritet: c − p = e^{−rT}E[S_T^i] − X e^{−rT}.
  const pc = powerOption(call(base)) - powerOption(put(base));
  close(pc, powerContract({ ...base, X: 1 }) - base.X * Math.exp(-base.r * base.T), 1e-10, 'paritet');
  // Tak = differanse av to potensopsjoner; stort tak = standard potensopsjon.
  close(cappedPowerOption(call({ ...base, C: 20 })), powerOption(call(base)) - powerOption(call({ ...base, X: 120 })), 1e-10);
  close(cappedPowerOption(put({ ...base, C: 30 })), powerOption(put(base)) - powerOption(put({ ...base, X: 70 })), 1e-10);
  close(cappedPowerOption(call({ ...base, C: 1e7 })), powerOption(call(base)), 1e-8);
  close(cappedPowerOption(put({ ...base, C: 150 })), powerOption(put(base)), 1e-12);
});

test('Opphøyde opsjoner (powered) mot MC', () => {
  const p = { S: 100, X: 100, T: 0.5, r: 0.08, b: 0.06, v: 0.3 };
  for (const i of [1, 2, 3]) {
    for (const type of ['call', 'put']) {
      const mc = mcTerminal({ ...p, n: 300000, seed: 10 + i, payoff: (ST) => Math.max(type === 'call' ? ST - p.X : p.X - ST, 0) ** i });
      withinMC(mc, poweredOption({ type, ...p, i }), 4, 0, `i=${i} ${type}`);
    }
  }
  close(poweredOption(call({ ...p, i: 1 })), gbsm(call(p)), 1e-10);
  // i = 2: call + put = e^{−rT}E[(S_T − X)²] (en av dem er null for hver S_T).
  const m2 = Math.exp(-p.r * p.T) * (p.S ** 2 * Math.exp((2 * p.b + p.v * p.v) * p.T) - 2 * p.X * p.S * Math.exp(p.b * p.T) + p.X ** 2);
  close(poweredOption(call({ ...p, i: 2 })) + poweredOption(put({ ...p, i: 2 })), m2, 1e-8);
});

test('Logkontrakter og log-opsjoner', () => {
  const p = { S: 100, X: 95, T: 0.5, r: 0.08, b: 0.06, v: 0.3 };
  const mc = (payoff, seed) => mcTerminal({ ...p, n: 300000, seed, payoff });
  withinMC(mc((ST) => Math.log(ST / p.X), 21), logContract(p), 4, 0, 'ln(S/X)');
  withinMC(mc((ST) => Math.log(ST), 22), logSContract(p), 4, 0, 'ln S');
  withinMC(mc((ST) => Math.max(Math.log(ST / p.X), 0), 23), logOption(call(p)), 4, 0, 'log call');
  withinMC(mc((ST) => Math.max(Math.log(p.X / ST), 0), 24), logOption(put(p)), 4, 0, 'log put');
  close(logOption(call(p)) - logOption(put(p)), logContract(p), 1e-12, 'call − put = kontrakt');
  close(logSContract(p) - logContract(p), Math.exp(-p.r * p.T) * Math.log(p.X), 1e-12);
});

test('Forward start og ratchet', () => {
  const p = { S: 60, alpha: 1.1, t: 0.25, T: 1, r: 0.08, b: 0.04, v: 0.3 };
  for (const type of ['call', 'put']) {
    const mc = mcTwoDates({ ...p, t1: p.t, seed: 31, payoff: (St, ST) => Math.max(type === 'call' ? ST - p.alpha * St : p.alpha * St - ST, 0) });
    withinMC(mc, forwardStart({ type, ...p }), 4, 0, `forward start ${type}`);
  }
  close(forwardStart(call({ ...p, t: 0 })), gbsm(call({ S: 60, X: 66, T: 1, r: 0.08, b: 0.04, v: 0.3 })), 1e-12, 't = 0');
  close(forwardStart(call({ ...p, S: 120 })), 2 * forwardStart(call(p)), 1e-12, 'homogen i S');

  const q = { S: 100, alpha: 1.05, times: [0.25, 0.5, 0.75, 1], r: 0.08, b: 0.04, v: 0.3 };
  for (const type of ['call', 'put']) {
    const mc = mcPaths({
      S: q.S, T: 1, r: q.r, b: q.b, v: q.v, steps: 4, n: 300000, seed: 37, discount: false,
      payoff: (path) => {
        let s = 0;
        for (let i = 1; i <= 4; i++) {
          const K = q.alpha * path[i - 1];
          s += Math.max(type === 'call' ? path[i] - K : K - path[i], 0) * Math.exp(-q.r * 0.25 * i);
        }
        return s;
      },
    });
    withinMC(mc, ratchet({ type, ...q }).price, 4, 0, `ratchet ${type}`);
  }
  close(ratchet(call({ ...q, times: [1] })).price, gbsm(call({ S: 100, X: 105, T: 1, r: 0.08, b: 0.04, v: 0.3 })), 1e-12);
  assert.throws(() => ratchet(call({ ...q, times: [0.5, 0.25] })));
});

test('Fade-in mot MC og grensetilfeller', () => {
  const p = { S: 100, X: 100, L: 90, H: 110, T: 0.5, n: 26, r: 0.05, b: 0.05, v: 0.2 };
  for (const [type, seed] of [['call', 2], ['put', 3]]) {
    const mc = mcPaths({
      S: p.S, T: p.T, r: p.r, b: p.b, v: p.v, steps: p.n, n: 300000, seed,
      payoff: (path) => {
        let k = 0;
        for (let i = 1; i <= p.n; i++) if (path[i] > p.L && path[i] < p.H) k++;
        return k / p.n * Math.max(type === 'call' ? path[p.n] - p.X : p.X - path[p.n], 0);
      },
    });
    withinMC(mc, fadeIn({ type, ...p }).price, 4, 0, `fade-in ${type}`);
  }
  // Uten grenser er fade-in lik vanilla.
  const wide = { ...p, L: 0, H: 1e9 };
  close(fadeIn(call(wide)).price, gbsm(call(p)), 1e-10);
  close(fadeIn(put(wide)).price, gbsm(put(p)), 1e-10);
  close(fadeIn(call(wide)).insideShare, 1, 1e-12);
  assert.ok(fadeIn(call(p)).price < gbsm(call(p)));
});

test('Reset strike type 1 og 2 mot MC', () => {
  const cases = [
    { S: 100, X: 100, tau: 0.25, T: 1, r: 0.1, b: 0.1, v: 0.3 },
    { S: 95, X: 100, tau: 0.4, T: 0.9, r: 0.05, b: 0.02, v: 0.35 },
  ];
  cases.forEach((p, k) => {
    const mc = (payoff, seed) => mcTwoDates({ ...p, t1: p.tau, n: 300000, seed, payoff });
    const reset = (type, St) => (type === 'call' ? (St < p.X ? St : p.X) : (St > p.X ? St : p.X));
    for (const type of ['call', 'put']) {
      const pay2 = (St, ST) => Math.max(type === 'call' ? ST - reset(type, St) : reset(type, St) - ST, 0);
      withinMC(mc(pay2, 40 + k), resetStrikeType2({ type, ...p }), 4, 0, `type 2 ${type} #${k}`);
      withinMC(mc((St, ST) => pay2(St, ST) / reset(type, St), 50 + k), resetStrikeType1({ type, ...p }), 4, 0, `type 1 ${type} #${k}`);
      // Tilbakestillingen kan bare hjelpe innehaveren.
      assert.ok(resetStrikeType2({ type, ...p }) > gbsm({ type, ...p }));
      assert.ok(resetStrikeType1({ type, ...p }) > gbsm({ type, ...p }) / p.X);
    }
  });
  assert.throws(() => resetStrikeType2(call({ ...cases[0], tau: 1.2 })));
});

test('Time-switch mot MC og identiteter', () => {
  const p = { S: 100, X: 110, A: 5, T: 1, m: 0, dt: 1 / 365, r: 0.06, b: 0.06, v: 0.26 };
  for (const [type, seed] of [['call', 61], ['put', 62]]) {
    const mc = mcPaths({
      S: p.S, T: p.T, r: p.r, b: p.b, v: p.v, steps: 365, n: 30000, seed,
      payoff: (path) => {
        let k = 0;
        for (let i = 1; i <= 365; i++) if (type === 'call' ? path[i] > p.X : path[i] < p.X) k++;
        return p.A * p.dt * k;
      },
    });
    withinMC(mc, timeSwitch({ type, ...p }).price, 4, 0, `time-switch ${type}`);
  }
  // call + put = A·e^{−rT}·Δt·(n + 2m): hver fiksering teller i nøyaktig én av dem.
  const sum = timeSwitch(call({ ...p, m: 7 })).price + timeSwitch(put({ ...p, m: 7 })).price;
  close(sum, p.A * Math.exp(-p.r * p.T) * p.dt * (365 + 14), 1e-10);
  close(timeSwitch(call({ ...p, X: 1e-8 })).price, p.A * Math.exp(-p.r * p.T) * 365 * p.dt, 1e-10);
});

test('Enkel chooser: dekomponering og MC', () => {
  const p = { S: 50, X: 50, t: 0.25, T: 0.5, r: 0.08, b: 0.05, v: 0.25 };
  const w = simpleChooser(p);
  // Chooser = call(X, T) + e^{(b−r)(T−t)}·put(X e^{−b(T−t)}, t)
  const dec = gbsm(call(p)) + Math.exp((p.b - p.r) * (p.T - p.t))
    * gbsm(put({ S: p.S, X: p.X * Math.exp(-p.b * (p.T - p.t)), T: p.t, r: p.r, b: p.b, v: p.v }));
  close(w, dec, 1e-12, 'dekomponering');
  const mc = mcTwoDates({
    ...p, t1: p.t, T: p.t, seed: 71,
    payoff: (St) => Math.max(gbsm(call({ ...p, S: St, T: p.T - p.t })), gbsm(put({ ...p, S: St, T: p.T - p.t }))),
  });
  withinMC(mc, w, 4, 0, 'chooser MC');
  assert.ok(w > Math.max(gbsm(call(p)), gbsm(put(p))));
  close(simpleChooser({ ...p, t: 1e-12 }), Math.max(gbsm(call(p)), gbsm(put(p))), 1e-4, 't → 0');
});

test('Kompleks chooser: MC og spesialtilfelle', () => {
  const p = { S: 50, Xc: 55, Xp: 48, t: 0.25, Tc: 0.5, Tp: 0.5833, r: 0.1, b: 0.05, v: 0.35 };
  const res = complexChooser(p);
  const at = (St, o) => gbsm({ S: St, r: p.r, b: p.b, v: p.v, ...o });
  close(at(res.I, { type: 'call', X: p.Xc, T: p.Tc - p.t }), at(res.I, { type: 'put', X: p.Xp, T: p.Tp - p.t }), 1e-9, 'I');
  const mc = mcTwoDates({
    S: p.S, t1: p.t, T: p.t, r: p.r, b: p.b, v: p.v, seed: 73,
    payoff: (St) => Math.max(at(St, { type: 'call', X: p.Xc, T: p.Tc - p.t }), at(St, { type: 'put', X: p.Xp, T: p.Tp - p.t })),
  });
  withinMC(mc, res.price, 4, 0, 'kompleks chooser MC');
  const same = complexChooser({ ...p, Xc: 50, Xp: 50, Tc: 0.5, Tp: 0.5 }).price;
  close(same, simpleChooser({ S: 50, X: 50, t: 0.25, T: 0.5, r: 0.1, b: 0.05, v: 0.35 }), 1e-9, 'lik enkel chooser');
});

test('Opsjoner på opsjoner: numerisk integrasjon, paritet og MC', () => {
  const base = { S: 500, X1: 520, X2: 50, t1: 0.25, T2: 0.5, r: 0.08, b: 0.05, v: 0.35 };
  const cases = [base, { S: 100, X1: 95, X2: 6, t1: 0.3, T2: 1.1, r: 0.03, b: -0.02, v: 0.25 }];
  for (const p of cases) {
    for (const kind of COMPOUND_KINDS) {
      const [outer, inner] = kind.split('-');
      const res = compoundOption({ kind, ...p });
      const g = (St) => {
        const u = gbsm({ type: inner, S: St, X: p.X1, T: p.T2 - p.t1, r: p.r, b: p.b, v: p.v });
        return Math.max(outer === 'call' ? u - p.X2 : p.X2 - u, 0);
      };
      const num = integrateAt({ S: p.S, t: p.t1, r: p.r, b: p.b, v: p.v, g, kinks: [res.I] });
      close(res.price, num, 1e-8, `${kind} S=${p.S}`);
    }
    // Paritet: call på X − put på X = X i dag − X2·e^{−r t1}
    for (const inner of ['call', 'put']) {
      const c = compoundOption({ kind: `call-${inner}`, ...p });
      const q = compoundOption({ kind: `put-${inner}`, ...p });
      close(c.price - q.price, c.underlying - p.X2 * Math.exp(-p.r * p.t1), 1e-9, `paritet ${inner}`);
    }
  }
  // Uavhengig MC for put på call (bokas eksempel).
  const mc = mcTwoDates({
    S: base.S, t1: base.t1, T: base.t1, r: base.r, b: base.b, v: base.v, n: 200000, seed: 79,
    payoff: (St) => Math.max(base.X2 - gbsm(call({ S: St, X: base.X1, T: base.T2 - base.t1, r: base.r, b: base.b, v: base.v })), 0),
  });
  withinMC(mc, compoundOption({ kind: 'put-call', ...base }).price, 4, 0, 'put på call MC');
  // Put med X2 over maksimal putverdi: call på put er verdiløs, put på put innløses alltid.
  const hi = { ...base, X2: 600 };
  assert.equal(compoundOption({ kind: 'call-put', ...hi }).price, 0);
  close(compoundOption({ kind: 'put-put', ...hi }).price,
    600 * Math.exp(-base.r * base.t1) - gbsm(put({ S: 500, X: 520, T: 0.5, r: 0.08, b: 0.05, v: 0.35 })), 1e-10);
});

test('Forlengbare opsjoner (innehaver): integrasjon, MC og grensetilfeller', () => {
  const cases = [
    call({ S: 100, X1: 100, X2: 105, t1: 0.5, T2: 0.75, A: 1, r: 0.08, b: 0.08, v: 0.25 }),
    put({ S: 100, X1: 100, X2: 95, t1: 0.5, T2: 0.75, A: 1, r: 0.08, b: 0.08, v: 0.25 }),
    put({ S: 100, X1: 100, X2: 105, t1: 0.5, T2: 0.75, A: 1, r: 0.08, b: 0.08, v: 0.25 }),
    // b > r: forlengelse kan også være best for høye kurser (ingen øvre kritisk pris).
    call({ S: 100, X1: 100, X2: 105, t1: 0.5, T2: 0.9, A: 2, r: 0.03, b: 0.08, v: 0.25 }),
    put({ S: 90, X1: 100, X2: 102, t1: 0.4, T2: 1, A: 0.5, r: 0.02, b: 0.07, v: 0.3 }),
  ];
  cases.forEach((p, k) => {
    const res = holderExtendible(p);
    const sign = p.type === 'call' ? 1 : -1;
    const g = (St) => Math.max(0, sign * (St - p.X1),
      gbsm({ type: p.type, S: St, X: p.X2, T: p.T2 - p.t1, r: p.r, b: p.b, v: p.v }) - p.A);
    // Uavhengig: fin Gauss–Legendre uten kjennskap til de kritiske prisene.
    const num = integrateAt({ S: p.S, t: p.t1, r: p.r, b: p.b, v: p.v, g, panels: 3000 });
    close(res.price, num, 2e-5, `integrasjon #${k}`);
    const mc = mcTwoDates({ S: p.S, t1: p.t1, T: p.t1, r: p.r, b: p.b, v: p.v, n: 100000, seed: 90 + k, payoff: g });
    withinMC(mc, res.price, 4, 0, `MC #${k}`);
    assert.ok(res.price >= res.vanilla - 1e-12, `≥ vanilla #${k}`);
  });
  const std = holderExtendible(cases[0]);
  assert.ok(std.I1 < 100 && std.I2 > 100, 'Longstaffs struktur I1 < X1 < I2');
  // Med b > r kan forlengelse også lønne seg for svært høye kurser: to adskilte områder.
  const twoRegions = holderExtendible(cases[3]).regions;
  assert.equal(twoRegions.length, 2);
  assert.equal(twoRegions[1][1], Infinity);
  assert.ok(twoRegions[0][1] > 100 && twoRegions[1][0] > twoRegions[0][1]);
  // Svært høyt gebyr: forlengelse lønner seg aldri.
  const noExt = holderExtendible({ ...cases[0], A: 1e6 });
  close(noExt.price, noExt.vanilla, 1e-12);
  assert.equal(noExt.I1, null);
});

test('Forlengbare opsjoner (utsteder): integrasjon og MC', () => {
  for (const type of ['call', 'put']) {
    const p = { type, S: 80, X1: 90, X2: 82, t1: 0.5, T2: 0.75, r: 0.1, b: 0.1, v: 0.3 };
    const res = writerExtendible(p);
    const g = (St) => (type === 'call'
      ? (St >= p.X1 ? St - p.X1 : gbsm(call({ S: St, X: p.X2, T: 0.25, r: p.r, b: p.b, v: p.v })))
      : (St <= p.X1 ? p.X1 - St : gbsm(put({ S: St, X: p.X2, T: 0.25, r: p.r, b: p.b, v: p.v }))));
    close(res.price, integrateAt({ S: p.S, t: p.t1, r: p.r, b: p.b, v: p.v, g, kinks: [p.X1] }), 1e-8, `integrasjon ${type}`);
    const mc = mcTwoDates({
      ...p, t1: p.t1, T: p.T2, seed: 99,
      payoff: (St, ST) => (type === 'call'
        ? (St >= p.X1 ? (St - p.X1) * Math.exp(p.r * (p.T2 - p.t1)) : Math.max(ST - p.X2, 0))
        : (St <= p.X1 ? (p.X1 - St) * Math.exp(p.r * (p.T2 - p.t1)) : Math.max(p.X2 - ST, 0))),
    });
    withinMC(mc, res.price, 4, 0, `MC ${type}`);
    assert.ok(res.price > res.vanilla);
  }
});
