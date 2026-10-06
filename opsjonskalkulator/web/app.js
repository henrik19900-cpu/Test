// Nett-UI: register over alle kalkulatorene, generiske skjema, resultater,
// numeriske følsomheter og en graf over pris mot spot.
import { CALCULATORS, CHAPTERS } from '../src/catalog/index.js';
import { defaultParams, parseNumber, parseList, validate, resultEntries, exampleEntries } from '../src/catalog/params.js';

const byId = new Map(CALCULATORS.map((c) => [c.id, c]));
const chapterTitle = new Map(CHAPTERS.map((c) => [c.n, c.title]));
const SPOT_KEYS = ['S', 'F', 'S1'];
const GAMMA_KEYS = new Set(['S', 'F', 'S1', 'S2']);

const $ = (id) => document.getElementById(id);
const SVG_TAGS = new Set(['g', 'path', 'line', 'text', 'circle', 'rect']);

function el(tag, attrs = {}, ...children) {
  const node = document.createElementNS(tag === 'svg' || SVG_TAGS.has(tag) ? 'http://www.w3.org/2000/svg' : 'http://www.w3.org/1999/xhtml', tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v === undefined || v === null) continue;
    node.setAttribute(k, v === true ? '' : String(v));
  }
  for (const ch of children.flat()) {
    if (ch === null || ch === undefined || ch === false) continue;
    node.append(typeof ch === 'string' || typeof ch === 'number' ? document.createTextNode(String(ch)) : ch);
  }
  return node;
}

