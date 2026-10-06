// Samler alle kalkulatorene. Rekkefølgen her er rekkefølgen i menyen.
import ch01 from './ch01-bsm.js';
import ch02 from './ch02-greeks.js';
import ch03 from './ch03-american.js';
import ch04a from './ch04-exotics.js';
import ch04b from './ch04-barriers.js';
import ch05 from './ch05-two-asset.js';
import ch06 from './ch06-alternatives.js';
import ch07 from './ch07-lattice.js';
import ch08 from './ch08-monte-carlo.js';
import ch09 from './ch09-dividends.js';
import ch10 from './ch10-commodity.js';
import ch11 from './ch11-rates.js';
import ch12 from './ch12-volatility.js';
import ch13 from './ch13-distributions.js';
import ch14 from './ch14-formulas.js';

export { CHAPTERS } from './chapters.js';

export const CALCULATORS = [
  ...ch01, ...ch02, ...ch03, ...ch04a, ...ch04b, ...ch05, ...ch06, ...ch07,
  ...ch08, ...ch09, ...ch10, ...ch11, ...ch12, ...ch13, ...ch14,
];
