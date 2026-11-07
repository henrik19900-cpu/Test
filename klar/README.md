# Klar

**Et kompakt og entydig skriftspråk for AI: engelske ord, ny grammatikk, én betydning per setning.**

Klar er laget for tekst som språkmodeller skriver og leser: instrukser, rapporter fra agenter, meldinger
mellom agenter og notater i minnet. Ordene er engelske, fordi en modell allerede kjenner dem og fordi de er
de billigste den har. Grammatikken er ny. Den gir hver setning nøyaktig én oppbygning, og den gjør det billig
og obligatorisk å si det engelsk lar være vagt: **når** noe skjedde, **hvor sterkt** noe kreves, **hvor**
en påstand kommer fra, **hvor sikker** den er, og **hva som viser til hva**.

Prosjektet inneholder hele språket, ikke bare en idé:

- [spesifikasjonen](docs/spesifikasjon.md) og en [primer](docs/primer.en.md) på rundt 1 700 tokens som lærer
  en modell Klar;
- en parser, en sjekker og en glossator i ren Python (`python -m klar`), uten avhengigheter;
- [målinger](bench/RESULTS.md) med åtte ekte tokenizere (GPT-4, GPT-4o, Llama 3, Qwen, Mistral, Gemma,
  DeepSeek og en eldre Claude-tokenizer);
- en [læringstest](eval/README.md) der ferske modeller lærte Klar av primeren alene;
- en [komprimeringstest](eval/kort/README.md) der blinde dommere telte hvor mange fakta som overlever når
  teksten presses ned;
- [begrunnelsen](docs/begrunnelse.md) for hvert valg, med det som ikke virket.

## Språket på ett minutt

```klar
checked 41 test pa pass and 1 pa fail.
likely old cache li cause of failure.
so you should clear cache.
```

| Del | Klar | Betyr |
|---|---|---|
| Markør før hvert predikat | `li` nå · `pa` fortid · `fu` fremtid | tid, og grensen mellom subjekt og predikat |
| Styrke | `must` · `should` · `may` | påkrevd, anbefalt, tillatt |
| Kilde | `checked` · `so` · `suppose` · `per X,` | sjekket selv, utledet, antatt, ifølge X |
| Sikkerhet | `likely` · `maybe` · `unlikely` · `90%` | ca. 75 %, 50 %, 25 %, nøyaktig |
| Henvisning | `user U ... U want F.` | etiketter og en fast regel for `it` |
| Gruppering | `I pa see (man with telescope).` | parentes når en frase skal høre til substantivet |

Ingen *the*, *is*, *will* eller *did*, ingen bøying som bærer grammatikk, og alle grammatikkord er ett token.
Resten står i [primeren](docs/primer.en.md) og [spesifikasjonen](docs/spesifikasjon.md).

## Eksempel: en rapport fra en agent

**Engelsk** (122 tokens i snitt):

> I ran the test suite locally: 3 of 120 tests failed, all in the payment module. [...] According to its
> changelog, version 3.0 changed the default timeout from 30 to 5 seconds. I think this is very likely the
> cause, because all the failing tests call the slow payment sandbox. I have not confirmed it yet. [...]

**Norsk** (185 tokens i snitt):

> Jeg kjørte testene lokalt: 3 av 120 tester feilet, alle i betalingsmodulen. [...] Ifølge endringsloggen
> endret versjon 3.0 standard tidsavbrudd fra 30 til 5 sekunder. Jeg tror det er svært sannsynlig at dette
> er årsaken, [...]

**Klar** (111 tokens i snitt), hele rapporten:

```klar
checked 3 of 120 checkout test pa fail in local run. all failed test li in payment module.
failure pa start after dependency update U of yesterday. U pa upgrade HTTP client from version 2.4 to 3.0.
per changelog, version 3.0 pa change default timeout from 30s to 5s.
so 90% this li cause because all failed test li call slow payment sandbox. I pa not yet confirm this.
then I fu set timeout to 30s then rerun test.
```

Hver setning har nøyaktig én tolkning, og et program kan lese den. `python -m klar gloss` viser hvordan:

