# Målinger: hvor mange tokens koster det samme innholdet?

Generert av `python bench/run.py` fra `bench/corpus.yaml`: 40 setninger og 5 lengre tekster, hver skrevet på engelsk, telegramengelsk, norsk og Klar med samme informasjon. Tallene er tokens slik hver modells egen tokenizer teller dem.

## Hovedresultat (alle tekster)

| Tokenizer | Engelsk | Telegramengelsk | Norsk | Klar | Klar mot engelsk | Klar mot norsk |
|---|---:|---:|---:|---:|---:|---:|
| GPT-4 / GPT-3.5 (`cl100k_base`) | 1089 | 862 | 1567 | 1019 | −6 % | −35 % |
| GPT-4o / o-serien (`o200k_base`) | 1080 | 842 | 1354 | 1018 | −6 % | −25 % |
| Claude (eldre, offentlig) (`claude-legacy`) | 1072 | 847 | 1658 | 1001 | −7 % | −40 % |
| Llama 3 (`llama3`) | 1089 | 862 | 1565 | 1018 | −7 % | −35 % |
| Qwen 2.5 (`qwen2.5`) | 1128 | 901 | 1605 | 1059 | −6 % | −34 % |
| Mistral Nemo (`mistral-nemo`) | 1138 | 914 | 1538 | 1067 | −6 % | −31 % |
| Gemma 2 (`gemma2`) | 1135 | 913 | 1390 | 1073 | −5 % | −23 % |
| DeepSeek V3 (`deepseek-v3`) | 1093 | 867 | 1578 | 1022 | −6 % | −35 % |
| **Snitt** | **1103** | **876** | **1532** | **1035** | **−6 %** | **−32 %** |

Tegn (ikke tokens): engelsk 4797, telegramengelsk 3734, norsk 4806, Klar 4172 (−13 % mot engelsk).

## Per kategori (snitt over de åtte tokenizerne)

| Kategori | Engelsk | Telegramengelsk | Norsk | Klar | Klar mot engelsk | Klar mot telegram |
|---|---:|---:|---:|---:|---:|---:|
| Instrukser til en AI (11) | 247 | 206 | 351 | 232 | −6 % | +13 % |
| Rapporter fra agenter (12) | 371 | 288 | 519 | 334 | −10 % | +16 % |
| Resonnement (9) | 236 | 185 | 314 | 224 | −5 % | +21 % |
| Fakta (7) | 171 | 137 | 243 | 170 | −1 % | +24 % |
| Spørsmål og svar (6) | 77 | 59 | 105 | 74 | −4 % | +25 % |
| *Bare de 5 lengre tekstene* | 489 | 391 | 686 | 469 | −4 % | +20 % |

Klar er kortere enn engelsk i 35 av 45 tekster. Median for Klar/engelsk per tekst: 0.95; spredning fra 0.47 til 1.12.

## Hver tekst (snitt over tokenizerne)

