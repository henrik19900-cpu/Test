// Kapittel 11: rentederivater.
// Konvertering mellom kontinuerlig rente og rente med m forrentninger per år finnes også i
// kapittel 14 (formula-rate-conversion); her ligger pengemarkedskonvensjonene.
import {
  moneyMarketRates, fra, futuresToForward, bondFromYield, bondYield,
  moneyMarketFuturesOption, caplet, capFloor, swaption, bondOptionBlack,
  schaeferSchwartz, schaeferSchwartzBSM,
  vasicekBond, vasicekOption, vasicekCouponOption, hoLeeOption, hullWhiteOption,
  rendlemanBartter, bdtCalibrate, bdtOption,
} from '../models/rates.js';
import { callPut, num, int, list, select, S, F, X, T, r, v } from './common.js';

const pos = { min: 0, exclusiveMin: true };

const basisSelect = (label = 'Dagtelling') => select('basis', label, [
  { value: '360', label: 'ACT/360' },
  { value: '365', label: 'ACT/365' },
], '360');

const exerciseSelect = () => select('exercise', 'Innløsning', [
  { value: 'european', label: 'Europeisk' },
  { value: 'american', label: 'Amerikansk' },
], 'european');

const capFloorSelect = () => select('type', 'Type', [
  { value: 'call', label: 'Cap / caplet' },
  { value: 'put', label: 'Floor / floorlet' },
], 'call');

const payerReceiver = () => select('type', 'Type', [
  { value: 'call', label: 'Betaler fast rente (payer)' },
  { value: 'put', label: 'Mottar fast rente (receiver)' },
], 'call');

const rate = (key, label, d, extra = {}) => num(key, label, d, { unit: 'rate', ...extra });
const L = (d = 100) => num('L', 'Pålydende L', d, pos);
const sBond = (d) => num('s', 'Obligasjonens forfall s (år)', d, pos);
const Topt = (d) => T(d, 'Opsjonens løpetid T (år)');
const kappa = (d, label = 'Mean reversion κ') => num('kappa', label, d, { min: 0 });
const sigmaAbs = (d) => num('v', 'Volatilitet i kortrenten σ (absolutt)', d, { min: 0, unit: 'rate' });
const pct = (x) => `${(100 * x).toFixed(2).replace('.', ',')} %`;

