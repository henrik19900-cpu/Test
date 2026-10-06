import { gbsmGreeks, strikeFromDelta, atmForwardApprox, impliedVolGBSM } from '../models/bsm.js';
import { callPut, num, S, X, T, r, b, v } from './common.js';

export default [
  {
    id: 'greeks-all',
    chapter: 2,
    group: 'Analytiske Greeks',
    name: 'Alle Greeks',
    authors: 'Haug (2007), kap. 2',
    description: 'Pris og alle analytiske følsomheter for generalisert BSM. Tidsderivater er per år når tiden går (−∂/∂T).',
    inputs: [callPut('call'), S(105), X(100), T(0.5), r(0.1), b(0), v(0.36)],
    compute: (p) => {
      const g = gbsmGreeks(p);
      return {
        'Pris': g.price,
        'Delta': g.delta,
        'Elastisitet (lambda)': g.elasticity,
        'Vanna (∂Delta/∂σ)': g.vanna,
        '∂Vanna/∂σ': g.dvannaDvol,
        'Charm (∂Delta/∂t)': g.charm,
        'Gamma': g.gamma,
        'GammaP': g.gammaP,
        'Zomma (∂Gamma/∂σ)': g.zomma,
        'ZommaP': g.zommaP,
        'Speed (∂Gamma/∂S)': g.speed,
        'SpeedP': g.speedP,
        'Color (∂Gamma/∂t)': g.color,
        'ColorP': g.colorP,
        'Vega': g.vega,
        'VegaP': g.vegaP,
        'Vega-elastisitet': g.vegaLeverage,
        'Vomma (∂Vega/∂σ)': g.vomma,
        'VommaP': g.vommaP,
        'Ultima (∂Vomma/∂σ)': g.ultima,
        'Veta (∂Vega/∂t)': g.veta,
        'Variansvega': g.varianceVega,
        '∂Delta/∂varians': g.ddeltaDvar,
        'Variansvomma': g.varianceVomma,
        'Variansultima': g.varianceUltima,
        'Theta (per år)': g.theta,
        'Theta (per dag)': g.thetaDay,
        'Driftløs theta': g.driftlessTheta,
        'Rho': g.rho,
        'Futures-rho (b fast)': g.futuresRho,
        'Carry-rho (∂/∂b)': g.carryRho,
        'Phi (∂/∂q)': g.phi,
        'Strike-delta (∂/∂X)': g.strikeDelta,
        'Risikonøytral tetthet (∂²c/∂X²)': g.rnd,
        'P(i pengene ved forfall)': g.itmProb,
        '∂P(ITM)/∂σ': g.dzetaDvol,
        '∂P(ITM)/∂t': g.dzetaDtime,
        'P(noen gang i pengene)': g.hitProb,
        'Delta-speilstrike': g.deltaMirrorStrike,
        'Spot med maks gamma': g.maxGammaSpot,
        'Spot med maks vega': g.maxVegaSpot,
        'd1': g.d1,
        'd2': g.d2,
      };
    },
    example: { 'Delta': 0.5946 },
  },
  {
    id: 'greeks-strike-from-delta',
    chapter: 2,
    group: 'Analytiske Greeks',
    name: 'Innløsningskurs fra delta',
    authors: 'Haug (2007), kap. 2',
    description: 'Finn innløsningskursen som gir en ønsket delta, slik valutamarkedet kvoterer opsjoner.',
    inputs: [callPut('call'), S(1.35, 'Spot S'), T(0.5), r(0.05), b(0.02), v(0.1), num('delta', 'Ønsket delta', 0.25)],
    compute: (p) => {
      const K = strikeFromDelta(p);
      const g = gbsmGreeks({ type: p.type, S: p.S, X: K, T: p.T, r: p.r, b: p.b, v: p.v });
      return { 'Innløsningskurs X': K, 'Kontroll: delta ved X': g.delta, 'Pris ved X': g.price };
    },
  },
  {
    id: 'greeks-atm-approx',
    chapter: 2,
    group: 'Tilnærminger',
    name: 'ATM-forward-tilnærminger',
    authors: 'Haug (2007), kap. 2',
    description: 'Tommelfingerregler for en opsjon med innløsningskurs lik forwardprisen, X = S e^{bT}: pris ≈ 0,4 · S e^{(b−r)T} σ√T.',
    inputs: [S(100), T(0.5), r(0.05), b(0.05), v(0.2)],
    compute: (p) => {
      const a = atmForwardApprox(p);
      const exact = gbsmGreeks({ type: 'call', S: p.S, X: p.S * Math.exp(p.b * p.T), T: p.T, r: p.r, b: p.b, v: p.v });
      return {
        'Pris (tilnærmet)': a.price,
        'Pris (eksakt call)': exact.price,
        'Delta call (tilnærmet)': a.deltaCall,
        'Delta put (tilnærmet)': a.deltaPut,
        'Gamma (tilnærmet)': a.gamma,
        'Vega (tilnærmet)': a.vega,
        'Driftløs theta (tilnærmet)': a.thetaDriftless,
      };
    },
  },
  {
    id: 'greeks-implied-vol',
    chapter: 2,
    group: 'Implisitt volatilitet',
    name: 'Implisitt volatilitet (GBSM)',
    authors: 'Newton-Raphson med Brent som sikkerhetsnett',
    description: 'Finn volatiliteten som gir observert opsjonspris i generalisert BSM.',
    inputs: [callPut('call'), S(59), X(60), T(0.25), r(0.067), b(0.067), num('price', 'Observert opsjonspris', 2.82, { min: 0 })],
    compute: (p) => {
      const iv = impliedVolGBSM(p);
      const g = gbsmGreeks({ type: p.type, S: p.S, X: p.X, T: p.T, r: p.r, b: p.b, v: iv });
      return { 'Implisitt volatilitet': iv, 'Vega ved løsningen': g.vega, 'Kontroll: modellpris': g.price };
    },
  },
];