// ---------- Tallformat ----------
const NF_FIXED = new Intl.NumberFormat('nb-NO', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
const NF_SIG = new Intl.NumberFormat('nb-NO', { maximumSignificantDigits: 4 });
const NF_PCT = new Intl.NumberFormat('nb-NO', { maximumFractionDigits: 4 });
const SUP = { '-': '⁻', 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹' };

export function fmt(x) {
  if (typeof x === 'string') return x;
  if (typeof x !== 'number' || !Number.isFinite(x)) return '–';
  const a = Math.abs(x);
  if (a === 0) return NF_FIXED.format(0);
  if (a >= 1e9 || a < 1e-6) {
    const [m, e] = x.toExponential(3).split('e');
    const exp = String(Number(e)).split('').map((c) => SUP[c]).join('');
    return `${m.replace('.', ',').replace('-', '−')} × 10${exp}`;
  }
  if (a < 0.01) return NF_SIG.format(x);
  return NF_FIXED.format(x);
}

function fmtInputValue(inp, value) {
  if (inp.type === 'select') return value;
  if (inp.type === 'list') return value.map((x) => fmtNum(x)).join('; ');
  return fmtNum(value);
}
function fmtNum(x) {
  return String(Number(Number(x).toPrecision(12))).replace('.', ',');
}

function axisFormatter(step) {
  const decimals = Math.min(6, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)));
  const nf = new Intl.NumberFormat('nb-NO', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return (v) => nf.format(v);
}

// Gjør S_T, e^{−rT} osv. om til senket og hevet skrift. Teksten kommer fra katalogen.
const RICH = /_\{([^}]*)\}|_([A-Za-z0-9αβγδσρλμνθτ]+)|\^\{([^}]*)\}|\^([A-Za-z0-9−\-+]+)/g;
function rich(str) {
  const text = String(str ?? '');
  const nodes = [];
  let last = 0;
  for (const m of text.matchAll(RICH)) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const sub = m[1] ?? m[2];
    nodes.push(sub !== undefined ? el('sub', {}, sub) : el('sup', {}, m[3] ?? m[4]));
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

const lowerFirst = (s) => (/^[A-ZÆØÅ][a-zæøå]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);

const norm = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

// ---------- Tilstand ----------
let current = null;
let raw = {};
let timer = null;
let chartState = null;

// ---------- Register ----------
function orderedItems(chapterN) {
  const items = CALCULATORS.filter((c) => c.chapter === chapterN);
  const firstIdx = new Map();
  items.forEach((c, i) => { if (!firstIdx.has(c.group)) firstIdx.set(c.group, i); });
  return items
    .map((c, i) => ({ c, i }))
    .sort((a, b) => firstIdx.get(a.c.group) - firstIdx.get(b.c.group) || a.i - b.i)
    .map((x) => x.c);
}

function matches(c, q) {
  if (!q) return true;
  const hay = norm([c.name, c.authors, c.group, c.description, c.id, chapterTitle.get(c.chapter), `kapittel ${c.chapter}`].join(' '));
  return q.split(/\s+/).every((w) => hay.includes(w));
}

function renderIndex() {
  const q = norm($('q').value.trim());
  const list = $('list');
  list.textContent = '';
  let shown = 0;
  let chapters = 0;
  for (const ch of CHAPTERS) {
    const all = orderedItems(ch.n);
    const items = all.filter((c) => matches(c, q));
    if (!items.length) continue;
    chapters++;
    const groups = new Set(all.map((c) => c.group));
    const sec = el('section', { class: 'chap' });
    sec.append(el('h2', { class: 'chap-head' }, el('span', { class: 'chap-num' }, String(ch.n)), ch.title));
    let lastGroup;
    for (const c of items) {
      if (groups.size > 1 && c.group && c.group !== lastGroup) sec.append(el('p', { class: 'group-label' }, c.group));
      lastGroup = c.group;
      const a = el('a', { class: 'item', href: `#${c.id}` }, c.name, el('small', {}, c.authors));
      if (current && current.id === c.id) a.setAttribute('aria-current', 'page');
      sec.append(a);
    }
    list.append(sec);
    shown += items.length;
  }
  $('count').textContent = q
    ? `${shown} av ${CALCULATORS.length} kalkulatorer`
    : `${CALCULATORS.length} kalkulatorer i ${chapters} kapitler`;
  if (!shown) list.append(el('p', { class: 'empty' }, 'Ingen treff. Prøv et annet ord, for eksempel «barriere» eller «asiatisk».'));
}

function markCurrent() {
  for (const a of document.querySelectorAll('.item')) {
    if (current && a.getAttribute('href') === `#${current.id}`) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
}

// ---------- Regneark ----------
function openCalc(calc, savedRaw) {
  current = calc;
  raw = {};
  for (const inp of calc.inputs) raw[inp.key] = fmtInputValue(inp, inp.default);
  if (savedRaw) for (const k of Object.keys(raw)) if (typeof savedRaw[k] === 'string') raw[k] = savedRaw[k];
  chartState = null;
  renderSheet(calc);
  markCurrent();
  run();
}

function renderSheet(calc) {
  const sheet = $('sheet');
  sheet.textContent = '';
  const art = el('article', { class: 'calc' });
  art.append(el('a', { class: 'back', href: '#' }, '← Alle kalkulatorer'));

  const head = el('header', { class: 'head' },
    el('p', { class: 'eyebrow' }, `Kapittel ${calc.chapter} · ${calc.group || chapterTitle.get(calc.chapter)}`),
    el('h1', { class: 'title' }, calc.name),
    el('p', { class: 'authors' }, calc.authors),
    el('p', { class: 'desc' }, rich(calc.description)));
  if (calc.payoff) head.append(el('p', { class: 'payoff' }, el('span', {}, 'Utbetaling'), el('em', {}, rich(calc.payoff))));
  art.append(head);

  const form = el('form', { class: 'inputs', novalidate: true, 'aria-label': 'Inndata' });
  form.addEventListener('submit', (e) => e.preventDefault());
  const fields = el('div', { class: 'fields' });
  for (const inp of calc.inputs) fields.append(renderField(calc, inp));
  const reset = el('button', { type: 'button', class: 'btn', id: `reset-${calc.id}` },
    calc.example !== undefined ? 'Tilbakestill til bokas eksempel' : 'Tilbakestill');
  reset.addEventListener('click', () => openCalc(calc));
  form.append(fields, el('div', { class: 'actions' }, reset,
    el('span', { class: 'note' }, 'Desimalkomma eller punktum. Renter og volatilitet som desimaltall: 0,08 = 8 %.')));

  const results = el('section', { class: 'results', id: 'results', 'aria-live': 'polite', 'aria-label': 'Resultat' });
  art.append(el('div', { class: 'work' }, form, results));

  if (calc.chart !== false && chartKey(calc)) {
    const key = chartKey(calc);
    const label = calc.inputs.find((i) => i.key === key).label;
    art.append(el('section', { class: 'panel', id: 'chart-panel' },
      el('h2', { id: 'chart-title' }, 'Pris mot spot'),
      el('p', { class: 'sub', id: 'chart-sub' }, `${label} fra 50 % til 150 % av dagens verdi. Loddrett strek: dagens verdi.`),
      el('div', { class: 'chart-wrap', id: 'chart-wrap' }),
      el('details', { id: 'chart-table' }, el('summary', {}, 'Vis tallene'), el('div', { class: 'table-wrap', id: 'chart-table-body' }))));
  }
  if (calc.greeks !== false) {
    art.append(el('section', { class: 'panel', id: 'sens-panel' },
      el('h2', {}, 'Følsomheter'),
      el('p', { class: 'sub' }, 'Numeriske derivater av hovedresultatet: hver input flyttes litt opp og ned.'),
      el('div', { class: 'table-wrap', id: 'sens-body' })));
  }
  sheet.append(art);
}

function renderField(calc, inp) {
  const id = `in-${calc.id}-${inp.key}`;
  if (inp.type === 'select' && inp.options.length <= 3) {
    const fs = el('fieldset', { class: 'seg field wide' }, el('legend', {}, inp.label));
    const opts = el('div', { class: 'seg-options' });
    inp.options.forEach((o, i) => {
      const radio = el('input', { type: 'radio', name: id, id: `${id}-${i}`, value: o.value });
      radio.checked = raw[inp.key] === o.value;
      radio.addEventListener('change', () => {
        raw[inp.key] = o.value;
        schedule(0);
      });
      opts.append(el('label', { for: `${id}-${i}` }, radio, el('span', {}, o.label)));
    });
    fs.append(opts);
    return fs;
  }
  if (inp.type === 'select') {
    const sel = el('select', { id }, inp.options.map((o) => el('option', { value: o.value }, o.label)));
    sel.value = raw[inp.key];
    sel.addEventListener('change', () => {
      raw[inp.key] = sel.value;
      schedule(0);
    });
    return el('div', { class: 'field wide' }, el('label', { for: id }, inp.label), sel);
  }
  const input = el('input', {
    type: 'text',
    id,
    inputmode: inp.type === 'list' ? 'text' : inp.type === 'int' ? 'numeric' : 'decimal',
    autocomplete: 'off',
    autocapitalize: 'off',
    spellcheck: 'false',
    'data-key': inp.key,
  });
  input.value = raw[inp.key];
  const hint = el('span', { class: 'hint', id: `${id}-hint` });
  const updateHint = () => {
    if (inp.help) {
      hint.textContent = inp.help;
      return;
    }
    if (inp.type === 'list') {
      hint.textContent = 'Skill tallene med semikolon.';
      return;
    }
    if (inp.unit === 'rate') {
      const x = parseNumber(input.value);
      hint.textContent = Number.isFinite(x) ? `= ${NF_PCT.format(x * 100)} %` : '';
    }
  };
  updateHint();
  input.addEventListener('input', () => {
    raw[inp.key] = input.value;
    updateHint();
    schedule();
  });
  input.setAttribute('aria-describedby', hint.id);
  return el('div', { class: `field${inp.type === 'list' || inp.help ? ' wide' : ''}` },
    el('label', { for: id }, inp.label), input, hint);
}

function readParams(calc) {
  const p = {};
  for (const inp of calc.inputs) {
    const v = raw[inp.key];
    if (inp.type === 'select') p[inp.key] = v;
    else if (inp.type === 'list') p[inp.key] = parseList(v);
    else p[inp.key] = parseNumber(v);
  }
  return p;
}

function atDefaults(calc, p) {
  const d = defaultParams(calc);
  return calc.inputs.every((inp) => {
    const a = p[inp.key];
    const b = d[inp.key];
    if (inp.type === 'list') return a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) <= 1e-12 * Math.max(1, Math.abs(b[i])));
    if (inp.type === 'select') return a === b;
    return Math.abs(a - b) <= 1e-12 * Math.max(1, Math.abs(b));
  });
}

