// Kapittel 3: analytiske tilnærminger for amerikanske opsjoner.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  bawAmerican, bsAmerican1993, bsAmerican2002, perpetualAmerican, putCallTransform,
} from '../src/models/american.js';
import { crrTree } from '../src/models/lattice.js';
import { finiteDifference } from '../src/models/finite-difference.js';
import { gbsm } from '../src/models/bsm.js';
import { close } from './helpers.js';

// Fint CRR-tre (snitt av n og n + 1 steg demper oddetall/partall-svingningen).
const tree = (p, n = 2000) => 0.5 * (crrTree({ ...p, exercise: 'american', n }).price
  + crrTree({ ...p, exercise: 'american', n: n + 1 }).price);

// Et utvalg fra bokas tabell for Barone-Adesi og Whaley: X = 100, r = 0,10, b = 0.
const BAW_BOOK = [
  ['call', 90, 0.1, 0.15, 0.0206],
  ['call', 100, 0.5, 0.25, 6.8015],
  ['call', 90, 0.5, 0.35, 5.0063],
  ['put', 100, 0.1, 0.25, 3.1277],
  ['put', 90, 0.5, 0.25, 12.4419],
  ['put', 110, 0.5, 0.35, 5.8823],
];

test('BAW: et utvalg fra bokas tabell (X = 100, r = 0,10, b = 0)', () => {
  // Bokas tall er regnet med en Newton-iterasjon for kritisk pris som stoppes ved relativ
  // toleranse rundt 1e-4–1e-5. Vi løser likningen til maskinpresisjon, så verdiene kan
  // avvike med inntil 5e-4.
  for (const [type, S, T, v, expected] of BAW_BOOK) {
    const res = bawAmerican({ type, S, X: 100, T, r: 0.1, b: 0, v });
    close(res.price, expected, 5e-4, `${type} S=${S} T=${T} σ=${v}`);
  }
});

test('BAW: kritisk pris oppfyller verdimatching og glatt tilpasning', () => {
  for (const [type, b] of [['call', -0.03], ['call', 0], ['put', 0.05], ['put', -0.02]]) {
    const p = { type, X: 100, T: 0.5, r: 0.08, b, v: 0.3 };
    const crit = bawAmerican({ ...p, S: 100 }).critical;
    const z = type === 'call' ? 1 : -1;
    // Rett innenfor fortsettelsesområdet er verdien ≈ innløsningsverdien, og helningen ≈ ±1.
    const h = 1e-4 * crit;
    const inside = crit - z * h;
    const P0 = bawAmerican({ ...p, S: inside }).price;
    const P1 = bawAmerican({ ...p, S: inside - z * h }).price;
    close(P0, z * (inside - p.X), 1e-6, `${type} b=${b} verdimatching`);
    close((P0 - P1) / h, 1, 1e-3, `${type} b=${b} glatt tilpasning`);
  }
});

test('Bjerksund-Stensland 1993: bokas eksempel og referanseverdi for put', () => {
  close(bsAmerican1993({ type: 'call', S: 42, X: 40, T: 0.75, r: 0.04, b: -0.04, v: 0.35 }).price, 5.2704);
  // Put S = 36, X = 40, T = 1, r = b = 0,06, σ = 0,2: 4,4531 (Haugs VBA-kode, også brukt i QuantLibs testsett).
  close(bsAmerican1993({ type: 'put', S: 36, X: 40, T: 1, r: 0.06, b: 0.06, v: 0.2 }).price, 4.4531);
});