| Tekst | Engelsk | Telegram | Norsk | Klar | Klar mot engelsk |
|---|---:|---:|---:|---:|---:|
| instruks-01 | 11.0 | 9.0 | 12.9 | 10.0 | −9 % |
| instruks-02 | 12.6 | 11.6 | 17.1 | 12.6 | +0 % |
| instruks-03 | 16.2 | 13.2 | 22.4 | 16.0 | −2 % |
| instruks-04 | 11.0 | 8.0 | 12.9 | 9.0 | −18 % |
| instruks-05 | 12.0 | 10.0 | 17.0 | 10.9 | −9 % |
| instruks-06 | 14.0 | 11.0 | 17.2 | 11.9 | −15 % |
| instruks-07 | 19.0 | 14.0 | 26.8 | 21.0 | +11 % |
| instruks-08 | 11.2 | 9.2 | 16.5 | 9.0 | −20 % |
| instruks-09 | 12.0 | 10.0 | 19.0 | 12.0 | +0 % |
| instruks-10 | 19.2 | 18.2 | 28.1 | 18.0 | −6 % |
| rapport-01 | 15.1 | 12.8 | 18.5 | 12.1 | −20 % |
| rapport-02 | 10.0 | 7.0 | 17.6 | 7.0 | −30 % |
| rapport-03 | 18.9 | 11.9 | 28.4 | 16.8 | −11 % |
| rapport-04 | 14.2 | 11.2 | 15.2 | 12.2 | −14 % |
| rapport-05 | 15.0 | 12.0 | 21.6 | 14.9 | −1 % |
| rapport-06 | 15.6 | 11.6 | 20.5 | 12.6 | −19 % |
| rapport-07 | 17.2 | 14.5 | 26.4 | 17.5 | +1 % |
| rapport-08 | 13.0 | 8.8 | 21.1 | 9.8 | −25 % |
| rapport-09 | 14.2 | 11.4 | 21.0 | 13.5 | −5 % |
| rapport-10 | 17.0 | 11.0 | 23.1 | 8.0 | −53 % |
| resonnement-01 | 29.6 | 24.6 | 39.8 | 28.6 | −3 % |
| resonnement-02 | 28.5 | 23.5 | 29.9 | 27.5 | −4 % |
| resonnement-03 | 14.9 | 12.9 | 22.9 | 13.9 | −7 % |
| resonnement-04 | 15.0 | 10.0 | 20.9 | 14.0 | −7 % |
| resonnement-05 | 21.0 | 17.0 | 30.4 | 21.0 | +0 % |
| resonnement-06 | 20.2 | 11.2 | 27.9 | 16.1 | −20 % |
| resonnement-07 | 14.6 | 11.6 | 26.2 | 14.0 | −4 % |
| resonnement-08 | 20.0 | 13.0 | 26.9 | 18.0 | −10 % |
| fakta-01 | 17.2 | 15.2 | 23.0 | 16.1 | −7 % |
| fakta-02 | 11.9 | 11.9 | 16.9 | 11.6 | −2 % |
| fakta-03 | 17.1 | 15.1 | 20.2 | 17.4 | +1 % |
| fakta-04 | 15.2 | 13.2 | 22.1 | 15.9 | +4 % |
| fakta-05 | 13.0 | 9.9 | 18.0 | 12.9 | −1 % |
| fakta-06 | 9.9 | 9.9 | 13.2 | 9.8 | −1 % |
| dialog-01 | 7.0 | 6.0 | 10.2 | 6.2 | −11 % |
| dialog-02 | 17.0 | 13.0 | 22.2 | 17.0 | +0 % |
| dialog-03 | 12.0 | 8.0 | 16.1 | 12.0 | +0 % |
| dialog-04 | 8.0 | 8.0 | 14.0 | 9.0 | +12 % |
| dialog-05 | 15.0 | 11.1 | 20.4 | 13.0 | −13 % |
| dialog-06 | 18.2 | 13.2 | 21.8 | 17.2 | −5 % |
| tekst-instruks | 108.5 | 91.5 | 161.0 | 101.6 | −6 % |
| tekst-rapport | 121.5 | 95.5 | 185.2 | 110.6 | −9 % |
| tekst-resonnement | 72.4 | 61.4 | 89.1 | 71.1 | −2 % |
| tekst-forskning | 86.9 | 61.9 | 129.8 | 86.4 | −1 % |
| tekst-kodegjennomgang | 99.5 | 80.8 | 120.4 | 98.9 | −1 % |

## Grammatikkordene: ett token hver?

130 av 130 grammatikkord og etiketter koster nøyaktig ett token (med mellomrom foran) i alle åtte tokenizerne.

## Symboler mot ord

Mange «AI-språk» bruker logiske symboler og emoji. De ser korte ut, men koster mer:

| Symbol / Klar-ord | Tokens for symbolet | Tokens for ordet |
|---|---:|---:|
| ∀ / all | 1.50 | 1.00 |
| ∃ / some | 1.88 | 1.00 |
| ¬ / not | 1.38 | 1.00 |
| ∧ / and | 1.50 | 1.00 |
| ∨ / or | 1.75 | 1.00 |
| ⊕ / xor | 2.25 | 1.00 |
| → / if | 1.00 | 1.00 |
| ⇔ / iff | 2.25 | 1.00 |
| ∴ / so | 1.88 | 1.00 |
| ≈ / approx | 1.50 | 1.00 |
| ✓ / checked | 1.38 | 1.00 |
| ❓ / maybe | 2.12 | 1.00 |
| 🔒 / must | 2.25 | 1.00 |

