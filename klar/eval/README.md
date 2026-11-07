# Læringstesten

**Spørsmålet:** Kan en språkmodell lære Klar bare ved å lese primeren, uten trening og uten eksempler utover
dem primeren selv har?

**Svaret:** Ja. Tre modeller av ulik størrelse forsto nesten alt de leste (53,5 av 54 poeng), og etter én
runde med rettelser i primeren skrev alle tre gyldig Klar i 48 av 48 nye setninger. Tallene og alle svarene
står i [RESULTS.md](RESULTS.md).

## Slik ble testen gjort

- **Ferske modeller.** Hver modell ble startet på nytt, med bare én tekst: primeren og oppgavene
  ([round1/prompt.txt](round1/prompt.txt), [round2/prompt.txt](round2/prompt.txt)). Den fikk beskjed om ikke å
  bruke verktøy, så den kunne ikke lese repoet eller fasiten. Modellene var Claude Haiku, Sonnet og Opus.
- **Usette setninger.** Ingen av testsetningene står i primeren. Fasiten
  ([round1/items.yaml](round1/items.yaml), [round2/items.yaml](round2/items.yaml)) lå utenfor repoet mens
  modellene svarte.
- **To retninger.** I oppgave A oversetter modellen Klar til engelsk (forstå). I oppgave B oversetter den
  engelsk til Klar (skrive).
- **Maskin der det går, hånd der det må.** Om et Klar-svar er gyldig, og om det har de grammatiske trekkene
  oppgaven krever (riktig tid, kilde, sikkerhet, modalitet, nektelse, leddsetning, relativsetning), avgjøres av
  parseren i [score.py](score.py). Betydningen er vurdert for hånd etter en fast skala: 1 når alle
  hovedpunktene er riktige, 0,5 når ett er feil eller mangler, og 0 når hovedbetydningen er feil. Hvert trekk
  under 1 har en begrunnelse i `grading.yaml`, og råsvarene ligger i `answers/`, så vurderingene kan
  etterprøves.

## Hva runde 1 viste

Forståelsen var nesten feilfri (35,5 av 36). Modellene fulgte de delene av grammatikken som skiller seg mest
fra engelsk: hvor en preposisjonsfrase hører til (`hit man with stick` mot `hit (man with stick)`), hvor
relativsetningen slutter, hvilken kvantor som har størst rekkevidde, og forskjellen på sikker, sannsynlig
(`likely`) og prosent.

Skrivingen hadde tre slags feil, alle vaner fra engelsk:

1. **Komma før «but»** (`..., but I pa not check.`), hos to modeller.
2. **`suppose` for «jeg tror»**, hos to modeller. I Klar er `suppose` en antakelse man ikke påstår.
3. **Adverb foran markøren** (`file still li needed`), hos én modell.

## Hva som ble endret

Primeren fikk to setninger til: en om `suppose` mot `likely`/`maybe`, og en om komma og adverbplassering.
Sjekkeren fikk egne feilmeldinger for de samme feilene, så en modell som bruker `klar check` kan rette seg
selv.

## Hva runde 2 viste

Med 16 nye setninger i skriveoppgaven skrev alle tre modellene gyldig Klar hver gang (48 av 48). Feilene fra
runde 1 kom ikke igjen. Forståelsen var feilfri (18 av 18), også på oppgaver laget for å være vanskelige:
rekkevidden til `not` (`not all test pa pass` mot `all test pa not pass`), `xor` og hva `it` viser til.

Én ny svakhet dukket opp. Haiku skrev `script pa delete file and it pa crash.` og mente at skriptet krasjet.
Etter regelen i primeren peker `it` her på filen, og alle tre modellene leste det slik i oppgave A. Regelen er
altså lett å lese etter, men skrivere faller tilbake på engelsk vane når de skriver. Det er løst slik:
sjekkeren advarer nå når `it` som subjekt peker på et objekt mens et subjekt står like før, og primeren viser
den ryddige formen (`script pa delete file then crash.`). Hvorfor regelen ikke ble byttet ut, står i
[spesifikasjonen, § 7.2](../docs/spesifikasjon.md#72-hva-it-viser-til).

## Begrensninger

- **Liten test.** 24 setninger i runde 1 og 22 i runde 2. Testen viser at primeren virker, men den gir ikke
  presise feilrater.
- **Én modellfamilie.** Alle tre modellene er Claude-modeller. Andre modellfamilier er ikke testet.
- **Vurdert av den som laget språket.** Betydningen er vurdert for hånd av samme part som skrev Klar.
  Råsvarene og begrunnelsene er lagt ved for at andre skal kunne sjekke.
- **Primeren har endret seg litt etter runde 2.** Linjen om `then` ved `it` ble lagt til etterpå og er ikke
  testet med modeller. Primeren slik den ble testet, står i `round2/prompt.txt`.
- **Korte oppgaver.** Lange tekster og samtaler over mange runder, der en modell kan gli tilbake til engelsk,
  er ikke testet. Det er her `klar check` er tenkt brukt: som en sjekk i løkken.

## Kjør på nytt

```sh
python eval/score.py   # leser round*/answers og grading.yaml, skriver RESULTS.md
```

For å teste en ny modell: gi den `round2/prompt.txt`, lagre JSON-svaret som `round2/answers/<modell>.json`,
legg modellen til i `MODELS` i `score.py` og fyll ut vurderingen i `round2/grading.yaml`.
