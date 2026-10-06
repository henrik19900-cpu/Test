// Kapittel 5: valutaoversatte opsjoner.
// Monte Carlo-kontrollen simulerer bare innenlandske omsettelige størrelser: Y = E·S (den utenlandske
// aksjen målt i innenlandsk valuta, carry r − q) og valutakursen E (carry r − rf). Da forutsettes ingen
// quanto-justering; den må komme ut av simuleringen.
import test from 'node:test';
import { close, withinMC, mcTwoAssets } from './helpers.js';
import { gbsm } from '../src/models/bsm.js';
import { cnd } from '../src/math/normal.js';
import { foreignEquityDomesticStrike, quanto, equityLinkedFX, takeoverFX } from '../src/models/currency.js';

const P = { E: 1.5, S: 100, T: 0.5, r: 0.08, rf: 0.05, q: 0.04, vS: 0.2, vE: 0.12, rho: 0.45 };

// Simulerer (Y = E·S, E) og gir payoff(S_T, E_T) i innenlandsk valuta.
function mcFx({ E, S, T, r, rf, q, vS, vE, rho }, payoff, seed = 1) {
  const vY = Math.sqrt(vS * vS + vE * vE + 2 * rho * vS * vE);
  const corr = (rho * vS * vE + vE * vE) / (vY * vE);
  return mcTwoAssets({
    S1: E * S, S2: E, T, r, b1: r - q, b2: r - rf, v1: vY, v2: vE, rho: corr, seed,
    payoff: (y, e) => payoff(y / e, e),
  });
}

test('Bokas eksempler', () => {
  close(foreignEquityDomesticStrike({ type: 'call', E: 1.5, S: 100, X: 160, T: 0.5, r: 0.08, q: 0.05, vS: 0.2, vE: 0.12, rho: 0.45 }).price, 8.3056, 1e-4);
  close(quanto({ type: 'call', Ep: 1.5, S: 100, X: 105, T: 0.5, r: 0.08, rf: 0.05, q: 0.04, vS: 0.2, vE: 0.1, rho: 0.3 }).price, 5.328, 1e-4);
});

test('Utenlandsk aksje med innenlandsk innløsningskurs mot MC og paritet', () => {
  for (const rho of [-0.5, 0.45]) {
    for (const type of ['call', 'put']) {
      const X = 155;
      const p = { ...P, rho, X };
      withinMC(mcFx(p, (s, e) => Math.max(type === 'call' ? e * s - X : X - e * s, 0)),
        foreignEquityDomesticStrike({ type, ...p }).price, 4, 0, `${type} ρ=${rho}`);
    }
  }
  const p = { ...P, X: 150 };
  const c = foreignEquityDomesticStrike({ type: 'call', ...p }).price;
  const pu = foreignEquityDomesticStrike({ type: 'put', ...p }).price;
  close(c - pu, p.E * p.S * Math.exp(-p.q * p.T) - p.X * Math.exp(-p.r * p.T), 1e-10, 'put-call-paritet');
  // σE = 0: vanlig opsjon på E·S.
  close(foreignEquityDomesticStrike({ type: 'call', ...p, vE: 0 }).price,
    gbsm({ type: 'call', S: p.E * p.S, X: p.X, T: p.T, r: p.r, b: p.r - p.q, v: p.vS }), 1e-12);
});

