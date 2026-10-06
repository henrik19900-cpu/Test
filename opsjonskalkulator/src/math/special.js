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

// Regularisert ufullstendig gamma. Under a + 1 brukes potensrekken i Abramowitz og Stegun
// 6.5.29, over brukes kjedebrøken for Γ(a, x) i A&S 6.5.31. Kjedebrøken regnes ut med
// Lentz' metode (Lentz 1976; Thompson og Barnett 1986).

// Felles faktor x^a e^{−x} / Γ(a), regnet i logaritmer.
const gammaPrefactor = (a, x) => Math.exp(a * Math.log(x) - x - lnGamma(a));

// P(a, x) = x^a e^{−x} / Γ(a) · Σ_{n≥0} x^n / (a (a+1) ⋯ (a+n))
function lowerSeries(a, x) {
  let term = 1 / a;
  let total = term;
  for (let n = 1; n < 100000; n++) {
    term *= x / (a + n);
    total += term;
    if (term <= total * 1e-17) break;
  }
  return total * gammaPrefactor(a, x);
}

// Q(a, x) = x^a e^{−x} / Γ(a) · 1/(x + (1−a)/(1 + 1/(x + (2−a)/(1 + 2/(x + …)))))
// skrevet som b0 + a1/(b1 + a2/(b2 + …)) med b0 = 0 og, for k = 1, 2, …,
// a(2k) = k − a, b(2k) = 1, a(2k+1) = k, b(2k+1) = x, samt a1 = 1, b1 = x.
function upperFraction(a, x) {
  const tiny = 1e-300;
  let value = tiny;
  let C = value;
  let D = 0;
  for (let j = 1; j < 200000; j++) {
    let aj;
    let bj;
    if (j === 1) {
      aj = 1;
      bj = x;
    } else if (j % 2 === 0) {
      aj = j / 2 - a;
      bj = 1;
    } else {
      aj = (j - 1) / 2;
      bj = x;
    }
    D = bj + aj * D;
    D = Math.abs(D) < tiny ? 1 / tiny : 1 / D;
    C = bj + aj / C;
    if (Math.abs(C) < tiny) C = tiny;
    const delta = C * D;
    value *= delta;
    if (Math.abs(delta - 1) < 1e-16) break;
  }
  return value * gammaPrefactor(a, x);
}

export function gammaP(a, x) {
  if (x <= 0) return 0;
  return x < a + 1 ? lowerSeries(a, x) : 1 - upperFraction(a, x);
}

export function gammaQ(a, x) {
  if (x <= 0) return 1;
  return x < a + 1 ? 1 - lowerSeries(a, x) : upperFraction(a, x);
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