// Verdien av strategien «innløs første gang kursen når I2 i [0, t1] eller I1 i [t1, T]» for en call,
// regnet med Crank-Nicolson i ln S med absorberende rand i grensen. BS 1993 er spesialtilfellet I1 = I2.
function policyValuePDE({ S, X, T, r, b, v, I1, I2, t1, nx = 1200, nt = 2400 }) {
  const xTop = Math.log(I2);
  const gap = xTop - Math.log(I1);
  const xLo = Math.min(Math.log(S), Math.log(X)) - 10 * v * Math.sqrt(T);
  let dx = (xTop - xLo) / nx;
  let k = 0;
  if (gap > 0) {
    k = Math.max(1, Math.round(gap / dx));
    dx = gap / k;
  }
  const J = Math.ceil((xTop - xLo) / dx);
  const Sx = Array.from({ length: J + 1 }, (_, j) => Math.exp(xTop - j * dx));
  const nu = b - v * v / 2;
  const up = v * v / (2 * dx * dx) + nu / (2 * dx); // koeffisient for høyere kurs (j − 1)
  const dn = v * v / (2 * dx * dx) - nu / (2 * dx); // koeffisient for lavere kurs (j + 1)
  const mid = -v * v / (dx * dx) - r;
  let V = Sx.map((s, j) => (j >= k ? Math.max(s - X, 0) : s - X));
  const step = (Vold, top, topVal, h, theta) => {
    const N = J - top - 1;
    const d = new Float64Array(N);
    const rhs = new Float64Array(N);
    const Vn = Vold.slice();
    Vn[top] = topVal;
    Vn[J] = 0;
    for (let i = 0; i < N; i++) {
      const j = top + 1 + i;
      rhs[i] = Vold[j] + (1 - theta) * h * (up * Vold[j - 1] + mid * Vold[j] + dn * Vold[j + 1]);
      d[i] = 1 - theta * h * mid;
    }
    const a = -theta * h * up;
    const c = -theta * h * dn;
    rhs[0] -= a * topVal;
    for (let i = 1; i < N; i++) {
      const m = a / d[i - 1];
      d[i] -= m * c;
      rhs[i] -= m * rhs[i - 1];
    }
    Vn[top + N] = rhs[N - 1] / d[N - 1];
    for (let i = N - 2; i >= 0; i--) Vn[top + 1 + i] = (rhs[i] - c * Vn[top + 2 + i]) / d[i];
    return Vn;
  };
  const dt = T / nt;
  const n1 = Math.round((T - t1) / dt);
  for (let s = 0; s < nt; s++) {
    const second = s < n1;
    const top = second ? k : 0;
    const topVal = second ? I1 - X : I2 - X;
    if (s === n1) for (let j = 0; j < k; j++) V[j] = Sx[j] - X;
    if (s === 0 || s === n1) {
      V = step(V, top, topVal, dt / 2, 1);
      V = step(V, top, topVal, dt / 2, 1);
    } else {
      V = step(V, top, topVal, dt, 0.5);
    }
  }
  const u = (xTop - Math.log(S)) / dx;
  const j0 = Math.min(Math.max(Math.floor(u) - 1, 0), J - 3);
  const t = u - j0;
  return V[j0] * (t - 1) * (t - 2) * (t - 3) / -6 + V[j0 + 1] * t * (t - 2) * (t - 3) / 2
    + V[j0 + 2] * t * (t - 1) * (t - 3) / -2 + V[j0 + 3] * t * (t - 1) * (t - 2) / 6;
}

test('Bjerksund-Stensland: lukket formel = PDE-verdien av den samme innløsningsstrategien', () => {
  const cases = [
    { S: 42, X: 40, T: 0.75, r: 0.04, b: -0.04, v: 0.35 },
    { S: 100, X: 100, T: 1, r: 0.08, b: 0, v: 0.35 },
    { S: 90, X: 100, T: 0.5, r: 0.1, b: -0.05, v: 0.25 },
    putCallTransform({ S: 36, X: 40, T: 1, r: 0.06, b: 0.06, v: 0.2 }),
  ];
  for (const p of cases) {
    const c02 = bsAmerican2002({ type: 'call', ...p });
    const c93 = bsAmerican1993({ type: 'call', ...p });
    close(c02.price, policyValuePDE({ ...p, I1: c02.I1, I2: c02.I2, t1: c02.t1 }), 1e-4, `BS 2002 ${JSON.stringify(p)}`);
    close(c93.price, policyValuePDE({ ...p, I1: c93.boundary, I2: c93.boundary, t1: p.T / 2 }), 1e-4, `BS 1993 ${JSON.stringify(p)}`);
  }
});