```text
checked 3 of 120 checkout test pa fail in local run.
  ‹VERIFIED› [3 of [120 checkout test]] PAST:fail {in [local run]} .
per changelog, version 3.0 pa change default timeout from 30s to 5s.
  ‹SOURCE [changelog]› [version 3.0] PAST:change [default timeout] {from [30s]} {to [5s]} .
so 90% this li cause because all failed test li call slow payment sandbox.
  ‹INFERRED› ‹90%› [this] NOW:cause BECAUSE [all failed test] NOW:call [slow payment sandbox] .
```

Leseren ser hva agenten selv har sjekket (`checked`), hva som er hentet fra endringsloggen (`per changelog,`)
og hva som er en slutning med 90 % sikkerhet (`so 90%`). På engelsk sto dette spredt i formuleringer som
*I ran*, *According to* og *I think this is very likely*.

## Resultater

**Tokens** (45 tekster, snitt over åtte tokenizere, [alle tall](bench/RESULTS.md)):

| | Tokens | Klar sparer |
|---|---:|---:|
| Norsk | 1532 | 32 % |
| Engelsk | 1103 | 6 % |
| **Klar** | **1035** | |
| Telegramengelsk (uten artikler og hjelpeverb) | 876 | Klar er 18 % lengre, men entydig |

**Læring** ([alle svar](eval/RESULTS.md)): Claude Haiku, Sonnet og Opus fikk bare primeren, ingen verktøy og
ingen tilgang til repoet. De forsto 53,5 av 54 Klar-setninger. Etter at primeren ble rettet for feilene i
første runde, skrev de gyldig Klar i 48 av 48 nye setninger.

**De tre viktigste funnene:**

1. **Engelske ord er det billigste en modell har.** Oppdiktede ord gjorde tekstene 27–41 % dyrere, og
   logiske symboler som `∀` og `⇔` koster 1,5–2,3 tokens mot 1 for `all` og `iff`. Derfor er ordforrådet
   engelsk.
2. **Entydighet koster omtrent ett token per verb.** Telegramengelsk er kortest fordi leseren må gjette.
   Klar betaler med markøren og får til gjengjeld én tolkning, tid, kilde og sikkerhet. Klar er altså et
   presisjonsformat som også er litt kortere, ikke et kompresjonsformat.
3. **Den store gevinsten er for norsk og for usikkerhet.** Mot norsk sparer Klar en tredel. Setninger som
   *I'm not sure, but I think the memory leak comes from the image cache* (17 tokens) blir
   `maybe memory leak li from image cache.` (8 tokens).

