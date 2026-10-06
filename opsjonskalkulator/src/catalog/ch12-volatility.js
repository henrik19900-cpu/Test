import {
  closeToCloseVol, ewmaVol, parkinsonVol, garmanKlassVol, rogersSatchellVol, yangZhangVol,
  volConfidenceInterval, impliedVolApproximations, impliedForwardVol, historicalCorrelation,
  corrDensity, corrCdf, corrMean, impliedCorrelationFX, impliedIndexCorrelation, varianceSwapStrike,
} from '../models/volatility.js';
import { cnd } from '../math/normal.js';
import { callPut, num, int, list, select, S, X, T, r, b } from './common.js';

// Syntetiske eksempeldata (21 handelsdager, simulert med σ ≈ 25 %, avrundet til øre).
const OPEN = [100.29, 101.04, 99.06, 100.3, 101.4, 99.73, 101.89, 103.93, 103.25, 102.15, 104.22, 105.25, 104.61,
  105.49, 106.38, 107.22, 105.2, 104.91, 104.66, 105.74, 105.04];
const HIGH = [101.2, 101.55, 100.88, 101.47, 101.86, 101.62, 104.13, 104.44, 103.66, 104.74, 105.75, 105.93, 106.82,
  106.8, 109.47, 108.01, 106.38, 106.18, 106.79, 105.97, 106.87];
const LOW = [99.59, 98.72, 97.62, 99.34, 99.16, 99.63, 101.63, 102.36, 102.09, 101.94, 103.36, 102.95, 104.28, 105.22,
  106.32, 105.56, 104.63, 104.86, 104.35, 104, 104.86];
const CLOSE = [100.48, 99.33, 99.89, 101.11, 99.64, 101.3, 103.5, 102.69, 103.02, 103.48, 105.6, 104.43, 106.61,
  106.36, 107.83, 105.78, 105.68, 105.1, 106.45, 104.36, 104.86];
const SERIES_A = [50, 49.49, 48.59, 47.91, 48.5, 48.53, 47.93, 47.58, 48.56, 47.86, 47.99, 48, 48.31, 46.69, 46.27,
  46.12, 47.52, 48.31, 46.8, 46.31, 44.96, 43.94];
const SERIES_B = [120, 119.48, 118.49, 116.63, 114.51, 114.98, 113.72, 112.4, 113.2, 112.3, 110.91, 112.19, 111.45,
  110.67, 108.09, 107.53, 107.07, 109.42, 108.38, 109.3, 107.36, 108.17];

const positive = { min: 0, exclusiveMin: true };
const ppy = () => num('ppy', 'Antall perioder per år', 252, positive);
const conf = () => num('conf', 'Konfidensnivå', 0.95, { min: 0, max: 1, exclusiveMin: true, exclusiveMax: true });
const prices = (key, label, def) => list(key, label, def, { minLength: 3 });
const off = { greeks: false, chart: false };

