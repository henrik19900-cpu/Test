// Kapittel 6: Justeringer av og alternativer til Black-Scholes-Merton.
//
//   tradingDaysBSM       French (1984): volatilitet over handelsdager, diskontering over kalenderdager
//   mertonJumpDiffusion  Merton (1976) med Haugs parametrisering (λ hopp per år, γ andel av variansen fra hopp)
//   batesJumpDiffusion   Merton (1976)/Bates (1991): lognormale hopp med forventet relativ hoppstørrelse k̄
//   leland               Leland (1985): transaksjonskostnader via justert volatilitet
//   hullWhite87          Hull og White (1987): ukorrelert stokastisk volatilitet, rekkeutvikling
//   hullWhite88          Hull og White (1988): korrelert stokastisk volatilitet, andreordens rekke i ξ
//   sabrVol / sabr       Hagan, Kumar, Lesniewski og Woodward (2002)
//   cev                  Cox (1975), Schroder (1989): konstant elastisitet i variansen
//   displacedDiffusion   Rubinstein (1983): fortrengt diffusjon
//   heston               Heston (1993) via karakteristisk funksjon (Lewis' enkeltintegral)
//
// Notasjon som i resten av prosjektet: S, X, T, r, b (cost of carry), v (σ), type = 'call' | 'put'.

import { nd, cnd } from '../math/normal.js';
import { gaussLegendre, gaussLegendreNodes } from '../math/integrate.js';
import { gammaP, lnGamma, chi2cdf } from '../math/special.js';
import { gbsm, isCall } from './bsm.js';

// e1(x) = (e^x − 1)/x, numerisk stabil nær 0.
function e1(x) {
  return Math.abs(x) < 1e-8 ? 1 + 0.5 * x : Math.expm1(x) / x;
}

// Regularisert nedre ufullstendig gamma P(a, z) som også tåler svært store a: for a ≥ 200
// integreres gammatettheten numerisk over halen (integranden er tilnærmet normal rundt a − 1).
export function gammaPRobust(a, z) {
  if (!(z > 0)) return 0;
  if (a < 200) return gammaP(a, z);
  const a1 = a - 1;
  const la1 = Math.log(a1);
  const sq = Math.sqrt(a1);
  const upper = z > a1;
  const zu = upper ? Math.max(a1 + 12 * sq, z + 7 * sq) : Math.max(0, Math.min(a1 - 9 * sq, z - 6 * sq));
  const { x: gx, w: gw } = gaussLegendreNodes(96);
  const half = 0.5 * (zu - z);
  const mid = 0.5 * (zu + z);
  let sum = 0;
  for (let i = 0; i < gx.length; i++) {
    const t = mid + half * gx[i];
    if (t > 0) sum += gw[i] * Math.exp(-(t - a1) + a1 * (Math.log(t) - la1));
  }
  // ∫_z^{zu} t^{a−1} e^{−t} dt / Γ(a): positiv over (øvre hale), negativ under.
  const ans = sum * half * Math.exp(a1 * (la1 - 1) - lnGamma(a));
  return upper ? 1 - ans : -ans;
}

// Kumulativ ikke-sentral kjikvadrat P(χ'²(k, λ) ≤ x) for store λ og k: Poisson-vektet sum av
// sentrale fordelinger der P(k/2 + j, x/2) bare regnes direkte ved modusen og ellers fås fra
// P(a + 1, z) = P(a, z) − e^{−z} z^a / Γ(a + 1).
export function ncx2cdfLarge(x, k, lambda) {
  if (!(x > 0)) return 0;
  if (!(lambda > 0)) return chi2cdf(x, k);
  const z = x / 2;
  const m = lambda / 2;
  const lz = Math.log(z);
  const j0 = Math.floor(m);
  const a0 = k / 2 + j0;
  const p0 = gammaPRobust(a0, z);
  const logW0 = -m + j0 * Math.log(m) - lnGamma(j0 + 1);
  const t0 = Math.exp(-z + a0 * lz - lnGamma(a0 + 1)); // e^{−z} z^{a0}/Γ(a0 + 1)
  const w0 = Math.exp(logW0);
  let sum = w0 * p0;
  // Oppover
  let w = w0;
  let p = p0;
  let t = t0;
  for (let j = j0 + 1; ; j++) {
    p = Math.max(p - t, 0);
    t *= z / (k / 2 + j);
    w *= m / j;
    sum += w * p;
    if ((w < 1e-20 * w0 && j > j0 + 5) || p === 0 || j > j0 + 1e7) break;
  }
  // Nedover
  w = w0;
  p = p0;
  t = t0;
  for (let j = j0 - 1; j >= 0; j--) {
    t *= (k / 2 + j + 1) / z; // e^{−z} z^{a}/Γ(a + 1) for a = k/2 + j
    p += t;
    w *= (j + 1) / m;
    sum += w * Math.min(p, 1);
    if (w < 1e-20 * w0) break;
  }
  return Math.min(1, Math.max(0, sum));
}

