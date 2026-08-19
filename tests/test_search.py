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
    answer = run_js(
        page,
        "(() => { params.set('q', " + repr(query).replace("'", '"') + "); "
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
