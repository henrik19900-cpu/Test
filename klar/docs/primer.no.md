# Klar v1 — grammatikk for modeller

Klar er et skriftspråk for meldinger mellom og til AI: engelske grunnord, en liten og presis grammatikk, én betydning per setning. Hvert grammatikkord nedenfor er ett token.

## Ord
- Innholdsord: engelske ord uten «the/a/an» og uten «is/are/was/will/did». Verb i grunnform (go, ikke went). Flertall og gradbøying er lov (tests, bigger).
- Navn: stor forbokstav (Oslo, GitHub). Tall: sifre, med enheten inntil (5MB, 30s, 70%, 14:30). Kode og stier som de er (config.yaml, find_order()) eller i `backticks`. Sitater: "tekst".
- Én stor bokstav (A–Z unntatt I) er en etikett (se Henvisninger).
- Partikkelverb skrives som ett ord: log-in, set-up, eller et synonym (register).

## Setning = subjekt + markør + hovedord + objekt + tillegg
Hvert verb, adjektiv eller substantiv som brukes som predikat, får én markør foran seg:

| tid | li nå/alltid · pa fortid · fu fremtid |
|---|---|
| modal | must påkrevd · should anbefalt · may tillatt · can i stand til/mulig · would hypotetisk |

Tid kan stå foran modal: `pa can` = kunne.
- `user pa test system.` = Brukeren testet systemet.
- `sky li blue.` `user li in Oslo.`
- `Python li a programming language.` — `a` markerer en substantivfrase på to eller flere ord som predikat.
- Etter pronomenene I, you, we, it eller en etikett kan `li` sløyfes: `it valid.` `I recommend B.`
- Uten subjekt + modal = instruks til leseren: `must answer short.` `must not use jargon.`
- Uten subjekt + tid = ukjent handlende (passiv): `pa delete file.` = Filen ble slettet.
- Mellom markør og hovedord: not never always often already still yet again only also very too more less most. `pa not yet test login.`
- Hovedordet er første ord etter markøren; frasen etter er objektet. Bestemmelser står foran substantivet sitt: `new login system`.
- Tillegg etter objektet: preposisjonene of in on at to from with without by for about per via than as into over under between during since before after until against through within despite except around, `because of`, `instead of`; og ordene now today yesterday tomorrow soon later here there.
- En preposisjon etter objektet hører til verbet. For å knytte den til substantivet, grupper med ( ): `I pa see (man with telescope).`
- Hvert verb trenger sin egen markør. Samme subjekt, flere verb: `user pa open file pa edit it.` / `user pa open file and pa edit it.` / `then` gjentar forrige markør: `must read file then summarize it then save summary.`
- Måte: si det som en egenskap eller med en preposisjon: `answer must short.` `must read file with care.`

## Kilde og sikkerhet (først i setningen)
- Kilde: `checked` = sjekket her (kjørt, lest, målt) · `so` = utledet av det som er sagt · `suppose` = antakelse, ikke påstand · `per X,` = ifølge X (bare først i setningen; ellers betyr per «for hver»: 100 request per minute). Uten kildeord: sagt som kjent.
- Sikkerhet: `likely` ≈75 % · `maybe` ≈50 % · `unlikely` ≈25 % · eller en prosent `90%`. Uten: sikker (≥90 %). `80% of user` er en mengde, ikke sikkerhet.
- Rekkefølge: kilde, sikkerhet, resten. `checked test li pass.` `so likely cache li old.` `maybe pa deprecate API in version 3.`
- «Jeg tror», «sannsynligvis», «ser ut til»: bruk `likely` eller `maybe`. `suppose` er bare for en antakelse du ikke påstår (anta, la oss si).

## Binde sammen
- Setninger: and · or (inkluderende) · xor (nøyaktig én) · but · so (derfor) · because · iff. `and` binder sterkere enn `or`/`xor`, som binder sterkere enn resten; grupper med ( ).
- `and`/`or`/`but`/`so` + markør fortsetter med samme subjekt; `and` + substantiv + markør starter en ny setning; `and` + substantiv alene binder sammen substantiver.
- Leddsetninger: if when unless until while before after since where (og `because` først). Står den først, avsluttes den med `,` eller `then`: `if file li big, must compress it.` Etter hovedsetningen: `must compress file if it li big.`
- Objektsetninger: `user pa say that file li big.` `must check whether test pa pass.` `must explain why test pa fail.` `must check which test pa fail.` Også etter et objekt: `must tell user that build pa fail.`
- Relativsetning: substantiv + which + setning med et hull: `file which user pa upload li big.` `user which pa log-in pa see error.` En innskutt setning slutter ved neste markør som ikke har and/or/but/so foran seg; grupper lengre med ( ).
- Det som settes først, avsluttes med komma: `in 2024, user pa buy car.` `yesterday, server pa crash.`

## Henvisninger
- Pronomen I, you, we, it (ingen objektformer: `to I`); eiendomsord my, your, our, its; `this` = det som nettopp ble sagt.
- `it` = nærmeste tidligere subjekt eller objekt, ikke inne i en which-setning eller preposisjonsfrase, og aldri subjektet eller objektet til sitt eget verb: `I pa fix bug pa add test for it.` (it = bug). For å beholde subjektet, bruk `then` eller gjenta ordet: `script pa delete file then crash.`
- Etikett: en stor bokstav etter et substantiv gir det navn: `user U pa send file F to admin. U want copy of F.`
- Definisjon: `K = customer support ticket.` Navn på påstand: `P: all bird li fly. so P li false.`

## Mengde og rekkevidde
- Foran substantiv: all each some (minst én) no any many few most more less this which, tall, `how many`, `min 2`, `max 5`, `approx 20%`.
- Kvantoren som står først, har størst rekkevidde: `all student pa read some book.` = hver leste en bok, kanskje ulike.
- `not` gjelder det som følger. `only`/`not` kan stå foran et substantiv: `only admin may delete file.`
- `may not` betyr «har lov til å la være»; skriv `must not` for forbud.

## Spørsmål og svar
- Slutt med `?`. Spørreordet står der svaret skal stå: `user pa want what?` `who pa delete file?` `meeting fu start when?` `which test pa fail?` `file li exist?`
- Svar: `yes.` `no.` `= F.` (= + frase).

## Eksempel
Norsk: Jeg kjørte testene: 41 besto og 1 feilet. Feilen skyldes sannsynligvis en gammel hurtigbuffer, så du bør tømme den.
Klar: `checked 41 test pa pass and 1 pa fail. likely old cache li cause of failure. so you should clear cache.`

## Feil å unngå
Ingen the/an/is/are/was/will/did/he/she/they. Aldri to markører etter hverandre (unntatt tid + modal). «and» + verb uten markør binder sammen substantiver, ikke verb: skriv `and pa`/`and must` eller `then`. Adverb står etter markøren: `file li still necessary.`, ikke «file still li». Komma avslutter bare noe som står først; aldri komma foran but/and/so. Setninger slutter med `.` eller `?`.
