// Kapittel 7: Trær.
//
//   crrTree             Cox, Ross og Rubinstein (1979) binomialtre med delta, gamma og theta fra treet
//   binomialTree        generelt binomialtre: 'crr', 'rb' (Rendleman og Bartter 1979), 'lr' (Leisen og Reimer 1996)
//   trinomialTree       Boyle (1986) trinomialtre med delta, gamma og theta
//   threeDimTree        Rubinstein (1994) tredimensjonalt binomialtre for to aktiva
//   dermanKaniTree      Derman og Kani (1994) implisitt binomialtre med lineær volatilitetsskjevhet
//
// Notasjon som i Haug. exercise = 'american' | 'european'. Theta er per år når kalendertiden går.

import { cbnd } from '../math/normal.js';
import { gbsm, isCall } from './bsm.js';

export function isAmerican(exercise) {
  if (exercise === 'american' || exercise === 'a') return true;
  if (exercise === 'european' || exercise === 'e') return false;
  throw new Error(`Ukjent innløsningstype: ${exercise}`);
}

function checkSteps(n, min = 3, max = 20000) {
  if (!Number.isInteger(n) || n < min) throw new Error(`Antall tidssteg må være et heltall på minst ${min}.`);
  if (n > max) throw new Error(`Antall tidssteg kan være høyst ${max}.`);
}

function checkBasic({ S, X, T, v }) {
  if (!(S > 0) || !(X > 0)) throw new Error('Spot og innløsningskurs må være positive.');
  if (!(T > 0)) throw new Error('Tid til forfall må være positiv.');
  if (!(v > 0)) throw new Error('Volatiliteten må være positiv.');
}

// Felles motor for rekombinerende binomialtrær med konstante u, d og p.
// Node (j, i) har kurs S·u^i·d^(j−i). Returnerer pris og verdiene på nivå 1 og 2.
function binomialEngine({ call, american, S, X, n, u, d, p, df }) {
  if (!(p >= 0 && p <= 1)) {
    throw new Error('Sannsynligheten i treet havner utenfor [0, 1]. Øk antall tidssteg eller endre parametrene.');
  }
  const z = call ? 1 : -1;
  const pu = df * p;
  const pd = df * (1 - p);
  const ratio = u / d;
  const V = new Float64Array(n + 1);
  let s = S * d ** n;
  for (let i = 0; i <= n; i++) {
    V[i] = Math.max(z * (s - X), 0);
    s *= ratio;
  }
  const lvl = [null, null, null];
  for (let j = n - 1; j >= 0; j--) {
    s = S * d ** j;
    for (let i = 0; i <= j; i++) {
      let val = pu * V[i + 1] + pd * V[i];
      if (american) {
        const ex = z * (s - X);
        if (ex > val) val = ex;
      }
      V[i] = val;
      s *= ratio;
    }
    if (j <= 2) lvl[j] = Array.from(V.subarray(0, j + 1));
  }
  return { price: V[0], lvl };
}

function treeGreeks(S, u, d, lvl, dt, withTheta) {
  const [f10, f11] = lvl[1];
  const [f20, f21, f22] = lvl[2];
  const Suu = S * u * u;
  const Sud = S * u * d;
  const Sdd = S * d * d;
  const delta = (f11 - f10) / (S * u - S * d);
  const gamma = ((f22 - f21) / (Suu - Sud) - (f21 - f20) / (Sud - Sdd)) / (0.5 * (Suu - Sdd));
  const out = { delta, gamma };
  if (withTheta) out.theta = (f21 - lvl[0][0]) / (2 * dt);
  return out;
}

// Cox-Ross-Rubinstein: u = e^{σ√Δt}, d = 1/u, p = (e^{bΔt} − d)/(u − d).
export function crrTree({ type = 'call', exercise = 'american', S, X, T, r, b, v, n = 100 }) {
  checkBasic({ S, X, T, v });
  checkSteps(n);
  const dt = T / n;
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp(b * dt) - d) / (u - d);
  const { price, lvl } = binomialEngine({
    call: isCall(type), american: isAmerican(exercise), S, X, n, u, d, p, df: Math.exp(-r * dt),
  });
  return { price, ...treeGreeks(S, u, d, lvl, dt, true), u, d, p, dt };
}

