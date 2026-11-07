# Kan en kodebok gjøre Klar Kort kortere?

Generert av `python bench/codebook.py`. En kodebok lærer leseren korte koder for ord og uttrykk, og gjør derfor primeren lengre. Den kan bare spare tokens der et ord eller uttrykk koster mer enn ett token. Tabellen deler tokenene i Kort v3 (den korteste versjonen som beholder innholdet, 45 tekster) etter hva de er. Snitt over 8 tokenizere.

| Del av teksten | Tokens | Andel |
|---|---:|---:|
| Første token i hvert ord (439 ord) | 439 | 69 % |
| Tall og enheter, tokens utover det første (`30s`, `3/120`, `~25%`) | 82 | 13 % |
| Navn, stier og kode, tokens utover det første (`JSON`, `src/payments/validators.py`) | 23 | 4 % |
| Engelske ord, tokens utover det første (`unconfirmed`, `penguins`) | 17 | 3 % |
| Tegnsetting og symboler (`.` `,` `:` `→` `+`) | 71 | 11 % |
| Sammenslåing over ordgrenser, og første ord i hver tekst | 7 | 1 % |
| **Kort v3 i alt** | **640** | |

## Det meste en kodebok kan spare

Tallene under er en øvre grense. Kodeboken er laget med fasit: den kjenner testen på forhånd. I ny tekst står mange av ordene ikke i kodeboken.

| Kodebok | Sparer | Kort v3 blir |
|---|---:|---:|
| Hvert engelske ord koster ett token (21 oppføringer) | 17 | 622 |
| + hvert uttrykk som står minst to ganger blir ett token (6 oppføringer) | 33 | 606 |

Kodeboken selv koster omtrent 191 tokens i primeren, mer enn den sparer på hele testen. Den sparer tokens tilsvarende 3,0 % av den engelske originalen, så den lønner seg først etter omtrent 6 312 tokens med tekst, eller 631 med prompt caching (en lagret primer koster omtrent en tidel). Det forutsetter at akkurat ordene i kodeboken kommer igjen i den teksten.

Uttrykkene som står minst to ganger:

`say so never guess` (2), `always answer` (2), `never share` (2), `error message` (2), `rerun tests` (2), `so likely` (2)

De dyreste engelske ordene:

`penguins` (+2.6), `don't` (+2.0), `rerun` (+1.5), `yesterday's` (+1.1), `unconfirmed` (+1.1), `couldn't` (+1.0), `can't` (+1.0), `signups` (+1.0), `customer's` (+1.0), `customers'` (+1.0), `changelog` (+1.0), `jargon` (+0.6)

