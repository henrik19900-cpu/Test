# Opsjonskalkulator

Kalkulatorer for formlene i Espen Gaarder Haug: *The Complete Guide to Option Pricing Formulas*, 2. utgave (McGraw-Hill, 2007). Hver formel i boka har sitt eget skjema, gruppert etter bokas kapitler, med pris, Greeks, numeriske følsomheter og en graf over pris mot spot.

Appen har 157 kalkulatorer fordelt på alle bokas 14 kapitler:

| Kap. | Innhold | Antall |
|---:|---|---:|
| 1 | Black-Scholes-Merton og modellene før BSM | 11 |
| 2 | Greeks, innløsningskurs fra delta, implisitt volatilitet | 4 |
| 3 | Amerikanske opsjoner: BAW, Bjerksund-Stensland 1993/2002, evigvarende | 6 |
| 4 | Eksotiske opsjoner på ett underliggende, inkl. barrierer, binære, lookback og asiatiske | 43 |
| 5 | Eksotiske opsjoner på to underliggende og valutaoversatte opsjoner | 18 |
| 6 | Hopp-diffusjon, Leland, Hull-White, SABR, CEV, Heston | 10 |
| 7 | Binomial-, trinomial- og tredimensjonale trær, Derman-Kani, finite difference | 8 |
| 8 | Monte Carlo, kvasi-MC, kontrollvariat, Longstaff-Schwartz | 5 |
| 9 | Diskrete utbytter: escrowed, volatilitetsjusteringer, HHL, Roll-Geske-Whaley | 11 |
| 10 | Råvarer og energi: swapper, swapsjoner, Miltersen-Schwartz, Schwartz | 5 |
| 11 | Renter: FRA, obligasjoner, caps, swapsjoner, Vasicek, Hull-White, BDT | 18 |
| 12 | Historisk og implisitt volatilitet og korrelasjon, variansswap | 12 |
| 13 | Normalfordeling, bivariat normal, lognormal pris | 4 |
| 14 | Rentekonvertering og forwardpris | 2 |

34 av kalkulatorene har bokas talleksempel som standardverdier, og testene krever at resultatet stemmer med fire desimaler.

`npm run build` lager også `dist/va-formler/opsjonskalkulator/index.html`, som er versjonen for <https://va-formler.no/opsjonskalkulator/>.

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

1. **Bokas talleksempler.** Der boka trykker et eksempel, er det standardinput i skjemaet, og testene krever at resultatet stemmer med fire desimaler. For formler der boka har hele tabeller, sjekker testene bare et lite utvalg av tallene; resten dekkes av punktene under.
2. **Uavhengige beregninger.** Hver lukket formel sammenlignes med Monte Carlo (fast seed, innenfor fire standardfeil), binomialtrær, finite difference eller numerisk integrasjon. Kontinuerlige barrierer simuleres med brownsk bro.
3. **Identiteter.** Inn + ut = vanilla, put-call-paritet og -symmetri, og grensetilfeller som skal gi Black-Scholes-Merton.
4. **Greeks.** Alle analytiske Greeks sammenlignes med numeriske derivater.

### Legge til en kalkulator

En kalkulator er et objekt i en katalogfil i `src/catalog/`. Formatet er beskrevet øverst i `src/catalog/common.js`. UI-et lager skjema, resultatvisning, følsomheter og graf automatisk, og `test/catalog.test.js` sjekker den nye oppføringen.

## Merknader om boka og tolkninger

Boka var ikke tilgjengelig under arbeidet. Talleksempler er bare tatt med der formelen gjenskaper dem med fire desimaler. Ellers bygger kontrollen på Monte Carlo, trær, numerisk integrasjon og identiteter.

**Mulige trykkfeil.** I disse tilfellene stemmer kalkulatoren med formelen, inn + ut-paritet og Monte Carlo, men ikke med tallet slik det ble husket fra boka:

- Binære barriereopsjoner, tabellen med 28 typer (X = 102): type 14 gir 5,8926 og type 20 gir 33,1723.
- Fade-in-put skal ha +ρ i den bivariate normalfordelingen, og capped power-put skal ha (X − C).

**Tolkninger.**

- *Eksempelet 21,1965* er put på call. Formelen gir 21,19635.
- *BAW-tabellen* ser ut til å være regnet med en Newton-iterasjon som stopper tidlig. Kalkulatoren løser likningen helt, og verdiene stemmer innen 5e-4, bortsett fra to celler like under kritisk pris.
- *CEV* følger Schroder: dS = bS dt + σS^{β/2} dW, der β = 2 gir Black-Scholes.
- *Hull-White (1988)* bruker en andreordens rekke med korrelasjon som er utledet og kontrollert mot betinget Monte Carlo, ikke mot bokas trykte ledd.
- *To-aktiva-barrierer:* S1 er aktivet utbetalingen beregnes på, S2 er aktivet barrieren gjelder.

**Ikke med:** volatilitetsswap, volatilitetskjegler, implisitte trinomialtrær, konvertible obligasjoner i trær, swingopsjoner og andre spread-tilnærminger enn Kirk. For spread vises i stedet eksakt pris ved numerisk integrasjon.

## Numeriske rutiner og kilder

De generelle rutinene i `src/math/` er skrevet etter originalkildene:

| Rutine | Kilde |
|---|---|
| N(x) | Hart (1968), i Wests (2005) dobbeltpresisjonsversjon |
| M(a, b; ρ) | Genz (2004) |
| N⁻¹(p) | Acklams algoritme med ett Halley-steg |
| Nullpunkter | Brent (1973), kap. 4 |
| Ufullstendig gamma | Abramowitz og Stegun 6.5.29 og 6.5.31, med Lentz' metode for kjedebrøken |
| Gauss–Legendre | Startverdier fra Tricomi (A&S 22.16.6) og Newton-iterasjon |
| ln Γ | Lanczos-tilnærmingen |

## Lisens

Koden er lisensiert under MIT-lisensen, se [LICENSE](LICENSE).

## Forbehold

Formlene er implementert på nytt fra den matematiske beskrivelsen. Prosjektet har ingen tilknytning til forfatteren eller forlaget, og bruker ingen tekst eller kode fra boka eller CD-en. Resultatene er ikke investeringsråd.
