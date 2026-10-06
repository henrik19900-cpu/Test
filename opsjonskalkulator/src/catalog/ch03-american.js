import {
  bawAmerican, bsAmerican1993, bsAmerican2002, perpetualAmerican, putCallTransform,
} from '../models/american.js';
import { crrTree } from '../models/lattice.js';
import { gbsm } from '../models/bsm.js';
import { callPut, int, S, X, T, r, b, v } from './common.js';

const NONE = 'ingen (tidlig innløsning lønner seg aldri)';
const level = (x) => (x === null || x === undefined || !Number.isFinite(x) ? NONE : x);

export default [
  {
    id: 'am-baw',
    chapter: 3,
    group: 'Analytiske tilnærminger',
    name: 'Barone-Adesi og Whaley',
    authors: 'Barone-Adesi og Whaley (1987)',
    description: 'Kvadratisk tilnærming for amerikanske opsjoner med generell cost of carry. Den kritiske prisen S* løses numerisk; for call over S* (put under S*) er umiddelbar innløsning optimal.',
    payoff: 'max(S − X, 0) / max(X − S, 0), kan innløses når som helst',
    inputs: [callPut('put'), S(100), X(100), T(0.1), r(0.1), b(0), v(0.25)],
    compute: (p) => {
      const res = bawAmerican(p);
      return {
        'Pris': res.price,
        'Europeisk verdi (GBSM)': res.european,
        'Tidlig innløsningspremie': res.premium,
        'Kritisk pris S*': level(res.critical),
      };
    },
    example: 3.1277,
  },
  {
    id: 'am-bs1993',
    chapter: 3,
    group: 'Analytiske tilnærminger',
    name: 'Bjerksund og Stensland (1993)',
    authors: 'Bjerksund og Stensland (1993)',
    description: 'Verdien av å innløse første gang kursen treffer en flat innløsningsgrense I. Gir en nedre grense for den amerikanske verdien. Put prises via put-call-transformasjonen.',
    payoff: 'max(S − X, 0) / max(X − S, 0), kan innløses når som helst',
    inputs: [callPut('call'), S(42), X(40), T(0.75), r(0.04), b(-0.04), v(0.35)],
    compute: (p) => {
      const res = bsAmerican1993(p);
      return {
        'Pris': res.price,
        'Europeisk verdi (GBSM)': res.european,
        'Tidlig innløsningspremie': res.premium,
        'Innløsningsgrense': level(res.boundary),
      };
    },
    example: 5.2704,
  },
  {
    id: 'am-bs2002',
    chapter: 3,
    group: 'Analytiske tilnærminger',
    name: 'Bjerksund og Stensland (2002)',
    authors: 'Bjerksund og Stensland (2002)',
    description: 'Forbedret versjon med innløsningsgrense i to trinn: I2 fram til t1 = ½(√5 − 1)T og I1 deretter. Put prises via put-call-transformasjonen.',
    payoff: 'max(S − X, 0) / max(X − S, 0), kan innløses når som helst',
    inputs: [callPut('call'), S(42), X(40), T(0.75), r(0.04), b(-0.04), v(0.35)],
    compute: (p) => {
      const res = bsAmerican2002(p);
      return {
        'Pris': res.price,
        'Europeisk verdi (GBSM)': res.european,
        'Tidlig innløsningspremie': res.premium,
        'Innløsningsgrense nå (I2)': level(res.I2),
        'Innløsningsgrense fra t1 (I1)': level(res.I1),
        'Skilletidspunkt t1 (år)': res.t1 ?? NONE,
      };
    },
  },
  {
    id: 'am-perpetual',
    chapter: 3,
    group: 'Evigvarende opsjoner',
    name: 'Evigvarende amerikansk opsjon',
    authors: 'McKean (1965), Merton (1973)',
    description: 'Amerikansk opsjon uten forfall. Verdien er eksakt; innløsning er optimal når kursen når den kritiske grensen. Call krever b < r og put krever r > 0.',
    payoff: 'max(S − X, 0) / max(X − S, 0), kan innløses når som helst',
    inputs: [callPut('put'), S(100), X(100), r(0.1), b(0.02), v(0.25)],
    compute: (p) => {
      const res = perpetualAmerican(p);
      return { 'Pris': res.price, 'Kritisk innløsningsgrense': res.boundary, 'Eksponent (y1 eller y2)': res.exponent };
    },
  },
  {
    id: 'am-put-call-transformation',
    chapter: 3,
    group: 'Put-call-transformasjon',
    name: 'Put-call-transformasjon for amerikanske opsjoner',
    authors: 'Bjerksund og Stensland (1993), McDonald og Schroder (1998)',
    description: 'En amerikansk put er verdt det samme som en amerikansk call der spot og innløsningskurs bytter plass, renten er r − b og carry er −b: P(S, X, T, r, b, σ) = C(X, S, T, r − b, −b, σ).',
    inputs: [S(36), X(40), T(1), r(0.06), b(0.06), v(0.2), int('n', 'Antall tidssteg n (binomialtre)', 500, { min: 3, max: 5000 })],
    compute: (p) => {
      const q = putCallTransform(p);
      const putTree = crrTree({ type: 'put', exercise: 'american', S: p.S, X: p.X, T: p.T, r: p.r, b: p.b, v: p.v, n: p.n });
      const callTree = crrTree({ type: 'call', exercise: 'american', ...q, n: p.n });
      return {
        'Put (binomialtre)': putTree.price,
        'Call med transformerte parametre (binomialtre)': callTree.price,
        'Put (Bjerksund-Stensland 2002)': bsAmerican2002({ type: 'put', ...p }).price,
        'Transformert spot (= X)': q.S,
        'Transformert innløsningskurs (= S)': q.X,
        'Transformert rente r − b': q.r,
        'Transformert carry −b': q.b,
      };
    },
  },
  {
    id: 'am-compare',
    chapter: 3,
    group: 'Sammenligning',
    name: 'Sammenligning av metoder for amerikanske opsjoner',
    authors: 'Haug (2007), kap. 3',
    description: 'Barone-Adesi-Whaley og Bjerksund-Stensland (1993 og 2002) mot et Cox-Ross-Rubinstein-binomialtre og den europeiske verdien.',
    inputs: [callPut('put'), S(100), X(100), T(0.5), r(0.1), b(0), v(0.35), int('n', 'Antall tidssteg n (binomialtre)', 500, { min: 3, max: 5000 })],
    compute: (p) => {
      const tree = crrTree({ ...p, exercise: 'american' }).price;
      const baw = bawAmerican(p).price;
      const bs93 = bsAmerican1993(p).price;
      const bs02 = bsAmerican2002(p).price;
      return {
        'Binomialtre (CRR)': tree,
        'Barone-Adesi-Whaley': baw,
        'Bjerksund-Stensland 1993': bs93,
        'Bjerksund-Stensland 2002': bs02,
        'Europeisk (GBSM)': gbsm(p),
        'Avvik BAW − tre': baw - tree,
        'Avvik BS 1993 − tre': bs93 - tree,
        'Avvik BS 2002 − tre': bs02 - tree,
      };
    },
  },
];
