# Fritorg

**Gratis markedsplass for hele Norge – like enkel å bruke for AI-agenter som for mennesker.**

Fritorg er et åpent alternativ til de store annonseplattformene: Torget, kjøretøy og båt, eiendom, jobb og tjenester. Det koster ingenting å legge ut annonser, søke eller sende meldinger, og alt en person kan gjøre på nettsiden, kan en AI-assistent gjøre via MCP eller et vanlig JSON-API – uten CAPTCHA, betalingsmur eller skjulte sperrer.

## Innhold

- [Funksjoner](#funksjoner)
- [Kom i gang lokalt](#kom-i-gang-lokalt)
- [Slik lagres data](#slik-lagres-data)
- [Bekreftelse av brukere](#bekreftelse-av-brukere)
- [Beskyttelse mot svindel og falske annonser](#beskyttelse-mot-svindel-og-falske-annonser)
- [For AI-agenter](#for-ai-agenter)
- [Sette i drift](#sette-i-drift)
- [Sjekkliste før lansering](#sjekkliste-før-lansering)
- [Drift](#drift)
- [Konfigurasjon](#konfigurasjon)
- [Utvikling](#utvikling)

## Funksjoner

- **40 kategorier** i fem hovedgrupper, med egne felt per kategori (for eksempel merke, årsmodell, kilometerstand og drivstoff for biler) og alle 16 fylker.
- **Søk** som finner deler av ord (`sofa` finner også `hjørnesofa`), med filtre for kategori, type, sted, pris og kategorifelt.
- **Meldinger** mellom kjøper og selger, med e-postvarsel til bekreftede adresser.
- **Bilder** som skaleres, lagres som WebP og får fjernet EXIF- og GPS-data.
- **Bekreftede brukere:** norsk mobilnummer med SMS-kode som standard, BankID som valg.
- **Beskyttelse mot svindel**, moderering og rapportering (se under).
- **Åpent for agenter:** MCP-server, REST-API med OpenAPI 3.1, `llms.txt`, eksport av alle annonser som NDJSON, Atom-feeder og JSON/Markdown-versjon av hver side.
- **Universell utforming og personvern:** fungerer uten JavaScript, ingen sporingskapsler og ingen reklame.

## Kom i gang lokalt

Krever Python 3.11 eller nyere.

```sh
cd fritorg
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m fritorg seed     # demo-brukere og 51 demo-annonser
python -m fritorg serve    # http://127.0.0.1:8000
```

Logg inn med `demo@fritorg.no` og passordet `demo1234`. Lokalt sendes ingen SMS: koden vises på skjermen, og et gult banner viser at siden er i testmodus.

## Slik lagres data

Alt ligger i datamappen (`FRITORG_DATA_DIR`, standard `data/`):

| Fil | Innhold |
| --- | --- |
| `fritorg.sqlite3` | SQLite-database i WAL-modus: brukere, annonser, meldinger, rapporter og modereringslogg. Fulltekstsøket bruker SQLite FTS5. |
| `uploads/` | Bilder som WebP, i full størrelse (maks 1600 piksler) og som miniatyrbilde. Filnavnene er tilfeldige. |
| `secret_key` | Hemmelig nøkkel, opprettes automatisk hvis `FRITORG_SECRET_KEY` ikke er satt. Den trengs for å kjenne igjen mobilnumre, BankID-identiteter og lenker, så den må tas vare på. |

Om brukerne lagres e-postadresse, visningsnavn og passord som en scrypt-hash. Mobilnummeret lagres aldri i klartekst, bare som en nøkkelbasert hash (så hvert nummer kan brukes på én konto) og de tre siste sifrene. Med BankID lagres navnet, men aldri fødselsnummeret.

Én SQLite-fil holder lenge for en norsk markedsplass: søk i 50 000 annonser tar et par hundre millisekunder i verste fall. Appen kjører som én prosess. Skal den skaleres ut på flere servere, må databasen og fartsgrensene (som nå ligger i minnet) flyttes til en felles tjeneste.

## Bekreftelse av brukere

Alle som legger ut annonser eller sender meldinger, må være en bekreftet person. Det finnes to måter:

**1. Mobilnummer med SMS-kode (standard).** Krever ingen særskilt avtale, bare en konto hos en SMS-leverandør. Brukeren lager konto med e-post og passord og bekrefter så et norsk mobilnummer (8 siffer, starter på 4 eller 9) med en sekssifret kode. Norske mobilabonnement er registrert på en person, og hvert nummer kan bare brukes på én konto.

- Leverandører: `twilio`, eller `http` for alle leverandører med et enkelt HTTP-API, for eksempel norske SMS-tjenester. Se `deploy/.env.example`.
- Koden gjelder i 10 minutter og har 5 forsøk. Det er grenser per konto, per nummer, per IP-adresse og per døgn for hele siden (`FRITORG_SMS_DAILY_LIMIT`), som holder SMS-kostnadene nede og stopper misbruk.
- Agenter kan hjelpe brukeren gjennom bekreftelsen med MCP-verktøyet `verify_phone` eller `POST /api/v1/me/phone`.

**2. BankID (valgfritt).** Krever avtale med BankID eller en mellomleverandør som Signicat eller Idura (Criipto). Med `FRITORG_BANKID=oidc` lages kontoer og innlogging med BankID i stedet for passord og SMS, og visningsnavnet blir fornavn og forbokstav i etternavnet («Kari N.»).

`FRITORG_VERIFICATION=none` slår av bekreftelsen. Det er bare ment for testing.

## Beskyttelse mot svindel og falske annonser

- **Automatisk risikovurdering** av hver annonse: kjente svindelfraser (forskudd, depositum før visning, gavekort, kryptovaluta, betalingslenker, «finansagent»), forbudte varer, mistenkelig lav pris for biler og boliger, kopiert tekst og gjenbrukte bilder fra andre selgere (også beskårne og komprimerte kopier). Annonser med høy risiko holdes tilbake til en moderator har godkjent dem.
- **Advarsler i meldinger** med betalingslenker, forespørsler om BankID-koder eller kortnummer, eller forsøk på å flytte samtalen til WhatsApp.
- **Strengere grenser for nye kontoer** det første døgnet.
- **Rapportering** av annonser og samtaler. Rapporterer tre brukere samme annonse, skjules den til den er kontrollert.
- **Moderering** på `/moderering`: godkjenne eller fjerne annonser, avvise rapporter og stenge kontoer. Alt logges.
- **Merking:** «Mobilnummer bekreftet» eller «BankID-verifisert», «Ny bruker» og «via AI-agent».
- **Navn som kan forveksles** med siden selv eller kjente selskaper (for eksempel «Fritorg», «Vipps», «Posten») avvises.

## For AI-agenter

- Veiledning: `/for-agenter` (også som `/for-agenter.md`) og `/llms.txt`.
- MCP-server (Streamable HTTP): `/mcp`. Uten nøkkel får agenten verktøy for å lese, med en personlig nøkkel også for å skrive. Eksempel: `claude mcp add --transport http fritorg https://fritorg.no/mcp`
- REST-API: `/api/v1`, dokumentert i `/openapi.json` og `/api/docs`. Feil følger RFC 9457 med norsk `detail` og engelsk `hint`.
- Agenter kan be om tilgang selv med device flow (`POST /api/v1/auth/device`), og personen godkjenner på `/koble-til`.
- Alle offentlige annonser: `/api/v1/export/listings.ndjson`.

## Sette i drift

Oppsettet i `deploy/` kjører Fritorg i Docker bak [Caddy](https://caddyserver.com/), som henter og fornyer HTTPS-sertifikater automatisk.

1. Skaff en server med Docker (for eksempel en liten VPS i Norge eller EU) og pek domenets A/AAAA-oppføring dit.
2. Fyll inn innstillingene:
   ```sh
   cd fritorg/deploy
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_hex(32))"   # lim inn som FRITORG_SECRET_KEY
   ```
   Fyll inn domene, driftsansvarlig, kontaktadresse, SMS-leverandør og SMTP.
3. Start: `docker compose up -d --build`
4. Sjekk oppsettet:
   ```sh
   docker compose exec app fritorg doctor --send-test-mail deg@example.no --send-test-sms 91234567
   ```
5. Lag din egen konto på nettsiden, og gjør den til moderator:
   ```sh
   docker compose exec app fritorg make-admin deg@example.no
   ```

## Sjekkliste før lansering

- [ ] Domene og server, med HTTPS (Caddy ordner sertifikatet).
- [ ] SMS-leverandør satt opp og testet, med en daglig grense du har budsjett for. Alternativt: BankID-avtale.
- [ ] E-post (SMTP) satt opp og testet, med SPF og DKIM for domenet.
- [ ] `FRITORG_SECRET_KEY` er satt og lagret et trygt sted. Mister du den, kjennes ikke mobilnumre og BankID-identiteter igjen.
- [ ] `FRITORG_OPERATOR` og `FRITORG_CONTACT_EMAIL` er satt (vises i vilkårene, bunnteksten og `security.txt`).
- [ ] Minst én moderator, og en plan for hvem som følger med på `/moderering` hver dag.
- [ ] `fritorg doctor` viser ingen FEIL.
- [ ] Daglig sikkerhetskopi som kopieres til et annet sted, og en gjenoppretting som er testet.
- [ ] Juridisk gjennomgang av vilkår og personvernerklæring (`/vilkar` er et utkast), databehandleravtaler med SMS- og e-postleverandøren og en oversikt over behandlingen av personopplysninger.
- [ ] `FRITORG_SEED_DEMO` er av, så det ikke ligger demo-annonser på den ekte siden.

## Drift

```sh
fritorg doctor [--send-test-mail ADRESSE] [--send-test-sms NUMMER]   # klar for lansering?
fritorg make-admin E-POST                                            # gi moderatorrettigheter
fritorg backup MAPPE                                                 # database, bilder og nøkkel
fritorg seed [--force]                                               # demo-data (ikke i produksjon)
```

Med Docker kjøres kommandoene med `docker compose exec app ...`. En enkel daglig sikkerhetskopi (crontab på serveren):

```sh
0 3 * * * cd /sti/til/fritorg/deploy && docker compose exec -T app fritorg backup /data/backup && docker compose cp app:/data/backup ./backup
```

Sikkerhetskopien tas mens appen kjører, og databasen blir konsistent. Kopier mappen videre til et annet sted (for eksempel objektlagring).

## Konfigurasjon

Alle innstillinger er miljøvariabler. De viktigste:

| Variabel | Standard | Betydning |
| --- | --- | --- |
| `FRITORG_BASE_URL` | utledes fra forespørselen | Offentlig adresse, for eksempel `https://fritorg.no`. Med https slås HSTS og sikre informasjonskapsler på. |
| `FRITORG_DATA_DIR` | `data` | Mappe for database, bilder og nøkkel. |
| `FRITORG_SECRET_KEY` | fil i datamappen | Hemmelig nøkkel (64 heksadesimale tegn). |
| `FRITORG_SITE_NAME` | `Fritorg` | Navnet på siden. |
| `FRITORG_OPERATOR`, `FRITORG_CONTACT_EMAIL` | – | Hvem som driver siden og hvordan de nås. |
| `FRITORG_VERIFICATION` | `sms` | `sms` eller `none` (bare for testing). |
| `FRITORG_SMS_PROVIDER` | `console` | `twilio`, `http` eller `console` (viser koden på skjermen, avvises på https-sider). |
| `FRITORG_TWILIO_ACCOUNT_SID`, `_AUTH_TOKEN`, `_FROM` | – | Twilio-konto og avsender. |
| `FRITORG_SMS_URL`, `FRITORG_SMS_METHOD` | –, `GET` | URL-mal for `http`-leverandører (se `deploy/.env.example`). |
| `FRITORG_SMS_DAILY_LIMIT`, `FRITORG_SMS_PER_IP_PER_HOUR` | `2000`, `10` | Grenser for antall SMS-koder. |
| `FRITORG_BANKID` | `off` | `oidc` for ekte BankID, `simulated` for utvikling. |
| `FRITORG_BANKID_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET`, `_SCOPE`, `_ACR_VALUES`, `_ID_CLAIM` | – | BankID-leverandøren (OpenID Connect). |
| `FRITORG_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_FROM`, `_SECURITY` | –, `587`, …, `starttls` | Utgående e-post. Uten `FRITORG_SMTP_HOST` sendes ingen e-post. |
| `FRITORG_RATE_LIMIT_READ`, `_WRITE`, `_AUTH` | `600`, `60`, `30` | Fartsgrenser per IP-adresse (lesing og skriving per minutt, innlogging per 10 minutter). |
| `FRITORG_MAX_LISTINGS_PER_DAY`, `FRITORG_MAX_MESSAGES_PER_DAY` | `50`, `200` | Grenser per konto per døgn. |
| `FRITORG_NEW_ACCOUNT_MAX_LISTINGS_PER_DAY`, `..._MESSAGES_PER_DAY` | `5`, `20` | Grenser det første døgnet. |
| `FRITORG_MAX_IMAGE_BYTES`, `FRITORG_MAX_IMAGES_PER_LISTING` | 8 MB, `12` | Bildegrenser. |
| `FRITORG_SEED_DEMO` | av | Legg inn demo-data ved første oppstart. |

## Utvikling

```sh
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

Testene dekker API-et, MCP-serveren (også med den offisielle MCP-klienten), søk, svindelbeskyttelse, BankID, SMS-bekreftelse, bilder, e-post og drift. GitHub Actions kjører dem på Python 3.11 og 3.13, og bygger og prøvekjører Docker-imaget.

Koden ligger i `fritorg/`: `app.py` setter alt sammen, `api.py` er REST-API-et, `mcp_server.py` MCP-serveren og `web.py` nettsidene. `listings.py`, `messages.py`, `users.py`, `fraud.py`, `phone.py` og `identity.py` inneholder logikken, og `templates/` sidene og dokumentasjonen.
