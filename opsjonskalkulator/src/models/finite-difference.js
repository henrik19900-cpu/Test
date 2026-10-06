// Kapittel 7: Finite difference-metoder for Black-Scholes-Merton-likningen i x = ln S.
//
//   ∂V/∂τ = ½σ² ∂²V/∂x² + (b − ½σ²) ∂V/∂x − rV,   τ = tid til forfall.
//
// method = 'explicit' | 'implicit' | 'cn' (Crank-Nicolson). Gitteret er jevnt i ln S med
// dagens spot på en node. Startbetingelsen er cellemiddelet av utbetalingen, som gjør prisen
// glatt i S. Crank-Nicolson starter med to implisitte halvsteg (Rannacher) for å dempe
// svingninger fra knekken i utbetalingen. Amerikanske opsjoner løses med Brennan-Schwartz
// (eksakt projeksjon i den tridiagonale løsningen); den eksplisitte metoden tar maks med
// innløsningsverdien etter hvert steg. Den eksplisitte metoden øker antall tidssteg
// automatisk til stabilitetskravet Δt ≤ 0,9 / (σ²/Δx² + |r|) er oppfylt.

import { isCall } from './bsm.js';
import { isAmerican } from './lattice.js';

function cellAverage(call, X, a, c) {
  const lx = Math.log(X);
  const w = c - a;
  if (call) {
    if (c <= lx) return 0;
    const lo = Math.max(a, lx);
    return (Math.exp(c) - Math.exp(lo) - X * (c - lo)) / w;
  }
  if (a >= lx) return 0;
  const hi = Math.min(c, lx);
  return (X * (hi - a) - (Math.exp(hi) - Math.exp(a))) / w;
}

