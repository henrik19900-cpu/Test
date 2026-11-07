"""Every grammatical word in Klar, its class and its meaning.

Klar has two kinds of words. Content words are open: any English word in its base form (``go``, ``child``,
``big``), plus names, numbers, labels and quoted text. Grammatical words are closed and listed here. This module
is the single source of truth: the lexer, the parser, the glosser, the linter, the docs tests and the
token count in ``bench/run.py`` all read it.

Every form here is one token in all eight tokenizers that ``bench/run.py`` measures.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Particle:
    form: str
    cls: str
    en: str
    no: str


def _group(cls: str, rows: list[tuple[str, str, str]]) -> dict[str, Particle]:
    return {form: Particle(form, cls, en, no) for form, en, no in rows}


# Predicate markers carrying time. Every predicate starts with one of these, a modal, or both.
TENSES = _group(
    "tense",
    [
        ("li", "present or timeless (is / does)", "nå eller alltid (er / gjør)"),
        ("pa", "past (was / did)", "fortid (var / gjorde)"),
        ("fu", "future (will)", "fremtid (skal / vil)"),
    ],
)

# Predicate markers carrying modality. Without a subject they are instructions to the addressee.
MODALS = _group(
    "modal",
    [
        ("must", "required", "må (krav)"),
        ("should", "recommended", "bør (anbefalt)"),
        ("may", "allowed, optional", "kan (har lov, valgfritt)"),
        ("can", "able, possible", "kan (er i stand til, mulig)"),
        ("would", "hypothetical", "ville (hypotetisk)"),
    ],
)

# Words between the marker and the head of a predicate.
ADVERBS = _group(
    "adverb",
    [
        ("not", "negation of what follows", "ikke"),
        ("never", "never", "aldri"),
        ("always", "always", "alltid"),
        ("often", "often", "ofte"),
        ("already", "already", "allerede"),
        ("yet", "yet (with not: not yet)", "ennå (not yet: ikke ennå)"),
        ("still", "still", "fortsatt"),
        ("again", "again", "igjen"),
        ("only", "only", "bare"),
        ("also", "also", "også"),
        ("very", "very", "veldig"),
        ("too", "too (excessively)", "for (altfor)"),
        ("more", "more (comparative)", "mer"),
        ("less", "less", "mindre"),
        ("most", "most (superlative)", "mest"),
    ],
)

# Marks a predicate that is a noun phrase: "Python li a programming language".
PREDICATE_NOMINAL = _group(
    "nominal", [("a", "is a kind of (predicate noun phrase)", "er en (substantivfrase)")]
)

# Sentence openers: where the information comes from.
EVIDENTIALS = _group(
    "evidential",
    [
        ("checked", "verified directly here (ran, read, measured)", "sjekket selv her (kjørt, lest, målt)"),
        ("so", "inferred from what was said (therefore)", "utledet av det som er sagt (altså)"),
        ("suppose", "assumption, not claimed as true", "antakelse, ikke påstand"),
    ],
)

# Sentence openers: how sure the writer is. A percentage ("90%") also works. No marker: confident (>= 90%).
CONFIDENCE = {
    "likely": (Particle("likely", "confidence", "likely (about 75%)", "sannsynlig (ca. 75 %)"), 0.75),
    "maybe": (Particle("maybe", "confidence", "maybe (about 50%)", "kanskje (ca. 50 %)"), 0.5),
    "unlikely": (Particle("unlikely", "confidence", "unlikely (about 25%)", "usannsynlig (ca. 25 %)"), 0.25),
}

# Sentence openers that link to the previous sentence.
DISCOURSE = _group(
    "discourse",
    [
        ("but", "contrast with the previous sentence", "men"),
        ("also", "addition to the previous sentence", "dessuten"),
        ("then", "next in time", "deretter"),
    ],
)

# Between clauses. "and" binds tighter than "or"/"xor", which bind tighter than the rest.
CONNECTIVES = _group(
    "connective",
    [
        ("and", "and", "og"),
        ("or", "inclusive or (one or both)", "eller (ett eller begge)"),
        ("xor", "exclusive or (exactly one)", "enten eller (nøyaktig ett)"),
        ("but", "but", "men"),
        ("so", "therefore", "så, derfor"),
        ("because", "because", "fordi"),
        ("iff", "if and only if", "hvis og bare hvis"),
    ],
)
AND_LEVEL = {"and"}
OR_LEVEL = {"or", "xor"}
LOW_LEVEL = {"but", "so", "because", "iff"}

# Introduce a subordinate clause, before (ending with "," or "then") or after the main clause.
SUBORDINATORS = _group(
    "subordinator",
    [
        ("if", "if", "hvis"),
        ("when", "when", "når"),
        ("unless", "unless", "med mindre"),
        ("until", "until", "til, inntil"),
        ("while", "while", "mens"),
        ("before", "before", "før"),
        ("after", "after", "etter at"),
        ("since", "since (time)", "siden (tid)"),
        ("where", "where (place)", "der, hvor"),
    ],
)

COMPLEMENTIZERS = _group(
    "complementizer",
    [
        ("that", "introduces a clause as object: say that ...", "at"),
        ("whether", "introduces a yes/no question as object", "om"),
    ],
)

RELATIVIZER = _group("relativizer", [("which", "after a noun: which/who/that (relative clause)", "som")])

QUESTION_WORDS = _group(
    "question",
    [
        ("what", "what", "hva"),
        ("who", "who", "hvem"),
        ("where", "where", "hvor"),
        ("when", "when", "når"),
        ("why", "why", "hvorfor"),
        ("how", "how", "hvordan"),
        ("which", "which (before a noun)", "hvilken"),
    ],
)
# Question words that can stand alone as a phrase ("which" needs a noun after it).
WH_PRONOUNS = {"what", "who", "where", "when", "why", "how"}

PRONOUNS = _group(
    "pronoun",
    [
        ("I", "speaker (also object: to I)", "jeg / meg"),
        ("you", "addressee", "du / deg"),
        ("we", "speaker and others", "vi / oss"),
        (
            "it",
            "the nearest earlier subject or object",
            "den / det / han / hun (nærmeste subjekt eller objekt)",
        ),
    ],
)

POSSESSIVES = _group(
    "possessive",
    [
        ("my", "my", "min"),
        ("your", "your", "din"),
        ("our", "our", "vår"),
        ("its", "its", "dens / dets"),
    ],
)

DETERMINERS = _group(
    "determiner",
    [
        ("all", "all", "alle"),
        ("each", "each", "hver"),
        ("some", "at least one", "minst én, noen"),
        ("no", "none", "ingen"),
        ("any", "any", "hvilken som helst"),
        ("many", "many", "mange"),
        ("few", "few", "få"),
        ("most", "most", "de fleste"),
        ("more", "more", "flere"),
        ("less", "less", "mindre"),
        ("this", "this (the one just mentioned)", "denne, dette"),
        ("which", "which (question)", "hvilken (spørsmål)"),
    ],
)

# Focus words allowed in front of a noun phrase: "only admin may delete file".
NP_FOCUS = {"only", "not"}

PREPOSITIONS = _group(
    "preposition",
    [
        ("of", "of (binds inside the noun phrase)", "av, til"),
        ("in", "in", "i"),
        ("on", "on", "på"),
        ("at", "at", "ved, på"),
        ("to", "to (goal, receiver, purpose)", "til, for å"),
        ("from", "from", "fra"),
        ("with", "with", "med"),
        ("without", "without", "uten"),
        ("by", "by (agent, means)", "av, ved hjelp av"),
        ("for", "for", "for"),
        ("about", "about (topic)", "om"),
        (
            "per",
            "per, for each; first in the sentence with comma: according to (source)",
            "per; først i setningen med komma: ifølge (kilde)",
        ),
        ("via", "via", "via"),
        ("than", "than (comparison)", "enn"),
        ("as", "as (in the role of)", "som (i rollen som)"),
        ("into", "into", "inn i"),
        ("over", "over", "over"),
        ("under", "under", "under"),
        ("between", "between", "mellom"),
        ("during", "during", "under, i løpet av"),
        ("since", "since (time)", "siden"),
        ("before", "before", "før"),
        ("after", "after", "etter"),
        ("until", "until", "til"),
        ("against", "against", "mot"),
        ("through", "through", "gjennom"),
        ("within", "within", "innen"),
        ("despite", "despite", "til tross for"),
        ("except", "except", "unntatt"),
        ("around", "around (place)", "rundt"),
        ("instead", "instead of", "i stedet for"),
        ("because", "because of (only as: because of)", "på grunn av"),
    ],
)

# Bare time and place words. They end a noun phrase and attach to the predicate, like a preposition phrase.
ADVERBIAL_WORDS = _group(
    "adverbial",
    [
        ("now", "now", "nå"),
        ("today", "today", "i dag"),
        ("yesterday", "yesterday", "i går"),
        ("tomorrow", "tomorrow", "i morgen"),
        ("soon", "soon", "snart"),
        ("later", "later", "senere"),
        ("here", "here", "her"),
        ("there", "there", "der"),
    ],
)

ANSWERS = _group("answer", [("yes", "yes", "ja"), ("no", "no", "nei")])

# Punctuation with a grammatical job.
PUNCTUATION = {
    ".": ("end of statement or instruction", "slutt på påstand eller instruks"),
    "?": ("end of question", "slutt på spørsmål"),
    ",": ("ends a fronted part: if ..., / in 2024,", "avslutter noe som står først: if ..., / in 2024,"),
    ":": ("after a claim label: P: ...", "etter navnet på en påstand: P: ..."),
    "=": ("definition or answer: K = ... / = F", "definisjon eller svar: K = ... / = F"),
    "(": ("start of a group", "start på gruppe"),
    ")": ("end of a group", "slutt på gruppe"),
}

PMARKS = {**TENSES, **MODALS}

# Every closed-class word. A lowercase word not in here is a content word.
ALL_FORMS: set[str] = set()
for _table in (
    TENSES,
    MODALS,
    ADVERBS,
    PREDICATE_NOMINAL,
    EVIDENTIALS,
    DISCOURSE,
    CONNECTIVES,
    SUBORDINATORS,
    COMPLEMENTIZERS,
    RELATIVIZER,
    QUESTION_WORDS,
    PRONOUNS,
    POSSESSIVES,
    DETERMINERS,
    PREPOSITIONS,
    ADVERBIAL_WORDS,
    ANSWERS,
):
    ALL_FORMS |= set(_table)
ALL_FORMS |= set(CONFIDENCE)

# Labels: one capital letter. "I" is the pronoun, so it is not a label.
LABEL_LETTERS = set("ABCDEFGHJKLMNOPQRSTUVWXYZ")

# English grammar words that Klar does not have, with what to write instead. The linter and the parser's
# error messages use these: they are the usual slips when a model drifts back into English.
ENGLISH_SLIPS: dict[str, str] = {
    "the": "Klar har ingen artikler: stryk «the».",
    "an": "Klar har ingen artikler: stryk «an».",
    "is": "Bruk markøren li (nå), pa (fortid) eller fu (fremtid); foran en substantivfrase: li a ...",
    "are": "Bruk li (nå), pa (fortid) eller fu (fremtid).",
    "am": "Bruk li.",
    "was": "Bruk pa.",
    "were": "Bruk pa.",
    "be": "Kopula finnes ikke: «must be ready» blir «must ready».",
    "been": "Bruk pa (fortid).",
    "being": "Bruk li.",
    "will": "Bruk fu for fremtid (eller must for krav).",
    "shall": "Bruk must eller fu.",
    "did": "Bruk pa.",
    "does": "Bruk li.",
    "has": "Bruk pa (ferdig) eller li have (eier).",
    "had": "Bruk pa.",
    "could": "Bruk pa can (kunne) eller maybe/would.",
    "might": "Bruk maybe ... (ca. 50 %).",
    "he": "Bruk it, et navn eller en etikett (U).",
    "she": "Bruk it, et navn eller en etikett (U).",
    "they": "Bruk it, et navn eller en etikett (U).",
    "them": "Bruk it eller en etikett.",
    "their": "Bruk its eller «of U».",
    "his": "Bruk its eller «of U».",
    "her": "Bruk its eller «of U».",
    "him": "Bruk it eller en etikett.",
    "me": "Klar har ikke kasus: skriv I (to I).",
    "us": "Klar har ikke kasus: skriv we.",
    "these": "Bruk this.",
    "those": "Bruk this eller en etikett.",
    "every": "Bruk each eller all.",
}


def meaning(form: str) -> Particle | None:
    """The particle for a form, preferring the class most often meant out of context."""
    for table in (
        TENSES,
        MODALS,
        EVIDENTIALS,
        PREDICATE_NOMINAL,
        PRONOUNS,
        POSSESSIVES,
        ADVERBS,
        COMPLEMENTIZERS,
        SUBORDINATORS,
        CONNECTIVES,
        DETERMINERS,
        RELATIVIZER,
        QUESTION_WORDS,
        PREPOSITIONS,
        ADVERBIAL_WORDS,
        DISCOURSE,
        ANSWERS,
    ):
        if form in table:
            return table[form]
    if form in CONFIDENCE:
        return CONFIDENCE[form][0]
    return None
