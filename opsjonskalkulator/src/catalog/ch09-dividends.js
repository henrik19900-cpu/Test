import {
  dividendSchedule, escrowedDividend, simpleVolAdjustment, haugHaugVol, bgsVol, bosVandermark,
  hhlEuropean, hhlAmericanCall, rollGeskeWhaley, blackPseudoAmerican, dividendTree,
} from '../models/dividends.js';
import { callPut, num, int, list, select, S, X, T, r, v } from './common.js';

const divInputs = (times = [0.5], amounts = [7]) => [
  list('tD', 'Utbyttetidspunkter (år)', times, { minLength: 1, help: 'Tid til hver utbyttedato i år, skilt med semikolon. Utbytter etter forfall ignoreres.' }),
  list('D', 'Utbyttebeløp', amounts, { minLength: 1, help: 'Kontant utbytte per dato, i samme rekkefølge som tidspunktene.' }),
];

const base = (type = 'call') => [callPut(type), S(100), X(100), T(1), r(0.06), v(0.3)];
const schedule = (p) => dividendSchedule({ tD: p.tD, D: p.D, T: p.T });

const adjusted = (fn) => (p) => {
  const res = fn({ ...p, divs: schedule(p) });
  const out = { 'Pris': res.price, 'Justert spot S − PV(D)': res.Sadj, 'Nåverdi av utbyttene': res.pv };
  if (res.vAdj !== undefined) out['Justert volatilitet'] = res.vAdj;
  return out;
};

