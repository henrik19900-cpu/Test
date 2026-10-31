# Odds-sammenligner

Viser, kamp for kamp, Norsk Tippings odds mot margin-fri referanseodds, og fremhever utfall med positiv forventet verdi (EV). Et personlig analyseverktøy som kjører lokalt, uten innlogging og uten spillfunksjon.

Første versjon dekker fotball, markedet H/U/B (1X2), kamper de neste 7 dagene, én referansekilde, henting fra Norsk Tipping hvert 15. minutt med historikk i SQLite, og et Streamlit-dashboard med ett kort per kamp sortert på beste EV. Referanseodds hentes bare når du ber om det.

Alt er gratis: Python-pakkene, SQLite, Streamlit og Docker er åpen kildekode, og referanseoddsen kommer fra gratisplanen til The Odds API.

## Kom i gang

Krever Python 3.12 eller nyere.

```sh
cd odds-compare
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # legg inn THE_ODDS_API_KEY (gratis, se under)
oddscompare reference       # Norsk Tipping og referanseodds (bruker kreditter)
streamlit run app.py        # http://localhost:8501
```

| Kommando | Hva den gjør |
| --- | --- |
| `oddscompare fetch` | Henter én runde fra Norsk Tipping og skriver et sammendrag. |
| `oddscompare run --interval 15` | Henter fra Norsk Tipping i løkke. Under 5 minutter avvises. |
| `oddscompare reference` | Henter referanseodds nå, sammen med Norsk Tipping, og viser hvor mange kreditter som er igjen. Det samme gjør knappen «Hent referanseodds» i dashboardet. |
| `oddscompare prune --days 90` | Sletter kamper (med odds) som startet for mer enn 90 dager siden. |
| `streamlit run app.py` | Starter dashboardet. Det leser fra databasen, så det fungerer også når en kilde er nede. |

Med Docker: `docker compose up -d --build` starter `fetcher` (henter fra Norsk Tipping hvert 15. minutt) og `dashboard` på http://127.0.0.1:8501, der knappen henter referanseodds. Begge deler mappen `data/`.

## Konfigurasjon

Alt står i `config.yaml`: antall dager frem, intervall, marginmetode (`proportional`, `power` eller `shin`), tidsvindu og terskler for matching, hvilke land i Oddsens fotballmeny som hentes, og referansekilde og bookmaker. API-nøkler leses bare fra `.env`, som aldri sjekkes inn.

## Datakilder

**Norsk Tipping** har ikke et offentlig odds-API. Adapteren (`src/oddscompare/sources/nt.py`) bruker de samme kallene som Oddsen-siden selv gjør. De ble funnet ved å se på nettverkstrafikken i nettleseren:

1. `POST …/sportsbook/services/content/get` med en `boNavigationList` gir menyen: Fotball, land og ligaer. Hver liga har en kampkupong (`MATCHESCOUPON`).
2. Oddsen ligger ikke i noe vanlig svar. Siden åpner en SockJS-websocket (`velnt-opr1.sport2.norsk-tipping.no/notification/listen`), som gir en abonnent-id.
3. `POST …/content/subscribe` med kupongen får serveren til å sende kampene med hovedmarkedet (HUB) over websocketen. Prisene er brøker. Desimalodds er 1 + teller/nevner, avrundet slik siden viser dem.

Endepunktene er uoffisielle og kan endres uten varsel. Når svarene ikke ser ut som forventet, feiler adapteren med en melding om hva som mangler, i stedet for å returnere en tom liste. For å holde trafikken lav gjelder dette:

- Høyst én runde per 5 minutter. Ellers brukes siste svar fra `data/cache/`.
- Ligamenyen caches i 6 timer.
- Bare landene i konfigen hentes.
- Kallene bruker en egen User-Agent.

En runde med de 10 landene i standardkonfigen tar rundt 7 sekunder og gir rundt 300 kamper. `robots.txt` stenger ikke `/sport/oddsen` (bare `/sport/liveoddsen`). **Les likevel Norsk Tippings vilkår før bruk.** Det er ikke gjort i dette prosjektet.

