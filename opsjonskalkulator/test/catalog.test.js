// Generiske tester for alle kalkulatorene i katalogen:
// unike id-er, gyldige inndata, endelige resultater og at bokas eksempler stemmer.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CALCULATORS, CHAPTERS } from '../src/catalog/index.js';
import { defaultParams, validate, resultEntries, exampleEntries } from '../src/catalog/params.js';

test('katalogen er gyldig', () => {
  const ids = new Set();
  const chapters = new Set(CHAPTERS.map((c) => c.n));
  for (const c of CALCULATORS) {
    assert.ok(/^[a-z0-9-]+$/.test(c.id), `ugyldig id ${c.id}`);
    assert.ok(!ids.has(c.id), `duplisert id ${c.id}`);
    ids.add(c.id);
    assert.ok(chapters.has(c.chapter), `${c.id}: ukjent kapittel ${c.chapter}`);
    assert.ok(c.name && c.description && c.authors, `${c.id}: mangler navn, beskrivelse eller forfattere`);
    assert.equal(typeof c.compute, 'function', `${c.id}: mangler compute`);
    const keys = new Set();
    for (const inp of c.inputs) {
      assert.ok(!keys.has(inp.key), `${c.id}: duplisert input ${inp.key}`);
      keys.add(inp.key);
      assert.ok(inp.label, `${c.id}.${inp.key}: mangler label`);
      assert.ok(['number', 'int', 'select', 'list'].includes(inp.type), `${c.id}.${inp.key}: ukjent type ${inp.type}`);
    }
  }
});

for (const c of CALCULATORS) {
  test(`${c.id}: standardinput gir endelige resultater`, () => {
    const p = defaultParams(c);
    assert.deepEqual(validate(c, p), [], `${c.id}: standardverdiene er ugyldige`);
    const entries = resultEntries(c.compute(p));
    assert.ok(entries.length > 0, `${c.id}: tomt resultat`);
    const [label, value] = entries[0];
    assert.ok(typeof value === 'number' && Number.isFinite(value), `${c.id}: hovedresultatet «${label}» er ${value}`);
    for (const [l, val] of entries) {
      assert.ok(typeof val === 'string' || Number.isFinite(val), `${c.id}: «${l}» er ${val}`);
    }
    const res = Object.fromEntries(entries);
    for (const [key, expected] of exampleEntries(c)) {
      const actual = key === null ? value : res[key];
      const tol = c.exampleTol ?? 1.01e-4;
      assert.ok(
        Math.abs(actual - expected) <= tol,
        `${c.id}: bokas eksempel ${key ?? label} = ${expected}, men kalkulatoren gir ${actual}`,
      );
    }
  });
}
