"""What the search box finds, and what the server finds, asked of both at once.

The two halves of this app filter the same plan. The server's `apply_filters`
swept title, tags, PR references *and the whole shaping document* into one blob;
the browser searched `row.title + ' ' + row.tags`. So a word in a body found
seventeen rows through a link and none in the box in front of you, a PR number
found the entity on the server and nothing in the table, and neither side
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
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from test_injection import run_js

from openproj.index import Index, apply_filters, build_index
from openproj.model import load_repo
from openproj.render import render_table

WORD = re.compile(r"[a-z0-9_]{4,}")


@pytest.fixture
def index(demo_root: Path) -> Index:
    entities, config, _ = load_repo(demo_root)
    return build_index(entities, config, date(2026, 8, 17))


@pytest.fixture
def page(index: Index) -> str:
    return render_table(index, base_commit="deadbee")


def fields_of(index: Index) -> list[str]:
    """Every value a record carries in a field, as text."""
    said = []
    for entity in index.entities.values():
        said += [entity.id, entity.title, *entity.tags, *entity.prs]
        said += [entity.owner or "", *entity.assignees, *entity.reviewers]
    return [word for word in said if word]


def needles(index: Index) -> list[str]:
    """What a person types: a tag, a PR number, a login, an id, a word from a
    title. Each is taken from the corpus, so this list grows with the plan."""
    found: set[str] = set()
    for entity in index.entities.values():
        found.update(entity.tags)
        found.update(entity.prs)
        found.update(pr.lstrip("#") for pr in entity.prs)
        found.update(filter(None, [entity.owner, *entity.assignees, *entity.reviewers]))
        found.add(entity.id)
        found.update(WORD.findall(entity.title.lower()))
    return sorted(found)


def body_words(index: Index) -> list[str]:
    """Words that appear in a shaping document and in no field of any record.

    These are the ones that must find nothing: the document is the record, but it
    is not the record's index, and a 900-word pitch swept into a substring search
    made every long word in the plan a match for something.
    """
    in_fields = {word for value in fields_of(index) for word in WORD.findall(value.lower())}
    said: set[str] = set()
    for entity in index.entities.values():
        said.update(WORD.findall(entity.body.lower()))
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


def test_a_word_only_in_a_shaping_document_is_not_a_match(index: Index, page: str):
    """Fields, not bodies — and the same on both sides.

    The server used to answer these; the box never did. Either behaviour alone is
    defensible and the two together are not, because the link and the box are the
    same filter to everybody but this codebase.
    """
    only_in_prose = body_words(index)
    assert len(only_in_prose) > 20, (
        "no word in this corpus is unique to a body, so this test asks nothing"
    )

    for word in only_in_prose[:12]:
        assert apply_filters(index, {}, word) == [], (
            f"{word!r} appears only in a shaping document and the server found it"
        )
        assert found_in_the_browser(page, word) == [], (
            f"{word!r} appears only in a shaping document and the box found it"
        )


def test_every_searchable_field_is_reachable_from_the_box(index: Index, page: str):
    """Each field the definition names can actually be found through the box.

    A field list is a promise, and the way this promise breaks is a field that is
    on the list and empty on every row — the reader types a login and finds
    nothing, and nothing anywhere says the field was never carried.
    """
    for entity in index.entities.values():
        for value in filter(None, [entity.id, entity.title, *entity.tags, *entity.prs]):
            assert entity.id in found_in_the_browser(page, value), (
                f"{entity.id} does not find itself by {value!r}"
            )
            assert entity.id in apply_filters(index, {}, value), (
                f"the server does not find {entity.id} by {value!r}"
            )
        break


# --------------------------------------------------------------------------- #
# The query language
# --------------------------------------------------------------------------- #


def ids(index: Index, query: str) -> list[str]:
    return apply_filters(index, {}, query)


def test_a_bare_word_is_a_substring_of_the_searchable_text(index: Index):
    """What the box always did, and it keeps doing it: the language is something
    a query grows into rather than something it has to opt into."""
    assert ids(index, "turbulence") == ids(index, "TURBULENCE")
    assert ids(index, "turbulence")
    assert ids(index, "no such word anywhere") == []


def test_a_field_asks_that_field_and_nothing_else(index: Index):
    """`owner:jcanton` is not `jcanton`: the second finds every record his name is
    on in any role, which is the whole reason a field is worth spelling out."""
    everywhere = set(ids(index, "jcanton"))
    owned = set(ids(index, "owner:jcanton"))

    assert owned < everywhere, "owner: found no fewer records than the bare word"
    assert all(index.entities[i].owner == "jcanton" for i in owned)


def test_two_tags_can_be_asked_for_at_once(index: Index):
    """The query the dropdowns cannot express. A menu means OR within a field, so
    "both of these tags" has no control on the page — it is why there is a
    language at all."""
    tags = [t for t in index.facets["tags"] if t != "(none)"]
    pairs = [
        (one, two)
        for one in tags
        for two in tags
        if one < two
        and any({one, two} <= set(e.tags) for e in index.entities.values())
    ]
    assert pairs, "no record in this corpus carries two tags, so this asks nothing"

    one, two = pairs[0]
    both = ids(index, f"tag:{one} and tag:{two}")
    assert both == sorted(
        i for i, e in index.entities.items() if {one, two} <= set(e.tags)
    )
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
    assert any(e.kind == "pitch" and e.status != "done" for e in index.entities.values())

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
    assert ids(index, "onwer:jcanton") == []
    assert ids(index, "owner:jcanton or onwer:jcanton") == ids(index, "owner:jcanton")


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
    assert asked == sorted(i for i, e in index.entities.items() if not e.cycle)


def test_a_pr_is_found_however_it_is_written(index: Index):
    """`#1364`, `1364` and the whole `C2SM/icon4py#1364` are one PR, and a person
    reading a review types whichever of the three is in front of them."""
    holders = [e for e in index.entities.values() if e.prs]
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
        "turbulence",
        "TURBULENCE",
        "port turbulence",
        "kind:task",
        "kind:task and status:ready",
        "kind:task status:ready",
        "kind:task or kind:pitch",
        "not kind:task",
        "not (kind:task or kind:pitch)",
        "kind:task and (status:ready or status:done)",
        "(kind:task and status:ready) or status:done",
        "owner:jcanton",
        "assignee:jcanton",
        "reviewer:jcanton",
        f"tag:{tags[0]}",
        f"tag:{tags[0]} and tag:{tags[1]}",
        f"tag:{tags[0]} or tag:{tags[1]}",
        'cycle:"(none)"',
        "onwer:jcanton",
        "id:pitch-0b0001",
        "title:porting",
        "pr:1364",
        "(kind:task",
        "kind:task and",
        "not",
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


def test_the_two_field_lists_are_the_same():
    """The language names the same fields in both places.

    A field in one list and not the other is `owner:jcanton` answering on the
    server and matching nothing in the table — the `(none)` sentinel's failure
    with a different name, which is why that one is pinned the same way.
    """
    from openproj.index import _HOLDER_FACETS, _LIST_FACETS, _SCALAR_FACETS
    from openproj.render import _FILTER_JS

    here = [*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS,
            "id", "title", "prs", "predicate"]
    said = re.search(r"const QUERY_FIELDS = \[([^\]]*)\]", _FILTER_JS).group(1)
    there = re.findall(r"'([^']+)'", said)

    assert sorted(there) == sorted(here), f"browser {sorted(there)}, server {sorted(here)}"


def test_the_aliases_and_the_free_text_fields_are_the_same():
    """The rest of the language's vocabulary, pinned the same way. An alias in one
    place only means `tag:gpu` narrows in the table and matches nothing through a
    link; a free-text field in one place only means `pr:1364` finds the record in
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
    ":jcanton",
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