// Leisen-Reimer: Peizer-Pratt-invertering (metode 2) av normalfordelingen. Krever odde n.
function peizerPratt(z, n) {
  const t = z / (n + 1 / 3 + 0.1 / (n + 1));
  return 0.5 + Math.sign(z) * Math.sqrt(0.25 - 0.25 * Math.exp(-t * t * (n + 1 / 6)));
}

export function binomialTree({ method = 'crr', type = 'call', exercise = 'american', S, X, T, r, b, v, n = 100 }) {
  checkBasic({ S, X, T, v });
  checkSteps(n);
  if (method === 'crr') return crrTree({ type, exercise, S, X, T, r, b, v, n });
  let u;
  let d;
  let p;
  let steps = n;
  if (method === 'rb') {
    const dt = T / steps;
    const m = (b - 0.5 * v * v) * dt;
    u = Math.exp(m + v * Math.sqrt(dt));
    d = Math.exp(m - v * Math.sqrt(dt));
    p = 0.5;
  } else if (method === 'lr') {
    if (steps % 2 === 0) steps += 1;
    const dt = T / steps;
    const sq = v * Math.sqrt(T);
    const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / sq;
    const d2 = d1 - sq;
    p = peizerPratt(d2, steps);
    const pp = peizerPratt(d1, steps);
    const a = Math.exp(b * dt);
    u = a * pp / p;
    d = (a - p * u) / (1 - p);
  } else {
    throw new Error(`Ukjent tretype: ${method}`);
  }
  const dt = T / steps;
  const { price, lvl } = binomialEngine({
    call: isCall(type), american: isAmerican(exercise), S, X, n: steps, u, d, p, df: Math.exp(-r * dt),
  });
  return { price, ...treeGreeks(S, u, d, lvl, dt, false), u, d, p, steps };
}

// Boyle (1986) trinomialtre slik Haug presenterer det:
// u = e^{σ√(2Δt)}, pu = ((e^{bΔt/2} − e^{−σ√(Δt/2)}) / (e^{σ√(Δt/2)} − e^{−σ√(Δt/2)}))², pd tilsvarende.
export function trinomialTree({ type = 'call', exercise = 'american', S, X, T, r, b, v, n = 100 }) {
  checkBasic({ S, X, T, v });
  checkSteps(n, 2);
  const call = isCall(type);
  const american = isAmerican(exercise);
  const dt = T / n;
  const u = Math.exp(v * Math.sqrt(2 * dt));
  const d = 1 / u;
  const eb = Math.exp(b * dt / 2);
  const ev = Math.exp(v * Math.sqrt(dt / 2));
  const evm = 1 / ev;
  const pu = ((eb - evm) / (ev - evm)) ** 2;
  const pd = ((ev - eb) / (ev - evm)) ** 2;
  const pm = 1 - pu - pd;
  if (!(pu >= 0 && pd >= 0 && pm >= 0)) {
    throw new Error('Sannsynlighetene i treet havner utenfor [0, 1]. Øk antall tidssteg eller endre parametrene.');
  }
  const df = Math.exp(-r * dt);
  const z = call ? 1 : -1;
  const V = new Float64Array(2 * n + 1);
  let s = S * d ** n;
  for (let i = 0; i <= 2 * n; i++) {
    V[i] = Math.max(z * (s - X), 0);
    s *= u;
  }
  const lvl = [null, null];
  for (let j = n - 1; j >= 0; j--) {
    s = S * d ** j;
    for (let i = 0; i <= 2 * j; i++) {
      let val = df * (pu * V[i + 2] + pm * V[i + 1] + pd * V[i]);
      if (american) {
        const ex = z * (s - X);
        if (ex > val) val = ex;
      }
      V[i] = val;
      s *= u;
    }
    if (j <= 1) lvl[j] = Array.from(V.subarray(0, 2 * j + 1));
  }
  const [f10, f11, f12] = lvl[1];
  const price = lvl[0][0];
  return {
    price,
    delta: (f12 - f10) / (S * u - S * d),
    gamma: ((f12 - f11) / (S * u - S) - (f11 - f10) / (S - S * d)) / (0.5 * (S * u - S * d)),
    theta: (f11 - price) / dt,
    pu, pm, pd, u,
  };
}