// Σ_i e^{−m} m^i / i! · f(i): forventning over en Poisson-fordelt variabel med forventning m.
export function poissonMixture(m, f) {
  if (!(m > 0)) return f(0);
  const iMax = Math.ceil(m + 14 * Math.sqrt(m) + 50);
  const lm = Math.log(m);
  let logW = -m;
  let sum = 0;
  for (let i = 0; i <= iMax; i++) {
    if (i > 0) logW += lm - Math.log(i);
    const w = Math.exp(logW);
    if (w > 1e-300) sum += w * f(i);
    if (i > m && w < 1e-18) break;
  }
  return sum;
}

// --- French (1984): handelsdager ------------------------------------------------------
// T = kalendertid (år) for diskontering og carry, t = handelstid (år) for volatiliteten.
export function tradingDaysBSM({ type = 'call', S, X, T, t, r, b, v }) {
  const call = isCall(type);
  if (!(t > 0) || !(v > 0)) return gbsm({ type, S, X, T, r, b, v: 0 });
  const sqt = Math.sqrt(t);
  const d1 = (Math.log(S / X) + b * T + 0.5 * v * v * t) / (v * sqt);
  const d2 = d1 - v * sqt;
  const sc = S * Math.exp((b - r) * T);
  const xd = X * Math.exp(-r * T);
  return call ? sc * cnd(d1) - xd * cnd(d2) : xd * cnd(-d2) - sc * cnd(-d1);
}

// --- Hopp-diffusjon -----------------------------------------------------------------------
// Merton (1976) slik Haug parametriserer modellen: v er total volatilitet, λ forventet antall
// hopp per år og γ andelen av total varians som skyldes hopp. Forventet relativt hopp er null.
//   δ² = γ v² / λ,  z² = v² − λδ²,  σ_i² = z² + δ² i / T
//   c = Σ e^{−λT} (λT)^i / i! · c_BSM(S, X, T, r, b, σ_i)
export function mertonJumpDiffusion({ type = 'call', S, X, T, r, b = r, v, lambda, gamma }) {
  if (!(lambda >= 0)) throw new Error('Hoppintensiteten λ kan ikke være negativ.');
  if (!(gamma >= 0 && gamma <= 1)) throw new Error('Andelen γ må ligge mellom 0 og 1.');
  if (lambda === 0 || gamma === 0) return gbsm({ type, S, X, T, r, b, v });
  const delta2 = gamma * v * v / lambda;
  const z2 = v * v * (1 - gamma);
  return poissonMixture(lambda * T, (i) => gbsm({ type, S, X, T, r, b, v: Math.sqrt(z2 + delta2 * i / T) }));
}

// Generell hopp-diffusjon med lognormale hopp, Merton (1976) og Bates (1991):
//   dS/S = (b − λk̄) dt + v dW + k dq,  ln(1 + k) ~ N(ln(1 + k̄) − δ²/2, δ²)
//   b_i = b − λk̄ + i ln(1 + k̄)/T,  σ_i² = v² + δ² i / T
//   c = Σ e^{−λT} (λT)^i / i! · c_GBSM(S, X, T, r, b_i, σ_i)
export function batesJumpDiffusion({ type = 'call', S, X, T, r, b, v, lambda, kbar, delta }) {
  if (!(lambda >= 0)) throw new Error('Hoppintensiteten λ kan ikke være negativ.');
  if (!(kbar > -1)) throw new Error('Forventet hoppstørrelse k̄ må være større enn −1 (−100 %).');
  if (!(delta >= 0)) throw new Error('Volatiliteten i hoppstørrelsen δ kan ikke være negativ.');
  const g = Math.log1p(kbar);
  return poissonMixture(lambda * T, (i) => gbsm({
    type, S, X, T, r, b: b - lambda * kbar + i * g / T, v: Math.sqrt(v * v + delta * delta * i / T),
  }));
}

