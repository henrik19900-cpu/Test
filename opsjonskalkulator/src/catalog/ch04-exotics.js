// Kapittel 4: Eksotiske opsjoner på ett underliggende (unntatt barriere- og binære opsjoner).
import { gbsm } from '../models/bsm.js';
import {
  variablePurchaseOption, executiveStockOption, moneynessOption, powerContract, powerOption,
  cappedPowerOption, poweredOption, logContract, logSContract, logOption, forwardStart, ratchet,
  fadeIn, resetStrikeType1, resetStrikeType2, timeSwitch, simpleChooser, complexChooser,
  compoundOption, holderExtendible, writerExtendible,
} from '../models/exotics.js';
import {
  floatingStrikeLookback, fixedStrikeLookback, partialFloatingLookback, partialFixedLookback, extremeSpread,
} from '../models/lookback.js';
import {
  geometricAverage, turnbullWakeman, levy, curran, discreteArithmeticAverage,
} from '../models/asian.js';
import { callPut, num, int, list, select, S, X, T, r, b, v } from './common.js';

const pos = { min: 0, exclusiveMin: true };
const posNum = (key, label, d, extra = {}) => num(key, label, d, { ...pos, ...extra });
const time = (key, label, d) => num(key, label, d, pos);
const nonNegTime = (key, label, d) => num(key, label, d, { min: 0 });
const fmtLevel = (x) => (x === null ? 'finnes ikke' : x === Infinity ? '∞ (ingen øvre grense)' : x);
const fmtNum = (x) => (x === Infinity ? '∞' : x.toFixed(4).replace('.', ','));
const fmtRegions = (regions) => (regions.length === 0 ? 'aldri'
  : regions.map(([lo, hi]) => `${lo === 0 ? '(0' : `[${fmtNum(lo)}`}; ${fmtNum(hi)}${hi === Infinity ? ')' : ']'}`).join(' og '));

const G_VARIANTS = 'Varianter av standardopsjoner';
const G_POWER = 'Kontrakter og potensopsjoner';
const G_FWD = 'Forward start, cliquet og reset';
const G_ACCRUAL = 'Opptjening over tid';
const G_CHOOSER = 'Chooser og sammensatte';
const G_LOOKBACK = 'Lookback';
const G_ASIAN = 'Asiatiske';

const SA = (d) => posNum('SA', 'Gjennomsnitt så langt S_A', d);
const discreteInputs = (type, def) => [
  callPut(type), S(def.S), SA(def.S), X(def.X), T(def.T),
  nonNegTime('t1', 'Tid til første gjenstående fiksering t1 (år)', def.t1),
  int('n', 'Antall fikseringer totalt n', def.n, { min: 1, max: 10000 }),
  int('m', 'Fikseringer allerede gjort m', 0, { min: 0 }),
  r(def.r), b(def.b), v(def.v),
];

export default [
  // --- Varianter av standardopsjoner ---------------------------------------------------------
  {
    id: 'exo-vpo',
    chapter: 4,
    group: G_VARIANTS,
    name: 'Variable purchase option (VPO)',
    authors: 'Handley (2001)',
    description: 'Kjøpsopsjon der innehaveren betaler et fast beløp X for N = X/(S_T(1 − D)) aksjer, dvs. kjøper med rabatt D på kursen ved forfall. Kursgrensene L og U begrenser antallet aksjer.',
    payoff: 'max(N·S_T − X, 0), N = X/(S_T(1 − D)) begrenset til [X/(U(1 − D)), X/(L(1 − D))]',
    inputs: [
      S(100), X(100, 'Fast innløsningsbeløp X'),
      num('D', 'Rabatt D', 0.1, { min: 0, max: 1, exclusiveMax: true, unit: 'rate' }),
      posNum('L', 'Nedre kursgrense L', 80), posNum('U', 'Øvre kursgrense U', 120),
      T(1), r(0.05), b(0.05), v(0.3),
    ],
    compute: (p) => {
      const res = variablePurchaseOption(p);
      return {
        'Pris': res.price,
        'Minste antall aksjer N_min': res.Nmin,
        'Største antall aksjer N_max': res.Nmax,
        'Nåverdi av rabatten X·D/(1 − D)·e^{−rT}': res.fixed,
      };
    },
  },
  {
    id: 'exo-executive',
    chapter: 4,
    group: G_VARIANTS,
    name: 'Ansatteopsjon med fratredelsesrisiko',
    authors: 'Jennergren og Näslund (1993)',
    description: 'Opsjonen tapes hvis den ansatte slutter før forfall. Fratredelse skjer med intensitet λ per år, så verdien er e^{−λT} ganger BSM-verdien.',
    inputs: [
      callPut('call'), S(60), X(64), T(2), r(0.07), b(0.04), v(0.38),
      num('lambda', 'Fratredelsesrate λ (per år)', 0.15, { min: 0, unit: 'rate' }),
    ],
    compute: (p) => {
      const res = executiveStockOption(p);
      return {
        'Pris': res.price,
        'Uten fratredelsesrisiko (BSM)': res.vanilla,
        'Sannsynlighet for å beholde opsjonen e^{−λT}': res.keep,
      };
    },
    example: 9.1244,
  },
  {
    id: 'exo-moneyness',
    chapter: 4,
    group: G_VARIANTS,
    name: 'Moneyness-opsjon',
    authors: 'Haug (2007), kap. 4',
    description: 'Vanlig opsjon der innløsningskursen er en prosentandel av forwardprisen F. For en call er L = X/F og prisen oppgis per enhet F; for en put er L = F/X og prisen oppgis per enhet X.',
    payoff: 'e^{−rT}[N(d1) − L·N(d2)], d1 = (−ln L + σ²T/2)/(σ√T)',
    inputs: [callPut('call'), posNum('L', 'Moneyness L (call: X/F, put: F/X)', 1.2), T(0.5), r(0.05), v(0.3)],
    compute: (p) => {
      const price = moneynessOption(p);
      return { 'Pris (andel av F for call, av X for put)': price, 'Pris i prosent': 100 * price };
    },
    chart: false,
  },

  // --- Kontrakter og potensopsjoner -----------------------------------------------------------
  {
    id: 'exo-power-contract',
    chapter: 4,
    group: G_POWER,
    name: 'Potenskontrakt',
    authors: 'Shaw (1998)',
    description: 'Kontrakt som ved forfall betaler forholdet mellom kursen og X opphøyd i potensen i.',
    payoff: '(S_T/X)^i',
    inputs: [S(100), X(110), T(0.5), r(0.08), b(0.06), v(0.3), num('i', 'Potens i', 2)],
    compute: (p) => ({ 'Pris': powerContract(p) }),
  },
  {
    id: 'exo-power-option',
    chapter: 4,
    group: G_POWER,
    name: 'Standard potensopsjon',
    authors: 'Heynen og Kat (1996), Zhang (1998), Esser (2003)',
    description: 'Opsjon på kursen opphøyd i potensen i. Gir sterkere gearing enn en vanlig opsjon.',
    payoff: 'max(S_T^i − X, 0) / max(X − S_T^i, 0)',
    inputs: [callPut('call'), S(10), X(100), T(0.5), r(0.08), b(0.06), v(0.3), posNum('i', 'Potens i', 2)],
    compute: (p) => ({ 'Pris': powerOption(p) }),
  },
  {
    id: 'exo-capped-power',
    chapter: 4,
    group: G_POWER,
    name: 'Potensopsjon med tak',
    authors: 'Esser (2003)',
    description: 'Standard potensopsjon der utbetalingen er begrenset oppad av taket C.',
    payoff: 'min(max(S_T^i − X, 0), C) / min(max(X − S_T^i, 0), C)',
    inputs: [
      callPut('call'), S(10), X(100), posNum('C', 'Tak på utbetalingen C', 20),
      T(0.5), r(0.08), b(0.06), v(0.3), posNum('i', 'Potens i', 2),
    ],
    compute: (p) => ({ 'Pris': cappedPowerOption(p), 'Uten tak': powerOption(p) }),
  },
  {
    id: 'exo-powered',
    chapter: 4,
    group: G_POWER,
    name: 'Opphøyd opsjon (powered option)',
    authors: 'Esser (2003)',
    description: 'Utbetalingen til en vanlig opsjon opphøyd i et heltall i.',
    payoff: 'max(S_T − X, 0)^i / max(X − S_T, 0)^i',
    inputs: [
      callPut('call'), S(100), X(100), T(0.5), r(0.08), b(0.06), v(0.3),
      int('i', 'Potens i (heltall)', 2, { min: 1, max: 10 }),
    ],
    compute: (p) => ({ 'Pris': poweredOption(p) }),
  },
  {
    id: 'exo-log-contract',
    chapter: 4,
    group: G_POWER,
    name: 'Logkontrakt ln(S_T/X)',
    authors: 'Neuberger (1994)',
    description: 'Kontrakt som ved forfall betaler den naturlige logaritmen av S_T/X. Verdien er lineær i variansen og brukes til å handle volatilitet.',
    payoff: 'ln(S_T/X)',
    inputs: [S(100), X(100), T(0.5), r(0.08), b(0.06), v(0.3)],
    compute: (p) => ({ 'Pris': logContract(p) }),
  },
  {
    id: 'exo-log-s-contract',
    chapter: 4,
    group: G_POWER,
    name: 'Logkontrakt ln(S_T)',
    authors: 'Neuberger (1994)',
    description: 'Kontrakt som ved forfall betaler den naturlige logaritmen av kursen.',
    payoff: 'ln(S_T)',
    inputs: [S(100), T(0.5), r(0.08), b(0.06), v(0.3)],
    compute: (p) => ({ 'Pris': logSContract(p) }),
  },
  {
    id: 'exo-log-option',
    chapter: 4,
    group: G_POWER,
    name: 'Log-opsjon',
    authors: 'Wilmott (2000)',
    description: 'Opsjon på logaritmen av kursen. Callen betaler max(ln(S_T/X), 0); putten max(ln(X/S_T), 0) er tatt med for symmetri.',
    payoff: 'max(ln(S_T/X), 0) / max(ln(X/S_T), 0)',
    inputs: [callPut('call'), S(100), X(100), T(0.5), r(0.08), b(0.06), v(0.3)],
    compute: (p) => ({ 'Pris': logOption(p), 'Logkontrakt ln(S_T/X)': logContract(p) }),
  },

  // --- Forward start, cliquet og reset ----------------------------------------------------------
  {
    id: 'exo-forward-start',
    chapter: 4,
    group: G_FWD,
    name: 'Forward start-opsjon',
    authors: 'Rubinstein (1990)',
    description: 'Opsjonen starter ved tidspunktet t med innløsningskurs α·S_t og forfaller ved T, f.eks. en ansatteopsjon som tildeles senere.',
    payoff: 'max(S_T − α·S_t, 0) / max(α·S_t − S_T, 0)',
    inputs: [
      callPut('call'), S(60), posNum('alpha', 'Andel α (X = α·S_t)', 1.1),
      nonNegTime('t', 'Starttidspunkt t (år)', 0.25), T(1), r(0.08), b(0.04), v(0.3),
    ],
    compute: (p) => ({ 'Pris': forwardStart(p) }),
    example: 4.4064,
  },
  {
    id: 'exo-ratchet',
    chapter: 4,
    group: G_FWD,
    name: 'Ratchet-opsjon (cliquet)',
    authors: 'Rubinstein (1990)',
    description: 'En rekke forward start-opsjoner. Ved hvert tidspunkt låses gevinsten inn, og ny innløsningskurs settes til α ganger kursen da.',
    payoff: 'Σ max(S_{t_i} − α·S_{t_{i−1}}, 0), utbetalt ved t_i (t_0 = 0)',
    inputs: [
      callPut('call'), S(100), posNum('alpha', 'Andel α', 1),
      list('times', 'Tilbakestillingstidspunkter t₁; …; tₙ (år)', [0.25, 0.5, 0.75, 1], { minLength: 1 }),
      r(0.08), b(0.04), v(0.3),
    ],
    compute: (p) => {
      const res = ratchet(p);
      return { 'Pris': res.price, ...Object.fromEntries(res.parts.map((x, i) => [`Periode ${i + 1}`, x])) };
    },
  },
  {
    id: 'exo-reset-1',
    chapter: 4,
    group: G_FWD,
    name: 'Reset strike-opsjon, type 1 (prosentvis)',
    authors: 'Gray og Whaley (1997)',
    description: 'Er opsjonen ute av pengene ved τ, settes innløsningskursen lik kursen da. Utbetalingen er prosentvis, dvs. per krone innløsningskurs.',
    payoff: 'max((S_T − X̃)/X̃, 0) / max((X̃ − S_T)/X̃, 0), X̃ = S_τ ved tilbakestilling, ellers X',
    inputs: [
      callPut('call'), S(100), X(100), time('tau', 'Tilbakestillingstidspunkt τ (år)', 0.25),
      T(1), r(0.1), b(0.1), v(0.3),
    ],
    compute: (p) => ({ 'Pris': resetStrikeType1(p), 'Vanilla per krone innløsningskurs': gbsm(p) / p.X }),
  },
  {
    id: 'exo-reset-2',
    chapter: 4,
    group: G_FWD,
    name: 'Reset strike-opsjon, type 2',
    authors: 'Gray og Whaley (1999)',
    description: 'Er opsjonen ute av pengene ved τ, settes innløsningskursen lik kursen da. Ellers en vanlig europeisk opsjon.',
    payoff: 'max(S_T − X̃, 0) / max(X̃ − S_T, 0), X̃ = S_τ ved tilbakestilling, ellers X',
    inputs: [
      callPut('call'), S(100), X(100), time('tau', 'Tilbakestillingstidspunkt τ (år)', 0.25),
      T(1), r(0.1), b(0.1), v(0.3),
    ],
    compute: (p) => ({ 'Pris': resetStrikeType2(p), 'Vanilla (BSM)': gbsm(p) }),
  },

  // --- Opptjening over tid --------------------------------------------------------------------------
  {
    id: 'exo-fade-in',
    chapter: 4,
    group: G_ACCRUAL,
    name: 'Fade-in-opsjon',
    authors: 'Brockhaus m.fl. (1999)',
    description: 'Vanilla-utbetalingen ganges med andelen av n jevnt fordelte fikseringer (t_i = iT/n) der kursen lå mellom L og H.',
    payoff: '(1/n)·Σ 1{L < S_{t_i} < H} · max(S_T − X, 0)',
    inputs: [
      callPut('call'), S(100), X(100), num('L', 'Nedre grense L', 90, { min: 0 }), posNum('H', 'Øvre grense H', 110),
      T(0.5), int('n', 'Antall fikseringer n', 26, { min: 1, max: 5000 }), r(0.05), b(0.05), v(0.2),
    ],
    compute: (p) => {
      const res = fadeIn(p);
      return {
        'Pris': res.price,
        'Vanilla (BSM)': gbsm(p),
        'Forventet andel fikseringer i intervallet': res.insideShare,
      };
    },
  },
  {
    id: 'exo-time-switch',
    chapter: 4,
    group: G_ACCRUAL,
    name: 'Time-switch-opsjon',
    authors: 'Pechtl (1995)',
    description: 'Innehaveren opptjener A·Δt for hver tidsenhet Δt = 1/k der kursen er over X (call) eller under X (put). Beløpet utbetales ved forfall.',
    payoff: 'A·Δt·(m + antall fikseringer iΔt ≤ T med S > X / S < X)',
    inputs: [
      callPut('call'), S(100), X(110), posNum('A', 'Beløp per år i pengene A', 5), T(1),
      int('k', 'Tidsenheter per år k (Δt = 1/k)', 365, { min: 1, max: 100000 }),
      int('m', 'Tidsenheter allerede opptjent m', 0, { min: 0 }),
      r(0.06), b(0.06), v(0.26),
    ],
    compute: (p) => {
      const res = timeSwitch({ ...p, dt: 1 / p.k });
      return {
        'Pris': res.price,
        'Forventet antall tidsenheter i pengene': res.expectedUnits,
        'Antall fikseringer n': res.n,
      };
    },
    example: 1.375,
  },

  // --- Chooser og sammensatte -------------------------------------------------------------------------
  {
    id: 'exo-simple-chooser',
    chapter: 4,
    group: G_CHOOSER,
    name: 'Enkel chooser-opsjon',
    authors: 'Rubinstein (1991)',
    description: 'Ved tidspunktet t velger innehaveren om opsjonen skal være en call eller en put med innløsningskurs X og forfall T.',
    payoff: 'max(c(S_t, X, T − t), p(S_t, X, T − t)) ved t',
    inputs: [S(50), X(50), time('t', 'Valgtidspunkt t (år)', 0.25), T(0.5), r(0.08), b(0.08), v(0.25)],
    compute: (p) => {
      const call = gbsm({ ...p, type: 'call' });
      const putPart = Math.exp((p.b - p.r) * (p.T - p.t))
        * gbsm({ type: 'put', S: p.S, X: p.X * Math.exp(-p.b * (p.T - p.t)), T: p.t, r: p.r, b: p.b, v: p.v });
      return { 'Pris': simpleChooser(p), 'Call-del c(S, X, T)': call, 'Put-del e^{(b−r)(T−t)}·p(S, X·e^{−b(T−t)}, t)': putPart };
    },
    example: 6.1071,
  },
  {
    id: 'exo-complex-chooser',
    chapter: 4,
    group: G_CHOOSER,
    name: 'Kompleks chooser-opsjon',
    authors: 'Rubinstein (1991)',
    description: 'Ved tidspunktet t velger innehaveren mellom en call (Xc, Tc) og en put (Xp, Tp) med ulike innløsningskurser og forfall.',
    payoff: 'max(c(S_t, Xc, Tc − t), p(S_t, Xp, Tp − t)) ved t',
    inputs: [
      S(50), posNum('Xc', 'Innløsningskurs call Xc', 55), posNum('Xp', 'Innløsningskurs put Xp', 48),
      time('t', 'Valgtidspunkt t (år)', 0.25), time('Tc', 'Forfall call Tc (år)', 0.5), time('Tp', 'Forfall put Tp (år)', 0.5833),
      r(0.1), b(0.05), v(0.35),
    ],
    compute: (p) => {
      const res = complexChooser(p);
      return { 'Pris': res.price, 'Kritisk spotpris I': res.I };
    },
    example: 6.0508,
  },
  {
    id: 'exo-compound',
    chapter: 4,
    group: G_CHOOSER,
    name: 'Opsjon på opsjon',
    authors: 'Geske (1977), Rubinstein (1991)',
    description: 'Opsjon med forfall t1 og innløsningskurs X2 på en underliggende call eller put med innløsningskurs X1 og forfall T2.',
    payoff: 'max(V(S_{t1}) − X2, 0) / max(X2 − V(S_{t1}), 0), V = verdien av den underliggende opsjonen',
    inputs: [
      select('kind', 'Type', [
        { value: 'call-call', label: 'Call på call' },
        { value: 'put-call', label: 'Put på call' },
        { value: 'call-put', label: 'Call på put' },
        { value: 'put-put', label: 'Put på put' },
      ], 'put-call'),
      S(500),
      posNum('X1', 'Innløsningskurs underliggende opsjon X1', 520),
      posNum('X2', 'Innløsningskurs opsjonen på opsjonen X2', 50),
      time('t1', 'Forfall opsjonen på opsjonen t1 (år)', 0.25),
      time('T2', 'Forfall underliggende opsjon T2 (år)', 0.5),
      r(0.08), b(0.05), v(0.35),
    ],
    compute: (p) => {
      const res = compoundOption(p);
      return {
        'Pris': res.price,
        'Kritisk spotpris I ved t1': fmtLevel(res.I),
        'Underliggende opsjon i dag': res.underlying,
      };
    },
    // Boka trykker 21,1965 for put på call; formelen gir 21,19635 (bekreftet med numerisk integrasjon).
    example: 21.1965,
    exampleTol: 2e-4,
  },
  {
    id: 'exo-holder-extendible',
    chapter: 4,
    group: G_CHOOSER,
    name: 'Forlengbar opsjon (innehaver)',
    authors: 'Longstaff (1990)',
    description: 'Ved t1 kan innehaveren innløse, la opsjonen falle bort eller forlenge den til T2 med ny innløsningskurs X2 mot et gebyr A.',
    payoff: 'ved t1: max(utbetaling med X1, opsjon(X2, T2 − t1) − A, 0)',
    inputs: [
      callPut('call'), S(100), posNum('X1', 'Innløsningskurs X1', 100), posNum('X2', 'Ny innløsningskurs X2', 105),
      time('t1', 'Første forfall t1 (år)', 0.5), time('T2', 'Forlenget forfall T2 (år)', 0.75),
      num('A', 'Gebyr for forlengelse A', 1, { min: 0 }), r(0.08), b(0.08), v(0.25),
    ],
    compute: (p) => {
      const res = holderExtendible(p);
      return {
        'Pris': res.price,
        'Vanilla med forfall t1': res.vanilla,
        'Nedre kritiske kurs I1': fmtLevel(res.I1),
        'Øvre kritiske kurs I2': fmtLevel(res.I2),
        'Forlengelse lønner seg når S_{t1} ligger i': fmtRegions(res.regions),
      };
    },
  },
  {
    id: 'exo-writer-extendible',
    chapter: 4,
    group: G_CHOOSER,
    name: 'Forlengbar opsjon (utsteder)',
    authors: 'Longstaff (1990)',
    description: 'Er opsjonen ute av pengene ved t1, forlenges den automatisk til T2 med ny innløsningskurs X2.',
    payoff: 'max(S_{t1} − X1, 0) hvis i pengene ved t1, ellers max(S_{T2} − X2, 0) (call)',
    inputs: [
      callPut('call'), S(80), posNum('X1', 'Innløsningskurs X1', 90), posNum('X2', 'Ny innløsningskurs X2', 82),
      time('t1', 'Første forfall t1 (år)', 0.5), time('T2', 'Forlenget forfall T2 (år)', 0.75),
      r(0.1), b(0.1), v(0.3),
    ],
    compute: (p) => {
      const res = writerExtendible(p);
      return { 'Pris': res.price, 'Vanilla med forfall t1': res.vanilla };
    },
    example: 6.8238,
  },

  // --- Lookback ------------------------------------------------------------------------------------
  {
    id: 'exo-lookback-floating',
    chapter: 4,
    group: G_LOOKBACK,
    name: 'Lookback med flytende innløsningskurs',
    authors: 'Goldman, Sosin og Gatto (1979)',
    description: 'Callen betaler S_T minus laveste kurs i levetiden, putten høyeste kurs minus S_T. Kontinuerlig overvåking.',
    payoff: 'S_T − S_min / S_max − S_T',
    inputs: [
      callPut('call'), S(120), posNum('Smin', 'Observert minimum S_min (call)', 100),
      posNum('Smax', 'Observert maksimum S_max (put)', 120), T(0.5), r(0.1), b(0.04), v(0.3),
    ],
    compute: (p) => ({ 'Pris': floatingStrikeLookback(p) }),
    example: 25.3533,
  },
  {
    id: 'exo-lookback-fixed',
    chapter: 4,
    group: G_LOOKBACK,
    name: 'Lookback med fast innløsningskurs',
    authors: 'Conze og Viswanathan (1991)',
    description: 'Callen betaler høyeste kurs i levetiden minus X, putten X minus laveste kurs. Kontinuerlig overvåking.',
    payoff: 'max(S_max − X, 0) / max(X − S_min, 0)',
    inputs: [
      callPut('call'), S(100), X(105), posNum('Smax', 'Observert maksimum S_max (call)', 100),
      posNum('Smin', 'Observert minimum S_min (put)', 100), T(0.5), r(0.1), b(0.1), v(0.3),
    ],
    compute: (p) => ({ 'Pris': fixedStrikeLookback(p) }),
  },
  {
    id: 'exo-lookback-partial-floating',
    chapter: 4,
    group: G_LOOKBACK,
    name: 'Delvis lookback, flytende innløsningskurs',
    authors: 'Heynen og Kat (1994)',
    description: 'Minimum (call) eller maksimum (put) observeres bare fram til t1, mens opsjonen forfaller ved T. Med λ ≠ 1 blir den en fraksjonell lookback.',
    payoff: 'max(S_T − λ·min_{[0,t1]} S, 0) / max(λ·max_{[0,t1]} S − S_T, 0)',
    inputs: [
      callPut('call'), S(90), posNum('Smin', 'Observert minimum S_min (call)', 90),
      posNum('Smax', 'Observert maksimum S_max (put)', 90), posNum('lambda', 'Multiplikator λ', 1),
      time('t1', 'Slutt på lookback-perioden t1 (år)', 0.5), T(1), r(0.06), b(0.06), v(0.2),
    ],
    compute: (p) => ({ 'Pris': partialFloatingLookback(p) }),
  },
  {
    id: 'exo-lookback-partial-fixed',
    chapter: 4,
    group: G_LOOKBACK,
    name: 'Delvis lookback, fast innløsningskurs',
    authors: 'Heynen og Kat (1994)',
    description: 'Maksimum (call) eller minimum (put) observeres fra t1 til forfall T. Billigere enn en vanlig lookback med fast innløsningskurs.',
    payoff: 'max(max_{[t1,T]} S − X, 0) / max(X − min_{[t1,T]} S, 0)',
    inputs: [
      callPut('call'), S(100), X(90), time('t1', 'Start på lookback-perioden t1 (år)', 0.5),
      T(1), r(0.06), b(0.06), v(0.2),
    ],
    compute: (p) => ({ 'Pris': partialFixedLookback(p) }),
  },
  {
    id: 'exo-extreme-spread',
    chapter: 4,
    group: G_LOOKBACK,
    name: 'Extreme spread-opsjon',
    authors: 'Bermin (1996)',
    description: 'Levetiden deles ved t1. Opsjonen betaler differansen mellom ekstremverdiene i de to periodene; M er maksimum og m minimum, indeks 1 og 2 angir periode.',
    payoff: 'max(M₂ − M₁, 0), max(m₁ − m₂, 0), max(m₂ − m₁, 0) eller max(M₁ − M₂, 0)',
    inputs: [
      select('kind', 'Type', [
        { value: 'call', label: 'Extreme spread call: max(M₂ − M₁, 0)' },
        { value: 'put', label: 'Extreme spread put: max(m₁ − m₂, 0)' },
        { value: 'reverse-call', label: 'Omvendt extreme spread call: max(m₂ − m₁, 0)' },
        { value: 'reverse-put', label: 'Omvendt extreme spread put: max(M₁ − M₂, 0)' },
      ], 'call'),
      S(100), posNum('Smax', 'Observert maksimum i første periode', 100),
      posNum('Smin', 'Observert minimum i første periode', 100),
      time('t1', 'Slutt på første periode t1 (år)', 0.5), T(1), r(0.1), b(0.1), v(0.3),
    ],
    compute: (p) => ({ 'Pris': extremeSpread(p) }),
  },

  // --- Asiatiske ----------------------------------------------------------------------------------
  {
    id: 'exo-asian-geometric',
    chapter: 4,
    group: G_ASIAN,
    name: 'Geometrisk gjennomsnitt',
    authors: 'Kemna og Vorst (1990)',
    description: 'Opsjon på det kontinuerlige geometriske gjennomsnittet over [0, T]. Gjennomsnittet er lognormalt, så formelen er eksakt.',
    payoff: 'max(G − X, 0) / max(X − G, 0), G = exp((1/T)∫ ln S dt)',
    inputs: [callPut('put'), S(80), X(85), T(0.25), r(0.05), b(0.08), v(0.2)],
    compute: (p) => ({
      'Pris': geometricAverage(p),
      'Justert carry b_A = (b − σ²/6)/2': 0.5 * (p.b - p.v * p.v / 6),
      'Justert volatilitet σ_A = σ/√3': p.v / Math.sqrt(3),
    }),
    example: 4.6922,
  },
  {
    id: 'exo-asian-tw',
    chapter: 4,
    group: G_ASIAN,
    name: 'Aritmetisk gjennomsnitt – Turnbull og Wakeman',
    authors: 'Turnbull og Wakeman (1991)',
    description: 'Tilnærming for kontinuerlig aritmetisk gjennomsnitt med samme to første momenter som et lognormalt gjennomsnitt. T2 er hele periodens lengde: T2 < T betyr at perioden starter om T − T2, T2 > T at den har pågått i T2 − T med gjennomsnitt S_A.',
    payoff: 'max(A − X, 0) / max(X − A, 0), A = gjennomsnitt over de siste T2 årene før forfall',
    inputs: [
      callPut('put'), S(90), SA(88), X(95), T(0.25), time('T2', 'Lengde på gjennomsnittsperioden T2 (år)', 0.5),
      r(0.07), b(0.02), v(0.25),
    ],
    compute: (p) => {
      const res = turnbullWakeman(p);
      return { 'Pris': res.price, 'Justert carry b_A': res.bA, 'Justert volatilitet σ_A': res.vA };
    },
  },
  {
    id: 'exo-asian-levy',
    chapter: 4,
    group: G_ASIAN,
    name: 'Aritmetisk gjennomsnitt – Levy',
    authors: 'Levy (1992)',
    description: 'Lognormal tilnærming for kontinuerlig aritmetisk gjennomsnitt. Perioden har lengde T2 og slutter ved T; med T2 > T har den pågått i T2 − T år med gjennomsnitt S_A, med T2 < T starter den om T − T2.',
    payoff: 'max(A − X, 0) / max(X − A, 0)',
    inputs: [
      callPut('call'), S(6.8), SA(6.8), X(6.9), T(0.5), time('T2', 'Lengde på gjennomsnittsperioden T2 (år)', 0.5),
      r(0.07), b(-0.02), v(0.14),
    ],
    compute: (p) => {
      const res = levy(p);
      return {
        'Pris': res.price,
        'S_E (nåverdi av gjenstående del av gjennomsnittet)': res.SE,
        'Justert innløsningskurs X*': res.Xstar,
      };
    },
    example: 0.0944,
  },
  {
    id: 'exo-asian-curran',
    chapter: 4,
    group: G_ASIAN,
    name: 'Diskret aritmetisk gjennomsnitt – Curran',
    authors: 'Curran (1992)',
    description: 'Tilnærming som betinger på det geometriske gjennomsnittet. De n − m gjenstående fikseringene ligger likt fordelt fra t1 til T; m fikseringer med gjennomsnitt S_A er allerede gjort.',
    payoff: 'max(A − X, 0) / max(X − A, 0), A = (1/n)·Σ S_{t_i}',
    inputs: discreteInputs('call', { S: 100, X: 100, T: 1, t1: 0.1, n: 10, r: 0.05, b: 0.05, v: 0.3 }),
    compute: (p) => {
      const res = curran(p);
      return { 'Pris': res.price, 'Forventet gjennomsnitt E[A]': res.mean };
    },
  },
  {
    id: 'exo-asian-discrete',
    chapter: 4,
    group: G_ASIAN,
    name: 'Diskret aritmetisk gjennomsnitt – momenttilpasning',
    authors: 'Haug, Haug og Margrabe (2003)',
    description: 'Eksakte første og andre momenter for det diskrete gjennomsnittet, som så tilnærmes lognormalt. Fikseringene ligger som i Currans formel.',
    payoff: 'max(A − X, 0) / max(X − A, 0), A = (1/n)·Σ S_{t_i}',
    inputs: discreteInputs('call', { S: 100, X: 100, T: 1, t1: 0.1, n: 10, r: 0.05, b: 0.05, v: 0.3 }),
    compute: (p) => {
      const res = discreteArithmeticAverage(p);
      return { 'Pris': res.price, 'Forventet gjennomsnitt E[A]': res.EA, 'Volatilitet for gjennomsnittet σ_A': res.vA };
    },
  },
];
