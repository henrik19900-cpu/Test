# Komprimeringstesten: hvor mye mening overlever?

**Spørsmålet:** Kan testkorpuset skrives med maks 200 tokens i stedet for rundt 1 000, uten å miste
innhold? Og hvor langt ned kommer man hvis alt innhold skal være med?

Tallene står i [RESULTS.md](RESULTS.md).

## Gulvet

Først en måling som ikke trenger modeller. Innholdsordene i Klar-tekstene (*user, file, Oslo, 700000,
config.yaml* og så videre), uten et eneste grammatikkord og uten engang «not», koster **551 tokens** i snitt
over de åtte tokenizerne. Det er omtrent gulvet for hva samme innhold kan koste, fordi et ord ikke kan bli
billigere enn ett token. Da har teksten allerede mistet betydning: «do not use jargon» er blitt «use jargon».

200 tokens er altså under gulvet. Skal hele korpuset ned dit, må omtrent to tredeler av innholdsordene ut.

## To versjoner

- **Klar Kort** ([docs/kort.en.md](../../docs/kort.en.md), primer på ca. 440 tokens): så kort som mulig, men
  med alle fakta. Den tar vekk alt leseren kan bygge opp igjen (artikler, hjelpeverb, opplagte pronomen,
  fyllord), bruker vanlig engelsk bøying fordi den er gratis, og beholder Klars ord for kilde og sikkerhet.
  `→` erstatter «if … then» og «so», `:` erstatter «is».
- **Kort-200**: hele korpuset presset ned til maks 200 tokens i alle åtte tokenizerne. Bare hovedpoenget i hver
  tekst får være med.

Begge står i [bench/kort.yaml](../../bench/kort.yaml), ved siden av [bench/corpus.yaml](../../bench/corpus.yaml).

## Slik ble det målt

1. **Fakta.** For hver av de 45 tekstene står nøkkelfaktaene i [facts.yaml](facts.yaml), 156 i alt, skrevet
   ut fra den engelske originalen. Eksempel: «Do not use technical jargon» og «Exception: jargon is allowed
   if the user asks for it».
2. **Utpakking.** Fire ferske modellinstanser (Claude Sonnet) fikk hver sin versjon: telegramengelsk, Klar
   (med Klar-primeren), Klar Kort eller Kort-200 (begge med Kort-primeren). De fikk beskjed om å skrive hver
   tekst ut som fullstendig engelsk, uten å legge til noe. Ingen av dem så originalen eller de andre
   versjonene. Promptene står i [prompts/](prompts/), og svarene i [decoded/](decoded/).
3. **Dommere.** To ferske modellinstanser (Claude Opus) fikk faktalisten og de utpakkede tekstene og satte
   1, 0,5 eller 0 på hvert faktum. De visste ikke hvilken versjon en tekst kom fra, fordi versjonene het S1–S4
   ([judged/labels.json](judged/labels.json)). Svarene står i [judged/](judged/).
4. **Poeng.** [score.py](score.py) regner ut andelen fakta som overlevde, og deler tokens på antall bevarte
   fakta.

## Begrensninger

- Faktalistene, Kort-tekstene og Kort-200-tekstene er skrevet av den samme som laget språket. Utpakkingen og
  karaktersettingen er gjort av uavhengige modellinstanser, men alle er Claude-modeller.
- Én utpakking per versjon. En annen modell ville kanskje fått med seg litt mer eller litt mindre.
- Engelsk får 100 % per definisjon, fordi faktaene er skrevet ut fra den engelske teksten.
- Kort er laget for at en *modell* skal lese det. Et menneske uten primeren vil ofte gjette feil.

## Kjør på nytt

```sh
python bench/run.py          # tokens for alle versjoner, skriver bench/results.json
python eval/kort/score.py    # skriver eval/kort/RESULTS.md fra de lagrede svarene
```
