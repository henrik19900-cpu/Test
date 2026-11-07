# Komprimeringstesten: hvor mye mening overlever?

**Spørsmålet:** Kan testkorpuset skrives med maks 200 tokens i stedet for rundt 1 000, uten å miste
innhold? Og hvor langt ned kommer man hvis alt innhold skal være med?

**Svaret:** 200 tokens går, men da forsvinner det meste av innholdet. Med alt innholdet kommer vi ned til
rundt 660.

| Versjon | Tokens (snitt, 8 tokenizere) | Fakta som overlevde |
|---|---:|---:|
| Engelsk (originalen) | 1103 | 100 % |
| Klar | 1035 | 99 % |
| Telegramengelsk | 876 | 100 % |
| **Klar Kort** | **664** | **93 %** |
| **Kort-200** | **185** | **39 %** |

Alle tallene og hvert tapte faktum står i [RESULTS.md](RESULTS.md).

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

## Hva tallene viser

- **Kort-200 holder budsjettet, men mister 61 % av innholdet.** Hver tekst blir til hovedpoenget sitt:
  «Before you delete any files, ask the user for confirmation» blir `confirm deletes`. Det går bra. Men
  «The function returns null when the list is empty, which explains the crash» blir `empty list → crash`,
  og da er både «null» og forklaringen borte. De lange tekstene taper mest: av 13 poeng i systemprompten
  ble 3 igjen.
- **Klar Kort beholder 93 % for 60 % av tokenene.** Det som forsvant, er små presiseringer, ikke
  hovedinnhold: «technical» foran jargon, «with anyone», «about» foran 60 %, «first» foran released. Hver av
  dem koster omtrent ett token å ta med. Én feil var mer alvorlig: `x even, >2 → not prime` ble lest som en
  regel («hvis x er partall …») og ikke som en påstand om x.
- **Telegramengelsk mistet ingenting her.** Med 876 tokens er det et godt valg når leseren er en modell og
  man ikke trenger at teksten kan sjekkes maskinelt. Klar koster litt mer og gir én tolkning per setning.
- **Tokens per bevart faktum** faller fra 7,1 (engelsk) til 4,6 (Klar Kort) og 3,0 (Kort-200). Kort-200 er
  altså mest effektiv per faktum den beholder, men den beholder færre enn to av fem.

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
