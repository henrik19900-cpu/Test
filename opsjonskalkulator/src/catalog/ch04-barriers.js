// Kapittel 4: barriereopsjoner (4.17) og binære opsjoner (4.19) i Haug (2007).
import { gbsm } from '../models/bsm.js';
import {
  standardBarrier, barrierHitProbability, discreteBarrier, bgkAdjustedBarrier, barrierKind,
  doubleBarrier, partialTimeBarrier, lookBarrier, partialFixedLookback, softBarrier,
} from '../models/barriers.js';
import {
  gapOption, cashOrNothing, assetOrNothing, supershare, binaryBarrier, BINARY_BARRIER_TYPES,
  doubleBarrierBinary,
} from '../models/binary.js';
import { callPut, num, select, S, X, T, r, b, v } from './common.js';

const pos = { min: 0, exclusiveMin: true };
const BAR = 'Barriereopsjoner';
const BIN = 'Binære opsjoner';

const barrierType = select('barrier', 'Barrieretype', [
  { value: 'do', label: 'Ned-og-ut (down-and-out)' },
  { value: 'uo', label: 'Opp-og-ut (up-and-out)' },
  { value: 'di', label: 'Ned-og-inn (down-and-in)' },
  { value: 'ui', label: 'Opp-og-inn (up-and-in)' },
], 'do');
const H = (d, label = 'Barriere H') => num('H', label, d, pos);
const rebate = (d) => num('K', 'Rabatt K', d, {
  min: 0,
  help: 'Knock-out: betales ved treff. Knock-in: betales ved forfall hvis barrieren aldri treffes.',
});
const t1 = (d, help) => num('t1', 'Tidspunkt t1 (år)', d, { ...pos, help });
const T2 = (d) => num('T2', 'Tid til forfall T2 (år)', d, pos);