function schedule(delay = 140) {
  clearTimeout(timer);
  timer = setTimeout(run, delay);
}

function mainOf(res) {
  const entries = resultEntries(res);
  return entries.length ? entries[0][1] : NaN;
}

function run() {
  const calc = current;
  if (!calc) return;
  const p = readParams(calc);
  const errors = [];
  for (const inp of calc.inputs) {
    const errs = validate({ inputs: [inp] }, p);
    const field = document.getElementById(`in-${calc.id}-${inp.key}`);
    if (field && field.tagName === 'INPUT') field.setAttribute('aria-invalid', errs.length ? 'true' : 'false');
    errors.push(...errs);
  }
  if (errors.length) {
    showErrors(errors);
    return;
  }
  let res;
  const t0 = performance.now();
  try {
    res = calc.compute(p);
  } catch (e) {
    showErrors([e && e.message ? e.message : String(e)]);
    return;
  }
  const elapsed = performance.now() - t0;
  const entries = resultEntries(res);
  showResults(calc, p, entries);
  const heavy = elapsed > 40;
  if (calc.greeks !== false) renderSens(calc, p, entries, heavy);
  if (calc.chart !== false && chartKey(calc)) renderChart(calc, p, entries, heavy);
}

function showErrors(errors) {
  const box = $('results');
  if (!box) return;
  box.textContent = '';
  box.append(el('div', { class: 'main-label' }, 'Kan ikke regne ut'),
    el('ul', { class: 'errors' }, errors.map((e) => el('li', {}, e))));
  $('mini-label').textContent = 'Rett opp inndata';
  $('mini-value').textContent = '–';
  for (const id of ['sens-body', 'chart-wrap', 'chart-table-body']) {
    const n = document.getElementById(id);
    if (n) n.style.opacity = '0.4';
  }
}

