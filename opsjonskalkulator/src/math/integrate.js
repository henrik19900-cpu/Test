// Numerisk integrasjon.

const glCache = new Map();

// Noder og vekter for n-punkts Gauss–Legendre på [-1, 1].
export function gaussLegendreNodes(n) {
  if (glCache.has(n)) return glCache.get(n);
  const x = new Float64Array(n);
  const w = new Float64Array(n);
  const m = Math.floor((n + 1) / 2);
  for (let i = 0; i < m; i++) {
    let z = Math.cos(Math.PI * (i + 0.75) / (n + 0.5));
    let pp = 0;
    for (let it = 0; it < 100; it++) {
      let p1 = 1;
      let p2 = 0;
      for (let j = 1; j <= n; j++) {
        const p3 = p2;
        p2 = p1;
        p1 = ((2 * j - 1) * z * p2 - (j - 1) * p3) / j;
      }
      pp = n * (z * p1 - p2) / (z * z - 1);
      const z1 = z;
      z = z1 - p1 / pp;
      if (Math.abs(z - z1) < 1e-15) break;
    }
    x[i] = -z;
    x[n - 1 - i] = z;
    w[i] = 2 / ((1 - z * z) * pp * pp);
    w[n - 1 - i] = w[i];
  }
  const res = { x, w };
  glCache.set(n, res);
  return res;
}

export function gaussLegendre(f, a, b, n = 64) {
  const { x, w } = gaussLegendreNodes(n);
  const half = 0.5 * (b - a);
  const mid = 0.5 * (a + b);
  let s = 0;
  for (let i = 0; i < n; i++) s += w[i] * f(mid + half * x[i]);
  return s * half;
}

// Sammensatt Gauss–Legendre: deler [a, b] i `panels` like deler.
export function gaussLegendreComposite(f, a, b, panels = 16, n = 16) {
  const h = (b - a) / panels;
  let s = 0;
  for (let i = 0; i < panels; i++) s += gaussLegendre(f, a + i * h, a + (i + 1) * h, n);
  return s;
}

export function adaptiveSimpson(f, a, b, { eps = 1e-10, maxDepth = 40 } = {}) {
  const fa = f(a);
  const fb = f(b);
  const m = 0.5 * (a + b);
  const fm = f(m);
  const whole = (b - a) / 6 * (fa + 4 * fm + fb);
  return simpsonRec(f, a, b, fa, fm, fb, whole, eps, maxDepth);
}

function simpsonRec(f, a, b, fa, fm, fb, whole, eps, depth) {
  const m = 0.5 * (a + b);
  const lm = 0.5 * (a + m);
  const rm = 0.5 * (m + b);
  const flm = f(lm);
  const frm = f(rm);
  const left = (m - a) / 6 * (fa + 4 * flm + fm);
  const right = (b - m) / 6 * (fm + 4 * frm + fb);
  const delta = left + right - whole;
  if (depth <= 0 || Math.abs(delta) <= 15 * eps) return left + right + delta / 15;
  return simpsonRec(f, a, m, fa, flm, fm, left, eps / 2, depth - 1) +
    simpsonRec(f, m, b, fm, frm, fb, right, eps / 2, depth - 1);
}
