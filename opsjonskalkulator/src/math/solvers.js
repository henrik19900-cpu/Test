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

// Brents metode (Brent 1973, kap. 4). Hvert steg prøver invers kvadratisk interpolasjon
// gjennom de tre siste punktene, eller sekantmetoden når to funksjonsverdier er like.
// Brents vilkår avgjør om forslaget godtas; ellers halveres intervallet. Intervallet
// [a, b] har alltid fortegnsskifte, og b er det beste estimatet.
export function brent(f, lo, hi, { tol = 1e-13, maxIter = 300 } = {}) {
  let a = lo;
  let b = hi;
  let fa = f(a);
  let fb = f(b);
  if (fa === 0) return a;
  if (fb === 0) return b;
  if (fa * fb > 0) throw new Error('Fant ingen løsning i intervallet.');
  const swap = () => {
    [a, b] = [b, a];
    [fa, fb] = [fb, fa];
  };
  if (Math.abs(fa) < Math.abs(fb)) swap();
  let prev = a;       // forrige b
  let fPrev = fa;
  let prevPrev = a;   // b for to steg siden
  let bisected = true;
  for (let i = 0; i < maxIter; i++) {
    const eps = 2 * Number.EPSILON * Math.abs(b) + 0.5 * tol;
    if (fb === 0 || Math.abs(b - a) <= 2 * eps) return b;

    let s;
    if (fa !== fPrev && fb !== fPrev) {
      s = a * fb * fPrev / ((fa - fb) * (fa - fPrev))
        + b * fa * fPrev / ((fb - fa) * (fb - fPrev))
        + prev * fa * fb / ((fPrev - fa) * (fPrev - fb));
    } else {
      s = b - fb * (b - a) / (fb - fa);
    }

    // Forslaget må ligge mellom (3a + b)/4 og b og krympe steget raskt nok.
    const edge = (3 * a + b) / 4;
    const between = (s - edge) * (s - b) < 0;
    const lastStep = bisected ? Math.abs(b - prev) : Math.abs(prev - prevPrev);
    const accept = between && Math.abs(s - b) < lastStep / 2 && lastStep >= eps;
    if (!accept) s = 0.5 * (a + b);
    bisected = !accept;

    const fs = f(s);
    prevPrev = prev;
    prev = b;
    fPrev = fb;
    if (fa * fs < 0) {
      b = s;
      fb = fs;
    } else {
      a = s;
      fa = fs;
    }
    if (Math.abs(fa) < Math.abs(fb)) swap();
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