function showResults(calc, p, entries) {
  const box = $('results');
  box.textContent = '';
  const [mainLabel, mainValue] = entries[0];
  box.append(el('div', {}, el('div', { class: 'main-label' }, rich(mainLabel)), el('output', { class: 'main-value' }, fmt(mainValue))));

  const ex = exampleEntries(calc);
  if (ex.length) {
    const res = Object.fromEntries(entries);
    const tol = calc.exampleTol ?? 1.01e-4;
    const values = ex.map(([k, v]) => [k ?? mainLabel, v]);
    const parts = [];
    values.forEach(([k, v], i) => {
      if (i) parts.push(', ');
      parts.push(values.length > 1 || k !== mainLabel ? `${k} ` : '', el('b', {}, fmt(v)));
    });
    if (atDefaults(calc, p)) {
      const ok = ex.every(([k, v]) => Math.abs((k === null ? mainValue : res[k]) - v) <= tol);
      box.append(el('span', { class: `chip ${ok ? 'ok' : 'off'}` }, ok ? '✓ Som i boka: ' : 'Avviker fra boka: ', ...parts));
    } else {
      box.append(el('span', { class: 'chip' }, 'Bokas eksempel med standardverdiene: ', ...parts));
    }
  }

  if (entries.length > 1) {
    const dl = el('dl', { class: 'outputs' });
    for (const [label, value] of entries.slice(1)) dl.append(el('div', {}, el('dt', {}, rich(label)), el('dd', {}, fmt(value))));
    box.append(dl);
  }
  $('mini-label').textContent = '';
  $('mini-label').append(...rich(mainLabel));
  $('mini-value').textContent = fmt(mainValue);
  for (const id of ['sens-body', 'chart-wrap', 'chart-table-body']) {
    const n = document.getElementById(id);
    if (n) n.style.opacity = '';
  }
}

// ---------- Følsomheter ----------
function inRange(inp, x) {
  if (inp.min !== undefined && (inp.exclusiveMin ? !(x > inp.min) : !(x >= inp.min))) return false;
  if (inp.max !== undefined && (inp.exclusiveMax ? !(x < inp.max) : !(x <= inp.max))) return false;
  return true;
}

