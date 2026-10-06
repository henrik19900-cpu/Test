// Seedbar tilfeldighetsgenerator (xoshiro128**) og kvasi-tilfeldige Halton-tall.
// Samme seed gir samme sekvens, så Monte Carlo-resultater og numeriske Greeks blir stabile.

import { cndInv } from './normal.js';

function splitmix32(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x9e3779b9) >>> 0;
    let z = s;
    z = Math.imul(z ^ (z >>> 16), 0x85ebca6b) >>> 0;
    z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35) >>> 0;
    return (z ^ (z >>> 16)) >>> 0;
  };
}

export function createRng(seed = 20070101) {
  const sm = splitmix32(seed);
  let a = sm();
  let b = sm();
  let c = sm();
  let d = sm();
  if ((a | b | c | d) === 0) a = 1;

  function next32() {
    const result = Math.imul(rotl(Math.imul(b, 5), 7), 9) >>> 0;
    const t = b << 9;
    c ^= a;
    d ^= b;
    b ^= c;
    a ^= d;
    c ^= t;
    d = rotl(d, 11);
    return result;
  }

  // Uniform i (0, 1) med 53 bits presisjon.
  function uniform() {
    const hi = next32() >>> 5;
    const lo = next32() >>> 6;
    return (hi * 67108864 + lo + 0.5) / 9007199254740992;
  }

  let spare = null;
  // Standardnormal via Marsaglias polarmetode.
  function normal() {
    if (spare !== null) {
      const s = spare;
      spare = null;
      return s;
    }
    let u;
    let v;
    let s;
    do {
      u = 2 * uniform() - 1;
      v = 2 * uniform() - 1;
      s = u * u + v * v;
    } while (s >= 1 || s === 0);
    const m = Math.sqrt(-2 * Math.log(s) / s);
    spare = v * m;
    return u * m;
  }

  return { uniform, normal, next32 };
}

function rotl(x, k) {
  return ((x << k) | (x >>> (32 - k))) >>> 0;
}

export const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97];

// Halton-tall nr. `index` (1, 2, 3, …) i gitt primtallsbase.
export function halton(index, base) {
  let f = 1;
  let r = 0;
  let i = index;
  while (i > 0) {
    f /= base;
    r += f * (i % base);
    i = Math.floor(i / base);
  }
  return r;
}

// Normalfordelt kvasi-tilfeldig tall fra Halton-sekvensen.
export function haltonNormal(index, base) {
  return cndInv(halton(index, base));
}
