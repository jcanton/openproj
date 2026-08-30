"""What the search box finds, and what the server finds, asked of both at once.

The two halves of this app filter the same plan. The server's `apply_filters`
swept title, tags, PR references *and the whole shaping document* into one blob;
the browser searched `row.title + ' ' + row.tags`. So a word in a body found
seventeen rows through a link and none in the box in front of you, a PR number
found the record on the server and nothing in the table, and neither side
erred — which is the shape of every divergence this repository has shipped: two
answers to one question, both silent.

jcanton's ruling, 2026-08-19: **fields, not bodies**. So there is one definition
of a record's searchable text, it is built from named fields, it travels with the
row, and this file asks both sides the same questions about the same corpus.

The needles are read off the corpus rather than written down here. A list of
words typed into a test is a list that goes stale on the commit that renames a
tag, and it cannot contain the one thing that matters: a word that appears in a
body and nowhere else, which is how "bodies are not searched" is asked rather
than asserted.

**How a needle meets a haystack changed on 2026-08-28** and both halves changed
with it: separators stop counting on either side, and four letters or more find
a name whose letters they are when those letters sit close together. Two
functions, `plain` and `found`, spelled once in `query.py` and once in the
shell's script. The second half of this file is what holds those two together,
and it does it the way the first half holds the parsers together — by asking
both and comparing the answers, never by reading either one's source.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from test_index import a_task
from test_injection import run_js

from openproj.index import Index, apply_filters, build_index
from openproj.model import Config, load_repo
from openproj.query import bare, sought
from openproj.render import render_table

WORD = re.compile(r"[a-z0-9_]{4,}")

# Two cycles whose numbers are a prefix of one another, so that "matched whole"
# is a claim this file can actually put a question to. Every other fixture here
# reads a corpus off the disk; this one is two records wide because it exists to
# hold one title that no corpus may grow.
COOL_CONFIG = Config(
    schema_version=2,
    nominal_availability=1.0,
    cycles={
        3: (date(2026, 6, 22), date(2026, 8, 14)),
        30: (date(2026, 8, 17), date(2026, 10, 9)),
    },
)


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


@pytest.fixture
def page(index: Index) -> str:
    return render_table(index, base_commit="deadbee", may_write=True)


def fields_of(index: Index) -> list[str]:
    """Every value a record carries in a field, as text."""
    said = []
    for record in index.plan.values():
        said += [record.id, record.title, *record.tags, *record.prs]
        said += [record.owner or "", *record.assignees, *record.reviewers]
    return [word for word in said if word]


def needles(index: Index) -> list[str]:
    """What a person types: a tag, a PR number, a login, an id, a word from a
    title. Each is taken from the corpus, so this list grows with the plan."""
    found: set[str] = set()
    for record in index.plan.values():
        found.update(record.tags)
        found.update(record.prs)
        found.update(pr.lstrip("#") for pr in record.prs)
        found.update(filter(None, [record.owner, *record.assignees, *record.reviewers]))
        found.add(record.id)
        found.update(WORD.findall(record.title.lower()))
    return sorted(found)


def body_words(index: Index) -> list[str]:
    """Words that appear in a shaping document and in no field of any record.

    These are the ones that must find nothing: the document is the record, but it
    is not the record's index, and a 900-word pitch swept into a substring search
    made every long word in the plan a match for something.
    """
    in_fields = {word for value in fields_of(index) for word in WORD.findall(value.lower())}
    said: set[str] = set()
    for record in index.plan.values():
        said.update(WORD.findall(record.body.lower()))
    return sorted(said - in_fields)


def found_in_the_browser(page: str, query: str) -> list[str]:
    """The ids the page's own `matches()` keeps for this query.

    The table's rows are built by script and filtered by script, so this is the
    only place the question can be asked of the thing that actually runs.
    """
    # `json.dumps` and not a repr with the quotes swapped: a query is allowed to
    # contain a double quote — `cycle:"(none)"` is how emptiness is asked — and
    # swapping quote characters in a string that holds one produces JavaScript
    # that does not parse, which reports as a disagreement about the language.
    answer = run_js(
        page,
        "(() => { params.set('q', " + json.dumps(query) + "); "
        "return Object.keys(DATA.rows).filter(id => matches(DATA.rows[id])).sort(); })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    return answer["value"]


def found_in_the_browser_for_each(page: str, queries: list[str]) -> dict[str, list[str]]:
    """The same question, asked of the same script, once for every query.

    One node process per query is one process per word, and the corpus holds
    thirteen hundred of them. This batch is what makes "every body-only word"
    affordable — and the alternative, asking about the first twelve
    alphabetically, is a test that goes red when somebody renames a tag.
    """
    answer = run_js(
        page,
        "(() => { const said = {}; for (const query of " + json.dumps(queries) + ") {"
        "  params.set('q', query);"
        "  said[query] = Object.keys(DATA.rows).filter(id => matches(DATA.rows[id])).sort();"
        "} return said; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    return answer["value"]


def test_the_box_and_the_server_find_the_same_records(index: Index, page: str):
    """One question, asked of both halves, for every word the corpus contains.

    This is the third time this class of divergence has been found — after the
    `(none)` sentinel and the search blob itself — so it is asked of results
    rather than of source: the browser's answer comes from running the page's own
    script, and the server's from `apply_filters`.
    """
    asked = needles(index)
    assert len(asked) > 20, "the corpus stopped containing words, which cannot be"

    disagreed = {}
    for needle in asked:
        here = apply_filters(index, {}, needle)
        there = found_in_the_browser(page, needle)
        if here != there:
            disagreed[needle] = (here, there)
    assert not disagreed, (
        "the server and the search box disagree about "
        f"{len(disagreed)} of {len(asked)} words:\n"
        + "\n".join(
            f"  {needle!r}: server {server}, browser {browser}"
            for needle, (server, browser) in list(disagreed.items())[:8]
        )
    )


def test_a_shaping_document_is_still_not_an_index(index: Index, page: str):
    """Fields, not bodies — and the same on both sides.

    The server used to answer these; the box never did. Either behaviour alone is
    defensible and the two together are not, because the link and the box are the
    same filter to everybody but this codebase.

    **"Never a match" stopped being the claim on 2026-08-28**, when the box went
    separator-blind and gained a subsequence tier. `__init__` is written in one
    pitch's prose and in no field of any record; it plains to `init`, which sits
    inside `implementdeterministicmeans` — a task's title — skipping one letter
    at a time. That is a coincidence, and a rule that answers `some cool` for
    `some_cool_title` buys a few of them. So what is asked here is the two things
    that are still true and are not tautologies: that both halves call exactly the
    same words coincidences, and that coincidences stay rare enough that the
    document is still not the index.

    Every body-only word, and not `[:12]`. Sampling the first twelve
    alphabetically means this test goes red or green on somebody renaming a tag
    rather than on the rule it is about.

    **Two axes, because one of them was blind.** Counting the WORDS that find
    anything cannot see a word that finds half the plan: while the subsequence
    tier still read the whole blob, `oere` kept 18 of `seed/`'s 28 rows and cost
    this test one word out of thirteen hundred. So the rows are counted too, over
    every needle the corpus offers and not only the body-only ones.
    """
    only_in_prose = body_words(index)
    assert len(only_in_prose) > 20, (
        "no word in this corpus is unique to a body, so this test asks nothing"
    )

    here = {word: apply_filters(index, {}, word) for word in only_in_prose}
    there = found_in_the_browser_for_each(page, only_in_prose)
    disagreed = {
        word: (here[word], there[word]) for word in only_in_prose if here[word] != there[word]
    }
    assert not disagreed, (
        f"the server and the box disagree about {len(disagreed)} words that appear "
        "only in a shaping document:\n"
        + "\n".join(
            f"  {w!r}: server {s}, browser {b}" for w, (s, b) in list(disagreed.items())[:8]
        )
    )

    coincide = sorted(word for word in only_in_prose if here[word])
    assert len(coincide) <= len(only_in_prose) // 10, (
        f"{len(coincide)} of {len(only_in_prose)} words that appear only in a body now "
        f"find a record — a tenth is the ceiling, and past it the prose is an index "
        f"again by accident: {coincide[:12]}"
    )

    # The second axis: rows, not words. For every needle this corpus offers, how
    # many rows the SUBSEQUENCE tier adds over what the substring tier already
    # kept. A fifth of the plan is the ceiling, and it is set by what the split
    # haystacks leave behind rather than by taste — measured 2026-08-28, the
    # worst needle over `seed/` adds 3 rows of 28 (11%) and the worst over
    # `tests/fixtures/corpus` adds 3 of 26 (12%), so a fifth is roughly twice the
    # room the rule needs. Before the tiers were split it would have been 18 of
    # 28, and a ceiling anywhere under a half would have caught it.
    #
    # **What this axis cannot see, so that nobody cites it for that.** The
    # needles come from `needles` and `body_words`, which take title words of
    # four characters or more and whole field values, so the set holds five
    # needles under four characters over `seed/` and six over the fixture. It
    # therefore answers the same for a subsequence floor of 4, 3 or 2 — this
    # assertion is no evidence about the floor at all, and the measurement that
    # is lives over `found` in `query.py`.
    rows = len(index.plan)
    loose = {}
    for word in sorted({*needles(index), *only_in_prose}):
        needle = sought(word)
        if not needle:
            continue
        added = [
            record_id
            for record_id in index.plan
            if bare(needle, index.search_blob[record_id], index.name_blob[record_id]) == 2
        ]
        if len(added) * 5 > rows:
            loose[word] = added
    assert not loose, (
        f"the subsequence tier adds more than a fifth of {rows} rows for "
        f"{len(loose)} needles, which is a tier that answers the plan rather than "
        f"a name: {dict(list(loose.items())[:4])}"
    )


def test_every_searchable_field_is_reachable_from_the_box(index: Index, page: str):
    """Each field the definition names can actually be found through the box.

    A field list is a promise, and the way this promise breaks is a field that is
    on the list and empty on every row — the reader types a login and finds
    nothing, and nothing anywhere says the field was never carried.
    """
    for record in index.plan.values():
        for value in filter(None, [record.id, record.title, *record.tags, *record.prs]):
            assert record.id in found_in_the_browser(page, value), (
                f"{record.id} does not find itself by {value!r}"
            )
            assert record.id in apply_filters(index, {}, value), (
                f"the server does not find {record.id} by {value!r}"
            )
        break


# --------------------------------------------------------------------------- #
# The query language
# --------------------------------------------------------------------------- #


def ids(index: Index, query: str) -> list[str]:
    return apply_filters(index, {}, query)


def test_a_bare_word_is_found_however_it_is_spelled(index: Index):
    """What the box always did, and it keeps doing it: the language is something
    a query grows into rather than something it has to opt into.

    It was called `..._is_a_substring_of_the_searchable_text` until the box went
    separator-blind, and the three assertions under it did not move. The name had
    to, or the file starts lying about the rule it is pinning.
    """
    assert ids(index, "throughflow") == ids(index, "THROUGHFLOW")
    assert ids(index, "throughflow")
    assert ids(index, "no such word anywhere") == []


def test_a_field_asks_that_field_and_nothing_else(index: Index):
    """`owner:jackdawrie` is not `jackdawrie`: the second finds every record that
    name is on in any role, which is the whole reason a field is worth spelling
    out."""
    everywhere = set(ids(index, "jackdawrie"))
    owned = set(ids(index, "owner:jackdawrie"))

    assert owned < everywhere, "owner: found no fewer records than the bare word"
    assert all(index.plan[i].owner == "jackdawrie" for i in owned)


def test_two_tags_can_be_asked_for_at_once(index: Index):
    """The query the dropdowns cannot express. A menu means OR within a field, so
    "both of these tags" has no control on the page — it is why there is a
    language at all."""
    tags = [t for t in index.facets["tags"] if t != "(none)"]
    pairs = [
        (one, two)
        for one in tags
        for two in tags
        if one < two and any({one, two} <= set(e.tags) for e in index.plan.values())
    ]
    assert pairs, "no record in this corpus carries two tags, so this asks nothing"

    one, two = pairs[0]
    both = ids(index, f"tag:{one} and tag:{two}")
    assert both == sorted(i for i, e in index.plan.items() if {one, two} <= set(e.tags))
    assert set(both) < set(ids(index, f"tag:{one} or tag:{two}"))


def test_not_takes_records_away(index: Index):
    every = set(ids(index, ""))
    ready = set(ids(index, "status:ready"))

    assert ids(index, "not status:ready") == sorted(every - ready)
    assert ready, "no record in this corpus is ready, so this asks nothing"


def test_parentheses_change_the_answer(index: Index):
    """`a and (b or c)` is not `(a and b) or c`, and a language where they are the
    same is a language that quietly ignored the brackets."""
    # The precondition, stated rather than hoped for: the two spellings differ
    # only if some pitch is not done, and a corpus where every pitch is finished
    # would let a parser that ignored brackets pass this.
    assert any(e.kind == "pitch" and e.status != "done" for e in index.plan.values())

    grouped = ids(index, "kind:pitch or (kind:task and status:done)")
    flat = ids(index, "(kind:pitch or kind:task) and status:done")

    assert grouped != flat
    assert set(flat) - set(grouped) == set(), "the brackets moved records the other way"
    assert set(grouped) > set(flat)


def test_adjacent_terms_are_anded(index: Index):
    """Two words beside each other narrow, because that is what every search box
    a person has ever used does with them."""
    assert ids(index, "kind:task status:ready") == ids(index, "kind:task and status:ready")


def test_an_unknown_field_matches_nothing_rather_than_everything(index: Index):
    """The rule `apply_filters` already had, extended to the language: a typo that
    silently widens a result set is worse than one that visibly empties it."""
    assert ids(index, "onwer:jackdawrie") == []
    assert ids(index, "owner:jackdawrie or onwer:jackdawrie") == ids(index, "owner:jackdawrie")


def test_a_malformed_query_says_so_and_matches_nothing(index: Index):
    """Both halves of the rule. Matching everything would be a table that looks
    like it answered; saying nothing would be a table that looks broken."""
    from openproj.query import QueryError, parse

    for broken in ("(kind:task", "kind:task and", "and kind:task", "not", "()", "or"):
        assert ids(index, broken) == [], broken
        with pytest.raises(QueryError):
            parse(broken)


def test_the_empty_menu_option_is_askable_in_the_language(index: Index):
    """`(none)` is the one value a menu offers that is not a value. It is quoted
    here because the brackets are grammar — and it is the same string the menus
    use, because two spellings for one thing is how a sentinel drifts."""
    from openproj.index import NO_VALUE

    asked = ids(index, f'cycle:"{NO_VALUE}"')
    assert asked == sorted(i for i, e in index.plan.items() if not e.cycle)


def test_a_pr_is_found_however_it_is_written(index: Index):
    """`#2318`, `2318` and the whole `kilnlab/kiln4py#2318` are one PR, and a person
    reading a review types whichever of the three is in front of them."""
    holders = [e for e in index.plan.values() if e.prs]
    assert holders, "no record in this corpus names a PR"

    whole = holders[0].prs[0]
    number = whole.split("#")[-1]
    assert holders[0].id in ids(index, f"pr:{number}")
    assert holders[0].id in ids(index, f"pr:{whole}")


def test_the_language_is_evaluated_the_same_in_the_browser(index: Index, page: str):
    """The claim that matters, asked of results and not of source.

    Two parsers exist because there have to be two — the server renders a static
    export with no JavaScript and the table filters without a server — so this is
    the only thing standing between them and a query that means two things.
    """
    tags = [t for t in index.facets["tags"] if t != "(none)"][:2]
    queries = [
        "",
        "throughflow",
        "THROUGHFLOW",
        "port throughflow",
        "kind:task",
        "kind:task and status:ready",
        "kind:task status:ready",
        "kind:task or kind:pitch",
        "not kind:task",
        "not (kind:task or kind:pitch)",
        "kind:task and (status:ready or status:done)",
        "(kind:task and status:ready) or status:done",
        "owner:jackdawrie",
        "assignee:jackdawrie",
        "reviewer:jackdawrie",
        f"tag:{tags[0]}",
        f"tag:{tags[0]} and tag:{tags[1]}",
        f"tag:{tags[0]} or tag:{tags[1]}",
        'cycle:"(none)"',
        "onwer:jackdawrie",
        "id:pitch-0b0001",
        "title:porting",
        "pr:2318",
        "(kind:task",
        "kind:task and",
        "not",
        # The separator-blind and subsequence spellings, on the wall that pins the
        # two halves together: an id typed without its hyphen, a PR typed without
        # its `#`, a quoted phrase whose space is gone, a title asked for through
        # `title:` with a hyphen it does not have, a word that can only be a
        # subsequence, and one made of punctuation alone.
        "pitch0b0001",
        "id:pitch0b0001",
        "pr:kilnlab/kiln4py#2318",
        "prs:kilnlabkiln4py2318",
        '"the throughflow"',
        "title:port-ing",
        "thrghflw",
        "#",
        "not thrghflw",
        # A needle the separators truncate rather than empty, and its negation:
        # `plain` leaves `c`, which answered 27 of 28 rows and — inverted — one.
        "C++",
        "not C++",
        # A query pasted out of a spreadsheet cell that carries a byte-order
        # mark. `str.isspace()` says U+FEFF is not whitespace and `/\s/` says it
        # is, so this used to be a bare word on one side and a field query on the
        # other. Harmless while a bare word was a substring — neither side found
        # it — and not harmless once `found` matched where `includes` did not.
        "\ufefftitle:smcl",
        "\ufeffthroughflow",
        # And the four whitespace characters the disagreement ran the other way
        # on: Python called them spaces and the browser did not.
        "kind:task\u0085status:done",
        "kind:task\u001estatus:done",
    ]
    disagreed = {}
    for query in queries:
        here = apply_filters(index, {}, query)
        there = found_in_the_browser(page, query)
        if here != there:
            disagreed[query] = (here, there)
    assert not disagreed, "\n".join(
        f"  {q!r}: server {s}, browser {b}" for q, (s, b) in disagreed.items()
    )


# --------------------------------------------------------------------------- #
# How a needle meets a haystack
#
# jcanton, 2026-08-28: "so if a record has title some_cool_title it shows up even
# when searching 'some cool', and capital letters are ignored etc etc" — and,
# shown three widths, he took the widest: separators stop counting anywhere, and
# the letters of a name find it when they sit close together inside it.
#
# The corpus holds no record called `some_cool_title`, and the one thing it must
# not do is grow one: `tests/fixtures/corpus` is frozen and `seed/` is the demo
# people read. So the example he gave is built here, two records wide, which is
# also what makes each of these a narrowing rather than a number.
# --------------------------------------------------------------------------- #

COOL = "task-5c0001"
DULL = "task-5c0002"


@pytest.fixture
def cool_index() -> Index:
    """His own example, and a decoy that shares its first word.

    The decoy is the half that makes this a test: `some cool` finding one record
    out of one record is what every rule in the rejected pile also does.
    """
    return build_index(
        [
            a_task(COOL, "some_cool_title", cycle=3, person_weeks=1.0),
            a_task(DULL, "Some other work entirely", cycle=30, person_weeks=1.0),
        ],
        COOL_CONFIG,
        date(2026, 8, 17),
    )


@pytest.fixture
def cool_page(cool_index: Index) -> str:
    return render_table(cool_index, base_commit="deadbee", may_write=True)


def test_a_title_is_found_however_its_words_are_run_together(
    cool_index: Index, cool_page: str
):
    """The ask, in the six spellings somebody actually types.

    `some cool` already worked, because two words beside each other are ANDed and
    both are substrings. The other five did not: quoting it made one term with a
    space in it, and `some-cool`, `some.cool` and `somecool` each disagreed with
    the title about which characters are punctuation. They are one rule now — the
    separators are deleted from both sides before either is looked at.
    """
    for typed in (
        "some cool",
        "SOME Cool",
        '"some cool"',
        "some-cool",
        "some.cool",
        "somecool",
        "Some_Cool_Title",
    ):
        assert apply_filters(cool_index, {}, typed) == [COOL], typed
    said = found_in_the_browser_for_each(
        cool_page,
        ["some cool", "SOME Cool", '"some cool"', "some-cool", "some.cool", "somecool"],
    )
    assert all(kept == [COOL] for kept in said.values()), said


def test_the_letters_of_a_title_find_it_when_they_sit_close_together(
    cool_index: Index, cool_page: str
):
    """The subsequence tier, and the two bounds that stop it answering the plan.

    `smcl` is the shortest example jcanton gave and it is what both constants are
    set by: four characters, because three letters read as a subsequence add up
    to a sixth of a real plan and at worst well over half of it (the numbers are
    over `found`, measured against this narrowed haystack on 2026-08-28), and a
    run of two skipped letters, because `smcl` in `somecooltitle` needs exactly
    two (`c`, then `o` and `o`).

    **Which bound refuses which, because this docstring got it wrong once.**
    `oot` is the floor's, and the only one here that is: it is a subsequence of
    both titles within the gap, so a floor of 3 would hand back the record AND
    its decoy, and four is what keeps it out. `scltl`, `sometitle` and `smclx`
    are the gap's. So is **`sct`** — it is under the floor as well, but lowering
    the floor would not admit it, because `somecooltitle` skips `o`, `m` and `e`
    between the `s` and the `c` and that is three in a row. It was written here
    as the floor's example until it was measured; `s_c_t` plains to it, and the
    reason that spelling finds nothing is the gap and never the floor.

    The gap's three are the ones worth having: all are letters of the right title
    in the right order, and `sometitle` is even its first word and its last. The
    rule finds letters that sit CLOSE TOGETHER, not any letters in order — a
    matcher that took those would have stopped narrowing anything.

    A third bound, and it is not visible in a two-record fixture: the HAYSTACK.
    This tier reads `nameable`'s id and title and never the rest of the blob, so
    `bare` and not `found` is what answers a bare word. What that is worth is
    measured over a real plan, in `test_a_shaping_document_is_still_not_an_index`
    — here there is no login to be dragged in.
    """
    for typed in ("smcl", "coltitle"):
        assert apply_filters(cool_index, {}, typed) == [COOL], typed
    # `s_c_t` beside `sct` because they are one needle after `sought`, and the
    # spelling is the one jcanton was shown: it has to be asked in the shape he
    # would type, or the test pins the plaining and not the answer.
    for typed in ("sct", "s_c_t", "oot", "scltl", "sometitle", "smclx"):
        assert apply_filters(cool_index, {}, typed) == [], typed

    said = found_in_the_browser_for_each(
        cool_page, ["smcl", "coltitle", "sct", "s_c_t", "oot", "scltl", "sometitle", "smclx"]
    )
    assert said == {
        "smcl": [COOL],
        "coltitle": [COOL],
        "sct": [],
        "s_c_t": [],
        "oot": [],
        "scltl": [],
        "sometitle": [],
        "smclx": [],
    }, said


def test_a_short_query_is_never_read_as_a_subsequence(index: Index, page: str):
    """The floor, asked of the corpus rather than of the constant.

    Three characters read as a subsequence answer far too much of a plan — over
    `seed/`, `ith` would add 14 rows of 28 and `a00` 16, on top of what the
    substring tier already kept — so under four characters there is no second
    tier at all and a short needle is a substring or nothing. Pinned by what the
    rows do: for every short needle the corpus contains, the answer is exactly
    the rows whose blob holds it literally.

    `gpu` was the example here until 2026-08-28, and it was a bad one: once the
    loose tier stopped reading logins and tags it added NOTHING for `gpu` on
    either corpus, because the four rows it keeps hold those three letters
    literally. An example that costs nothing cannot argue for a floor. See
    `found` in `query.py` for the distribution the floor is actually set from.

    This is what a regex over the shipped source could not say. A pin asserting
    that `4` appears in the script passes over a walk that starts its loop
    somewhere else.

    "Holds it literally" means holds `sought(needle)` and not `plain(needle)`,
    because `sought` is what a needle goes through: `no-` is a three-character
    prefix of the tag `no-scatter-solver`, and it is a TRUNCATION — two
    characters left of three typed — so it answers nothing rather than the six
    rows `no` sits inside. That is the rule above this one and it is asked in its
    own test; here it only has to be the same needle on both sides of the claim.
    """
    from openproj.query import sought

    # Bare words only. A two-letter prefix that happens to be `or` is the
    # operator and answers a QueryError rather than a row, and a prefix carrying
    # a colon or a bracket is a different production of the grammar — neither is
    # a claim about the floor.
    short = sorted(
        needle
        for needle in {n[:length] for n in needles(index) for length in (2, 3)}
        if needle.lower() not in ("or", "and", "not") and not set(needle) & set('():"')
    )
    literal = {
        needle: sorted(
            i
            for i, blob in index.search_blob.items()
            if sought(needle) and sought(needle) in blob and i in index.plan
        )
        for needle in short
    }
    assert any(literal.values()), "no short needle in this corpus finds anything"

    wider = {
        needle: (literal[needle], apply_filters(index, {}, needle))
        for needle in short
        if literal[needle] != apply_filters(index, {}, needle)
    }
    assert not wider, (
        "a needle under four characters found a record it is not literally inside, "
        f"so the subsequence floor is not where it says it is: {list(wider.items())[:4]}"
    )
    said = found_in_the_browser_for_each(page, short)
    assert said == literal, {n: (literal[n], said[n]) for n in short if said[n] != literal[n]}


def test_a_needle_of_pure_punctuation_matches_nothing_and_is_not_a_complaint(
    index: Index, page: str
):
    """Two halves, and the second is the one that would be missed.

    `-` used to match all twenty-eight records of this corpus and `#` twelve of
    them, because every id carries a hyphen and every PR reference a hash. There
    is nothing searchable left in either once the separators are gone, so they
    answer nothing — the same ruling `onwer:` gets, and for the same reason: a
    query that widens by accident is worse than one that visibly empties.

    And they are not malformed. Somebody typing `#` is a sentence away from
    `#2318`, and a box that says "that search cannot be read" while they type is
    a box that flickers a complaint at every third keystroke.

    **`C++`, `c#`, `I/O` and `Δt` belong here and were not here.** Stripping the
    separators does not only EMPTY a needle, it truncates one, and a truncation
    is worse than an emptying because it still matches: measured over `seed/` on
    2026-08-28, `C++` plained to `c` and kept 27 of the 28 planned rows, `c#` the
    same, `Δt` plained to `t` and kept all 28, `I/O` plained to `io` and kept 10
    — and `not C++` turned the whole plan into one row. Nothing was drawn beside
    the box for any of them, because all four parse. This test's name already
    claimed the case; `sought` (`query.py`) is what makes the claim true, and in
    a plan about porting numerics these are not adversarial inputs.
    """
    from openproj.query import QueryError, parse

    for typed in ("-", "#", "---", "/", "...", "C++", "c#", "I/O", "Δt"):
        assert ids(index, typed) == [], typed
        assert found_in_the_browser(page, typed) == [], typed
        parse(typed)  # readable: raises QueryError if this became a complaint

    # And the sentinel is still not a word: `(none)` is brackets and a word to
    # `plain`, which would make it `none`, and a field value must survive whole.
    assert ids(index, 'cycle:"(none)"') == sorted(
        i for i, record in index.plan.items() if not record.cycle
    )
    with pytest.raises(QueryError):
        parse('title:"')


def test_a_cycle_number_is_still_matched_whole(cool_index: Index, cool_page: str):
    """`cycle:3` must never answer for cycle 30, and the widening does not reach
    it: a vocabulary is matched by equality and only `title` and `prs` are free
    text. The corpus this is asked of holds one of each on purpose — a plan with
    no cycle 30 in it cannot tell a whole match from a loose one.
    """
    assert apply_filters(cool_index, {}, "cycle:3") == [COOL]
    assert apply_filters(cool_index, {}, "cycle:30") == [DULL]
    said = found_in_the_browser_for_each(cool_page, ["cycle:3", "cycle:30"])
    assert said == {"cycle:3": [COOL], "cycle:30": [DULL]}, said


# Pairs no corpus contains, each written for one branch of the walk: nothing
# searchable in the needle, a needle longer than its haystack, an accented value
# against itself and against its unaccented spelling, a space that a match may
# not cross, and a skipped run of exactly two against one of exactly three, which
# is the gap bound itself and the one place a wrong `>` would hide.
ADVERSARIAL = [
    ("", ""),
    ("", "somecooltitle"),
    ("#", "somecooltitle"),
    ("焙煎", "somecooltitle"),
    ("somecooltitlelonger", "somecooltitle"),
    # The pair that matters most and looks least like a test. `plain` deletes
    # everything outside ASCII, and it has to delete it in both languages,
    # because `found` walks by index and an index here is a code point while an
    # index in the browser is a UTF-16 code unit — one skipped emoji would cost
    # the gap counter 1 on this side and 2 on that one.
    ("a\U0001f600\U0001f600bcd", "abcd"),
    ("Söderberg", "sderberg"),
    ("sderberg", "sderberg"),
    ("soderberg", "sderberg"),
    ("abcd", "axxbxxcxxd"),
    ("abcd", "axxxbxxcxxd"),
    # The truncations `sought` has to empty, and the two spellings either side of
    # its floor: three characters survive a deletion and two do not.
    ("C++", "c"),
    ("c#", "c"),
    ("I/O", "io"),
    ("Δt", "t"),
    ("s_c_t", "somecooltitle"),
    ("2-gpu", "2gpu"),
    ("some.cool", "somecooltitle"),
    ("ci", "ci hearth"),
    # An all-digit needle, which takes the substring tier and never the loose
    # one: `1364` IS a subsequence of this reference and must not answer for it.
    ("1364", "kilnlabkiln4py1234564"),
    ("#1364", "kilnlabkiln4py1364"),
    ("1364", "kilnlabkiln4py1364"),
    ("abcd", "ab cd"),
    ("abcd", "axxb cxxd"),
    ("abc", "axxbxxc"),
    ("smcl", "somecooltitle"),
    ("scltl", "somecooltitle"),
    ("aaaa", "aaa"),
    ("title", "somecooltitle"),
]


def test_the_two_matchers_agree_letter_for_letter(index: Index, page: str):
    """`found` and `plain`, run in node and in Python over the same pairs.

    This file pins its two halves by results and never by source — `query.py`
    says why in its own first paragraph — and the two constants are no exception.
    A regex asserting that `4` and `2` appear in the shipped script would pass
    over a walk whose loop bounds differ by one, which is exactly the kind of
    divergence that ships here: the answer is the claim, not the digits.

    The rank is compared and not the truth of it. Two matchers that agree about
    *whether* a row matched and disagree about *how* are two matchers, and the
    completion lists sort by that number.

    All three normalisers, and not only `plain`. `sought` is what a needle
    actually goes through — it is `plain` plus the floor that empties a
    truncation — so two `plain`s that agree over a `sought` that does not is
    still two matchers, and the browser's is the one nothing else here runs.
    """
    from openproj.query import found, plain, sought

    hays = sorted(set(index.search_blob.values()))
    pairs = [(needle, hay) for needle in needles(index) for hay in hays] + ADVERSARIAL
    assert len(pairs) > 500, "this corpus stopped being big enough to ask"

    def here(needle: str, hay: str) -> list:
        return [found(sought(needle), hay), sought(needle), plain(needle)]

    # The pairs travel INSIDE the page rather than in the expression, and that is
    # not tidiness: Linux caps a single argv entry at 128KB (`MAX_ARG_STRLEN`),
    # and six thousand pairs of a plan's own words is comfortably past it — the
    # suite went green on a laptop and answered `OSError: [Errno 7] Argument list
    # too long: 'node'` on CI, which reads as a broken harness rather than as a
    # corpus that grew. The page arrives on stdin, and `<script
    # type=application/json>` is the shape the driver already lifts out of markup
    # for the pages' own payloads.
    asked = page.replace(
        "</body>",
        '<script type="application/json" id="pairs">'
        + json.dumps([[n, h] for n, h in pairs])
        + "</script></body>",
        1,
    )
    answer = run_js(
        asked,
        "(() => JSON.parse(document.getElementById('pairs').textContent)"
        ".map(([n, h]) => [found(sought(n), h), sought(n), plain(n)]))()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]

    disagreed = [
        (needle, hay, here(needle, hay), there)
        for (needle, hay), there in zip(pairs, answer["value"], strict=True)
        if here(needle, hay) != there
    ]
    assert not disagreed, (
        f"the two matchers answer differently for {len(disagreed)} of {len(pairs)} pairs, "
        f"as [rank, sought, plain]: {disagreed[:6]}"
    )


def test_the_two_field_lists_are_the_same():
    """The language names the same fields in both places.

    A field in one list and not the other is `owner:jackdawrie` answering on the
    server and matching nothing in the table — the `(none)` sentinel's failure
    with a different name, which is why that one is pinned the same way.
    """
    from openproj.index import _HOLDER_FACETS, _LIST_FACETS, _SCALAR_FACETS
    from openproj.render import _FILTER_JS

    here = [*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS, "id", "title", "prs", "predicate"]
    said = re.search(r"const QUERY_FIELDS = \[([^\]]*)\]", _FILTER_JS).group(1)
    there = re.findall(r"'([^']+)'", said)

    assert sorted(there) == sorted(here), f"browser {sorted(there)}, server {sorted(here)}"


def test_the_aliases_and_the_free_text_fields_are_the_same():
    """The rest of the language's vocabulary, pinned the same way. An alias in one
    place only means `tag:gpu` narrows in the table and matches nothing through a
    link; a free-text field in one place only means `pr:2318` finds the record in
    one of them and not the other."""
    from openproj.query import ALIASES, FREE_TEXT
    from openproj.render import _FILTER_JS

    aliases = re.search(r"const ALIASES = \{(.*?)\};", _FILTER_JS, re.S).group(1)
    said = dict(re.findall(r"(\w+): '([^']+)'", aliases))
    listed = re.search(r"const FREE_TEXT = \[([^\]]*)\]", _FILTER_JS).group(1)
    free = re.findall(r"'([^']+)'", listed)

    assert said == ALIASES
    assert free == list(FREE_TEXT)


def test_a_half_typed_query_says_what_is_wrong_with_it(index: Index, page: str):
    """Both halves of the rule, in the browser: no rows, and a sentence.

    The rows going is not the interesting half — an empty table is what a filter
    that matches nothing looks like, and this repository's oldest recurring
    finding is that empty and broken render identically. So this asks what the
    reader is actually shown while they are halfway through typing a bracket.
    """
    answer = run_js(
        page,
        "(() => { params.set('q', 'kind:task and ('); syncFilters(); draw(); return {"
        "  said: document.getElementById('query-error').textContent,"
        "  hidden: document.getElementById('query-error').hidden,"
        "  rows: document.querySelectorAll('tbody tr[data-id]').length,"
        "  empty: (document.querySelector('tr.nothing .headline') || {}).textContent,"
        "}; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]

    assert answer["value"]["said"] == "a bracket is opened and never closed"
    assert answer["value"]["hidden"] is False
    assert answer["value"]["rows"] == 0
    assert answer["value"]["empty"] == "That search cannot be read."


def test_a_query_that_reads_leaves_nothing_said(index: Index, page: str):
    """And the sentence goes when the bracket is closed. A message that stays is a
    page that is wrong about itself for as long as somebody keeps typing."""
    answer = run_js(
        page,
        "(() => { params.set('q', 'kind:task and ('); syncFilters();"
        "  params.set('q', 'kind:task'); syncFilters(); return {"
        "  said: document.getElementById('query-error').textContent,"
        "  hidden: document.getElementById('query-error').hidden}; })()",
        page=True,
    )
    assert answer["value"] == {"said": "", "hidden": True}


MALFORMED = [
    "(kind:task",
    "kind:task and (",
    "kind:task and",
    "and kind:task",
    "not",
    "()",
    "or",
    ")",
    "kind:",
    ":jackdawrie",
    'title:"unclosed',
]


def test_both_halves_refuse_the_same_queries_with_the_same_sentence(index: Index, page: str):
    """Two parsers, one vocabulary of complaints.

    Not decoration: the sentence is what the reader is shown, so a query refused
    in the table and accepted through a link is a divergence, and one refused by
    both with different words is two tools. Asked of every way of writing a
    broken query that this language has.
    """
    from openproj.query import QueryError, parse

    said = {}
    for query in MALFORMED:
        try:
            parse(query)
            here = ""
        except QueryError as refused:
            here = str(refused)
        there = run_js(
            page,
            "(() => { params.set('q', " + json.dumps(query) + "); return queryError(); })()",
            page=True,
        )["value"]
        if here != there:
            said[query] = (here, there)
    assert not said, "\n".join(
        f"  {q!r}: server {s!r}, browser {b!r}" for q, (s, b) in said.items()
    )


def test_nothing_malformed_is_quietly_accepted(index: Index, page: str):
    """Every query above is actually refused, by both. Without this the test
    beside it passes handsomely on a pair of parsers that accept everything."""
    from openproj.query import QueryError, parse

    for query in MALFORMED:
        with pytest.raises(QueryError):
            parse(query)
        assert apply_filters(index, {}, query) == []
        assert found_in_the_browser(page, query) == []
