import { cnd, nd, cndInv, cbnd } from '../math/normal.js';
import { num, S, T, b, v } from './common.js';

export default [
  {
    id: 'dist-normal',
    chapter: 13,
    group: 'Normalfordelingen',
    name: 'Kumulativ normalfordeling N(x)',
    authors: 'Hart (1968)',
    description: 'Sannsynligheten for at en standardnormal variabel er mindre enn x, med dobbel presisjon.',
    inputs: [num('x', 'x', 1.96)],
    compute: (p) => ({ 'N(x)': cnd(p.x), 'n(x) (tetthet)': nd(p.x), '1 − N(x)': cnd(-p.x) }),
    greeks: false,
    chart: false,
  },
  {
    id: 'dist-inverse-normal',
    chapter: 13,
    group: 'Normalfordelingen',
    name: 'Invers normalfordeling N⁻¹(p)',
    authors: 'Acklam, med Halley-korreksjon',
    description: 'Kvantilen x slik at N(x) = p.',
    inputs: [num('p', 'Sannsynlighet p', 0.975, { min: 0, max: 1, exclusiveMin: true, exclusiveMax: true })],
    compute: (p) => {
      const x = cndInv(p.p);
      return { 'N⁻¹(p)': x, 'Kontroll: N(x)': cnd(x) };
    },
    greeks: false,
    chart: false,
  },
  {
    id: 'dist-bivariate',
    chapter: 13,
    group: 'Normalfordelingen',
    name: 'Bivariat kumulativ normal M(a, b; ρ)',
    authors: 'Genz (2004), Drezner og Wesolowsky (1990)',
    description: 'P(X ≤ a, Y ≤ b) for to standardnormale variabler med korrelasjon ρ. Brukes i mange eksotiske formler.',
    inputs: [num('a', 'a', 0.5), num('b', 'b', -0.3), num('rho', 'Korrelasjon ρ', 0.5, { min: -1, max: 1 })],
    compute: (p) => ({ 'M(a, b; ρ)': cbnd(p.a, p.b, p.rho), 'N(a)·N(b) (uavhengige)': cnd(p.a) * cnd(p.b) }),
    greeks: false,
    chart: false,
  },
  {
    id: 'dist-lognormal-price',
    chapter: 13,
    group: 'Lognormal pris',
    name: 'Fordelingen til S_T',
    authors: 'Lognormal modell under risikonøytralt mål',
    description: 'Sannsynligheter og kvantiler for prisen ved forfall når ln S_T er normalfordelt.',
    inputs: [S(100), num('K', 'Nivå K', 110, { min: 0, exclusiveMin: true }), T(1), b(0.05), v(0.25)],
    compute: (p) => {
      const m = Math.log(p.S) + (p.b - 0.5 * p.v * p.v) * p.T;
      const sd = p.v * Math.sqrt(p.T);
      const z = (Math.log(p.K) - m) / sd;
      const mean = p.S * Math.exp(p.b * p.T);
      return {
        'P(S_T ≤ K)': cnd(z),
        'P(S_T > K)': cnd(-z),
        'Forventning E[S_T]': mean,
        'Standardavvik': mean * Math.sqrt(Math.exp(p.v * p.v * p.T) - 1),
        'Median': Math.exp(m),
        '2,5 %-kvantil': Math.exp(m + sd * cndInv(0.025)),
        '97,5 %-kvantil': Math.exp(m + sd * cndInv(0.975)),
      };
    },
    chart: false,
  },
];
