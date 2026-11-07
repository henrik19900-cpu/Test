# Klar Kort — compressed notes between models

Klar Kort is the shortest way to pass facts, instructions and reports to another model while keeping every fact. Write only what the reader cannot rebuild; the reader expands it to full English.

## Writing
- Content words only. Leave out the/a/is/are/was/will/do, filler, politeness, and obvious pronouns (I in reports, you in instructions). Normal English word forms: failed, tests, cheaper.
- A statement that starts with a verb in base form is an instruction (required). Weaker: `should` (recommended), `may` (allowed). Bans: `no X`, `never X`. A past-tense verb reports what the writer did: `ran tests`, `couldn't reach server`.
- Source first: `checked` verified here · `so` inferred · `suppose` assumed · `per X:` according to X. None: stated as known.
- Certainty first: `likely` ≈75% · `maybe` ≈50% · `unlikely` ≈25% · or `60%`. None: confident.
- `:` is, has, consists of (`Oslo: capital Norway`). `→` if/when … then, leads to, changes to (`user uploads file → read all`, `timeout 30s → 5s`). `so` therefore, a conclusion about what was just said (`x even, >2, so not prime`). `=` equals. `+` and. `~` about. `<` `>` `≤` `≥` compare. `min` `max` at least, at most.
- Keep every number, name, condition (unless, until, before, only), negation and qualifier (any, all, first, about, technical, here) exactly. Keep who did something when it is not the writer.
- A capital letter after a noun names it for later: `file F … F`.
- Separate statements with `.`; the last one needs none. `?` asks.

## Reading
Expand each statement into complete English: restore articles, verbs, tense and the obvious subject, and keep source and certainty. Never add facts.

## Example
English: I ran the tests: 41 passed and 1 failed. The failure was probably caused by an old cache, so you should clear it.
Kort: `ran tests: 41 pass, 1 fail. failure likely caused by old cache, so should clear it`
