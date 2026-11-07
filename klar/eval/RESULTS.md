# Læringstest: kan en modell lære Klar av primeren alene?

Generert av `python eval/score.py`. Metode og vurdering står i [README.md](README.md). Hver modell fikk bare primeren og oppgavene, uten verktøy og uten tilgang til repoet. Råsvarene ligger i `round*/answers/`.

## Oppsummering

| Runde | Modell | Forstå Klar | Skrive gyldig Klar | Riktige grammatiske trekk | Riktig betydning |
|---|---|---:|---:|---:|---:|
| 1 | haiku | 12 av 12 | 11 av 12 | 10 av 12 | 11 av 12 |
| 1 | sonnet | 11.5 av 12 | 10 av 12 | 10 av 12 | 11 av 12 |
| 1 | opus | 12 av 12 | 12 av 12 | 12 av 12 | 12 av 12 |
| 2 | haiku | 6 av 6 | 16 av 16 | 15 av 16 | 15 av 16 |
| 2 | sonnet | 6 av 6 | 16 av 16 | 16 av 16 | 15.5 av 16 |
| 2 | opus | 6 av 6 | 16 av 16 | 16 av 16 | 16 av 16 |

## Runde 1: primeren slik den først ble skrevet

Oppgavene og fasit: [round1/items.yaml](round1/items.yaml). Prompt: [round1/prompt.txt](round1/prompt.txt).

### Klar → engelsk (poeng satt for hånd)

| Oppgave | Klar | haiku | sonnet | opus |
|---|---|---|---|---|
| A1 | `checked 3 of 50 user pa not receive email yesterday.` | 1 | 1 | 1 |
| A2 | `suppose server li overload. then maybe request fu fail.` | 1 | 1 | 1 |
| A3 | `must not delete log unless user pa ask for it.` | 1 | 1 | 1 |
| A4 | `file A li bigger than file B. so likely A pa cause error.` | 1 | 0.5: formuleringen kaller «A er større enn B» utledet; det er sagt som kjent, bare den andre setningen er utledet | 1 |
| A5 | `user pa hit man with stick.` | 1 | 1 | 1 |
| A6 | `user pa hit (man with stick).` | 1 | 1 | 1 |
| A7 | `all agent pa read some report.` | 1 | 1 | 1 |
| A8 | `per log, job pa stop at 03:00. checked job li not run now.` | 1 | 1 | 1 |
| A9 | `customer C pa order book B. C li ask when B fu arrive.` | 1 | 1 | 1 |
| A10 | `you may skip test but must not skip review.` | 1 | 1 | 1 |
| A11 | `file which user pa upload yesterday li corrupt.` | 1 | 1 | 1 |
| A12 | `unlikely bug li in parser. 80% bug li in lexer.` | 1 | 1 | 1 |

### Engelsk → Klar

Gyldig og trekk: sjekket av parseren. Betydning: satt for hånd.

**haiku**

| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |
|---|---|---|---|---|---|
| B1 | I checked: the backup finished at 02:00. | `checked backup pa finish at 02:00.` | ja | OK | 1 |
| B2 | You must never log passwords. | `must not log passwords.` | ja | adverbs: ville ha ['never'], fikk ['not'] | 1: «not» i stedet for «never»; samme forbud |
| B3 | The tests will probably pass after the fix. | `likely tests fu pass after fix.` | ja | OK | 1 |
| B4 | Assume the cache is empty. Then the first request is slow. | `suppose cache li empty. then first request li slow.` | ja | OK | 1 |
| B5 | According to the manual, the limit is 10 GB per user. | `per manual, limit li 10GB per user.` | ja | OK | 1 |
| B6 | Ask the user whether the file is still needed. | `must ask user whether file li still need.` | ja | OK | 0.5: «li still need» leses som at filen trenger noe; riktig er «li still necessary» |
| B7 | The user who reported the bug is from Oslo. | `user which pa report bug li from Oslo.` | ja | OK | 1 |
| B8 | If the build fails, notify the team and do not deploy. | `if build li fail, must notify team and must not deploy.` | ja | OK | 1 |
| B9 | I saw the man who had the binoculars. | `I pa see man which pa have binoculars.` | ja | OK | 1: relativsetning i stedet for parentes; like riktig |
| B10 | Each server sent a report to the admin. | `each server pa send some report to admin.` | ja | OK | 1 |
| B11 | Does the service run on port 8080? | `service li run on port 8080?` | ja | OK | 1 |
| B12 | I think the bug is probably in the parser, but I have not checked. | `suppose likely bug li in parser, but I pa not yet check.` | **nei**: komma brukes bare etter noe som står først (if ..., / in 2024,); skriv «but»/«and» uten komma, eller avslutt setningen med punktum | – | 0.5: «suppose» betyr antakelse, ikke «jeg tror»; komma før «but» er ikke Klar |

