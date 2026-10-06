// Standardverdier, tolking og validering av inndata. Brukes av både UI og tester.

export function defaultParams(calc) {
  const p = {};
  for (const inp of calc.inputs) p[inp.key] = Array.isArray(inp.default) ? [...inp.default] : inp.default;
  return p;
}

// Godtar både komma og punktum som desimaltegn, og vanlig minus eller U+2212.
export function parseNumber(str) {
  if (typeof str === 'number') return str;
  const s = String(str).trim().replace(/−/g, '-').replace(/\s/g, '').replace(',', '.');
  if (s === '' || !/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return NaN;
  return Number(s);
}

// Tallrekke skilt med semikolon, linjeskift eller mellomrom.
export function parseList(str) {
  if (Array.isArray(str)) return str;
  const parts = String(str).split(/[;\n\t ]+/).map((x) => x.trim()).filter(Boolean);
  return parts.map(parseNumber);
}

export function formatInput(inp, value) {
  if (inp.type === 'list') return value.map((x) => String(x).replace('.', ',')).join('; ');
  if (inp.type === 'select') return value;
  return String(value).replace('.', ',');
}

export function validate(calc, params) {
  const errors = [];
  for (const inp of calc.inputs) {
    const val = params[inp.key];
    const name = inp.label;
    if (inp.type === 'select') {
      if (!inp.options.some((o) => o.value === val)) errors.push(`${name}: ugyldig valg.`);
      continue;
    }
    if (inp.type === 'list') {
      if (!Array.isArray(val) || val.some((x) => !Number.isFinite(x))) {
        errors.push(`${name}: skriv tall skilt med semikolon, for eksempel 2,5; 3.`);
        continue;
      }
      if (inp.minLength !== undefined && val.length < inp.minLength) {
        errors.push(`${name}: trenger minst ${inp.minLength} tall.`);
      }
      continue;
    }
    if (!Number.isFinite(val)) {
      errors.push(`${name}: skriv et tall.`);
      continue;
    }
    if (inp.type === 'int' && !Number.isInteger(val)) errors.push(`${name}: må være et heltall.`);
    if (inp.min !== undefined) {
      if (inp.exclusiveMin ? !(val > inp.min) : !(val >= inp.min)) {
        errors.push(`${name}: må være ${inp.exclusiveMin ? 'større enn' : 'minst'} ${String(inp.min).replace('.', ',')}.`);
      }
    }
    if (inp.max !== undefined) {
      if (inp.exclusiveMax ? !(val < inp.max) : !(val <= inp.max)) {
        errors.push(`${name}: må være ${inp.exclusiveMax ? 'mindre enn' : 'høyst'} ${String(inp.max).replace('.', ',')}.`);
      }
    }
  }
  return errors;
}

// Normaliserer resultatet fra compute til en liste av [etikett, verdi].
export function resultEntries(res) {
  if (typeof res === 'number') return [['Pris', res]];
  return Object.entries(res);
}

export function exampleEntries(calc) {
  if (calc.example === undefined) return [];
  if (typeof calc.example === 'number') return [[null, calc.example]];
  return Object.entries(calc.example);
}
