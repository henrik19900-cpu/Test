# Opsjonskalkulator

Kalkulatorer for formlene i Espen Gaarder Haug: *The Complete Guide to Option Pricing Formulas*, 2. utgave (McGraw-Hill, 2007). Hver formel i boka har sitt eget skjema, gruppert etter bokas kapitler, med pris, Greeks, numeriske følsomheter og en graf over pris mot spot.

## Bruk

Åpne `dist/opsjonskalkulator.html` i en nettleser. Hele appen ligger i den ene filen og virker uten nettilgang (bare skrifttypene hentes fra Google Fonts).

- Velg kalkulator i registeret til venstre, eller søk etter navn, forfatter eller begrep.
- Standardverdiene i hvert skjema er bokas talleksempel når boka har ett. Et grønt merke viser at resultatet stemmer med boka.
- Desimaltall kan skrives med komma eller punktum. Renter og volatiliteter oppgis som desimaltall, som i boka: 0,08 betyr 8 %.
- Tidsderivater (theta, charm, color, veta) er per år når tiden går, altså −∂/∂T. Theta vises også per dag.
- Hver kalkulator har en egen adresse, for eksempel `#bsm-black-scholes`, som kan bokmerkes.

## Utvikling

Krever Node 22 eller nyere.

```sh
npm install      # installerer esbuild (bare for bygging)
npm test         # kjører alle testene
npm run build    # bygger dist/opsjonskalkulator.html
```

### Struktur

| Mappe | Innhold |
|---|---|
| `src/math/` | Normalfordelinger (Hart 1968, Genz 2004), løsere, integrasjon, tilfeldige tall, spesialfunksjoner |
| `src/models/` | Prisformlene, én fil per område (BSM, amerikanske, eksotiske, barrierer, to aktiva, renter …) |
| `src/catalog/` | Én katalogfil per kapittel som beskriver skjemaene: inndata, standardverdier, resultater og bokas eksempel |
| `web/` | Nett-UI-et (`app.js`) og HTML-malen med stiler |
| `test/` | Tester per område, pluss en generisk test som kjører alle kalkulatorene |
| `scripts/build.mjs` | Pakker alt til én HTML-fil |

### Slik er formlene kontrollert

1. **Bokas talleksempler.** Der boka trykker et eksempel, er det standardinput i skjemaet, og testene krever at resultatet stemmer med fire desimaler.
2. **Uavhengige beregninger.** Hver lukket formel sammenlignes med Monte Carlo (fast seed, innenfor fire standardfeil), binomialtrær, finite difference eller numerisk integrasjon. Kontinuerlige barrierer simuleres med brownsk bro.
3. **Identiteter.** Inn + ut = vanilla, put-call-paritet og -symmetri, og grensetilfeller som skal gi Black-Scholes-Merton.
4. **Greeks.** Alle analytiske Greeks sammenlignes med numeriske derivater.

### Legge til en kalkulator

En kalkulator er et objekt i en katalogfil i `src/catalog/`. Formatet er beskrevet øverst i `src/catalog/common.js`. UI-et lager skjema, resultatvisning, følsomheter og graf automatisk, og `test/catalog.test.js` sjekker den nye oppføringen.

## Forbehold

Formlene er implementert på nytt fra den matematiske beskrivelsen. Prosjektet har ingen tilknytning til forfatteren eller forlaget, og bruker ingen tekst eller kode fra boka eller CD-en. Resultatene er ikke investeringsråd.
