// Universal design check (WCAG 2.1 A and AA, which Norwegian law requires, plus axe's best practices): the
// main pages, logged out and logged in as the demo user, on a desktop and on a 320 px wide phone, in light and
// dark mode. Fails on any violation, on a page that scrolls sideways, or on a server error.
// Run against a site with demo data: node tests/a11y/audit.mjs http://127.0.0.1:8010
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';

const base = process.argv[2] || 'http://127.0.0.1:8010';
const axe = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8');
const tags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'];
const anonymous = ['/', '/sok', '/sok?q=sykkel', '/logg-inn', '/registrer', '/glemt-passord', '/hjelp', '/vilkar',
  '/om', '/for-agenter', '/for-bedrifter', '/trygg-handel', '/finnes-ikke'];
const loggedIn = ['/min-side', '/meldinger', '/favoritter', '/lagrede-sok', '/ny-annonse', '/ny-annonse?category=sykler'];
const problems = [];
let checked = 0;

async function audit(context, path, label) {
  const page = await context.newPage();
  const response = await page.goto(base + path);
  if (response.status() >= 500) problems.push(`${label} ${path}: HTTP ${response.status()}`);
  await page.addScriptTag({ content: axe });
  const violations = await page.evaluate(
    async (tags) => (await axe.run(document, { runOnly: { type: 'tag', values: tags } })).violations
      .map((v) => `${v.id} (${v.impact}, ${v.nodes.length}×): ${v.help}. E.g. ${v.nodes[0].target.join(' ')}`),
    tags,
  );
  for (const v of violations) problems.push(`${label} ${path}: ${v}`);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (wide > 1) problems.push(`${label} ${path}: scrolls ${wide} px sideways`);
  checked += 1;
  await page.close();
}

async function hrefs(context, path, selector) {
  const page = await context.newPage();
  await page.goto(base + path);
  const found = await page.$$eval(selector, (links) => links.map((a) => a.getAttribute('href')));
  await page.close();
  return found;
}

const browser = await chromium.launch();
for (const [screen, viewport] of [['desktop', { width: 1280, height: 900 }], ['phone', { width: 320, height: 700 }]]) {
  for (const colorScheme of ['light', 'dark']) {
    const label = `${screen} ${colorScheme}`;
    const options = { viewport, colorScheme, bypassCSP: true }; // the site's CSP would block the checker itself
    const visitor = await browser.newContext(options);
    const listings = (await hrefs(visitor, '/sok', 'a.card-link')).slice(0, 2);
    for (const path of [...anonymous, ...listings]) await audit(visitor, path, `${label} logged out`);
    await visitor.close();

    const user = await browser.newContext(options);
    const login = await user.newPage();
    await login.goto(base + '/logg-inn');
    await login.fill('input[name=email]', 'demo@gratistorget.no');
    await login.fill('input[name=password]', 'demo1234');
    await Promise.all([login.waitForNavigation(), login.click('form[action="/logg-inn"] button[type=submit]')]);
    await login.close();
    const own = (await hrefs(user, '/min-side', 'a[href^="/annonse/"]')).find((h) => /^\/annonse\/\d+$/.test(h));
    const conversation = (await hrefs(user, '/meldinger', 'a[href^="/meldinger/"]'))[0];
    const extra = [own, own && `${own}/rediger`, conversation].filter(Boolean);
    for (const path of [...loggedIn, ...extra]) await audit(user, path, `${label} logged in`);
    await user.close();
  }
}
await browser.close();
console.log(`${checked} pages checked`);
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log('No accessibility problems found.');