export default [
  // --- Pengemarked og FRA ---------------------------------------------------------------
  {
    id: 'rate-money-market',
    chapter: 11,
    group: 'Pengemarked og FRA',
    name: 'Pengemarkedsrenter og dagtelling',
    authors: 'Haug (2007), kap. 11',
    description: 'Gjør om en rente for en gitt periode mellom enkel rente (ACT/360 og ACT/365), diskonteringsrente, kontinuerlig rente og rente med m forrentninger per år.',
    inputs: [
      select('from', 'Oppgitt rente er', [
        { value: 'simple', label: 'Enkel rente (pengemarked)' },
        { value: 'discount', label: 'Diskonteringsrente (diskontobasis)' },
        { value: 'cont', label: 'Kontinuerlig rente (ACT/365)' },
        { value: 'comp', label: 'Rente med m forrentninger per år (ACT/365)' },
      ], 'simple'),
      rate('rate', 'Rente', 0.05),
      int('days', 'Dager i perioden', 90, { min: 1 }),
      basisSelect('Dagtelling for enkel rente og diskonteringsrente'),
      int('m', 'Forrentninger per år m', 2, { min: 1 }),
    ],
    compute: (p) => {
      const c = moneyMarketRates({ ...p, basis: Number(p.basis) });
      return {
        'Kontinuerlig rente, ACT/365 (%)': 100 * c.cont,
        'Enkel rente, ACT/360 (%)': 100 * c.simple360,
        'Enkel rente, ACT/365 (%)': 100 * c.simple365,
        [`Diskonteringsrente, ACT/${p.basis} (%)`]: 100 * c.discount,
        'Effektiv årlig rente (%)': 100 * c.annual,
        [`Rente med ${p.m} forrentninger per år (%)`]: 100 * c.comp,
        'Diskonteringsfaktor': c.df,
        'Pris per 100 i pålydende': 100 * c.df,
      };
    },
    greeks: false,
  },
  {
    id: 'rate-fra',
    chapter: 11,
    group: 'Pengemarked og FRA',
    name: 'FRA – fremtidig renteavtale',
    authors: 'Haug (2007), kap. 11',
    description: 'FRA-renten for perioden fra T1 til T2 ut fra to pengemarkedsrenter (enkel rente), verdien av en inngått FRA og oppgjørsbeløpet ved T1.',
    payoff: 'N (L − X) τ / (1 + L τ) betales ved T1 til kjøperen',
    inputs: [
      rate('r1', 'Pengemarkedsrente til T1, r1', 0.05),
      int('d1', 'Dager til T1', 90, { min: 0 }),
      rate('r2', 'Pengemarkedsrente til T2, r2', 0.055),
      int('d2', 'Dager til T2', 270, { min: 1 }),
      basisSelect(),
      rate('X', 'Avtalt FRA-rente X', 0.055),
      num('N', 'Hovedstol N', 1000000, pos),
      rate('L', 'Fiksert rente ved T1, L (for oppgjøret)', 0.06),
    ],
    compute: (p) => {
      const f = fra({ ...p, basis: Number(p.basis) });
      return {
        'FRA-rente (%)': 100 * f.F,
        'Verdi i dag for kjøper (betaler X)': f.value,
        'Oppgjør ved T1 til kjøper, gitt L': f.settlement,
        'Periodelengde τ (år)': f.tau,
        'Diskonteringsfaktor til T1': f.df1,
        'Diskonteringsfaktor til T2': f.df2,
      };
    },
  },
  {
    id: 'rate-convexity',
    chapter: 11,
    group: 'Pengemarked og FRA',
    name: 'Konveksitetsjustering – futures mot FRA',
    authors: 'Ho og Lee (1986), Hull og White (1990)',
    description: 'Renten i en pengemarkedsfutures er høyere enn forwardrenten fordi futures gjøres opp daglig. Justeringen (kontinuerlig rente) er σ² t1 t2/2 med Ho og Lee (a = 0) og har en lukket form med Hull og White (a > 0).',
    inputs: [
      num('Pf', 'Futurespris (100 − rente)', 94, { min: 0, max: 100, exclusiveMax: true }),
      num('t1', 'Tid til futuresforfall t1 (år)', 8, { min: 0 }),
      num('tau', 'Renteperiode τ (år)', 0.25, pos),
      sigmaAbs(0.012),
      num('a', 'Mean reversion a (0 = Ho og Lee)', 0, { min: 0 }),
    ],
    compute: (p) => {
      const c = futuresToForward(p);
      return {
        'Forwardrente, enkel rente (%)': 100 * c.forwardSimple,
        'Futuresrente, enkel rente (%)': 100 * c.futuresRate,
        'Konveksitetsjustering (%-poeng, kontinuerlig)': 100 * c.adj,
        'Futuresrente, kontinuerlig (%)': 100 * c.futuresCont,
        'Forwardrente, kontinuerlig (%)': 100 * c.forwardCont,
      };
    },
  },

  // --- Obligasjonsmatematikk --------------------------------------------------------------
  {
    id: 'rate-bond-price',
    chapter: 11,
    group: 'Obligasjonsmatematikk',
    name: 'Obligasjonspris, durasjon og konveksitet',
    authors: 'Macaulay (1938), Haug (2007), kap. 11',
    description: 'Kurs på en kupongobligasjon fra yielden (m forrentninger per år), med påløpte renter, Macaulay- og modifisert durasjon, konveksitet og prisendringen ved et renteskift Δy.',
    inputs: [
      rate('y', 'Yield y', 0.08),
      rate('c', 'Kupongrente c', 0.08, { min: 0 }),
      int('m', 'Kuponger per år m', 1, { min: 1 }),
      T(10, 'Tid til forfall T (år)'),
      L(100),
      rate('dy', 'Renteskift Δy', 0.01),
    ],
    compute: (p) => {
      const b = bondFromYield(p);
      const shifted = bondFromYield({ ...p, y: p.y + p.dy });
      return {
        'Ren kurs': b.clean,
        'Kurs inkl. påløpte renter': b.dirty,
        'Påløpte renter': b.accrued,
        'Macaulay-durasjon (år)': b.macaulay,
        'Modifisert durasjon': b.modified,
        'Konveksitet': b.convexity,
        'Verdiendring per basispunkt (DV01)': b.dv01,
        'Prisendring ved Δy (durasjon og konveksitet)': b.dirty * (-b.modified * p.dy + 0.5 * b.convexity * p.dy * p.dy),
        'Prisendring ved Δy (eksakt)': shifted.dirty - b.dirty,
      };
    },
  },
  {
    id: 'rate-bond-yield',
    chapter: 11,
    group: 'Obligasjonsmatematikk',
    name: 'Yield fra obligasjonskurs',
    authors: 'Haug (2007), kap. 11',
    description: 'Finner yielden (m forrentninger per år) som gir observert kurs, og regner ut durasjon og konveksitet ved denne yielden.',
    inputs: [
      select('priceType', 'Kursen er', [
        { value: 'clean', label: 'Ren kurs (uten påløpte renter)' },
        { value: 'dirty', label: 'Kurs inkl. påløpte renter' },
      ], 'clean'),
      num('price', 'Kurs', 95, pos),
      rate('c', 'Kupongrente c', 0.08, { min: 0 }),
      int('m', 'Kuponger per år m', 2, { min: 1 }),
      T(9.75, 'Tid til forfall T (år)'),
      L(100),
    ],
    compute: (p) => {
      const b = bondYield(p);
      return {
        'Yield (%)': 100 * b.y,
        'Kontinuerlig yield (%)': 100 * p.m * Math.log1p(b.y / p.m),
        'Kurs inkl. påløpte renter': b.dirty,
        'Påløpte renter': b.accrued,
        'Macaulay-durasjon (år)': b.macaulay,
        'Modifisert durasjon': b.modified,
        'Konveksitet': b.convexity,
      };
    },
  },

  // --- Black-76 for renteopsjoner ---------------------------------------------------------
  {
    id: 'rate-mm-futures-option',
    chapter: 11,
    group: 'Black-76 for renteopsjoner',
    name: 'Opsjon på pengemarkedsfutures',
    authors: 'Black (1976)',
    description: 'Opsjon på en futures notert som 100 minus renten (for eksempel Euribor-futures). Renten 100 − F er lognormal, så en call på futuresprisen er en put på renten.',
    payoff: 'max(F_T − X, 0) = max((100 − X) − (100 − F_T), 0)',
    inputs: [
      callPut('call'), F(94.5, 'Futurespris F'), X(95, 'Innløsningskurs X'), T(0.5), r(0.05),
      v(0.2, 'Volatilitet i futuresrenten σ'),
    ],
    compute: (p) => {
      const o = moneyMarketFuturesOption(p);
      return { 'Pris (prispoeng)': o.price, 'Futuresrente 100 − F (%)': o.Fr, 'Innløsningsrente 100 − X (%)': o.Xr };
    },
    chart: false,
  },
  {
    id: 'rate-caplet',
    chapter: 11,
    group: 'Black-76 for renteopsjoner',
    name: 'Caplet og floorlet',
    authors: 'Black (1976)',
    description: 'Opsjon på renten for én periode: fikseres ved T og betales ved T + τ. Diskontering med e^{−rT} til fiksering og 1/(1 + Fτ) videre til betaling.',
    payoff: 'N τ max(L_T − X, 0) (caplet) / N τ max(X − L_T, 0) (floorlet), betalt ved T + τ',
    inputs: [
      capFloorSelect(), num('F', 'Forwardrente F', 0.07, { ...pos, unit: 'rate' }), rate('X', 'Cap-/floor-rente X', 0.08, pos),
      T(1, 'Fiksering T (år)'), num('tau', 'Renteperiode τ (år)', 0.25, pos), r(0.065, 'Risikofri rente r (til fiksering)'),
      v(0.2), num('N', 'Hovedstol N', 10000, pos),
    ],
    compute: (p) => {
      const c = caplet(p);
      const other = caplet({ ...p, type: p.type === 'call' ? 'put' : 'call' });
      const df = Math.exp(-p.r * p.T) / (1 + p.F * p.tau);
      return {
        'Pris': c,
        [p.type === 'call' ? 'Floorlet med samme input' : 'Caplet med samme input']: other,
        'Diskonteringsfaktor til betaling': df,
      };
    },
  },
  {
    id: 'rate-cap-floor',
    chapter: 11,
    group: 'Black-76 for renteopsjoner',
    name: 'Cap og floor',
    authors: 'Black (1976)',
    description: 'En cap (floor) er en serie caplets (floorlets) med fikseringer T_i og forwardrenter F_i, priset med Black-76 og samme (flate) volatilitet. Cap − floor er verdien av en renteswap.',
    payoff: 'Σ N τ max(L_{T_i} − X, 0) (cap) / Σ N τ max(X − L_{T_i}, 0) (floor)',
    inputs: [
      capFloorSelect(),
      list('times', 'Fikseringstidspunkter T_i (år)', [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75], { minLength: 1 }),
      list('forwards', 'Forwardrenter F_i', [0.05, 0.052, 0.054, 0.055, 0.056, 0.057, 0.058], { minLength: 1 }),
      rate('X', 'Cap-/floor-rente X', 0.055, pos), num('tau', 'Renteperiode τ (år)', 0.25, pos),
      r(0.05, 'Risikofri rente r'), v(0.2, 'Flat volatilitet σ'), num('N', 'Hovedstol N', 1000000, pos),
    ],
    compute: (p) => {
      const c = capFloor(p);
      const isCap = p.type === 'call';
      const out = {
        'Pris': c.price,
        [isCap ? 'Floor med samme input' : 'Cap med samme input']: c.otherPrice,
        'Swapverdi (cap − floor)': c.swap,
      };
      c.parts.forEach((x, i) => {
        out[`${isCap ? 'Caplet' : 'Floorlet'} ${i + 1} (T = ${String(p.times[i]).replace('.', ',')})`] = x;
      });
      return out;
    },
  },
  {
    id: 'rate-swaption',
    chapter: 11,
    group: 'Black-76 for renteopsjoner',
    name: 'Europeisk swapsjon',
    authors: 'Black (1976)',
    description: 'Rett til å gå inn i en renteswap som betaler (payer) eller mottar (receiver) fast rente X. Forward swaprenten er lognormal; annuiteten regnes med forward swaprenten selv, som i Haug.',
    payoff: 'A · max(F_T − X, 0) (payer) / A · max(X − F_T, 0) (receiver), A = [1 − (1 + F/m)^{−t1·m}]/F',
    inputs: [
      payerReceiver(), num('F', 'Forward swaprente F', 0.07, { ...pos, unit: 'rate' }), rate('X', 'Innløsningsrente X', 0.075, pos),
      Topt(2), num('t1', 'Swappens løpetid t1 (år)', 4, pos), int('m', 'Betalinger per år m', 2, { min: 1 }),
      r(0.06), v(0.2), num('N', 'Hovedstol N', 100, pos),
    ],
    compute: (p) => {
      const s = swaption(p);
      return {
        'Pris': s.price,
        'Annuitetsfaktor A': s.annuity,
        'Forward swapverdi (payer − receiver)': s.forwardValue,
      };
    },
    example: 1.7964,
  },
  {
    id: 'rate-bond-option-black',
    chapter: 11,
    group: 'Obligasjonsopsjoner',
    name: 'Europeisk obligasjonsopsjon (Black-76)',
    authors: 'Black (1976)',
    description: 'Black-76 på forward obligasjonskurs. Er volatiliteten oppgitt i yield, gjøres den om til prisvolatilitet med σ_P ≈ D · y · σ_y, der D er modifisert durasjon ved forfall og y forward yield.',
    payoff: 'max(B_T − X, 0) / max(X − B_T, 0)',
    inputs: [
      callPut('call'), F(939.68, 'Forward obligasjonskurs F'), X(1000), Topt(10 / 12), r(0.1),
      select('volType', 'Volatiliteten gjelder', [
        { value: 'price', label: 'Obligasjonskursen' },
        { value: 'yield', label: 'Yielden' },
      ], 'price'),
      v(0.09, 'Volatilitet σ'), rate('y', 'Forward yield y', 0.1, pos), num('D', 'Modifisert durasjon D ved T', 6.5, pos),
    ],
    compute: (p) => {
      const o = bondOptionBlack(p);
      return { 'Pris': o.price, 'Prisvolatilitet σ_P': o.vPrice, 'Yield-volatilitet σ_y': o.vYield };
    },
  },
  {
    id: 'rate-schaefer-schwartz',
    chapter: 11,
    group: 'Obligasjonsopsjoner',
    name: 'Schaefer og Schwartz – volatilitet proporsjonal med durasjonen',
    authors: 'Schaefer og Schwartz (1987)',
    description: 'Obligasjonskursens volatilitet er K B^{α−1} D(t), der durasjonen D(t) = D − t avtar mot forfall. K settes slik at volatiliteten i dag er σ. Europeisk opsjon løses med finite difference (Crank-Nicolson); for α = 1 er BSM med effektiv volatilitet eksakt.',
    payoff: 'max(B_T − X, 0) / max(X − B_T, 0)',
    inputs: [
      callPut('call'), S(100, 'Obligasjonskurs B'), X(100), Topt(1), r(0.05),
      v(0.08, 'Prisvolatilitet i dag σ'), num('D', 'Durasjon D (år)', 5, pos),
      num('alpha', 'Eksponent α', 0.5, { min: 0, max: 1 }),
    ],
    compute: (p) => {
      const bsm = schaeferSchwartzBSM(p);
      return {
        'Pris': schaeferSchwartz(p),
        'BSM med effektiv volatilitet (eksakt for α = 1)': bsm.price,
        'Effektiv volatilitet σ√[(D³ − (D − T)³)/(3D²T)]': bsm.veff,
        'Konstant K = σ B^{1−α}/D': p.v * p.S ** (1 - p.alpha) / p.D,
      };
    },
  },

  // --- Ett-faktor rentemodeller ----------------------------------------------------------
  {
    id: 'rate-vasicek-bond',
    chapter: 11,
    group: 'Ett-faktor rentemodeller',
    name: 'Vasicek – nullkupongobligasjon',
    authors: 'Vasicek (1977)',
    description: 'Kortrenten følger dr = κ(θ − r)dt + σ dz. Prisen på en nullkupongobligasjon er A e^{−B r}, med B = (1 − e^{−κT})/κ.',
    inputs: [
      rate('r', 'Kortrente i dag r', 0.05), kappa(0.2), rate('theta', 'Langsiktig rentenivå θ', 0.06),
      sigmaAbs(0.02), T(5, 'Løpetid T (år)'), L(100),
    ],
    compute: (p) => {
      const b = vasicekBond(p);
      return {
        'Obligasjonspris': p.L * b.P,
        'Nullkupongrente, kontinuerlig (%)': -100 * Math.log(b.P) / p.T,
        'B(0,T)': b.B,
        'ln A(0,T)': b.lnA,
        'Langsiktig rente R∞ = θ − σ²/(2κ²) (%)': p.kappa > 0 ? 100 * (p.theta - p.v * p.v / (2 * p.kappa * p.kappa)) : '–',
      };
    },
  },
  {
    id: 'rate-vasicek-option',
    chapter: 11,
    group: 'Ett-faktor rentemodeller',
    name: 'Vasicek – opsjon på nullkupongobligasjon',
    authors: 'Vasicek (1977), Jamshidian (1989)',
    description: 'Europeisk opsjon med forfall T på en nullkupongobligasjon som forfaller ved s, i Vasicek-modellen.',
    payoff: 'max(L P(T,s) − X, 0) / max(X − L P(T,s), 0)',
    inputs: [
      callPut('call'), L(100), X(90), Topt(1), sBond(3),
      rate('r', 'Kortrente i dag r', 0.05), kappa(0.2), rate('theta', 'Langsiktig rentenivå θ', 0.06), sigmaAbs(0.02),
    ],
    compute: (p) => {
      const o = vasicekOption(p);
      return {
        'Pris': o.price,
        'Obligasjonspris L P(0,s)': p.L * o.P0s,
        'Forward obligasjonskurs L P(0,s)/P(0,T)': p.L * o.P0s / o.P0T,
        'P(0,T)': o.P0T,
        'Prisvolatilitet σ_P': o.sigmaP,
      };
    },
  },
  {
    id: 'rate-vasicek-coupon-option',
    chapter: 11,
    group: 'Ett-faktor rentemodeller',
    name: 'Vasicek – opsjon på kupongobligasjon (Jamshidian)',
    authors: 'Jamshidian (1989)',
    description: 'Europeisk opsjon på en kupongobligasjon i Vasicek-modellen, skrevet som en sum av opsjoner på nullkuponger med innløsningskurser fra den kritiske renten r*. Kuponger før T tilfaller ikke opsjonen.',
    payoff: 'max(B_T − X, 0) / max(X − B_T, 0), B_T = verdien ved T av kontantstrømmene etter T',
    inputs: [
      callPut('call'), L(100), rate('c', 'Kupongrente c', 0.06, { min: 0 }), int('m', 'Kuponger per år m', 2, { min: 1 }),
      sBond(5), X(100, 'Innløsningskurs X (inkl. påløpte renter)'), Topt(1.25),
      rate('r', 'Kortrente i dag r', 0.05), kappa(0.2), rate('theta', 'Langsiktig rentenivå θ', 0.06), sigmaAbs(0.02),
    ],
    compute: (p) => {
      const o = vasicekCouponOption(p);
      return {
        'Pris': o.price,
        'Kritisk rente r* (%)': 100 * o.rStar,
        'Nåverdi av kontantstrømmene etter T': o.bond,
        'Forward obligasjonskurs': o.forward,
        'Antall kontantstrømmer etter T': o.n,
      };
    },
  },
  {
    id: 'rate-ho-lee-option',
    chapter: 11,
    group: 'Ett-faktor rentemodeller',
    name: 'Ho og Lee – opsjon på nullkupongobligasjon',
    authors: 'Ho og Lee (1986)',
    description: 'Gaussisk kortrente uten mean reversion, tilpasset dagens rentekurve (her flat med kontinuerlig rente r). Prisvolatiliteten er σ (s − T) √T.',
    payoff: 'max(L P(T,s) − X, 0) / max(X − L P(T,s), 0)',
    inputs: [callPut('call'), L(100), X(90), Topt(1), sBond(3), r(0.05, 'Flat nullkupongrente r'), sigmaAbs(0.01)],
    compute: (p) => {
      const o = hoLeeOption(p);
      return { 'Pris': o.price, 'Obligasjonspris L P(0,s)': p.L * o.P0s, 'P(0,T)': o.P0T, 'Prisvolatilitet σ_P': o.sigmaP };
    },
  },
  {
    id: 'rate-hull-white-option',
    chapter: 11,
    group: 'Ett-faktor rentemodeller',
    name: 'Hull og White – opsjon på nullkupongobligasjon',
    authors: 'Hull og White (1990)',
    description: 'Vasicek-dynamikk med mean reversion κ, tilpasset dagens rentekurve (her flat med kontinuerlig rente r). Prisvolatiliteten er σ (1 − e^{−κ(s−T)})/κ · √[(1 − e^{−2κT})/(2κ)].',
    payoff: 'max(L P(T,s) − X, 0) / max(X − L P(T,s), 0)',
    inputs: [callPut('call'), L(100), X(90), Topt(1), sBond(3), r(0.05, 'Flat nullkupongrente r'), kappa(0.1), sigmaAbs(0.01)],
    compute: (p) => {
      const o = hullWhiteOption(p);
      return { 'Pris': o.price, 'Obligasjonspris L P(0,s)': p.L * o.P0s, 'P(0,T)': o.P0T, 'Prisvolatilitet σ_P': o.sigmaP };
    },
  },

  // --- Rentetrær ---------------------------------------------------------------------------
  {
    id: 'rate-rendleman-bartter',
    chapter: 11,
    group: 'Rentetrær',
    name: 'Rendleman og Bartter – binomialtre for kortrenten',
    authors: 'Rendleman og Bartter (1980)',
    description: 'Kortrenten følger en geometrisk brownsk bevegelse, dr = μ r dt + σ r dz. Binomialtreet priser nullkupongobligasjonen og en europeisk eller amerikansk opsjon på den.',
    payoff: 'max(L P(T,s) − X, 0) / max(X − L P(T,s), 0)',
    inputs: [
      callPut('put'), exerciseSelect(), L(100), X(90), Topt(1), sBond(3),
      rate('r', 'Kortrente i dag r', 0.05, pos), rate('mu', 'Drift i kortrenten μ', 0.01),
      v(0.15, 'Relativ volatilitet i kortrenten σ'), int('n', 'Antall tidssteg n (til s)', 300, { min: 1, max: 3000 }),
    ],
    compute: (p) => {
      const o = rendlemanBartter(p);
      return {
        'Pris': o.price,
        'Obligasjonspris L P(0,s) i treet': o.bond,
        'Nullkupongrente til s, kontinuerlig (%)': -100 * Math.log(o.bond / p.L) / p.s,
        'Sannsynlighet for oppgang p': o.p,
      };
    },
  },
  {
    id: 'rate-bdt',
    chapter: 11,
    group: 'Rentetrær',
    name: 'Black-Derman-Toy – kalibrert binomialtre',
    authors: 'Black, Derman og Toy (1990)',
    description: 'Lognormalt binomialtre for kortrenten, kalibrert slik at det gjenskaper nullkupongrentene og yield-volatilitetene. Priser europeiske og amerikanske opsjoner på en nullkupongobligasjon.',
    payoff: 'max(L P(T,s) − X, 0) / max(X − L P(T,s), 0)',
    inputs: [
      list('maturities', 'Løpetider (Δt, 2Δt, …) i år', [1, 2, 3, 4, 5], { minLength: 2 }),
      list('yields', 'Nullkupongrenter (én forrentning per Δt)', [0.1, 0.11, 0.12, 0.125, 0.13], { minLength: 2 }),
      list('vols', 'Yield-volatiliteter', [0.2, 0.19, 0.18, 0.17, 0.16], {
        minLength: 2,
        help: 'Én per løpetid. Den første brukes ikke, fordi korteste rente er kjent i dag.',
      }),
      callPut('call'), exerciseSelect(), L(100), X(65),
      int('kT', 'Opsjonens løpetid (antall perioder Δt)', 2, { min: 0 }),
      int('ks', 'Obligasjonens løpetid (antall perioder Δt)', 5, { min: 1 }),
    ],
    compute: (p) => {
      const tree = bdtCalibrate(p);
      const o = bdtOption({ ...p, tree });
      const out = {
        'Pris': o.price,
        'Obligasjonspris L P(0,s)': o.bond,
      };
      tree.rates.forEach((row, i) => {
        const t = String(+(i * tree.dt).toPrecision(12)).replace('.', ',');
        out[`Kortrenter ved t = ${t}`] = Array.from(row, pct).join(' · ');
      });
      tree.sigmas.forEach((s, i) => {
        if (i > 0) out[`Kortrentevolatilitet σ ved t = ${String(+(i * tree.dt).toPrecision(12)).replace('.', ',')}`] = s;
      });
      return out;
    },
  },
];
