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
- [Hente inn annonser fra andre kilder](#hente-inn-annonser-fra-andre-kilder)
- [Sette i drift](#sette-i-drift)
- [Sjekkliste før lansering](#sjekkliste-før-lansering)
- [Drift](#drift)
- [Kapasitet og serverkrav](#kapasitet-og-serverkrav)
- [Konfigurasjon](#konfigurasjon)
- [Utvikling](#utvikling)

## Funksjoner

- **42 kategorier** i fem hovedgrupper, med egne felt per kategori (for eksempel merke, årsmodell, kilometerstand og drivstoff for biler) og alle 16 fylker.
- **Søk** som finner deler av ord (`sofa` finner også `hjørnesofa`), med filtre for kategori, type, sted, pris og kategorifelt. Det er like raskt med en million annonser (se [Kapasitet og serverkrav](#kapasitet-og-serverkrav)).
- **Annonser ligger ute i 60 dager** og kan fornyes med ett klikk. Selgeren får e-post når en annonse går ut.
- **Gamle annonser slettes automatisk:** en annonse som ikke er aktiv og ikke er endret på ett år, slettes med bildene. Selgeren får beskjed på Min side og på e-post 14 dager før.
- **Meldinger** mellom kjøper og selger, med e-postvarsel til bekreftede adresser, hurtigsvar for selgeren («Ja, den er fortsatt til salgs») og blokkering av brukere man ikke vil høre fra. Selgerens svartid vises på annonsen («Svarer vanligvis innen en time»). Samtaler kan slettes fra innboksen, og når begge har slettet en samtale, slettes den for godt.
- **For selgere:** hvor mange som har sett annonsen og lagret den, og valg av hovedbilde.
- **Vurderinger:** når selgeren har registrert handelen i samtalen («Solgt til Ola»), kan kjøper og selger vurdere hverandre fra 1 til 5 med en kommentar, innen 14 dager. Vurderingene vises når begge har vurdert, eller når fristen er ute, så ingen svarer på en vurdering de har lest. Snittet står på profilen og ved annonsen. Usanne eller krenkende vurderinger kan rapporteres og fjernes av en moderator.
- **Favoritter og lagrede søk:** lagre annonser med hjertet, og lagre et søk for å se hvor mange nye treff som har kommet siden sist. Med bekreftet e-post kommer nye treff på e-post, høyst én gang i timen per søk, med lenke for å melde seg av uten å logge inn. Selgeren ser hvor mange som har lagret annonsen, men ikke hvem.
- **Prisvarsel:** settes prisen på en favoritt ned med minst 5 %, vises den gamle prisen på favorittsiden, og man får e-post om det (høyst to ganger i døgnet, kan slås av).
- **Deling:** «Del»-knappen åpner mobilens delemeny (eller kopierer lenken), og hver annonse har forhåndsvisning med bilde, tittel og pris når den deles i meldinger og sosiale medier (Open Graph). Annonsesiden viser også lignende annonser. Siden kan legges på hjemskjermen på mobilen med eget ikon.
- **Glemt passord** løses med en lenke på e-post eller en kode på SMS til det bekreftede nummeret.
- **Bilder** som skaleres, lagres som WebP og får fjernet EXIF- og GPS-data.
- **Bekreftede brukere:** norsk mobilnummer med SMS-kode som standard, BankID som valg.
- **Beskyttelse mot svindel**, moderering og rapportering (se under).
- **Åpent for agenter:** MCP-server, REST-API med OpenAPI 3.1, `llms.txt`, eksport av alle annonser som NDJSON, Atom-feeder og JSON/Markdown-versjon av hver side.
- **Annonser fra åpne kilder:** titusenvis av ledige stillinger fra arbeidsplassen.no (Nav), og svenske stillinger for folk som kan norsk. Alt hentes automatisk og holdes oppdatert.
- **Universell utforming og personvern:** fungerer uten JavaScript (det lille skriptet for «Del» er et tillegg), synlig tastaturfokus og god kontrast i lyst og mørkt tema, ingen sporingskapsler og ingen reklame.

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
| `fritorg.sqlite3` | SQLite-database i WAL-modus: brukere, annonser, meldinger, handler og vurderinger, favoritter, lagrede søk, rapporter og modereringslogg. Fulltekstsøket bruker SQLite FTS5. Databasen oppgraderes automatisk når appen starter med en ny versjon (migreringene står i `fritorg/db.py`). |
| `uploads/` | Bilder som WebP, i full størrelse (maks 1600 piksler) og som miniatyrbilde. Filnavnene er tilfeldige, og filene ligger i 256 undermapper etter de to første tegnene i navnet. Mappen kan legges et annet sted med `FRITORG_UPLOADS_DIR`. |
| `secret_key` | Hemmelig nøkkel, opprettes automatisk hvis `FRITORG_SECRET_KEY` ikke er satt. Den trengs for å kjenne igjen mobilnumre, BankID-identiteter og lenker, så den må tas vare på. |

Postnummerregisteret til Posten Bring AS (åpne data under NLOD 2.0) følger med koden i `fritorg/data/postnummer.tsv`, så postnummeret i en annonse kan fylle ut sted og fylke. Oppdater filen én gang i året fra [data.norge.no](https://data.norge.no/datasets/f7508db5-2167-3356-ab5e-aacffce2a9b6).

Om brukerne lagres e-postadresse, visningsnavn og passord som en scrypt-hash. Mobilnummeret lagres aldri i klartekst, bare som en nøkkelbasert hash (så hvert nummer kan brukes på én konto) og de tre siste sifrene. Med BankID lagres navnet, men aldri fødselsnummeret.

Annonser som ikke er aktive (skjulte, utløpte, solgte, til kontroll og fjernede), slettes automatisk med bildene når de ikke har vært endret på ett år (`FRITORG_DELETE_AFTER_DAYS`). Eieren får beskjed på Min side og på e-post 14 dager før, og annonsen blir stående hvis den gjøres aktiv igjen eller endres innen da. Meldinger om en slettet annonse blir liggende. Annonser fra Nav, Platsbanken og bedrifter som synkroniserer lageret sitt, følger kilden.

Én SQLite-fil holder for en million annonser og mer på en liten server (se [Kapasitet og serverkrav](#kapasitet-og-serverkrav)). Appen kjører som én prosess. Skal den skaleres ut på flere servere, må databasen og fartsgrensene (som nå ligger i minnet) flyttes til en felles tjeneste.

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
- **Moderering** på `/moderering`: godkjenne eller fjerne annonser, avvise rapporter, fjerne vurderinger og stenge kontoer. Alt logges.
- **Klage:** den som får en annonse fjernet, ser begrunnelsen og kan klage én gang. En moderator publiserer annonsen igjen eller svarer på e-post hvorfor den forblir fjernet. Stengte kontoer får vite hvor de kan klage (`FRITORG_CONTACT_EMAIL`).
- **Merking:** «Mobilnummer bekreftet» eller «BankID-verifisert», «Ny bruker» og «via AI-agent».
- **Navn som kan forveksles** med siden selv eller kjente selskaper (for eksempel «Fritorg», «Vipps», «Posten») avvises.

## For AI-agenter

- Veiledning: `/for-agenter` (også som `/for-agenter.md`) og `/llms.txt`.
- MCP-server (Streamable HTTP): `/mcp`. Uten nøkkel får agenten verktøy for å lese, med en personlig nøkkel også for å skrive. Eksempel: `claude mcp add --transport http fritorg https://fritorg.no/mcp`
- Innlogging fra AI-assistenten: `/mcp/konto` ber assistenten logge inn (OAuth 2.1 med PKCE og dynamisk registrering, slik MCP-spesifikasjonen beskriver). Brukeren logger inn og godkjenner, og assistenten får en vanlig API-nøkkel som vises og kan slettes på Min side. Claude, ChatGPT, Claude Code, Cursor og VS Code støtter dette.
- REST-API: `/api/v1`, dokumentert i `/openapi.json` og `/api/docs`. Feil følger RFC 9457 med norsk `detail` og engelsk `hint`.
- Agenter kan be om tilgang selv med device flow (`POST /api/v1/auth/device`), og personen godkjenner på `/koble-til`.
- Agenter kan følge med på søk for brukeren (`save_search` og `check_saved_searches`, eller `/api/v1/me/saved-searches`) og lagre favoritter.
- Alle offentlige annonser: `/api/v1/export/listings.ndjson`.

## Hente inn annonser fra andre kilder

Å kopiere annonser fra finn.no eller andre markedsplasser er ikke lovlig. Det bryter FINNs vilkår, som forbyr kopiering og automatisk innhenting, og databasevernet i åndsverkloven § 24. Bildene er dessuten fotografenes, og annonsene inneholder personopplysninger om private selgere. Disse veiene er lovlige:

1. **Ledige stillinger fra Nav (innebygd).** Navs åpne stillingsfeed kan brukes av alle, og [vilkårene](https://arbeidsplassen.nav.no/vilkar-api) gir uttrykkelig rett til å publisere annonsene videre. Til gjengjeld må annonser som endres eller avsluttes hos Nav, endres eller fjernes straks, og «Søk på stillingen» må lenke direkte til arbeidsgiverens søknadsside. Fritorg gjør alt dette automatisk:
   - Slå det på med `FRITORG_NAV_IMPORT=1`. Importen kjører i bakgrunnen og sjekker feeden hvert annet minutt. Den første importen av alle aktive stillinger tar noen timer.
   - Be om et eget token: send en e-post til nav.team.arbeidsplassen@nav.no der du bekrefter at du godtar vilkårene, med firmanavn, kontaktperson, e-post og telefon. Legg tokenet i `FRITORG_NAV_TOKEN`. Uten det brukes Navs offentlige testtoken, som byttes ut med jevne mellomrom.
   - Kontaktpersonlistene fra Nav lagres ikke, og stillingene er ikke med i bulk-eksporten (de finnes i Navs egen feed).
   - Manuelt: `fritorg import-nav --until-done`.
2. **Bedrifter som deler sine egne annonser.** Bilforhandlere, meglere, butikker, auksjonshus og arbeidsgivere eier annonsene sine og kan sende dem til flere markedsplasser, slik meglerne gjør med hjem.no. Med `PUT /api/v1/me/feeds/{feed}` sender de hele lageret i ett kall, og Fritorg lager, endrer og fjerner annonser så det stemmer. Siden `/for-bedrifter` forklarer hvordan. Avtalen bør si at de har rett til tekst og bilder.
3. **Selgere som flytter sine egne annonser.** En selger kan legge ut samme vare her, med sin egen tekst og sine egne bilder fra mobilen eller PC-en. AI-assistenter kan hjelpe til via MCP. Ikke hent annonsen automatisk fra finn.no.
4. **Svenske stillinger (innebygd).** Stillinger fra Platsbanken som ligger i Norge eller krever norsk (CC0, rundt 200), slås på med `FRITORG_JOBTECH_IMPORT=1`. Kontaktpersonene tas ikke med.
5. **Lenker.** En vanlig lenke til et søk på en annen side er lovlig, men vis aldri andres søkeresultater inne på Fritorg.

Disse kildene krever en avtale, men er verdt å kontakte: Auksjonen.no (vilkårene åpner for å formidle auksjonsannonser eksternt), rekrutteringssystemer som Teamtailor og Jobylon (stillinger som ikke er hos Nav), utbyggere og boligbyggelag som OBOS og Selvaag Bolig, Loopfront (brukte møbler og utstyr fra kommuner), BUA (gratis utlån av utstyr), frivillig.no og affiliate-nettverk som Adtraction for nye varer fra nettbutikker (må merkes som reklame). Å kopiere fra finn.no, Blocket, Tise, eBay, Etsy eller Facebook er ikke lov.

Dette bygger på en gjennomgang av vilkårene, loven og rettspraksis (blant annet Innoweb, C-202/12, og HR-2019-1725-A om Lovdata). Det er ikke juridisk rådgivning: la en advokat se på det før lansering.

## Sette i drift

Oppsettet i `deploy/` kjører Fritorg i Docker bak [Caddy](https://caddyserver.com/), som henter og fornyer HTTPS-sertifikater automatisk.

1. Skaff en server med Docker (for eksempel en liten VPS i Norge eller EU) og pek domenets A/AAAA-oppføring dit. En gratis maskin hos Oracle Cloud holder godt: se [steg for steg](deploy/oracle-cloud.md).
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
- [ ] Personvern:
  - juridisk gjennomgang av vilkår og personvernerklæring (`/vilkar` er et utkast), også aldersgrensen (18 år) og lagringstidene
  - protokoll over behandlingene (personvernforordningen artikkel 30) og en vurdering av personvernkonsekvenser (DPIA, artikkel 35), fordi alle meldinger sjekkes automatisk for svindel og annonsene deles åpent med AI-agenter
  - databehandleravtaler med server-, SMS- og e-postleverandøren (og BankID-megleren), en vurdering av overføringen til USA hvis SMS går gjennom Twilio, og `FRITORG_PROCESSORS` satt
  - rutiner for avvik (melding til Datatilsynet innen 72 timer), for henvendelser som kommer på e-post (`fritorg export-user` og `fritorg delete-user`) og for hvem som får være moderator
  - sikkerhetskopiene lagres kryptert i EØS, slettes etter 30 dager, og `FRITORG_SECRET_KEY` er lagret et annet sted
- [ ] `FRITORG_SEED_DEMO` er av, så det ikke ligger demo-annonser på den ekte siden.
- [ ] Eget token for Navs stillingsfeed, hvis stillingene fra arbeidsplassen.no skal vises (se over).

## Drift

```sh
fritorg doctor [--send-test-mail ADRESSE] [--send-test-sms NUMMER]   # klar for lansering?
fritorg make-admin E-POST                                            # gi moderatorrettigheter
fritorg backup MAPPE [--keep 7] [--with-key]                         # database og bilder (nøkkelen bare med --with-key)
fritorg import-nav [--until-done]                                    # hent ledige stillinger fra Nav nå
fritorg benchmark [--listings 1000000]                               # mål søket med oppdiktede annonser
fritorg seed [--force]                                               # demo-data (ikke i produksjon)
```

Med Docker kjøres kommandoene med `docker compose exec app ...`. En enkel daglig sikkerhetskopi (crontab på serveren):

```sh
0 3 * * * cd /sti/til/fritorg/deploy && docker compose exec -T app fritorg backup /data/backup && rm -rf ./backup && docker compose cp app:/data/backup ./backup
```

Sikkerhetskopien tas mens appen kjører, og databasen blir konsistent. Den har de 7 nyeste kopiene av databasen og bildene slik de er nå, så et bilde som er slettet på siden, forsvinner også fra kopien. Bare eieren av filene kan lese dem. Kopier mappen videre til et annet sted, kryptert (for eksempel objektlagring), og slett kopier som er eldre enn 30 dager: personvernerklæringen sier at sikkerhetskopier slettes etter 30 dager.

Den hemmelige nøkkelen er ikke med i sikkerhetskopien, fordi mobilnumrene kan finnes igjen fra hashene med den. Ta vare på `FRITORG_SECRET_KEY` (i `.env`) et annet sted, for eksempel i en passordbehandler. Uten den virker gjenopprettingen, men alle må bekrefte mobilnummeret på nytt, og BankID-kontoer kobles ikke lenger til personen.

Loggene: Caddy fører en tilgangslogg med IP-adresse og side, uten nøkler, engangslenker og e-postadresser, og sletter den etter 14 dager. Appen logger bare feil, og Docker roterer loggene.

## Kapasitet og serverkrav

Fritorg skal kunne ha veldig mange annonser på én liten server. Det er målt med en testdatabase med 1 million oppdiktede annonser, omtrent like mange som på finn.no. Testmaskinen hadde to prosessorkjerner (Intel Xeon, 2,1 GHz). Før denne versjonen tok forsiden 3 sekunder å lage med så mange annonser, og et søk opptil 5 sekunder. Nå tar en hel side, med HTML:

| Side (1 million annonser) | Tid |
| --- | --- |
| Forsiden | 8 ms |
| Kategori, for eksempel Møbler | 8 ms |
| Søk «sofa» | 13 ms |
| Søk «sofa» i Oslo | 30 ms |
| Smalt søk, for eksempel «leilighet» i Finnmark | 60 ms |
| Bil, lavest pris først | 8 ms |
| En annonse | 8 ms |
| Søk i API-et | 16 ms |

Under full belastning, med 16 brukere som klikker uten pause på en blanding av søk og annonser, klarte de to kjernene 77 sidevisninger i sekundet. Det tilsvarer over 6 millioner i døgnet. Appen brukte da 150 MB minne. Resten av minnet går til operativsystemets hurtigbuffer for databasefilen.

Slik holder søket seg raskt:

- Søket gjør like mye arbeid enten det er tusen eller en million annonser. Annonsene på en side hentes fra indekser som har alle feltene det filtreres og sorteres på, og spørringen stopper så snart siden er full. Bare annonsene som vises, leses i sin helhet.
- Treff telles opp til 1 000. Er det flere, står det «Over 1 000 treff». For vanlige ord ser tellingen på de 20 000 nyeste treffene, og står det da «Minst 450 treff», kan det være flere. Sidene viser likevel alle treffene. Antall annonser per kategori telles én gang i minuttet.
- Fylke, kategori og sted ligger som egne merker i søkeindeksen, så «sofa i Finnmark» bare leser sofaene i Finnmark.
- «Mest relevant» setter annonser med alle ordene i tittelen, kategorien, stedet eller egenskapene først, de nyeste først. Blant svært vanlige ord gjelder det de 2 000 nyeste treffene.
- Søkeindeksen leser teksten fra annonsetabellen i stedet for å ha sin egen kopi. Den oppdateres av databasen selv, så den aldri kommer ut av takt med annonsene.
- Bildene serveres direkte av Caddy, så Python bare lager sidene. Sjekken av gjenbrukte bilder slår opp i en indeks i stedet for å sammenligne med alle bildene.
- Sitemap deles i filer på 50 000 annonser, som søkemotorene krever. Eksporten av alle annonser leser 30 000 annonser i sekundet.
- Vedlikeholdet oppdaterer statistikken SQLite bruker til å velge indekser, én gang i døgnet.
- Gamle annonser slettes automatisk etter ett år, 500 om gangen hvert tiende minutt, så databasen og bildene ikke vokser for alltid.

**Plassbehov.** Med testdataene (beskrivelser på rundt 800 tegn i snitt) tar databasen rundt 6 kB per annonse, altså 6 GB for en million annonser. Søkeindeksen er drøyt halvparten av det. Bildene tar mest plass: rundt 0,25 MB per bilde (stort bilde og miniatyr). Med tre bilder per annonse blir det rundt 75 GB per 100 000 annonser. Fordi gamle annonser slettes etter ett år, avhenger plassen av hvor mange annonser som legges ut i løpet av et år, ikke av hvor lenge siden har vært i drift.

| Annonser | Server |
| --- | --- |
| Inntil 100 000 | 2 kjerner, 2 GB minne, 40 GB disk og et volum til bildene |
| Inntil 1 million | 2–4 kjerner, 4–8 GB minne, 20 GB disk til databasen og et volum til bildene (rundt 750 GB) |

Prøv en server før du leier den: `fritorg benchmark --listings 1000000` lager en egen testdatabase med oppdiktede annonser, måler de vanligste søkene og sletter databasen etterpå. Med 100 000 annonser tar det et par minutter, med en million rundt en halvtime.

Neste steg, når det trengs:

- **Mer trafikk:** sett et CDN (for eksempel Cloudflare) foran siden, så bilder og filer i `/static` leveres derfra. Kjør appen i flere prosesser. Da må bakgrunnsjobbene (vedlikehold og import) bare kjøres i én av dem.
- **Flere bilder enn disken rommer:** flytt bildene til S3-kompatibel objektlagring. Lagringen av bilder ligger samlet i `fritorg/images.py`.

## Konfigurasjon

Alle innstillinger er miljøvariabler. De viktigste:

| Variabel | Standard | Betydning |
| --- | --- | --- |
| `FRITORG_BASE_URL` | utledes fra forespørselen | Offentlig adresse, for eksempel `https://fritorg.no`. Med https slås HSTS og sikre informasjonskapsler på. |
| `FRITORG_DATA_DIR` | `data` | Mappe for database, bilder og nøkkel. |
| `FRITORG_UPLOADS_DIR` | `data/uploads` | Mappe for bildene. I `deploy/` er det et eget volum, så Caddy kan servere bildene uten tilgang til databasen. |
| `FRITORG_SECRET_KEY` | fil i datamappen | Hemmelig nøkkel (64 heksadesimale tegn). |
| `FRITORG_SITE_NAME` | `Fritorg` | Navnet på siden. |
| `FRITORG_OPERATOR`, `FRITORG_CONTACT_EMAIL` | – | Behandlingsansvarlig og kontaktadresse for personvern (vises i vilkårene; `fritorg doctor` krever dem). |
| `FRITORG_PROCESSORS` | – | Databehandlerne, slik personvernerklæringen skal nevne dem, f.eks. «Oracle Cloud (servere, Sverige), Twilio (SMS, USA)». |
| `FRITORG_VERIFICATION` | `sms` | `sms` eller `none` (bare for testing). |
| `FRITORG_SMS_PROVIDER` | `console` | `twilio`, `http` eller `console` (viser koden på skjermen, avvises på https-sider). |
| `FRITORG_TWILIO_ACCOUNT_SID`, `_AUTH_TOKEN`, `_FROM` | – | Twilio-konto og avsender. |
| `FRITORG_SMS_URL`, `FRITORG_SMS_METHOD` | –, `GET` | URL-mal for `http`-leverandører (se `deploy/.env.example`). |
| `FRITORG_SMS_DAILY_LIMIT`, `FRITORG_SMS_PER_IP_PER_HOUR` | `2000`, `10` | Grenser for antall SMS-koder. |
| `FRITORG_BANKID` | `off` | `oidc` for ekte BankID, `simulated` for utvikling. |
| `FRITORG_BANKID_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET`, `_SCOPE`, `_ACR_VALUES`, `_ID_CLAIM` | – | BankID-leverandøren (OpenID Connect). |
| `FRITORG_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_FROM`, `_SECURITY` | –, `587`, …, `starttls` | Utgående e-post. Uten `FRITORG_SMTP_HOST` sendes ingen e-post. |
| `FRITORG_RATE_LIMIT_READ`, `_WRITE`, `_AUTH` | `600`, `60`, `30` | Fartsgrenser per IP-adresse (lesing og skriving per minutt, innlogging per 10 minutter). |
| `FRITORG_LISTING_DAYS` | `60` | Hvor lenge en annonse ligger ute før den skjules og kan fornyes (0 = for alltid). |
| `FRITORG_DELETE_AFTER_DAYS` | `365` | Annonser som ikke er aktive, slettes med bildene når de ikke er endret på så mange dager, etter varsel 14 dager før (0 = aldri). Vilkårene viser tallet. |
| `FRITORG_MAX_LISTINGS_PER_DAY`, `FRITORG_MAX_MESSAGES_PER_DAY` | `50`, `200` | Grenser per konto per døgn. |
| `FRITORG_NEW_ACCOUNT_MAX_LISTINGS_PER_DAY`, `..._MESSAGES_PER_DAY` | `5`, `20` | Grenser det første døgnet. |
| `FRITORG_MAX_IMAGE_BYTES`, `FRITORG_MAX_IMAGES_PER_LISTING` | 8 MB, `12` | Bildegrenser. |
| `FRITORG_NAV_IMPORT` | av | Hent ledige stillinger fra arbeidsplassen.no (Nav). |
| `FRITORG_NAV_TOKEN` | Navs testtoken | Eget token for Navs stillingsfeed. |
| `FRITORG_NAV_IMPORT_INTERVAL` | `120` | Sekunder mellom hver sjekk av feeden. |
| `FRITORG_JOBTECH_IMPORT` | av | Hent svenske stillinger i Norge eller som krever norsk. |
| `FRITORG_SEED_DEMO` | av | Legg inn demo-data ved første oppstart. |
| `FORWARDED_ALLOW_IPS` | private adresser i Docker | Proxyer som får oppgi den besøkendes IP-adresse (`X-Forwarded-For`). Bak en CDN legger du til CDN-ens adresser her og i Caddy (se `deploy/Caddyfile`). |

## Utvikling

```sh
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

Testene dekker API-et, MCP-serveren (også med den offisielle MCP-klienten), søk, svindelbeskyttelse, BankID, SMS-bekreftelse, importen fra Nav, bilder, e-post og drift. GitHub Actions kjører dem på Python 3.11 og 3.13, og bygger og prøvekjører Docker-imaget.

Koden ligger i `fritorg/`: `app.py` setter alt sammen, `api.py` er REST-API-et, `mcp_server.py` MCP-serveren og `web.py` nettsidene. `listings.py`, `messages.py`, `users.py`, `fraud.py`, `phone.py`, `identity.py` og `navjobs.py` (importen fra Nav) inneholder logikken, og `templates/` sidene og dokumentasjonen.