export default [
  {
    id: 'div-escrowed',
    chapter: 9,
    group: 'Europeiske opsjoner',
    name: 'Escrowed dividend-modellen',
    authors: 'Haug (2007), kap. 9',
    description: 'Den vanligste tilnærmingen: spotprisen erstattes av S minus nåverdien av utbyttene før forfall, og prisen regnes med Black-Scholes. Undervurderer typisk call og put fordi volatiliteten ikke justeres.',
    inputs: [...base('call'), ...divInputs()],
    compute: adjusted(escrowedDividend),
  },
  {
    id: 'div-vol-simple',
    chapter: 9,
    group: 'Volatilitetsjusteringer',
    name: 'Enkel volatilitetsjustering',
    authors: 'Haug (2007), kap. 9',
    description: 'Escrowed-modellen med volatiliteten skalert til σ·S/(S − PV(D)) for hele løpetiden. Justerer for mye når utbyttet kommer sent.',
    inputs: [...base('call'), ...divInputs()],
    compute: adjusted(simpleVolAdjustment),
  },
  {
    id: 'div-vol-haug',
    chapter: 9,
    group: 'Volatilitetsjusteringer',
    name: 'Haug og Haug volatilitetsjustering',
    authors: 'Haug og Haug (1998), Haug, Haug og Lewis (2003)',
    description: 'Volatiliteten justeres bare for tiden før hvert utbytte: σ_adj²·T = Σ σ_k²·(t_{k+1} − t_k) med σ_k = σ·S/(S − PV av gjenværende utbytter).',
    inputs: [...base('call'), ...divInputs()],
    compute: adjusted(haugHaugVol),
  },
  {
    id: 'div-vol-bgs',
    chapter: 9,
    group: 'Volatilitetsjusteringer',
    name: 'Bos-Gairat-Shepeleva volatilitetsjustering',
    authors: 'Bos, Gairat og Shepeleva (2003)',
    description: 'Volatilitetsjustering som avhenger av innløsningskursen og tidspunktet for hvert utbytte, brukt sammen med S − PV(D). Svært nøyaktig for moderate utbytter.',
    inputs: [...base('call'), ...divInputs()],
    compute: adjusted(bgsVol),
  },
  {
    id: 'div-bos-vandermark',
    chapter: 9,
    group: 'Volatilitetsjusteringer',
    name: 'Bos og Vandermark: justering av spot og innløsningskurs',
    authors: 'Bos og Vandermark (2002)',
    description: 'Hvert utbytte deles etter tidspunktet: andelen (T − t)/T trekkes fra spot og andelen t/T legges (rentejustert) til innløsningskursen.',
    inputs: [...base('call'), ...divInputs()],
    compute: (p) => {
      const res = bosVandermark({ ...p, divs: schedule(p) });
      return {
        'Pris': res.price,
        'Justert spot S − X_n': res.Sadj,
        'Justert innløsningskurs X + X_f·e^{rT}': res.Xadj,
        'Nær del X_n': res.Xn,
        'Fjern del X_f': res.Xf,
      };
    },
  },
  {
    id: 'div-hhl-european',
    chapter: 9,
    group: 'Europeiske opsjoner',
    name: 'Eksakt pris med diskrete utbytter (HHL)',
    authors: 'Haug, Haug og Lewis (2003)',
    description: 'Eksakt europeisk pris når aksjen er lognormal mellom utbyttene og faller med utbyttet på utbyttedatoen. Black-Scholes-verdien etter siste utbytte integreres numerisk bakover over utbyttedatoene.',
    inputs: [...base('call'), ...divInputs()],
    compute: (p) => {
      const divs = schedule(p);
      const res = hhlEuropean({ ...p, divs });
      return { 'Pris': res.price, 'Escrowed dividend-modellen': escrowedDividend({ ...p, divs }).price };
    },
  },
  {
    id: 'div-hhl-american-call',
    chapter: 9,
    group: 'Amerikanske opsjoner',
    name: 'Amerikansk call med diskrete utbytter (HHL)',
    authors: 'Haug, Haug og Lewis (2003)',
    description: 'Uten løpende utbytte lønner det seg bare å innløse en call rett før en utbyttedato. Rekursiv integrasjon over utbyttedatoene gir da eksakt verdi med flere utbytter.',
    inputs: [S(100), X(100), T(1), r(0.06), v(0.3), ...divInputs()],
    compute: (p) => {
      const divs = schedule(p);
      const res = hhlAmericanCall({ ...p, divs });
      const out = { 'Pris': res.price, 'Europeisk verdi (HHL)': hhlEuropean({ ...p, type: 'call', divs }).price };
      res.critical.forEach((c, i) => {
        out[`Kritisk kurs rett før utbytte ${i + 1}`] = Number.isFinite(c) ? c : 'ingen innløsning';
      });
      return out;
    },
  },
  {
    id: 'div-roll-geske-whaley',
    chapter: 9,
    group: 'Amerikanske opsjoner',
    name: 'Roll-Geske-Whaley',
    authors: 'Roll (1977), Geske (1979, 1981), Whaley (1981)',
    description: 'Lukket formel for amerikansk call på en aksje med ett kontant utbytte, i escrowed-modellen. Tidlig innløsning skjer rett før utbyttet hvis kursen da er over den kritiske kursen.',
    inputs: [
      S(80), X(82),
      num('t1', 'Tid til utbytte t (år)', 0.25, { min: 0, exclusiveMin: true }),
      T(0.3333), r(0.06),
      num('D', 'Utbytte D', 4, { min: 0 }),
      v(0.3),
    ],
    compute: (p) => {
      const res = rollGeskeWhaley({ S: p.S, X: p.X, t1: p.t1, T: p.T, r: p.r, D: p.D, v: p.v });
      return {
        'Pris': res.price,
        'Kritisk kurs rett før utbyttet': res.earlyExercise ? res.critical : 'ingen tidlig innløsning',
      };
    },
    example: 4.386,
    exampleTol: 2e-4,
  },
  {
    id: 'div-black-approximation',
    chapter: 9,
    group: 'Amerikanske opsjoner',
    name: 'Blacks pseudoamerikanske tilnærming',
    authors: 'Black (1975)',
    description: 'Den amerikanske call-verdien tilnærmes med den høyeste av europeiske call som forfaller rett før hvert utbytte og ved T, hver med spot minus nåverdien av utbyttene før forfallet.',
    inputs: [S(80), X(82), T(0.3333), r(0.06), v(0.3), ...divInputs([0.25], [4])],
    compute: (p) => {
      const res = blackPseudoAmerican({ ...p, divs: schedule(p) });
      const out = {
        'Pris': res.price,
        'Europeisk call til T': res.europeanAtT,
        'Beste innløsning': res.bestDividend === 0 ? 'ved forfall' : `rett før utbytte ${res.bestDividend}`,
      };
      for (const c of res.candidates) if (c.label > 0) out[`Europeisk call til rett før utbytte ${c.label}`] = c.price;
      return out;
    },
  },
  {
    id: 'div-binomial',
    chapter: 9,
    group: 'Amerikanske opsjoner',
    name: 'Binomialtre med diskrete utbytter',
    authors: 'Cox, Ross og Rubinstein (1979), Vellekoop og Nieuwenhuis (2006)',
    description: 'CRR-tre for amerikanske eller europeiske opsjoner. «Faktisk utbytte»: kursen faller med D på utbyttedatoen og verdien hentes ved interpolasjon i treet. «Escrowed»: treet bygges for S − PV(D).',
    inputs: [
      select('exercise', 'Innløsning', [
        { value: 'american', label: 'Amerikansk' },
        { value: 'european', label: 'Europeisk' },
      ], 'american'),
      select('model', 'Utbyttemodell', [
        { value: 'real', label: 'Faktisk utbytte (kursen faller med D)' },
        { value: 'escrowed', label: 'Escrowed dividend-modellen' },
      ], 'real'),
      ...base('put'), ...divInputs(),
      int('n', 'Antall tidssteg n', 500, { min: 3, max: 5000 }),
    ],
    greeks: false,
    compute: (p) => {
      const divs = schedule(p);
      const res = dividendTree({ ...p, divs });
      return { 'Pris': res.price };
    },
  },
  {
    id: 'div-compare',
    chapter: 9,
    group: 'Sammenligning',
    name: 'Sammenligning av metoder for diskrete utbytter',
    authors: 'Haug, Haug og Lewis (2003)',
    description: 'Europeiske priser fra escrowed-modellen, volatilitetsjusteringene og Bos-Vandermark mot den eksakte HHL-verdien, samt amerikanske verdier.',
    inputs: [...base('call'), ...divInputs()],
    compute: (p) => {
      const divs = schedule(p);
      const q = { ...p, divs };
      const exact = hhlEuropean(q).price;
      const out = { 'Eksakt europeisk (HHL)': exact };
      const methods = [
        ['Escrowed dividend', escrowedDividend],
        ['Enkel volatilitetsjustering', simpleVolAdjustment],
        ['Haug og Haug', haugHaugVol],
        ['Bos-Gairat-Shepeleva', bgsVol],
        ['Bos-Vandermark', bosVandermark],
      ];
      const safe = (fn) => {
        try {
          return fn().price;
        } catch (e) {
          return null;
        }
      };
      const prices = methods.map(([label, fn]) => [label, safe(() => fn(q))]);
      for (const [label, x] of prices) out[label] = x ?? 'ikke definert';
      for (const [label, x] of prices) out[`Avvik ${label}`] = x === null ? 'ikke definert' : x - exact;
      out['Amerikansk (binomialtre, 500 steg)'] = safe(() => dividendTree({ ...q, exercise: 'american', n: 500 })) ?? 'ikke definert';
      if (p.type === 'call' && p.r >= 0) out['Amerikansk call (HHL)'] = hhlAmericanCall(q).price;
      return out;
    },
  },
];