function sensitivities(calc, p, base) {
  const f = (key, val) => {
    try {
      const v = mainOf(calc.compute({ ...p, [key]: val }));
      return Number.isFinite(v) ? v : NaN;
    } catch {
      return NaN;
    }
  };
  const rows = [];
  for (const inp of calc.inputs) {
    if (inp.type !== 'number') continue;
    const x = p[inp.key];
    const h = 1e-4 * Math.max(Math.abs(x), 0.01);
    const okLo = inRange(inp, x - h);
    const okHi = inRange(inp, x + h);
    let d1 = NaN;
    let d2 = NaN;
    if (okLo && okHi) {
      const fu = f(inp.key, x + h);
      const fd = f(inp.key, x - h);
      d1 = (fu - fd) / (2 * h);
      d2 = (fu - 2 * base + fd) / (h * h);
    } else if (okHi) {
      d1 = (f(inp.key, x + h) - base) / h;
    } else if (okLo) {
      d1 = (base - f(inp.key, x - h)) / h;
    }
    const label = inp.label;
    if (GAMMA_KEYS.has(inp.key)) {
      rows.push([label, 'Delta, per 1,00', d1]);
      rows.push([label, 'Gamma, per 1,00²', d2]);
    } else if (inp.key === 'T') {
      rows.push([label, 'Theta, per dag', -d1 / 365]);
      rows.push([label, '∂/∂T, per år', d1]);
    } else if (inp.unit === 'rate') {
      rows.push([label, 'Per 1 %-poeng', d1 / 100]);
    } else {
      rows.push([label, 'Per 1,00', d1]);
    }
  }
  return rows;
}

function renderSens(calc, p, entries, heavy) {
  const body = $('sens-body');
  if (!body) return;
  body.textContent = '';
  const doIt = () => {
    body.textContent = '';
    const rows = sensitivities(calc, p, entries[0][1]);
    const table = el('table', { class: 'sens' },
      el('thead', {}, el('tr', {}, el('th', {}, 'Inndata og mål'), el('th', {}, rich(`Endring i ${lowerFirst(entries[0][0])}`)))),
      el('tbody', {}, rows.map(([a, b, v]) => el('tr', {}, el('td', {}, a, el('small', {}, b)), el('td', {}, fmt(v))))));
    body.append(table);
  };
  if (heavy) {
    const btn = el('button', { type: 'button', class: 'btn' }, 'Regn ut følsomheter');
    btn.addEventListener('click', doIt);
    body.append(el('div', { class: 'actions' }, btn, el('span', { class: 'note' }, 'Denne modellen er tung å regne, så følsomhetene beregnes på forespørsel.')));
  } else {
    doIt();
  }
}

// ---------- Graf ----------
function chartKey(calc) {
  return SPOT_KEYS.find((k) => calc.inputs.some((i) => i.key === k && i.type === 'number'));
}

function renderChart(calc, p, entries, heavy) {
  const wrap = $('chart-wrap');
  if (!wrap) return;
  const key = chartKey(calc);
  const mainLabel = entries[0][0];
  const build = () => {
    const x0 = p[key];
    const N = 61;
    const pts = [];
    for (let i = 0; i < N; i++) {
      const x = x0 * (0.5 + i / (N - 1));
      let y = NaN;
      try {
        y = mainOf(calc.compute({ ...p, [key]: x }));
      } catch {
        y = NaN;
      }
      pts.push([x, Number.isFinite(y) ? y : NaN]);
    }
    chartState = { pts, x0, y0: entries[0][1], key, mainLabel, idx: Math.round((N - 1) / 2) };
    $('chart-title').textContent = `${mainLabel} mot ${key}`;
    drawChart();
    renderChartTable();
  };
  if (heavy) {
    wrap.textContent = '';
    chartState = null;
    const btn = el('button', { type: 'button', class: 'btn' }, 'Tegn grafen');
    btn.addEventListener('click', build);
    wrap.append(el('div', { class: 'actions' }, btn, el('span', { class: 'note' }, 'Grafen krever 61 beregninger, så den tegnes på forespørsel.')));
    const tb = $('chart-table-body');
    if (tb) tb.textContent = '';
  } else {
    build();
  }
}

function niceTicks(min, max, count) {
  if (!(max > min)) {
    const pad = Math.abs(min) > 0 ? Math.abs(min) * 0.1 : 1;
    min -= pad;
    max += pad;
  }
  const raw0 = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw0));
  const err = raw0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return { ticks, step, lo, hi };
}

