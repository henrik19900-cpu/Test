#!/bin/sh
# Publishes one commit of main on this server and checks that it answers; if it does not, the version that ran
# before comes back. The GitHub workflow .github/workflows/deploy.yml runs it through an SSH key that can run
# nothing else (github-deploy.sh). By hand: ./update.sh for the newest version, or ./update.sh <commit>.
set -eu
want=${SSH_ORIGINAL_COMMAND:-${1:-main}}
case $want in
  main) ;;
  "" | *[!0-9a-f]*) echo "Bruk: update.sh [main | <commit>]" >&2; exit 2 ;;
esac
cd "$(dirname "$0")"
repo=$(git rev-parse --show-toplevel)
git -C "$repo" fetch --quiet origin main
if [ "$want" = main ]; then
  sha=$(git -C "$repo" rev-parse origin/main)
else
  sha=$(git -C "$repo" rev-parse --verify --quiet "$want^{commit}" || true)
  if [ -z "$sha" ] || ! git -C "$repo" merge-base --is-ancestor "$sha" origin/main; then
    echo "$want er ikke en del av main, så den publiseres ikke." >&2
    exit 1
  fi
fi
previous=$(git -C "$repo" rev-parse HEAD)

answers() {  # the app is up and runs commit $1
  for _ in $(seq 1 60); do
    live=$(docker compose exec -T app python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)).get('commit') or '')" 2>/dev/null || true)
    [ "$live" = "$1" ] && return 0
    sleep 2
  done
  return 1
}

git -C "$repo" reset --quiet --hard "$sha"
if ! COMMIT=$sha docker compose build --quiet; then
  git -C "$repo" reset --quiet --hard "$previous"
  echo "Byggingen feilet. Siden kjører fortsatt forrige versjon ($previous)." >&2
  exit 1
fi
COMMIT=$sha docker compose up -d --remove-orphans
# Caddy reads its file once, and a file mounted on its own stays the old one until the container restarts.
git -C "$repo" diff --quiet "$previous" "$sha" -- fritorg/deploy/Caddyfile || docker compose restart caddy
if answers "$sha"; then
  docker image prune -f >/dev/null
  echo "Gratistorget kjører nå $sha."
  exit 0
fi
echo "Den nye versjonen svarer ikke. Går tilbake til $previous." >&2
docker compose logs --tail 80 app >&2 || true
git -C "$repo" reset --quiet --hard "$previous"
COMMIT=$previous docker compose up -d --build --remove-orphans
if answers "$previous"; then
  echo "Forrige versjon ($previous) kjører igjen." >&2
else
  echo "Forrige versjon svarer heller ikke. Se: docker compose logs app" >&2
fi
exit 1