// --- Leland (1985): transaksjonskostnader ------------------------------------------------
// k er rundturskostnad som andel av handlet beløp, dt tiden mellom rebalanseringene.
// Kort opsjon (den som sikrer): σ_A² = σ²(1 + Le), lang: σ_A² = σ²(1 − Le), Le = √(2/π) k/(σ√Δt).
export function leland({ type = 'call', S, X, T, r, b, v, k, dt, position = 'short' }) {
  if (!(dt > 0)) throw new Error('Tiden mellom rebalanseringer må være positiv.');
  if (!(k >= 0)) throw new Error('Transaksjonskostnaden kan ikke være negativ.');
  const le = Math.sqrt(2 / Math.PI) * k / (v * Math.sqrt(dt));
  const factor = position === 'long' ? 1 - le : 1 + le;
  if (!(factor > 0)) {
    throw new Error('Kostnadene er så store at justert varians blir negativ for en lang posisjon (Leland-tallet ≥ 1).');
  }
  const vA = v * Math.sqrt(factor);
  return { price: gbsm({ type, S, X, T, r, b, v: vA }), vA, le };
}

// --- Hull og White (1987): ukorrelert stokastisk volatilitet -----------------------------
// Variansen V = σ² følger dV = μV dt + ξV dW, uavhengig av aksjen. Prisen er forventet BSM-pris
// over gjennomsnittsvariansen V̄; rekkeutvikling rundt E[V̄] til tredje sentralmoment.

// Forventning, varians og tredje sentralmoment til V̄ = (1/T)∫V dt når V er geometrisk brownsk
// med drift μ og volatilitet ξ. Sentralmomentene regnes direkte (ikke fra råmomenter) for å unngå
// kansellering når ξ er liten.
export function averageVarianceMoments(V, mu, xi, T) {
  const x2 = xi * xi;
  if (mu === 0) {
    // Lukket form (Hull og White 1987), k = ξ²T:
    //   Var/V² = 2(e^k − k − 1)/k² − 1
    //   M3/V³ = (e^{3k} − (9 + 18k)e^k + 8 + 24k + 18k² + 6k³)/(3k³)
    // For små k brukes Taylor-rekkene til de samme uttrykkene.
    const k = x2 * T;
    let varF;
    let m3F;
    if (k < 2) {
      varF = 0;
      let term = 2 / 6; // 2k^{n−2}/n! for n = 3
      for (let n = 3; n < 60; n++) {
        varF += term;
        term *= k / (n + 1);
        if (term < 1e-18 * varF) break;
      }
      varF *= k;
      m3F = 0;
      // c_n = (3^n − 9)/n! − 18/(n − 1)!, ledd c_n k^{n−3}/3 for n ≥ 5
      let invFact = 1 / 120; // 1/n!
      let pow3 = 243;
      let kp = k * k;
      for (let n = 5; n < 80; n++) {
        const cn = (pow3 - 9) * invFact - 18 * invFact * n;
        const t = cn * kp / 3;
        m3F += t;
        if (n > 8 && Math.abs(t) < 1e-18 * Math.abs(m3F)) break;
        invFact /= n + 1;
        pow3 *= 3;
        kp *= k;
      }
    } else {
      varF = 2 * (Math.expm1(k) - k) / (k * k) - 1;
      m3F = (Math.exp(3 * k) - (9 + 18 * k) * Math.exp(k) + 8 + 24 * k + 18 * k * k + 6 * k ** 3) / (3 * k ** 3);
    }
    return [V, V * V * varF, V ** 3 * m3F];
  }
  // Generell drift: m_s = V e^{μs}, A(s) = e^{ξ²s} − 1. For s ≤ t ≤ u er
  //   Cov(V_s, V_t) = m_s m_t A(s),  κ₃(V_s, V_t, V_u) = m_s m_t m_u (A(s)² + 2A(s)A(t) + A(s)²A(t)).
  // Integralet over u regnes analytisk, resten med nøstet Gauss-Legendre.
  const { x: gx, w: gw } = gaussLegendreNodes(24);
  const m1 = V * e1(mu * T);
  let s2 = 0;
  let s3 = 0;
  for (let i = 0; i < gx.length; i++) {
    const t = 0.5 * T * (gx[i] + 1);
    const wt = 0.5 * T * gw[i];
    let i1 = 0; // ∫_0^t e^{μs} A(s) ds
    let i2 = 0; // ∫_0^t e^{μs} A(s)² ds
    for (let j = 0; j < gx.length; j++) {
      const s = 0.5 * t * (gx[j] + 1);
      const ws = 0.5 * t * gw[j];
      const A = Math.expm1(x2 * s);
      i1 += ws * Math.exp(mu * s) * A;
      i2 += ws * Math.exp(mu * s) * A * A;
    }
    const At = Math.expm1(x2 * t);
    const et = Math.exp(mu * t);
    s2 += wt * et * i1;
    const U = et * (T - t) * e1(mu * (T - t)); // ∫_t^T e^{μu} du
    s3 += wt * et * U * (i2 * (1 + At) + 2 * At * i1);
  }
  return [m1, 2 * V * V * s2 / (T * T), 6 * V ** 3 * s3 / T ** 3];
}

