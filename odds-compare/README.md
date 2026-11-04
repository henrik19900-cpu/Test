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

### På Streamlit Community Cloud (gratis)

Da kan du åpne dashboardet fra mobilen uten egen maskin:

1. Gå til [share.streamlit.io](https://share.streamlit.io) og logg inn med GitHub-kontoen som eier repoet.
2. Velg «Create app» og deretter «Deploy a public app from GitHub». Fyll inn repoet `henrik19900-cpu/Test`, branchen (`main` når PR-en er flettet) og `odds-compare/app.py` som «Main file path».
3. Under «Advanced settings» velger du Python 3.12 eller nyere. I «Secrets» skriver du `THE_ODDS_API_KEY = "nøkkelen din"`.
4. Trykk «Deploy». Streamlit installerer `requirements.txt`, og appen finner koden i `src/`.

Gjør appen privat under «Share», så bare du kan åpne den. Ellers kan alle med lenken trykke «Hent referanseodds» og bruke kredittene dine. Uten `oddscompare run` ved siden av henter appen Norsk Tippings odds selv når siden åpnes og dataene er eldre enn 15 minutter. Streamlit Cloud lagrer ikke filer når appen startes på nytt, så historikken (oddsutviklingen) begynner på nytt da.

### Som snarvei på telefonen

Åpne appens adresse (for eksempel `https://ditt-navn.streamlit.app`) på telefonen og vent til siden har lastet:

- **iPhone (Safari):** trykk del-knappen (firkanten med pil opp), velg «Legg til på Hjem-skjerm» og trykk «Legg til».
- **Android (Chrome):** trykk ⋮ øverst til høyre, velg «Legg til på startsiden» eller «Installer app», og trykk «Legg til».

Snarveien heter «Odds» og har et grønt «1X2»-ikon. Den åpner appen i fullskjerm, uten adresselinje. Har appen ikke vært brukt på en stund, sover den hos Streamlit. Trykk da «Yes, get this app back up!» og vent et halvt minutt.

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

**Referanseodds** kommer fra [OddsLink](https://oddslink.app), med [The Odds API](https://the-odds-api.com) som reserve. Pinnacle stengte sitt offentlige API i juli 2025, men begge har Pinnacles odds på gratisplanen.

- **OddsLink** (`reference.source: oddslink`, standard) gir 1 000 forespørsler i måneden, uten betalingskort. Én forespørsel henter alle fotballigaene med Pinnacle og konkurrentene, uansett hvor mange kamper svaret har. Den dekker alle Norsk Tipping-ligaene The Odds API har unntatt 3. Liga, og i tillegg blant annet OBOS-ligaen, dansk 1. division, Eerste Divisie og skotsk Championship. Konkurrentene er Unibet, 888sport, Betway, bet365, bwin, Betano, William Hill og Betfair Exchange; Betsson, NordicBet, Coolbet og LeoVegas finnes ikke der. Betfair Exchange tar provisjon av gevinsten, så oddsen derfra vises og sammenlignes etter den: 3,00 blir 2,90 med 5 % (`exchange_commission` i `config.yaml`; sjekk satsen på kontoen din hos Betfair). Fair odds regnes fortsatt av prisene slik de står. Lag en gratis nøkkel på nettstedet og legg den i `.env` som `ODDSLINK_API_KEY`. OddsLink er en ny tjeneste (vilkårene er fra oktober 2026), og den sier ikke hvor Pinnacle-oddsen kommer fra.
- **The Odds API** brukes av seg selv når OddsLink feiler (`fallback: the_odds_api`), hvis `THE_ODDS_API_KEY` er satt. Oddsen lagres da som OddsLinks, så dashboardet og varslene fortsetter som før. Mangler OddsLink odds fra et selskap, som Unibet 3.11.2026, kan du trykke «Hent fra The Odds API i stedet» i dashboardet: da hentes Pinnacle og konkurrentene derfra for ligaene den dekker, og de nyeste oddsene fra hver av de to vises. Unibet og 888sport har ulike navn hos de to kildene, men lagres som samme selskap. Den kan også være eneste kilde (`reference.source: the_odds_api`). Gratisplanen gir 500 kreditter i måneden, og hver liga koster 1 kreditt per henting. Resten av avsnittet beskriver den.

**Referanseodds hentes bare når du ber om det**, med `oddscompare reference` eller knappen «Hent referanseodds» i dashboardet. Den vanlige hentingen (`fetch` og `run`) bruker ingen kreditter. Kredittene brukes slik:

- Å liste kamper (`/events`) er gratis.
- Odds for én liga (`/odds`) koster 1 kreditt, uansett hvor mange kamper svaret har.
- Adapteren kjøper bare odds for ligaer som har kamper som kan matche en Norsk Tipping-kamp. Med de 6 ligaene i standardkonfigen koster en henting høyst 6 kreditter, altså minst 83 hentinger i måneden.
- Ber du igjen innen 5 minutter (`min_interval_minutes`), brukes forrige svar, så et dobbeltklikk ikke koster dobbelt.

**Ligaer:** Standard er alle de 21 Norsk Tipping-ligaene The Odds API har: Eliteserien, Premier League, Championship, League One og Two, Champions League, Europa League, Conference League, LaLiga og LaLiga 2, Serie A og B, Bundesliga 1–3, Ligue 1 og 2, Eredivisie, Allsvenskan, Superettan og Superligaen. 31.10.2026 ga det referanse til 218 av 313 Norsk Tipping-kamper (70 %). Resten er ligaer The Odds API ikke har: norske divisjoner under Eliteserien (også OBOS-ligaen), kvinneligaer, National League, Ligue 3, Primera Federación, dansk 1. division og Eerste Divisie. En henting med alle ligaene koster opptil 21 kreditter. I dashboardet velger du hvilke ligaer hver henting skal betale for, og ser kostnaden før du trykker.

**Konkurrentene til Norsk Tipping** hentes i samme forespørsel som Pinnacle, uten ekstra kostnad: opptil 10 bookmakere teller som én. Standard er Unibet, Betsson, NordicBet, Coolbet, LeoVegas, 888sport og Betway (`competitors` i `config.yaml`). Bet365 og ComeOn finnes ikke hos The Odds API. Hvert kort viser beste odds per utfall og hvem som har dem, i grønt når det er Norsk Tipping. Under «Konkurrentenes odds» står alle bookmakerne side om side med margin.

Pinnacle legger ofte ut odds sent, særlig på midtukekamper. En kamp som bare konkurrentene har priset, blir likevel matchet, slik at konkurrentenes odds vises. Har minst 3 konkurrenter odds, regnes fair odds ut fra snittet av dem, med marginen fjernet hos hver. Kortet sier tydelig fra om dette, siden konkurrentene er en svakere referanse enn Pinnacle. Når Pinnacle priser kampen, brukes Pinnacle.

Kortene viser når referanseoddsen sist ble hentet. Dashboardet varsler ikke om at den er gammel, siden det er du som bestemmer når den hentes. Ligaene heter som i `GET /v4/sports` (gratis), for eksempel `soccer_germany_bundesliga`. `bookmaker` kan også være `betfair_ex_eu`.

Odds-API.io (`reference.source: odds_api_io`) er fortsatt støttet, men krever betalt plan. [SharpOddz](https://sportsapis.dev/apis/sharpoddz) er ikke implementert, fordi API-dokumentasjonen deres ikke er offentlig, og fordi den koster penger etter en prøvedag.

## Mine spill

Under «Registrer spill» på hvert kort logger du et spill: utfall, oddsen du fikk og innsatsen. Fair odds og EV i øyeblikket lagres sammen med spillet. Fanen «Mine spill» viser:

- antall spill, resultat i kroner, ROI og hva EV-en tilsa
- snitt-CLV: oddsen du tok mot fair sluttodds, altså referansens siste odds før avspark med marginen fjernet
- hvor sikre snittene er (95 %-intervall og p-verdi), og omtrent hvor mange spill som trengs til, når det er minst 10 spill

Sluttoddsen oppdateres hver gang du henter referanseodds før avspark. Hent derfor referanseodds like før kampene du har spilt på, gjerne bare for de ligaene. CLV viser om du har en fordel etter 40–100 spill, mens gevinst og tap trenger tusenvis. Resultatet (vunnet, tapt, annullert) setter du selv i tabellen etter kampen.

Spilloggen kan lastes ned og opp som CSV. På Streamlit Cloud starter databasen på nytt når appen startes på nytt. Da forsvinner spilloggen, med mindre den også lagres i en database utenfor appen (under).

### Varig spillogg

Med `DATABASE_URL` til en Postgres-database lagrer appen spilloggen der i tillegg. Hver gang den endres, lagres den på nytt, og forrige versjon tas vare på. Når appen starter på nytt, leses den inn igjen av seg selv. Gratisplanen til [Neon](https://neon.com) holder godt: 0,5 GB, og databasen sover når den ikke brukes og våkner av seg selv ved neste spørring. Supabase passer dårligere, siden gratisprosjekter settes på pause etter en uke uten bruk.

1. Gå til [neon.com](https://neon.com) og logg inn med GitHub.
2. Lag et prosjekt, for eksempel `odds`, med region «AWS Europe Central 1 (Frankfurt)».
3. Trykk «Connect» og kopier «Connection string». Den begynner med `postgresql://`.
4. I Streamlit: «Manage app» → ⋮ → «Settings» → «Secrets». Legg til en linje under API-nøkkelen, med anførselstegn:
   ```
   DATABASE_URL = "postgresql://…"
   ```
5. Trykk «Save». Under «Mine spill» står det nå «Spilloggen lagres i databasen».

Spilloggen ligger som CSV i tabellen `oddscompare_store` (nøklene `bets.csv` og `bets.previous.csv`), som appen lager selv. Lokalt kan du legge `DATABASE_URL` i `.env`. Svarer ikke databasen, virker spilloggen i appen som før, og den lagres ved neste klikk.

## Varsler

`oddscompare watch` gjør én varslingsrunde, og GitHub Actions kjører den (`.github/workflows/odds-alerts.yml`). Den har ingen tidsplan hos GitHub, som hoppet over de fleste kjøringene: cron-job.org starter den én gang i timen (steg 5 under). En kjøring som starter inntil 5 minutter før timen er gått, regnes som en ny time. Det er gratis, siden repoet er offentlig. Hver runde gjør dette:

1. Henter Norsk Tippings odds. Det er gratis.
2. Kjøper referanseodds (Pinnacle og konkurrentene) to ganger per kamp: én tidlig sjekk rundt 3 timer før avspark, og én innen 75 minutter før. Det koster 1 kreditt per liga. En kamp sjekkes igjen hvis Norsk Tipping har hevet et utfall med 5 % siden forrige sjekk. De tidlige sjekkene gjøres bare til dagen har brukt halvparten av kredittaket, så det alltid er kreditter igjen til sjekkene like før avspark, som er de mest presise.
   Med OddsLink (standard) koster alle kampene én forespørsel, så da sjekkes i stedet alle kampene de neste 7 dagene (`alerts.days_ahead`) én gang i timen (`scan_minutes`), også kampene som starter snart. Det blir høyst 24 forespørsler i døgnet, rundt 740 i måneden, og resten av de 1 000 er til knappene i appen. Feiler OddsLink, spørres The Odds API bare for kampene som starter snart, siden den tar betalt per liga. Overvåkeren sletter oddshistorikk eldre enn 12 timer (`history_hours`), men beholder siste odds for hver kamp, så databasen i GitHub-cachen holder seg liten.
3. Sender varsel til telefonen når et utfall har EV på minst 2 % mot Pinnacle, Pinnacles margin er høyst 6 %, referanseoddsen er fersk og Norsk Tipping ikke har flyttet seg siden. Hvert utfall varsles én gang, og igjen bare hvis EV har økt med minst ett prosentpoeng.

Overvåkeren bruker høyst 24 kreditter (med OddsLink: forespørsler) per dag, og aldri de siste 30 i måneden. Grensene står under `alerts` i `config.yaml`. Den deler kredittene med knappen i appen.

**Slik setter du det opp:**

1. Installer appen **ntfy** (iPhone eller Android). Abonner på et emne med et hemmelig navn som ingen kan gjette, for eksempel `odds-` fulgt av 20 tilfeldige tegn. Server: `ntfy.sh`.
2. Legg to hemmeligheter i repoet på GitHub under «Settings» → «Secrets and variables» → «Actions» → «New repository secret»:
   - `ODDSLINK_API_KEY`: nøkkelen fra OddsLink
   - `THE_ODDS_API_KEY`: nøkkelen fra The Odds API (reserve når OddsLink feiler)
   - `NTFY_TOPIC`: emnenavnet fra steg 1
   - `NTFY_TOKEN` er valgfri: en tilgangsnøkkel fra en ntfy-konto. På gratisplanen gir den ingen høyere grense, så den trengs bare med betalt plan eller egen ntfy-server.
3. Flett PR-en til `main`. Kjøringene fra cron-job.org bruker koden på `main`.
4. Test under «Actions» → «odds-alerts» → «Run workflow». Kryss av for «Send ett testvarsel nå», så får du ett varsel merket «TEST» for det beste utfallet akkurat nå, uansett terskel (eller et vanlig testvarsel når ingen kamp har referanseodds ennå). Lokalt: `oddscompare watch --test`, eller `oddscompare notify-test` for bare et testvarsel.
5. Start kjøringene fra **cron-job.org** (gratis), siden GitHubs tidsplan hopper over de fleste:
   - Lag en fine-grained token på github.com/settings/personal-access-tokens/new med bare dette repoet og «Actions: Read and write».
   - Lag en cron-jobb som én gang i timen sender `POST` til `https://api.github.com/repos/<eier>/<repo>/actions/workflows/odds-alerts.yml/dispatches` med body `{"ref":"main"}`.
   - Bruk headerne `Authorization: Bearer <tokenet>`, `Accept: application/vnd.github+json` og `Content-Type: application/json`.
   - Svaret på «Test run» skal være 204.

ntfy.sh tar imot 250 varsler i døgnet per IP-adresse på gratisplanen, også med konto, og grensen deles med alle som bruker samme adresse. Blir et varsel avvist, prøver overvåkeren igjen ved neste kjøring. GitHub gir hver kjøring en ny maskin, ofte med en annen adresse.

Varselet har lenke til odds-siden i `alerts.app_url`: trykk på varselet eller knappen «Åpne odds-siden», så åpnes Streamlit-appen, som henter ferske odds. Feiler hentingen fra Norsk Tipping eller The Odds API, for eksempel fordi nøkkelen er feil, blir kjøringen rød på GitHub, og du får e-post om det.

## Matching av kamper

En Norsk Tipping-kamp er samme kamp som en referansekamp når begge lagnavn matcher og avsparkstiden er innenfor ±30 minutter. Hjemme og borte må stemme, så byttet rekkefølge regnes ikke som match.

Lagnavn normaliseres slik:

- små bokstaver
- ø → o, å → a, æ → ae, og andre aksenter fjernes
- punktum fjernes, og & leses som «and»
- ord for klubbform fjernes, som «FK», «IL», «FC», «BK», «IF», «FF» og «SK» (se `STRIP_WORDS` i `matching.py`), og årstall som «1899»

Er det ene navnet det andre med ekstra ord («Oviedo» og «Real Oviedo»), regnes det som treff. Unntaket er når de ekstra ordene betyr et annet lag i klubben, som «II», «U21» eller «Women». «Hoffenheim» matcher derfor aldri «Hoffenheim II».

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
