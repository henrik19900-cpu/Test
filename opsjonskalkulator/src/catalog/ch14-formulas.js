import { num, int, select, S, T, r } from './common.js';

export default [
  {
    id: 'formula-rate-conversion',
    chapter: 14,
    group: 'Renter',
    name: 'Konvertering av rentekonvensjoner',
    authors: 'Haug (2007), kap. 14',
    description: 'Gjør om mellom kontinuerlig rente og rente med m forrentninger per år.',
    inputs: [
      select('dir', 'Retning', [
        { value: 'toCont', label: 'Diskret → kontinuerlig' },
        { value: 'fromCont', label: 'Kontinuerlig → diskret' },
      ], 'toCont'),
      num('rate', 'Rente', 0.08, { unit: 'rate' }),
      int('m', 'Forrentninger per år m', 2, { min: 1 }),
    ],
    compute: (p) => {
      if (p.dir === 'toCont') {
        const rc = p.m * Math.log(1 + p.rate / p.m);
        return { 'Kontinuerlig rente': rc, 'Effektiv årlig rente': Math.exp(rc) - 1 };
      }
      const rm = p.m * (Math.exp(p.rate / p.m) - 1);
      return { [`Rente med ${p.m} forrentninger/år`]: rm, 'Effektiv årlig rente': Math.exp(p.rate) - 1 };
    },
    greeks: false,
    chart: false,
  },
  {
    id: 'formula-forward',
    chapter: 14,
    group: 'Cost of carry',
    name: 'Forwardpris og nåverdi',
    authors: 'Cost-of-carry-modellen',
    description: 'Forwardpris F = S e^{bT}, nåverdi av forwarden og diskonteringsfaktor e^{−rT}.',
    inputs: [S(100), T(0.5), r(0.08), num('b', 'Cost of carry b', 0.03, { unit: 'rate' }), num('K', 'Avtalt forwardpris K', 100, { min: 0 })],
    compute: (p) => {
      const Fwd = p.S * Math.exp(p.b * p.T);
      const df = Math.exp(-p.r * p.T);
      return {
        'Forwardpris F': Fwd,
        'Verdi av lang forward (F − K)e^{−rT}': (Fwd - p.K) * df,
        'Diskonteringsfaktor e^{−rT}': df,
      };
    },
  },
];
