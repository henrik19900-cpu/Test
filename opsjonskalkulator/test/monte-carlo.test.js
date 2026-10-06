// Kapittel 8: Monte Carlo. Simulatorene sjekkes mot analytiske formler, mot testhjelpernes
// uavhengige MC-motorer og (for Longstaff-Schwartz) mot et binomialtre.
import test from 'node:test';
import assert from 'node:assert/strict';
import { gbsm, gbsmGreeks } from '../src/models/bsm.js';
import {
  mcEuropean, qmcEuropean, geometricAsianDiscrete, mcAsianArithmetic, mcTwoAsset, stulz, margrabe, kirk,
  longstaffSchwartz,
} from '../src/models/monte-carlo.js';
import { close, withinMC, mcPaths, mcTwoAssets } from './helpers.js';

const H = (type, S, X, T, r, b, v) => ({ type, S, X, T, r, b, v });

// Differansen mellom to uavhengige estimater skal ligge innenfor k samlede standardfeil.
function agree(a, b, k = 4, msg = '') {
  const se = Math.sqrt(a.se ** 2 + b.se ** 2);
  assert.ok(Math.abs(a.price - b.price) <= k * se, `${msg}: ${a.price} mot ${b.price} (samlet SE ${se})`);
}

test('Europeisk MC: pris, pathwise delta og vega mot BSM', () => {
  for (const p of [H('call', 100, 100, 0.5, 0.05, 0.02, 0.3), H('put', 100, 110, 1, 0.03, 0.03, 0.2), H('call', 50, 40, 0.25, 0.08, -0.02, 0.45)]) {
    const res = mcEuropean({ ...p, paths: 200000, seed: 7 });
    const g = gbsmGreeks(p);
    withinMC({ mean: res.price, se: res.se }, g.price, 4, 0, `${p.type} pris`);
    withinMC({ mean: res.delta, se: res.deltaSe }, g.delta, 4, 0, `${p.type} delta`);
    withinMC({ mean: res.vega, se: res.vegaSe }, g.vega, 4, 0, `${p.type} vega`);
    close(res.hi - res.lo, 2 * 1.959963984540054 * res.se, 1e-12, '95 %-intervall');
  }
  // Fast seed gir samme svar; annen seed gir et annet (men like godt) svar.
  const p = { ...H('call', 100, 100, 0.5, 0.05, 0.02, 0.3), paths: 20000 };
  assert.equal(mcEuropean({ ...p, seed: 3 }).price, mcEuropean({ ...p, seed: 3 }).price);
  assert.notEqual(mcEuropean({ ...p, seed: 3 }).price, mcEuropean({ ...p, seed: 4 }).price);
  assert.throws(() => mcEuropean({ ...p, paths: 10 }));
});

test('Kvasi-tilfeldig (Halton): treffer BSM og har mye lavere feil enn vanlig MC', () => {
  for (const p of [H('call', 100, 100, 0.5, 0.05, 0.02, 0.3), H('put', 100, 90, 1, 0.05, 0.05, 0.25)]) {
    const exact = gbsm(p);
    const res = qmcEuropean({ ...p, paths: 32000, seed: 5 });
    withinMC({ mean: res.price, se: res.se }, exact, 4, 0, `${p.type} randomisert Halton`);
    withinMC({ mean: res.mcPrice, se: res.mcSe }, exact, 4, 0, `${p.type} vanlig MC`);
    assert.ok(res.se < 0.25 * res.mcSe, `QMC-feilen ${res.se} bør være langt under MC-feilen ${res.mcSe}`);
    assert.ok(Math.abs(res.plain - exact) < 0.02 * Math.max(1, exact) && Math.abs(res.plain - exact) < 2 * res.mcSe,
      `ren Halton ${res.plain} mot ${exact}`);
  }
});

