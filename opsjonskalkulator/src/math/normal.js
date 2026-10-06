// Standardnormalfordelingen.
//   nd(x)        tetthet n(x)
//   cnd(x)       kumulativ N(x), Hart (1968) i Wests (2005) dobbeltpresisjonsversjon
//   cndInv(p)    invers N^-1(p), Acklam med ett Halley-steg
//   cbnd(a,b,ρ)  bivariat kumulativ M(a,b;ρ) = P(X ≤ a, Y ≤ b), Genz (2004)

const SQRT2PI = Math.sqrt(2 * Math.PI);

export function nd(x) {
  return Math.exp(-0.5 * x * x) / SQRT2PI;
}

export function cnd(x) {
  if (Number.isNaN(x)) return NaN;
  const xa = Math.abs(x);
  let c;
  if (xa > 37) {
    c = 0;
  } else {
    const e = Math.exp(-0.5 * xa * xa);
    if (xa < 7.07106781186547) {
      let b = 3.52624965998911e-2 * xa + 0.700383064443688;
      b = b * xa + 6.37396220353165;
      b = b * xa + 33.912866078383;
      b = b * xa + 112.079291497871;
      b = b * xa + 221.213596169931;
      b = b * xa + 220.206867912376;
      c = e * b;
      b = 8.83883476483184e-2 * xa + 1.75566716318264;
      b = b * xa + 16.064177579207;
      b = b * xa + 86.7807322029461;
      b = b * xa + 296.564248779674;
      b = b * xa + 637.333633378831;
      b = b * xa + 793.826512519948;
      b = b * xa + 440.413735824752;
      c /= b;
    } else {
      let b = xa + 0.65;
      b = xa + 4 / b;
      b = xa + 3 / b;
      b = xa + 2 / b;
      b = xa + 1 / b;
      c = e / b / 2.506628274631;
    }
  }
  return x > 0 ? 1 - c : c;
}

const A = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
const B = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
const C = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
const D = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];

export function cndInv(p) {
  if (!(p > 0 && p < 1)) {
    if (p === 0) return -Infinity;
    if (p === 1) return Infinity;
    return NaN;
  }
  const pLow = 0.02425;
  let x;
  if (p < pLow) {
    const q = Math.sqrt(-2 * Math.log(p));
    x = (((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5]) /
      ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
  } else if (p <= 1 - pLow) {
    const q = p - 0.5;
    const r = q * q;
    x = (((((A[0] * r + A[1]) * r + A[2]) * r + A[3]) * r + A[4]) * r + A[5]) * q /
      (((((B[0] * r + B[1]) * r + B[2]) * r + B[3]) * r + B[4]) * r + 1);
  } else {
    const q = Math.sqrt(-2 * Math.log(1 - p));
    x = -(((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5]) /
      ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
  }
  // Ett Halley-steg gir full dobbel presisjon.
  const e = (p < 0.5 ? cnd(x) - p : (1 - p) - cnd(-x));
  const u = e * SQRT2PI * Math.exp(0.5 * x * x);
  return x - u / (1 + 0.5 * x * u);
}

// Gauss-Legendre-noder og vekter (halvdelen; symmetriske) for 3, 6 og 10 punkter.
const GL_W = [
  [0.17132449237917, 0.360761573048138, 0.46791393457269],
  [4.71753363865118e-2, 0.106939325995318, 0.160078328543346, 0.203167426723066, 0.233492536538355, 0.249147045813403],
  [1.76140071391521e-2, 4.06014298003869e-2, 6.26720483341091e-2, 8.32767415767048e-2, 0.10193011981724,
    0.118194531961518, 0.131688638449177, 0.142096109318382, 0.149172986472604, 0.152753387130726],
];
const GL_X = [
  [-0.932469514203152, -0.661209386466265, -0.238619186083197],
  [-0.981560634246719, -0.904117256370475, -0.769902674194305, -0.587317954286617, -0.36783149899818, -0.125233408511469],
  [-0.993128599185095, -0.963971927277914, -0.912234428251326, -0.839116971822219, -0.746331906460151,
    -0.636053680726515, -0.510867001950827, -0.37370608871542, -0.227785851141645, -7.65265211334973e-2],
];

export function cbnd(x, y, rho) {
  if (Number.isNaN(x) || Number.isNaN(y) || Number.isNaN(rho)) return NaN;
  if (rho >= 1) return cnd(Math.min(x, y));
  if (rho <= -1) return Math.max(0, cnd(x) + cnd(y) - 1);
  if (x === -Infinity || y === -Infinity) return 0;
  if (x === Infinity) return cnd(y);
  if (y === Infinity) return cnd(x);

  const ar = Math.abs(rho);
  const ng = ar < 0.3 ? 0 : ar < 0.75 ? 1 : 2;
  const w = GL_W[ng];
  const xs = GL_X[ng];
  const lg = w.length;

  let h = -x;
  let k = -y;
  let hk = h * k;
  let bvn = 0;

  if (ar < 0.925) {
    if (ar > 0) {
      const hs = (h * h + k * k) / 2;
      const asr = Math.asin(rho);
      for (let i = 0; i < lg; i++) {
        for (const is of [-1, 1]) {
          const sn = Math.sin(asr * (is * xs[i] + 1) / 2);
          bvn += w[i] * Math.exp((sn * hk - hs) / (1 - sn * sn));
        }
      }
      bvn = bvn * asr / (4 * Math.PI);
    }
    bvn += cnd(-h) * cnd(-k);
  } else {
    if (rho < 0) {
      k = -k;
      hk = -hk;
    }
    const as = (1 - rho) * (1 + rho);
    let a = Math.sqrt(as);
    const bs = (h - k) * (h - k);
    const c = (4 - hk) / 8;
    const d = (12 - hk) / 16;
    let asr = -(bs / as + hk) / 2;
    if (asr > -100) {
      bvn = a * Math.exp(asr) * (1 - c * (bs - as) * (1 - d * bs / 5) / 3 + c * d * as * as / 5);
    }
    if (-hk < 100) {
      const bb = Math.sqrt(bs);
      bvn -= Math.exp(-hk / 2) * SQRT2PI * cnd(-bb / a) * bb * (1 - c * bs * (1 - d * bs / 5) / 3);
    }
    a /= 2;
    for (let i = 0; i < lg; i++) {
      for (const is of [-1, 1]) {
        const xx = (a * (is * xs[i] + 1)) ** 2;
        const rs = Math.sqrt(1 - xx);
        asr = -(bs / xx + hk) / 2;
        if (asr > -100) {
          bvn += a * w[i] * Math.exp(asr) * (Math.exp(-hk * (1 - rs) / (2 * (1 + rs))) / rs - (1 + c * xx * (1 + d * xx)));
        }
      }
    }
    bvn = -bvn / (2 * Math.PI);
    if (rho > 0) {
      bvn += cnd(-Math.max(h, k));
    } else {
      bvn = -bvn;
      if (k > h) {
        bvn += h < 0 ? cnd(k) - cnd(h) : cnd(-h) - cnd(-k);
      }
    }
  }
  return Math.min(1, Math.max(0, bvn));
}

// Bivariat normaltetthet.
export function bnd(x, y, rho) {
  const s = 1 - rho * rho;
  return Math.exp(-(x * x - 2 * rho * x * y + y * y) / (2 * s)) / (2 * Math.PI * Math.sqrt(s));
}