test('Tilnærmingene mot et fint binomialtre, og amerikansk ≥ europeisk', () => {
  // Avvikene er tilnærmingenes egne (formlene er bekreftet mot PDE over). Største avvik i dette
  // rutenettet er en dyp ITM-put med r = b = 0,06 og T = 0,5, der BAW og BS 2002 bommer med ≈ 0,066.
  const err = { baw: [], bs93: [], bs02: [] };
  for (const type of ['call', 'put']) {
    for (const b of [-0.04, 0, 0.03, 0.06]) {
      for (const [T, v] of [[0.25, 0.2], [0.25, 0.35], [0.5, 0.25]]) {
        for (const S of [90, 100, 110]) {
          const p = { type, S, X: 100, T, r: 0.06, b, v };
          const ref = tree(p, 1000);
          const eu = gbsm(p);
          const baw = bawAmerican(p).price;
          const bs93 = bsAmerican1993(p).price;
          const bs02 = bsAmerican2002(p).price;
          const tag = `${type} S=${S} T=${T} b=${b} σ=${v}`;
          err.baw.push(Math.abs(baw - ref));
          err.bs93.push(Math.abs(bs93 - ref));
          err.bs02.push(Math.abs(bs02 - ref));
          for (const x of [baw, bs93, bs02]) assert.ok(x >= eu - 1e-9, `amerikansk < europeisk ${tag}`);
          assert.ok(ref >= eu - 2e-3, `treet under europeisk ${tag}`); // treet har diskretiseringsfeil ~1e-3
          // BS-verdiene er verdien av en tillatt (ikke optimal) strategi og dermed nedre grenser.
          assert.ok(bs93 <= ref + 2e-3 && bs02 <= ref + 2e-3, `BS over treet ${tag}`);
          assert.ok(bs02 >= bs93 - 1e-9, `BS 2002 under BS 1993 ${tag}`);
        }
      }
    }
  }
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  const max = (a) => Math.max(...a);
  assert.equal(err.baw.length, 72);
  assert.ok(mean(err.baw) < 0.012 && max(err.baw) < 0.07, `BAW: snitt ${mean(err.baw)}, maks ${max(err.baw)}`);
  assert.ok(mean(err.bs93) < 0.025 && max(err.bs93) < 0.11, `BS 1993: snitt ${mean(err.bs93)}, maks ${max(err.bs93)}`);
  assert.ok(mean(err.bs02) < 0.015 && max(err.bs02) < 0.07, `BS 2002: snitt ${mean(err.bs02)}, maks ${max(err.bs02)}`);
  // Kort løpetid og moderat volatilitet: BAW og BS 2002 innenfor 0,05; BS 1993 (flat grense) innenfor 0,07.
  for (const type of ['call', 'put']) {
    const p = { type, S: 100, X: 100, T: 0.25, r: 0.06, b: type === 'call' ? -0.02 : 0.06, v: 0.25 };
    const ref = tree(p, 1000);
    close(bawAmerican(p).price, ref, 0.05, `BAW ${type}`);
    close(bsAmerican2002(p).price, ref, 0.05, `BS 2002 ${type}`);
    close(bsAmerican1993(p).price, ref, 0.07, `BS 1993 ${type}`);
  }
});

test('Ingen tidlig innløsning: call med b ≥ r og put med r ≤ 0 er europeiske', () => {
  for (const fn of [bawAmerican, bsAmerican1993, bsAmerican2002]) {
    const c = { type: 'call', S: 100, X: 95, T: 0.5, r: 0.05, b: 0.05, v: 0.3 };
    close(fn(c).price, gbsm(c), 1e-12, `${fn.name} call`);
    const pz = { type: 'put', S: 100, X: 105, T: 0.5, r: 0, b: 0.02, v: 0.3 };
    close(fn(pz).price, gbsm(pz), 1e-12, `${fn.name} put r=0`);
  }
});

