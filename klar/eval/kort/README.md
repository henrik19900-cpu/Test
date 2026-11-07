# Komprimeringstesten: hvor mye mening overlever?

**Spørsmålet:** Kan testkorpuset skrives med maks 200 tokens, eller under 500, i stedet for rundt 1 000, uten
å miste innhold? Og hvor langt ned kommer man hvis alt innhold skal være med?

**Svaret:** Med alt innholdet kommer vi ned til 640 tokens: Klar Kort versjon 3 beholdt 99 % av fakta. Under
500 og 200 går også, men da forsvinner innhold. Kort-500 beholdt 79 % og Kort-200 39 %.

| Versjon | Tokens (snitt, 8 tokenizere) | Fakta som overlevde |
|---|---:|---:|
| Engelsk (originalen) | 1103 | 100 % |
| Klar | 1035 | 99 % |
| Telegramengelsk | 876 | 100 % |
| Klar Kort, versjon 1 | 664 | 93 % |
| Klar Kort, versjon 2 | 700 | 98 % |
| **Klar Kort, versjon 3** | **640** | **99 %** |
| **Kort-500** | **463** | **79 %** |
| Kort-200 | 185 | 39 % |

Alle tallene og hvert tapte faktum står i [RESULTS.md](RESULTS.md).

## Gulvet

Først en måling som ikke trenger modeller. Innholdsordene i Klar-tekstene (*user, file, Oslo, 700000,
config.yaml* og så videre), uten et eneste grammatikkord og uten engang «not», koster **551 tokens** i snitt
over de åtte tokenizerne. Det er omtrent gulvet for hva samme innhold kan koste, fordi et ord ikke kan bli
billigere enn ett token. Da har teksten allerede mistet betydning: «do not use jargon» er blitt «use jargon».

Både 500 og 200 tokens er altså under gulvet. For å komme under 500 måtte nesten en tredel av ordene i
Klar Kort ut (fra 459 til 322), og for å komme ned til 200 nesten tre av fire.

## Versjonene

- **Klar Kort** ([docs/kort.en.md](../../docs/kort.en.md), primer på ca. 530 tokens): så kort som mulig, men
  med alle fakta. Den tar vekk alt leseren kan bygge opp igjen (artikler, hjelpeverb, opplagte pronomen,
  fyllord), bruker vanlig engelsk bøying fordi den er gratis, og beholder Klars ord for kilde og sikkerhet.
  `→` betyr «hvis … så», «fører til» eller «endres til», `so` betyr «derfor», og `:` erstatter «is».
  - **Versjon 1** var første forsøk. Den mistet små presiseringer, og `→` ble brukt for både «hvis» og
    «derfor».
  - **Versjon 2** tok med presiseringene igjen, og primeren fikk `so` for «derfor».
  - **Versjon 3** er samme språk skrevet strammere: færre komma og billigere ord, men uten å fjerne innhold
    med vilje.
- **Kort-500**: hele korpuset under 500 tokens i alle åtte tokenizerne (463 i snitt, høyst 493). Det minst
  viktige i hver tekst er tatt ut.
- **Kort-200**: hele korpuset presset ned til maks 200 tokens i alle åtte tokenizerne. Bare hovedpoenget i hver
  tekst får være med.

Alle står i [bench/kort.yaml](../../bench/kort.yaml), ved siden av [bench/corpus.yaml](../../bench/corpus.yaml).

## Slik ble det målt

1. **Fakta.** For hver av de 45 tekstene står nøkkelfaktaene i [facts.yaml](facts.yaml), 156 i alt, skrevet
   ut fra den engelske originalen. Eksempel: «Do not use technical jargon» og «Exception: jargon is allowed
   if the user asks for it».
2. **Utpakking.** Hver versjon gikk til en fersk modellinstans (Claude Sonnet): telegramengelsk, Klar (med
   Klar-primeren) og hver Kort-versjon (med Kort-primeren). Modellene fikk beskjed om å skrive hver tekst ut
   som fullstendig engelsk, uten å legge til noe. Ingen av dem så originalen eller de andre versjonene.
   Promptene står i [prompts/](prompts/), og svarene i [decoded/](decoded/). To prøveutpakkinger av et utkast
   til versjon 2 (`kort_v2a.json` og `kort_v2b.json`) viste at `x → y` fortsatt ble lest som en regel to
   steder. De tekstene ble rettet før den endelige utpakkingen.
3. **Dommere.** Fire ferske modellinstanser (Claude Opus), A–D, fikk faktalisten og to utpakkede versjoner
   hver, og satte 1, 0,5 eller 0 på hvert faktum. De visste ikke hvilken versjon en tekst kom fra, fordi
   versjonene het S1–S8 ([judged/labels.json](judged/labels.json)). Versjon 1 ble vurdert av to dommere, A og
   C, og begge ga 93 %. Svarene står i [judged/](judged/).
