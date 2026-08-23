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

# Fields whose values are free text, matched by substring. Everything else is a
# vocabulary — a status, a login, a tag, a cycle number — and is matched whole,
# because `cycle:3` must not answer for cycle 30 and `status:done` must not be a
# way of writing "any status containing done".
#
# A title is a sentence and nobody types a whole one. A PR reference is written
# three ways in the same review — `1364`, `#1364`, `C2SM/icon4py#1364` — and the
# person searching has whichever of them is in front of them.
FREE_TEXT = ("title", "prs")


class QueryError(ValueError):
    """A query that cannot be read, with the sentence the reader is shown."""


@dataclass(frozen=True)
class Word:
    """A bare word: a substring of the record's searchable text."""

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
        if text[i].isspace():
            i += 1
            continue
        if text[i] in "()":
            tokens.append((text[i], False))
            i += 1
            continue
        buffer, quoted, colon = "", False, -1
        while i < len(text) and not text[i].isspace() and text[i] not in "()":
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
        return Field(ALIASES.get(field.lower(), field.lower()), value.lower())
    if not raw:
        raise QueryError("there is nothing between the quotes")
    return Word(raw.lower())


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


def evaluate(node: Node | None, fields: dict[str, list[str]], text: str, empty: str) -> bool:
    """Whether one record answers the query.

    `fields` is that record's values per field, lowered, absent where the record
    has none — the same shape the browser builds out of the row, so the two
    parsers are asked about identical data and any disagreement is the language
    rather than the plan. `text` is `searchable()`'s blob, which is what a bare
    word looks in. `empty` is `NO_VALUE`, passed rather than spelled.
    """
    if node is None:
        return True
    if isinstance(node, Word):
        return node.text in text
    if isinstance(node, Not):
        return not evaluate(node.of, fields, text, empty)
    if isinstance(node, Both):
        return evaluate(node.left, fields, text, empty) and evaluate(
            node.right, fields, text, empty
        )
    if isinstance(node, Either):
        return evaluate(node.left, fields, text, empty) or evaluate(
            node.right, fields, text, empty
        )
    if node.name not in fields:
        return False        # a field this plan has not got: nothing, not everything
    held = fields[node.name]
    if node.value == empty:
        return not held
    if node.name in FREE_TEXT:
        return any(node.value in value for value in held)
    return node.value in held