export default [
  {
    id: 'vol-hist-close',
    chapter: 12,
    group: 'Historisk volatilitet',
    name: 'Historisk volatilitet fra sluttkurser',
    authors: 'Standardestimatoren (close-to-close)',
    description: 'Standardavviket til logavkastningene ln(S_i/S_{i−1}), skalert med √(perioder per år). Intervallet bygger på at (n − 1)σ̂²/σ² er kjikvadratfordelt.',
    inputs: [prices('closes', 'Sluttkurser', CLOSE), ppy(), conf()],
    compute: (p) => {
      const res = closeToCloseVol(p.closes, p.ppy);
      const ci = volConfidenceInterval({ sigma: res.sigma, n: res.n, conf: p.conf });
      return {
        'Volatilitet (årlig)': res.sigma,
        'Volatilitet per periode': res.sigmaPeriod,
        'Antall avkastninger n': res.n,
        'Gjennomsnittlig logavkastning per periode': res.mean,
        'Konfidensintervall, nedre': ci.lower,
        'Konfidensintervall, øvre': ci.upper,
      };
    },
    ...off,
  },
  {
    id: 'vol-hist-ewma',
    chapter: 12,
    group: 'Historisk volatilitet',
    name: 'Eksponentielt vektet historisk volatilitet',
    authors: 'EWMA (RiskMetrics, λ = 0,94)',
    description: 'Avkastning i kvadrat vektes med λ^i, der i = 0 er siste periode. Vektene er normert til å summere til 1, og avkastningene sentreres ikke.',
    inputs: [
      prices('closes', 'Sluttkurser', CLOSE),
      num('lambda', 'Vektfaktor λ', 0.94, { min: 0, max: 1, exclusiveMin: true }),
      ppy(),
    ],
    compute: (p) => {
      const res = ewmaVol(p.closes, p.lambda, p.ppy);
      return {
        'EWMA-volatilitet (årlig)': res.sigma,
        'EWMA-volatilitet per periode': res.sigmaPeriod,
        'Vekt på siste avkastning': res.weightLatest,
        'Likevektet volatilitet (sluttkurser)': closeToCloseVol(p.closes, p.ppy).sigma,
      };
    },
    ...off,
  },
  {
    id: 'vol-hist-parkinson',
    chapter: 12,
    group: 'Historisk volatilitet',
    name: 'Høy-lav-volatilitet',
    authors: 'Parkinson (1980)',
    description: 'Bruker spennet mellom høyeste og laveste kurs i hver periode: σ² = Σ ln²(H/L) / (4n ln 2). Mer effektiv enn sluttkurser når kursen følger en driftfri diffusjon.',
    inputs: [prices('highs', 'Høykurser', HIGH), prices('lows', 'Lavkurser', LOW), ppy()],
    compute: (p) => {
      const res = parkinsonVol(p.highs, p.lows, p.ppy);
      return {
        'Parkinson-volatilitet (årlig)': res.sigma,
        'Volatilitet per periode': res.sigmaPeriod,
        'Antall perioder': res.n,
      };
    },
    ...off,
  },
  {
    id: 'vol-hist-ohlc',
    chapter: 12,
    group: 'Historisk volatilitet',
    name: 'Volatilitet fra åpning, høy, lav og slutt',
    authors: 'Garman og Klass (1980), Rogers og Satchell (1991), Yang og Zhang (2000)',
    description: 'Estimatorer som bruker hele dagsprisbildet. Garman-Klass forutsetter null drift, Rogers-Satchell tåler drift, og Yang-Zhang tar også med hoppet fra forrige slutt til åpning.',
    inputs: [
      prices('opens', 'Åpningskurser', OPEN), prices('highs', 'Høykurser', HIGH),
      prices('lows', 'Lavkurser', LOW), prices('closes', 'Sluttkurser', CLOSE), ppy(),
    ],
    compute: (p) => {
      const args = [p.opens, p.highs, p.lows, p.closes, p.ppy];
      return {
        'Garman-Klass (årlig)': garmanKlassVol(...args).sigma,
        'Garman-Klass med forrige slutt som åpning': garmanKlassVol(null, p.highs, p.lows, p.closes, p.ppy).sigma,
        'Rogers-Satchell (årlig)': rogersSatchellVol(...args).sigma,
        'Yang-Zhang (årlig)': yangZhangVol(...args).sigma,
        'Parkinson (årlig)': parkinsonVol(p.highs, p.lows, p.ppy).sigma,
        'Sluttkurs til sluttkurs (årlig)': closeToCloseVol(p.closes, p.ppy).sigma,
      };
    },
    ...off,
  },
  {
    id: 'vol-confidence',
    chapter: 12,
    group: 'Historisk volatilitet',
    name: 'Konfidensintervall for volatilitet',
    authors: 'Kjikvadratfordelingen til utvalgsvariansen',
    description: 'For n normalfordelte avkastninger er (n − 1)σ̂²/σ² kjikvadratfordelt med n − 1 frihetsgrader. Gir et intervall for den sanne volatiliteten.',
    inputs: [
      num('sigma', 'Estimert volatilitet σ̂', 0.3, { ...positive, unit: 'rate' }),
      int('n', 'Antall avkastninger n', 20, { min: 2 }),
      conf(),
    ],
    compute: (p) => {
      const ci = volConfidenceInterval(p);
      return { 'Nedre grense': ci.lower, 'Øvre grense': ci.upper, 'Frihetsgrader n − 1': p.n - 1 };
    },
    ...off,
  },
  {
    id: 'vol-implied-approx',
    chapter: 12,
    group: 'Implisitt volatilitet',
    name: 'Implisitt volatilitet – tilnærmingsformler',
    authors: 'Brenner og Subrahmanyam (1988), Corrado og Miller (1996), Bharadia, Christofides og Salkin (1996)',
    description: 'Lukkede tilnærminger til implisitt volatilitet, sammenlignet med eksakt løsning (Newton-Raphson). En put gjøres om til call med put-call-pariteten.',
    inputs: [
      callPut('call'), S(59), X(60), T(0.25), r(0.067), b(0.067),
      num('price', 'Observert opsjonspris', 2.82, positive),
    ],
    compute: (p) => {
      const a = impliedVolApproximations(p);
      const exact = Number.isFinite(a.exact) ? a.exact : 'ikke definert';
      const err = (x) => (Number.isFinite(a.exact) ? x - a.exact : 'ikke definert');
      return {
        'Eksakt implisitt volatilitet': exact,
        'Brenner-Subrahmanyam': a.brennerSubrahmanyam,
        'Corrado-Miller': a.corradoMiller,
        'Bharadia-Christofides-Salkin': a.bcs,
        'Avvik Brenner-Subrahmanyam': err(a.brennerSubrahmanyam),
        'Avvik Corrado-Miller': err(a.corradoMiller),
        'Avvik Bharadia-Christofides-Salkin': err(a.bcs),
        'Manaster-Koehler startverdi for Newton': a.manasterKoehler,
        ...(a.cmNegativeRoot ? { 'Merknad': 'Kvadratroten i Corrado-Miller ble negativ og er satt til null.' } : {}),
      };
    },
    ...off,
  },
  {
    id: 'vol-implied-forward',
    chapter: 12,
    group: 'Implisitt volatilitet',
    name: 'Implisitt forward-volatilitet',
    authors: 'Additiv total varians',
    description: 'Volatiliteten mellom T1 og T2 som implisitt ligger i to implisitte volatiliteter: σ_F² = (σ2²T2 − σ1²T1)/(T2 − T1).',
    inputs: [
      num('v1', 'Implisitt volatilitet σ1 (kort løpetid)', 0.2, { ...positive, unit: 'rate' }),
      num('T1', 'Løpetid T1 (år)', 0.5, positive),
      num('v2', 'Implisitt volatilitet σ2 (lang løpetid)', 0.25, { ...positive, unit: 'rate' }),
      num('T2', 'Løpetid T2 (år)', 1, positive),
    ],
    compute: (p) => {
      const fv = impliedForwardVol(p);
      return { 'Forward-volatilitet σ_F': fv, 'Forward-varians σ_F²': fv * fv };
    },
    ...off,
  },
  {
    id: 'vol-hist-correlation',
    chapter: 12,
    group: 'Korrelasjon',
    name: 'Historisk korrelasjon',
    authors: 'Pearson; konfidensintervall: Fisher (1915)',
    description: 'Korrelasjonen mellom logavkastningene til to prisrekker, med konfidensintervall fra Fishers z-transformasjon atanh(ρ̂) ± z_{α/2}/√(n − 3).',
    inputs: [
      list('prices1', 'Prisrekke 1', SERIES_A, { minLength: 5 }),
      list('prices2', 'Prisrekke 2', SERIES_B, { minLength: 5 }),
      conf(), ppy(),
    ],
    compute: (p) => {
      const res = historicalCorrelation(p.prices1, p.prices2, p.conf, p.ppy);
      return {
        'Korrelasjon ρ̂': res.rho,
        'Konfidensintervall, nedre': res.lower,
        'Konfidensintervall, øvre': res.upper,
        'Antall avkastninger n': res.n,
        't-verdi for ρ = 0': res.tStat,
        'Volatilitet rekke 1 (årlig)': res.v1,
        'Volatilitet rekke 2 (årlig)': res.v2,
      };
    },
    ...off,
  },
  {
    id: 'vol-corr-distribution',
    chapter: 12,
    group: 'Korrelasjon',
    name: 'Fordelingen til empirisk korrelasjon',
    authors: 'Fisher (1915), Hotelling (1953)',
    description: 'Eksakt fordeling til korrelasjonskoeffisienten fra n par binormale observasjoner med sann korrelasjon ρ, sammenlignet med Fishers normaltilnærming.',
    inputs: [
      num('rho', 'Sann korrelasjon ρ', 0.5, { min: -1, max: 1, exclusiveMin: true, exclusiveMax: true }),
      int('n', 'Antall observasjonspar n', 20, { min: 4 }),
      num('rhat', 'Verdi r for empirisk korrelasjon', 0.3, { min: -1, max: 1 }),
    ],
    compute: (p) => {
      const fisher = cnd((Math.atanh(Math.max(-1 + 1e-15, Math.min(1 - 1e-15, p.rhat))) - Math.atanh(p.rho)) * Math.sqrt(p.n - 3));
      return {
        'P(ρ̂ ≤ r)': corrCdf(p.rhat, p.rho, p.n),
        'Tetthet f(r)': corrDensity(p.rhat, p.rho, p.n),
        'Forventet ρ̂': corrMean(p.rho, p.n),
        'P(ρ̂ ≤ r), Fishers tilnærming': fisher,
      };
    },
    ...off,
  },
  {
    id: 'vol-implied-corr-fx',
    chapter: 12,
    group: 'Korrelasjon',
    name: 'Implisitt korrelasjon fra valutaopsjoner',
    authors: 'Volatiliteten til en krysskurs',
    description: 'Tre implisitte valutavolatiliteter bestemmer korrelasjonen: er krysskursen S1/S2, er σ₁₂² = σ1² + σ2² − 2ρσ1σ2.',
    inputs: [
      num('v1', 'Volatilitet σ1 til valutakurs S1', 0.1, { ...positive, unit: 'rate' }),
      num('v2', 'Volatilitet σ2 til valutakurs S2', 0.12, { ...positive, unit: 'rate' }),
      num('v12', 'Volatilitet σ₁₂ til krysskursen', 0.13, { min: 0, unit: 'rate' }),
      select('cross', 'Krysskursen er', [
        { value: 'ratio', label: 'S1/S2 (f.eks. EUR/USD fra EUR/NOK og USD/NOK)' },
        { value: 'product', label: 'S1·S2 (f.eks. EUR/JPY fra EUR/USD og USD/JPY)' },
      ], 'ratio'),
    ],
    compute: (p) => ({ 'Implisitt korrelasjon ρ': impliedCorrelationFX(p) }),
    ...off,
  },
  {
    id: 'vol-implied-corr-index',
    chapter: 12,
    group: 'Korrelasjon',
    name: 'Gjennomsnittlig implisitt indekskorrelasjon',
    authors: 'Lik parvis korrelasjon i indeksvariansen',
    description: 'Korrelasjonen ρ̄ som gjør σ_I² = Σw_i²σ_i² + ρ̄ Σ_{i≠j} w_i w_j σ_i σ_j, gitt implisitt volatilitet for indeksen og komponentene.',
    inputs: [
      num('vIndex', 'Indeksvolatilitet σ_I', 0.18, { ...positive, unit: 'rate' }),
      list('weights', 'Vekter w_i', [0.4, 0.35, 0.25], { minLength: 2 }),
      list('vols', 'Komponentvolatiliteter σ_i', [0.25, 0.22, 0.3], { minLength: 2 }),
    ],
    compute: (p) => {
      const res = impliedIndexCorrelation(p);
      return {
        'Implisitt korrelasjon ρ̄': res.rho,
        'Indeksvolatilitet ved ρ = 0': res.vIndexUncorrelated,
        'Indeksvolatilitet ved ρ = 1': res.vIndexPerfect,
      };
    },
    ...off,
  },
  {
    id: 'vol-variance-swap',
    chapter: 12,
    group: 'Variansswap',
    name: 'Variance swap – rettferdig variansstrike',
    authors: 'Demeterfi, Derman, Kamal og Zou (1999)',
    description: 'Rettferdig strike for realisert varians, replikert statisk med en portefølje av OTM-opsjoner vektet med 1/K². Smilet er lineært i strike: σ(K) = σ₀ − skew·(K − F)/F.',
    inputs: [
      S(100), T(1), r(0.05), b(0.03),
      num('vAtm', 'ATM-volatilitet σ₀', 0.2, { ...positive, unit: 'rate' }),
      num('skew', 'Skjevhet (volatilitetsfall per 100 % høyere strike)', 0.2),
    ],
    compute: (p) => {
      const res = varianceSwapStrike(p);
      return {
        'Rettferdig variansstrike K_var': res.kvar,
        'Rettferdig volatilitet √K_var': res.kvol,
        'Tilnærming σ₀²(1 + 3T·skew²)': res.approx,
        'Forwardpris F': res.F,
      };
    },
    ...off,
  },
];