// ∂ⁿc/∂Vⁿ for n = 1, 2, 3 der V = σ² (årlig varians), for call og put (like).
function varianceDerivatives({ S, X, T, r, b, v }) {
  const sqT = Math.sqrt(T);
  const vst = v * sqT;
  const d1 = (Math.log(S / X) + (b + 0.5 * v * v) * T) / vst;
  const d2 = d1 - vst;
  const base = S * Math.exp((b - r) * T) * sqT * nd(d1);
  return {
    c1: base / (2 * v),
    c2: base * (d1 * d2 - 1) / (4 * v ** 3),
    c3: base * ((d1 * d2 - 1) * (d1 * d2 - 3) - (d1 * d1 + d2 * d2)) / (8 * v ** 5),
  };
}

export function hullWhite87({ type = 'call', S, X, T, r, b, v, xi, mu = 0 }) {
  if (!(xi >= 0)) throw new Error('Volatiliteten til variansen ξ kan ikke være negativ.');
  const [m1, variance, third] = averageVarianceMoments(v * v, mu, xi, T);
  const vbar = Math.sqrt(m1);
  const bs = gbsm({ type, S, X, T, r, b, v: vbar });
  const { c2, c3 } = varianceDerivatives({ S, X, T, r, b, v: vbar });
  const second = 0.5 * c2 * variance;
  const thirdTerm = c3 * third / 6;
  return { price: bs + second + thirdTerm, bs, vbar, sdVbar: Math.sqrt(variance), second, third: thirdTerm };
}

