// Kapittel 5: eksotiske opsjoner på to underliggende, inkludert valutaoversatte opsjoner.
import {
  relativeOutperformance, productOption, twoAssetCorrelation, exchangeOption, americanExchangeOption,
  exchangeOnExchange, maxMinOption, maxMinTwoAverages, kirkSpread, spreadExact, twoAssetBarrier,
  partialTwoAssetBarrier, margrabeBarrier, exchangeEuropean, twoAssetCashOrNothing, bestWorstCashOrNothing,
} from '../models/two-asset.js';
import { foreignEquityDomesticStrike, quanto, equityLinkedFX, takeoverFX } from '../models/currency.js';
import { gbsm } from '../models/bsm.js';
import { callPut, num, select, X, T, r, q, v, rho } from './common.js';

const pos = { min: 0, exclusiveMin: true };
const carryHelp = 'b = r: aksje uten utbytte · b = r − q: utbytte q · b = 0: futures · b = r − rf: valuta';

const S1 = (d, label = 'Spotpris S1') => num('S1', label, d, pos);
const S2 = (d, label = 'Spotpris S2') => num('S2', label, d, pos);
const b1 = (d) => num('b1', 'Cost of carry b1', d, { unit: 'rate', help: carryHelp });
const b2 = (d) => num('b2', 'Cost of carry b2', d, { unit: 'rate', help: carryHelp });
const v1 = (d) => v(d, 'Volatilitet σ1', 'v1');
const v2 = (d) => v(d, 'Volatilitet σ2', 'v2');
const Q1 = (d = 1) => num('Q1', 'Antall enheter Q1 av aktivum 1', d, pos);
const Q2 = (d = 1) => num('Q2', 'Antall enheter Q2 av aktivum 2', d, pos);
const cash = (d) => num('K', 'Kontantbeløp K', d, pos);

const barrierKind = (def = 'down-out') => select('kind', 'Barrieretype', [
  { value: 'down-out', label: 'Ned-og-ut' },
  { value: 'up-out', label: 'Opp-og-ut' },
  { value: 'down-in', label: 'Ned-og-inn' },
  { value: 'up-in', label: 'Opp-og-inn' },
], def);
const complement = { 'down-out': 'down-in', 'up-out': 'up-in', 'down-in': 'down-out', 'up-in': 'up-out' };

const maxMinKind = (def = 'min') => select('kind', 'Variant', [
  { value: 'min', label: 'Minimum av de to' },
  { value: 'max', label: 'Maksimum av de to' },
], def);

const exchangeDirection = () => select('type', 'Retning', [
  { value: 'call', label: 'Motta Q1·S1, lever Q2·S2' },
  { value: 'put', label: 'Motta Q2·S2, lever Q1·S1' },
], 'call');

// Felles inndata for to aktiva: S1, S2, …, T, r, b1, b2, σ1, σ2, ρ.
const market = (d) => [T(d.T), r(d.r), b1(d.b1), b2(d.b2), v1(d.v1), v2(d.v2), rho(d.rho)];

const G_RATIO = 'Kvotient, produkt og korrelasjon';
const G_EXCH = 'Bytte og spread';
const G_MAXMIN = 'Maks og min';
const G_BARRIER = 'Barrierer på to aktiva';
const G_BINARY = 'Binære på to aktiva';
const G_FX = 'Valutaoversatte';

