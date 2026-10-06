// Kapittel 10: råvare- og energiopsjoner.
// Black-76 for energifutures finnes i kapittel 1 (bsm-black76), asiatiske opsjoner i kapittel 4
// og spreadopsjoner (Kirk) i kapittel 5.
import {
  energySwap, energySwaption, miltersenSchwartz, schwartz1fOption, schwartz2fOption,
} from '../models/commodity.js';
import { callPut, num, int, list, select, S, F, X, T, r, v, rho } from './common.js';

const pos = { min: 0, exclusiveMin: true };

const payerReceiver = (def = 'call') => select('type', 'Type', [
  { value: 'call', label: 'Betaler fastpris (payer)' },
  { value: 'put', label: 'Mottar fastpris (receiver)' },
], def);

const T2 = (d) => num('T2', 'Futureskontraktens forfall T2 (år)', d, pos);
const kappa = (d, label = 'Mean reversion-hastighet κ', key = 'kappa') => num(key, label, d, { min: 0 });

export default [
  {
    id: 'com-energy-swap',
    chapter: 10,
    group: 'Energiswapper',
    name: 'Energiswap – fastpris mot flytende pris',
    authors: 'Haug (2007), kap. 10',
    description: 'En energiswap er en rekke forwardkontrakter. Verdien er nåverdien av (F_i − X) over oppgjørene, og swapprisen er fastprisen som gir verdi null.',
    payoff: 'Q (S_{T_i} − X) ved hvert oppgjør T_i for den som betaler fastpris',
    inputs: [
      list('times', 'Oppgjørstidspunkter T_i (år)', [0.25, 0.5, 0.75, 1], { minLength: 1 }),
      list('forwards', 'Forwardpriser F_i', [45.3, 42.1, 48.7, 51.2], { minLength: 1 }),
      list('rates', 'Kontinuerlige renter r_i', [0.04], {
        minLength: 1,
        help: 'Én verdi gir flat rente for alle oppgjør; ellers én rente per oppgjørstidspunkt.',
      }),
      X(46, 'Fastpris X'),
      num('Q', 'Volum per oppgjør Q', 1, pos),
    ],
    compute: (p) => {
      const s = energySwap(p);
      return {
        'Verdi for den som betaler fastpris': s.value,
        'Verdi for den som mottar fastpris': -s.value,
        'Swappris (fastpris som gir verdi null)': s.swapPrice,
        'Nåverdi av flytende ben': s.pvFloat,
        'Nåverdi av fast ben': s.pvFixed,
        'Annuitet Σ Q e^{−r_i T_i}': s.annuity,
      };
    },
  },
  {
    id: 'com-energy-swaption',
    chapter: 10,
    group: 'Energiswapper',
    name: 'Energiswapsjon',
    authors: 'Black (1976) på swapprisen',
    description: 'Rett til å gå inn i en energiswap til fastpris X ved tid T. Swapprisen antas lognormal, så prisen er annuiteten over swappens oppgjør ganger Black-76.',
    payoff: 'A · max(F_T − X, 0) (payer) / A · max(X − F_T, 0) (receiver), A = Σ Q e^{−r(T + i/j)}',
    inputs: [
      payerReceiver('call'), F(50, 'Swappris F (forward)'), X(50, 'Fastpris X'), T(0.5, 'Opsjonens løpetid T (år)'),
      int('n', 'Antall oppgjør n', 12, { min: 1 }), int('j', 'Oppgjør per år j', 12, { min: 1 }),
      r(0.05), v(0.25, 'Volatilitet i swapprisen σ'), num('Q', 'Volum per oppgjør Q', 1, pos),
    ],
    compute: (p) => {
      const s = energySwaption(p);
      return {
        'Pris': s.price,
        'Annuitet A': s.annuity,
        'Forward swapverdi A(F − X) = payer − receiver': s.forwardValue,
      };
    },
  },
  {
    id: 'com-miltersen-schwartz',
    chapter: 10,
    group: 'Opsjoner på råvarefutures',
    name: 'Miltersen og Schwartz – stokastisk rente og convenience yield',
    authors: 'Miltersen og Schwartz (1998)',
    description: 'Europeisk opsjon på en råvarefutures når både renten og convenience yield er stokastiske med mean reversion. Futuresprisen er lognormal, og σ_xz justerer for samvariasjonen mellom futurespris og rente.',
    payoff: 'max(F_T − X, 0) / max(X − F_T, 0)',
    inputs: [
      callPut('call'), F(95, 'Futurespris F'), X(80), T(0.5, 'Opsjonens løpetid T (år)'), T2(1),
      r(0.05, 'Nullkupongrente til T, r'),
      v(0.266, 'Volatilitet i spotprisen σ_S', 'vS'),
      num('vE', 'Volatilitet i convenience yield σ_E', 0.249, { min: 0, unit: 'rate' }),
      num('vf', 'Volatilitet i forwardrenten σ_f', 0.0096, { min: 0, unit: 'rate' }),
      rho(0.805, 'Korrelasjon spot–convenience yield ρ_SE', 'rhoSE'),
      rho(0.0805, 'Korrelasjon spot–rente ρ_Sf', 'rhoSf'),
      rho(0.1243, 'Korrelasjon convenience yield–rente ρ_Ef', 'rhoEf'),
      kappa(1.045, 'Mean reversion i convenience yield κ_E', 'kE'),
      kappa(0.2, 'Mean reversion i renten κ_f', 'kf'),
    ],
    compute: (p) => {
      const m = miltersenSchwartz(p);
      const out = {
        'Pris': m.price,
        'Standardavvik σ_z i ln F': m.vz,
        'Gjennomsnittlig volatilitet σ_z/√T': m.vz / Math.sqrt(p.T),
        'Justering σ_xz': m.sxz,
        'Justert futurespris F e^{−σ_xz}': m.Fadj,
        'P(0,T) = e^{−rT}': m.Pt,
      };
      if (m.vz > 0) Object.assign(out, { 'd1': m.d1, 'd2': m.d2 });
      return out;
    },
  },
  {
    id: 'com-schwartz-1f',
    chapter: 10,
    group: 'Mean reversion-modeller',
    name: 'Schwartz én-faktor – mean reversion i spotprisen',
    authors: 'Schwartz (1997)',
    description: 'Logaritmen av spotprisen trekkes mot et langsiktig risikonøytralt nivå α*. Gir futureskurven fra spotprisen og europeiske opsjoner på futures; T2 = T gir opsjon på spot.',
    payoff: 'max(F(T, T2) − X, 0) / max(X − F(T, T2), 0)',
    inputs: [
      callPut('call'), S(20), X(20), T(0.5, 'Opsjonens løpetid T (år)'), T2(1), r(0.05),
      kappa(0.3), num('alpha', 'Langsiktig nivå for ln S under Q, α*', 3.1), v(0.33),
    ],
    compute: (p) => {
      const o = schwartz1fOption(p);
      return {
        'Pris': o.price,
        'Futurespris F(0,T2)': o.F,
        'Futurespris F(0,T) (forventet spot ved T)': o.spotForward,
        'Effektiv volatilitet for opsjonen': o.veff,
        'Langsiktig futurespris e^{α* + σ²/(4κ)}': p.kappa > 0 ? Math.exp(p.alpha + p.v * p.v / (4 * p.kappa)) : '–',
      };
    },
  },
  {
    id: 'com-schwartz-2f',
    chapter: 10,
    group: 'Mean reversion-modeller',
    name: 'Schwartz to-faktor – stokastisk convenience yield',
    authors: 'Gibson og Schwartz (1990), Schwartz (1997)',
    description: 'Spotprisen er lognormal, og convenience yield δ følger en Ornstein-Uhlenbeck-prosess som er korrelert med spotprisen. Gir futurespris og europeisk opsjon på futures.',
    payoff: 'max(F(T, T2) − X, 0) / max(X − F(T, T2), 0)',
    inputs: [
      callPut('call'), S(20), X(20), T(0.5, 'Opsjonens løpetid T (år)'), T2(1), r(0.06),
      num('delta', 'Convenience yield i dag δ', 0.05, { unit: 'rate' }),
      kappa(1.2),
      num('alpha', 'Langsiktig convenience yield α̂ (risikojustert)', 0.06, { unit: 'rate' }),
      v(0.35, 'Volatilitet i spotprisen σ1', 'v1'),
      num('v2', 'Volatilitet i convenience yield σ2', 0.4, { min: 0, unit: 'rate' }),
      rho(0.8, 'Korrelasjon spot–convenience yield ρ'),
    ],
    compute: (p) => {
      const o = schwartz2fOption(p);
      return {
        'Pris': o.price,
        'Futurespris F(0,T2)': o.F,
        'Effektiv volatilitet for opsjonen': o.veff,
      };
    },
  },
];