// --- Hull og White (1988): korrelert stokastisk volatilitet ---------------------------------
// dS/S = b dt + √V dW₁,  dV = κ(θ − V) dt + ξ V dW₂,  dW₁dW₂ = ρ dt.
// Prisen utvikles i potenser av ξ rundt BSM-prisen med forventet gjennomsnittsvarians:
//   c ≈ c_BSM(w) + ξρ J₁ D′/2 + ξ²[ρ²(K₁ D″/2 + J₁²(D⁗ − D‴)/8) + K₃(D″ − D′)/4]
// der w = ∫V_s ds langs den deterministiske variansbanen V_s = θ + (V₀ − θ)e^{−κs},
// D(x) = e^{−rT} X n(d₂)/√w = 2∂c/∂w og ′ betyr derivert med hensyn på x = ln S.
//   φ(τ) = (1 − e^{−κτ})/κ,  J₁ = ∫V_s^{3/2} φ(T − s) ds,  K₃ = ½∫V_s² φ(T − s)² ds,
//   K₁ = ∫V_s^{3/2} · (3/2)∫_s^T V_u^{1/2} e^{−κ(u−s)} φ(T − u) du ds.
export function hullWhite88({ type = 'call', S, X, T, r, b, v, vLR, kappa, xi, rho }) {
  if (!(v > 0 && vLR > 0)) throw new Error('Volatilitetene må være positive.');
  if (!(kappa >= 0)) throw new Error('Mean reversion-hastigheten κ kan ikke være negativ.');
  if (!(xi >= 0)) throw new Error('Volatiliteten til variansen ξ kan ikke være negativ.');
  if (!(rho >= -1 && rho <= 1)) throw new Error('Korrelasjonen må ligge mellom −1 og 1.');
  const V0 = v * v;
  const th = vLR * vLR;
  const Vs = (s) => th + (V0 - th) * Math.exp(-kappa * s);
  const phi = (tau) => tau * e1(-kappa * tau);
  const w = th * T + (V0 - th) * phi(T);
  const { x: gx, w: gw } = gaussLegendreNodes(32);
  const n = gx.length;
  let J1 = 0;
  let K1 = 0;
  let K3 = 0;
  for (let i = 0; i < n; i++) {
    const s = 0.5 * T * (gx[i] + 1);
    const ws = 0.5 * T * gw[i];
    const V = Vs(s);
    const ph = phi(T - s);
    J1 += ws * V ** 1.5 * ph;
    K3 += ws * 0.5 * V * V * ph * ph;
    let dJ = 0;
    const len = T - s;
    for (let j = 0; j < n; j++) {
      const u = s + 0.5 * len * (gx[j] + 1);
      dJ += 0.5 * len * gw[j] * Math.sqrt(Vs(u)) * Math.exp(-kappa * (u - s)) * phi(T - u);
    }
    K1 += ws * V ** 1.5 * 1.5 * dJ;
  }
  const sw = Math.sqrt(w);
  const vbar = Math.sqrt(w / T);
  const bs = gbsm({ type, S, X, T, r, b, v: vbar });
  const d2 = (Math.log(S / X) + b * T - 0.5 * w) / sw;
  const base = Math.exp(-r * T) * X * nd(d2) / sw;
  // D^{(k)} = base · w^{−k/2} · (−1)^k He_k(d₂)
  const D1 = -base * d2 / sw;
  const D2 = base * (d2 * d2 - 1) / w;
  const D3 = -base * (d2 ** 3 - 3 * d2) / (w * sw);
  const D4 = base * (d2 ** 4 - 6 * d2 * d2 + 3) / (w * w);
  const first = xi * rho * J1 * D1 / 2;
  const second = xi * xi * (rho * rho * (K1 * D2 / 2 + J1 * J1 * (D4 - D3) / 8) + K3 * (D2 - D1) / 4);
  return { price: bs + first + second, bs, vbar, first, second };
}

// --- SABR (Hagan m.fl. 2002) -----------------------------------------------------------------
// dF = α F^β dW₁, dα = ν α dW₂, dW₁dW₂ = ρ dt. Implisitt Black-volatilitet, Hagans tilnærming.
export function sabrVol({ F, X, T, alpha, beta, rho, nu }) {
  if (!(alpha > 0)) throw new Error('α må være positiv.');
  if (!(beta >= 0 && beta <= 1)) throw new Error('β må ligge mellom 0 og 1.');
  if (!(rho > -1 && rho < 1)) throw new Error('ρ må ligge strengt mellom −1 og 1.');
  if (!(nu >= 0)) throw new Error('ν kan ikke være negativ.');
  if (!(F > 0 && X > 0)) throw new Error('Forwardpris og innløsningskurs må være positive.');
  const omb = 1 - beta;
  const lfk = Math.log(F / X);
  const fkb = Math.pow(F * X, omb / 2);
  const z = nu / alpha * fkb * lfk;
  let zx;
  if (Math.abs(z) < 1e-7) {
    zx = 1 - 0.5 * rho * z;
  } else {
    const s = Math.sqrt(1 - 2 * rho * z + z * z);
    const x = z > 0 ? Math.log((s + z - rho) / (1 - rho)) : -Math.log((s - z + rho) / (1 + rho));
    zx = z / x;
  }
  const l2 = lfk * lfk;
  const denom = fkb * (1 + omb * omb / 24 * l2 + omb ** 4 / 1920 * l2 * l2);
  const corr = 1 + (omb * omb / 24 * alpha * alpha / (fkb * fkb) + 0.25 * rho * beta * nu * alpha / fkb +
    (2 - 3 * rho * rho) / 24 * nu * nu) * T;
  return alpha / denom * zx * corr;
}

