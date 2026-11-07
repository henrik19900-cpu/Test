# Begrunnelse: hvorfor Klar ser ut som det gjør

Oppdraget var å lage et nytt språk tilpasset AI som er mer effektivt enn engelsk. Dette dokumentet forklarer
hva «effektivt» kan bety for en språkmodell, hva målingene viste, og hvorfor hvert valg i Klar ble som det
ble. Tallene kommer fra [bench/RESULTS.md](../bench/RESULTS.md) og [eval/RESULTS.md](../eval/RESULTS.md).

## Innhold

1. [Hva «effektivt» betyr for en AI](#1-hva-effektivt-betyr-for-en-ai)
2. [Tre funn som styrte designet](#2-tre-funn-som-styrte-designet)
3. [Hva Klar gir for prisen](#3-hva-klar-gir-for-prisen)
4. [Valgene, ett for ett](#4-valgene-ett-for-ett)
5. [Forsøk som ble forkastet](#5-forsøk-som-ble-forkastet)
6. [Forbilder og beslektet arbeid](#6-forbilder-og-beslektet-arbeid)
7. [Hvorfor ikke et språk bare maskiner forstår?](#7-hvorfor-ikke-et-språk-bare-maskiner-forstår)
8. [Når Klar lønner seg, og når ikke](#8-når-klar-lønner-seg-og-når-ikke)
9. [Begrensninger](#9-begrensninger)
10. [Videre arbeid](#10-videre-arbeid)

## 1. Hva «effektivt» betyr for en AI

En språkmodell leser og skriver **tokens**, biter av ord fra en fast ordliste (tokenizeren). Alt den gjør,
koster per token: pris, ventetid og plass i kontekstvinduet. Output-tokens koster mer enn input-tokens og
lages ett og ett. Effektivitet har likevel fem sider, ikke én:

| Side | Spørsmål |
|---|---|
| **Kostnad** | Hvor mange tokens trengs for samme innhold? |
| **Presisjon** | Kan teksten bare forstås på én måte? Misforståelser koster nye runder, og de koster mer enn tokens. |
| **Maskinlesbarhet** | Kan et program hente ut hvem, hva, når, hvor sikkert og hvorfra, uten en ny modell? |
| **Lærbarhet** | Hvor mye må modellen lære før den kan bruke språket, og hvor ofte gjør den feil? |
| **Innsyn** | Kan et menneske lese det modellene sier til hverandre? |

Et språk som bare minimerer tokens, ofrer de andre fire. Klar prøver å vinne på presisjon, maskinlesbarhet og
innsyn uten å tape på kostnad eller lærbarhet.

## 2. Tre funn som styrte designet

### Funn 1: Engelske ord er det billigste modellen har

Tokenizerne er bygd på tekst som for det meste er engelsk. Nesten alle vanlige engelske ord er ett token
med mellomrom foran, også bøyde former (`tested`, `children`, `bigger`). Norsk koster mer: det samme
innholdet var i snitt **39 % dyrere på norsk enn på engelsk** i korpuset, og enkeltord som
`sannsynligvis` koster 4–5 tokens mot 1 for `probably`. Forskning viser det samme mønsteret i stor skala:
samme tekst kan bli opptil 15 ganger så mange tokens på noen språk som på engelsk ([Petrov mfl., NeurIPS
2023](https://proceedings.neurips.cc/paper_files/paper/2023/hash/74bb24dca8334adce292883b4b651eda-Abstract.html)).

Modellen «tenker» likevel ikke bare på engelsk. Anthropics tolkningsforskning fant at Claude bruker felles
begreper på tvers av språk, og at andelen delte trekk øker med modellstørrelsen
([Tracing the thoughts of a large language model, 2025](https://www.anthropic.com/research/tracing-thoughts-language-model)).
Engelsk er altså ikke nødvendigvis språket modellen tenker på, men det er språket den er **billigst å snakke** på.

### Funn 2: Nye ord og symboler koster mer, ikke mindre

To populære ideer for «AI-språk» er nye, korte ord (som i esperanto eller toki pona) og logiske symboler.
Begge ble målt:

- **Oppdiktede ord:** Når hvert engelsk innholdsord i Klar-tekstene byttes med et oppdiktet ord, blir
  tekstene **27–41 % dyrere**, avhengig av tokenizer. Modellen måtte i tillegg lære hva ordene betyr.
- **Symboler:** `∀` koster 1,5 tokens i snitt, `⊕` og `⇔` 2,25, emoji opptil 3. De engelske ordene `all`,
  `xor` og `iff` koster 1.

Derfor låner Klar ordforrådet fra engelsk og bruker bare vanlige ASCII-ord til grammatikken. Alle 130
grammatikkordene og etikettene er målt til nøyaktig ett token i alle åtte tokenizerne.

### Funn 3: Bøying er gratis, entydighet koster omtrent ett token per verb

Det overrasket mest. Første versjon av Klar var bare **5 % kortere enn engelsk** og **20 % lengre enn
telegramengelsk** (engelsk uten artikler og hjelpeverb). Grunnen er at tid i engelsk ofte ligger
i bøyingen (`tested`), og den er gratis fordi `tested` er ett token. Klar setter tid i et eget ord (`pa`).
Det koster ett token, og artiklene som forsvinner, sparer omtrent like mye.

Markøren er likevel det som gjør Klar entydig. Uten den kan ingen avgjøre om `user test results` betyr at
brukeren tester resultatene, eller at noe er brukerens testresultater. Telegramengelsk er kort fordi den lar
leseren gjette. Etter tre runder med forbedringer, alle målt, endte Klar på:

| | Tokens (snitt over 8 tokenizere, hele korpuset) |
|---|---:|
| Norsk | 1532 |
| Engelsk | 1103 |
| **Klar** | **1035** (−6 % mot engelsk, −32 % mot norsk) |
| Telegramengelsk | 876 (men tvetydig, og uten tid, kilde og styrke) |

**Konklusjonen er ærlig:** Klar er ikke et kompresjonsformat. Det er et presisjonsformat som også er litt
kortere enn engelsk og mye kortere enn norsk. Den store gevinsten i tokens kommer der engelsk bruker mange ord
på det Klar sier med ett: usikkerhet (`I'm not sure, but I think ...` blir `maybe ...`, −53 % for den setningen), kilder og instrukser.

## 3. Hva Klar gir for prisen

| Egenskap | Engelsk | Telegramengelsk | Klar |
|---|---|---|---|
| Én tolkning av oppbygningen | nei | nei | **ja**, sjekket av parseren |
| Tid på hvert verb | som regel | ofte borte | **alltid** |
| Hvor sterk en instruks er | vagt | vagt | `must` / `should` / `may` |
| Hvor en påstand kommer fra | sjelden, og dyrt | nei | `checked` / `so` / `suppose` / `per X,` |
| Hvor sikker skriveren er | vagt og dyrt | `probably` | `likely` / `maybe` / `unlikely` / `90%` |
| Henvisninger | `it`, `they`, «den første filen» | gjetting | etiketter (`F`) og fast `it`-regel |
| Kan leses av et program | nei | nei | **ja**: syntakstre og trekk som JSON |
| Kan sjekkes automatisk | nei | nei | **ja**: `klar check` |
| Kan leses av et menneske | ja | ja | ja, etter noen minutter med primeren |

## 4. Valgene, ett for ett

**Engelske innholdsord.** De er billigst og har betydning for modellen fra før (funn 1 og 2).

**Ingen artikler, ingen kopula.** `the`, `a` og `is` sto for en stor del av tokenene uten å bære mye
informasjon. Bestemthet kommer fram av sammenhengen, og der den ikke gjør det, finnes `this` og etiketter.

**Markørene `li`, `pa`, `fu`.** Klar trengte et ord som markerer predikatet uansett ordklasse, fordi engelske
ord kan være både verb og substantiv (`test`, `run`, `file`). Engelske hjelpeverb passer ikke: `is` foran et
verb leses som «er en», og `did` foran et adjektiv blir rart. Nye, korte ord som ikke betyr noe annet på
engelsk, gir ingen falske assosiasjoner. `li` er lånt fra toki pona, der det har nøyaktig denne jobben.

**Modale markører fra engelsk.** `must`, `should` og `may` betyr det samme som i engelsk og i RFC 2119
(standarden for krav i internettstandarder). Her er engelsk presist nok, så Klar låner direkte.

**`li` kan sløyfes etter pronomen og etiketter.** Et pronomen eller en etikett kan aldri være del av en lengre
frase, så grensen mellom subjekt og predikat er klar uten markør. Etter vanlige substantiver er det ikke trygt,
fordi `error message appear` kunne vært både «feil-melding vises» og «feil gir melding». Derfor gjelder regelen
bare for pronomen og etiketter.

**`a` foran en substantivfrase som predikat.** Uten `a` ville `li big city` bety at «big» er verbet. Det
trengs bare for fraser på to eller flere ord, og leses naturlig som engelsk «is a».

**Preposisjoner hører til verbet, parentes knytter dem til substantivet.** I engelsk tekst er det omtrent
like vanlig at en preposisjonsfrase hører til verbet som til substantivet foran, bortsett fra `of`, som nesten
alltid hører til substantivet. Klar gjør `of` til en del av frasen og lar resten høre til verbet. Parentes
(to tokens) brukes når det skal være annerledes, og en modell skjønner straks at parentes betyr gruppering.

**Kilde og sikkerhet først i setningen.** Mange språk har grammatisk evidensialitet, det vil si at man må si
om noe er sett, hørt eller utledet (for eksempel quechua og tyrkisk). For en AI er nettopp det skillet viktig:
har agenten kjørt testene, eller tror den bare at de passerer? Skalaen for sikkerhet (`likely` ≈75 %,
`maybe` ≈50 %, `unlikely` ≈25 %) er en grovere utgave av skalaen amerikansk etterretning bruker i ICD 203,
der «likely» dekker 55–80 %. Ordene står først i setningen fordi det er der en leser, og en modell som
skriver ord for ord, trenger dem.

**`per X,` bare først i setningen.** `per` betyr «per, for hver» i teknisk engelsk (`100 request per
minute`), og den betydningen er vanligst. Bare når `per` står først og slutter med komma, betyr det
«ifølge».

**Etiketter.** Én stor bokstav er ett token og kan aldri misforstås, akkurat som en variabel i matematikk.
Etiketter erstatter pronomen der det kunne vært flere kandidater, og lange navn som nevnes flere ganger.

**Fast regel for `it`.** Engelsk bruker kjønn, levende/ikke-levende og sunn fornuft for å avgjøre hva
pronomen viser til. Klar har én fast regel og en advarsel der regelen og engelsk vane kan sprike (se
[spesifikasjonen, § 7.2](spesifikasjon.md#72-hva-it-viser-til)).

**Komma bare etter noe som står først.** Komma i engelsk har mange jobber. I Klar har det én, og da kan
parseren alltid vite hvor en leddsetning som står først, slutter.

**Ingen nye tegn.** Alle grammatikkord er vanlige små ASCII-ord, fordi de er ett token. `[`, `{`, `;` og `!`
er ikke med i språket.

## 5. Forsøk som ble forkastet

Hvert forslag ble målt før det ble tatt inn eller forkastet.

| Forslag | Hvorfor forkastet |
|---|---|
| Oppdiktet ordforråd | 27–41 % flere tokens, og modellen må lære ordene (funn 2) |
| Logiske symboler og emoji | 1,4–2,3 tokens per symbol mot 1 per ord (funn 2) |
| Instrukser uten `must` (bare verbet) | Sparer ett token, men gjør `and` + verb til en felle: `open file and close it` ville blitt lest som to substantiver, og engelsk binder nettopp verb med «and» |
| Sløyfe `li` etter alle ett-ords-subjekter | Sammensatte ord (`user input`) ville blitt lest feil uten at noen merket det |
| Store forbokstaver som verbmarkør | Kostet ekstra tokens for sjeldne ord, og kolliderer med navn |
| `it` som subjekt peker på forrige subjekt | Retter `script pa delete file and it pa crash`, men ødelegger `user pa send report to admin. it li long` |
| Backticks rundt all kode | 2 tokens per sti; filstier og funksjonsnavn kjennes nå igjen uten |

## 6. Forbilder og beslektet arbeid

- **Lojban** (logisk språk): entydig grammatikk, men et eget ordforråd og mange regler. Klar låner ideen om
  entydighet, men ikke ordforrådet.
- **Toki pona**: et lite språk med få regler. Klar låner `li` som predikatmarkør.
- **Ithkuil**: ekstremt kompakt, men nesten umulig å lære. En påminnelse om at korthet ikke er alt.
- **Attempto Controlled English** og andre kontrollerte språk: engelsk med faste regler, oversatt til logikk.
  Klar er beslektet, men har egne grammatikkord og bygger inn kilde og sikkerhet.
- **RFC 2119**: `MUST`, `SHOULD` og `MAY` i internettstandarder. Klar bruker samme tre nivåer.
- **Modeller som lærer språk fra en grammatikk:** MTOB-testen viste at store modeller kan lære å oversette
  et nesten udokumentert språk (kalamang) fra én grammatikkbok i konteksten, men under menneskelig nivå
  ([Tanzer mfl., 2023](https://arxiv.org/abs/2309.16575)). Klar er laget for å være mye lettere enn
  kalamang. Læringstesten viser at primeren på rundt 1 700 tokens holder.
- **Kortere resonnering:** «Chain of Draft» lot modeller resonnere i korte utkast og brukte ned mot 7,6 %
  av tokenene, med like god eller bedre presisjon på flere oppgaver
  ([Xu mfl., 2025](https://arxiv.org/abs/2502.18600)). Det viser at mye av lengden i vanlig resonnering kan
  kuttes. Klar gjør noe av det samme, men med fast grammatikk.
- **Resonnering uten ord:** «Coconut» lar modellen resonnere i sine egne vektorer i stedet for i tokens
  ([Hao mfl., 2024](https://arxiv.org/abs/2412.06769)). Se neste avsnitt.

## 7. Hvorfor ikke et språk bare maskiner forstår?

Det mest effektive «språket» for en modell er dens egne interne vektorer. Forskning som Coconut viser at
modeller kan resonnere der, med færre steg. Slik kommunikasjon kan ingen mennesker lese.

Klar tar et bevisst valg den andre veien: **alt som sies i Klar, kan leses av et menneske etter noen
minutter med primeren, og oversettes mekanisk med `klar gloss`.** Når AI-agenter snakker sammen, gjør
mer av arbeidet og sender instrukser til hverandre, er innsyn ikke en luksus. Det er det som gjør at
mennesker kan følge med på hva som skjer. Et språk som sparer tokens ved å gjøre samtalen ugjennomsiktig,
er ikke mer effektivt i noen meningsfull forstand.

## 8. Når Klar lønner seg, og når ikke

Primeren koster omtrent 1 700 tokens. Den lønner seg når besparelsen over en samtale er større:

| Situasjon | Lønner seg etter omtrent |
|---|---|
| mot engelsk, uten caching | 28 000 tokens med tekst |
| mot engelsk, primeren cachet | 2 800 tokens |
| mot norsk, uten caching | 5 300 tokens |
| mot norsk, primeren cachet | 530 tokens |

Klar passer godt for:

- **rapporter og logger fra agenter**, der skillet mellom sjekket, utledet og antatt er det viktigste, og der
  `klar check --strict` kan kreve en kilde for hver påstand;
- **meldinger mellom agenter**, der begge sider har primeren og presisjon er viktigere enn stil;
- **langtidsminne**: notater som lagres kompakt og kan søkes i som JSON (alle `checked`-påstander, alle
  `must`-krav);
- **systemprompter som brukes mange ganger**, der primeren caches;
- **norske brukere og andre ikke-engelske språk**, der besparelsen er tre–fem ganger større.

Klar passer dårlig for:

- svar til mennesker som ikke kan Klar (bruk vanlig språk, eller la modellen oversette);
- korte enkeltspørsmål (primeren lønner seg ikke);
- tekst der stil og nyanser er poenget.

## 9. Begrensninger

- **Ordene er like flertydige som på engelsk.** Klar fjerner tvetydighet i oppbygningen, ikke i ordforrådet
  (*bank*, *run*). Definisjoner (`B = river bank.`) hjelper der det trengs.
- **Korpuset er skrevet av den som laget språket.** Engelsk og norsk er skrevet så konsist som en dyktig
  skribent ville gjort, og telegramengelsk er med som en hard motstander, men korpuset er lite (45 tekster).
  Det ligger åpent for at andre kan utvide det.
- **Dagens Claude-tokenizer er ikke offentlig.** «Claude (eldre, offentlig)» er tokenizeren Anthropic
  publiserte for tidligere Claude-modeller. Resultatene var like på tvers av alle åtte tokenizerne, men
  tallene for dagens Claude kan avvike litt.
- **Læringstesten er liten og bruker én modellfamilie** (se [eval/README.md](../eval/README.md)).
- **Modellene er ikke trent på Klar.** Lange tekster kan gli tilbake mot engelsk. Sjekkeren er laget for å
  fange det i en løkke: skriv, sjekk, rett.
- **Manér og noen tidsuttrykk er klønete.** Klar har ikke adverb på -ly og krever preposisjon foran de fleste
  tidsuttrykk (`in last week`).

## 10. Videre arbeid

- **Finjustere en liten modell på Klar**, slik at primeren ikke trengs og lengden faller ytterligere.
- **Klar som utdataformat** for agenter, med `klar check` som validering, for eksempel som et verktøy i MCP.
- **Måle resonnering:** gir resonnering skrevet i Klar like riktige svar som på engelsk, med færre tokens?
- **Flere språk:** Klar-grammatikk med norske innholdsord ville vært lettere for norske lesere, men målingene
  viser at det ville kostet mer. Med en tokenizer trent på norsk kunne det sett annerledes ut.
- **Teste andre modellfamilier** med samme prompt (`eval/round2/prompt.txt`).
