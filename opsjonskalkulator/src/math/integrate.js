// Numerisk integrasjon.

const glCache = new Map();

// Legendre-polynomet P_n(x) og den deriverte, fra trelleddsrekursjonen
// k P_k = (2k − 1) x P_{k−1} − (k − 1) P_{k−2} og P_n' = n (x P_n − P_{n−1}) / (x² − 1).
function legendre(n, x) {
  let pPrev = 1;
  let p = x;
  for (let k = 2; k <= n; k++) {
    const next = ((2 * k - 1) * x * p - (k - 1) * pPrev) / k;
    pPrev = p;
    p = next;
  }
  return [p, n * (x * p - pPrev) / (x * x - 1)];
}

// Noder og vekter for n-punkts Gauss–Legendre på [−1, 1]. Nullpunktene startes fra
// Tricomis tilnærming (Abramowitz og Stegun 22.16.6) og poleres med Newton;
// vekten er w = 2 / ((1 − x²) P_n'(x)²).
export function gaussLegendreNodes(n) {
  if (glCache.has(n)) return glCache.get(n);
  const x = new Float64Array(n);
  const w = new Float64Array(n);
  const scale = 1 - 1 / (8 * n * n) + 1 / (8 * n * n * n);
  for (let k = 1; k <= Math.ceil(n / 2); k++) {
    let t = scale * Math.cos(Math.PI * (4 * k - 1) / (4 * n + 2));
    for (let it = 0; it < 100; it++) {
      const [p, dp] = legendre(n, t);
      const step = p / dp;
      t -= step;
      if (Math.abs(step) < 1e-16) break;
    }
    const dp = legendre(n, t)[1];
    const weight = 2 / ((1 - t * t) * dp * dp);
    x[n - k] = t;
    x[k - 1] = -t;
    w[n - k] = weight;
    w[k - 1] = weight;
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
