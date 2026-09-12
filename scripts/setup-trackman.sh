#!/usr/bin/env bash
# Sett opp Trackman MCP (golf-coach) og logg inn.
#
# Kjør dette på DIN EGEN maskin — innloggingen åpner et nettleservindu der du
# skriver inn Trackman-brukeren din. Det kan ikke gjøres fra en remote-sesjon.
#
#   bash scripts/setup-trackman.sh
#
# Prosjekt: https://github.com/bjornj12/golf-coach (MIT)
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "▸ Installerer uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv havner i ~/.local/bin, som ikke nødvendigvis er på PATH ennå.
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "▸ Installerer golf-coach (med innloggingsstøtte)…"
uv tool install --force "golf-coach[login]"

echo "▸ Åpner nettleseren for Trackman-innlogging."
echo "  Logg inn én gang — vinduet står åpent til du er ferdig."
golf-coach login

cat <<'DONE'

✓ Ferdig. Tokenet ligger i ~/.golf-coach/token.json (mode 0600) og fornyer seg selv.

Neste steg:
  • Claude Code: .mcp.json i dette repoet plukker opp serveren ved neste sesjonsstart.
    Spør "What's my Trackman handicap?" for å teste.
  • Vil du ha coaching-skillsene også:
      /plugin marketplace add bjornj12/golf-coach
      /plugin install golf-coach@golf-coach

Tokenet varer ~7 dager. Forny med:  golf-coach login --headless
DONE