function drawChart() {
  const wrap = $('chart-wrap');
  if (!wrap || !chartState) return;
  const { pts, x0, y0, key, mainLabel } = chartState;
  const W = Math.max(280, Math.round(wrap.clientWidth || 600));
  const H = Math.round(Math.min(300, Math.max(200, W * 0.42)));
  const m = { l: 58, r: 14, t: 14, b: 30 };
  const ys = pts.map((d) => d[1]).filter(Number.isFinite);
  wrap.textContent = '';
  if (!ys.length) {
    wrap.append(el('p', { class: 'note' }, 'Modellen gir ingen verdier i dette området.'));
    return;
  }
  let yMin = Math.min(...ys);
  let yMax = Math.max(...ys);
  if (yMin >= 0 && yMin < 0.3 * yMax) yMin = 0;
  const yt = niceTicks(yMin, yMax, 4);
  const xt = niceTicks(pts[0][0], pts[pts.length - 1][0], W < 420 ? 4 : 6);
  const xLo = pts[0][0];
  const xHi = pts[pts.length - 1][0];
  const sx = (x) => m.l + (x - xLo) / (xHi - xLo) * (W - m.l - m.r);
  const sy = (y) => m.t + (yt.hi - y) / (yt.hi - yt.lo) * (H - m.t - m.b);
  const fy = axisFormatter(yt.step);
  const fx = axisFormatter(xt.step);

  const svg = el('svg', {
    viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', tabindex: 0,
    'aria-label': `${mainLabel} som funksjon av ${key}. Bruk piltastene for å lese av verdier.`,
  });
  const grid = el('g', { class: 'grid' });
  const axis = el('g', { class: 'axis' });
  for (const v of yt.ticks) {
    if (v < yt.lo - 1e-12 || v > yt.hi + 1e-12) continue;
    grid.append(el('line', { x1: m.l, x2: W - m.r, y1: sy(v), y2: sy(v) }));
    axis.append(el('text', { x: m.l - 8, y: sy(v) + 4, 'text-anchor': 'end' }, fy(v)));
  }
  for (const v of xt.ticks) {
    if (v < xLo - 1e-9 || v > xHi + 1e-9) continue;
    axis.append(el('text', { x: sx(v), y: H - 8, 'text-anchor': 'middle' }, fx(v)));
  }
  svg.append(grid, el('line', { class: 'baseline', x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }), axis);

  // Linje og vask, med brudd der modellen ikke gir verdi.
  let d = '';
  let area = '';
  let seg = [];
  const flush = () => {
    if (seg.length > 1) {
      d += seg.map(([x, y], i) => `${i ? 'L' : 'M'}${sx(x).toFixed(2)},${sy(y).toFixed(2)}`).join('');
      area += `M${sx(seg[0][0]).toFixed(2)},${sy(yt.lo).toFixed(2)}` +
        seg.map(([x, y]) => `L${sx(x).toFixed(2)},${sy(y).toFixed(2)}`).join('') +
        `L${sx(seg[seg.length - 1][0]).toFixed(2)},${sy(yt.lo).toFixed(2)}Z`;
    }
    seg = [];
  };
  for (const pt of pts) {
    if (Number.isFinite(pt[1])) seg.push(pt);
    else flush();
  }
  flush();
  svg.append(el('path', { class: 'wash', d: area }), el('path', { class: 'series', d }));

  // Dagens verdi
  const nx = sx(x0);
  svg.append(el('line', { class: 'now-line', x1: nx, x2: nx, y1: m.t, y2: H - m.b }));
  if (Number.isFinite(y0)) svg.append(el('circle', { class: 'dot', cx: nx, cy: sy(y0), r: 4.5 }));
  svg.append(el('text', { class: 'now-label', x: nx + 6, y: m.t + 10 }, `${key} = ${fmtNum(x0)}`));

  // Hover-lag
  const cross = el('line', { class: 'cross', x1: 0, x2: 0, y1: m.t, y2: H - m.b, visibility: 'hidden' });
  const hdot = el('circle', { class: 'dot', r: 4.5, visibility: 'hidden' });
  svg.append(cross, hdot);
  const tip = el('div', { class: 'tip', hidden: true });
  const show = (i) => {
    const [x, y] = pts[i];
    chartState.idx = i;
    cross.setAttribute('x1', sx(x));
    cross.setAttribute('x2', sx(x));
    cross.setAttribute('visibility', 'visible');
    tip.textContent = '';
    tip.append(el('strong', {}, fmt(y)), el('span', {}, `${mainLabel} ved ${key} = ${fmtNum(Number(x.toPrecision(6)))}`));
    tip.hidden = false;
    if (Number.isFinite(y)) {
      hdot.setAttribute('cx', sx(x));
      hdot.setAttribute('cy', sy(y));
      hdot.setAttribute('visibility', 'visible');
    } else {
      hdot.setAttribute('visibility', 'hidden');
    }
    const scale = wrap.clientWidth / W;
    const left = Math.min(Math.max(sx(x) * scale, 70), wrap.clientWidth - 70);
    tip.style.left = `${left}px`;
    tip.style.top = `${(Number.isFinite(y) ? sy(y) : m.t + 20) * scale}px`;
  };
  const hide = () => {
    cross.setAttribute('visibility', 'hidden');
    hdot.setAttribute('visibility', 'hidden');
    tip.hidden = true;
  };
  const nearest = (evt) => {
    const rect = svg.getBoundingClientRect();
    const x = (evt.clientX - rect.left) / rect.width * W;
    const t = (x - m.l) / (W - m.l - m.r);
    return Math.max(0, Math.min(pts.length - 1, Math.round(t * (pts.length - 1))));
  };
  svg.addEventListener('pointermove', (e) => show(nearest(e)));
  svg.addEventListener('pointerdown', (e) => show(nearest(e)));
  svg.addEventListener('pointerleave', hide);
  svg.addEventListener('focus', () => show(chartState.idx));
  svg.addEventListener('blur', hide);
  svg.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      show(Math.max(0, Math.min(pts.length - 1, chartState.idx + (e.key === 'ArrowLeft' ? -1 : 1))));
    }
  });
  wrap.append(svg, tip);
}