## Hvorfor ikke helt nye ord?

Et språk med eget ordforråd (som esperanto eller toki pona) måtte bytte ut de engelske innholdsordene. For å måle hva det ville koste, er hvert innholdsord i Klar-tekstene byttet mot et oppdiktet ord med samme lengde i stavelser, mens grammatikken er den samme. Eksempel: `must always answer in Norwegian. answer must short.` blir `must always pebu in Norwegian. pebu must kevu.`.

| Tokenizer | Klar | Klar med oppdiktede ord | Forskjell |
|---|---:|---:|---:|
| GPT-4 / GPT-3.5 | 1019 | 1401 | +37 % |
| GPT-4o / o-serien | 1018 | 1292 | +27 % |
| Claude (eldre, offentlig) | 1001 | 1415 | +41 % |
| Llama 3 | 1018 | 1394 | +37 % |
| Qwen 2.5 | 1059 | 1441 | +36 % |
| Mistral Nemo | 1067 | 1396 | +31 % |
| Gemma 2 | 1073 | 1361 | +27 % |
| DeepSeek V3 | 1022 | 1391 | +36 % |

Ordene modellen allerede kjenner, er de billigste den har. Nye ord koster flere tokens, og modellen må i tillegg lære hva de betyr.

## Klar Kort: så få tokens som mulig

[Klar Kort](../docs/kort.en.md) dropper alt leseren kan gjette seg til, men beholder hvert faktum. Kort-200 er hele korpuset presset ned til maks 200 tokens, og der overlever bare hovedpoenget i hver tekst. «Bare innholdsord» er innholdsordene i Klar-tekstene uten et eneste grammatikkord, ikke engang «not». Det er omtrent gulvet for hva samme innhold kan koste i tokens. Hvor mange av fakta som overlever i hver versjon, står i [eval/kort/RESULTS.md](../eval/kort/RESULTS.md).

| Tokenizer | Engelsk | Klar | Telegramengelsk | Klar Kort | Kort-200 | Bare innholdsord |
|---|---:|---:|---:|---:|---:|---:|
| GPT-4 / GPT-3.5 | 1089 | 1019 | 862 | 687 | 181 | 539 |
| GPT-4o / o-serien | 1080 | 1018 | 842 | 681 | 179 | 539 |
| Claude (eldre, offentlig) | 1072 | 1001 | 847 | 662 | 178 | 505 |
| Llama 3 | 1089 | 1018 | 862 | 687 | 181 | 539 |
| Qwen 2.5 | 1128 | 1059 | 901 | 723 | 191 | 579 |
| Mistral Nemo | 1138 | 1067 | 914 | 736 | 197 | 590 |
| Gemma 2 | 1135 | 1073 | 913 | 724 | 188 | 574 |
| DeepSeek V3 | 1093 | 1022 | 867 | 692 | 185 | 544 |
| **Snitt** | **1103** | **1035** | **876** | **699** | **185** | **551** |

Klar Kort er −37 % mot engelsk, −32 % mot Klar og −20 % mot telegramengelsk. Kort-200 er −83 % mot engelsk.

## Primeren: hva det koster å lære en modell Klar

- `docs/primer.en.md` (Klar, engelsk): 1713 tokens i snitt (1689–1780).
- `docs/primer.no.md` (Klar, norsk): 2063 tokens i snitt (1924–2266).
- `docs/kort.en.md` (Klar Kort): 526 tokens i snitt (517–540).

Klar sparer 6% av tokenene mot engelsk i korpuset. Primeren på 1713 tokens lønner seg derfor etter omtrent **27 627 tokens** med engelsk tekst som ellers ville blitt skrevet eller lest i samme samtale. Med prompt caching koster en lagret primer omtrent en tidel per gjenbruk, og da er grensen nær **2 763 tokens**. Mot norsk tekst sparer Klar 32%, og grensen er omtrent **5 276 tokens** (528 med caching). Når modellen *skriver* Klar, teller besparelsen mer, fordi output-tokens er dyrere og tregere enn input-tokens.

