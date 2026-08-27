"""The served stylesheet, resolved the way a browser resolves it.

Three of the defects this module's tests pin were CSS that parsed, linted and
shipped, and then lost the cascade to a rule written for something else: two
frozen columns qualified by one extra class quietly outranked the three rules
that exist to correct them, and every assertion anybody had written about them
was a substring search for the rule's own text. A rule being *in* the stylesheet
says nothing about whether it wins, which is the only thing a reader sees.

So this is a small cascade engine: selectors are parsed, weighed the way
§ Selectors 4 weighs them, matched against a described element, and the
declarations sorted by (importance, specificity, order). It answers one
question — for this element and this property, which rule wins and what does it
say — and it names the selector, so a failure reads as "the header's z-index is
decided by `[data-col="id"]`" rather than as two numbers.

Two deliberate limits, both stated rather than hidden:

* At-rules are skipped, bodies and all. `@media (max-width: 1100px)` and
  `@media (prefers-color-scheme: dark)` are different *conditions*; folding them
  in would answer about a page nobody is looking at. This resolves the default
  one: a wide window, in the light theme.
* An element is described by its ancestor path, so descendant and child
  combinators work and the sibling ones cannot. `+` and `~` raise rather than
  silently failing to match — a matcher that answers "no" to a question it does
  not understand is a matcher that reports every rule as losing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STYLE = re.compile(r"<style>(.*?)</style>", re.S)


# --------------------------------------------------------------------------- #
# The element under the microscope
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class El:
    """One element, described by what a selector can ask about it.

    `states` is how a pseudo-class is answered: an element is `:hover` only if it
    was described as hovered. That makes the resting state the default — which is
    the state a page is in — and lets a test ask about the other one on purpose.
    """

    tag: str
    id: str = ""
    classes: frozenset[str] = frozenset()
    attrs: dict[str, str] = field(default_factory=dict)
    states: frozenset[str] = frozenset()


def el(tag: str, classes: str = "", id: str = "", states: str = "", **attrs: str) -> El:
    """`el("td", "edit", data_col="title")` — underscores become dashes, because
    every attribute these pages select on is a `data-*` one."""
    return El(
        tag=tag,
        id=id,
        classes=frozenset(classes.split()),
        attrs={name.replace("_", "-"): value for name, value in attrs.items()},
        states=frozenset(states.split()),
    )


# --------------------------------------------------------------------------- #
# Selectors
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Compound:
    tag: str = ""
    ids: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    attrs: tuple[str, ...] = ()
    pseudos: tuple[tuple[str, str | None, bool], ...] = ()  # name, argument, is-element


# `:where()` contributes nothing; `:is()`, `:not()` and `:has()` contribute the
# weight of their heaviest argument. Everything else is an ordinary pseudo-class.
_ZERO = {"where"}
_FORWARDING = {"is", "not", "has", "matches", "any"}


def _parse_compound(text: str) -> Compound:
    tag, ids, classes, attrs, pseudos = "", [], [], [], []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "*":
            tag, i = "*", i + 1
        elif char == "#":
            found = re.match(r"#([-\w]+)", text[i:])
            ids.append(found.group(1))
            i += found.end()
        elif char == ".":
            found = re.match(r"\.([-\w]+)", text[i:])
            classes.append(found.group(1))
            i += found.end()
        elif char == "[":
            close = text.index("]", i)
            attrs.append(text[i + 1 : close])
            i = close + 1
        elif char == ":":
            found = re.match(r"(::?)([-\w]+)", text[i:])
            element = found.group(1) == "::"
            name = found.group(2)
            i += found.end()
            argument = None
            if i < len(text) and text[i] == "(":
                depth, j = 0, i
                while True:
                    if text[j] == "(":
                        depth += 1
                    elif text[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                argument, i = text[i + 1 : j], j + 1
            pseudos.append((name, argument, element))
        else:
            found = re.match(r"[-\w]+", text[i:])
            if not found:
                raise ValueError(f"cannot parse {text!r} at {text[i:]!r}")
            tag = found.group(0)
            i += found.end()
    return Compound(tag, tuple(ids), tuple(classes), tuple(attrs), tuple(pseudos))


def _split_complex(selector: str) -> list[tuple[str, Compound]]:
    """`[(combinator-before-it, compound), ...]`, left to right.

    Written by hand rather than with a split, because `:where(a, button, input)`
    holds both the spaces and the commas the naive versions of this cut on.
    """
    parts: list[tuple[str, Compound]] = []
    buffer, combinator, depth = "", "", 0
    for char in selector.strip():
        if char in "([":
            depth += 1
            buffer += char
        elif char in ")]":
            depth -= 1
            buffer += char
        elif depth == 0 and char.isspace():
            if buffer:
                parts.append((combinator, _parse_compound(buffer)))
                buffer, combinator = "", " "
            elif not combinator:
                combinator = " "
        elif depth == 0 and char in ">+~":
            if buffer:
                parts.append((combinator, _parse_compound(buffer)))
                buffer = ""
            combinator = char
        else:
            buffer += char
    if buffer:
        parts.append((combinator, _parse_compound(buffer)))
    return parts


def split_list(selector: str) -> list[str]:
    """A selector list, cut on the commas that are not inside brackets."""
    out, buffer, depth = [], "", 0
    for char in selector:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            out.append(buffer.strip())
            buffer = ""
        else:
            buffer += char
    if buffer.strip():
        out.append(buffer.strip())
    return out


def specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes/attributes/pseudo-classes, elements/pseudo-elements)."""
    a = b = c = 0
    for _, compound in _split_complex(selector):
        a += len(compound.ids)
        b += len(compound.classes) + len(compound.attrs)
        if compound.tag and compound.tag != "*":
            c += 1
        for name, argument, is_element in compound.pseudos:
            if is_element:
                c += 1
            elif name in _ZERO:
                continue
            elif name in _FORWARDING and argument:
                heaviest = max(specificity(one) for one in split_list(argument))
                a, b, c = a + heaviest[0], b + heaviest[1], c + heaviest[2]
            else:
                b += 1
    return (a, b, c)