export function sabr({ type = 'call', S, X, T, r, b, alpha, beta, rho, nu }) {
  const F = S * Math.exp(b * T);
  const vol = sabrVol({ F, X, T, alpha, beta, rho, nu });
  return { price: gbsm({ type, S, X, T, r, b, v: vol }), vol, F };
}

// --- CEV (Cox 1975, Schroder 1989) -------------------------------------------------------------
// dS = bS dt + σ S^{β/2} dW. β = 2 gir BSM, β < 2 gir fallende lokal volatilitet (absorberende null),
// β > 2 stigende. Lokal volatilitet er σ S^{β/2 − 1}. χ²(z; k, λ) er ikke-sentral kjikvadrat.
//   κ = 2b / (σ²(2 − β)(e^{b(2−β)T} − 1)),  x = κ S^{2−β} e^{b(2−β)T},  y = κ X^{2−β}
// β < 2: c = S e^{(b−r)T}[1 − χ²(2y; 2 + 2/(2−β), 2x)] − X e^{−rT} χ²(2x; 2/(2−β), 2y)
// β > 2: c = S e^{(b−r)T}[1 − χ²(2x; 2/(β−2), 2y)] − X e^{−rT} χ²(2y; 2 + 2/(β−2), 2x)
// For β > 2 er prisprosessen en strengt lokal martingal; put-formelen er da forventet utbetaling,
// og call-formelen er den som oppfyller put-call-pariteten (slik Schroder og Haug skriver den).
// Svært nær β = 2 blir kjikvadratparametrene enorme; der interpoleres prisen lineært i β (σ fast)
// mellom BSM (β = 2) og formelen i β = 2 ± CEV_NEAR_2.
const CEV_NEAR_2 = 1e-3;

function cevSchroder(call, S, X, T, r, b, v, beta) {
  const tb = 2 - beta;
  const bt = b * tb * T;
  const kappa = 2 / (v * v * tb * tb * T * e1(bt));
  const x = kappa * Math.pow(S, tb) * Math.exp(bt);
  const y = kappa * Math.pow(X, tb);
  const sc = S * Math.exp((b - r) * T);
  const xd = X * Math.exp(-r * T);
  if (beta < 2) {
    const nu = 2 / tb;
    const pS = ncx2cdfLarge(2 * y, 2 + nu, 2 * x);
    const pX = ncx2cdfLarge(2 * x, nu, 2 * y);
    return call ? sc * (1 - pS) - xd * pX : xd * (1 - pX) - sc * pS;
  }
  const nu = 2 / (beta - 2);
  const pS = ncx2cdfLarge(2 * x, nu, 2 * y);
  const pX = ncx2cdfLarge(2 * y, 2 + nu, 2 * x);
  return call ? sc * (1 - pS) - xd * pX : xd * (1 - pX) - sc * pS;
}

export function cev({ type = 'call', S, X, T, r, b, v, beta }) {
  const call = isCall(type);
  if (!(v > 0)) throw new Error('Volatilitetsparameteren σ må være positiv.');
  if (!(beta >= 0)) throw new Error('Elastisiteten β kan ikke være negativ.');
  if (!(T > 0)) return Math.max(call ? S - X : X - S, 0);
  const dist = beta - 2;
  if (Math.abs(dist) < CEV_NEAR_2) {
    const p2 = gbsm({ type, S, X, T, r, b, v });
    if (dist === 0) return p2;
    const pe = cevSchroder(call, S, X, T, r, b, v, 2 + Math.sign(dist) * CEV_NEAR_2);
    return p2 + (pe - p2) * Math.abs(dist) / CEV_NEAR_2;
  }
  return cevSchroder(call, S, X, T, r, b, v, beta);
}

