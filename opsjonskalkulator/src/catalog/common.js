// Felles byggeklosser for kalkulatordefinisjoner.
//
// En kalkulator er et objekt:
// {
//   id: 'unik-id',                 // små bokstaver og bindestrek, prefikset med område
//   chapter: 4,                    // kapittelnummer i boka (se chapters.js)
//   group: 'Barrierer',            // undergruppe innen kapitlet (valgfri)
//   name: 'Standard barriereopsjon',
//   authors: 'Merton (1973), Reiner og Rubinstein (1991)',
//   description: 'Én til to setninger på norsk om hva opsjonen er.',
//   payoff: 'max(S_T − X, 0) hvis …', // valgfri, kort utbetalingsformel
//   inputs: [ … ],                 // se presetene under
//   compute: (p) => ({ 'Pris': 1.23, 'Delta': 0.5 }),  // første nøkkel er hovedresultatet
//   example: 9.0246,               // bokas tallverdi for standardinputene (valgfri, kun når sikker)
//   greeks: true,                  // numeriske følsomheter i UI (false for trege/stokastiske)
//   chart: true,                   // pris som funksjon av spot i UI (false for trege)
// }
//
// Inndatatyper: 'number' (standard), 'int', 'select', 'list' (tallrekke skilt med semikolon/mellomrom).

export const num = (key, label, def, extra = {}) => ({ key, label, type: 'number', default: def, ...extra });
export const int = (key, label, def, extra = {}) => ({ key, label, type: 'int', default: def, ...extra });
export const list = (key, label, def, extra = {}) => ({ key, label, type: 'list', default: def, ...extra });
export const select = (key, label, options, def, extra = {}) => ({
  key, label, type: 'select', default: def ?? options[0].value, options, ...extra,
});

export const callPut = (def = 'call', key = 'type', label = 'Type') => select(key, label, [
  { value: 'call', label: 'Call (kjøpsopsjon)' },
  { value: 'put', label: 'Put (salgsopsjon)' },
], def);

const pos = { min: 0, exclusiveMin: true };

export const S = (d, label = 'Spotpris S') => num('S', label, d, pos);
export const F = (d, label = 'Futures-/forwardpris F') => num('F', label, d, pos);
export const X = (d, label = 'Innløsningskurs X') => num('X', label, d, pos);
export const T = (d, label = 'Tid til forfall T (år)') => num('T', label, d, pos);
export const r = (d, label = 'Risikofri rente r') => num('r', label, d, { unit: 'rate' });
export const b = (d, label = 'Cost of carry b') => num('b', label, d, {
  unit: 'rate',
  help: 'b = r: aksje uten utbytte · b = r − q: utbytte q · b = 0: futures · b = r − rf: valuta',
});
export const q = (d, label = 'Utbytteavkastning q') => num('q', label, d, { unit: 'rate' });
export const v = (d, label = 'Volatilitet σ', key = 'v') => num(key, label, d, { ...pos, unit: 'rate' });
export const rho = (d, label = 'Korrelasjon ρ', key = 'rho') => num(key, label, d, { min: -1, max: 1 });

// Hjelper for compute: bygger resultatobjekt der første nøkkel er hovedresultatet.
export const result = (pairs) => Object.fromEntries(pairs);
