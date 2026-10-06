// Nullpunktsløsere. Alle kaster en Error med norsk melding når de ikke finner en løsning.

export function bisection(f, lo, hi, { tol = 1e-12, maxIter = 300 } = {}) {
  let flo = f(lo);
  const fhi = f(hi);
  if (flo === 0) return lo;
  if (fhi === 0) return hi;
  if (flo * fhi > 0) throw new Error('Fant ingen løsning i intervallet.');
  for (let i = 0; i < maxIter; i++) {
    const mid = 0.5 * (lo + hi);
    const fm = f(mid);
    if (fm === 0 || 0.5 * (hi - lo) < tol) return mid;
    if (flo * fm < 0) {
      hi = mid;
    } else {
      lo = mid;
      flo = fm;
    }
  }
  return 0.5 * (lo + hi);
}

// Brent–Dekker. Krever fortegnsskifte mellom a og b.
export function brent(f, a, b, { tol = 1e-13, maxIter = 300 } = {}) {
  let fa = f(a);
  let fb = f(b);
  if (fa === 0) return a;
  if (fb === 0) return b;
  if (fa * fb > 0) throw new Error('Fant ingen løsning i intervallet.');
  let c = a;
  let fc = fa;
  let d = b - a;
  let e = d;
  for (let i = 0; i < maxIter; i++) {
    if (fb * fc > 0) {
      c = a;
      fc = fa;
      d = b - a;
      e = d;
    }
    if (Math.abs(fc) < Math.abs(fb)) {
      a = b; b = c; c = a;
      fa = fb; fb = fc; fc = fa;
    }
    const tol1 = 2 * Number.EPSILON * Math.abs(b) + 0.5 * tol;
    const xm = 0.5 * (c - b);
    if (Math.abs(xm) <= tol1 || fb === 0) return b;
    if (Math.abs(e) >= tol1 && Math.abs(fa) > Math.abs(fb)) {
      const s = fb / fa;
      let p;
      let q;
      if (a === c) {
        p = 2 * xm * s;
        q = 1 - s;
      } else {
        const qq = fa / fc;
        const r = fb / fc;
        p = s * (2 * xm * qq * (qq - r) - (b - a) * (r - 1));
        q = (qq - 1) * (r - 1) * (s - 1);
      }
      if (p > 0) q = -q;
      p = Math.abs(p);
      if (2 * p < Math.min(3 * xm * q - Math.abs(tol1 * q), Math.abs(e * q))) {
        e = d;
        d = p / q;
      } else {
        d = xm;
        e = d;
      }
    } else {
      d = xm;
      e = d;
    }
    a = b;
    fa = fb;
    b += Math.abs(d) > tol1 ? d : (xm > 0 ? tol1 : -tol1);
    fb = f(b);
  }
  return b;
}

// Utvider [a, b] geometrisk til f skifter fortegn. Returnerer [a, b].
export function bracket(f, a, b, { factor = 1.6, maxIter = 60, lower = -Infinity, upper = Infinity } = {}) {
  let fa = f(a);
  let fb = f(b);
  for (let i = 0; i < maxIter; i++) {
    if (fa * fb <= 0) return [a, b];
    if (Math.abs(fa) < Math.abs(fb)) {
      a = Math.max(lower, a + factor * (a - b));
      fa = f(a);
    } else {
      b = Math.min(upper, b + factor * (b - a));
      fb = f(b);
    }
  }
  throw new Error('Fant ikke et intervall med fortegnsskifte.');
}

// Newton–Raphson med fallback til Brent når et intervall [lo, hi] er gitt.
export function newton(f, df, x0, { tol = 1e-12, maxIter = 100, lo, hi } = {}) {
  let x = x0;
  for (let i = 0; i < maxIter; i++) {
    const fx = f(x);
    const dfx = df(x);
    if (!Number.isFinite(fx) || !Number.isFinite(dfx) || dfx === 0) break;
    const step = fx / dfx;
    let xn = x - step;
    if (lo !== undefined && hi !== undefined && (xn <= lo || xn >= hi)) break;
    if (Math.abs(step) <= tol * Math.max(1, Math.abs(xn))) return xn;
    x = xn;
  }
  if (lo !== undefined && hi !== undefined) return brent(f, lo, hi, { tol });
  throw new Error('Newton-iterasjonen konvergerte ikke.');
}
