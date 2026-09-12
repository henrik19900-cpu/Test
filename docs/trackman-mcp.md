# Trackman MCP (golf-coach)

MCP-server som henter dine egne Trackman Golf-stats (handicap, runder, økter,
shot-nivå launch monitor-data, club gapping) og eksponerer dem som MCP-verktøy.

- Prosjekt: https://github.com/bjornj12/golf-coach
- Pakke: [`golf-coach`](https://pypi.org/project/golf-coach/) (PyPI, v0.7.0, MIT)
- Kjøres med [`uv`](https://docs.astral.sh/uv/): `uvx golf-coach`

> **Uoffisiell.** Prosjektet er ikke tilknyttet Trackman. Det snakker med
> Trackmans private web-API med et token fra din egen innloggede sesjon. Det kan
> være i strid med Trackmans vilkår — bruk det kun på din egen konto, på eget
> ansvar.

## Oppsett i dette repoet

`.mcp.json` i rota er allerede konfigurert, så en Claude Code-sesjon i dette
repoet plukker opp serveren automatisk. Eneste forutsetning er `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Vil du låse versjonen, bytt `"args": ["golf-coach"]` til
`"args": ["golf-coach@0.7.0"]`.

## Alternativ: plugin i Claude Code (server + coaching-skills)

Gir både MCP-serveren og de ti coaching-skillsene:

```text
/plugin marketplace add bjornj12/golf-coach
/plugin install golf-coach@golf-coach
```

## Alternativ: Claude Desktop

Last ned `golf-coach.mcpb` fra
https://github.com/bjornj12/golf-coach/releases/latest og dra den inn i
**Settings → Extensions**. La token-feltet stå tomt.

## Innlogging (engangsjobb)

> Innloggingen **må skje på din egen maskin** — den åpner et nettleservindu der
> du skriver inn Trackman-brukeren din. En remote Claude Code-sesjon i skyen har
> ingen skjerm du kan se det vinduet på, og tokenet ville forsvunnet med
> containeren.

Alt-i-ett, lokalt:

```bash
bash scripts/setup-trackman.sh
```

Skriptet installerer `uv` hvis den mangler, installerer `golf-coach[login]` og
åpner nettleseren. Trenger ikke Chrome — Playwright henter Chromium selv.

### Eller: si det til Claude

Si **"log in to Trackman"** til Claude (lokal Claude Code eller Claude Desktop). Et browser-vindu åpnes (isolert profil),
du logger inn én gang med din Trackman-konto (Apple/Google-innlogging fungerer
også). Tokenet caches i `~/.golf-coach/token.json` (mode `0600`) og fornyes
selv. Passordet ditt ser eller lagrer verktøyet aldri.

Fra terminal i stedet:

```bash
uv tool install "golf-coach[login]"
golf-coach login              # åpner browser, logg inn én gang
golf-coach login --headless   # stille fornyelse senere (token varer ~7 dager)
```

Sjekk at det virker: spør Claude *"Am I signed in to Trackman?"* — den kjører
`auth(action="status")` og svarer med navnet ditt (aldri tokenet).

## Verktøy (8)

| Verktøy | Hva det gjør |
|---------|--------------|
| `setup` | Returnerer system-prompt, skills som filer, og klient-spesifikke steg |
| `auth` | `status \| login` |
| `trackman` | `profile \| handicap \| sessions \| session \| rounds \| clubs \| summary` (read-only) |
| `gamebook` | `save \| list \| get \| compare` — runder fra Golf GameBook-screenshots |
| `synthesize` | Sammenstiller funn fra Trackman og GameBook per ferdighetsområde |
| `session_analysis` | `analyze \| get \| list` |
| `training_plan` | `save \| next \| list \| done \| verify` |
| `build_visualization` | Animert HTML-artifact av ballflukt/diagnose |

Verktøyene returnerer rådata; all coaching ligger i skillsene.

## Hvis du vil ha kildekoden lokalt

```bash
git clone https://github.com/bjornj12/golf-coach.git
```