**sonnet**

| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |
|---|---|---|---|---|---|
| B1 | I checked: the backup finished at 02:00. | `checked I pa finish backup at 02:00.` | ja | OK | 0.5: «I pa finish backup» sier at jeg fullførte backupen; i originalen ble backupen ferdig av seg selv |
| B2 | You must never log passwords. | `you must never log password.` | ja | OK | 1 |
| B3 | The tests will probably pass after the fix. | `likely test fu pass after fix.` | ja | OK | 1 |
| B4 | Assume the cache is empty. Then the first request is slow. | `suppose cache li empty. then first request li slow.` | ja | OK | 1 |
| B5 | According to the manual, the limit is 10 GB per user. | `per manual, limit li 10GB per user.` | ja | OK | 1 |
| B6 | Ask the user whether the file is still needed. | `must ask user whether file still li needed.` | **nei**: «still» står mellom markøren og hovedordet: li still ..., ikke still li ... | – | 1: riktig betydning, men adverbet står foran markøren («still li»), så setningen er ugyldig |
| B7 | The user who reported the bug is from Oslo. | `user which pa report bug li from Oslo.` | ja | OK | 1 |
| B8 | If the build fails, notify the team and do not deploy. | `if build pa fail, must notify team and must not deploy.` | ja | OK | 1: «pa fail» (har feilet) i stedet for «li fail»; tåler begge lesninger |
| B9 | I saw the man who had the binoculars. | `I pa see man which pa have binoculars.` | ja | OK | 1: relativsetning i stedet for parentes; like riktig |
| B10 | Each server sent a report to the admin. | `each server pa send report to admin.` | ja | OK | 1 |
| B11 | Does the service run on port 8080? | `service li run on port 8080?` | ja | OK | 1 |
| B12 | I think the bug is probably in the parser, but I have not checked. | `suppose likely bug li in parser, but I pa not check.` | **nei**: komma brukes bare etter noe som står først (if ..., / in 2024,); skriv «but»/«and» uten komma, eller avslutt setningen med punktum | – | 0.5: «suppose» betyr antakelse, ikke «jeg tror»; komma før «but» er ikke Klar |

**opus**

| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |
|---|---|---|---|---|---|
| B1 | I checked: the backup finished at 02:00. | `checked backup pa finish at 02:00.` | ja | OK | 1 |
| B2 | You must never log passwords. | `you must never log passwords.` | ja | OK | 1 |
| B3 | The tests will probably pass after the fix. | `likely tests fu pass after fix.` | ja | OK | 1 |
| B4 | Assume the cache is empty. Then the first request is slow. | `suppose cache li empty. then first request li slow.` | ja | OK | 1 |
| B5 | According to the manual, the limit is 10 GB per user. | `per manual, limit li 10GB per user.` | ja | OK | 1 |
| B6 | Ask the user whether the file is still needed. | `must ask user whether file li still necessary.` | ja | OK | 1 |
| B7 | The user who reported the bug is from Oslo. | `user which pa report bug li from Oslo.` | ja | OK | 1 |
| B8 | If the build fails, notify the team and do not deploy. | `if build li fail, must notify team and must not deploy.` | ja | OK | 1 |
| B9 | I saw the man who had the binoculars. | `I pa see man which pa have binoculars.` | ja | OK | 1: relativsetning i stedet for parentes; like riktig |
| B10 | Each server sent a report to the admin. | `each server pa send report to admin.` | ja | OK | 1 |
| B11 | Does the service run on port 8080? | `service li run on port 8080?` | ja | OK | 1 |
| B12 | I think the bug is probably in the parser, but I have not checked. | `likely bug li in parser. I pa not check this.` | ja | OK | 1 |

