#!/bin/sh
# Sets up Gratistorget on a Linux server in one go, also on a server that already runs something else, such as
# a trading bot. Nothing is changed before the web ports (80 and 443) are known to be free and the disk to have
# room, and other programs are left alone. Then it installs Docker if it is missing, opens the firewall on the
# machine for the web ports, fetches the code to ~/fritorg-kode, writes deploy/.env (asks for the domain and a
# contact address), starts the site with update.sh, adds a nightly backup and lets GitHub publish new versions
# (github-deploy.sh). Safe to run again: what is already in place is kept.
#
#   curl -fsSL https://raw.githubusercontent.com/henrik19900-cpu/Test/main/fritorg/deploy/install.sh | sh
#
# The answers can be given up front instead: DOMAIN=... CONTACT_EMAIL=... OPERATOR=... sh install.sh
set -eu

repo=${FRITORG_REPO:-https://github.com/henrik19900-cpu/Test.git}
code=${FRITORG_CODE_DIR:-$HOME/fritorg-kode}
deploy=$code/fritorg/deploy
env_file=$deploy/.env

say() { printf '\n== %s\n' "$*"; }
short() { printf '%s' "$1" | sed "s#^$HOME/#~/#"; } # a path as it is shown
note() { printf '   %s\n' "$*"; }
stop() {
  printf '\nStopper: %s\n' "$*" >&2
  exit 1
}

# Questions are read from the terminal, also when the script itself comes through a pipe (curl ... | sh).
tty=
if (exec </dev/tty) 2>/dev/null; then tty=/dev/tty; fi
ask() { # ask QUESTION [DEFAULT] -> $answer
  answer=${2:-}
  [ -n "$tty" ] || return 0
  printf '%s%s: ' "$1" "${2:+ [$2]}" >"$tty"
  read -r reply <"$tty" || reply=
  [ -z "$reply" ] || answer=$reply
}

wait_for_apt() { # Ubuntu updates itself now and then; apt cannot be used meanwhile (at most 5 minutes)
  for _ in $(seq 1 60); do
    sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || return 0
    sleep 5
  done
}

install_packages() {
  case $family in
    debian)
      wait_for_apt
      sudo apt-get update -q >/dev/null
      # needrestart would otherwise restart services that use updated libraries, such as other programs here.
      sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install -y -q "$@" >/dev/null
      ;;
    redhat) sudo dnf install -y -q "$@" >/dev/null ;;
  esac
}

as_docker() { # runs a command with access to Docker, also before joining the docker group takes effect
  if docker info >/dev/null 2>&1; then sh -c "$1"; else sg docker -c "$1"; fi
}