function renderChartTable() {
  const body = $('chart-table-body');
  if (!body || !chartState) return;
  body.textContent = '';
  const { pts, key, mainLabel } = chartState;
  const rows = pts.filter((_, i) => i % 5 === 0);
  body.append(el('table', {},
    el('thead', {}, el('tr', {}, el('th', {}, key), el('th', {}, mainLabel))),
    el('tbody', {}, rows.map(([x, y]) => el('tr', {}, el('td', {}, fmtNum(Number(x.toPrecision(6)))), el('td', {}, fmt(y)))))));
}

let resizeTimer = null;
const ro = typeof ResizeObserver !== 'undefined'
  ? new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawChart, 80);
  })
  : null;

// ---------- Ruting og oppstart ----------
function route() {
  const id = decodeURIComponent(location.hash.slice(1));
  const calc = byId.get(id);
  const app = $('app');
  if (calc) {
    if (!current || current.id !== calc.id) openCalc(calc);
    app.classList.add('show-sheet');
    window.scrollTo(0, 0);
  } else {
    app.classList.remove('show-sheet');
    if (!current) openCalc(CALCULATORS[0]);
  }
  const wrap = $('chart-wrap');
  if (ro && wrap) ro.observe(wrap);
}

function start(data = {}) {
  $('q').addEventListener('input', renderIndex);
  $('q').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      $('q').value = '';
      renderIndex();
    }
  });
  renderIndex();
  const saved = data && data.id && byId.get(data.id);
  if (saved && !location.hash) {
    openCalc(saved, data.raw);
    $('app').classList.toggle('show-sheet', Boolean(data.sheet));
  }
  window.addEventListener('hashchange', route);
  route();
  const observer = new MutationObserver(() => {
    const wrap = $('chart-wrap');
    if (ro && wrap) ro.observe(wrap);
  });
  observer.observe($('sheet'), { childList: true });
}

const hot = typeof window !== 'undefined' ? window.claude?.hot : undefined;
hot?.snapshot?.(() => ({ id: current?.id, raw, sheet: $('app').classList.contains('show-sheet') }));
if (hot?.ready) hot.ready(start);
else start(hot?.data ?? {});
