#!/bin/sh
# Run once on the server: lets the GitHub workflow .github/workflows/deploy.yml publish new versions here.
# Makes an SSH key that can only run update.sh, and prints the three secrets to add on GitHub. Run it again to
# see them again. To stop publishing from GitHub, delete the line with "github-deploy" in ~/.ssh/authorized_keys.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
key="$HOME/.ssh/github-deploy"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
[ -f "$key" ] || ssh-keygen -q -t ed25519 -N "" -C github-deploy -f "$key"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! grep -qF "$(cut -d' ' -f2 "$key.pub")" "$HOME/.ssh/authorized_keys"; then
  echo "command=\"$here/update.sh\",restrict $(cat "$key.pub")" >> "$HOME/.ssh/authorized_keys"
fi
ip=${1:-$(curl -fsS https://checkip.amazonaws.com)}

cat <<TEXT

Legg inn disse tre på GitHub: repoet → Settings → Secrets and variables → Actions → New repository secret.
Navnet står over streken, og verdien (alt mellom strekene) limer du inn.

DEPLOY_HOST
----------
$(whoami)@$ip
----------

DEPLOY_KNOWN_HOSTS
----------
$ip $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)
----------

DEPLOY_SSH_KEY
----------
$(cat "$key")
----------

Nøkkelen kan bare kjøre $here/update.sh. Del den ikke med andre.
TEXT
