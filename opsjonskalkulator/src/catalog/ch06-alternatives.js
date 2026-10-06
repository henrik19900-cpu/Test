import {
  tradingDaysBSM, mertonJumpDiffusion, batesJumpDiffusion, leland, hullWhite87, hullWhite88,
  sabr, sabrVol, cev, cevExpectedSpot, displacedDiffusion, heston, hestonExpectedVariance,
} from '../models/alternatives.js';
import { gbsm, impliedVolGBSM } from '../models/bsm.js';
import { callPut, num, int, select, S, X, T, r, b, v, rho } from './common.js';

// Implisitt BSM-volatilitet som tall, eller en forklarende tekst når den ikke finnes.
const iv = (p, price) => {
  try {
    return impliedVolGBSM({ type: p.type, S: p.S, X: p.X, T: p.T, r: p.r, b: p.b, price });
  } catch {
    return 'ikke definert';
  }
};

const nonneg = { min: 0 };
const positive = { min: 0, exclusiveMin: true };

export default [
  {
    id: 'alt-trading-days',
    chapter: 6,
    group: 'Justert BSM',
    name: 'BSM justert for handelsdager',
    authors: 'French (1984)',
    description: 'Volatiliteten virker bare på handelsdager, mens rente og cost of carry løper over kalenderdager. σ er volatilitet per handelsår.',
    payoff: 'max(S_T − X, 0) / max(X − S_T, 0)',
    inputs: [
      callPut('call'), S(100), X(100),
      int('calDays', 'Kalenderdager til forfall', 60, { min: 1 }),
      int('tradeDays', 'Handelsdager til forfall', 42, nonneg),
      num('calYear', 'Kalenderdager per år', 365, positive),
      num('tradeYear', 'Handelsdager per år', 252, positive),
      r(0.05), b(0.05), v(0.2, 'Volatilitet σ (per handelsår)'),
    ],
    compute: (p) => {
      const T = p.calDays / p.calYear;
      const t = p.tradeDays / p.tradeYear;
      const q = { type: p.type, S: p.S, X: p.X, T, r: p.r, b: p.b };
      return {
        'Pris': tradingDaysBSM({ ...q, t, v: p.v }),
        'Kalendertid T (år)': T,
        'Handelstid t (år)': t,
        'Effektiv volatilitet over kalendertid σ√(t/T)': p.v * Math.sqrt(t / T),
        'BSM uten justering (σ over kalendertid)': gbsm({ ...q, v: p.v }),
      };
    },
  },
  {
    id: 'alt-merton-jump',
    chapter: 6,
    group: 'Hopp-diffusjon',
    name: 'Merton hopp-diffusjon',
    authors: 'Merton (1976)',
    description: 'Kursen følger en diffusjon med lognormale hopp. Total volatilitet σ deles i en diffusjonsdel og en hoppdel, der γ er andelen av variansen som skyldes hopp.',
    payoff: 'max(S_T − X, 0) / max(X − S_T, 0)',
    inputs: [
      callPut('call'), S(45), X(55), T(0.25), r(0.1), b(0.1), v(0.25, 'Total volatilitet σ'),
      num('lambda', 'Forventet antall hopp per år λ', 3, nonneg),
      num('gamma', 'Andel av variansen fra hopp γ', 0.4, { min: 0, max: 1 }),
    ],
    compute: (p) => {
      const price = mertonJumpDiffusion(p);
      return {
        'Pris': price,
        'BSM med samme totale volatilitet': gbsm(p),
        'Diffusjonsvolatilitet z = σ√(1 − γ)': p.v * Math.sqrt(1 - p.gamma),
        'Standardavvik per hopp δ = √(γσ²/λ)': p.lambda > 0 ? Math.sqrt(p.gamma * p.v * p.v / p.lambda) : 0,
        'Implisitt BSM-volatilitet': iv(p, price),
      };
    },
    example: 0.2417,
  },
  {
    id: 'alt-bates-jump',
    chapter: 6,
    group: 'Hopp-diffusjon',
    name: 'Generalisert hopp-diffusjon',
    authors: 'Merton (1976), Bates (1991)',
    description: 'Hopp-diffusjon der hoppene kan ha forventning ulik null: k̄ er forventet relativ hoppstørrelse og δ standardavviket til logaritmen av hoppfaktoren. σ er diffusjonsvolatiliteten.',
    payoff: 'max(S_T − X, 0) / max(X − S_T, 0)',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.08), b(0.08), v(0.2, 'Diffusjonsvolatilitet σ'),
      num('lambda', 'Forventet antall hopp per år λ', 1, nonneg),
      num('kbar', 'Forventet relativ hoppstørrelse k̄', -0.1, { min: -1, exclusiveMin: true, unit: 'rate' }),
      num('delta', 'Volatilitet i hoppstørrelsen δ', 0.3, { ...nonneg, unit: 'rate' }),
    ],
    compute: (p) => {
      const price = batesJumpDiffusion(p);
      const g = Math.log1p(p.kbar) - 0.5 * p.delta * p.delta;
      const total = Math.sqrt(p.v * p.v + p.lambda * (p.delta * p.delta + g * g));
      return {
        'Pris': price,
        'BSM med diffusjonsvolatiliteten': gbsm(p),
        'Total volatilitet i ln S per år': total,
        'BSM med total volatilitet': gbsm({ ...p, v: total }),
        'Implisitt BSM-volatilitet': iv(p, price),
      };
    },
  },
  {
    id: 'alt-leland',
    chapter: 6,
    group: 'Transaksjonskostnader',
    name: 'Leland – transaksjonskostnader',
    authors: 'Leland (1985)',
    description: 'Diskret delta-sikring med proporsjonale transaksjonskostnader tas hensyn til ved å justere volatiliteten: opp for den som har solgt opsjonen, ned for den som har kjøpt.',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.1), b(0.1), v(0.3),
      num('k', 'Transaksjonskostnad k (rundtur, andel av beløpet)', 0.01, { ...nonneg, unit: 'rate' }),
      int('freq', 'Rebalanseringer per år (Δt = 1/antall)', 52, { min: 1 }),
      select('position', 'Posisjon', [
        { value: 'short', label: 'Kort opsjon (utsteder som sikrer)' },
        { value: 'long', label: 'Lang opsjon (kjøper som sikrer)' },
      ], 'short'),
    ],
    compute: (p) => {
      const res = leland({ ...p, dt: 1 / p.freq });
      return {
        'Pris': res.price,
        'Justert volatilitet σ_A': res.vA,
        'Leland-tall √(2/π)·k/(σ√Δt)': res.le,
        'BSM uten kostnader': gbsm(p),
      };
    },
  },
  {
    id: 'alt-hull-white-87',
    chapter: 6,
    group: 'Stokastisk volatilitet',
    name: 'Hull-White – ukorrelert stokastisk volatilitet',
    authors: 'Hull og White (1987)',
    description: 'Variansen V = σ² følger dV = μV dt + ξV dW uten korrelasjon med kursen. Prisen er BSM med forventet gjennomsnittsvarians pluss korreksjoner for variansen og skjevheten til gjennomsnittsvariansen (rekkeutvikling).',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.05), b(0.05), v(0.2, 'Startvolatilitet σ'),
      num('xi', 'Volatilitet til variansen ξ', 0.8, { ...nonneg, unit: 'rate' }),
      num('mu', 'Drift i variansen μ', 0, { unit: 'rate' }),
    ],
    compute: (p) => {
      const res = hullWhite87(p);
      return {
        'Pris': res.price,
        'BSM med gjennomsnittsvolatilitet σ̄': res.bs,
        'Gjennomsnittsvolatilitet σ̄ = √E[V̄]': res.vbar,
        'Standardavvik til gjennomsnittsvariansen': res.sdVbar,
        'Korreksjon for variansen til V̄': res.second,
        'Korreksjon for skjevheten til V̄': res.third,
        'Implisitt BSM-volatilitet': iv(p, res.price),
      };
    },
  },
  {
    id: 'alt-hull-white-88',
    chapter: 6,
    group: 'Stokastisk volatilitet',
    name: 'Hull-White – korrelert stokastisk volatilitet',
    authors: 'Hull og White (1988)',
    description: 'Variansen følger dV = κ(σ_LR² − V)dt + ξV dW₂ med korrelasjon ρ mot kursen. Prisen er en rekkeutvikling til andre orden i ξ rundt BSM med forventet gjennomsnittsvarians.',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.05), b(0.05),
      v(0.2, 'Startvolatilitet σ₀'),
      num('vLR', 'Langsiktig volatilitet σ_LR', 0.2, { ...positive, unit: 'rate' }),
      num('kappa', 'Mean reversion-hastighet κ', 1, nonneg),
      num('xi', 'Volatilitet til variansen ξ', 0.5, { ...nonneg, unit: 'rate' }),
      rho(-0.5),
    ],
    compute: (p) => {
      const res = hullWhite88(p);
      return {
        'Pris': res.price,
        'BSM med gjennomsnittsvolatilitet σ̄': res.bs,
        'Gjennomsnittsvolatilitet σ̄': res.vbar,
        'Korreksjon av første orden (korrelasjon)': res.first,
        'Korreksjon av andre orden': res.second,
        'Implisitt BSM-volatilitet': iv(p, res.price),
      };
    },
  },
  {
    id: 'alt-sabr',
    chapter: 6,
    group: 'Stokastisk volatilitet',
    name: 'SABR – implisitt volatilitet og pris',
    authors: 'Hagan, Kumar, Lesniewski og Woodward (2002)',
    description: 'Forwarden følger dF = αF^β dW₁ og volatiliteten dα = να dW₂ med korrelasjon ρ. Hagans formel gir implisitt Black-volatilitet, som settes inn i generalisert BSM med F = S e^{bT}.',
    inputs: [
      callPut('call'), S(100, 'Spot-/forwardpris S'), X(110), T(1), r(0.05), b(0),
      num('alpha', 'Volatilitetsnivå α', 2, { ...positive, help: 'ATM-volatiliteten er omtrent α/F^{1−β}: med β = 0,5 og F = 100 gir α = 2 om lag 20 %.' }),
      num('beta', 'Elastisitet β', 0.5, { min: 0, max: 1 }),
      rho(-0.4),
      num('nu', 'Volatilitet til volatiliteten ν', 0.4, { ...nonneg, unit: 'rate' }),
    ],
    compute: (p) => {
      const res = sabr(p);
      return {
        'Pris': res.price,
        'Implisitt Black-volatilitet': res.vol,
        'ATM-volatilitet (X = F)': sabrVol({ F: res.F, X: res.F, T: p.T, alpha: p.alpha, beta: p.beta, rho: p.rho, nu: p.nu }),
        'Forwardpris F': res.F,
      };
    },
  },
  {
    id: 'alt-cev',
    chapter: 6,
    group: 'Lokal volatilitet',
    name: 'CEV – konstant elastisitet i variansen',
    authors: 'Cox (1975), Schroder (1989)',
    description: 'dS = bS dt + σS^{β/2} dW, så lokal volatilitet er σS^{β/2−1}. β = 2 gir BSM; β < 2 gir høyere volatilitet når kursen faller. Prisen regnes med ikke-sentral kjikvadratfordeling.',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.1), b(0.1),
      num('v', 'Volatilitetsparameter σ', 3, { ...positive, help: 'Lokal volatilitet ved S er σS^{β/2−1}: σ = 3 og β = 1 gir 30 % ved S = 100.' }),
      num('beta', 'Elastisitet β (β = 2 gir BSM)', 1, nonneg),
    ],
    compute: (p) => {
      const price = cev(p);
      const localVol = p.v * Math.pow(p.S, p.beta / 2 - 1);
      const res = {
        'Pris': price,
        'Lokal volatilitet ved S: σS^{β/2−1}': localVol,
        'BSM med lokal volatilitet ved S': gbsm({ ...p, v: localVol }),
        'Implisitt BSM-volatilitet': iv(p, price),
      };
      if (p.beta > 2) res['Forventet S_T (under S e^{bT} når β > 2)'] = cevExpectedSpot(p);
      return res;
    },
  },
  {
    id: 'alt-displaced-diffusion',
    chapter: 6,
    group: 'Lokal volatilitet',
    name: 'Fortrengt diffusjon',
    authors: 'Rubinstein (1983)',
    description: 'En andel a av verdien er risikable eiendeler med volatilitet σ, resten er risikofri. Aksjens volatilitet blir da aσ i dag og stiger når kursen faller.',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.05), b(0.05),
      v(0.3, 'Volatilitet til de risikable eiendelene σ'),
      num('a', 'Andel risikable eiendeler a', 0.6, { min: 0, max: 1, exclusiveMin: true }),
    ],
    compute: (p) => {
      const price = displacedDiffusion(p);
      return {
        'Pris': price,
        'Aksjevolatilitet i dag aσ': p.a * p.v,
        'BSM med volatilitet aσ': gbsm({ ...p, v: p.a * p.v }),
        'Implisitt BSM-volatilitet': iv(p, price),
      };
    },
  },
  {
    id: 'alt-heston',
    chapter: 6,
    group: 'Stokastisk volatilitet',
    name: 'Heston – stokastisk volatilitet',
    authors: 'Heston (1993)',
    description: 'Variansen følger dv = κ(θ − v)dt + σ_v√v dW₂ med korrelasjon ρ mot kursen. Prisen regnes eksakt fra den karakteristiske funksjonen (Lewis’ integral).',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.03), b(0.03),
      num('v0', 'Startvolatilitet √v₀', 0.2, { ...nonneg, unit: 'rate' }),
      num('vLR', 'Langsiktig volatilitet √θ', 0.2, { ...nonneg, unit: 'rate' }),
      num('kappa', 'Mean reversion-hastighet κ', 2, nonneg),
      num('sigma', 'Volatilitet til variansen σ_v', 0.3, { ...nonneg, unit: 'rate' }),
      rho(-0.7),
    ],
    compute: (p) => {
      const q = { ...p, v0: p.v0 * p.v0, theta: p.vLR * p.vLR };
      const price = heston(q);
      const vbar = Math.sqrt(hestonExpectedVariance({ T: p.T, v0: q.v0, kappa: p.kappa, theta: q.theta }));
      return {
        'Pris': price,
        'BSM med forventet gjennomsnittsvarians': gbsm({ ...p, v: vbar }),
        'Forventet gjennomsnittsvolatilitet': vbar,
        'Implisitt BSM-volatilitet': iv(p, price),
        'Feller-forhold 2κθ/σ_v² (≥ 1: v når ikke null)': p.sigma > 0 ? 2 * p.kappa * q.theta / (p.sigma * p.sigma) : 'uendelig',
      };
    },
  },
];