## Runde 2: nye setninger, primeren rettet etter feilene i runde 1

Oppgavene og fasit: [round2/items.yaml](round2/items.yaml). Prompt: [round2/prompt.txt](round2/prompt.txt).

### Klar → engelsk (poeng satt for hånd)

| Oppgave | Klar | haiku | sonnet | opus |
|---|---|---|---|---|
| D1 | `script pa delete file and it pa crash.` | 1 | 1: følger regelen (it = file) og nevner at engelsk ville lest det annerledes | 1 |
| D2 | `user pa open file and admin pa close it.` | 1 | 1 | 1 |
| D3 | `server A xor server B must active.` | 1 | 1 | 1 |
| D4 | `not all test pa pass.` | 1 | 1 | 1 |
| D5 | `all agent pa not read report.` | 1 | 1 | 1 |
| D6 | `per monitor, CPU li 95% since 10:00. so likely job J li stuck. must restart J if J li still stuck at 11:00.` | 1 | 1 | 1 |

### Engelsk → Klar

Gyldig og trekk: sjekket av parseren. Betydning: satt for hånd.

**haiku**

| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |
|---|---|---|---|---|---|
| C1 | I think the migration will probably finish tonight, but I'm not sure. | `likely migration fu finish later today but I li not sure.` | ja | OK | 1: «tonight» ble «later today»; «but I li not sure» er overflødig, men riktig |
| C2 | Open the config file, change the port to 8080 and restart the server. | `must open config file then change port to 8080 then restart server.` | ja | OK | 1 |
| C3 | The report was written by the analytics team. | `report pa write by analytics team.` | ja | OK | 0.5: «report pa write» gjør rapporten til den som skriver; passiv skrives uten subjekt: «pa write report by analytics team» |
| C4 | Do not merge the branch until all checks pass. | `must not merge branch until all checks li pass.` | ja | OK | 1 |
| C5 | The function that parses dates is still slow. | `function which li parse dates li still slow.` | ja | OK | 1 |
| C6 | We tested the backup: it works, but a restore takes three hours. | `we pa test backup. it li work but restore li take 3h.` | ja | evidential: ville ha checked, fikk None | 1: uten «checked», men «we pa test backup» sier det samme |
| C7 | According to the vendor, the new version fixes the memory leak. | `per vendor, new version li fix memory leak.` | ja | OK | 1 |
| C8 | If the user is an admin or the file is public, show the file. | `if user li admin or file li public, must show file.` | ja | OK | 1 |
| C9 | Exactly one of the two servers must be active. | `server A xor server B must active.` | ja | OK | 1 |
| C10 | Tell the customer that the package was delayed because of the storm. | `must tell customer that package pa delay because of storm.` | ja | OK | 1 |
| C11 | Each user may upload at most 3 files per day. | `each user may upload max 3 files per day.` | ja | OK | 1 |
| C12 | Who changed the configuration yesterday? | `who pa change configuration yesterday?` | ja | OK | 1 |
| C13 | I am 90% sure that the cache is the problem. | `90% I li sure that cache li problem.` | ja | OK | 1: dobbelt opp («90%» og «I li sure»), men riktig |
| C14 | Suppose the API is down. What should the app do? | `suppose API li down. app should do what?` | ja | OK | 1 |
| C15 | The script deleted the file and then it crashed. | `script pa delete file and it pa crash.` | ja | OK | 0.5: «and it pa crash» betyr etter regelen at filen krasjet; mente skriptet. Sjekkeren advarer nå mot nettopp dette (versjon 1.1) |
| C16 | Only admins can see this page. | `only admins can see this page.` | ja | OK | 1 |

**sonnet**

| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |
|---|---|---|---|---|---|
| C1 | I think the migration will probably finish tonight, but I'm not sure. | `likely migration fu finish today.` | ja | OK | 0.5: «tonight» ble «today» |
| C2 | Open the config file, change the port to 8080 and restart the server. | `must open config file then change port to 8080 then restart server.` | ja | OK | 1 |
| C3 | The report was written by the analytics team. | `pa write report by analytics team.` | ja | OK | 1 |
| C4 | Do not merge the branch until all checks pass. | `must not merge branch until all check li pass.` | ja | OK | 1 |
| C5 | The function that parses dates is still slow. | `function which li parse date li still slow.` | ja | OK | 1 |
| C6 | We tested the backup: it works, but a restore takes three hours. | `we pa test backup. checked it li work but restore li take 3h.` | ja | OK | 1 |
| C7 | According to the vendor, the new version fixes the memory leak. | `per vendor, new version li fix memory leak.` | ja | OK | 1 |
| C8 | If the user is an admin or the file is public, show the file. | `if user li admin or file li public, must show file.` | ja | OK | 1 |
| C9 | Exactly one of the two servers must be active. | `server A xor server B must active.` | ja | OK | 1 |
| C10 | Tell the customer that the package was delayed because of the storm. | `must tell customer that package pa delay because of storm.` | ja | OK | 1: «package pa delay» i stedet for passiv uten subjekt; forstås likevel |
| C11 | Each user may upload at most 3 files per day. | `each user may upload max 3 file per day.` | ja | OK | 1 |
| C12 | Who changed the configuration yesterday? | `who pa change configuration yesterday?` | ja | OK | 1 |
| C13 | I am 90% sure that the cache is the problem. | `90% cache li problem.` | ja | OK | 1 |
| C14 | Suppose the API is down. What should the app do? | `suppose API li down. app should do what?` | ja | OK | 1 |
| C15 | The script deleted the file and then it crashed. | `script pa delete file then crash.` | ja | OK | 1 |
| C16 | Only admins can see this page. | `only admin can see this page.` | ja | OK | 1 |

**opus**

| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |
|---|---|---|---|---|---|
| C1 | I think the migration will probably finish tonight, but I'm not sure. | `likely migration fu finish today at night.` | ja | OK | 1 |
| C2 | Open the config file, change the port to 8080 and restart the server. | `must open config file then change port to 8080 then restart server.` | ja | OK | 1 |
| C3 | The report was written by the analytics team. | `analytics team pa write report.` | ja | OK | 1 |
| C4 | Do not merge the branch until all checks pass. | `until all check li pass, must not merge branch.` | ja | OK | 1 |
| C5 | The function that parses dates is still slow. | `function which li parse dates li still slow.` | ja | OK | 1 |
| C6 | We tested the backup: it works, but a restore takes three hours. | `checked backup li work but restore li take 3h.` | ja | OK | 1 |
| C7 | According to the vendor, the new version fixes the memory leak. | `per vendor, new version li fix memory leak.` | ja | OK | 1 |
| C8 | If the user is an admin or the file is public, show the file. | `if user li admin or file li public, must show file.` | ja | OK | 1 |
| C9 | Exactly one of the two servers must be active. | `server A xor server B must active.` | ja | OK | 1 |
| C10 | Tell the customer that the package was delayed because of the storm. | `must tell customer that pa delay package because of storm.` | ja | OK | 1 |
| C11 | Each user may upload at most 3 files per day. | `each user may upload max 3 file per day.` | ja | OK | 1 |
| C12 | Who changed the configuration yesterday? | `who pa change configuration yesterday?` | ja | OK | 1 |
| C13 | I am 90% sure that the cache is the problem. | `90% cache li problem.` | ja | OK | 1 |
| C14 | Suppose the API is down. What should the app do? | `suppose API li down. app should do what?` | ja | OK | 1 |
| C15 | The script deleted the file and then it crashed. | `script pa delete file then crash.` | ja | OK | 1 |
| C16 | Only admins can see this page. | `only admin can see this page.` | ja | OK | 1 |