_ATTR = re.compile(r"""^\s*([-\w]+)\s*(?:([~^$*|]?=)\s*["']?(.*?)["']?\s*)?$""")


def _attr_matches(element: El, text: str) -> bool:
    name, operator, value = _ATTR.match(text).groups()
    if name not in element.attrs:
        return False
    if operator is None:
        return True
    held = element.attrs[name]
    return {
        "=": held == value,
        "^=": held.startswith(value),
        "$=": held.endswith(value),
        "*=": value in held,
        "~=": value in held.split(),
        "|=": held == value or held.startswith(value + "-"),
    }[operator]


def _compound_matches(compound: Compound, path: list[El], at: int) -> bool:
    element = path[at]
    if compound.tag and compound.tag != "*" and compound.tag != element.tag:
        return False
    if any(one != element.id for one in compound.ids):
        return False
    if not set(compound.classes) <= element.classes:
        return False
    if not all(_attr_matches(element, one) for one in compound.attrs):
        return False
    for name, argument, is_element in compound.pseudos:
        if is_element:
            return False  # nothing here resolves ::before
        if name in _ZERO | _FORWARDING and argument is not None:
            hit = any(_matches(one, path[: at + 1]) for one in split_list(argument))
            if hit == (name == "not"):
                return False
        elif name not in element.states:
            return False
    return True


def _walk(parts: list[tuple[str, Compound]], part: int, path: list[El], at: int) -> bool:
    if at < 0 or not _compound_matches(parts[part][1], path, at):
        return False
    if part == 0:
        return True
    combinator = parts[part][0]
    if combinator == ">":
        return _walk(parts, part - 1, path, at - 1)
    if combinator in (" ", ""):
        return any(_walk(parts, part - 1, path, up) for up in range(at - 1, -1, -1))
    raise NotImplementedError(
        f"{combinator!r} needs siblings, and an element here is described by its ancestors only"
    )


def _matches(selector: str, path: list[El]) -> bool:
    parts = _split_complex(selector)
    return bool(parts) and _walk(parts, len(parts) - 1, path, len(path) - 1)


# --------------------------------------------------------------------------- #
# The sheet
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Won:
    """Which rule decided a property, and what it said."""

    selector: str
    value: str
    specificity: tuple[int, int, int]
    order: int

    def __str__(self) -> str:
        return f"{self.selector} {{ … : {self.value} }}  [{self.specificity}]"


@dataclass(frozen=True)
class Rule:
    selector: str
    specificity: tuple[int, int, int]
    order: int
    declarations: dict[str, tuple[str, bool]]


def _declarations(body: str) -> dict[str, tuple[str, bool]]:
    out: dict[str, tuple[str, bool]] = {}
    for piece in body.split(";"):
        if ":" not in piece:
            continue
        name, _, value = piece.partition(":")
        value = value.strip()
        important = value.endswith("!important")
        if important:
            value = value[: -len("!important")].strip()
        out[name.strip()] = (" ".join(value.split()), important)
    return out


class Sheet:
    """Every rule in one page's `<style>`, ready to be asked who wins."""

    def __init__(self, css: str) -> None:
        css = _COMMENT.sub(" ", css)
        self.rules: list[Rule] = []
        for prelude, body in _blocks(css):
            if prelude.startswith("@"):
                continue  # a different condition; see the module docstring
            declarations = _declarations(body)
            if not declarations:
                continue
            for one in split_list(prelude):
                self.rules.append(Rule(one, specificity(one), len(self.rules), declarations))

    def winner(self, path: list[El], prop: str) -> Won | None:
        """The declaration a browser would use, or None if nothing sets it."""
        best: Won | None = None
        rank = None
        for rule in self.rules:
            if prop not in rule.declarations:
                continue
            if not _matches(rule.selector, path):
                continue
            value, important = rule.declarations[prop]
            here = (important, rule.specificity, rule.order)
            if rank is None or here > rank:
                rank, best = here, Won(rule.selector, value, rule.specificity, rule.order)
        return best

    def value(self, path: list[El], prop: str) -> str | None:
        won = self.winner(path, prop)
        return won.value if won else None

    def selectors_reaching(self, path: list[El], prop: str) -> list[Rule]:
        """Every rule that sets `prop` on this element, heaviest last. For saying
        what a losing rule lost to."""
        reaching = [
            rule
            for rule in self.rules
            if prop in rule.declarations and _matches(rule.selector, path)
        ]
        return sorted(reaching, key=lambda r: (r.declarations[prop][1], r.specificity, r.order))


def _blocks(css: str) -> list[tuple[str, str]]:
    """(prelude, body) pairs, brace-matched so an at-rule's contents come back
    whole rather than as three rules with a stray `}` in them."""
    out, i = [], 0
    while True:
        open_at = css.find("{", i)
        if open_at < 0:
            return out
        prelude = " ".join(css[i:open_at].split())
        depth, j = 1, open_at + 1
        while depth and j < len(css):
            depth += (css[j] == "{") - (css[j] == "}")
            j += 1
        out.append((prelude, css[open_at + 1 : j - 1]))
        i = j


def sheet_of(page: str) -> Sheet:
    """The stylesheet a page actually serves — the shell's rules and the page's,
    in the order the browser reads them, which is the order they are inlined."""
    return Sheet(_STYLE.search(page).group(1))
