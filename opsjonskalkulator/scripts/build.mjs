// Bygger nett-UI-et til én selvstendig HTML-fil.
//   dist/opsjonskalkulator.html  frittstående side (åpnes direkte i nettleseren)
//   dist/artifact.html           samme innhold uten <html>/<head>/<body>, for publisering som Artifact
//   dist/va-formler/opsjonskalkulator/index.html  for https://va-formler.no/opsjonskalkulator/
import { build } from 'esbuild';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, 'dist');

const result = await build({
  entryPoints: [path.join(root, 'web/app.js')],
  bundle: true,
  format: 'iife',
  minify: true,
  target: ['es2020'],
  legalComments: 'none',
  write: false,
});
const js = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
const template = await readFile(path.join(root, 'web/template.html'), 'utf8');
const fragment = template.replace('<!--APP_SCRIPT-->', `<script>\n${js}</script>`);

const cut = fragment.indexOf('</style>') + '</style>'.length;
const head = fragment.slice(0, cut);
const body = fragment.slice(cut);
const full = `<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
${head}
</head>
<body>${body}</body>
</html>
`;

// Versjon for va-formler.no: legges som opsjonskalkulator/index.html i webroten.
const site = full.replace('<meta charset="utf-8">',
  '<meta charset="utf-8">\n<link rel="canonical" href="https://va-formler.no/opsjonskalkulator/">');

await mkdir(path.join(out, 'va-formler', 'opsjonskalkulator'), { recursive: true });
await writeFile(path.join(out, 'artifact.html'), fragment);
await writeFile(path.join(out, 'opsjonskalkulator.html'), full);
await writeFile(path.join(out, 'va-formler', 'opsjonskalkulator', 'index.html'), site);
const kb = (s) => `${(Buffer.byteLength(s) / 1024).toFixed(0)} kB`;
console.log(`dist/opsjonskalkulator.html (${kb(full)}), dist/artifact.html (${kb(fragment)})`);