**Referanseodds** kommer fra [The Odds API](https://the-odds-api.com). Pinnacle stengte sitt offentlige API i juli 2025, men The Odds API har Pinnacles odds, hentet fra Pinnacles nettsted, også på gratisplanen. Gratisplanen gir 500 kreditter i måneden, uten betalingskort. Registrer deg med e-post på nettstedet og legg nøkkelen i `.env` som `THE_ODDS_API_KEY`.

**Referanseodds hentes bare når du ber om det**, med `oddscompare reference` eller knappen «Hent referanseodds» i dashboardet. Den vanlige hentingen (`fetch` og `run`) bruker ingen kreditter. Kredittene brukes slik:

- Å liste kamper (`/events`) er gratis.
- Odds for én liga (`/odds`) koster 1 kreditt, uansett hvor mange kamper svaret har.
- Adapteren kjøper bare odds for ligaer som har kamper som kan matche en Norsk Tipping-kamp. Med de 6 ligaene i standardkonfigen koster en henting høyst 6 kreditter, altså minst 83 hentinger i måneden.
- Ber du igjen innen 5 minutter (`min_interval_minutes`), brukes forrige svar, så et dobbeltklikk ikke koster dobbelt.

**Konkurrentene til Norsk Tipping** hentes i samme forespørsel som Pinnacle, uten ekstra kostnad: opptil 10 bookmakere teller som én. Standard er Unibet, Betsson, NordicBet, Coolbet, LeoVegas, 888sport og Betway (`competitors` i `config.yaml`). Bet365 og ComeOn finnes ikke hos The Odds API. Hvert kort viser beste odds per utfall og hvem som har dem, i grønt når det er Norsk Tipping. Under «Konkurrentenes odds» står alle bookmakerne side om side med margin.

Kortene viser når referanseoddsen sist ble hentet. Dashboardet varsler ikke om at den er gammel, siden det er du som bestemmer når den hentes. Ligaene heter som i `GET /v4/sports` (gratis), for eksempel `soccer_germany_bundesliga`. `bookmaker` kan også være `betfair_ex_eu`.

Odds-API.io (`reference.source: odds_api_io`) er fortsatt støttet, men krever betalt plan. [SharpOddz](https://sportsapis.dev/apis/sharpoddz) er ikke implementert, fordi API-dokumentasjonen deres ikke er offentlig, og fordi den koster penger etter en prøvedag.

## Matching av kamper

En Norsk Tipping-kamp er samme kamp som en referansekamp når begge lagnavn matcher og avsparkstiden er innenfor ±30 minutter. Hjemme og borte må stemme, så byttet rekkefølge regnes ikke som match.

Lagnavn normaliseres slik:

- små bokstaver
- ø → o, å → a, æ → ae, og andre aksenter fjernes
- punktum fjernes, og & leses som «and»
- ord for klubbform fjernes, som «FK», «IL», «FC», «BK», «IF», «FF» og «SK» (se `STRIP_WORDS` i `matching.py`)

Deretter slås navnet opp i `data/team_aliases.yaml`. Som reserve brukes `rapidfuzz` med terskel 90. Treff mellom 80 og 90 brukes ikke, men vises i dashboardet under «Umatchede kamper» med et ferdig YAML-forslag som kan kopieres inn i alias-tabellen.

## Beregninger

`src/oddscompare/calc.py` har rene funksjoner uten I/O:

- margin: `m = Σ 1/oᵢ − 1`
- fair sannsynlighet med proporsjonal metode, power-metoden (k slik at `Σ (1/oᵢ)^k = 1`) eller Shin
- EV: `oᵢ(NT) · pᵢ − 1`

Metoden velges i konfigen og kan byttes i dashboardet, som regner om direkte.

Kampene kan sorteres etter beste EV (standard), avsparkstid, liga, lavest NT-margin, eller hvor nær Norsk Tipping er beste odds i markedet.

## Data

SQLite i `data/odds.db`. Hver henting lagrer et nytt snapshot.

| Tabell | Innhold |
| --- | --- |
| `events` | Kanonisk kamp. Norsk Tipping er ankeret. |
| `source_events` | Kobling fra hver kildes kamp til den kanoniske kampen. |
| `odds_snapshots` | Én rad per utfall per henting. Viewet `latest_odds` gir siste snapshot per kilde, via hjelpetabellen `latest_fetch` som en trigger holder oppdatert, så dashboardet er raskt også med måneder med historikk. |
| `unmatched` | Norsk Tipping-kamper uten referansekamp, med nærmeste kandidat og likhet. |
| `fetch_log` | Hver henting per kilde: status, antall kamper og feilmelding. |

Feiler en kilde, prøves den tre ganger med eksponentiell backoff (2 og 4 sekunder). Deretter logges feilen, og runden fortsetter med den andre kilden. Feilen vises øverst i dashboardet.

## Tester

```sh
pytest                      # uten nettverk
ruff check . && ruff format --check .
```

Fixturene ligger i `tests/fixtures/`:

- `nt_sample.json` er et ekte svar fra Oddsen 31.10.2026 med 88 kamper fra sju ligaer.
- `odds_api_io_sample.json` er laget for hånd etter Odds-API.ios dokumenterte format, fordi prosjektet ikke har en API-nøkkel. Den brukes til å teste matchingen og har de samme 88 kampene med navn slik en engelskspråklig feed typisk skriver dem («Bodo/Glimt», «Odds BK», «Preston North End»), pluss 10 andre kamper. Blant dem er to med hjemme og borte byttet om på samme tidspunkt. Bytt den gjerne ut med ekte navn fra referansen når du har en nøkkel: `data/cache/the_odds_api.json` har svarene.
- Testene for The Odds API bruker svar i formatet fra v4-dokumentasjonen deres, skrevet inn i `tests/test_reference.py`.

Med alias-tabellen matcher 88 av 88 kamper (100 %). Uten alias-tabellen matcher 70 av 88 (79,5 %).
