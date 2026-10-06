import {
  crrTree, binomialTree, trinomialTree, threeDimTree, dermanKaniTree, THREE_DIM_PAYOFFS, margrabe, stulzMinMax,
} from '../models/lattice.js';
import { finiteDifference } from '../models/finite-difference.js';
import { gbsm } from '../models/bsm.js';
import { callPut, num, int, select, S, X, T, r, b, v, rho } from './common.js';

const exercise = (def = 'american') => select('exercise', 'Innløsning', [
  { value: 'american', label: 'Amerikansk' },
  { value: 'european', label: 'Europeisk' },
], def);

const steps = (def, max = 5000, label = 'Antall tidssteg n') => int('n', label, def, { min: 3, max });

// Trepriser er stykkevis lineære i S, så UI-ets numeriske gamma blir misvisende. Trekalkulatorene
// har derfor greeks: false og viser i stedet delta, gamma og theta lest av treet.
const treeResult = (res, p, withTheta = true) => {
  const out = { 'Pris': res.price, 'Delta': res.delta, 'Gamma': res.gamma };
  if (withTheta) {
    out['Theta (per år)'] = res.theta;
    out['Theta (per dag)'] = res.theta / 365;
  }
  out['Europeisk GBSM (til sammenligning)'] = gbsm(p);
  return out;
};

const fdInputs = [
  exercise('american'), callPut('put'), S(100), X(100), T(0.5), r(0.1), b(0.1), v(0.25),
  int('M', 'Antall prissteg M', 200, { min: 10, max: 5000 }),
  int('N', 'Antall tidssteg N', 200, { min: 1, max: 20000 }),
];

const fdCompute = (method) => (p) => {
  const res = finiteDifference({ ...p, method });
  const out = {
    'Pris': res.price,
    'Delta': res.delta,
    'Gamma': res.gamma,
    'Theta (per år)': res.theta,
    'Theta (per dag)': res.theta / 365,
    'Europeisk GBSM (til sammenligning)': gbsm(p),
  };
  if (method === 'explicit') out['Tidssteg brukt'] = res.steps;
  out['Gitter: laveste og høyeste kurs'] = `${res.Smin.toFixed(2)} – ${res.Smax.toFixed(2)}`;
  return out;
};

// Lukkede formler for europeiske varianter med to aktiva (til sammenligning med treet).
function twoAssetReference(p) {
  if (p.exercise !== 'european') return null;
  const { S1, S2, Q1, Q2, X1, T: TT, r: rr, b1, b2, v1, v2 } = p;
  const vr = Math.sqrt(Math.max(v1 * v1 + v2 * v2 - 2 * p.rho * v1 * v2, 1e-300));
  switch (p.payoff) {
    case 'exchange':
      return ['Margrabe (lukket formel)', margrabe({ S1, S2, Q1, Q2, T: TT, r: rr, b1, b2, v1, v2, rho: p.rho })];
    case 'max':
    case 'min':
      return ['Stulz (lukket formel)', stulzMinMax({ ...p, kind: p.payoff, X: X1 })];
    case 'product':
      return ['Lukket formel (lognormalt produkt)', gbsm({
        type: p.type, S: Q1 * S1 * Q2 * S2, X: X1, T: TT, r: rr, b: b1 + b2 + p.rho * v1 * v2,
        v: Math.sqrt(v1 * v1 + v2 * v2 + 2 * p.rho * v1 * v2),
      })];
    case 'outperformance':
      return ['Lukket formel (lognormal kvote)', gbsm({
        type: p.type, S: Q1 * S1 / (Q2 * S2), X: X1, T: TT, r: rr, b: b1 - b2 + v2 * v2 - p.rho * v1 * v2, v: vr,
      })];
    default:
      return null;
  }
}