// Forventet S_T i CEV-modellen (lavere enn S e^{bT} når β > 2: strengt lokal martingal).
export function cevExpectedSpot({ S, T, b, v, beta }) {
  if (beta <= 2) return S * Math.exp(b * T);
  const tb = 2 - beta;
  const bt = b * tb * T;
  const kappa = 2 / (v * v * tb * tb * T * e1(bt));
  const x = kappa * Math.pow(S, tb) * Math.exp(bt);
  return S * Math.exp(b * T) * chi2cdf(2 * x, 2 / (beta - 2));
}

// --- Fortrengt diffusjon (Rubinstein 1983) ----------------------------------------------------
// Andelen a av verdien er risikable eiendeler med volatilitet σ, resten er risikofri:
//   F_T = a F e^{σW − σ²T/2} + (1 − a) F,  F = S e^{bT}
//   c = c_GBSM(aS, X − (1 − a)F, T, r, b, σ) når X − (1 − a)F > 0, ellers (F − X)e^{−rT}.
export function displacedDiffusion({ type = 'call', S, X, T, r, b, v, a }) {
  const call = isCall(type);
  if (!(a > 0 && a <= 1)) throw new Error('Andelen risikable eiendeler a må ligge i (0, 1].');
  const F = S * Math.exp(b * T);
  const Xd = X - (1 - a) * F;
  if (Xd <= 0) return call ? (F - X) * Math.exp(-r * T) : 0;
  return gbsm({ type, S: a * S, X: Xd, T, r, b, v });
}

// --- Heston (1993) -------------------------------------------------------------------------------
// dS/S = b dt + √V dW₁,  dV = κ(θ − V) dt + σ_v √V dW₂,  dW₁dW₂ = ρ dt.
// Lewis (2001): c = S e^{(b−r)T} − (√(FX) e^{−rT}/π) ∫₀^∞ Re[e^{iuk} ψ(u − i/2)] / (u² + ¼) du,
// k = ln(F/X), ψ karakteristisk funksjon til ln(S_T/F) («little Heston trap»-formen).

// Små komplekse hjelpere, tall som [re, im].
const cmul = (a, b) => [a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]];
const cdiv = (a, b) => {
  const m = b[0] * b[0] + b[1] * b[1];
  return [(a[0] * b[0] + a[1] * b[1]) / m, (a[1] * b[0] - a[0] * b[1]) / m];
};
const csqrt = (a) => {
  const mod = Math.hypot(a[0], a[1]);
  const re = Math.sqrt(0.5 * (mod + a[0]));
  const im = Math.sqrt(Math.max(0.5 * (mod - a[0]), 0));
  return [re, a[1] < 0 ? -im : im];
};
const cexp = (a) => {
  const m = Math.exp(a[0]);
  return [m * Math.cos(a[1]), m * Math.sin(a[1])];
};
// ln(1 + w), nøyaktig også når |w| er liten.
const clog1p = (w) => [0.5 * Math.log1p(2 * w[0] + w[0] * w[0] + w[1] * w[1]), Math.atan2(w[1], 1 + w[0])];

