import {
  mcEuropean, qmcEuropean, mcAsianArithmetic, mcTwoAsset, stulz, margrabe, kirk, longstaffSchwartz,
} from '../models/monte-carlo.js';
import { gbsm, gbsmGreeks } from '../models/bsm.js';
import { callPut, num, int, select, S, X, T, r, b, v, rho } from './common.js';

const positive = { min: 0, exclusiveMin: true };

const mcInputs = (paths) => [
  int('paths', 'Antall stier', paths, { min: 100, max: 5000000 }),
  int('seed', 'Seed (startverdi for tilfeldige tall)', 1, { min: 0 }),
];

const ci = (res) => ({
  'Standardfeil': res.se,
  '95 %-intervall, nedre': res.lo,
  '95 %-intervall, øvre': res.hi,
});

export default [
  {
    id: 'mc-european',
    chapter: 8,
    group: 'Europeiske opsjoner',
    name: 'Monte Carlo – europeisk opsjon',
    authors: 'Boyle (1977); pathwise Greeks: Broadie og Glasserman (1996)',
    description: 'Simulerer S_T under risikonøytral geometrisk brownsk bevegelse med antitetiske trekk. Delta og vega regnes pathwise på de samme stiene.',
    payoff: 'max(S_T − X, 0) / max(X − S_T, 0)',
    inputs: [callPut('call'), S(100), X(100), T(0.5), r(0.05), b(0.02), v(0.3), ...mcInputs(50000)],
    compute: (p) => {
      const res = mcEuropean(p);
      const g = gbsmGreeks(p);
      return {
        'Pris': res.price,
        ...ci(res),
        'Delta (pathwise)': res.delta,
        'Standardfeil delta': res.deltaSe,
        'Vega (pathwise)': res.vega,
        'Standardfeil vega': res.vegaSe,
        'BSM-pris (analytisk)': g.price,
        'BSM-delta': g.delta,
        'BSM-vega': g.vega,
      };
    },
    greeks: false,
    chart: false,
  },
  {
    id: 'mc-halton',
    chapter: 8,
    group: 'Europeiske opsjoner',
    name: 'Kvasi-tilfeldig Monte Carlo (Halton)',
    authors: 'Halton (1960)',
    description: 'Erstatter tilfeldige tall med Halton-sekvensen i base 2. Feilen anslås med 16 tilfeldige skift av punktene (randomisert kvasi-Monte Carlo) og sammenlignes med vanlig Monte Carlo.',
    payoff: 'max(S_T − X, 0) / max(X − S_T, 0)',
    inputs: [callPut('call'), S(100), X(100), T(0.5), r(0.05), b(0.02), v(0.3), ...mcInputs(20000)],
    compute: (p) => {
      const res = qmcEuropean(p);
      const exact = gbsm(p);
      return {
        'Pris (randomisert Halton)': res.price,
        ...ci(res),
        'Pris (ren Halton-sekvens)': res.plain,
        'Feil ren Halton mot BSM': res.plain - exact,
        'Vanlig Monte Carlo, samme antall': res.mcPrice,
        'Standardfeil vanlig Monte Carlo': res.mcSe,
        'BSM-pris (analytisk)': exact,
      };
    },
    greeks: false,
    chart: false,
  },
  {
    id: 'mc-asian-cv',
    chapter: 8,
    group: 'Asiatiske opsjoner',
    name: 'Aritmetisk asiatisk opsjon med kontrollvariat',
    authors: 'Kemna og Vorst (1990)',
    description: 'Opsjon på aritmetisk gjennomsnitt av n like fordelte fikseringer frem til forfall. Den geometriske gjennomsnittsopsjonen, som har lukket form, brukes som kontrollvariat.',
    payoff: 'max(A − X, 0) / max(X − A, 0), A = (1/n) Σ S(iT/n)',
    inputs: [
      callPut('call'), S(100), X(100), T(1), r(0.05), b(0.05), v(0.3),
      int('n', 'Antall fikseringer n', 12, { min: 1, max: 1000 }),
      ...mcInputs(20000),
    ],
    compute: (p) => {
      const res = mcAsianArithmetic(p);
      return {
        'Pris': res.price,
        ...ci(res),
        'Pris uten kontrollvariat': res.plain,
        'Standardfeil uten kontrollvariat': res.plainSe,
        'Geometrisk gjennomsnittsopsjon (analytisk)': res.geometric,
        'Kontrollvariatkoeffisient β': res.beta,
        'Variansreduksjon (faktor)': res.se > 0 ? (res.plainSe / res.se) ** 2 : 'uendelig',
      };
    },
    greeks: false,
    chart: false,
  },
  {
    id: 'mc-two-asset',
    chapter: 8,
    group: 'To aktiva',
    name: 'Spread, maks og min på to korrelerte aktiva',
    authors: 'Simulering med korrelerte normaler; referanser Stulz (1982), Margrabe (1978), Kirk (1995)',
    description: 'Simulerer to korrelerte lognormale aktiva ved forfall med antitetiske trekk. Sammenlignes med Stulz for maks/min, Margrabe for spread med X = 0 og Kirks tilnærming ellers.',
    payoff: 'spread: max(S1 − S2 − X, 0) · maks: max(max(S1, S2) − X, 0) · min: max(min(S1, S2) − X, 0)',
    inputs: [
      select('kind', 'Utbetaling', [
        { value: 'spread', label: 'Spread S1 − S2 − X' },
        { value: 'max', label: 'Maksimum av S1 og S2' },
        { value: 'min', label: 'Minimum av S1 og S2' },
      ], 'spread'),
      callPut('call'),
      num('S1', 'Spotpris S1', 110, positive),
      num('S2', 'Spotpris S2', 100, positive),
      num('X', 'Innløsningskurs X (spread: kan være 0 eller negativ)', 5),
      T(0.5), r(0.05),
      num('b1', 'Cost of carry b1', 0, { unit: 'rate' }),
      num('b2', 'Cost of carry b2', 0, { unit: 'rate' }),
      v(0.3, 'Volatilitet σ1', 'v1'), v(0.2, 'Volatilitet σ2', 'v2'), rho(0.5),
      ...mcInputs(50000),
    ],
    compute: (p) => {
      if (p.kind !== 'spread' && !(p.X > 0)) throw new Error('Innløsningskursen må være positiv for maks- og min-opsjoner.');
      const res = mcTwoAsset(p);
      let ref;
      let model;
      if (p.kind === 'spread') {
        if (p.X === 0) {
          const ex = margrabe(p);
          // Put med X = 0: max(S2 − S1, 0), Margrabe med aktivaene byttet om.
          ref = p.type === 'call' ? ex : ex - p.S1 * Math.exp((p.b1 - p.r) * p.T) + p.S2 * Math.exp((p.b2 - p.r) * p.T);
          model = 'Margrabe (1978), eksakt';
        } else {
          try {
            ref = kirk(p);
            model = 'Kirk (1995), tilnærming';
          } catch {
            ref = 'ikke definert';
            model = 'Kirk (1995) gjelder ikke';
          }
        }
      } else {
        ref = stulz(p);
        model = 'Stulz (1982), eksakt';
      }
      return {
        'Pris': res.price,
        ...ci(res),
        'Analytisk referanse': ref,
        'Referansemodell': model,
        'Avvik i antall standardfeil': typeof ref === 'number' && res.se > 0 ? (res.price - ref) / res.se : 'ikke definert',
      };
    },
    greeks: false,
    chart: false,
  },
  {
    id: 'mc-lsm',
    chapter: 8,
    group: 'Amerikanske opsjoner',
    name: 'Longstaff-Schwartz – amerikansk opsjon',
    authors: 'Longstaff og Schwartz (2001)',
    description: 'Amerikansk opsjon med utøvelse på n like fordelte datoer. Fortsettelsesverdien estimeres med minste kvadraters regresjon på et polynom i S/X, bare over stier i pengene.',
    payoff: 'max(S_t − X, 0) / max(X − S_t, 0) ved valgfri utøvelse',
    inputs: [
      callPut('put'), S(36), X(40), T(1), r(0.06), b(0.06), v(0.2),
      int('steps', 'Antall tidssteg (utøvelsesdatoer)', 50, { min: 1, max: 2000 }),
      int('degree', 'Polynomgrad i regresjonen', 3, { min: 1, max: 6 }),
      ...mcInputs(20000),
    ],
    compute: (p) => {
      const res = longstaffSchwartz(p);
      return {
        'Pris (amerikansk)': res.price,
        ...ci(res),
        'Europeisk, samme stier': res.european,
        'Europeisk BSM (analytisk)': res.bsm,
        'Tidligutøvelsespremie (mot BSM)': res.price - res.bsm,
      };
    },
    greeks: false,
    chart: false,
  },
];