Primeren koster omtrent 1 700 tokens og lønner seg etter rundt 5 300 tokens med tekst mot norsk, eller rundt
28 000 mot engelsk. Med prompt caching er tallene en tidel. Se [når Klar lønner seg](docs/begrunnelse.md#8-når-klar-lønner-seg-og-når-ikke).

## Klar Kort: når tokens teller mest

Klar er laget for presisjon. Når det bare gjelder å få ned antall tokens, finnes [Klar Kort](docs/kort.en.md):
korte notater mellom modeller som dropper alt leseren kan bygge opp igjen. Primeren er på rundt 530 tokens.

```text
ran tests: 41 pass, 1 fail. failure likely caused by old cache, so should clear it
```

Hvor kort kan testen bli? Ferske modeller pakket hver versjon ut igjen uten å se originalen, og uavhengige
dommere telte hvor mange av de 156 nøkkelfaktaene som overlevde ([metode og alle svar](eval/kort/README.md)):

| Versjon | Tokens (snitt, 8 tokenizere) | Fakta som overlevde |
|---|---:|---:|
| Engelsk | 1103 | 100 % |
| Klar | 1035 | 99 % |
| Telegramengelsk | 876 | 100 % |
| **Klar Kort** (versjon 3) | **640** | **99 %** |
| *bare innholdsordene, uten grammatikk* | *551* | *(gulvet)* |
| **Kort-500** | **463** | **79 %** |
| **Kort-200** | **185** | **39 %** |

Bare innholdsordene i testen koster 551 tokens, og et ord kan ikke koste mindre enn ett token. Klar Kort
kommer nær gulvet og beholder nesten alt, med 42 % færre tokens enn engelsk. Under 500 og 200 tokens går
også, men da er teksten under gulvet, og innhold må ut. Kort-500 beholder omtrent fire av fem fakta, og
Kort-200 bare hovedpoenget i hver tekst. Se [begrunnelsen](docs/begrunnelse.md#11-kan-testen-skrives-med-200-eller-500-tokens)
for hva som skal til for å komme lenger ned.

**Lønner det seg med noe mer avansert, som krever lengre opplæring?** Ikke som skriftspråk. To tredeler av
tokenene i Klar Kort er allerede ett token per ord, og selv en kodebok som kjenner testen på forhånd, sparer
bare 5 % ([CODEBOOK.md](bench/CODEBOOK.md)). Det som kan gi mer, er å trene selve modellen. Finjustering
fjerner primeren. En tokenizer med tokens som dekker flere ord kan gi opptil en tredel færre tokens, men
krever en ny modell ([begrunnelsen](docs/begrunnelse.md#12-lønner-det-seg-med-noe-mer-avansert-som-krever-lengre-opplæring)).

## Kom i gang

Krever Python 3.11 eller nyere. Selve språkverktøyene har ingen avhengigheter.

```sh
cd klar
pip install -e ".[dev]"

python -m klar check eksempler/systemprompt.klar          # feil og advarsler, med tips
python -m klar check --strict eksempler/agentrapport.klar # krever kilde for hver påstand
python -m klar gloss eksempler/kodegjennomgang.klar       # vis oppbygningen og hva it/etiketter peker på
python -m klar json eksempler/agentrapport.klar           # syntakstre og trekk som JSON
pytest
```

Feilmeldingene sier hva som er galt og hvordan det rettes, også når feilen er en engelsk vane:

```text
1:5: feil: ventet et subjekt eller en markør (li, pa, fu, must ...), fant «the». Tips: «the»: Klar har ingen artikler: stryk «the».
```

Målingene og læringstesten kan kjøres på nytt:

```sh
pip install -e ".[bench]"
python bench/run.py        # laster ned tokenizerne første gang (ca. 60 MB) og skriver bench/RESULTS.md
python bench/codebook.py   # hva en kodebok kunne spart, skriver bench/CODEBOOK.md
python eval/score.py       # skriver eval/RESULTS.md fra de lagrede svarene
python eval/kort/score.py  # skriver eval/kort/RESULTS.md fra de lagrede svarene
```

## Bruke Klar med en språkmodell

1. Legg [docs/primer.en.md](docs/primer.en.md) i systemprompten. Den er på engelsk fordi det er billigst:
   den norske utgaven ([primer.no.md](docs/primer.no.md)) koster rundt 20 % mer. Bruk prompt caching
   hvis du kan.
2. Be modellen skrive i Klar der det passer, for eksempel: *Write your status reports in Klar. Mark every claim
   with its source.*
3. Kjør svaret gjennom `klar check` (eller `--strict` for rapporter). Gi feilmeldingene tilbake til modellen.
   Da retter den seg selv.
4. Vis mennesker glossen, eller be modellen oversette til vanlig språk.

Fra Python:

```python
from klar import features, gloss_text
from klar.lint import check

text, issues = check("checked test pa pass. likely cache li old.", strict=True)
print(gloss_text(text))  # ['‹VERIFIED› [test] PAST:pass .', '‹likely ≈75%› [cache] NOW:old .']
print(features(text.sentences[1])["confidence"])  # likely
```

## Hva ligger hvor

| Mappe | Innhold |
|---|---|
| [`klar/`](klar/) | språket i kode: ordlisten (`lexicon.py`), lexer, parser, syntakstre, glossator og sjekker |
| [`docs/`](docs/) | spesifikasjon, primer (engelsk og norsk), Klar Kort og begrunnelse |
| [`eksempler/`](eksempler/) | systemprompt, agentrapport og kodegjennomgang på Klar |
| [`bench/`](bench/) | parallelkorpuset (engelsk, telegramengelsk, norsk, Klar, Klar Kort, Kort-500, Kort-200), målingene og kodebokanalysen |
| [`eval/`](eval/) | læringstesten og komprimeringstesten: prompter, fasit, modellsvar, vurdering og resultater |
| [`tests/`](tests/) | tester for parser, glossator, sjekker, korpus, dokumentasjon og robusthet |

## Begrensninger

Klar fjerner tvetydighet i oppbygningen, ikke i ordene (*bank*, *run*). Korpuset er lite og skrevet av den
som laget språket, og læringstesten bruker bare Claude-modeller. Modeller som ikke er trent på Klar, kan gli
tilbake mot engelsk i lange tekster; sjekkeren er laget for å fange det. Hele listen står i
[begrunnelsen](docs/begrunnelse.md#9-begrensninger).
