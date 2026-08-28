"""The search box's language: parsed here, and parsed again in the browser.

`tag:gpu and tag:distributed` is the query the dropdowns cannot express, because
a menu means OR within a field — two cycles selected means either, since a
record has one cycle and "both" is empty by construction. For `tags`,
`assignees` and `reviewers` "both" is a real question, and this is where it is
asked.

**Two implementations, on purpose, and only one of them can be avoided.** The
static export has no server to ask and the table filters without one, so the
language has to run in Python and in JavaScript; `_FILTER_JS` in `render.py`
holds the second copy. `tests/test_search.py` pins them together over a corpus
of queries by *results* rather than by source, which is the only claim worth
making about two parsers.

Three rules this file exists to keep:

* **A malformed query says so and matches nothing.** Matching everything is a
  table that looks like it answered; matching nothing silently is a table that
  looks broken. `parse` raises `QueryError` with a sentence, and the caller
  shows it.
* **An unknown field matches nothing**, and is not an error. That is the rule
  `apply_filters` already had — filter state comes from a hand-editable query
  string, and a typo that silently widens a result set is worse than one that
  visibly empties it. `onwer:jcanton` is a question about a field this plan has
  not got, and the honest answer to it is "nothing", drawn beside a box that
  still says what was typed.
* **The sentinel is not spelled here.** `(none)` is `index.NO_VALUE` and reaches
  `evaluate` as an argument, because the menus and the language have to agree
  about what empty is called and two spellings is how that agreement ends.

The grammar, smallest first:

    or     := and ( 'or' and )*
    and    := unary ( 'and'? unary )*        # adjacency is AND
    unary  := 'not' unary | '(' or ')' | term
    term   := field ':' value | word

Adjacency is AND because that is what every search box a person has used does
with two words. `not` binds tightest, then `and`, then `or` — the order every
language that has these three uses, and the one that makes
`kind:task and not status:done` mean what it looks like.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A field asked for by the name a person would say rather than the name the model
# uses. Written the way it is read: `tag:gpu`, not `tags:gpu`.
ALIASES = {
    "tag": "tags",
    "assignee": "assignees",
    "reviewer": "reviewers",
    "pr": "prs",
    "person": "owner",
}

# Fields whose values are free text, matched by `found` below. Everything else is
# a vocabulary — a status, a login, a tag, a cycle number — and is matched whole,
# because `cycle:3` must not answer for cycle 30 and `status:done` must not be a
# way of writing "any status containing done". Whole, but not raw: since
# 2026-08-28 both sides of that comparison are `plain`ed first, so `tag:bedheat`
# and `tag:bed-heat` are one question. See `evaluate`'s last branch.
#
# A title is a sentence and nobody types a whole one. A PR reference is written
# three ways in the same review — `1364`, `#1364`, `C2SM/icon4py#1364` — and the
# person searching has whichever of them is in front of them. Which is also why
# the separators inside one stop counting: `#`, `/`, `_` and `-` are how a
# reference and an id are *punctuated*, and a person retyping one from memory
# gets the letters right and the punctuation wrong.
FREE_TEXT = ("title", "prs")


# --------------------------------------------------------------------------- #
# Matching a needle against text
# --------------------------------------------------------------------------- #
#
# All four of these are spelled twice — here, and in the shell's script
# (`shell.py`, immediately after `esc`) for the browser. Character for character
# the same walk, in the same order, with the same early exits, because
# `test_the_two_matchers_agree_letter_for_letter` compares them by their answers
# over every corpus pair and a hand-written adversarial list.
#
# `plain` normalises a haystack, `sought` normalises a needle, `found` ranks one
# against the other, and `bare` is the rule a bare word is answered by: the two
# tiers read two different haystacks, and it is the only one of the four that
# knows that.


def plain(text: str) -> str:
    """Lowered, with everything that is not a letter or a digit deleted.

    `some_cool_title` is `somecooltitle`, and so is `Some Cool Title` and
    `some-cool-title`: the separators are how somebody punctuates a name, and
    they are the half of the ask that cannot be had any other way — jcanton,
    2026-08-28, asked for `some cool` to find `some_cool_title`.

    **ASCII, deliberately, and it is `found` that decides that.** Keeping the
    letters neither language classifies would put astral characters back in the
    haystack, and `found` walks a string by index: Python counts code points and
    JavaScript counts UTF-16 code units, so one skipped emoji costs the gap
    counter 1 here and 2 there. `abcd` against `a😀😀bcd` is a subsequence in
    Python and not in the browser, in silence, with every existing test green —
    which is this repository's own oldest two-language failure, and the reason
    `byte_offset` exists in `coedit.py`. Deleting them removes the whole class.

    What it costs, and it is a real cost: a value with no ASCII letter in it
    plains to nothing and drops out of the blob, so a tag written `焙煎` is no
    longer findable by typing it — on either side, which is why nothing goes
    red. Accented Latin survives, because the letters around the accent do:
    `Söderberg` plains to `sderberg` and still finds itself, while `Soderberg`
    finds nothing, exactly as before this. Anybody reopening that is reopening
    the paragraph above with it.
    """
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def sought(text: str) -> str:
    """`plain`, on the needle side, where a truncation has to become nothing.

    `plain` is right for a haystack and half-right for a needle: it is a
    *deletion*, and deleting from something short enough leaves a stub that is
    still a legal needle and answers far more of a plan than what was typed.
    Measured over `seed/` on 2026-08-28, before this existed: `C++` plained to
    `c` and kept 27 of the 28 planned rows, `c#` the same, `Δt` plained to `t`
    and kept all 28, `I/O` plained to `io` and kept 10. Negated they were no
    better and no steadier: `not C++` and `not c#` left one row each, `not Δt`
    left NOTHING at all, and `not I/O` left 18 — three different wrong answers
    to one shape of typo. None of them said anything beside the box, because all
    four parse perfectly.

    So: nothing survives a truncation that leaves fewer than three characters.
    Both halves of that are load-bearing.

    * **Fewer than three**, so that a stub cannot be a needle. What punctuation
      leaves behind is short, and short answers far more than it was asked to:
      `c` out of `C++` kept 27 of the 28 rows and `io` out of `I/O` kept 10.
      Three is where a deliberate short word — `ci`, `mpi`, `f2py` — stops being
      distinguishable from what is left of `C++`, and short words are only kept
      at all when nothing was dropped.
    * **AND something was dropped**, so that a word typed with no punctuation in
      it is never touched. `ci` is two characters and `plain` leaves it alone, so
      it goes on finding the tag `ci`; `c#` is two characters because `plain` ate
      one, and it finds nothing.

    `some.cool` (`somecool`) and `2-gpu` (`2gpu`) lose punctuation and keep far
    more than three, so they are exactly what they were. `#`, `---` and `/`
    already plained to nothing and keep the ruling they already had.

    "Something was dropped" is asked as `kept != lowered` rather than by counting
    characters, on purpose: `plain` only ever deletes, so the two are the same
    question, and a length comparison would be the one thing this pair must never
    do across two languages — Python counts code points where JavaScript counts
    UTF-16 units, which is the divergence `plain`'s own docstring exists to close.
    """
    lowered = text.lower()
    kept = plain(lowered)
    return "" if len(kept) < 3 and kept != lowered else kept


def found(needle: str, hay: str) -> int:
    """0 for no match, 1 for a substring, 2 for a subsequence.

    Truthy wherever a yes-or-no is wanted, which is everywhere but the two capped
    completion lists in `controls.py` — those show eight of what they find, so a
    weak match can evict a strong one and they sort by this number. A rank rather
    than a bool is also what the parity test compares, so the two halves have to
    agree about *how* a row matched and not only that it did.

    Both arguments are already `plain`ed. Greedy, leftmost, and no backtracking
    within a start: it can refuse a match a backtracking matcher would find, and
    the point is that both languages refuse the same ones.
    """
    # A term with nothing searchable left in it matches nothing, for the same
    # reason an unknown field does: a query that widens by accident is worse than
    # one that visibly empties. A stray `#` must not answer the plan.
    if not needle:
        return 0
    # The needle carries no space, so a substring can never cross a value.
    if needle in hay:
        return 1
    # Under four characters there is no subsequence tier at all. Four is `smcl`
    # — the shortest example jcanton gave, so it is the highest floor his ask
    # survives — and the floor was RE-MEASURED against the narrowed haystack on
    # 2026-08-28, after `bare` split the tiers, because the number it was first
    # set from had been taken against the whole blob.
    #
    # What a floor of 3 would cost, over every three-letter needle the corpus
    # offers (initials of multi-word titles, every three-character window of an
    # id or a title, and every three-letter word of one), counted as rows the
    # loose tier ADDS over the substring tier: `seed/` 404 needles, worst `a00`
    # +16 of 28 rows and `ith` +14; `tests/fixtures/corpus` 628 needles, worst
    # `ete` +11 of 26 and `ith` +9. Median 0 and 90th percentile 3 on both, but
    # 37% and 42% of those needles add at least one row, and 2.2% and 3.3% of
    # them add more than a fifth of the plan — the ceiling
    # `test_a_shaping_document_is_still_not_an_index` holds the tier to. A floor
    # of 2 is worse in the same direction: worst `ot` +17 of 28 and `ts` +16 of
    # 26, median 1, and 8.6% and 8.0% of needles over that fifth.
    #
    # And it would buy nothing, which is the half that settles it. `s_c_t` was
    # the spelling offered for `some_cool_title`, and it is refused by the GAP
    # rule below and not by this floor: `sct` in `somecooltitle` skips `o`, `m`,
    # `e` between the `s` and the `c`, three in a row, at every floor including
    # 2. Across both corpora nine titles are three words long and one of them is
    # found by its own initials at a floor of 3. So the loose tier reads four
    # characters or more, and a needle shorter than that is a substring or
    # nothing.
    if len(needle) < 4:
        return 0
    # An all-digit needle never takes the subsequence tier. A number is copied
    # off a screen rather than remembered, so it is typed right or not at all,
    # and read loosely it is catastrophic: `1364` is a subsequence of
    # `c2smicon4py1234564`, so `?q=1364` kept a record whose only pull request is
    # #1234564. The widening was asked for so that `1364`, `#1364` and
    # `C2SM/icon4py#1364` would all find the same record; separator-blindness and
    # the substring tier above already do that, and this tier adds nothing to a
    # reference but wrong answers.
    if re.fullmatch(r"[0-9]+", needle):
        return 0
    for start in range(len(hay)):
        if hay[start] != needle[0]:
            continue
        at, skipped = 1, 0
        for i in range(start + 1, len(hay)):
            if hay[i] == " ":
                break  # a value ended; a match may not cross into the next
            if hay[i] == needle[at]:
                at += 1
                skipped = 0
                if at == len(needle):
                    return 2
            else:
                skipped += 1
                if skipped > 2:
                    break  # never skip more than two letters in a row
    return 0


def bare(needle: str, wide: str, narrow: str) -> int:
    """How a bare word meets one record. The two tiers read different haystacks.

    `wide` is `searchable`'s blob — everything a record is known by, id and title
    and tags and pull requests and every person on it. `narrow` is `nameable`'s:
    the id and the title, and nothing else. A substring is looked for in the
    first, a subsequence only in the second.

    **The split is the whole point.** The ask was about a title — jcanton,
    2026-08-28: "if a record has title some_cool_title it shows up even when
    searching some cool" — and a subsequence let loose on the rest of the blob
    stops answering it. Measured over `seed/` (28 planned rows) before this
    split: typing `operator` gave 27, 19, 5, **19**, 5, 5, 5, 5 rows as the eight
    characters went in. The list QUADRUPLED on the fourth character and collapsed
    on the fifth. All 14 of the rows it gained on `oper` were subsequences, and
    13 of them matched nothing at all but the reviewer login `hoopoegrove` — o,
    p, e, r with a letter skipped between each; the fourteenth matched only the
    word `compiler` the same way. `oere` kept 18 of 28 like that. A result list
    that grows as you type it is not a result list; it is noise that happens to
    be sorted.

    **What that fixed, and how far the fix reaches.** The same eight keystrokes
    now give 27, 19, 5, 5, 5, 5, 5, 5 over `seed/` and `oere` keeps 4 — the list
    never grows. Over `tests/fixtures/corpus` (26 planned rows) they give 26, 5,
    4, **5**, 4, 4, 4, 4, so the claim is "monotone on the demo plan, one row of
    wobble on the frozen corpus" and not "monotone". The wobbling row is
    `task-5a4e39`, "Read the 2014 stable-summation paper": `oper` is a
    subsequence of `readthe2014stablesummationpaper` — its tail reads
    `o n p a p e r`, so o, then p over `n`, then e over `ap`, then r, every gap
    inside the two the walk allows — and `opera` drops it again. Narrowing the
    haystack to a name cannot remove this, because a name is still a sentence:
    the split makes the loose tier rare rather than impossible, and a test that
    pinned monotonicity over one corpus would be pinning that corpus.

    A login, a tag and a pull request are all things a person types EXACTLY —
    they are copied off a screen — so the substring tier already serves them and
    the second tier only costs them. A title is the one field nobody retypes
    whole, and an id is punctuated, which is why those two and no others.
    """
    if not needle:
        return 0
    if needle in wide:
        return 1
    # `narrow` is `wide`'s id and title chunks and nothing more, so a substring
    # of it was already a substring of `wide` and was answered above. Only the
    # subsequence rank can be new here, and taking only that keeps the ranks
    # meaning what `found`'s docstring says they mean.
    return 2 if found(needle, narrow) == 2 else 0


class QueryError(ValueError):
    """A query that cannot be read, with the sentence the reader is shown."""


@dataclass(frozen=True)
class Word:
    """A bare word, looked for in the record's searchable text by `found`.

    Not a substring of it any more: the text and the word are both `plain`ed, so
    `some-cool` and `somecool` find `some_cool_title`, and `smcl` does too.
    """

    text: str


@dataclass(frozen=True)
class Field:
    """`field:value`, where the field may be one this plan has not got."""

    name: str
    value: str


@dataclass(frozen=True)
class Not:
    of: object


@dataclass(frozen=True)
class Both:
    left: object
    right: object


@dataclass(frozen=True)
class Either:
    left: object
    right: object


# `object` on the three above rather than the union: the union is not a name yet
# while they are being defined, and a string annotation that ruff unquotes is a
# forward reference this file does not need — nothing here is validated by
# pydantic, and `evaluate` dispatches on the class it actually has.
Node = Word | Field | Not | Both | Either


# --------------------------------------------------------------------------- #
# Reading the text
# --------------------------------------------------------------------------- #


# Every character that separates one term from the next, written out rather than
# left to `str.isspace()` here and `/\s/` in `queryTerms` (`controls.py`). Those
# two disagree in BOTH directions and always have: `str.isspace()` is true for
# U+0085 and U+001C–U+001F and false for U+FEFF, and `/\s/` is the exact reverse
# on all four. The disagreement was harmless while a bare word was a substring —
# `\ufeffsmcl` was a word neither side found — and stopped being harmless when
# `found` started matching where `includes` did not: paste a query out of a
# spreadsheet cell that carries a byte-order mark and `"\ufefftitle:smcl"` is a
# field query in the browser and a bare word in Python, so the link and the box
# answer differently for a character nobody can see.
#
# The union of the two, so no input that used to split stops splitting. Splitting
# more can only narrow — adjacency is AND — which is the safe direction for a
# character a reader did not know they had typed.
#
# Spelled in escapes and never as the characters themselves: most of these are
# invisible, so written out they are a line no reviewer can check and no editor
# can be trusted not to trim.
_SPACE = frozenset(
    "\t\n\v\f\r \u001c\u001d\u001e\u001f\u0085\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def _terms(text: str) -> list[tuple[str, bool]]:
    """`(text, was-quoted-anywhere)` per token, with `(` and `)` as their own.

    Quoting is tracked rather than stripped and forgotten, because it decides two
    things: `"and"` is a word and not the operator, and the colon inside
    `title:"a: b"` is part of the value. A quote that never closes is malformed
    rather than a quote that runs to the end — the reader is mid-sentence and the
    result set should not lurch while they type the rest of it.
    """
    tokens: list[tuple[str, bool]] = []
    i = 0
    while i < len(text):
        if text[i] in _SPACE:
            i += 1
            continue
        if text[i] in "()":
            tokens.append((text[i], False))
            i += 1
            continue
        buffer, quoted, colon = "", False, -1
        while i < len(text) and text[i] not in _SPACE and text[i] not in "()":
            if text[i] == '"':
                closes = text.find('"', i + 1)
                if closes < 0:
                    raise QueryError("a quote is opened and never closed")
                buffer += text[i + 1 : closes]
                quoted = True
                i = closes + 1
                continue
            if text[i] == ":" and colon < 0:
                colon = len(buffer)
            buffer += text[i]
            i += 1
        # The colon that splits a term is the first one outside quotes, kept as a
        # position rather than found again later: `title:"a: b"` has two.
        split = buffer if colon < 0 else buffer[:colon] + "\x00" + buffer[colon + 1 :]
        tokens.append((split, quoted))
    return tokens


def _term_node(raw: str, quoted: bool) -> Node:
    field, sep, value = raw.partition("\x00")
    if sep:
        if not field or not value:
            raise QueryError("a field and a value both have to be there, as `field:value`")
        # Lowered and never `plain`ed. `plain("(none)")` is `"none"`, which is a
        # status somebody could have typed, so plaining here would hand `evaluate`
        # a value that no longer equals the sentinel and quietly turn
        # `cycle:"(none)"` into a search for records whose cycle contains "none".
        # A whole-match value is a vocabulary word and is compared as it is; only
        # `FREE_TEXT` values are plained, and there, after the sentinel test.
        return Field(ALIASES.get(field.lower(), field.lower()), value.lower())
    if not raw:
        raise QueryError("there is nothing between the quotes")
    # `sought` and not `plain`: a word the separators are stripped out of has to
    # be empty when stripping them left a stub, or `C++` becomes a search for `c`
    # and answers 27 of 28 rows. The empty word is what `found` answers nothing
    # for. Not a parse error either way: somebody typing punctuation into the box
    # is mid-sentence, not asking a question that cannot be read, and the box
    # beside them must not claim otherwise.
    return Word(sought(raw))


class _Reader:
    def __init__(self, tokens: list[tuple[str, bool]]) -> None:
        self.tokens = tokens
        self.at = 0

    def peek(self) -> tuple[str, bool] | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self) -> tuple[str, bool]:
        token = self.tokens[self.at]
        self.at += 1
        return token

    def keyword(self, word: str) -> bool:
        """An operator only if it was typed bare: `"not"` in quotes is a word,
        which is the only way to search for a record whose title contains it."""
        token = self.peek()
        return bool(token) and not token[1] and token[0].lower() == word

    def either(self) -> Node:
        node = self.both()
        while self.keyword("or"):
            self.take()
            if self.finished_or_closing():
                raise QueryError("`or` needs something on both sides of it")
            node = Either(node, self.both())
        return node

    def both(self) -> Node:
        node = self.unary()
        while True:
            if self.keyword("and"):
                self.take()
                if self.finished_or_closing():
                    raise QueryError("`and` needs something on both sides of it")
            elif self.finished_or_closing() or self.keyword("or"):
                return node
            node = Both(node, self.unary())

    def unary(self) -> Node:
        if self.keyword("not"):
            self.take()
            if self.finished_or_closing():
                raise QueryError("`not` needs something to take away")
            return Not(self.unary())
        token = self.peek()
        if token is None:
            raise QueryError("the query stops in the middle")
        if token[0] == "(" and not token[1]:
            self.take()
            # Asked here rather than left to the parse inside, which would report
            # a query that stops in the middle — true, and not the thing the
            # reader can act on. Somebody typing `kind:task and (` is told about
            # the bracket they just opened.
            if self.peek() is None:
                raise QueryError("a bracket is opened and never closed")
            if self.peek()[0] == ")":
                raise QueryError("there is nothing inside the brackets")
            node = self.either()
            closing = self.peek()
            if closing is None or closing[0] != ")":
                raise QueryError("a bracket is opened and never closed")
            self.take()
            return node
        if token[0] == ")" and not token[1]:
            raise QueryError("a bracket is closed that was never opened")
        if not token[1] and token[0].lower() in ("and", "or"):
            raise QueryError(f"`{token[0].lower()}` needs something on both sides of it")
        return _term_node(*self.take())

    def finished_or_closing(self) -> bool:
        token = self.peek()
        return token is None or (token[0] == ")" and not token[1])


def parse(text: str) -> Node | None:
    """The query, as a tree. `None` for an empty query, which matches everything.

    Raises `QueryError` for a query that cannot be read. The caller decides what
    to do with the sentence; every caller here shows it and keeps the rows out.
    """
    reader = _Reader(_terms(text))
    if not reader.tokens:
        return None
    node = reader.either()
    if reader.peek() is not None:
        raise QueryError("a bracket is closed that was never opened")
    return node


# --------------------------------------------------------------------------- #
# Answering it
# --------------------------------------------------------------------------- #


def evaluate(
    node: Node | None,
    fields: dict[str, list[str]],
    text: str,
    names: str,
    empty: str,
) -> bool:
    """Whether one record answers the query.

    `fields` is that record's values per field, lowered, absent where the record
    has none — the same shape the browser builds out of the row, so the two
    parsers are asked about identical data and any disagreement is the language
    rather than the plan. `empty` is `NO_VALUE`, passed rather than spelled.

    **Two haystacks, and `bare` says why.** `text` is `searchable()`'s blob —
    everything a record is known by — and `names` is `nameable()`'s, its id and
    title alone. Both arrive `plain`ed from the server, so nothing here
    normalises a haystack; only a needle, and only where one is not already
    normalised by the parse.
    """
    if node is None:
        return True
    if isinstance(node, Word):
        return bool(bare(node.text, text, names))
    if isinstance(node, Not):
        return not evaluate(node.of, fields, text, names, empty)
    if isinstance(node, Both):
        return evaluate(node.left, fields, text, names, empty) and evaluate(
            node.right, fields, text, names, empty
        )
    if isinstance(node, Either):
        return evaluate(node.left, fields, text, names, empty) or evaluate(
            node.right, fields, text, names, empty
        )
    if node.name not in fields:
        return False  # a field this plan has not got: nothing, not everything
    held = fields[node.name]
    if node.value == empty:
        return not held
    if node.name in FREE_TEXT:
        # Normalised here rather than in the parse, because the sentinel test
        # above needs the value spelled the way the menus spell it — and hoisted
        # out of the loop, because it is one answer for the whole query and
        # `held` is walked once per row per keystroke.
        #
        # `text` and not `names`: a `title:` or `pr:` query has already said
        # which field it means, so the subsequence tier cannot wander into
        # another one and `found` is asked directly.
        needle = sought(node.value)
        return any(found(needle, plain(value)) for value in held)
    # A vocabulary, matched WHOLE — but `plain`ed on both sides first, because
    # the separators stopped counting for a bare word and a language where half
    # the terms are separator-blind and half are not is a language nobody can
    # hold. Before this, over `seed/`, the bare word `pitch0a0001` found the
    # pitch and `id:pitch0a0001` found nothing, and `tag:bedheat` found nothing
    # while `tag:bed-heat` found one — with no sentence beside the box either
    # time.
    #
    # Equality, so it stays whole: `cycle:3` cannot answer cycle 30, because
    # `plain("3")` and `plain("30")` are still two different strings. That is
    # also why this is `plain` and not `sought` — `sought`'s floor exists to stop
    # a truncated stub WIDENING a loose search, and equality never widens, so
    # `priority:very_high` and a hypothetical `p-1` are safe where a bare `C++`
    # is not. The one thing equality does need is the empty guard: a value with
    # nothing alphanumeric in it plains to nothing, and `tag:#` must not be a way
    # of asking for it.
    want = plain(node.value)
    return bool(want) and any(plain(value) == want for value in held)