test('Put-call-transformasjonen: P(S, X, r, b) = C(X, S, r − b, −b) i fine trær', () => {
  for (const p of [
    { S: 100, X: 110, T: 0.5, r: 0.06, b: 0.06, v: 0.3 },
    { S: 95, X: 90, T: 1, r: 0.05, b: -0.02, v: 0.25 },
    { S: 100, X: 100, T: 0.25, r: 0.1, b: 0, v: 0.4 },
  ]) {
    const put = tree({ type: 'put', ...p });
    const call = tree({ type: 'call', ...putCallTransform(p) });
    close(put, call, 2e-3, JSON.stringify(p));
    // BS-tilnærmingene bruker transformasjonen direkte.
    close(bsAmerican2002({ type: 'put', ...p }).price, bsAmerican2002({ type: 'call', ...putCallTransform(p) }).price, 1e-12);
  }
});

test('Evigvarende opsjoner: ODE, glatt tilpasning og FD med svært lang løpetid', () => {
  const cases = [
    { type: 'put', S: 100, X: 100, r: 0.1, b: 0.02, v: 0.25 },
    { type: 'call', S: 100, X: 100, r: 0.1, b: 0.02, v: 0.25 },
    { type: 'call', S: 90, X: 100, r: 0.04, b: -0.03, v: 0.3 },
  ];
  for (const p of cases) {
    const res = perpetualAmerican(p);
    const V = (s) => perpetualAmerican({ ...p, S: s }).price;
    // ½σ²S²V'' + bSV' − rV = 0 i fortsettelsesområdet.
    const s0 = p.type === 'put' ? res.boundary * 1.3 : res.boundary * 0.7;
    const h = 1e-3 * s0;
    const d1 = (V(s0 + h) - V(s0 - h)) / (2 * h);
    const d2 = (V(s0 + h) - 2 * V(s0) + V(s0 - h)) / (h * h);
    close(0.5 * p.v * p.v * s0 * s0 * d2 + p.b * s0 * d1 - p.r * V(s0), 0, 1e-5, `ODE ${p.type}`);
    // Verdimatching og glatt tilpasning i grensen.
    const z = p.type === 'call' ? 1 : -1;
    const e = 1e-5 * res.boundary;
    close(V(res.boundary - z * e), z * (res.boundary - z * e - p.X), 1e-6, `verdimatching ${p.type}`);
    close((V(res.boundary - z * e) - V(res.boundary - 2 * z * e)) / e, 1, 1e-3, `glatt tilpasning ${p.type}`);
    // Uavhengig: Crank-Nicolson med T = 100 år.
    const fd = finiteDifference({ ...p, T: 100, method: 'cn', exercise: 'american', M: 3000, N: 1500 });
    close(fd.price, res.price, 2e-3, `FD ${p.type}`);
    // BAW og BS 1993 nærmer seg den evigvarende verdien når T vokser.
    close(bawAmerican({ ...p, T: 500 }).price, res.price, 1e-3, `BAW T=500 ${p.type}`);
  }
  close(bsAmerican1993({ type: 'call', S: 100, X: 100, T: 300, r: 0.1, b: 0.02, v: 0.25 }).price,
    perpetualAmerican({ type: 'call', S: 100, X: 100, r: 0.1, b: 0.02, v: 0.25 }).price, 1e-6);
  assert.throws(() => perpetualAmerican({ type: 'call', S: 100, X: 100, r: 0.05, b: 0.05, v: 0.2 }));
  assert.throws(() => perpetualAmerican({ type: 'put', S: 100, X: 100, r: 0, b: 0, v: 0.2 }));
});

test('Bjerksund-Stensland avviser ugyldig svært lang løpetid', () => {
  assert.throws(() => bsAmerican1993({ type: 'put', S: 100, X: 100, T: 1000, r: 0.1, b: 0.02, v: 0.25 }), /ikke gyldig/);
  assert.throws(() => bsAmerican2002({ type: 'put', S: 100, X: 100, T: 1000, r: 0.1, b: 0.02, v: 0.25 }), /ikke gyldig/);
});
