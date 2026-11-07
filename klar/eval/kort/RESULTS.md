# Hvor mye mening overlever komprimeringen?

Generert av `python eval/kort/score.py`. Metoden står i [README.md](README.md). Korpuset har 45 tekster med til sammen 156 nøkkelfakta ([facts.yaml](facts.yaml)).

## Resultat

| Versjon | Tokens (snitt, 8 tokenizere) | Fakta som overlevde | Tokens per bevart faktum |
|---|---:|---:|---:|
| Engelsk (originalen) | 1103 | 100% | 7.1 |
| Klar | 1035 | 99% | 6.7 |
| Telegramengelsk | 876 | 100% | 5.6 |
| Klar Kort, første versjon | 664 | 93% | 4.6 |
| Kort-200 | 185 | 39% | 3.0 |

## Per kategori

| Kategori | Klar | Telegramengelsk | Klar Kort, første versjon | Kort-200 |
|---|---:|---:|---:|---:|
| dialog | 100% | 100% | 97% | 44% |
| fakta | 100% | 100% | 98% | 42% |
| instruks | 100% | 100% | 89% | 47% |
| rapport | 98% | 100% | 92% | 34% |
| resonnement | 98% | 100% | 92% | 34% |

## Det Klar Kort, første versjon mistet (23 av 156 fakta under full score)

| Tekst | Faktum | Karakter |
|---|---|---:|
| instruks-02 | Do not use technical jargon. | 0.5 |
| instruks-03 | This applies when the user uploads a file. | 0.5 |
| instruks-04 | With anyone; this is an absolute rule. | 0.5 |
| instruks-05 | Cite sources for each factual claim. | 0.5 |
| instruks-09 | Before deleting any files. | 0.5 |
| instruks-10 | If you do not know something, say so. | 0.5 |
| rapport-01 | The writer ran the test suite. | 0.5 |
| rapport-02 | The failure was caused by an outdated cache. | 0.5 |
| rapport-07 | The writer could not reach the database server. | 0.5 |
| rapport-10 | There is a memory leak. | 0.5 |
| resonnement-03 | x is even. | 0.5 |
| resonnement-03 | x is greater than 2. | 0.5 |
| resonnement-03 | So x is not prime. | 0.5 |
| resonnement-05 | Speed matters more here. | 0.5 |
| resonnement-06 | With about 60% probability. | 0.5 |
| fakta-03 | Python was first released in 1991. | 0.5 |
| dialog-05 | The writer does not understand the error message. | 0.5 |
| tekst-instruks | Always answer in the customer's language. | 0.5 |
| tekst-instruks | If the tool returns an error, apologize. | 0.5 |
| tekst-rapport | The writer investigated failing checkout tests. | 0.5 |
| tekst-rapport | This is very likely the cause. | 0.5 |
| tekst-kodegjennomgang | The writer added that check to validate_card(). | 0.5 |
| tekst-kodegjennomgang | All tests in that file pass. | 0.5 |

## Det Kort-200 mistet (111 av 156 fakta under full score)

Tapt per tekst (summen av manglende poeng):

tekst-instruks 10, tekst-rapport 10, tekst-kodegjennomgang 9, tekst-resonnement 6, tekst-forskning 6, rapport-05 3, resonnement-05 3, dialog-02 3, instruks-05 2.5, instruks-10 2, rapport-01 2, rapport-04 2, resonnement-01 2, resonnement-02 2, resonnement-03 2, resonnement-08 2, instruks-03 1.5, instruks-07 1.5, rapport-03 1.5, rapport-07 1.5, rapport-09 1.5, resonnement-04 1.5, resonnement-06 1.5, fakta-01 1.5, fakta-03 1.5, fakta-04 1.5, dialog-05 1.5, dialog-06 1.5, instruks-02 1, rapport-06 1, rapport-08 1, fakta-02 1, dialog-01 1, dialog-03 1, dialog-04 1, instruks-06 0.5, instruks-08 0.5, instruks-09 0.5, rapport-02 0.5, rapport-10 0.5, resonnement-07 0.5

## Det Klar mistet (3 av 156 fakta under full score)

| Tekst | Faktum | Karakter |
|---|---|---:|
| rapport-01 | The writer ran the test suite. | 0.5 |
| rapport-08 | Update the dependencies. | 0.5 |
| resonnement-06 | With about 60% probability. | 0.5 |

## Det Telegramengelsk mistet (0 av 156 fakta under full score)

Ingenting.

