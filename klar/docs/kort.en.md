# Klar Kort — compressed notes between models

Klar Kort is the shortest way to pass facts, instructions and reports to another model while keeping every fact. Write only what the reader cannot rebuild; the reader expands it to full English.

## Writing
- Content words only. Leave out the/a/is/are/was/will/do, filler, politeness, and obvious pronouns (I in reports, you in instructions). Normal English word forms: failed, tests, cheaper.
- A statement that starts with a verb is an instruction (required). Weaker: `should` (recommended), `may` (allowed). Bans: `no X`, `never X`.
- Source first: `checked` verified here · `so` inferred · `suppose` assumed · `per X:` according to X. None: stated as known.
- Certainty first: `likely` ≈75% · `maybe` ≈50% · `unlikely` ≈25% · or `60%`. None: confident.
- `:` is, has, consists of (`Oslo: capital Norway`). `→` if/then, leads to, therefore (`file uploaded → read all`). `=` equals. `+` and. `~` about. `<` `>` `≤` `≥` compare. `min` `max` at least, at most.
- Keep every number, name, condition (unless, until, before, only) and negation exactly.
- A capital letter after a noun names it for later: `file F … F`.
- Separate statements with `.`; the last one needs none. `?` asks.

## Reading
Expand each statement into complete English: restore articles, verbs, tense and the obvious subject, and keep source and certainty. Never add facts.

## Example
English: I ran the tests: 41 passed and 1 failed. The failure was probably caused by an old cache, so you should clear it.
Kort: `checked tests: 41 pass, 1 fail. likely cause: old cache → should clear it`