// ---------------------------------------------------------------------------
// Tredimensjonalt binomialtre (Rubinstein 1994)
// ---------------------------------------------------------------------------

export const THREE_DIM_PAYOFFS = {
  spread: 'Spreadopsjon: max(0, Q1·S1 − Q2·S2 − X1)',
  max: 'Opsjon på maksimum: max(0, max(Q1·S1, Q2·S2) − X1)',
  min: 'Opsjon på minimum: max(0, min(Q1·S1, Q2·S2) − X1)',
  dual: 'Dual strike: max(0, Q1·S1 − X1, Q2·S2 − X2)',
  reverse: 'Omvendt dual strike: max(0, Q1·S1 − X1, X2 − Q2·S2)',
  portfolio: 'Porteføljeopsjon: max(0, Q1·S1 + Q2·S2 − X1)',
  exchange: 'Bytteopsjon: max(0, Q2·S2 − Q1·S1)',
  outperformance: 'Relativ avkastning: max(0, Q1·S1 / (Q2·S2) − X1)',
  product: 'Produktopsjon: max(0, Q1·S1·Q2·S2 − X1)',
};

// Utbetaling for to aktiva. For put byttes fortegnet (dual strike: X1 − Q1·S1 og X2 − Q2·S2,
// omvendt dual strike: X1 − Q1·S1 og Q2·S2 − X2). Bytteopsjonen har samme utbetaling for begge.
export function twoAssetPayoff(kind, call, { Q1 = 1, Q2 = 1, X1, X2 }) {
  const z = call ? 1 : -1;
  switch (kind) {
    case 'spread': return (s1, s2) => Math.max(0, z * (Q1 * s1 - Q2 * s2 - X1));
    case 'max': return (s1, s2) => Math.max(0, z * (Math.max(Q1 * s1, Q2 * s2) - X1));
    case 'min': return (s1, s2) => Math.max(0, z * (Math.min(Q1 * s1, Q2 * s2) - X1));
    case 'dual': return call
      ? (s1, s2) => Math.max(0, Q1 * s1 - X1, Q2 * s2 - X2)
      : (s1, s2) => Math.max(0, X1 - Q1 * s1, X2 - Q2 * s2);
    case 'reverse': return call
      ? (s1, s2) => Math.max(0, Q1 * s1 - X1, X2 - Q2 * s2)
      : (s1, s2) => Math.max(0, X1 - Q1 * s1, Q2 * s2 - X2);
    case 'portfolio': return (s1, s2) => Math.max(0, z * (Q1 * s1 + Q2 * s2 - X1));
    case 'exchange': return (s1, s2) => Math.max(0, Q2 * s2 - Q1 * s1);
    case 'outperformance': return (s1, s2) => Math.max(0, z * (Q1 * s1 / (Q2 * s2) - X1));
    case 'product': return (s1, s2) => Math.max(0, z * (Q1 * s1 * Q2 * s2 - X1));
    default: throw new Error(`Ukjent utbetalingstype: ${kind}`);
  }
}

// Margrabe (1978): retten til å bytte Q1 enheter av S1 mot Q2 enheter av S2, max(Q2·S2 − Q1·S1, 0).
export function margrabe({ S1, S2, Q1 = 1, Q2 = 1, T, r, b1, b2, v1, v2, rho }) {
  const vr = Math.sqrt(Math.max(v1 * v1 + v2 * v2 - 2 * rho * v1 * v2, 0));
  return gbsm({ type: 'call', S: Q2 * S2, X: Q1 * S1, T, r: r - b1, b: b2 - b1, v: vr });
}