export default [
  // --- Kvotient, produkt og korrelasjon ---------------------------------------------
  {
    id: 'two-relative-outperformance',
    chapter: 5,
    group: G_RATIO,
    name: 'Relative outperformance-opsjon',
    authors: 'Haug (2007), kap. 5',
    description: 'Opsjon på forholdet S1/S2, det vil si på om ett aktivum gjør det bedre enn et annet. Prises med Black-76 på forwarden til forholdet.',
    payoff: 'max(S1/S2 − X, 0) / max(X − S1/S2, 0)',
    inputs: [
      callPut('call'), S1(130), S2(100), X(1.3, 'Innløsningskurs X (for S1/S2)'),
      ...market({ T: 0.25, r: 0.07, b1: 0.05, b2: 0.03, v1: 0.3, v2: 0.4, rho: 0.6 }),
    ],
    compute: (p) => {
      const res = relativeOutperformance(p);
      return { 'Pris': res.price, 'Forward for S1/S2': res.F, 'Volatilitet for S1/S2': res.v };
    },
  },
  {
    id: 'two-product',
    chapter: 5,
    group: G_RATIO,
    name: 'Produktopsjon',
    authors: 'Zhang (1998)',
    description: 'Opsjon på produktet S1·S2, for eksempel en utenlandsk aksje omregnet med valutakursen. Prises med Black-76 på forwarden til produktet.',
    payoff: 'max(S1·S2 − X, 0) / max(X − S1·S2, 0)',
    inputs: [
      callPut('call'), S1(100), S2(105), X(15000, 'Innløsningskurs X (for S1·S2)'),
      ...market({ T: 0.1, r: 0.07, b1: 0.02, b2: 0.05, v1: 0.3, v2: 0.3, rho: 0 }),
    ],
    compute: (p) => {
      const res = productOption(p);
      return { 'Pris': res.price, 'Forward for S1·S2': res.F, 'Volatilitet for S1·S2': res.v };
    },
    example: 2.4026,
  },
  {
    id: 'two-correlation',
    chapter: 5,
    group: G_RATIO,
    name: 'Two-asset correlation-opsjon',
    authors: 'Zhang (1995)',
    description: 'Utbetalingen er en vanlig opsjon på S2, men den utbetales bare hvis S1 samtidig ender over X1 (call) eller under X1 (put).',
    payoff: 'Call: max(S2 − X2, 0) hvis S1 > X1 · Put: max(X2 − S2, 0) hvis S1 < X1',
    inputs: [
      callPut('call'), S1(52), S2(65),
      num('X1', 'Innløsningskurs X1 (for S1)', 50, pos), num('X2', 'Innløsningskurs X2 (for S2)', 70, pos),
      ...market({ T: 0.5, r: 0.1, b1: 0.1, b2: 0.1, v1: 0.2, v2: 0.3, rho: 0.75 }),
    ],
    compute: (p) => ({ 'Pris': twoAssetCorrelation(p) }),
    example: 4.7073,
  },

  // --- Bytte og spread ------------------------------------------------------------
  {
    id: 'two-exchange',
    chapter: 5,
    group: G_EXCH,
    name: 'Bytteopsjon (europeisk)',
    authors: 'Margrabe (1978)',
    description: 'Retten til å bytte Q2 enheter av aktivum 2 mot Q1 enheter av aktivum 1 ved forfall.',
    payoff: 'max(Q1·S1 − Q2·S2, 0)',
    inputs: [
      S1(22), S2(20), Q1(), Q2(),
      ...market({ T: 0.1, r: 0.1, b1: 0.04, b2: 0.06, v1: 0.2, v2: 0.25, rho: -0.5 }),
    ],
    compute: (p) => {
      const res = exchangeOption(p);
      return { 'Pris': res.price, 'Volatilitet for S1/S2': res.v, 'Delta S1': res.delta1, 'Delta S2': res.delta2 };
    },
  },
  {
    id: 'two-exchange-american',
    chapter: 5,
    group: G_EXCH,
    name: 'Amerikansk bytteopsjon',
    authors: 'Bjerksund og Stensland (1993)',
    description: 'Bytteopsjon som kan innløses når som helst før forfall. Prises som en amerikansk call på forholdet S1/S2 med rente r − b2 og cost of carry b1 − b2.',
    payoff: 'Q1·S1 − Q2·S2 ved innløsning (tidspunkt velges av eieren)',
    inputs: [
      select('method', 'Tilnærming', [
        { value: '1993', label: 'Bjerksund og Stensland (1993)' },
        { value: '2002', label: 'Bjerksund og Stensland (2002)' },
      ], '1993'),
      S1(22), S2(20), Q1(), Q2(),
      ...market({ T: 0.1, r: 0.1, b1: 0.04, b2: 0.06, v1: 0.2, v2: 0.25, rho: -0.5 }),
    ],
    compute: (p) => {
      const res = americanExchangeOption(p);
      return {
        'Pris': res.price,
        'Europeisk bytteopsjon (Margrabe)': res.european,
        'Tidliginnløsningspremie': res.price - res.european,
        'Volatilitet for S1/S2': res.v,
      };
    },
  },
  {
    id: 'two-exchange-on-exchange',
    chapter: 5,
    group: G_EXCH,
    name: 'Bytteopsjon på bytteopsjon',
    authors: 'Carr (1988)',
    description: 'Gir ved t1 rett til å kjøpe (call) eller selge (put) en bytteopsjon som forfaller ved T2, mot Q enheter av aktivum 2.',
    payoff: 'Ved t1: max(C − Q·S2, 0) eller max(Q·S2 − C, 0), der C er bytteopsjonens verdi',
    inputs: [
      select('kind', 'Type', [
        { value: 'cc', label: 'Call på opsjonen max(S1 − S2, 0)' },
        { value: 'pc', label: 'Put på opsjonen max(S1 − S2, 0)' },
        { value: 'cp', label: 'Call på opsjonen max(S2 − S1, 0)' },
        { value: 'pp', label: 'Put på opsjonen max(S2 − S1, 0)' },
      ], 'cc'),
      S1(105), S2(100), num('Q', 'Antall enheter Q av aktivum 2 (betales/mottas ved t1)', 0.1, pos),
      num('t1', 'Utøvelsestidspunkt t1 (år)', 0.75, pos),
      num('T2', 'Forfall for bytteopsjonen T2 (år)', 1, pos),
      r(0.1), b1(0.1), b2(0.1), v1(0.2), v2(0.25), rho(-0.5),
    ],
    compute: (p) => {
      const res = exchangeOnExchange(p);
      return {
        'Pris': res.price,
        'Kritisk forhold S1/S2 ved t1': res.I,
        'Underliggende bytteopsjon i dag': res.underlying,
      };
    },
  },
  {
    id: 'two-spread-kirk',
    chapter: 5,
    group: G_EXCH,
    name: 'Spreadopsjon (Kirks tilnærming)',
    authors: 'Kirk (1995)',
    description: 'Opsjon på differansen mellom to futures- eller forwardpriser. Kirks formel er en tilnærming; eksakt verdi ved numerisk integrasjon vises til sammenligning.',
    payoff: 'max(F1 − F2 − X, 0) / max(X − F1 + F2, 0), der Fi = Si·e^{bi·T}',
    inputs: [
      callPut('call'), S1(28, 'Pris S1 (futurespris F1 når b1 = 0)'), S2(20, 'Pris S2 (futurespris F2 når b2 = 0)'),
      num('X', 'Innløsningskurs X (for spreaden)', 7),
      ...market({ T: 0.25, r: 0.05, b1: 0, b2: 0, v1: 0.29, v2: 0.36, rho: 0.42 }),
    ],
    compute: (p) => {
      const res = kirkSpread(p);
      const exact = spreadExact(p);
      return {
        'Pris': res.price,
        'Eksakt verdi (numerisk integrasjon)': exact,
        'Avvik Kirk − eksakt': res.price - exact,
        'Volatilitet i Kirks formel': res.v,
      };
    },
    example: 2.167,
  },

  // --- Maks og min ----------------------------------------------------------------
  {
    id: 'two-max-min',
    chapter: 5,
    group: G_MAXMIN,
    name: 'Opsjon på maks eller min av to aktiva',
    authors: 'Stulz (1982), Johnson (1987)',
    description: 'Call eller put på det største eller minste av to aktiva ved forfall (regnbueopsjon).',
    payoff: 'Call: max(max/min(S1, S2) − X, 0) · Put: max(X − max/min(S1, S2), 0)',
    inputs: [
      callPut('call'), maxMinKind('min'), S1(100), S2(105), X(98),
      ...market({ T: 0.5, r: 0.05, b1: -0.01, b2: -0.04, v1: 0.11, v2: 0.16, rho: 0.63 }),
    ],
    compute: (p) => ({
      'Pris': maxMinOption(p),
      'Vanilla på S1': gbsm({ type: p.type, S: p.S1, X: p.X, T: p.T, r: p.r, b: p.b1, v: p.v1 }),
      'Vanilla på S2': gbsm({ type: p.type, S: p.S2, X: p.X, T: p.T, r: p.r, b: p.b2, v: p.v2 }),
    }),
  },
  {
    id: 'two-max-min-average',
    chapter: 5,
    group: G_MAXMIN,
    name: 'Opsjon på maks eller min av to gjennomsnitt',
    authors: 'Stulz (1982) med geometriske gjennomsnitt',
    description: 'Call eller put på det største eller minste av to geometriske gjennomsnitt, kontinuerlig målt fra i dag til forfall. Hvert snitt er lognormalt med volatilitet σ/√3.',
    payoff: 'Call: max(max/min(A1, A2) − X, 0) · Put: max(X − max/min(A1, A2), 0)',
    inputs: [
      callPut('call'), maxMinKind('min'), S1(100), S2(105), X(98),
      ...market({ T: 0.5, r: 0.05, b1: -0.01, b2: -0.04, v1: 0.11, v2: 0.16, rho: 0.63 }),
    ],
    compute: (p) => ({
      'Pris': maxMinTwoAverages(p),
      'Samme opsjon på spotprisene ved forfall': maxMinOption(p),
    }),
  },

  // --- Barrierer på to aktiva ------------------------------------------------------
  {
    id: 'two-barrier',
    chapter: 5,
    group: G_BARRIER,
    name: 'To-aktiva-barriereopsjon',
    authors: 'Heynen og Kat (1994)',
    description: 'Utbetalingen er en vanlig call eller put på aktivum 1, mens barrieren H overvåkes kontinuerlig på aktivum 2.',
    payoff: 'max(S1 − X, 0) / max(X − S1, 0) hvis S2 har (inn) eller ikke har (ut) truffet H',
    inputs: [
      callPut('call'), barrierKind('down-out'), S1(100, 'Spotpris S1 (utbetaling)'), S2(100, 'Spotpris S2 (barriere)'),
      X(100, 'Innløsningskurs X (for S1)'), num('H', 'Barriere H (for S2)', 90, pos),
      ...market({ T: 0.5, r: 0.08, b1: 0.08, b2: 0.08, v1: 0.2, v2: 0.25, rho: 0.5 }),
    ],
    compute: (p) => ({
      'Pris': twoAssetBarrier(p),
      'Motsatt type (inn ↔ ut)': twoAssetBarrier({ ...p, kind: complement[p.kind] }),
      'Vanilla på S1 uten barriere': gbsm({ type: p.type, S: p.S1, X: p.X, T: p.T, r: p.r, b: p.b1, v: p.v1 }),
    }),
  },
  {
    id: 'two-barrier-partial',
    chapter: 5,
    group: G_BARRIER,
    name: 'Partial-time to-aktiva-barriereopsjon',
    authors: 'Bermin (1996)',
    description: 'Som to-aktiva-barrieren, men barrieren på aktivum 2 er bare aktiv fra i dag til t1. Utbetalingen på aktivum 1 skjer ved T.',
    payoff: 'max(S1 − X, 0) / max(X − S1, 0) hvis S2 har (inn) eller ikke har (ut) truffet H før t1',
    inputs: [
      callPut('call'), barrierKind('down-out'), S1(100, 'Spotpris S1 (utbetaling)'), S2(100, 'Spotpris S2 (barriere)'),
      X(100, 'Innløsningskurs X (for S1)'), num('H', 'Barriere H (for S2)', 90, pos),
      num('t1', 'Barrieren overvåkes til t1 (år)', 0.25, pos),
      ...market({ T: 0.5, r: 0.08, b1: 0.08, b2: 0.08, v1: 0.2, v2: 0.25, rho: 0.5 }),
    ],
    compute: (p) => ({
      'Pris': partialTwoAssetBarrier(p),
      'Motsatt type (inn ↔ ut)': partialTwoAssetBarrier({ ...p, kind: complement[p.kind] }),
      'Med barriere hele løpetiden': twoAssetBarrier(p),
      'Vanilla på S1 uten barriere': gbsm({ type: p.type, S: p.S1, X: p.X, T: p.T, r: p.r, b: p.b1, v: p.v1 }),
    }),
  },
  {
    id: 'two-margrabe-barrier',
    chapter: 5,
    group: G_BARRIER,
    name: 'Margrabe-barriereopsjon',
    authors: 'Haug og Haug (2002)',
    description: 'Bytteopsjon som slås inn eller ut når forholdet S1/S2 treffer barrieren H (kontinuerlig overvåket). Prises som en standard barriereopsjon på forholdet.',
    payoff: 'max(Q1·S1 − Q2·S2, 0) / max(Q2·S2 − Q1·S1, 0) hvis S1/S2 har (inn) eller ikke har (ut) truffet H',
    inputs: [
      exchangeDirection(), barrierKind('down-out'), S1(100), S2(100), Q1(), Q2(),
      num('H', 'Barriere H (for forholdet S1/S2)', 0.9, pos),
      ...market({ T: 0.5, r: 0.08, b1: 0.04, b2: 0.06, v1: 0.2, v2: 0.25, rho: -0.5 }),
    ],
    compute: (p) => ({
      'Pris': margrabeBarrier(p),
      'Motsatt type (inn ↔ ut)': margrabeBarrier({ ...p, kind: complement[p.kind] }),
      'Bytteopsjon uten barriere': exchangeEuropean(p),
    }),
  },

  // --- Binære på to aktiva ---------------------------------------------------------
  {
    id: 'two-cash-or-nothing',
    chapter: 5,
    group: G_BINARY,
    name: 'Two-asset cash-or-nothing',
    authors: 'Heynen og Kat (1996)',
    description: 'Betaler et fast beløp K ved forfall hvis begge aktivaene ender på riktig side av hver sin innløsningskurs.',
    payoff: 'K hvis betingelsen for valgt type er oppfylt ved forfall, ellers 0',
    inputs: [
      select('kind', 'Type', [
        { value: '1', label: 'Type 1: S1 > X1 og S2 > X2' },
        { value: '2', label: 'Type 2: S1 < X1 og S2 < X2' },
        { value: '3', label: 'Type 3: S1 > X1 og S2 < X2' },
        { value: '4', label: 'Type 4: S1 < X1 og S2 > X2' },
      ], '1'),
      S1(100), S2(100), num('X1', 'Innløsningskurs X1 (for S1)', 110, pos), num('X2', 'Innløsningskurs X2 (for S2)', 90, pos),
      cash(10),
      ...market({ T: 0.5, r: 0.1, b1: 0.05, b2: 0.06, v1: 0.2, v2: 0.25, rho: 0.5 }),
    ],
    compute: (p) => {
      const price = twoAssetCashOrNothing(p);
      return { 'Pris': price, 'Risikonøytral sannsynlighet for utbetaling': price / (p.K * Math.exp(-p.r * p.T)) };
    },
  },
  {
    id: 'two-best-worst-cash',
    chapter: 5,
    group: G_BINARY,
    name: 'Best eller worst cash-or-nothing',
    authors: 'Haug (2007), kap. 5',
    description: 'Betaler K ved forfall hvis det beste (maks) eller dårligste (min) av to aktiva ender over (call) eller under (put) X.',
    payoff: 'Call: K hvis max/min(S1, S2) > X · Put: K hvis max/min(S1, S2) < X',
    inputs: [
      callPut('call'), select('kind', 'Variant', [
        { value: 'max', label: 'Beste (maksimum av S1 og S2)' },
        { value: 'min', label: 'Dårligste (minimum av S1 og S2)' },
      ], 'max'),
      S1(100), S2(105), X(110), cash(10),
      ...market({ T: 0.5, r: 0.05, b1: 0.05, b2: 0.05, v1: 0.2, v2: 0.3, rho: 0.5 }),
    ],
    compute: (p) => {
      const price = bestWorstCashOrNothing(p);
      return { 'Pris': price, 'Risikonøytral sannsynlighet for utbetaling': price / (p.K * Math.exp(-p.r * p.T)) };
    },
  },

  // --- Valutaoversatte opsjoner -------------------------------------------------------
  {
    id: 'two-fx-domestic-strike',
    chapter: 5,
    group: G_FX,
    name: 'Utenlandsk aksje med innløsningskurs i innenlandsk valuta',
    authors: 'Reiner (1992)',
    description: 'Opsjon på en utenlandsk aksje der innløsningskurs og utbetaling er i innenlandsk valuta, så eieren bærer valutarisikoen.',
    payoff: 'max(E_T·S_T − X, 0) / max(X − E_T·S_T, 0)',
    inputs: [
      callPut('call'), num('E', 'Valutakurs E (innenlandsk per utenlandsk)', 1.5, pos),
      num('S', 'Utenlandsk aksjekurs S (utenlandsk valuta)', 100, pos),
      X(160, 'Innløsningskurs X (innenlandsk valuta)'), T(0.5), r(0.08, 'Innenlandsk rente r'),
      q(0.05, 'Utbytteavkastning q (utenlandsk aksje)'),
      v(0.2, 'Volatilitet aksje σS', 'vS'), v(0.12, 'Volatilitet valutakurs σE', 'vE'), rho(0.45, 'Korrelasjon ρ (aksje og valutakurs)'),
    ],
    compute: (p) => {
      const res = foreignEquityDomesticStrike(p);
      return { 'Pris': res.price, 'Aksjekurs i innenlandsk valuta E·S': p.E * p.S, 'Volatilitet for E·S': res.v };
    },
    example: 8.3056,
  },
  {
    id: 'two-fx-quanto',
    chapter: 5,
    group: G_FX,
    name: 'Quanto (fast valutakurs)',
    authors: 'Reiner (1992)',
    description: 'Opsjon på en utenlandsk aksje der utbetalingen regnes om til innenlandsk valuta med en fast, avtalt valutakurs Ep.',
    payoff: 'Ep·max(S_T − X, 0) / Ep·max(X − S_T, 0)',
    inputs: [
      callPut('call'), num('Ep', 'Fast valutakurs Ep (innenlandsk per utenlandsk)', 1.5, pos),
      num('S', 'Utenlandsk aksjekurs S (utenlandsk valuta)', 100, pos),
      X(105, 'Innløsningskurs X (utenlandsk valuta)'), T(0.5), r(0.08, 'Innenlandsk rente r'),
      num('rf', 'Utenlandsk rente rf', 0.05, { unit: 'rate' }), q(0.04, 'Utbytteavkastning q (utenlandsk aksje)'),
      v(0.2, 'Volatilitet aksje σS', 'vS'), v(0.1, 'Volatilitet valutakurs σE', 'vE'), rho(0.3, 'Korrelasjon ρ (aksje og valutakurs)'),
    ],
    compute: (p) => {
      const res = quanto(p);
      return { 'Pris': res.price, 'Quanto-justert cost of carry rf − q − ρσSσE': res.b };
    },
    example: 5.328,
  },
  {
    id: 'two-fx-equity-linked',
    chapter: 5,
    group: G_FX,
    name: 'Equity-linked valutaopsjon',
    authors: 'Reiner (1992)',
    description: 'Valutaopsjon der antall valutaenheter følger kursen på en utenlandsk aksje, slik at en investor kan sikre valutarisikoen på aksjeinvesteringen.',
    payoff: 'S_T·max(E_T − X, 0) / S_T·max(X − E_T, 0)',
    inputs: [
      callPut('call'), num('E', 'Valutakurs E (innenlandsk per utenlandsk)', 1.5, pos),
      num('S', 'Utenlandsk aksjekurs S (utenlandsk valuta)', 100, pos),
      X(1.52, 'Innløsningskurs X (valutakurs)'), T(0.25), r(0.08, 'Innenlandsk rente r'),
      num('rf', 'Utenlandsk rente rf', 0.05, { unit: 'rate' }), q(0.04, 'Utbytteavkastning q (utenlandsk aksje)'),
      v(0.2, 'Volatilitet aksje σS', 'vS'), v(0.12, 'Volatilitet valutakurs σE', 'vE'), rho(-0.4, 'Korrelasjon ρ (aksje og valutakurs)'),
    ],
    compute: (p) => ({ 'Pris': equityLinkedFX(p) }),
  },
  {
    id: 'two-fx-takeover',
    chapter: 5,
    group: G_FX,
    name: 'Takeover-valutaopsjon',
    authors: 'Schnabel og Wei (1994)',
    description: 'Valutaopsjon for et selskap som har lagt inn bud K på et utenlandsk selskap. Den kan bare utøves hvis oppkjøpet lykkes, det vil si hvis selskapets verdi V er under budet ved forfall.',
    payoff: 'N·max(E_T − X, 0) hvis V_T < K, ellers 0',
    inputs: [
      num('V', 'Verdi av målselskapet V (utenlandsk valuta)', 100, pos),
      num('K', 'Budpris K (utenlandsk valuta)', 105, pos),
      num('N', 'Antall valutaenheter N', 1000, pos),
      num('E', 'Valutakurs E (innenlandsk per utenlandsk)', 1.5, pos),
      X(1.55, 'Innløsningskurs X (valutakurs)'), T(1), r(0.08, 'Innenlandsk rente r'),
      num('rf', 'Utenlandsk rente rf', 0.06, { unit: 'rate' }),
      v(0.2, 'Volatilitet selskapsverdi σV', 'vV'), v(0.25, 'Volatilitet valutakurs σE', 'vE'),
      rho(0.1, 'Korrelasjon ρ (selskapsverdi og valutakurs)'),
    ],
    compute: (p) => {
      const res = takeoverFX(p);
      return { 'Pris': res.price, 'Risikonøytral sannsynlighet for at oppkjøpet lykkes': res.prob };
    },
  },
];