test('Quanto mot MC og identiteter', () => {
  for (const rho of [-0.6, 0.3]) {
    for (const type of ['call', 'put']) {
      const p = { ...P, rho, X: 102, Ep: 1.4 };
      withinMC(mcFx(p, (s) => p.Ep * Math.max(type === 'call' ? s - p.X : p.X - s, 0), 2),
        quanto({ type, ...p }).price, 4, 0, `${type} ρ=${rho}`);
    }
  }
  const p = { ...P, X: 102, Ep: 1.4 };
  const fwd = p.Ep * (p.S * Math.exp((p.rf - p.q - p.rho * p.vS * p.vE - p.r) * p.T) - p.X * Math.exp(-p.r * p.T));
  close(quanto({ type: 'call', ...p }).price - quanto({ type: 'put', ...p }).price, fwd, 1e-10, 'paritet');
  // ρ = 0: ingen quanto-justering, så prisen er Ep ganger en vanlig opsjon med carry rf − q.
  close(quanto({ type: 'call', ...p, rho: 0 }).price,
    p.Ep * gbsm({ type: 'call', S: p.S, X: p.X, T: p.T, r: p.r, b: p.rf - p.q, v: p.vS }), 1e-12);
});

test('Equity-linked valutaopsjon mot MC og identiteter', () => {
  for (const rho of [-0.4, 0.5]) {
    for (const type of ['call', 'put']) {
      const p = { ...P, rho, X: 1.52, T: 0.75 };
      withinMC(mcFx(p, (s, e) => s * Math.max(type === 'call' ? e - p.X : p.X - e, 0), 3),
        equityLinkedFX({ type, ...p }), 4, 0, `${type} ρ=${rho}`);
    }
  }
  const p = { ...P, rho: -0.4, X: 1.52 };
  const fwd = p.E * p.S * Math.exp(-p.q * p.T) - p.X * p.S * Math.exp((p.rf - p.r - p.q - p.rho * p.vS * p.vE) * p.T);
  close(equityLinkedFX({ type: 'call', ...p }) - equityLinkedFX({ type: 'put', ...p }), fwd, 1e-10, 'paritet');
  // σS = 0: aksjen vokser deterministisk med rf − q, og opsjonen er så mange Garman-Kohlhagen-opsjoner.
  close(equityLinkedFX({ type: 'call', ...p, vS: 0 }),
    p.S * Math.exp((p.rf - p.q) * p.T) * gbsm({ type: 'call', S: p.E, X: p.X, T: p.T, r: p.r, b: p.r - p.rf, v: p.vE }), 1e-12);
});

test('Takeover-valutaopsjon mot MC og grensetilfeller', () => {
  const base = { V: 100, K: 105, N: 1000, E: 1.5, X: 1.55, T: 1, r: 0.08, rf: 0.06, vV: 0.2, vE: 0.25 };
  for (const rho of [-0.5, 0.1, 0.7]) {
    const p = { ...base, rho };
    // Z = E·V er selskapets verdi i innenlandsk valuta (carry r), E har carry r − rf.
    const vZ = Math.sqrt(p.vV * p.vV + p.vE * p.vE + 2 * rho * p.vV * p.vE);
    const est = mcTwoAssets({
      S1: p.E * p.V, S2: p.E, T: p.T, r: p.r, b1: p.r, b2: p.r - p.rf, v1: vZ, v2: p.vE,
      rho: (rho * p.vV * p.vE + p.vE * p.vE) / (vZ * p.vE), seed: 4,
      payoff: (z, e) => (z / e < p.K ? p.N * Math.max(e - p.X, 0) : 0),
    });
    withinMC(est, takeoverFX(p).price, 4, 0, `ρ=${rho}`);
  }
  const gk = base.N * gbsm({ type: 'call', S: base.E, X: base.X, T: base.T, r: base.r, b: base.r - base.rf, v: base.vE });
  // Budet er alltid høyt nok: vanlig valutaopsjon.
  close(takeoverFX({ ...base, rho: 0.3, K: 1e9 }).price, gk, 1e-8);
  // ρ = 0: uavhengighet, pris = valutaopsjon · P(V_T < K).
  const a1 = (Math.log(base.V / base.K) + (base.rf - 0.5 * base.vV * base.vV) * base.T) / (base.vV * Math.sqrt(base.T));
  close(takeoverFX({ ...base, rho: 0 }).price, gk * cnd(-a1), 1e-9);
});
