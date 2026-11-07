# Klar – spesifikasjon (versjon 1.1)

Dette er den fullstendige beskrivelsen av språket. Den korte utgaven som lærer en modell Klar, er
[primer.en.md](primer.en.md) (engelsk, fordi det er billigst i tokens) og [primer.no.md](primer.no.md)
(samme innhold på norsk). Parseren i [`klar/parser.py`](../klar/parser.py) følger denne teksten. Der de to er
uenige, er det en feil.

Alle eksemplene i kodeblokker merket `klar` er gyldig Klar. Det sjekker `tests/test_docs.py`.

## Innhold

1. [Grunnideen](#1-grunnideen)
2. [Ord og skrift](#2-ord-og-skrift)
3. [Setningen: subjekt, markør, hovedord](#3-setningen-subjekt-markør-hovedord)
4. [Flere verb for samme subjekt](#4-flere-verb-for-samme-subjekt)
5. [Kilde og sikkerhet](#5-kilde-og-sikkerhet)
6. [Binde setninger sammen](#6-binde-setninger-sammen)
7. [Henvisninger: pronomen, etiketter og definisjoner](#7-henvisninger-pronomen-etiketter-og-definisjoner)
8. [Mengde, nektelse og rekkevidde](#8-mengde-nektelse-og-rekkevidde)
9. [Spørsmål og svar](#9-spørsmål-og-svar)
10. [Formell grammatikk](#10-formell-grammatikk)
11. [Hvorfor hver setning har én tolkning](#11-hvorfor-hver-setning-har-én-tolkning)
12. [Alle grammatikkord](#12-alle-grammatikkord)
13. [Sjekk og feilmeldinger](#13-sjekk-og-feilmeldinger)
14. [Endringer](#14-endringer)

## 1. Grunnideen

Klar er engelske ord med ny grammatikk. Innholdsordene (user, file, test, big) er de engelske, fordi en
språkmodell allerede kjenner dem, og fordi de er de billigste ordene den har: nesten alle er ett token. Det
nye er grammatikken. Den gir hver setning nøyaktig én oppbygning, og den gjør fire ting obligatoriske eller
billige som engelsk lar være vage:

- **tid** på hvert verb (`li` nå, `pa` fortid, `fu` fremtid),
- **styrken** i en instruks (`must`, `should`, `may`),
- **kilden** til en påstand (`checked`, `so`, `suppose`, `per X,`) og **hvor sikker** den er (`likely`,
  `maybe`, `unlikely`, `80%`),
- **hva som viser til hva** (etiketter som `U` og `F`, og en fast regel for `it`).

Hvert grammatikkord er ett token i alle de åtte tokenizerne som er målt (se [bench/RESULTS.md](../bench/RESULTS.md)).

## 2. Ord og skrift

| Slag | Form | Eksempel |
|---|---|---|
| Innholdsord | engelsk ord med små bokstaver, ikke et grammatikkord | `user`, `file`, `big`, `log-in` |
| Navn | stor forbokstav, minst to tegn | `Oslo`, `GitHub`, `API` |
| Etikett | én stor bokstav, A–Z unntatt I | `U`, `F`, `K` |
| Tall og mengder | sifre, enheten skrevet inntil | `3`, `2.5`, `5MB`, `30s`, `70%`, `14:30`, `2026-11-07` |
| Kode og stier | som de er, eller i backticks | `config.yaml`, `find_order()`, `src/app/main.py` |
| Sitat | i doble anførselstegn | `"hello"` |

Regler for innholdsord:

- Ingen artikler (the, a, an), ingen kopula (is, are, was, be) og ingen hjelpeverb (will, did, has). Tid og
  modalitet ligger i markøren.
- Verb står i grunnform: `go`, ikke `went`. Flertall (`tests`) og gradbøying (`bigger`, `fastest`) er lov,
  fordi de koster det samme som grunnformen og ikke kolliderer med noe i grammatikken.
- Partikkelverb skrives som ett ord med bindestrek (`log-in`, `set-up`) eller byttes med et synonym
  (`register` for «sign up»).
- «Minst» og «høyst» skrives `min` og `max`, «omtrent» skrives `approx`: `min 2 source`, `approx 20%`.

Setninger slutter med `.` (påstand eller instruks) eller `?` (spørsmål). En setning kan gå over flere linjer,
men sjekkeren advarer, fordi et glemt punktum ofte er grunnen.

Markdown rundt Klar-tekst (overskrifter, punktlister, nummererte lister) blir ignorert.

## 3. Setningen: subjekt, markør, hovedord

Grunnformen er **subjekt + markør + hovedord + objekt + tillegg**:

```klar
user pa test new login system with care.
```

### 3.1 Markøren

Hvert predikat begynner med én markør. Markøren er det eneste som skiller subjektet fra predikatet, og den
bærer tid eller modalitet:

| Markør | Betydning | Eksempel |
|---|---|---|
| `li` | nå eller alltid | `sky li blue.` |
| `pa` | fortid | `user pa test system.` |
| `fu` | fremtid | `job fu start at 14:30.` |
| `must` | påkrevd | `you must answer short.` |
| `should` | anbefalt | `should cite source.` |
| `may` | tillatt, valgfritt | `may add example.` |
| `can` | i stand til, mulig | `admin can delete file.` |
| `would` | hypotetisk | `fix would help.` |

En tidsmarkør kan stå foran en modal: `pa can` = kunne, `fu must` = vil måtte.

```klar
user pa can not open file.
```

**`li` kan sløyfes** etter et subjekt som er et pronomen (I, you, we, it) eller en etikett, når neste ord er et
adverb, `a` eller et innholdsord. Da kan ingen ord høre til subjektet, så grensen er like klar:

```klar
I recommend B. it not valid. you a support assistant.
```

Etter et vanlig substantiv trengs alltid markøren, fordi `user input fail` ellers kunne vært både
«brukeren putter inn feil» og «brukerinput feiler».

### 3.2 Uten subjekt

- **Modal uten subjekt er en instruks til leseren:** `must not use jargon.` betyr «du skal ikke bruke sjargong».
- **Tid uten subjekt er passiv; den som handlet, er ukjent:** `pa delete file.` betyr «filen ble slettet».
  Den som handlet, kan legges til med `by`: `pa delete file by admin.`

### 3.3 Hva predikatet kan være

| Etter markøren | Slag | Eksempel |
|---|---|---|
| et innholdsord (+ objekt) | verb eller adjektiv | `user li ask for help.` `sky li blue.` |
| `a` + frase | substantivfrase som predikat | `Python li a programming language.` |
| bestemmerord eller eiendomsord | substantivfrase | `it li my file.` |
| tall + innholdsord | substantivfrase | `limit li 100 request per minute.` |
| preposisjon | sted eller tilstand | `user li in Oslo.` |

`a` trengs bare når predikatet er en substantivfrase på to eller flere ord. Uten `a` ville `li big city`
bety at «big» er verbet og «city» objektet.

### 3.4 Adverb

Mellom markøren og hovedordet kan disse stå: `not never always often already still yet again only also very
too more less most`. De står alltid etter markøren, aldri foran den:

```klar
I pa not yet confirm this. file li still necessary.
```

Måten noe gjøres på, sies som en egenskap eller med en preposisjon, ikke med et adverb på -ly:

```klar
answer must short. must read file with care.
```

### 3.5 Hovedord, objekt og tillegg

- **Hovedordet** er første ord etter markøren og adverbene.
- **Objektet** er frasen rett etter hovedordet. I en frase står bestemmelser foran ordet de bestemmer:
  `new login system` er et system.
- **Tillegg** kommer etter objektet: preposisjonsfraser (se [§ 12](#12-alle-grammatikkord)), tidsordene
  `now today yesterday tomorrow soon later here there`, leddsetninger og objektsetninger.

**Hvor en preposisjonsfrase hører hjemme:**

1. Etter objektet hører den til verbet: `I pa see man with telescope.` (jeg brukte kikkerten).
2. Inne i parentes hører den til substantivet: `I pa see (man with telescope).` (mannen hadde kikkerten).
3. I subjektet hører den til subjektet: `user from Norway pa buy car.`
4. `of` hører alltid til frasen foran og binder mot høyre: `name of file of user` er navnet på
   (filen til brukeren).

To fraser kan aldri stå rett etter hverandre uten et grammatikkord mellom seg. Derfor kan ikke `delete file
yesterday` bety noe annet enn at `yesterday` er et tidsord. Andre tidsuttrykk trenger preposisjon
(`in 2024`, `at 14:30`, `on Monday`) eller må stå først (`last week, ...`).

## 4. Flere verb for samme subjekt

Hvert verb trenger sin egen markør. Det finnes tre måter å legge til flere verb for samme subjekt:

| Form | Betydning | Eksempel |
|---|---|---|
| ny markør | og | `user pa open file pa edit it.` |
| `and`/`or`/`but`/`so` + markør | og / eller / men / derfor | `user pa try but pa fail.` |
| `then` (+ eventuelt markør) | deretter, samme markør som før | `must read file then summarize it.` |

`then` uten markør gjentar forrige markør: `must read file then summarize it then save summary.` er tre krav.

Det viktigste å huske: **`and` + et ord uten markør binder sammen substantiver, ikke verb.** `must open file and
folder` er én handling med to objekter. Med `and` + substantiv + markør begynner en ny setning med nytt subjekt
(se § 6.2).

## 5. Kilde og sikkerhet

### 5.1 Kilde

Først i setningen kan ett kildeord stå:

| Kilde | Betydning |
|---|---|
| `checked` | sjekket her og nå: kjørt, lest, målt |
| `so` | utledet av det som er sagt før |
| `suppose` | antakelse; påstås ikke |
| `per X,` | ifølge X (må stå først og slutte med komma) |
| (ingenting) | sagt som kjent |

`per` midt i en setning betyr «per, for hver»: `100 request per minute`. Bare `per X,` først i setningen er en
kilde.

`suppose` er for antakelser («anta at», «la oss si»). For «jeg tror» og «sannsynligvis» brukes sikkerhet,
ikke `suppose`.

### 5.2 Sikkerhet

| Ord | Sannsynlighet |
|---|---|
| (ingenting) | sikker, minst 90 % |
| `likely` | omtrent 75 % |
| `maybe` | omtrent 50 % |
| `unlikely` | omtrent 25 % |
| `90%` | akkurat det tallet |

En prosent først i setningen er sikkerhet, men ikke når `of` følger: `80% of user pa agree.` er en mengde.

Rekkefølgen er diskursord, kilde, sikkerhet:

```klar
but checked likely cache li old.
```

I streng modus (`klar check --strict`) skal hver påstand ha en kilde. Instrukser, spørsmål og definisjoner
er unntatt. Det passer for rapporter fra agenter, der forskjellen på «kjørt og sett» og «antatt» er det
viktigste.

## 6. Binde setninger sammen

### 6.1 Bindeord mellom setninger

`and`, `or` (ett eller begge), `xor` (nøyaktig ett), `but`, `so` (derfor), `because`, `iff` (hvis og bare
hvis).

`and` binder sterkest, så `or` og `xor`, så resten. Parentes overstyrer:

```klar
file li big and user li admin or flag li set.
(file li big or user li admin) and must compress file.
```

### 6.2 `and`: tre betydninger, avgjort av ordene etter

| Etter `and` | Betyr | Eksempel |
|---|---|---|
| markør | nytt verb, samme subjekt | `user pa open file and pa close it.` |
| frase + markør | ny setning, nytt subjekt | `user pa open file and admin pa close it.` |
| frase uten markør | flere substantiver | `user pa open file and folder.` |

Det samme gjelder `or` og `xor`. I subjektet, før markøren, binder `and` alltid substantiver:
`file and folder li big.`

### 6.3 Leddsetninger

`if when unless until while before after since where` (og `because` først i setningen) innleder en
leddsetning.

- **Står den først,** slutter den med `,` eller `then`, og kan inneholde bindeord:
  `if file li big and user li admin, must compress file.`
- **Står den etter,** er den én setning, uten `and`/`or`/`but` + nytt subjekt:
  `must compress file if it li big.`

`before`, `after`, `until` og `since` er preposisjoner når de ikke følges av en setning:
`before 2024, price pa low.` mot `before test pa run, must build code.`

### 6.4 Objektsetninger

| Innledning | Eksempel |
|---|---|
| `that` | `user pa say that file li big.` |
| `whether` | `must check whether test pa pass.` |
| spørreord | `must explain why test pa fail.` `must find what user want.` |
| `which` + frase | `must check which test pa fail.` |
| `how many` + frase | `must count how many user pa register.` |

De kan også komme etter et objekt: `must tell user that build pa fail.`

### 6.5 Relativsetninger

`which` etter et substantiv innleder en relativsetning med et hull der substantivet hører hjemme:

```klar
file which user pa upload li big. user which pa log-in pa see error.
```

**En innskutt setning (relativsetning, objektsetning, leddsetning etter hovedsetningen) slutter ved neste
markør som ikke har `and`/`or`/`but`/`so` foran seg.** Derfor er `li big` hovedverbet i første eksempel.
Skal relativsetningen ha flere verb, bindes de med `and`: `user which pa log-in and pa log-out pa see error.`

### 6.6 Noe som står først

En preposisjonsfrase, en frase eller en leddsetning kan stå først i setningen og slutter da med komma:

```klar
in 2024, user pa buy car. yesterday, server pa crash.
```

**Ellers brukes ikke komma.** Det er ikke komma foran `but`, ikke komma i lister (`red and green and blue`)
og ikke komma mellom setninger.

## 7. Henvisninger: pronomen, etiketter og definisjoner

### 7.1 Pronomen

`I`, `you`, `we`, `it` og eiendomsordene `my`, `your`, `our`, `its`. Klar har ikke kasus: `to I`, ikke «to
me». `this` viser til det som nettopp ble sagt: `this li a security risk.`

### 7.2 Hva `it` viser til

`it` følger én fast regel:

1. `it` viser til **nærmeste tidligere subjekt eller objekt**.
2. Fraser inne i en which-setning eller en preposisjonsfrase teller ikke.
3. `it` er aldri subjektet eller objektet til sitt eget verb.
4. `I`, `you` og `we` teller ikke.

```klar
I pa fix bug in login form pa add 2 test for it.
user pa open file and admin pa close it.
file pa crash. it pa restart.
```

Testene er for feilen, siden `2 test` er objektet til samme verb og `login form` står i en
preposisjonsfrase. Admin lukket filen, fordi `admin` er subjektet til samme verb.

**Når regelen og engelsk vane spriker.** I `script pa delete file and it pa crash.` sier regelen at filen
krasjet, mens en engelsk leser ofte tenker på skriptet. Det skjer når `it` står som subjekt og nærmeste
kandidat er et objekt, mens et subjekt står like før. Da advarer sjekkeren:

```text
1:27: advarsel: «it» er subjekt og viser etter regelen til objektet «file», ikke til «script». Mente du subjektet, skriv det ut, bruk en etikett eller then
```

Den ryddige måten er å la `then` beholde subjektet (`script pa delete file then crash.`), gjenta ordet eller
bruke en etikett. Regelen er den samme som i versjon 1.0 og er ikke byttet ut med en «smartere» regel. En
regel som lot subjekt-`it` peke på subjektet, ville tatt feil i `user pa send report to admin. it li long.`,
der en leser mener rapporten. Ingen enkel regel treffer engelsk intuisjon hver gang. Derfor er regelen enkel,
og sjekkeren advarer der intuisjonen kan dra i en annen retning.

Glossen viser hva hver `it` peker på: `[it→file]`.

### 7.3 Etiketter

En stor bokstav rett etter en frase gir den et navn som kan brukes senere:

```klar
user U pa send file F to admin. U want copy of F.
```

Etiketter er det billigste presise henvisningsmiddelet Klar har: ett token, og aldri tvetydig. De lønner seg
når noe langt nevnes flere ganger, for eksempel stier og funksjonsnavn i kode.

### 7.4 Definisjoner og navn på påstander

```klar
C = src/payments/checkout_service.py. K = customer support ticket.
P: all bird li fly. so P li false.
```

`=` mellom to fraser er en definisjon eller en likhet (`19 times 12 = 228.`). `P:` først i en setning gir
påstanden et navn.

## 8. Mengde, nektelse og rekkevidde

- Bestemmerord foran substantiv: `all each some no any many few most more less this which`, tall,
  `how many`, `min 2`, `max 5`, `approx 20%`. `some` betyr minst én.
- **Kvantoren som står først, har størst rekkevidde:** `all student pa read some book.` betyr at hver leste en
  bok, kanskje ulike.
- **`not` gjelder det som følger:** `not all test pa pass.` (minst én feilet) mot `all test pa not pass.`
  (ingen besto).
- `only` og `not` kan stå foran en frase: `only admin may delete file.`
- `may not` betyr «har lov til å la være». Forbud skrives `must not`. Sjekkeren advarer mot `may not`, fordi
  engelsk leser det som forbud.

## 9. Spørsmål og svar

Spørsmål slutter med `?`. Spørreordet står der svaret skal stå, eller først når det er subjekt eller et
fremskutt objekt:

```klar
user pa want what? who pa delete file? meeting fu start when? which test pa fail? file li exist?
```

Svar: `yes.`, `no.` eller `=` + frase:

```klar
= F.
```

## 10. Formell grammatikk

Grammatikken nedenfor er skrevet som en PEG: alternativene prøves i rekkefølge, og det første som passer,
gjelder. Ord i anførselstegn er grammatikkord; store bokstaver er ordklasser fra § 12.

```text
tekst       = setning*
setning     = (ETIKETT ":")? (svar | fragment | definisjon | påstand) ("." | "?")
svar        = "yes" | "no"
fragment    = "=" frase
definisjon  = frase "=" frase
påstand     = åpner* fremskutt* kompleks
åpner       = DISKURS | KILDE | SIKKERHET | PROSENT       ; PROSENT ikke fulgt av "of"
fremskutt   = UNDERORDNER kompleks ("," | "then")         ; ikke "then"-kjeder inni
            | PREPOSISJON frase ","
            | frase ","
kompleks    = eller (("but" | "so" | "because" | "iff") eller)*
eller       = og (("or" | "xor") og)*
og          = enhet ("and" enhet)*                         ; bare når en setning følger
enhet       = "(" kompleks ")" | klausul
klausul     = subjekt? predikat kjede*
            | BART-SUBJEKT rest kjede*                     ; li underforstått
kjede       = predikat                                     ; ikke inne i en innskutt setning
            | ("and" | "or" | "xor" | "but" | "so") predikat
            | "and"? "then" (markør)? rest
predikat    = markør rest
markør      = TID MODAL? | MODAL
rest        = ADVERB* kjerne tillegg*
kjerne      = "a" frase | BESTEMMER frase | TALL frase | prepfrase
            | HOVEDORD komplement?
komplement  = ("that" | "whether" | SPØRREORD) klausul | ("which" | "how many") klausul | frase
tillegg     = prepfrase | UNDERORDNER klausul | ("that" | "whether" | SPØRREORD) klausul | TIDSORD
prepfrase   = PREPOSISJON frase | ("because" | "instead") "of" frase
frase       = fog (("or" | "xor") fog)*                     ; ikke or og xor i samme liste
fog         = enhetsfrase ("and" enhetsfrase)*
enhetsfrase = FOKUS? kjernefrase ETIKETT? ("of" enhetsfrase)* ("which" klausul)? prepfrase*
kjernefrase = "(" frase ")" | PRONOMEN | ETIKETT | SPØRREORD | "how" ("many" | "much") INNHOLD*
            | BESTEMMER? INNHOLD+ | BESTEMMER | TIDSORD
```

Merknader:

- `prepfrase*` på slutten av `enhetsfrase` brukes bare i subjektet, i parentes og i fraser som står først.
- I `fog` og `frase` fortsetter `and`/`or` en liste bare når ordene etter ikke er starten på en ny setning
  (frase + markør). I subjektet fortsetter de alltid.
- `BART-SUBJEKT` er et pronomen (I, you, we, it) eller en etikett alene, fulgt av et adverb, `a` eller et
  innholdsord.

## 11. Hvorfor hver setning har én tolkning

Parseren er én deterministisk prosedyre. Ved hvert valg avgjør neste ett eller to ord, eller en avgrenset
prøvelesing av neste frase, hva som kommer, og valgene prøves i fast rekkefølge (som i en PEG). Den går aldri
tilbake og velger mellom to ferdige tolkninger. Derfor har hver setning høyst én oppbygning: hvilket ord som
er verbet, hva hver frase hører til, hvor langt `not`, `all` og `or` rekker, og hva `it` og etikettene viser
til.

Engelsk lar disse tingene stå åpne. Klar avgjør dem slik:

| Tvetydighet i engelsk | Klar avgjør med |
|---|---|
| hvor en preposisjonsfrase hører til (*saw the man with the telescope*) | etter objektet til verbet, i parentes til substantivet |
| hvor langt `and`/`or` rekker (*old men and women*) | `and` før `or`; bestemmelser gjelder bare frasen sin; parentes |
| rekkevidde for kvantorer (*every student read a book*) | den som står først, har størst rekkevidde |
| rekkevidde for nektelse (*all that glitters is not gold*) | `not` gjelder det som følger |
| hva *it/they/he* viser til | den faste it-regelen, eller etiketter |
| *or* inkluderende eller ekskluderende | `or` er inkluderende, `xor` ekskluderende |
| hvor sterk en instruks er (*do X*) | `must`/`should`/`may` |
| om noe er sjekket eller antatt | `checked`/`so`/`suppose`/`per` |
| hvor sikker skriveren er (*probably*, *I think*) | `likely`/`maybe`/`unlikely`/prosent |
| hvilket ord som er verbet (*user test results*) | markøren |

**Det Klar ikke gjør:** Ordene er engelske, så ordenes betydning er like flertydig som på engelsk
(*bank*, *run*, *set*). Klar fjerner tvetydighet i **oppbygningen**, ikke i ordforrådet. Der et ord kan
misforstås, kan det defineres: `B = river bank.` Hvordan et ord etter hovedordet skal forstås (objekt eller
måte, som i `must answer short`), avgjøres også av ordene selv.

## 12. Alle grammatikkord

Tabellen er hentet fra [`klar/lexicon.py`](../klar/lexicon.py), som parseren bruker. Hvert ord er ett token i
alle åtte tokenizere.

<!-- ORDLISTE START (generert av python -m klar.doc, ikke rediger for hånd) -->

**Markører: tid**

| Ord | Betydning | Meaning |
|---|---|---|
| `li` | nå eller alltid (er / gjør) | present or timeless (is / does) |
| `pa` | fortid (var / gjorde) | past (was / did) |
| `fu` | fremtid (skal / vil) | future (will) |

**Markører: modalitet**

| Ord | Betydning | Meaning |
|---|---|---|
| `must` | må (krav) | required |
| `should` | bør (anbefalt) | recommended |
| `may` | kan (har lov, valgfritt) | allowed, optional |
| `can` | kan (er i stand til, mulig) | able, possible |
| `would` | ville (hypotetisk) | hypothetical |

**Adverb (mellom markør og hovedord)**

| Ord | Betydning | Meaning |
|---|---|---|
| `not` | ikke | negation of what follows |
| `never` | aldri | never |
| `always` | alltid | always |
| `often` | ofte | often |
| `already` | allerede | already |
| `yet` | ennå (not yet: ikke ennå) | yet (with not: not yet) |
| `still` | fortsatt | still |
| `again` | igjen | again |
| `only` | bare | only |
| `also` | også | also |
| `very` | veldig | very |
| `too` | for (altfor) | too (excessively) |
| `more` | mer | more (comparative) |
| `less` | mindre | less |
| `most` | mest | most (superlative) |

**Substantivfrase som predikat**

| Ord | Betydning | Meaning |
|---|---|---|
| `a` | er en (substantivfrase) | is a kind of (predicate noun phrase) |

**Kilde (først i setningen)**

| Ord | Betydning | Meaning |
|---|---|---|
| `checked` | sjekket selv her (kjørt, lest, målt) | verified directly here (ran, read, measured) |
| `so` | utledet av det som er sagt (altså) | inferred from what was said (therefore) |
| `suppose` | antakelse, ikke påstand | assumption, not claimed as true |

**Sikkerhet (først i setningen)**

| Ord | Betydning | Meaning |
|---|---|---|
| `likely` | sannsynlig (ca. 75 %) | likely (about 75%) |
| `maybe` | kanskje (ca. 50 %) | maybe (about 50%) |
| `unlikely` | usannsynlig (ca. 25 %) | unlikely (about 25%) |

**Diskursord (først i setningen)**

| Ord | Betydning | Meaning |
|---|---|---|
| `but` | men | contrast with the previous sentence |
| `also` | dessuten | addition to the previous sentence |
| `then` | deretter | next in time |

**Bindeord mellom setninger**

| Ord | Betydning | Meaning |
|---|---|---|
| `and` | og | and |
| `or` | eller (ett eller begge) | inclusive or (one or both) |
| `xor` | enten eller (nøyaktig ett) | exclusive or (exactly one) |
| `but` | men | but |
| `so` | så, derfor | therefore |
| `because` | fordi | because |
| `iff` | hvis og bare hvis | if and only if |

**Underordnere (leddsetninger)**

| Ord | Betydning | Meaning |
|---|---|---|
| `if` | hvis | if |
| `when` | når | when |
| `unless` | med mindre | unless |
| `until` | til, inntil | until |
| `while` | mens | while |
| `before` | før | before |
| `after` | etter at | after |
| `since` | siden (tid) | since (time) |
| `where` | der, hvor | where (place) |

**Objektsetninger**

| Ord | Betydning | Meaning |
|---|---|---|
| `that` | at | introduces a clause as object: say that ... |
| `whether` | om | introduces a yes/no question as object |

**Relativsetninger**

| Ord | Betydning | Meaning |
|---|---|---|
| `which` | som | after a noun: which/who/that (relative clause) |

**Spørreord**

| Ord | Betydning | Meaning |
|---|---|---|
| `what` | hva | what |
| `who` | hvem | who |
| `where` | hvor | where |
| `when` | når | when |
| `why` | hvorfor | why |
| `how` | hvordan | how |
| `which` | hvilken | which (before a noun) |

**Pronomen**

| Ord | Betydning | Meaning |
|---|---|---|
| `I` | jeg / meg | speaker (also object: to I) |
| `you` | du / deg | addressee |
| `we` | vi / oss | speaker and others |
| `it` | den / det / han / hun (nærmeste subjekt eller objekt) | the nearest earlier subject or object |

**Eiendomsord**

| Ord | Betydning | Meaning |
|---|---|---|
| `my` | min | my |
| `your` | din | your |
| `our` | vår | our |
| `its` | dens / dets | its |

**Bestemmerord og kvantorer**

| Ord | Betydning | Meaning |
|---|---|---|
| `all` | alle | all |
| `each` | hver | each |
| `some` | minst én, noen | at least one |
| `no` | ingen | none |
| `any` | hvilken som helst | any |
| `many` | mange | many |
| `few` | få | few |
| `most` | de fleste | most |
| `more` | flere | more |
| `less` | mindre | less |
| `this` | denne, dette | this (the one just mentioned) |
| `which` | hvilken (spørsmål) | which (question) |

**Preposisjoner**

| Ord | Betydning | Meaning |
|---|---|---|
| `of` | av, til | of (binds inside the noun phrase) |
| `in` | i | in |
| `on` | på | on |
| `at` | ved, på | at |
| `to` | til, for å | to (goal, receiver, purpose) |
| `from` | fra | from |
| `with` | med | with |
| `without` | uten | without |
| `by` | av, ved hjelp av | by (agent, means) |
| `for` | for | for |
| `about` | om | about (topic) |
| `per` | per; først i setningen med komma: ifølge (kilde) | per, for each; first in the sentence with comma: according to (source) |
| `via` | via | via |
| `than` | enn | than (comparison) |
| `as` | som (i rollen som) | as (in the role of) |
| `into` | inn i | into |
| `over` | over | over |
| `under` | under | under |
| `between` | mellom | between |
| `during` | under, i løpet av | during |
| `since` | siden | since (time) |
| `before` | før | before |
| `after` | etter | after |
| `until` | til | until |
| `against` | mot | against |
| `through` | gjennom | through |
| `within` | innen | within |
| `despite` | til tross for | despite |
| `except` | unntatt | except |
| `around` | rundt | around (place) |
| `instead` | i stedet for | instead of |
| `because` | på grunn av | because of (only as: because of) |

**Tids- og stedsord**

| Ord | Betydning | Meaning |
|---|---|---|
| `now` | nå | now |
| `today` | i dag | today |
| `yesterday` | i går | yesterday |
| `tomorrow` | i morgen | tomorrow |
| `soon` | snart | soon |
| `later` | senere | later |
| `here` | her | here |
| `there` | der | there |

**Svar**

| Ord | Betydning | Meaning |
|---|---|---|
| `yes` | ja | yes |
| `no` | nei | no |

**Tegn**

| Tegn | Betydning | Meaning |
|---|---|---|
| `.` | slutt på påstand eller instruks | end of statement or instruction |
| `?` | slutt på spørsmål | end of question |
| `,` | avslutter noe som står først: if ..., / in 2024, | ends a fronted part: if ..., / in 2024, |
| `:` | etter navnet på en påstand: P: ... | after a claim label: P: ... |
| `=` | definisjon eller svar: K = ... / = F | definition or answer: K = ... / = F |
| `(` | start på gruppe | start of a group |
| `)` | slutt på gruppe | end of a group |

Etiketter: én stor bokstav, A B C D E F G H J K L M N O P Q R S T U V W X Y Z.

<!-- ORDLISTE SLUTT -->

## 13. Sjekk og feilmeldinger

`python -m klar check FIL` sjekker en tekst. Feil (ugyldig Klar) og advarsler (gyldig, men sannsynligvis ikke
ment) kommer med linje og kolonne, og feilene har tips når de skyldes vanlige engelske vaner:

```text
1:5: feil: ventet et subjekt eller en markør (li, pa, fu, must ...), fant «the». Tips: «the»: Klar har ingen artikler: stryk «the».
2:32: feil: komma brukes bare etter noe som står først (if ..., / in 2024,); skriv «but»/«and» uten komma, eller avslutt setningen med punktum
```

Advarsler:

- `may not` (se § 8)
- en etikett som brukes før den er knyttet til noe, eller som knyttes to ganger
- `it` uten noe å vise til
- en setning som går over flere linjer (glemt punktum?)
- i streng modus: en påstand uten kilde

`python -m klar gloss FIL` viser oppbygningen, og `python -m klar json FIL` gir et syntakstre og de
grammatiske trekkene som JSON.

## 14. Endringer

**1.1** (etter læringstesten, se [eval/README.md](../eval/README.md)):

- Primeren sier rett ut at `suppose` ikke betyr «jeg tror», at adverb står etter markøren, og at komma bare
  brukes etter noe som står først. Dette var de vanligste feilene i runde 1. I runde 2, med nye setninger,
  var alle 48 svarene gyldig Klar.
- Sjekkeren gir egne tips for adverb foran markøren og komma midt i setningen, og advarer når `it` som
  subjekt viser til et objekt mens et subjekt står like før (se § 7.2).
- Objektsetninger kan stå etter et objekt: `must ask user whether file li ready.`
- Kode, stier og identifikatorer kan skrives uten backticks (`config.yaml`, `find_order()`).
- `li` kan sløyfes etter et pronomen eller en etikett.
- Flertall og gradbøying av innholdsord er lov.

**1.0**: første versjon.
