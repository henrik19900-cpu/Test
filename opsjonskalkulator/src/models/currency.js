// Kapittel 5: valutaoversatte opsjoner.
//
// Notasjon som i Haug: S er prisen på et utenlandsk aktivum i utenlandsk valuta,
// E er valutakursen (innenlandsk valuta per enhet utenlandsk valuta), r er innenlandsk
// og rf utenlandsk risikofri rente, q er utbytteavkastningen på det utenlandske aktivumet,
// vS og vE er volatilitetene til S og E, og rho er korrelasjonen mellom avkastningene
// til S og E. Alle priser er i innenlandsk valuta.

import { cnd, cbnd } from '../math/normal.js';
import { gbsm, isCall } from './bsm.js';

// Utenlandsk aksje med innløsningskurs i innenlandsk valuta (Reiner 1992):
// utbetaling max(E_T·S_T − X, 0). E·S er et innenlandsk aktivum med utbytte q.
export function foreignEquityDomesticStrike({ type = 'call', E, S, X, T, r, q, vS, vE, rho }) {
  const v = Math.sqrt(Math.max(0, vS * vS + vE * vE + 2 * rho * vS * vE));
  return { price: gbsm({ type, S: E * S, X, T, r, b: r - q, v }), v };
}

// Quanto: utenlandsk aksjeopsjon med fast valutakurs Ep, utbetaling Ep·max(S_T − X, 0).
// Under innenlandsk risikonøytralt mål har S cost of carry rf − q − ρ·vS·vE.
export function quanto({ type = 'call', Ep, S, X, T, r, rf, q, vS, vE, rho }) {
  const bq = rf - q - rho * vS * vE;
  return { price: Ep * gbsm({ type, S, X, T, r, b: bq, v: vS }), b: bq };
}

// Equity-linked FX-opsjon: utbetaling S_T·max(E_T − X, 0) (call) eller S_T·max(X − E_T, 0) (put),
// dvs. en valutaopsjon på et antall enheter som følger den utenlandske aksjen.
export function equityLinkedFX({ type = 'call', E, S, X, T, r, rf, q, vS, vE, rho }) {
  const vst = vE * Math.sqrt(T);
  const d1 = (Math.log(E / X) + (r - rf + rho * vS * vE + 0.5 * vE * vE) * T) / vst;
  const d2 = d1 - vst;
  const a = E * S * Math.exp(-q * T);
  const c = X * S * Math.exp((rf - r - q - rho * vS * vE) * T);
  if (isCall(type)) return a * cnd(d1) - c * cnd(d2);
  return c * cnd(-d2) - a * cnd(-d1);
}

// Takeover-valutaopsjon (Schnabel og Wei 1994): retten til å kjøpe N enheter utenlandsk
// valuta til kurs X ved T, men bare hvis oppkjøpet lykkes, dvs. hvis verdien V_T av det
// utenlandske selskapet (i utenlandsk valuta) er under budet K. Utbetaling N·max(E_T − X, 0)·1{V_T < K}.
export function takeoverFX({ V, K, N, E, X, T, r, rf, vV, vE, rho }) {
  const sT = Math.sqrt(T);
  const a1 = (Math.log(V / K) + (rf - rho * vE * vV - 0.5 * vV * vV) * T) / (vV * sT);
  const a2 = (Math.log(E / X) + (r - rf - 0.5 * vE * vE) * T) / (vE * sT);
  const price = N * (E * Math.exp(-rf * T) * cbnd(a2 + vE * sT, -a1 - rho * vE * sT, -rho)
    - X * Math.exp(-r * T) * cbnd(-a1, a2, -rho));
  return { price, prob: cnd(-a1) };
}