// ψ(u − i/2) som [re, im]. Skrevet slik at ingen ledd kansellerer når σ_v → 0:
//   ξ = κ − ρσ/2 − iρσu,  d = √(ξ² + σ²(u² + ¼)),  ξ − d = −σ²(u² + ¼)/(ξ + d),  g = (ξ − d)/(ξ + d)
//   D = −(u² + ¼)/(ξ + d) · (1 − e^{−dT})/(1 − g e^{−dT})
//   C = κθ [−(u² + ¼)T/(ξ + d) − 2 ln(1 + w)/σ²],  w = g(1 − e^{−dT})/(1 − g)
function hestonPsiShifted(u, T, v0, kappa, theta, sig, rho) {
  const q = u * u + 0.25;
  const s2 = sig * sig;
  const xi = [kappa - 0.5 * rho * sig, -rho * sig * u];
  const xi2 = cmul(xi, xi);
  const d = csqrt([xi2[0] + s2 * q, xi2[1]]);
  const sum = [xi[0] + d[0], xi[1] + d[1]];
  const fac = cdiv([-q, 0], sum); // (ξ − d)/σ²
  const g = cdiv([s2 * fac[0], s2 * fac[1]], sum);
  const e = cexp([-d[0] * T, -d[1] * T]);
  const ome = [1 - e[0], -e[1]];
  const ge = cmul(g, e);
  const D = cmul(fac, cdiv(ome, [1 - ge[0], -ge[1]]));
  // w/σ² = fac/(ξ + d) · (1 − e)/(1 − g)
  const wOverS2 = cmul(cdiv(fac, sum), cdiv(ome, [1 - g[0], -g[1]]));
  const w = [s2 * wOverS2[0], s2 * wOverS2[1]];
  let LoverS2;
  if (Math.hypot(w[0], w[1]) < 1e-6) {
    // ln(1 + w)/w ≈ 1 − w/2 + w²/3
    const w2 = cmul(w, w);
    LoverS2 = cmul(wOverS2, [1 - 0.5 * w[0] + w2[0] / 3, -0.5 * w[1] + w2[1] / 3]);
  } else {
    const L = clog1p(w);
    LoverS2 = [L[0] / s2, L[1] / s2];
  }
  const kt = kappa * theta;
  const C = [kt * (fac[0] * T - 2 * LoverS2[0]), kt * (fac[1] * T - 2 * LoverS2[1])];
  return cexp([C[0] + D[0] * v0, C[1] + D[1] * v0]);
}

export function hestonExpectedVariance({ T, v0, kappa, theta }) {
  return theta + (v0 - theta) * e1(-kappa * T);
}

export function heston({ type = 'call', S, X, T, r, b, v0, kappa, theta, sigma, rho }) {
  const call = isCall(type);
  if (!(v0 >= 0 && theta >= 0)) throw new Error('Variansene må være ikke-negative.');
  if (!(kappa >= 0)) throw new Error('Mean reversion-hastigheten κ kan ikke være negativ.');
  if (!(sigma >= 0)) throw new Error('Volatiliteten til variansen kan ikke være negativ.');
  if (!(rho >= -1 && rho <= 1)) throw new Error('Korrelasjonen må ligge mellom −1 og 1.');
  if (!(T > 0)) return Math.max(call ? S - X : X - S, 0);
  const vbar = hestonExpectedVariance({ T, v0, kappa, theta });
  if (sigma === 0 || (kappa === 0 && sigma < 1e-10)) return gbsm({ type, S, X, T, r, b, v: Math.sqrt(vbar) });
  const F = S * Math.exp(b * T);
  const k = Math.log(F / X);
  const f = (u) => {
    const [pr, pi] = hestonPsiShifted(u, T, v0, kappa, theta, sigma, rho);
    return (pr * Math.cos(u * k) - pi * Math.sin(u * k)) / (u * u + 0.25);
  };
  // Gauss-Legendre i paneler til integranden er neglisjerbar. Panelene er høyst 4 brede, så både
  // toppen 1/(u² + ¼) nær null og svingningene i e^{iuk} blir godt oppløst.
  const scale = Math.sqrt(Math.max(Math.max(v0, theta, vbar) * T, 1e-6));
  const h = Math.min(4, Math.max(1, 1.5 / scale));
  let integral = 0;
  for (let p = 0; p < 20000; p++) {
    const a = p * h;
    const part = gaussLegendre(f, a, a + h, 32);
    integral += part;
    const [er, ei] = hestonPsiShifted(a + h, T, v0, kappa, theta, sigma, rho);
    const envelope = Math.hypot(er, ei) / ((a + h) ** 2 + 0.25);
    if (envelope * h < 1e-15 && Math.abs(part) < 1e-15) break;
  }
  const c = S * Math.exp((b - r) * T) - Math.sqrt(F * X) * Math.exp(-r * T) * integral / Math.PI;
  if (call) return c;
  return c - S * Math.exp((b - r) * T) + X * Math.exp(-r * T);
}
