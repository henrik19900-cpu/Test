// Spesialfunksjoner: gammafunksjonen, regularisert ufullstendig gamma og
// ikke-sentral kjikvadratfordeling (brukes bl.a. av CEV-modellen).

const LANCZOS = [
  0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
  -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6,
  1.5056327351493116e-7,
];

export function lnGamma(x) {
  if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lnGamma(1 - x);
  x -= 1;
  let a = LANCZOS[0];
  const t = x + 7.5;
  for (let i = 1; i < 9; i++) a += LANCZOS[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

export function gamma(x) {
  if (x < 0.5) return Math.PI / (Math.sin(Math.PI * x) * gamma(1 - x));
  return Math.exp(lnGamma(x));
}

// Regularisert nedre ufullstendig gamma P(a, x).
export function gammaP(a, x) {
  if (x <= 0) return 0;
  if (x < a + 1) return gammaSeries(a, x);
  return 1 - gammaCF(a, x);
}

// Regularisert øvre ufullstendig gamma Q(a, x) = 1 − P(a, x).
export function gammaQ(a, x) {
  if (x <= 0) return 1;
  if (x < a + 1) return 1 - gammaSeries(a, x);
  return gammaCF(a, x);
}

function gammaSeries(a, x) {
  let ap = a;
  let sum = 1 / a;
  let del = sum;
  for (let n = 0; n < 10000; n++) {
    ap += 1;
    del *= x / ap;
    sum += del;
    if (Math.abs(del) < Math.abs(sum) * 1e-16) break;
  }
  return sum * Math.exp(-x + a * Math.log(x) - lnGamma(a));
}

function gammaCF(a, x) {
  const FPMIN = 1e-300;
  let b = x + 1 - a;
  let c = 1 / FPMIN;
  let d = 1 / b;
  let h = d;
  for (let i = 1; i < 10000; i++) {
    const an = -i * (i - a);
    b += 2;
    d = an * d + b;
    if (Math.abs(d) < FPMIN) d = FPMIN;
    c = b + an / c;
    if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-16) break;
  }
  return Math.exp(-x + a * Math.log(x) - lnGamma(a)) * h;
}

// Kumulativ kjikvadrat med k frihetsgrader.
export function chi2cdf(x, k) {
  return gammaP(k / 2, x / 2);
}

// Kumulativ ikke-sentral kjikvadrat: P(χ'²(k, λ) ≤ x).
// Summerer Poisson-vektede sentrale fordelinger utover fra modusen.
export function ncx2cdf(x, k, lambda) {
  if (x <= 0) return 0;
  if (lambda <= 0) return chi2cdf(x, k);
  const half = lambda / 2;
  const j0 = Math.floor(half);
  const logW0 = -half + j0 * Math.log(half) - lnGamma(j0 + 1);
  let sum = 0;
  // Oppover fra modus
  let logW = logW0;
  for (let j = j0; j < j0 + 100000; j++) {
    const term = Math.exp(logW) * gammaP(k / 2 + j, x / 2);
    sum += term;
    if (Math.exp(logW) < 1e-17 && j > j0) break;
    logW += Math.log(half) - Math.log(j + 1);
  }
  // Nedover fra modus
  logW = logW0;
  for (let j = j0 - 1; j >= 0; j--) {
    logW += Math.log(j + 1) - Math.log(half);
    const term = Math.exp(logW) * gammaP(k / 2 + j, x / 2);
    sum += term;
    if (Math.exp(logW) < 1e-17) break;
  }
  return Math.min(1, Math.max(0, sum));
}