test('Geometrisk asiatisk (diskret) mot MC og grensetilfelle n = 1', () => {
  close(geometricAsianDiscrete({ ...H('call', 100, 95, 0.75, 0.05, 0.02, 0.3), n: 1 }), gbsm(H('call', 100, 95, 0.75, 0.05, 0.02, 0.3)), 1e-12, 'n = 1');
  for (const [type, n] of [['call', 12], ['put', 52]]) {
    const p = H(type, 100, 100, 1, 0.05, 0.03, 0.3);
    const est = mcPaths({
      ...p, steps: n, n: 200000, seed: 9,
      payoff: (path) => {
        let s = 0;
        for (let i = 1; i <= n; i++) s += Math.log(path[i]);
        const G = Math.exp(s / n);
        return Math.max(type === 'call' ? G - p.X : p.X - G, 0);
      },
    });
    withinMC(est, geometricAsianDiscrete({ ...p, n }), 4, 0, `geometrisk ${type} n=${n}`);
  }
});

test('Aritmetisk asiatisk med kontrollvariat mot uavhengig MC', () => {
  for (const [type, X, n, v] of [['call', 100, 12, 0.3], ['put', 105, 24, 0.2], ['call', 90, 4, 0.5]]) {
    const p = H(type, 100, X, 1, 0.05, 0.05, v);
    const res = mcAsianArithmetic({ ...p, n, paths: 50000, seed: 1 });
    const ref = mcPaths({
      ...p, steps: n, n: 400000, seed: 77,
      payoff: (path) => {
        let s = 0;
        for (let i = 1; i <= n; i++) s += path[i];
        return Math.max(type === 'call' ? s / n - X : X - s / n, 0);
      },
    });
    agree(res, { price: ref.mean, se: ref.se }, 4, `aritmetisk ${type} X=${X}`);
    agree(res, { price: res.plain, se: res.plainSe }, 4, 'kontrollvariat mot ren MC (samme stier)');
    assert.ok(res.se < res.plainSe / 5, `kontrollvariaten bør redusere feilen kraftig (${res.se} mot ${res.plainSe})`);
    // Aritmetisk ≥ geometrisk for call (AM-GM), motsatt for put.
    assert.ok(type === 'call' ? res.price > res.geometric : res.price < res.geometric, 'AM-GM-ordning');
  }
});

test('To aktiva: Stulz og Margrabe mot uavhengig MC, og identiteter', () => {
  const base = { S1: 100, S2: 105, T: 0.5, r: 0.05, b1: 0.05, b2: 0.02, v1: 0.2, v2: 0.3 };
  for (const rho of [-0.5, 0.3, 0.9]) {
    const p = { ...base, rho };
    for (const X of [95, 110]) {
      for (const kind of ['min', 'max']) {
        for (const type of ['call', 'put']) {
          const exact = stulz({ ...p, X, kind, type });
          const sign = type === 'call' ? 1 : -1;
          const f = kind === 'min' ? Math.min : Math.max;
          const est = mcTwoAssets({ ...p, n: 200000, seed: 19, payoff: (a, b) => Math.max(sign * (f(a, b) - X), 0) });
          withinMC(est, exact, 4, 0, `Stulz ${kind} ${type} ρ=${rho} X=${X}`);
        }
      }
      // max(S1, S2) + min(S1, S2) = S1 + S2 gir c_max + c_min = c(S1) + c(S2).
      const cs = gbsm({ type: 'call', S: p.S1, X, T: p.T, r: p.r, b: p.b1, v: p.v1 }) +
        gbsm({ type: 'call', S: p.S2, X, T: p.T, r: p.r, b: p.b2, v: p.v2 });
      close(stulz({ ...p, X, kind: 'max', type: 'call' }) + stulz({ ...p, X, kind: 'min', type: 'call' }), cs, 1e-9, 'max + min');
    }
    const ex = mcTwoAssets({ ...p, n: 200000, seed: 23, payoff: (a, b) => Math.max(a - b, 0) });
    withinMC(ex, margrabe(p), 4, 0, `Margrabe ρ=${rho}`);
    close(kirk({ ...p, X: 0, type: 'call' }), margrabe(p), 1e-12, 'Kirk med X = 0 er Margrabe');
  }
});