// Stulz (1982): call/put på maksimum eller minimum av Q1·S1 og Q2·S2 med innløsningskurs X.
export function stulzMinMax({ kind = 'max', type = 'call', S1, S2, Q1 = 1, Q2 = 1, X, T, r, b1, b2, v1, v2, rho }) {
  const A = Q1 * S1;
  const B = Q2 * S2;
  const sq = Math.sqrt(T);
  const vr = Math.sqrt(Math.max(v1 * v1 + v2 * v2 - 2 * rho * v1 * v2, 1e-300));
  const rho1 = (v1 - rho * v2) / vr;
  const rho2 = (v2 - rho * v1) / vr;
  const c1 = Math.exp((b1 - r) * T);
  const c2 = Math.exp((b2 - r) * T);
  const disc = Math.exp(-r * T);
  const d = (Math.log(A / B) + (b1 - b2 + vr * vr / 2) * T) / (vr * sq);
  const callAt = (K) => {
    if (!(K > 0)) {
      // Verdien av max/min selv: min = A − (A − B)+, max = B + (A − B)+.
      const ex = gbsm({ type: 'call', S: A, X: B, T, r: r - b2, b: b1 - b2, v: vr });
      return kind === 'min' ? A * c1 - ex : B * c2 + ex;
    }
    const y1 = (Math.log(A / K) + (b1 + v1 * v1 / 2) * T) / (v1 * sq);
    const y2 = (Math.log(B / K) + (b2 + v2 * v2 / 2) * T) / (v2 * sq);
    if (kind === 'min') {
      return A * c1 * cbnd(y1, -d, -rho1) + B * c2 * cbnd(y2, d - vr * sq, -rho2)
        - K * disc * cbnd(y1 - v1 * sq, y2 - v2 * sq, rho);
    }
    return A * c1 * cbnd(y1, d, rho1) + B * c2 * cbnd(y2, -d + vr * sq, rho2)
      - K * disc * (1 - cbnd(-y1 + v1 * sq, -y2 + v2 * sq, rho));
  };
  if (kind !== 'min' && kind !== 'max') throw new Error(`Ukjent type: ${kind}`);
  const call = callAt(X);
  if (isCall(type)) return call;
  return X * disc - callAt(0) + call;
}

// Fire grener med sannsynlighet 1/4: S1 → S1·e^{μ1Δt ± σ1√Δt},
// S2 → S2·e^{μ2Δt + σ2√Δt(±ρ ± √(1−ρ²))}, μi = bi − σi²/2.
export function threeDimTree({
  type = 'call', exercise = 'european', payoff = 'spread', S1, S2, Q1 = 1, Q2 = 1, X1 = 0, X2 = 0,
  T, r, b1, b2, v1, v2, rho, n = 100,
}) {
  if (!(S1 > 0) || !(S2 > 0)) throw new Error('Spotprisene må være positive.');
  if (!(T > 0)) throw new Error('Tid til forfall må være positiv.');
  if (!(v1 > 0) || !(v2 > 0)) throw new Error('Volatilitetene må være positive.');
  if (!(rho >= -1 && rho <= 1)) throw new Error('Korrelasjonen må ligge mellom −1 og 1.');
  checkSteps(n, 2, 1000);
  const call = isCall(type);
  const american = isAmerican(exercise);
  const f = twoAssetPayoff(payoff, call, { Q1, Q2, X1, X2 });
  const dt = T / n;
  const sq = Math.sqrt(dt);
  const mu1 = (b1 - 0.5 * v1 * v1) * dt;
  const mu2 = (b2 - 0.5 * v2 * v2) * dt;
  const c = Math.sqrt(Math.max(0, 1 - rho * rho));
  const a1 = Math.exp(2 * v1 * sq); // faktor per ekstra opptur i aktivum 1
  const a2r = Math.exp(2 * v2 * sq * rho); // S2-faktor per opptur i aktivum 1
  const a2c = Math.exp(2 * v2 * sq * c); // S2-faktor per opptur i den uavhengige komponenten
  const w = n + 1;
  const V = new Float64Array(w * w);
  const level = (j) => {
    const base1 = S1 * Math.exp(j * mu1 - j * v1 * sq);
    const base2 = S2 * Math.exp(j * mu2 - j * v2 * sq * (rho + c));
    return [base1, base2];
  };
  {
    const [base1, base2] = level(n);
    let s1 = base1;
    let s2row = base2;
    for (let i = 0; i <= n; i++) {
      let s2 = s2row;
      for (let k = 0; k <= n; k++) {
        V[i * w + k] = f(s1, s2);
        s2 *= a2c;
      }
      s1 *= a1;
      s2row *= a2r;
    }
  }
  const q = 0.25 * Math.exp(-r * dt);
  for (let j = n - 1; j >= 0; j--) {
    const [base1, base2] = level(j);
    let s1 = base1;
    let s2row = base2;
    for (let i = 0; i <= j; i++) {
      let s2 = s2row;
      const row = i * w;
      const up = row + w;
      for (let k = 0; k <= j; k++) {
        let val = q * (V[up + k + 1] + V[up + k] + V[row + k + 1] + V[row + k]);
        if (american) {
          const ex = f(s1, s2);
          if (ex > val) val = ex;
        }
        V[row + k] = val;
        s2 *= a2c;
      }
      s1 *= a1;
      s2row *= a2r;
    }
  }
  return { price: V[0] };
}