4. **Poeng.** [score.py](score.py) regner ut andelen fakta som overlevde, og deler tokens på antall bevarte
   fakta.

## Hva tallene viser

- **Klar Kort versjon 3 er best: 640 tokens og 99 % av fakta**, 42 % færre tokens enn engelsk. Færre komma
  og billigere ord kostet ingenting. To av de tre tapene skyldtes en feil i selve teksten, ikke i lesingen:
  `so very likely cause: failing tests all call slow payment sandbox` sier at årsaken *er* at testene kaller
  sandkassen. Riktig er `very likely cause, because failing tests all call slow payment sandbox`. Samme feil
  står i versjon 2.
- **Versjon 2 rettet det versjon 1 mistet.** Versjon 1 mistet små presiseringer: «technical» foran jargon,
  «with anyone», «about» foran 60 %, «first» foran released. Hver av dem koster omtrent ett token å ta med.
  Én feil var mer alvorlig: `x even, >2 → not prime` ble lest som en regel («hvis x er partall …») og ikke
  som en påstand om x. Derfor fikk versjon 2 `so` for «derfor».
- **Kort-500 holder budsjettet, men mister 21 % av innholdet.** Tapene er størst i de lange tekstene.
  Kodegjennomgangen mistet 4,5 av 10 poeng, fordi «reviewed PR» og filstiene ble tatt ut. Det samme gjelder
  dialoger der spørsmålet forsvant: i `bug still on Android, not iOS` er både «bug fixed?» og «no» borte. Én
  feil var en lesefeil: `read abstracts only` ble lest som en instruks, fordi *read* er likt i nåtid og
  fortid. Slike verb bør få `I` foran.
- **Tokenene kan fordeles bedre.** Velger man for hver tekst den målte versjonen som gir flest fakta, holder
  et utvalg seg under 500 tokens og beholder 87 % ([RESULTS.md](RESULTS.md#beste-blanding-under-500-tokens)).
  Det er et optimistisk anslag, fordi utvalget er gjort med fasit. Men det viser hvor gevinsten ligger: en
  presisering i en kort tekst koster 1–2 tokens, en filsti 7–9.
- **Kort-200 holder budsjettet, men mister 61 % av innholdet.** Hver tekst blir til hovedpoenget sitt:
  «Before you delete any files, ask the user for confirmation» blir `confirm deletes`. Det går bra. Men
  «The function returns null when the list is empty, which explains the crash» blir `empty list → crash`,
  og da er både «null» og forklaringen borte. De lange tekstene taper mest: av 13 poeng i systemprompten
  ble 3 igjen.
- **Telegramengelsk mistet ingenting her.** Med 876 tokens er det et godt valg når leseren er en modell og
  man ikke trenger at teksten kan sjekkes maskinelt. Klar koster litt mer og gir én tolkning per setning.
- **Tokens per bevart faktum** faller fra 7,1 (engelsk) til 4,1 (Klar Kort versjon 3), 3,7 (Kort-500) og 3,0
  (Kort-200). De korteste versjonene utnytter hvert token best, men de beholder færre fakta.
- **En lengre primer med kodebok hjelper lite.** To tredeler av tokenene i versjon 3 er ett token per ord.
  Selv en kodebok som kjenner testen på forhånd, sparer bare 5 %
  ([bench/CODEBOOK.md](../../bench/CODEBOOK.md), og
  [begrunnelsen](../../docs/begrunnelse.md#12-lønner-det-seg-med-noe-mer-avansert-som-krever-lengre-opplæring)).

## Begrensninger

- Faktalistene og alle Kort-tekstene er skrevet av den samme som laget språket. Utpakkingen og
  karaktersettingen er gjort av uavhengige modellinstanser, men alle er Claude-modeller.
- Én utpakking per versjon. En annen modell ville kanskje fått med seg litt mer eller litt mindre.
- Versjonene er vurdert av forskjellige dommere. De to dommerne som vurderte versjon 1, kom til nøyaktig samme
  andel, men forskjeller på ett eller to prosentpoeng (98 mot 99 %) er innenfor støyen.
- Engelsk får 100 % per definisjon, fordi faktaene er skrevet ut fra den engelske teksten.
- Kort er laget for at en *modell* skal lese det. Et menneske uten primeren vil ofte gjette feil.

## Kjør på nytt

```sh
python bench/run.py          # tokens for alle versjoner, skriver bench/results.json
python bench/codebook.py     # hva en kodebok kunne spart, skriver bench/CODEBOOK.md
python eval/kort/score.py    # skriver eval/kort/RESULTS.md fra de lagrede svarene
```