export function finiteDifference({
  method = 'cn', type = 'call', exercise = 'american', S, X, T, r, b, v, M = 200, N = 200,
}) {
  if (!(S > 0) || !(X > 0)) throw new Error('Spot og innløsningskurs må være positive.');
  if (!(T > 0)) throw new Error('Tid til forfall må være positiv.');
  if (!(v > 0)) throw new Error('Volatiliteten må være positiv.');
  if (!Number.isInteger(M) || M < 10 || M > 20000) throw new Error('Antall prissteg må være et heltall mellom 10 og 20000.');
  if (!Number.isInteger(N) || N < 1 || N > 200000) throw new Error('Antall tidssteg må være et heltall mellom 1 og 200000.');
  if (!['explicit', 'implicit', 'cn'].includes(method)) throw new Error(`Ukjent metode: ${method}`);
  const call = isCall(type);
  const american = isAmerican(exercise);
  if (M % 2 === 1) M += 1;
  const half = M / 2;

  // Bredden dekker både ±6 standardavvik og avstanden til innløsningskursen (glatt i S og X).
  const sd = v * Math.sqrt(T);
  const L = Math.sqrt((6 * sd) ** 2 + (2 * Math.log(X / S)) ** 2);
  const dx = 2 * L / M;
  const x0 = Math.log(S) - half * dx;
  const xs = new Float64Array(M + 1);
  const Sg = new Float64Array(M + 1);
  for (let i = 0; i <= M; i++) {
    xs[i] = x0 + i * dx;
    Sg[i] = Math.exp(xs[i]);
  }
  const z = call ? 1 : -1;
  const exercisePayoff = new Float64Array(M + 1);
  for (let i = 0; i <= M; i++) exercisePayoff[i] = Math.max(z * (Sg[i] - X), 0);

  let V = new Float64Array(M + 1);
  for (let i = 1; i < M; i++) V[i] = cellAverage(call, X, xs[i] - dx / 2, xs[i] + dx / 2);
  V[0] = exercisePayoff[0];
  V[M] = exercisePayoff[M];

  const nu = b - 0.5 * v * v;
  const alpha = v * v / (2 * dx * dx) - nu / (2 * dx);
  const beta = -v * v / (dx * dx) - r;
  const gamma = v * v / (2 * dx * dx) + nu / (2 * dx);

  let steps = N;
  if (method === 'explicit') {
    const dtMax = 0.9 / (v * v / (dx * dx) + Math.abs(r));
    steps = Math.max(N, Math.ceil(T / dtMax));
  }
  if (steps * M > 1e8) {
    throw new Error(method === 'explicit'
      ? 'Den eksplisitte metoden krever for mange tidssteg med så mange prissteg; reduser antall prissteg M.'
      : 'Gitteret er for stort (antall prissteg × tidssteg); reduser M eller N.');
  }
  const dt = T / steps;

  const boundary = (tau) => {
    const Smin = Sg[0];
    const Smax = Sg[M];
    const carry = Math.exp((b - r) * tau);
    const disc = Math.exp(-r * tau);
    let lo;
    let hi;
    if (call) {
      lo = 0;
      hi = Math.max(Smax * carry - X * disc, 0);
      if (american) hi = Math.max(hi, Smax - X);
    } else {
      lo = Math.max(X * disc - Smin * carry, 0);
      if (american) lo = Math.max(lo, X - Smin);
      hi = 0;
    }
    return [lo, hi];
  };

  // Ett θ-steg med lengde h fra tid τ til τ + h.
  const work = { rhs: new Float64Array(M + 1), cp: new Float64Array(M + 1), rp: new Float64Array(M + 1) };
  const thetaStep = (Vold, h, theta, tauNew) => {
    const Vn = new Float64Array(M + 1);
    const [lo, hi] = boundary(tauNew);
    Vn[0] = lo;
    Vn[M] = hi;
    const e = 1 - theta;
    const { rhs, cp, rp } = work;
    for (let i = 1; i < M; i++) {
      rhs[i] = Vold[i] + e * h * (alpha * Vold[i - 1] + beta * Vold[i] + gamma * Vold[i + 1]);
    }
    if (theta === 0) {
      for (let i = 1; i < M; i++) Vn[i] = american ? Math.max(rhs[i], exercisePayoff[i]) : rhs[i];
      return Vn;
    }
    const a = -theta * h * alpha;
    const d = 1 - theta * h * beta;
    const c = -theta * h * gamma;
    rhs[1] -= a * lo;
    rhs[M - 1] -= c * hi;
    if (american && !call) {
      // Brennan-Schwartz for put: eliminer ovenfra, substituer nedenfra med projeksjon.
      cp[M - 1] = a / d;
      rp[M - 1] = rhs[M - 1] / d;
      for (let i = M - 2; i >= 1; i--) {
        const m = d - c * cp[i + 1];
        cp[i] = a / m;
        rp[i] = (rhs[i] - c * rp[i + 1]) / m;
      }
      // Randverdien lo ligger allerede i rhs[1], så substitusjonen starter fra 0.
      let prev = 0;
      for (let i = 1; i < M; i++) {
        let val = rp[i] - cp[i] * prev;
        if (val < exercisePayoff[i]) val = exercisePayoff[i];
        Vn[i] = val;
        prev = val;
      }
      return Vn;
    }
    // Thomas-algoritmen (for amerikansk call: Brennan-Schwartz med projeksjon ovenfra).
    cp[1] = c / d;
    rp[1] = rhs[1] / d;
    for (let i = 2; i < M; i++) {
      const m = d - a * cp[i - 1];
      cp[i] = c / m;
      rp[i] = (rhs[i] - a * rp[i - 1]) / m;
    }
    // Randverdien hi ligger allerede i rhs[M − 1].
    let next = 0;
    for (let i = M - 1; i >= 1; i--) {
      let val = rp[i] - cp[i] * next;
      if (american && val < exercisePayoff[i]) val = exercisePayoff[i];
      Vn[i] = val;
      next = val;
    }
    return Vn;
  };

  const theta = method === 'explicit' ? 0 : method === 'implicit' ? 1 : 0.5;
  let tau = 0;
  let Vprev = V;
  for (let k = 0; k < steps; k++) {
    Vprev = V;
    if (method === 'cn' && k === 0) {
      V = thetaStep(V, dt / 2, 1, dt / 2);
      V = thetaStep(V, dt / 2, 1, dt);
    } else {
      V = thetaStep(V, dt, theta, tau + dt);
    }
    tau += dt;
  }

  const i0 = half;
  const Sm = Sg[i0 - 1];
  const Sp = Sg[i0 + 1];
  const price = V[i0];
  const delta = (V[i0 + 1] - V[i0 - 1]) / (Sp - Sm);
  const gammaS = 2 * ((V[i0 + 1] - V[i0]) / (Sp - S) - (V[i0] - V[i0 - 1]) / (S - Sm)) / (Sp - Sm);
  const thetaT = (Vprev[i0] - price) / dt;
  return { price, delta, gamma: gammaS, theta: thetaT, steps, M, dx, Smin: Sg[0], Smax: Sg[M] };
}
