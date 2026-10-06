import { gbsmGreeks, putCallParity, bachelier, sprenkle, boness, samuelson } from '../models/bsm.js';
import { callPut, num, S, F, X, T, r, b, q, v, select } from './common.js';

const core = (g) => ({
  'Delta': g.delta,
  'Gamma': g.gamma,
  'Vega': g.vega,
  'Theta (per dag)': g.thetaDay,
});

export default [
  {
    id: 'bsm-black-scholes',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Black-Scholes – aksje uten utbytte',
    authors: 'Black og Scholes (1973)',
    description: 'Europeisk opsjon på en aksje som ikke betaler utbytte i opsjonens levetid.',
    payoff: 'max(S_T − X, 0) / max(X − S_T, 0)',
    inputs: [callPut('call'), S(60), X(65), T(0.25), r(0.08), v(0.3)],
    compute: (p) => {
      const g = gbsmGreeks({ ...p, b: p.r });
      return { 'Pris': g.price, ...core(g), 'Rho': g.rho };
    },
    example: 2.1334,
  },
  {
    id: 'bsm-merton',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Merton – aksjeindeks med utbytte',
    authors: 'Merton (1973)',
    description: 'Europeisk opsjon på en aksje eller indeks med kontinuerlig utbytteavkastning q.',
    inputs: [callPut('put'), S(100), X(95), T(0.5), r(0.1), q(0.05), v(0.2)],
    compute: (p) => {
      const g = gbsmGreeks({ ...p, b: p.r - p.q });
      return { 'Pris': g.price, ...core(g), 'Rho': g.rho, 'Utbytte-rho (phi)': g.phi };
    },
    example: 2.4648,
  },
  {
    id: 'bsm-black76',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Black-76 – opsjon på futures/forward',
    authors: 'Black (1976)',
    description: 'Europeisk opsjon på en futures- eller forwardkontrakt (cost of carry b = 0).',
    inputs: [callPut('call'), F(19), X(19), T(0.75), r(0.1), v(0.28)],
    compute: (p) => {
      const g = gbsmGreeks({ type: p.type, S: p.F, X: p.X, T: p.T, r: p.r, b: 0, v: p.v });
      return { 'Pris': g.price, ...core(g), 'Rho (futures)': g.futuresRho };
    },
    example: 1.7011,
  },
  {
    id: 'bsm-asay',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Asay – futuresopsjon med margin',
    authors: 'Asay (1982)',
    description: 'Opsjon på futures der premien betales som margin, slik at verken rente eller carry inngår (r = b = 0).',
    inputs: [callPut('call'), F(19), X(19), T(0.75), v(0.28)],
    compute: (p) => {
      const g = gbsmGreeks({ type: p.type, S: p.F, X: p.X, T: p.T, r: 0, b: 0, v: p.v });
      return { 'Pris': g.price, ...core(g) };
    },
  },
  {
    id: 'bsm-garman-kohlhagen',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Garman-Kohlhagen – valutaopsjon',
    authors: 'Garman og Kohlhagen (1983)',
    description: 'Europeisk valutaopsjon. S er valutakursen, r innenlandsk og rf utenlandsk rente.',
    inputs: [
      callPut('call'), S(1.56, 'Valutakurs S'), X(1.6), T(0.5), r(0.06, 'Innenlandsk rente r'),
      num('rf', 'Utenlandsk rente rf', 0.08, { unit: 'rate' }), v(0.12),
    ],
    compute: (p) => {
      const g = gbsmGreeks({ type: p.type, S: p.S, X: p.X, T: p.T, r: p.r, b: p.r - p.rf, v: p.v });
      return { 'Pris': g.price, ...core(g), 'Rho innenlandsk': g.rho, 'Rho utenlandsk': g.phi };
    },
    example: 0.0291,
  },
  {
    id: 'bsm-generalized',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Generalisert Black-Scholes-Merton',
    authors: 'Black og Scholes (1973), Merton (1973)',
    description: 'Fellesformelen der cost of carry b velger modell: aksje, indeks, futures eller valuta.',
    inputs: [callPut('put'), S(75), X(70), T(0.5), r(0.1), b(0.05), v(0.35)],
    compute: (p) => {
      const g = gbsmGreeks(p);
      return { 'Pris': g.price, ...core(g), 'Rho': g.rho, 'Carry-rho': g.carryRho, 'd1': g.d1, 'd2': g.d2 };
    },
    example: 4.087,
  },
  {
    id: 'bsm-parity',
    chapter: 1,
    group: 'Black-Scholes-Merton',
    name: 'Put-call-paritet',
    authors: 'Stoll (1969)',
    description: 'Finn prisen på put fra call eller omvendt: c − p = S e^{(b−r)T} − X e^{−rT}.',
    inputs: [
      select('given', 'Kjent pris er for', [
        { value: 'call', label: 'Call → finn put' },
        { value: 'put', label: 'Put → finn call' },
      ], 'call'),
      num('price', 'Kjent opsjonspris', 2.1334, { min: 0 }), S(60), X(65), T(0.25), r(0.08), b(0.08),
    ],
    compute: (p) => {
      const other = putCallParity(p);
      return {
        [p.given === 'call' ? 'Put-pris' : 'Call-pris']: other,
        'S e^{(b−r)T} − X e^{−rT}': p.S * Math.exp((p.b - p.r) * p.T) - p.X * Math.exp(-p.r * p.T),
      };
    },
  },
  {
    id: 'bsm-bachelier',
    chapter: 1,
    group: 'Før Black-Scholes-Merton',
    name: 'Bachelier – normalfordelt pris',
    authors: 'Bachelier (1900)',
    description: 'Prisen følger en aritmetisk brownsk bevegelse. σ er absolutt volatilitet i kroner per √år. Med r = b = 0 får du originalformelen.',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0), b(0),
      num('v', 'Absolutt volatilitet σ (pris per √år)', 20, { min: 0, exclusiveMin: true }),
    ],
    compute: (p) => ({ 'Pris': bachelier(p) }),
  },
  {
    id: 'bsm-sprenkle',
    chapter: 1,
    group: 'Før Black-Scholes-Merton',
    name: 'Sprenkle',
    authors: 'Sprenkle (1964)',
    description: 'Tidlig lognormal modell med forventet vekst ρ i aksjen og risikoaversjon k.',
    inputs: [
      callPut('call'), S(60), X(65), T(0.25),
      num('rho', 'Forventet vekstrate ρ', 0.1, { unit: 'rate' }),
      num('k', 'Risikoaversjon k', 0.05), v(0.3),
    ],
    compute: (p) => ({ 'Pris': sprenkle(p) }),
  },
  {
    id: 'bsm-boness',
    chapter: 1,
    group: 'Før Black-Scholes-Merton',
    name: 'Boness',
    authors: 'Boness (1964)',
    description: 'Diskonterer innløsningskursen med aksjens forventede avkastning ρ i stedet for risikofri rente.',
    inputs: [callPut('call'), S(60), X(65), T(0.25), num('rho', 'Forventet avkastning ρ', 0.1, { unit: 'rate' }), v(0.3)],
    compute: (p) => ({ 'Pris': boness(p) }),
  },
  {
    id: 'bsm-samuelson',
    chapter: 1,
    group: 'Før Black-Scholes-Merton',
    name: 'Samuelson',
    authors: 'Samuelson (1965)',
    description: 'Skiller mellom forventet avkastning på aksjen (ρ) og på opsjonen (w).',
    inputs: [
      callPut('call'), S(60), X(65), T(0.25),
      num('rho', 'Forventet avkastning aksje ρ', 0.1, { unit: 'rate' }),
      num('w', 'Forventet avkastning opsjon w', 0.15, { unit: 'rate' }), v(0.3),
    ],
    compute: (p) => ({ 'Pris': samuelson(p) }),
  },
];