export default [
  {
    id: 'tree-crr',
    chapter: 7,
    group: 'Binomialtrær',
    name: 'Cox-Ross-Rubinstein binomialtre',
    authors: 'Cox, Ross og Rubinstein (1979)',
    description: 'Rekombinerende binomialtre med u = e^{σ√Δt}, d = 1/u og p = (e^{bΔt} − d)/(u − d). Delta, gamma og theta leses av de første nodene i treet.',
    inputs: [exercise('american'), callPut('put'), S(100), X(95), T(0.5), r(0.08), b(0.08), v(0.3), steps(100)],
    greeks: false,
    compute: (p) => treeResult(crrTree(p), p),
  },
  {
    id: 'tree-binomial-variants',
    chapter: 7,
    group: 'Binomialtrær',
    name: 'Rendleman-Bartter og Leisen-Reimer',
    authors: 'Rendleman og Bartter (1979), Leisen og Reimer (1996)',
    description: 'Rendleman-Bartter: like sannsynligheter og u, d = e^{(b − σ²/2)Δt ± σ√Δt}. Leisen-Reimer: noder og sannsynligheter fra Peizer-Pratt-invertering, som gir rask og jevn konvergens (n gjøres odde).',
    inputs: [
      select('method', 'Tretype', [
        { value: 'lr', label: 'Leisen-Reimer' },
        { value: 'rb', label: 'Rendleman-Bartter' },
      ], 'lr'),
      exercise('american'), callPut('put'), S(100), X(95), T(0.5), r(0.08), b(0.08), v(0.3), steps(101),
    ],
    greeks: false,
    compute: (p) => {
      const res = binomialTree(p);
      return { ...treeResult(res, p, false), 'Steg brukt': res.steps };
    },
  },
  {
    id: 'tree-trinomial',
    chapter: 7,
    group: 'Trinomialtrær',
    name: 'Trinomialtre',
    authors: 'Boyle (1986)',
    description: 'Rekombinerende trinomialtre med u = e^{σ√(2Δt)} og sannsynligheter for opp, uendret og ned. Delta, gamma og theta leses av treet.',
    inputs: [exercise('american'), callPut('put'), S(100), X(110), T(0.5), r(0.1), b(0.1), v(0.27), steps(100)],
    greeks: false,
    compute: (p) => {
      const res = trinomialTree(p);
      return { ...treeResult(res, p), 'Sannsynlighet opp pu': res.pu, 'Sannsynlighet uendret pm': res.pm, 'Sannsynlighet ned pd': res.pd };
    },
  },
  {
    id: 'tree-three-dimensional',
    chapter: 7,
    group: 'Tredimensjonale trær',
    name: 'Tredimensjonalt binomialtre for to aktiva',
    authors: 'Rubinstein (1994)',
    description: 'Binomialtre for to korrelerte aktiva med fire like sannsynlige grener per steg. Gir europeiske og amerikanske verdier for en rekke utbetalinger på to underliggende.',
    payoff: 'Se utbetalingstypen. Put bytter fortegn (bytteopsjonen har samme utbetaling).',
    inputs: [
      exercise('american'),
      select('payoff', 'Utbetaling', Object.entries(THREE_DIM_PAYOFFS).map(([value, label]) => ({ value, label })), 'spread'),
      callPut('call'),
      num('S1', 'Spotpris S1', 122, { min: 0, exclusiveMin: true }),
      num('S2', 'Spotpris S2', 120, { min: 0, exclusiveMin: true }),
      num('Q1', 'Antall Q1 av aktivum 1', 1, { min: 0, exclusiveMin: true }),
      num('Q2', 'Antall Q2 av aktivum 2', 1, { min: 0, exclusiveMin: true }),
      num('X1', 'Innløsningskurs X1', 3, { min: 0 }),
      num('X2', 'Innløsningskurs X2 (bare dual strike)', 3, { min: 0 }),
      T(0.1), r(0.1),
      num('b1', 'Cost of carry b1', 0, { unit: 'rate' }),
      num('b2', 'Cost of carry b2', 0, { unit: 'rate' }),
      v(0.2, 'Volatilitet σ1', 'v1'),
      v(0.2, 'Volatilitet σ2', 'v2'),
      rho(-0.5),
      steps(100, 400),
    ],
    greeks: false,
    compute: (p) => {
      const res = threeDimTree(p);
      const out = { 'Pris': res.price };
      const ref = twoAssetReference(p);
      if (ref) out[ref[0]] = ref[1];
      return out;
    },
  },
  {
    id: 'tree-implied-binomial',
    chapter: 7,
    group: 'Implisitte trær',
    name: 'Implisitt binomialtre (Derman-Kani)',
    authors: 'Derman og Kani (1994)',
    description: 'Binomialtre som gjenskaper en volatilitetsskjevhet. Nodene bygges nivå for nivå slik at treet priser opsjoner med innløsningskurs i nodene riktig; her er implisitt volatilitet σ(K) = σ + skjevhet·(K − S).',
    inputs: [
      exercise('european'), callPut('call'), S(100), X(100), T(5), r(0.03), b(0.03),
      v(0.1, 'Volatilitet σ ved S (ATM)'),
      num('skew', 'Skjevhet: endring i σ per enhet økning i K', -0.0005),
      steps(5, 150),
    ],
    greeks: false,
    compute: (p) => {
      const res = dermanKaniTree(p);
      return {
        'Pris (implisitt tre)': res.price,
        'CRR-tre med σ(X), samme antall steg': crrTree({ ...p, v: res.impliedVolAtX }).price,
        'GBSM med σ(X)': gbsm({ type: p.type, S: p.S, X: p.X, T: p.T, r: p.r, b: p.b, v: res.impliedVolAtX }),
        'Implisitt volatilitet σ(X)': res.impliedVolAtX,
        'Lokal volatilitet i første steg': res.localVol0,
        'Noder etter første steg (ned / opp)': res.tree.nodes[1].map((x) => x.toFixed(4).replace('.', ',')).join(' / '),
        'Sannsynlighet for opp i første steg': res.tree.probs[0][0],
        'Noder justert mot arbitrasje': res.tree.overrides,
      };
    },
  },
  {
    id: 'tree-fd-explicit',
    chapter: 7,
    group: 'Finite difference',
    name: 'Eksplisitt finite difference',
    authors: 'Brennan og Schwartz (1978), Hull og White (1990)',
    description: 'Eksplisitt skjema for Black-Scholes-Merton-likningen i ln S. Antall tidssteg økes automatisk til stabilitetskravet Δt ≤ 0,9/(σ²/Δx² + |r|) er oppfylt.',
    inputs: fdInputs,
    compute: fdCompute('explicit'),
  },
  {
    id: 'tree-fd-implicit',
    chapter: 7,
    group: 'Finite difference',
    name: 'Implisitt finite difference',
    authors: 'Brennan og Schwartz (1978)',
    description: 'Fullt implisitt skjema i ln S (ubetinget stabilt). Amerikanske opsjoner løses med Brennan-Schwartz-algoritmen.',
    inputs: fdInputs,
    compute: fdCompute('implicit'),
  },
  {
    id: 'tree-fd-crank-nicolson',
    chapter: 7,
    group: 'Finite difference',
    name: 'Crank-Nicolson',
    authors: 'Crank og Nicolson (1947)',
    description: 'Andreordens skjema i både tid og ln S, med to implisitte halvsteg først (Rannacher) for å dempe svingninger fra knekken i utbetalingen. Amerikanske opsjoner løses med Brennan-Schwartz.',
    inputs: fdInputs,
    compute: fdCompute('cn'),
  },
];