// ---------------------------------------------------------------------------
// Implisitt binomialtre (Derman og Kani 1994)
// ---------------------------------------------------------------------------

// Implisitt volatilitet som lineær funksjon av innløsningskursen: σ(K) = σ + skew·(K − S),
// avgrenset nedad til 1 % slik at den alltid er positiv.
export function linearSkewVol(K, S, v, skew) {
  return Math.max(0.01, v + skew * (K - S));
}

// Europeisk opsjon i et CRR-tre med m steg à Δt, regnet som binomisk sum (O(m)).
export function crrEuropeanSum(call, S, K, m, dt, r, b, v) {
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const p = (Math.exp(b * dt) - d) / (u - d);
  if (!(p > 0 && p < 1)) {
    throw new Error('Sannsynligheten i treet havner utenfor (0, 1). Øk antall steg eller endre parametrene.');
  }
  const lp = Math.log(p);
  const lq = Math.log(1 - p);
  let logC = 0;
  let sum = 0;
  for (let k = 0; k <= m; k++) {
    if (k > 0) logC += Math.log((m - k + 1) / k);
    const s = S * u ** (2 * k - m);
    const pay = call ? s - K : K - s;
    if (pay > 0) sum += Math.exp(logC + k * lp + (m - k) * lq) * pay;
  }
  return Math.exp(-r * m * dt) * sum;
}