export default [
  {
    id: 'bar-standard',
    chapter: 4,
    group: BAR,
    name: 'Standard barriereopsjon',
    authors: 'Merton (1973), Reiner og Rubinstein (1991)',
    description: 'Europeisk opsjon som slås inn eller ut når spot treffer barrieren H, med kontinuerlig overvåking. Dekker alle åtte typene, med rabatt K.',
    payoff: 'Ut: max(S_T − X, 0) hvis H aldri treffes, ellers K ved treff. Inn: max(S_T − X, 0) hvis H treffes, ellers K ved forfall.',
    inputs: [callPut('call'), barrierType, S(100), X(90), H(95), rebate(3), T(0.5), r(0.08), b(0.04), v(0.25)],
    compute: (p) => ({
      'Pris': standardBarrier(p),
      'Vanilla (uten barriere)': gbsm(p),
      'P(barrieren treffes før T)': barrierHitProbability(p),
    }),
    example: 9.0246,
  },
  {
    id: 'bar-discrete',
    chapter: 4,
    group: BAR,
    name: 'Diskret overvåket barriereopsjon',
    authors: 'Broadie, Glasserman og Kou (1997)',
    description: 'Barrieren sjekkes bare på faste tidspunkter. Formelen for kontinuerlig overvåking brukes med barrieren flyttet bort fra spot: H·e^{±0,5826·σ·√Δt}.',
    payoff: 'Som standard barriereopsjon, men treff registreres bare hver Δt = 1/m år.',
    inputs: [
      callPut('call'), barrierType, S(100), X(100), H(95), rebate(0), T(0.5), r(0.08), b(0.04), v(0.25),
      num('m', 'Observasjoner per år m', 52, { ...pos, help: '252 = daglig, 52 = ukentlig, 12 = månedlig' }),
    ],
    compute: (p) => {
      const dt = 1 / p.m;
      const { down } = barrierKind(p.barrier);
      return {
        'Pris (diskret overvåking)': discreteBarrier({ ...p, dt }),
        'Justert barriere H′': bgkAdjustedBarrier({ H: p.H, v: p.v, dt, down }),
        'Pris ved kontinuerlig overvåking': standardBarrier(p),
      };
    },
  },
  {
    id: 'bar-double',
    chapter: 4,
    group: BAR,
    name: 'Dobbel barriereopsjon',
    authors: 'Ikeda og Kunitomo (1992)',
    description: 'Opsjon med nedre og øvre barriere: knock-out dør og knock-in blir levende hvis spot treffer en av dem. Barrierene kan krummes eksponentielt som L·e^{δ2·t} og U·e^{δ1·t}.',
    payoff: 'Knock-out: max(S_T − X, 0) hvis spot holder seg mellom barrierene hele tiden. Knock-in = vanilla − knock-out.',
    inputs: [
      callPut('call'),
      select('kind', 'Inn eller ut', [
        { value: 'out', label: 'Knock-out (ut)' },
        { value: 'in', label: 'Knock-in (inn)' },
      ], 'out'),
      S(100), X(100), num('L', 'Nedre barriere L', 80, pos), num('U', 'Øvre barriere U', 120, pos),
      T(0.25), r(0.1), b(0.1), v(0.25),
      num('delta1', 'Krumning øvre barriere δ1', 0, { unit: 'rate' }),
      num('delta2', 'Krumning nedre barriere δ2', 0, { unit: 'rate' }),
    ],
    compute: (p) => ({ 'Pris': doubleBarrier(p), 'Vanilla (uten barrierer)': gbsm(p) }),
    example: 2.6387,
  },
  {
    id: 'bar-partial-time',
    chapter: 4,
    group: BAR,
    name: 'Partial-time barriereopsjon',
    authors: 'Heynen og Kat (1994)',
    description: 'Barrieren er bare aktiv i deler av levetiden: type A i [0, t1], type B i [t1, T2]. B1 slås ut ved enhver berøring; B2 ned-og-ut slås ut så snart spot er under H (opp-og-ut over H).',
    payoff: 'Ut: vanilla-utbetaling ved T2 hvis barrieren ikke er truffet i overvåkingsperioden. Inn = vanilla − ut.',
    inputs: [
      callPut('call'),
      select('kind', 'Barrieretype', [
        { value: 'A-do', label: 'A: ned-og-ut i [0, t1]' },
        { value: 'A-uo', label: 'A: opp-og-ut i [0, t1]' },
        { value: 'A-di', label: 'A: ned-og-inn i [0, t1]' },
        { value: 'A-ui', label: 'A: opp-og-inn i [0, t1]' },
        { value: 'B1-o', label: 'B1: ut ved berøring i [t1, T2]' },
        { value: 'B1-i', label: 'B1: inn ved berøring i [t1, T2]' },
        { value: 'B2-do', label: 'B2: ned-og-ut i [t1, T2]' },
        { value: 'B2-uo', label: 'B2: opp-og-ut i [t1, T2]' },
        { value: 'B2-di', label: 'B2: ned-og-inn i [t1, T2]' },
        { value: 'B2-ui', label: 'B2: opp-og-inn i [t1, T2]' },
      ], 'A-do'),
      S(100), X(100), H(90), t1(0.5, 'Type A: barrieren overvåkes fra 0 til t1. Type B: fra t1 til T2.'),
      T2(1), r(0.1), b(0.1), v(0.25),
    ],
    compute: (p) => ({ 'Pris': partialTimeBarrier(p), 'Vanilla (uten barriere)': gbsm({ ...p, T: p.T2 }) }),
  },
  {
    id: 'bar-look-barrier',
    chapter: 4,
    group: BAR,
    name: 'Look-barrier-opsjon',
    authors: 'Bermin (1996)',
    description: 'Barrieren overvåkes fra 0 til t1. Overlever opsjonen, blir den en fast-strike lookback på maksimum (call) eller minimum (put) fra t1 til T2.',
    payoff: 'Opp-og-ut call: max(max_{t1≤u≤T2} S_u − X, 0) hvis S < H i hele [0, t1]. Ned-og-ut put: max(X − min_{t1≤u≤T2} S_u, 0) hvis S > H i [0, t1].',
    inputs: [
      select('kind', 'Type', [
        { value: 'cuo', label: 'Opp-og-ut call' },
        { value: 'cui', label: 'Opp-og-inn call' },
        { value: 'pdo', label: 'Ned-og-ut put' },
        { value: 'pdi', label: 'Ned-og-inn put' },
      ], 'cuo'),
      S(100), X(100), H(130), t1(0.5, 'Barrieren overvåkes fra 0 til t1, lookback-perioden er fra t1 til T2.'),
      T2(1), r(0.1), b(0.1), v(0.15),
    ],
    compute: (p) => {
      const type = p.kind[0] === 'c' ? 'call' : 'put';
      const lookback = p.t1 < p.T2 ? partialFixedLookback({ ...p, type }) : gbsm({ ...p, type, T: p.T2 });
      return { 'Pris': lookBarrier(p), 'Partiell fast-strike lookback (uten barriere)': lookback };
    },
  },
  {
    id: 'bar-soft',
    chapter: 4,
    group: BAR,
    name: 'Soft-barrier-opsjon',
    authors: 'Hart og Ross (1994)',
    description: 'Barrieren er et område fra L til U, og opsjonen slås gradvis inn eller ut etter hvor langt spot har gått inn i området. Med L = U blir den en vanlig barriereopsjon.',
    payoff: 'Ned-og-inn call: max(S_T − X, 0) · min(max((U − min S)/(U − L), 0), 1). Opp-og-inn put tilsvarende med (max S − L)/(U − L).',
    inputs: [
      select('kind', 'Type', [
        { value: 'cdo', label: 'Ned-og-ut call' },
        { value: 'cdi', label: 'Ned-og-inn call' },
        { value: 'puo', label: 'Opp-og-ut put' },
        { value: 'pui', label: 'Opp-og-inn put' },
      ], 'cdo'),
      S(100), X(100), num('U', 'Øvre grense U', 95, pos), num('L', 'Nedre grense L', 90, pos),
      T(0.5), r(0.1), b(0.05), v(0.2),
    ],
    compute: (p) => {
      const call = p.kind[0] === 'c';
      const type = call ? 'call' : 'put';
      const barrier = `${call ? 'd' : 'u'}${p.kind[2] === 'i' ? 'i' : 'o'}`;
      const hard = (Hh) => standardBarrier({ ...p, type, barrier, H: Hh, K: 0 });
      return {
        'Pris': softBarrier(p),
        'Vanilla (uten barriere)': gbsm({ ...p, type }),
        'Hard barriere ved U': hard(p.U),
        'Hard barriere ved L': hard(p.L),
      };
    },
  },
  {
    id: 'bin-gap',
    chapter: 4,
    group: BIN,
    name: 'Gap-opsjon',
    authors: 'Reiner og Rubinstein (1991)',
    description: 'Utløsningskursen X1 avgjør om opsjonen betaler, men betalingen regnes fra X2. Prisen kan bli negativ.',
    payoff: 'Call: S_T − X2 hvis S_T > X1. Put: X2 − S_T hvis S_T < X1.',
    inputs: [
      callPut('call'), S(50), num('X1', 'Utløsningskurs X1', 50, pos), num('X2', 'Betalingskurs X2', 57, { min: 0 }),
      T(0.5), r(0.09), b(0.09), v(0.2),
    ],
    compute: (p) => ({ 'Pris': gapOption(p) }),
    example: -0.0053,
  },
  {
    id: 'bin-cash-or-nothing',
    chapter: 4,
    group: BIN,
    name: 'Cash-or-nothing',
    authors: 'Reiner og Rubinstein (1991)',
    description: 'Betaler et fast kontantbeløp K ved forfall hvis opsjonen ender i pengene, ellers ingenting.',
    payoff: 'Call: K hvis S_T > X. Put: K hvis S_T < X.',
    inputs: [callPut('put'), S(100), X(80), num('K', 'Kontantbeløp K', 10, { min: 0 }), T(0.75), r(0.06), b(0), v(0.35)],
    compute: (p) => ({
      'Pris': cashOrNothing(p),
      'P(i pengene ved forfall)': cashOrNothing({ ...p, K: 1, r: 0 }),
    }),
    example: 2.671,
  },
  {
    id: 'bin-asset-or-nothing',
    chapter: 4,
    group: BIN,
    name: 'Asset-or-nothing',
    authors: 'Cox og Rubinstein (1985)',
    description: 'Betaler verdien av underliggende ved forfall hvis opsjonen ender i pengene, ellers ingenting.',
    payoff: 'Call: S_T hvis S_T > X. Put: S_T hvis S_T < X.',
    inputs: [callPut('put'), S(70), X(65), T(0.5), r(0.07), b(0.02), v(0.27)],
    compute: (p) => ({ 'Pris': assetOrNothing(p) }),
    example: 20.2069,
  },
  {
    id: 'bin-supershare',
    chapter: 4,
    group: BIN,
    name: 'Supershare',
    authors: 'Hakansson (1976)',
    description: 'Betaler S_T/XL hvis underliggende ender mellom nedre grense XL og øvre grense XH, ellers ingenting.',
    payoff: 'S_T / XL hvis XL ≤ S_T < XH.',
    inputs: [
      S(100), num('XL', 'Nedre grense XL', 90, pos), num('XH', 'Øvre grense XH', 110, pos),
      T(0.25), r(0.1), b(0), v(0.2),
    ],
    compute: (p) => ({ 'Pris': supershare(p) }),
    example: 0.7389,
  },
  {
    id: 'bin-barrier',
    chapter: 4,
    group: BIN,
    name: 'Binær barriereopsjon (28 typer)',
    authors: 'Reiner og Rubinstein (1991)',
    description: 'Kontant- eller aktivabetaling som utløses eller slås ut av barrieren H, med betaling ved treff eller ved forfall. Typenumrene følger bokas tabell; odde numre har ned-barriere, like numre opp-barriere.',
    payoff: 'Type 1–4 betaler ved treff (type 3–4 betaler aktiva, verdi H), type 5–12 ved forfall uten krav til X, type 13–28 som cash-/asset-or-nothing med innløsningskurs X.',
    inputs: [
      select('kind', 'Type', BINARY_BARRIER_TYPES.map((t) => ({ value: String(t.kind), label: `${t.kind}. ${t.label}` })), '1'),
      S(105, 'Spotpris S'), X(102, 'Innløsningskurs X (type 13–28)'), H(100), num('K', 'Kontantbeløp K', 15, { min: 0 }),
      T(0.5), r(0.1), b(0.1), v(0.2),
    ],
    compute: (p) => ({ 'Pris': binaryBarrier({ ...p, kind: Number(p.kind) }) }),
    example: 9.7264,
  },
  {
    id: 'bin-double-barrier',
    chapter: 4,
    group: BIN,
    name: 'Dobbel-barriere binær opsjon',
    authors: 'Hui (1996)',
    description: 'Kontantbeløp K som avhenger av om spot treffer nedre barriere L eller øvre barriere U før forfall. Asymmetriske varianter betaler bare hvis en bestemt barriere treffes først.',
    payoff: 'Knock-out: K ved forfall hvis L < S < U hele tiden. Knock-in: K ved forfall hvis en barriere treffes. One-touch: K ved første treff.',
    inputs: [
      select('kind', 'Type', [
        { value: 'ko', label: 'Knock-out: K ved forfall hvis ingen barriere treffes' },
        { value: 'ki', label: 'Knock-in: K ved forfall hvis en barriere treffes' },
        { value: 'touch', label: 'One-touch: K ved første treff av L eller U' },
        { value: 'upper-hit', label: 'Asymmetrisk: K ved treff hvis U treffes før L' },
        { value: 'lower-hit', label: 'Asymmetrisk: K ved treff hvis L treffes før U' },
        { value: 'upper-exp', label: 'Asymmetrisk: K ved forfall hvis U treffes før L' },
        { value: 'lower-exp', label: 'Asymmetrisk: K ved forfall hvis L treffes før U' },
      ], 'ko'),
      S(100), num('L', 'Nedre barriere L', 80, pos), num('U', 'Øvre barriere U', 120, pos),
      num('K', 'Kontantbeløp K', 10, { min: 0 }), T(0.25), r(0.05), b(0.03), v(0.2),
    ],
    compute: (p) => ({ 'Pris': doubleBarrierBinary(p) }),
    example: 8.9307,
  },
];