dns_problems() { # dns_problems NAME IP: what is wrong with NAME's addresses, if anything
  v4=$(getent ahostsv4 "$1" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
  v6=$(getent ahostsv6 "$1" 2>/dev/null | awk '$1 !~ /^::ffff:/ {print $1}' | sort -u | tr '\n' ' ')
  if [ -z "$v4" ]; then
    echo "$1 finnes ikke i DNS ennå. Lag en A-oppføring for $1 som peker til $2."
  elif [ "$v4" != "$2 " ]; then
    echo "$1 peker til ${v4% }, ikke hit. Endre A-oppføringen for $1 til $2."
  fi
  if [ -n "$v6" ]; then
    echo "$1 har også en IPv6-adresse (AAAA-oppføring: ${v6% }). Slett den, ellers får ikke siden sertifikat."
  fi
}

main() {
  # --- What kind of machine -----------------------------------------------------------------------------------
  [ "$(id -u)" != 0 ] || stop "kjør skriptet som brukeren du logger inn med (for eksempel ubuntu eller opc), ikke som root."
  me=$(id -un)
  sudo true || stop "brukeren $me må kunne bruke sudo."
  [ -r /etc/os-release ] || stop "finner ikke /etc/os-release, så systemet er ukjent."
  # shellcheck source=/dev/null
  os_id=$(. /etc/os-release && printf '%s' "${ID:-}")
  # shellcheck source=/dev/null
  os_name=$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-$ID}")
  case $os_id in
    ubuntu | debian) family=debian ;;
    ol | rhel | centos | rocky | almalinux) family=redhat ;;
    *) stop "$os_name støttes ikke. Skriptet kan Ubuntu, Debian og Oracle Linux." ;;
  esac
  case $(uname -m) in
    aarch64 | x86_64) ;;
    *) stop "prosessortypen $(uname -m) støttes ikke (bare ARM64 og x86-64)." ;;
  esac

  say "Sjekker maskinen ($os_name) før noe endres"
  # Anything but Gratistorget's own containers listening on the web ports.
  busy=$(
    sudo ss -Hlntup 2>/dev/null | awk '$5 ~ /:(80|443)$/ && !/"docker-proxy"/ {print "   " $1 " " $5 " " $7}'
    if command -v docker >/dev/null 2>&1; then
      sudo docker ps --format '{{.Label "com.docker.compose.project"}}|{{.Names}}|{{.Ports}}' 2>/dev/null |
        awk -F '|' '$1 != "fritorg" && $3 ~ /:(80|443)->/ {print "   Docker-containeren " $2 ": " $3}'
    fi
  )
  if [ -n "$busy" ]; then
    printf '\nPort 80 eller 443 brukes allerede, og Gratistorget trenger dem:\n%s\n' "$busy" >&2
    stop "ingenting er endret. Det som bruker portene, må flyttes til andre porter eller settes bak Caddy sammen med Gratistorget."
  fi
  note "Port 80 og 443 er ledige for Gratistorget."
  free_mb=$(df -Pm /var/lib | awk 'NR == 2 {print $4}')
  mem_mb=$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)
  if [ "$free_mb" -lt 4096 ]; then
    stop "bare $free_mb MB er ledig på disken. Gratistorget trenger minst 4 GB, og blir disken full, stopper også andre programmer her. Gjør disken større (i Oracle: Boot volume → Edit), eller rydd først. Ingenting er endret."
  fi
  note "Ledig disk: $free_mb MB. Minne: $mem_mb MB."
  if [ "$mem_mb" -lt 1800 ]; then
    note "Det er lite minne. Tar det slutt, stoppes nettsiden først (den starter igjen av seg selv), ikke andre programmer."
  fi

  # --- Docker -------------------------------------------------------------------------------------------------
  say "Docker"
  if command -v docker >/dev/null 2>&1; then
    if docker --version 2>/dev/null | grep -qi podman; then
      stop "«docker» er Podman her. Skriptet bruker Docker og bytter ikke ut Podman, som andre programmer kan bruke."
    fi
    note "Finnes fra før: $(docker --version)"
  else
    case $family in
      debian)
        get_docker=$(mktemp)
        curl -fsSL https://get.docker.com -o "$get_docker"
        wait_for_apt
        sudo env NEEDRESTART_SUSPEND=1 sh "$get_docker" >/dev/null
        rm -f "$get_docker"
        ;;
      redhat)
        [ "$os_id" = rhel ] && dist=rhel || dist=centos
        install_packages dnf-plugins-core
        sudo dnf config-manager --add-repo "https://download.docker.com/linux/$dist/docker-ce.repo"
        install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        ;;
    esac
    command -v docker >/dev/null 2>&1 || stop "Docker ble ikke installert. Se feilmeldingen over."
    note "Installert: $(docker --version)"
  fi
  sudo systemctl enable --now docker >/dev/null 2>&1 || true
  if ! sudo docker compose version >/dev/null 2>&1; then
    if [ "$family" = redhat ] || dpkg -s docker-ce >/dev/null 2>&1; then
      install_packages docker-compose-plugin
    else
      install_packages docker-compose-v2  # Ubuntu's and Debian's own Docker (docker.io)
    fi
  fi
  sudo docker compose version >/dev/null 2>&1 || stop "finner ikke «docker compose»."
  if ! id -nG "$me" | tr ' ' '\n' | grep -qx docker; then
    sudo usermod -aG docker "$me"
    note "$me kan nå bruke Docker uten sudo (fra neste innlogging)."
  fi

  # --- Firewall on the machine (Oracle's own, the security list, is opened in the web console) ----------------
  say "Brannmuren på maskinen"
  if sudo ufw status 2>/dev/null | grep -q '^Status: active'; then
    for rule in 80/tcp 443/tcp 443/udp; do sudo ufw allow "$rule" >/dev/null; done
    note "ufw slipper inn port 80 og 443."
  elif sudo firewall-cmd --state >/dev/null 2>&1; then
    sudo firewall-cmd --quiet --add-service=http --add-service=https --add-port=443/udp
    sudo firewall-cmd --quiet --permanent --add-service=http --add-service=https --add-port=443/udp
    note "firewalld slipper inn port 80 og 443."
  elif [ -f /etc/iptables/rules.v4 ]; then
    # Oracle's Ubuntu images refuse everything but SSH, with rules that are loaded from rules.v4 at boot. The two
    # rules go into the running firewall and into that file, so Docker's own rules are not saved there.
    web='-p tcp -m multiport --dports 80,443 -m state --state NEW -j ACCEPT'
    quic='-p udp -m udp --dport 443 -j ACCEPT'
    for rule in "$web" "$quic"; do
      # shellcheck disable=SC2086 # the rule is meant to be split into words
      sudo iptables -C INPUT $rule 2>/dev/null || sudo iptables -I INPUT $rule
    done
    if ! sudo grep -q -- '--dports 80,443' /etc/iptables/rules.v4; then
      sudo sed -i "0,/^-A INPUT -j REJECT/s//-A INPUT $web\n-A INPUT $quic\n&/" /etc/iptables/rules.v4
    fi
    note "iptables slipper inn port 80 og 443, også etter omstart."
  else
    note "Fant ingen brannmur på maskinen som stenger port 80 og 443."
  fi

  # --- Code and settings --------------------------------------------------------------------------------------
  say "Koden"
  command -v git >/dev/null 2>&1 || install_packages git
  if [ -d "$code/.git" ]; then
    origin=$(git -C "$code" remote get-url origin 2>/dev/null || true)
    [ "${origin%.git}" = "${repo%.git}" ] || stop "$(short "$code") finnes allerede, men er ikke en kopi av $repo."
    note "Bruker $(short "$code")."
  elif [ -e "$code" ]; then
    stop "$(short "$code") finnes allerede, men er ikke en git-kopi. Flytt den, eller velg en annen mappe: FRITORG_CODE_DIR=..."
  else
    git clone --quiet "$repo" "$code"
    note "Hentet til $(short "$code")."
  fi

  say "Innstillinger"
  if [ -f "$env_file" ]; then
    note "Beholder $(short "$env_file")."
    if ! grep -q '^FRITORG_SECRET_KEY=.' "$env_file"; then
      sed -i "s/^FRITORG_SECRET_KEY=.*/FRITORG_SECRET_KEY=$(od -An -tx1 -N32 /dev/urandom | tr -d ' \n')/" "$env_file"
      note "Laget en hemmelig nøkkel (FRITORG_SECRET_KEY)."
    fi
  else
    domain=${DOMAIN:-}
    [ -n "$domain" ] || { ask "Domenet til nettsiden" gratistorget.no && domain=$answer; }
    domain=$(printf '%s' "$domain" | tr '[:upper:]' '[:lower:]' | sed 's#^https*://##; s#/.*##; s#^www\.##')
    case $domain in
      *[!a-z0-9.-]* | .* | *. | -* | *..* | "") stop "«$domain» er ikke et domene." ;;
      *.*) ;;
      *) stop "«$domain» er ikke et domene." ;;
    esac
    contact=${CONTACT_EMAIL:-}
    [ -n "$contact" ] || { ask "E-postadresse folk kan kontakte deg på, også om personvern (vises på siden)" && contact=$answer; }
    case $contact in
      "") note "Ingen kontaktadresse ennå. Legg den inn i .env senere (FRITORG_CONTACT_EMAIL)." ;;
      *[[:space:]]* | *@*@* | @* | *@) stop "«$contact» er ikke en e-postadresse." ;;
      *@*.*) ;;
      *) stop "«$contact» er ikke en e-postadresse." ;;
    esac
    operator=${OPERATOR:-}
    [ -n "$operator" ] || { ask "Hvem driver siden? Navnet ditt, eller firmanavn og org.nr. (vises i vilkårene)" && operator=$answer; }
    [ -n "$operator" ] || note "Ingen driftsansvarlig ennå. Legg den inn i .env før siden åpnes (FRITORG_OPERATOR)."

    # The privacy policy says where the servers are. Oracle tells the machine its region.
    region=$(curl -fsS --max-time 3 -H 'Authorization: Bearer Oracle' \
      http://169.254.169.254/opc/v2/instance/canonicalRegionName 2>/dev/null | tr -d '"[:space:]' || true)
    case $region in
      eu-stockholm-*) where=Sverige ;;
      eu-frankfurt-*) where=Tyskland ;;
      eu-amsterdam-*) where=Nederland ;;
      eu-paris-* | eu-marseille-*) where=Frankrike ;;
      eu-milan-* | eu-turin-*) where=Italia ;;
      eu-madrid-*) where=Spania ;;
      "") where= ;;
      *)
        where=$region
        note "Maskinen står i $region, utenfor EU/EØS. Det må personvernerklæringen si, og overføringen må ha et"
        note "lovlig grunnlag. Ta det med til juristen."
        ;;
    esac

    # Until an SMS provider is set up, codes are shown on screen and every page says that this is a test.
    (
      umask 077
      DOMAIN=$domain CONTACT=$contact OPERATOR=$operator PROCESSORS="Oracle Cloud (servere${where:+, $where})" \
        SECRET=$(od -An -tx1 -N32 /dev/urandom | tr -d ' \n') awk '
        /^DOMAIN=/ { $0 = "DOMAIN=" ENVIRON["DOMAIN"] }
        /^FRITORG_BASE_URL=/ { $0 = "FRITORG_BASE_URL=https://" ENVIRON["DOMAIN"] }
        /^FRITORG_OPERATOR=/ { $0 = "FRITORG_OPERATOR=" ENVIRON["OPERATOR"] }
        /^FRITORG_CONTACT_EMAIL=/ { $0 = "FRITORG_CONTACT_EMAIL=" ENVIRON["CONTACT"] }
        /^FRITORG_PROCESSORS=/ { $0 = "FRITORG_PROCESSORS=" ENVIRON["PROCESSORS"] }
        /^FRITORG_SECRET_KEY=/ { $0 = "FRITORG_SECRET_KEY=" ENVIRON["SECRET"] }
        /^FRITORG_SMTP_FROM=/ { $0 = "FRITORG_SMTP_FROM=Gratistorget <post@" ENVIRON["DOMAIN"] ">" }
        /^FRITORG_SMS_DAILY_LIMIT=/ { $0 = "FRITORG_SMS_DAILY_LIMIT=100" }
        /^FRITORG_SMS_PROVIDER=/ {
          print "# Testmodus til SMS er satt opp: kodene vises på skjermen. For ekte SMS: fyll inn Twilio under, sett"
          print "# FRITORG_SMS_PROVIDER=twilio, slett FRITORG_ALLOW_CONSOLE_SMS, og legg Twilio til i FRITORG_PROCESSORS."
          print "FRITORG_SMS_PROVIDER=console"
          $0 = "FRITORG_ALLOW_CONSOLE_SMS=1"
        }
        { print }
      ' "$deploy/.env.example" >"$env_file"
    )
    note "Skrev $(short "$env_file"). Den hemmelige nøkkelen der bør du også lagre i en passordbehandler."
  fi
  chmod 600 "$env_file"
  domain=$(sed -n 's/^DOMAIN=//p' "$env_file" | tail -n 1)

  # --- Start ----------------------------------------------------------------------------------------------------
  say "Bygger og starter Gratistorget. Første gang tar det noen minutter."
  as_docker "'$deploy/update.sh'" || stop "siden startet ikke. Feilmeldingen står over."

  say "Sikkerhetskopi hver natt"
  job="cd '$deploy' && docker compose exec -T app fritorg backup /data/backup && rm -rf ./backup && docker compose cp app:/data/backup ./backup"
  if ! command -v crontab >/dev/null 2>&1; then
    note "Fant ikke cron. Sett opp sikkerhetskopien for hånd (steg 9 i oracle-cloud.md)."
  elif existing=$(crontab -l 2>/dev/null) || crontab -l 2>&1 | grep -q '^no crontab'; then
    if printf '%s\n' "$existing" | grep -qF '# gratistorget-backup'; then
      note "Er satt opp fra før."
    else
      # Jobs already in the crontab, such as other programs', are kept as they are. This one is added at the end.
      { [ -z "$existing" ] || printf '%s\n' "$existing"; printf '0 3 * * * %s # gratistorget-backup\n' "$job"; } | crontab -
      note "Klokken 03 hver natt (maskinens klokke) til $(short "$deploy")/backup. Kopier den også til et annet sted."
    fi
  else
    note "Kunne ikke lese crontab. Sett opp sikkerhetskopien for hånd (steg 9 i oracle-cloud.md)."
  fi

  ip=$(curl -fsS --max-time 10 https://checkip.amazonaws.com 2>/dev/null || true)
  say "Publisering fra GitHub"
  "$deploy/github-deploy.sh" ${ip:+"$ip"}

  # --- What is left -----------------------------------------------------------------------------------------------
  dns=$(for name in "$domain" "www.$domain"; do dns_problems "$name" "$ip"; done)
  up=
  if [ -z "$dns" ]; then
    say "Sjekker at https://$domain svarer"
    for _ in $(seq 1 18); do
      if curl -fsS -o /dev/null --max-time 5 --resolve "$domain:443:127.0.0.1" "https://$domain/healthz" 2>/dev/null; then
        up=1
        break
      fi
      sleep 5
    done
  fi

  say "Ferdig"
  here=$(short "$deploy")
  note "Gratistorget kjører på maskinen. Andre programmer her er ikke endret."
  if [ -n "$up" ]; then
    note "Siden er oppe: https://$domain"
  else
    note "Før siden kan nås på https://$domain:"
    note "- I Oracle: slipp inn TCP 80 og 443 og UDP 443 fra 0.0.0.0/0 under Security Lists (steg 3 i oracle-cloud.md)."
    printf '%s\n' "$dns" | while read -r line; do [ -z "$line" ] || note "- $line"; done
    note "Caddy henter HTTPS-sertifikatet av seg selv når det er på plass."
  fi
  note "- På GitHub: legg inn de tre hemmelighetene over, så publiseres nye versjoner hit av seg selv."
  if grep -q '^FRITORG_ALLOW_CONSOLE_SMS=1' "$env_file"; then
    note "- SMS er i testmodus: kodene vises på skjermen, og siden sier at den er en test. Ekte SMS og e-post (SMTP)"
    note "  fyller du inn i $here/.env."
  fi
  note ""
  note "Nyttige kommandoer, i mappen $here:"
  note "  docker compose up -d                                  etter endringer i .env"
  note "  docker compose exec app fritorg doctor                sjekker innstillingene"
  note "  docker compose exec app fritorg make-admin E-POST     gjør kontoen din til moderator"
  note "  docker compose restart caddy                          prøver HTTPS-sertifikatet på nytt med en gang"
}

# The whole script has been read before anything runs, also when it comes through a pipe that breaks off.
main "$@"