// Bygger treet nivå for nivå fra europeiske opsjonspriser og Arrow-Debreu-priser. Som hos
// Derman og Kani prises opsjonene i et CRR-tre med samme tidssteg og volatiliteten σ(K), slik at
// flat volatilitet gir nøyaktig CRR-treet. Nivå i har i+1 noder (stigende). Returnerer
// nodeprisene, overgangssannsynlighetene og antall noder som måtte overstyres (arbitrasjekontroll).
export function buildDermanKani({ S, T, r, b, v, skew = 0, n = 5 }) {
  if (!(S > 0)) throw new Error('Spotprisen må være positiv.');
  if (!(T > 0)) throw new Error('Tid til forfall må være positiv.');
  if (!(v > 0)) throw new Error('Volatiliteten må være positiv.');
  checkSteps(n, 1, 150);
  const dt = T / n;
  const growth = Math.exp(b * dt);
  const er = Math.exp(r * dt);
  const nodes = [[S]];
  const probs = [];
  let lambda = [1];
  let overrides = 0;
  const price = (call, K, steps) => crrEuropeanSum(call, S, K, steps, dt, r, b, linearSkewVol(K, S, v, skew));

  for (let i = 0; i < n; i++) {
    const s = nodes[i];
    const m = i + 1; // antall noder på nivå i
    const F = s.map((x) => x * growth);
    const t = i + 1; // antall CRR-steg til forfallet for opsjonene på dette nivået
    const next = new Float64Array(m + 1);
    // Summer av λ(F − K) over noder over/under en gitt node.
    const sumAbove = (j, K) => {
      let acc = 0;
      for (let k = j + 1; k < m; k++) acc += lambda[k] * (F[k] - K);
      return acc;
    };
    const sumBelow = (j, K) => {
      let acc = 0;
      for (let k = 0; k < j; k++) acc += lambda[k] * (K - F[k]);
      return acc;
    };
    const spacing = (j) => (j > 0 ? s[j] / s[j - 1] : (j + 1 < m ? s[j + 1] / s[j] : Math.exp(2 * v * Math.sqrt(dt))));
    // Øvre node fra nedre node via call med strike s[j].
    const upper = (j, lower) => {
      const B = er * price(true, s[j], t) - sumAbove(j, s[j]);
      const A = lambda[j] * (F[j] - lower);
      let up = (B * lower - A * s[j]) / (B - A);
      const hi = j + 1 < m ? F[j + 1] : Infinity;
      if (!(up > F[j] && up < hi)) {
        overrides++;
        up = lower * spacing(j);
        if (!(up > F[j] && up < hi)) up = Number.isFinite(hi) ? 0.5 * (F[j] + hi) : F[j] * spacing(j);
      }
      return up;
    };
    // Nedre node fra øvre node via put med strike s[j].
    const lowerOf = (j, up) => {
      const B = er * price(false, s[j], t) - sumBelow(j, s[j]);
      const A = lambda[j] * (up - F[j]);
      let lo = (B * up - A * s[j]) / (B - A);
      const loBound = j > 0 ? F[j - 1] : 0;
      if (!(lo < F[j] && lo > loBound)) {
        overrides++;
        lo = up / spacing(j);
        if (!(lo < F[j] && lo > loBound)) lo = j > 0 ? 0.5 * (F[j] + loBound) : F[j] / spacing(j);
      }
      return lo;
    };

    if (m % 2 === 1) {
      // Nivå i+1 har et partall noder: de to midterste rundt S med s_øvre·s_nedre = S².
      const c = (m - 1) / 2;
      const C = er * price(true, S, t);
      const sig = sumAbove(c, S);
      let up = S * (C + lambda[c] * S - sig) / (lambda[c] * F[c] - C + sig);
      let lo = S * S / up;
      if (!(up > F[c] && lo < F[c] && (c + 1 >= m || up < F[c + 1]) && (c === 0 || lo > F[c - 1]))) {
        overrides++;
        up = S * Math.exp(v * Math.sqrt(dt));
        lo = S * S / up;
      }
      next[c] = lo;
      next[c + 1] = up;
      for (let j = c + 1; j < m; j++) next[j + 1] = upper(j, next[j]);
      for (let j = c - 1; j >= 0; j--) next[j] = lowerOf(j, next[j + 1]);
    } else {
      // Nivå i+1 har et oddetall noder: midtnoden settes lik dagens spot.
      const c = m / 2; // indeks for midtnoden på nivå i+1
      next[c] = S;
      for (let j = c; j < m; j++) next[j + 1] = upper(j, next[j]);
      for (let j = c - 1; j >= 0; j--) next[j] = lowerOf(j, next[j + 1]);
    }

    const p = new Float64Array(m);
    for (let j = 0; j < m; j++) p[j] = (F[j] - next[j]) / (next[j + 1] - next[j]);
    const lam = new Float64Array(m + 1);
    for (let j = 0; j < m; j++) {
      lam[j] += lambda[j] * (1 - p[j]) / er;
      lam[j + 1] += lambda[j] * p[j] / er;
    }
    nodes.push(Array.from(next));
    probs.push(Array.from(p));
    lambda = Array.from(lam);
  }
  return { nodes, probs, lambda, overrides, dt };
}

// Prising på det implisitte treet med bakoverinduksjon.
export function dermanKaniTree({ type = 'call', exercise = 'european', S, X, T, r, b, v, skew = 0, n = 5 }) {
  if (!(X > 0)) throw new Error('Innløsningskursen må være positiv.');
  const tree = buildDermanKani({ S, T, r, b, v, skew, n });
  const call = isCall(type);
  const american = isAmerican(exercise);
  const z = call ? 1 : -1;
  const df = Math.exp(-r * tree.dt);
  let V = tree.nodes[n].map((s) => Math.max(z * (s - X), 0));
  for (let i = n - 1; i >= 0; i--) {
    const p = tree.probs[i];
    const s = tree.nodes[i];
    V = s.map((si, j) => {
      const cont = df * (p[j] * V[j + 1] + (1 - p[j]) * V[j]);
      return american ? Math.max(cont, z * (si - X)) : cont;
    });
  }
  const s1 = tree.nodes[1];
  const p0 = tree.probs[0][0];
  const localVol0 = Math.sqrt(p0 * (1 - p0)) * Math.log(s1[1] / s1[0]) / Math.sqrt(tree.dt);
  return { price: V[0], tree, localVol0, impliedVolAtX: linearSkewVol(X, S, v, skew) };
}