test('To aktiva: simulatoren mot analytiske referanser', () => {
  const p = { S1: 110, S2: 100, T: 0.5, r: 0.05, b1: 0, b2: 0, v1: 0.3, v2: 0.2, rho: 0.5 };
  for (const [kind, type, X] of [['max', 'call', 105], ['min', 'put', 100], ['spread', 'call', 0], ['spread', 'put', 0]]) {
    const res = mcTwoAsset({ ...p, kind, type, X, paths: 200000, seed: 3 });
    let exact;
    if (kind === 'spread') {
      const ex = margrabe(p);
      exact = type === 'call' ? ex : ex - p.S1 * Math.exp((p.b1 - p.r) * p.T) + p.S2 * Math.exp((p.b2 - p.r) * p.T);
    } else {
      exact = stulz({ ...p, kind, type, X });
    }
    withinMC({ mean: res.price, se: res.se }, exact, 4, 0, `${kind} ${type}`);
  }
  // Kirk er en tilnærming; for moderat X og korrelasjon er den nær simulert verdi.
  for (const X of [5, 15]) {
    const res = mcTwoAsset({ ...p, kind: 'spread', type: 'call', X, paths: 400000, seed: 4 });
    withinMC({ mean: res.price, se: res.se }, kirk({ ...p, X, type: 'call' }), 4, 0.01, `Kirk X=${X}`);
  }
});

// Cox-Ross-Rubinstein-tre for amerikanske opsjoner (uavhengig referanse).
function crrAmerican({ type, S, X, T, r, b, v, n = 2000 }) {
  const dt = T / n;
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp(b * dt) - d) / (u - d);
  const df = Math.exp(-r * dt);
  const sign = type === 'call' ? 1 : -1;
  // Kursen i node (j, i) er S u^{2i − j}.
  const spot = new Float64Array(2 * n + 1);
  for (let k = -n; k <= n; k++) spot[k + n] = S * Math.exp(k * v * Math.sqrt(dt));
  const vals = new Float64Array(n + 1);
  for (let i = 0; i <= n; i++) vals[i] = Math.max(sign * (spot[2 * i] - X), 0);
  for (let j = n - 1; j >= 0; j--) {
    for (let i = 0; i <= j; i++) {
      const cont = df * (p * vals[i + 1] + (1 - p) * vals[i]);
      vals[i] = Math.max(cont, sign * (spot[2 * i - j + n] - X));
    }
  }
  return vals[0];
}

test('Longstaff-Schwartz mot binomialtre (amerikansk put)', () => {
  for (const [S, v, T] of [[36, 0.2, 1], [40, 0.4, 1], [44, 0.2, 2]]) {
    const p = H('put', S, 40, T, 0.06, 0.06, v);
    const res = longstaffSchwartz({ ...p, steps: 50 * T, paths: 100000, seed: 11 });
    const tree = crrAmerican(p);
    // LSM med 50 utøvelsesdatoer per år er bermudisk og regresjonsbasert: liten skjevhet tillates.
    withinMC({ mean: res.price, se: res.se }, tree, 4, 0.02, `LSM S=${S} σ=${v} T=${T}`);
    assert.ok(res.price > res.bsm + 10 * res.se, 'tidligutøvelsespremien er tydelig');
  }
  // Longstaff og Schwartz (2001), tabell 1: amerikansk verdi (finite difference) 4,478 for S = 36, σ = 0,2, T = 1.
  close(crrAmerican(H('put', 36, 40, 1, 0.06, 0.06, 0.2)), 4.478, 2e-3, 'treet mot LS tabell 1');
});

test('Longstaff-Schwartz: call uten utbytte er europeisk, og ett steg er europeisk', () => {
  const p = H('call', 100, 100, 1, 0.05, 0.05, 0.25);
  const res = longstaffSchwartz({ ...p, steps: 25, paths: 100000, seed: 2 });
  withinMC({ mean: res.price, se: res.se }, gbsm(p), 4, 0.01, 'amerikansk call med b = r');
  const one = longstaffSchwartz({ ...H('put', 100, 105, 0.5, 0.04, 0.01, 0.3), steps: 1, paths: 100000, seed: 6 });
  close(one.price, Math.max(one.european, 5), 1e-12, 'ett steg');
  withinMC({ mean: one.european, se: one.europeanSe }, gbsm(H('put', 100, 105, 0.5, 0.04, 0.01, 0.3)), 4, 0, 'europeisk del');
});
