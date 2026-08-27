"""The review deck: one cycle, one slide per piece of work in it.

The team built this by hand in Google Slides at the end of every cycle, out of
records that were already in the plan — so the deck said "PR#2427, under review"
beside a task whose `prs` and `status` said the same thing, and the copy in the
deck went stale the moment either moved. Generating it is the same argument that
made `blocks` derived rather than stored.

The claims here are about three different mediums and are asked in three
different places. What is *on* a slide is a question about a document, so it is
parsed rather than searched for: the shell inlines its own stylesheet into every
page, comments and all, and a substring test for "☑" or for a record id finds
its answer in a CSS comment as happily as in a slide. Which rule wins is asked of
`cascade.py`. And whether one slide really is one page is asked of Chrome, with
`--print-to-pdf`, because a `break-after: page` that resolves is still only a
promise about paper.
"""

from __future__ import annotations

import base64
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
from cascade import Sheet, _blocks, el, sheet_of

from openproj.index import Index, build_index
from openproj.model import (
    Config,
    Cycle,
    Pitch,
    Project,
    Record,
    Slide,
    Task,
    checklist,
    checklist_items,
    load_repo,
    without_checklist,
    without_sections,
)
from openproj.render import ROUTES, STATIC, STATUSES, render_cycle, render_deck
from openproj.render.deck import _deck_order
from openproj.render.tokens import PRIORITY_GLYPH, STATUS_GLYPH

TODAY = date(2026, 8, 17)


# --------------------------------------------------------------------------- #
# The deck, parsed
# --------------------------------------------------------------------------- #


class _Slides(HTMLParser):
    """Every `<article class="slide">`, as what a reader would say is on it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict] = []
        self._depth = 0
        self._where = ""
        self._text: list[str] = []

    def _slide(self) -> dict:
        return self.found[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if tag == "article" and "slide" in classes:
            self._depth = 1
            self.found.append(
                {
                    "classes": frozenset(classes),
                    "under": "",
                    "heading": "",
                    "points": [],
                    "prs": [],
                    "images": [],
                    "doc": "",
                    "note": "",
                    "text": [],
                }
            )
            return
        if not self._depth:
            return
        self._depth += 1
        if tag == "img":
            self._slide()["images"].append(found.get("src") or "")
        if tag == "a" and self._where == "prs":
            self._slide()["prs"].append(found.get("href") or "")
        # Where the parser is, so `handle_data` knows which bucket the words go
        # in. A list rather than a stack because none of these nest.
        if tag in ("h1", "h2") and not self._slide()["heading"]:
            self._where, self._text = "heading", []
        elif tag == "p" and "under" in classes:
            self._where, self._text = "under", []
        # The line about the slide rather than about the work: what was cut, or
        # that the record says nothing. Read as its own field, because a slide
        # saying it was cut and a slide that simply is short are two different
        # sheets and `text` cannot tell them apart.
        elif tag == "p" and "note" in classes:
            self._where, self._text = "note", []
        elif tag == "ul" and "points" in classes:
            self._where = "points"
        elif tag == "ul" and "prs" in classes:
            self._where = "prs"
        elif tag == "div" and "doc" in classes:
            self._where, self._text = "doc", []
        elif tag == "li" and self._where == "points":
            self._slide()["points"].append({"done": None, "text": ""})
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        said = " ".join("".join(self._text).split())
        if tag in ("h1", "h2") and self._where == "heading":
            self._slide()["heading"], self._where = said, ""
        elif tag == "p" and self._where == "under":
            self._slide()["under"], self._where = said, ""
        elif tag == "p" and self._where == "note":
            self._slide()["note"], self._where = said, ""
        elif tag == "li" and self._where == "points":
            point = self._slide()["points"][-1]
            # The box is the first character and is the tick itself: a test that
            # read the class would be reading the thing the class is drawn from
            # rather than the thing on the slide.
            point["done"] = said.startswith("☑")
            point["text"] = said.lstrip("☑☐ ")
        elif tag == "div" and self._where == "doc":
            self._slide()["doc"], self._where = said, ""
        elif tag == "ul" and self._where in ("points", "prs"):
            self._where = ""
        self._depth -= 1
        if not self._depth:
            self._where = ""

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._slide()["text"].append(data)
            if self._where:
                self._text.append(data)


def slides_in(page: str) -> list[dict]:
    """Each slide of a rendered deck, in the order it is presented."""
    parser = _Slides()
    parser.feed(page)
    for slide in parser.found:
        slide["text"] = " ".join("".join(slide["text"]).split())
    return parser.found


# --------------------------------------------------------------------------- #
# A corpus with progress in it
#
# The seed keeps no checklist anywhere, so it cannot say anything about the one
# thing a slide is mostly made of. Built here instead, and small enough that what
# each assertion is about is on the screen with it.
# --------------------------------------------------------------------------- #

BED = """## Problem

DRUMBED is Fortran and the interface is not.

## Progress

- [x] Read the tiling code
- [x] Generate the bindings
- [ ] Wire up the surface fluxes

## Notes

The gather/scatter seam is the one to watch.

![the driver](assets/0123456789abcdef.png)
"""


def corpus() -> list[Record]:
    project = Project(id="proj-000001", kind="project", title="Physics")
    bed = Pitch(
        id="pitch-0c0001",
        kind="pitch",
        title="Porting the bed",
        owner="ann",
        person_weeks=6.0,
        parent="proj-000001",
        status="in_progress",
        cycle=37,
        assigned_on=date(2026, 8, 17),
        reviewers=["bo"],
    )
    solver = Task(
        id="task-0c1001",
        kind="task",
        title="Port the bed solver",
        owner="ann",
        person_weeks=4.0,
        parent="pitch-0c0001",
        status="in_progress",
        assigned_on=date(2026, 8, 17),
        reviewers=["bo"],
        prs=["kilnlab/kiln4py#2427", "kilnlab/hearth#2765"],
        body=BED,
    )
    fluxes = Task(
        id="task-0c1002",
        kind="task",
        title="Coordinate with Kettleworth",
        owner="bo",
        person_weeks=1.0,
        parent="pitch-0c0001",
        status="done",
        assigned_on=date(2026, 8, 17),
        reviewers=["ann"],
        prs=["kilnlab/kiln4py#2403"],
    )
    # A chore nobody pitched: bettable in its own right, so its cycle is its own.
    chore = Task(
        id="task-0f0001",
        kind="task",
        title="Tidy the serialisation scripts",
        owner="cy",
        person_weeks=0.5,
        status="ready",
        cycle=37,
        reviewers=["ann"],
        body="## Progress\n\n- [ ] Move the docs out of the shared drive\n",
    )
    # Bet into a different cycle, and therefore on a different deck.
    other = Pitch(
        id="pitch-0d0001",
        kind="pitch",
        title="Aroma transport",
        owner="cy",
        person_weeks=2.0,
        status="ready",
        cycle=36,
        reviewers=["ann"],
    )
    return [project, bed, solver, fluxes, chore, other]


def plan_of(number: int = 37) -> Cycle:
    # The goal in the FIELD, and notes in the body, because they are two
    # documents — `Cycle.goal` exists so the goal is not "whatever happened to be
    # at the top of a growing document". This fixture used to carry the sentence
    # as `body="## Goal\n\n..."` and the deck read the body, so the two agreed by
    # accident and the deck's bug was invisible for as long as no cycle record
    # anywhere had a real `goal:` and a real body.
    return Cycle(
        cycle=number,
        starts_on=date(2026, 8, 17),
        reviews_on=date(2026, 9, 28),
        availability={"ann": 0.5, "bo": 1.0, "cy": 0.6},
        goal="The bed port is the one that cannot slip.",
        body="## Notes\n\nWhat the room said while betting.\n",
    )


@pytest.fixture
def index() -> Index:
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    return build_index(corpus(), config, TODAY)


@pytest.fixture
def deck(index: Index) -> str:
    return render_deck(index, 37, ROUTES)


@pytest.fixture
def demo_index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, TODAY)


@pytest.fixture
def golden_index(seed_root: Path) -> Index:
    """The frozen corpus, which is the only hand-written checklist in the suite."""
    records, config, _ = load_repo(seed_root)
    return build_index(records, config, TODAY)


# --------------------------------------------------------------------------- #
# What is on the deck
# --------------------------------------------------------------------------- #


def test_the_deck_is_a_title_slide_and_then_one_slide_per_piece_of_work(deck: str):
    """One per task, and not one per record: a pitch with tasks under it is a
    rollup of exactly those tasks, so a slide for it as well puts the same work
    on the screen twice — once as a summary nobody can act on, and again three
    slides later. It is the exclusion `Index.load` already makes."""
    found = slides_in(deck)

    assert [s["heading"] for s in found] == [
        "Cycle 37",
        # The bet first, then by id inside it — which is the order the pitch's
        # own progress panel lists the same tasks in.
        "Port the bed solver",
        "Coordinate with Kettleworth",
        "Tidy the serialisation scripts",
    ]
    assert "title" in found[0]["classes"]
    # The pitch these two belong to is a rollup and gets no slide of its own.
    assert not any("Porting the bed" == s["heading"] for s in found)


def test_a_slide_is_headed_by_what_the_work_belongs_to_and_then_by_itself(deck: str):
    """`[hearth] Features` — the real deck's own convention, typed by hand into
    sixteen titles. The bracket is the pitch, so nobody types it; and it is blank
    where the record IS the bet, because a bracket repeating the line under it is
    furniture."""
    under = {s["heading"]: s["under"] for s in slides_in(deck)}

    assert under["Port the bed solver"] == "Porting the bed"
    assert under["Coordinate with Kettleworth"] == "Porting the bed"
    # A chore nobody pitched is its own bet.
    assert under["Tidy the serialisation scripts"] == ""


def test_the_slides_of_one_bet_are_consecutive(index: Index):
    """Which is what the bracket in the real deck's titles was doing by hand:
    four hearth slides in a row, and then four kiln4py ones. Ordered by id alone
    they interleave, and a deck that jumps between two subjects and back is a
    deck the room cannot follow."""
    more = corpus() + [
        Task(
            id="task-0a0001",
            kind="task",
            title="A chore",
            owner="cy",
            person_weeks=1.0,
            status="ready",
            cycle=37,
            reviewers=["ann"],
        ),
    ]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    headings = [
        s["heading"] for s in slides_in(render_deck(build_index(more, config, TODAY), 37, ROUTES))
    ]

    bed = [
        at
        for at, name in enumerate(headings)
        if name in ("Port the bed solver", "Coordinate with Kettleworth")
    ]
    assert bed == [min(bed), min(bed) + 1], headings


def test_a_slide_shows_the_points_ticked_and_the_share_the_index_counted(deck: str):
    """The tick and the percentage are `index.progress`, which counted them once
    for the table, the detail page and this. Counting them again here is how the
    number above a list and the ticks in it come to disagree."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port the bed solver")

    assert slide["points"] == [
        {"done": True, "text": "Read the tiling code"},
        {"done": True, "text": "Generate the bindings"},
        {"done": False, "text": "Wire up the surface fluxes"},
    ]
    # Said in words beside the meter, because a bar alone says "some".
    assert "2/3" in slide["text"]
    assert 'style="width: 67%"' in deck


def test_the_points_are_drawn_once_and_not_twice(deck: str):
    """The detail page does not lift a leaf's checklist at all, precisely so that
    it is not printed above the document and inside it. A slide has to lift it —
    `[x]` read from the back of a room is not a tick — so the notes below must
    lose it, heading and all."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port the bed solver")

    assert slide["doc"], "the notes are the rest of the body and must still be there"
    assert "Wire up the surface fluxes" not in slide["doc"]
    assert "The gather/scatter seam is the one to watch." in slide["doc"]
    # The heading the template puts the list under is emptied by taking it away.
    assert "Progress" not in slide["doc"]


def test_a_slide_carries_the_notes_and_not_the_shaping_argument(deck: str):
    """Problem, Appetite, Rabbit holes and No-gos are the bet: written before the
    work started, to argue for it at the betting table where everybody in the
    room already argued them. Printed on a slide they are two pages of prose
    nobody can read from the third row and nobody is going to talk through —
    three of seven slides ran onto a second sheet before this, which is the one
    thing a deck must not do. What leads is what somebody wrote about what
    happened."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port the bed solver")

    assert "DRUMBED is Fortran" not in slide["doc"], "the Problem section is the bet"
    assert "Problem" not in slide["doc"]
    assert "The gather/scatter seam is the one to watch." in slide["doc"]
    # And the record is on the slide, because that is where the argument is.
    assert "task-0c1001" in slide["text"]


def test_the_sections_a_slide_leaves_out_are_read_off_the_templates():
    """Derived from the code rather than listed beside it: a section added to
    `TEMPLATES` reaches the deck on the commit that adds it. A list written by
    hand is a list that goes stale, and going stale here means a whole shaping
    argument back on a slide.

    Minus `## Progress`, which is in the task template and is the one heading a
    review is written under. Dropping it with the rest is what made the deck
    delete the only section it existed to show."""
    from openproj.model import RUNG
    from openproj.render import TEMPLATES, _bet_headings

    found = _bet_headings()

    assert {"problem", "appetite", "solution", "rabbit holes", "no-gos", "for later"} == found
    assert "progress" not in found
    # Skipping the kinds that carry no shaping document at all: a product is a
    # container — `RUNG["product"].carded is False`, which is also why it shows no
    # hover card — and it never reaches a slide, so its template is a sentence
    # about the codebase rather than an argument under headings. Read off the
    # ladder and not spelled `!= "product"`, so a later rung of the same sort is
    # covered on the commit that adds it.
    for name, body in TEMPLATES.items():
        if name in RUNG and not RUNG[name].carded:
            continue
        assert not without_sections(body, found | {"progress"}).strip("# \n"), body[:40]


def test_the_progress_section_is_what_a_review_slide_is_for(index: Index):
    """The checklist is lifted to the points at the top, and whatever else
    somebody wrote under `## Progress` is the sentence they are about to say out
    loud. It was being deleted along with the rest of the template."""
    said = Task(
        id="task-0c1001",
        kind="task",
        title="Port the bed solver",
        owner="ann",
        person_weeks=4.0,
        parent="pitch-0c0001",
        status="in_progress",
        assigned_on=TODAY,
        reviewers=["bo"],
        body="## Problem\n\nFortran.\n\n## Progress\n\n- [x] Bindings\n\n"
        "Blocked on a tap point nobody has generated yet.\n",
    )
    other = [e for e in corpus() if e.id != "task-0c1001"]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    found = slides_in(render_deck(build_index([*other, said], config, TODAY), 37, ROUTES))
    slide = next(s for s in found if s["heading"] == "Port the bed solver")

    assert "Blocked on a tap point nobody has generated yet." in slide["doc"]
    assert "Fortran" not in slide["doc"]
    # Lifted to the points, so it is not printed twice.
    assert [p["text"] for p in slide["points"]] == ["Bindings"]
    assert "Bindings" not in slide["doc"]


def test_a_task_that_is_still_this_tools_own_template_has_a_slide_to_present():
    """Built from `_TASK_TEMPLATE` and deliberately not from a body written here,
    because a hand-written body is what kept this out of sight for a whole round:
    a body typed into a test gets a trailing space after `- [ ]` without anybody
    deciding to put one there, and that space was the whole difference.

    The template ends `## Progress\\n\\n- [ ]` at the end of the file. Every check
    that reads a checklist wanted whitespace after the bracket, so that line was
    not a point — not counted, and not lifted out of the notes — and `## Progress`
    was therefore never emptied. It is the one template heading the deck keeps, so
    a task nobody has typed a word into printed as a heading over the literal
    characters `[ ]`: the blank slide of the round before, respelt."""
    from openproj.render import _TASK_TEMPLATE

    fresh = Task(
        id="task-0f0002",
        kind="task",
        title="Nobody wrote this one down",
        owner="cy",
        person_weeks=1.0,
        status="ready",
        cycle=37,
        reviewers=["ann"],
        body=_TASK_TEMPLATE,
    )
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    page = render_deck(build_index([*corpus(), fresh], config, TODAY), 37, ROUTES)
    slide = next(s for s in slides_in(page) if s["heading"] == "Nobody wrote this one down")

    assert "[ ]" not in slide["text"], "a checkbox printed as its own source"
    assert "Progress" not in slide["text"], "a heading with nothing left under it"
    assert slide["doc"] == ""
    # Empty is not broken and it is not a failure: the sheet says which it is,
    # because the person holding it cannot go and look.
    assert slide["note"] == "Nothing is written on this record."
    # And the box the template ships is a point like any other, everywhere the
    # points are counted — which is the part of this that is not about the deck.
    assert slide["points"] == [{"done": False, "text": ""}]
    assert "0/1" in slide["text"]


def test_a_heading_the_bet_emptied_is_not_printed_over_blank_paper():
    """The prune that takes away a heading with nothing under it runs inside
    `without_checklist`, one step BEFORE the sections that are the bet come out —
    so a heading emptied by *that* drop was never pruned at all. A `## Notes`
    whose only content was a `### Solution` written under it arrived as
    `<h2>Notes</h2>` and nothing else, and was truthy enough to suppress the
    fallback that exists to stop exactly this."""
    only = Task(
        id="task-0c1001",
        kind="task",
        title="Port the bed solver",
        owner="ann",
        person_weeks=4.0,
        parent="pitch-0c0001",
        status="in_progress",
        assigned_on=TODAY,
        reviewers=["bo"],
        body="## Notes\n\n### Solution\n\nThe plan lives here.\n",
    )
    others = [e for e in corpus() if e.id != "task-0c1001"]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    page = render_deck(build_index([*others, only], config, TODAY), 37, ROUTES)
    slide = next(s for s in slides_in(page) if s["heading"] == "Port the bed solver")

    assert "Notes" not in slide["doc"], "a heading whose whole content was the bet"
    assert slide["doc"], "and therefore nothing at all was left to print"
    # What is left of this record IS its plan, so the plan is what it says — under
    # the heading that stops the room mistaking it for a report.
    assert slide["doc"].startswith("Solution")
    assert "The plan lives here." in slide["doc"]


def test_a_pull_request_on_a_slide_is_a_link_to_the_pull_request(deck: str):
    """A dead reference teaches people the field is decorative, and the deck is
    where the field is most read: the real one links a PR on nearly every slide.
    The same `_pr_link` the facts list uses, so the two cannot point differently."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port the bed solver")

    assert slide["prs"] == [
        "https://github.com/kilnlab/kiln4py/pull/2427",
        "https://github.com/kilnlab/hearth/pull/2765",
    ]


def test_the_title_slide_names_the_cycle_its_review_and_what_it_was_for(deck: str):
    """The real deck's first slide is "Cycle 37 - 07/26 Review" and nothing else,
    because its goal lived in a different tool. Here the goal is on the cycle
    record, and a review that opens by saying what the cycle was for is the one
    thing the room needs before the first slide."""
    title = slides_in(deck)[0]

    assert title["heading"] == "Cycle 37"
    assert "Review" in title["text"]
    # The app's own format, not the file's — jcanton, 2026-08-25.
    assert "28.09.2026" in title["text"]
    assert "The bed port is the one that cannot slip." in title["text"]


def test_a_review_date_nobody_chose_is_not_printed_as_though_somebody_had(index: Index):
    """Two different silences, and they are not the same sentence. A cycle with a
    record that names no review meeting has no date to print, so the slide says
    that. A cycle nobody wrote a record for gets the date `_proposed` works out
    the same way the cycle page does — and it is marked assumed, because the
    sheet in front of the room is exactly where a guess stops looking like one."""
    silent = Config(known_people=["ann"]).with_plans(
        [Cycle(cycle=37, starts_on=date(2026, 8, 17), availability={"ann": 1.0})]
    )
    said = slides_in(render_deck(build_index(corpus(), silent, TODAY), 37, ROUTES))[0]

    assert "No review meeting recorded" in said["text"]
    assert "assumed" not in said["text"], "there is no date here to have assumed"

    # Cycle 41 has no record at all, so every date on it is worked out.
    guessed = slides_in(render_deck(index, 41, ROUTES))[0]

    assert "assumed" in guessed["text"]
    assert re.search(r"\d{2}\.\d{2}\.\d{4}", guessed["text"]), guessed["text"]


def test_work_bet_into_another_cycle_is_on_another_deck(deck: str):
    """A deck is a cycle review. `cycle:` records where a bet was made and is
    never re-stamped, so this is the same question every page asks."""
    assert "Aroma transport" not in " ".join(s["text"] for s in slides_in(deck))
    assert "pitch-0d0001" not in deck


def test_a_review_shows_what_was_finished_and_what_was_parked(index: Index):
    """`counts_in` is the wrong question here and this is why: it drops `done`
    and `shelved` because it exists to add up weeks still to be spent. A review
    is about what happened, so finished work is the most interesting thing on it
    and parked work is a decision the room will be asked about."""
    from openproj.model import Task as T

    parked = T(
        id="task-0f0002",
        kind="task",
        title="Circuit broken",
        owner="cy",
        person_weeks=1.0,
        status="shelved",
        cycle=37,
    )
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    headings = [
        s["heading"]
        for s in slides_in(render_deck(build_index(corpus() + [parked], config, TODAY), 37, ROUTES))
    ]

    assert not any(index.counts_in(e, 37) for e in (parked,))
    assert "Coordinate with Kettleworth" in headings, "a done task is what a review is about"
    assert "Circuit broken" in headings, "a shelved bet is a decision, not an absence"


def test_a_cycle_holding_nothing_says_so_and_offers_the_way_out(index: Index):
    """Finding F1, which keeps coming back through new mechanisms: a filter
    matching nothing, a plan that failed to load and a cycle nobody has bet into
    are three different sentences. An empty deck that is a title slide over a
    blank page reads as a page that broke."""
    empty = slides_in(render_deck(index, 41, ROUTES))

    assert len(empty) == 2, "the title slide, and one saying why there are no others"
    assert "Nothing is bet into cycle 41" == empty[1]["heading"]
    assert "/cycle/41" in render_deck(index, 41, ROUTES)


# --------------------------------------------------------------------------- #
# A deck is a file somebody sends on
# --------------------------------------------------------------------------- #


PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cf000001010100b6d4b1fb0000000049454e44ae426082"
)
B64 = base64.b64encode(PIXEL).decode("ascii")


def test_a_screenshot_travels_inside_the_deck(index: Index):
    """Every other page names a path, because it sits beside the directory the
    path resolves against — `/assets/` on the server, the copied folder in an
    export. A deck is mailed to the people who were not in the room, and a
    screenshot that only resolves next to its own repository does not arrive."""
    page = render_deck(index, 37, ROUTES, lambda name: PIXEL if "0123" in name else None)
    slide = next(s for s in slides_in(page) if s["heading"] == "Port the bed solver")

    assert slide["images"] == [f"data:image/png;base64,{B64}"]
    # Nothing is left pointing at a directory that will not be there.
    assert "/assets/" not in page


def test_bytes_that_will_not_come_back_cost_the_picture_and_not_the_page(index: Index):
    """An asset that has been deleted, or a reader that has nothing to read from
    — the test that renders every entry point passes no reader at all. A missing
    image must fall back to what every other page draws, not to a traceback."""
    for read in (None, lambda name: None):
        page = render_deck(index, 37, ROUTES, read)
        slide = next(s for s in slides_in(page) if s["heading"] == "Port the bed solver")

        assert slide["images"] == ["/assets/0123456789abcdef.png"]


def test_the_media_type_of_an_asset_is_not_written_down_twice(index: Index):
    """The pattern that decides what an asset IS is built from the map that says
    what to call it. Written separately, a fifth format added to one and forgotten
    in the other is an image that draws on the site and silently stops travelling
    — which nobody would find until a deck arrived somewhere without it."""
    from openproj.render import _ASSET_MEDIA, _EMBED_SRC

    for suffix in _ASSET_MEDIA:
        assert _EMBED_SRC.fullmatch(f"assets/0123456789abcdef{suffix}"), suffix
    assert not _EMBED_SRC.fullmatch("assets/0123456789abcdef.svg")


def test_the_deck_reaches_no_network(index: Index):
    """The rule the whole of `static/` exists for, asked of the page most likely
    to be opened on a train, from a download folder, off a memory stick."""
    page = render_deck(index, 37, ROUTES, lambda name: PIXEL)

    assert not re.search(r"<script[^>]+src\s*=", page)
    assert not re.search(r"""<link[^>]+href\s*=\s*["']https?://""", page)
    assert not re.search(r"""<img[^>]+src\s*=\s*["'](?!data:)[^"']*//""", page)
    assert "Content-Security-Policy" in page


# --------------------------------------------------------------------------- #
# Where it sits in the app
# --------------------------------------------------------------------------- #


def test_the_deck_is_not_in_the_nav_and_lights_the_cycle_it_is_of(deck: str):
    """The nav names the views of the whole plan. A deck is one cycle's
    handout, reached from that cycle's page — the same reasoning `/cycle/<n>`
    already carries, which lights Cycles rather than growing a seventh tab."""
    from pages import lit, nav_of

    assert lit(deck) == ["Cycles"]
    assert not any(label == "Deck" for label, _, _ in nav_of(deck))


def test_the_cycle_page_offers_the_deck_only_where_there_is_one(index: Index):
    """`links.deck` is empty in a static export for the reason `links.new` is:
    the export writes one file per view of the whole plan and has nowhere to put
    a cycle number. A link to a file nobody wrote is worse than no link."""
    assert "/deck/37" in render_cycle(index, 37, ROUTES, base_commit="deadbee")
    assert "deck" not in re.findall(r'href="([^"]*)"', render_cycle(index, 37, STATIC))


def test_no_slide_in_the_shipped_demo_is_a_heading_over_an_empty_page(demo_index: Index):
    """The defect this whole design was rewritten for, asked of the corpus the
    commit itself names.

    A well-shaped record IS the shaping template — Problem, Appetite, Solution,
    Rabbit holes, No-gos and nothing else — so selecting a slide's body by taking
    the template away took the whole document away with it. Rendering `seed/` at
    cycle 37 produced seven slides of which FIVE carried a heading, a status
    chip, a size, an owner and an id over blank paper, and printed to A4 they
    were five empty sheets. The demo keeps no checklist anywhere, which is why it
    is the corpus that finds this: there were no points to fall back on either.

    Eleven now — the four bets the demo grew into cycle 37 on 2026-08-23. The
    count is the demo's and moves whenever the demo does, which is exactly why
    the claim below is about blankness and not about the number.

    So the assertion is not that a page was returned. It is that every slide has
    something on it a person could stand up and read out — a sentence of prose,
    or ticked points, or a pull request — and enough of it to be worth a sheet of
    paper."""
    found = slides_in(render_deck(demo_index, 37, ROUTES))
    work = found[1:]

    assert len(found) == 11, [s["heading"] for s in found]
    assert "CI for the standalone driver v1.5" in [s["heading"] for s in found]

    blank = [s["heading"] for s in work if not s["points"] and not s["prs"] and len(s["doc"]) < 80]
    assert blank == [], f"{len(blank)} of {len(work)} slides have nothing to present"


def test_every_slide_of_the_frozen_corpus_is_worth_the_sheet_it_prints_on(
    golden_index: Index,
):
    """The same claim as the demo's above, made where it can be held to. `seed/`
    is the demo and conftest says in as many words that it is free to be
    rewritten, so a count of words asserted against it is a count that goes stale
    on somebody's copy edit. The frozen corpus is the one that has to stop
    moving, and it is the only prose in this suite nobody wrote for a test.

    What it holds is that every slide gives the presenter something: enough of
    the record's own words to stand up and read out, or points to walk, or a pull
    request to open. The cycles come off the corpus rather than being listed, so
    a cycle added to it is covered by the commit that adds it."""
    for number in sorted({e.cycle for e in golden_index.plan.values() if e.cycle}):
        found = slides_in(render_deck(golden_index, number, ROUTES))

        assert len(found) > 1, number
        for slide in found[1:]:
            # Words, and the record's own words: the heading, the chip and the id
            # are already excluded by reading `doc` rather than `text`.
            assert len(slide["doc"].split()) >= 20 or slide["points"] or slide["prs"], (
                number,
                slide["heading"],
            )


def test_a_record_that_is_only_its_bet_falls_back_to_what_it_was_going_to_do(
    demo_index: Index,
):
    """Nobody wrote a note under any of these, so the Solution is what is left:
    the plan, in the team's own words, which is exactly what the presenter is
    about to say happened or did not. Problem is why, Appetite is how long,
    Rabbit holes and No-gos are the edges — none of them is the question the room
    is asking.

    It keeps its own heading so that nobody in the room mistakes the plan for a
    report of it."""
    slide = next(
        s
        for s in slides_in(render_deck(demo_index, 37, ROUTES))
        if s["heading"] == "Port the bed solver"
    )

    assert slide["doc"].startswith("Solution")
    assert "Finish the forward-elimination half" in slide["doc"]
    # And still not the rest of the argument.
    assert "The first slice of DRUMBED" not in slide["doc"], "Problem is the bet"
    assert "Do not write a fourth TDMA" not in slide["doc"], "Rabbit holes are the bet"


def long_plan(paragraphs: int = 12) -> str:
    """A Solution nobody ever wrote a note against, at the length people write
    them: the frozen corpus already carries two of 232 and 301 words."""
    said = "The tap-point interface is the seam nobody has looked at yet."
    return "## Solution\n\n" + "\n\n".join(
        f"Step {n}. " + " ".join([said] * 4) for n in range(paragraphs)
    )


def test_the_plan_a_slide_falls_back_to_is_cut_to_the_sheet_and_says_so(tmp_path: Path):
    """The fallback is a floor and not a licence to print a whole section. Left
    unbounded it hands back the one thing a deck must not do — `_review`'s own
    docstring is where that phrase comes from — and the corpus is already close:
    printed with Chrome, a slide carrying six points and two pull requests
    crosses onto a second sheet between 201 and 211 rendered words, and the
    frozen corpus is at 206 on one slide of cycle 28.

    So it is bounded, and because a slide that silently prints half a section is
    its own lie, the sheet says so. Asked of paper, because the claim is about
    paper: this record's Solution is five hundred words and its slide is one
    sheet with a line on it saying where the rest is."""
    from browser import chrome, printed

    plan = long_plan()
    unread = Task(
        id="task-0c1002",
        kind="task",
        title="Coordinate with Kettleworth",
        owner="bo",
        person_weeks=1.0,
        parent="pitch-0c0001",
        status="done",
        assigned_on=TODAY,
        reviewers=["ann"],
        body=plan,
    )
    others = [e for e in corpus() if e.id != "task-0c1002"]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    page = render_deck(build_index([*others, unread], config, TODAY), 37, ROUTES)
    slide = next(s for s in slides_in(page) if s["heading"] == "Coordinate with Kettleworth")
    where = tmp_path / "long.html"
    where.write_text(page, encoding="utf-8")

    assert len(plan.split()) > 500, "the case is a section that cannot fit"
    assert printed(chrome(), where, tmp_path / "long.pdf") == len(slides_in(page))
    assert slide["note"] == "Cut to fit the sheet — the rest of the plan is on the record."
    # Cut, and still the plan: the top of the section is what the room is read.
    assert slide["doc"].startswith("Solution")
    assert "Step 0." in slide["doc"]
    assert "Step 11." not in slide["doc"]


def test_a_note_somebody_wrote_beats_the_plan_it_would_have_fallen_back_to(deck: str):
    """The fallback is a floor and not a preference. Where there is a note about
    what happened, that is the slide; the Solution appears only where the record
    said nothing else at all."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port the bed solver")

    assert "The gather/scatter seam is the one to watch." in slide["doc"]
    assert "Solution" not in slide["doc"]


def test_a_hand_written_checklist_reaches_the_slide_it_belongs_to(golden_index: Index):
    """Against the frozen corpus, whose checklists are the only ones in this
    suite nobody wrote for a test — sub-items, `[X]` in capitals, items outside
    `## Progress`. A generated deck that only works on the fixture it was written
    beside is not a deck."""
    found = slides_in(render_deck(golden_index, 36, ROUTES))
    ticked = {s["heading"]: s["points"] for s in found if s["points"]}

    assert ticked, [s["heading"] for s in found]
    for heading, points in ticked.items():
        record = next(e for e in golden_index.plan.values() if e.title == heading)
        counted = golden_index.progress[record.id]

        assert len(points) == counted.total, heading
        assert sum(1 for p in points if p["done"]) == counted.done, heading
        assert all(p["text"] for p in points), heading


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #

# One task bet into cycle 37, because `test_web`'s corpus stamps no cycle on
# anything and a deck of nothing cannot say whether the route works.
BET = "tasks/task-c00009.md"
BET_ID = "task-c00009"
BET_FILE = (
    "---\n"
    "id: task-c00009\n"
    "kind: task\n"
    "title: Distributed output\n"
    "status: in_progress\n"
    "owner: ann\n"
    "reviewers: [bo]\n"
    "assigned_on: 2026-08-17\n"
    "person_weeks: 2\n"
    "cycle: 37\n"
    'prs: ["kilnlab/kiln4py#2403"]\n'
    "---\n"
    "\n## Progress\n\n- [x] Gather to rank 0\n- [ ] Parallel netCDF\n"
)


@pytest.fixture
def served(tmp_path: Path):
    """The server, against a plan with one bet in cycle 37 and somebody signed in."""
    import pygit2
    from fastapi.testclient import TestClient
    from test_store import commit_directly
    from test_web import ANN, SECRET, SEED

    from openproj.auth import sign_session
    from openproj.web import SESSION_COOKIE, create_app

    repo = tmp_path / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    commit_directly(repo, SEED | {BET: BET_FILE}, "seed the corpus")
    with TestClient(create_app(repo, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client, repo


def test_a_deck_is_bounded_to_the_cycles_that_can_exist(served):
    """`int` admits -1 and 99999, and `/cycle/{number}` already carries the
    comment about what happens when a read path and a write path disagree about
    which cycles there are. Two routes taking one number is two places to forget
    it, so this asks the route rather than trusting the pattern is still there."""
    client, _ = served

    assert client.get("/deck/37").status_code == 200
    assert client.get("/deck/99999").status_code == 404
    assert client.get("/deck/-1").status_code == 404
    # A cycle nobody has written a record for still has a deck, for the same
    # reason it still has a page: the plan names it.
    assert client.get("/deck/41").status_code == 200
    assert "Distributed output" in client.get("/deck/37").text


def test_an_uploaded_screenshot_is_served_into_the_deck_as_bytes(served):
    """End to end through the store, because the reader the route hands
    `render_deck` is the one thing a test of the renderer alone cannot check.
    Uploaded through `/api/asset` and written into a body through the same PATCH
    a person's paste uses, so this is the path a screenshot actually takes."""
    from test_web import git_head

    client, repo = served
    uploaded = client.post("/api/asset", content=PIXEL, headers={"Content-Type": "image/png"})
    assert uploaded.status_code == 200, uploaded.text
    path = uploaded.json()["path"]

    saved = client.patch(
        f"/api/record/{BET_ID}",
        json={
            "base_commit": git_head(repo),
            "fields": {},
            "body": f"## Progress\n\n- [x] Gather to rank 0\n\n## Notes\n\n![a run]({path})\n",
        },
    )
    assert saved.status_code == 200, saved.text

    deck = client.get("/deck/37").text
    slide = next(s for s in slides_in(deck) if s["heading"] == "Distributed output")

    assert slide["images"] == [f"data:image/png;base64,{B64}"]
    # And the detail page still names the path, because it is served beside it.
    assert f'src="/{path}"' in client.get(f"/detail/{BET_ID}").text


# --------------------------------------------------------------------------- #
# Counting once
# --------------------------------------------------------------------------- #


def test_the_points_on_a_slide_are_the_ones_the_meter_counted():
    """Derived from the code rather than restated beside it: `checklist` is now
    `checklist_items` summed, so there is one parse of one document. Two walks of
    the same lines is two answers to "how many", and the slide draws one of them
    directly under the other."""
    bodies = [
        BED,
        "- [X] upper\n- [ ] lower\n",
        "",
        "no list at all",
        "```\n- [x] an example, not a point\n```\n",
    ]

    for body in bodies:
        items = checklist_items(body)
        assert checklist(body) == (sum(1 for done, _ in items if done), len(items)), body


def test_taking_the_points_out_leaves_the_prose_and_the_fences_alone():
    """A shaping document that quotes a markdown snippet keeps its example: a
    fence is where a document talks ABOUT a checklist rather than keeping one,
    which is the distinction `_outside_code` exists for."""
    body = "## Progress\n\n- [ ] a point\n\n## How\n\n```\n- [ ] an example\n```\n"

    left = without_checklist(body)

    assert "a point" not in left
    assert "an example" in left
    assert "## How" in left
    assert "## Progress" not in left, "a heading emptied by taking the list away"


# --------------------------------------------------------------------------- #
# What the cascade resolves to, and what Chrome actually prints
# --------------------------------------------------------------------------- #


SLIDE = [el("body"), el("main", id="main"), el("article", "slide")]


def test_a_link_on_a_slide_is_drawn_against_paper_and_not_against_the_theme(deck: str):
    """A slide is white in every theme, so the shell's link colour — chosen
    against the page's own ground — is the wrong ink on it. `.slide a` is (0,1,1)
    against the shell's `a` at (0,0,1) and `a:visited` at (0,0,2), so it wins on
    specificity whichever order the two are inlined in."""
    sheet = sheet_of(deck)

    for states in ("", "visited"):
        link = SLIDE + [el("a", states=states)]
        assert sheet.value(link, "color") == "var(--paper-link)", (
            states,
            sheet.selectors_reaching(link, "color"),
        )
    assert sheet.value(SLIDE, "background") == "var(--paper)"
    assert sheet.value(SLIDE, "color") == "var(--paper-ink)"


def test_paper_is_defined_where_every_reader_matches_it(deck: str):
    """Colours are tokens defined in three blocks, and nothing may have its only
    definition inside one that half the readers never match. These are the other
    case: one definition, in bare `:root`, deliberately identical under every
    theme — because a slide is a sheet of paper and paper has no theme. What this
    holds is that no theme block redefines one, which is what would make a deck
    come out ink-on-black for whoever had chosen dark."""
    style = re.search(r"<style>(.*?)</style>", deck, re.S).group(1)
    # The one bare `:root` block that carries them, and every definition of a
    # paper token anywhere in the served stylesheet. `--paper…:` and not
    # `--paper`, because the print block reads them with `var(--paper)` — a use
    # is not a redefinition, and a test that cannot tell the two apart fails on
    # the rule it was written to allow.
    bare = re.search(r"\n:root \{([^}]*--paper:[^}]*)\}", style)

    assert bare, "the paper block moved, so this proves nothing"
    assert "--paper: #ffffff" in bare.group(1)
    assert re.search(r':root\[data-theme="dark"\] \{', style), "so do the theme blocks"
    assert re.findall(r"--paper[\w-]*\s*:", bare.group(1)) == re.findall(
        r"--paper[\w-]*\s*:", style
    ), "a paper token is defined somewhere a reader can fail to match"


def test_every_deck_this_suite_can_reach_prints_one_slide_to_a_page(
    deck: str, demo_index: Index, golden_index: Index, tmp_path: Path
):
    """The claim is about paper, so it is asked of paper. A `break-after: page`
    that resolves is a promise a stylesheet cannot keep on its own — the same
    trap the frozen column's edge fell into, where the asserted value resolved
    exactly and Chrome painted nothing at all.

    Of every corpus and not only of the fixture above, which is three lines a
    record and could not overflow a sheet if it tried. `seed/` is what anybody
    points this at first, and the frozen corpus is the only prose in the suite
    nobody wrote for a test: 206 rendered words on one slide of cycle 28, which
    is about where the cliff turns out to be. A bound argued from a measurement
    is worth what the measurement is re-run against."""
    from browser import chrome, printed

    browser = chrome()
    decks = {"the fixture": deck, "seed 37": render_deck(demo_index, 37, ROUTES)}
    decks |= {
        f"corpus {number}": render_deck(golden_index, number, ROUTES)
        for number in sorted({e.cycle for e in golden_index.plan.values() if e.cycle})
    }

    for name, page in decks.items():
        where = tmp_path / f"{name.replace(' ', '-')}.html"
        where.write_text(page, encoding="utf-8")
        slides = len(slides_in(page))

        assert printed(browser, where, where.with_suffix(".pdf")) == slides, name


def test_a_point_is_a_line_of_markdown_and_is_rendered_as_one(index: Index):
    """The corpus writes `` `bed_setup` `` and `kilnlab/kiln4py#2403` inside its
    points, and the real deck links exactly those references from exactly those
    bullets. Taken as plain text a point came out with literal backticks and a
    dead reference — the field looking decorative, which is the thing `_pr_link`
    exists to stop."""
    more = [e for e in corpus() if e.id != "task-0f0001"] + [
        Task(
            id="task-0f0001",
            kind="task",
            title="Tidy the serialisation scripts",
            owner="cy",
            person_weeks=0.5,
            status="ready",
            cycle=37,
            reviewers=["ann"],
            body="- [ ] call `inspect_tappoints` from kilnlab/kiln4py#2409\n",
        ),
    ]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    page = render_deck(build_index(more, config, TODAY), 37, ROUTES)
    slide = next(s for s in slides_in(page) if s["heading"] == "Tidy the serialisation scripts")

    assert "<code>inspect_tappoints</code>" in page
    assert slide["prs"] == [], "the links inside a point are not the PR field"
    assert "https://github.com/kilnlab/kiln4py/pull/2409" in page
    # And it stays on the row with its own tick rather than starting a paragraph.
    assert '<li class=""><span class="box" aria-hidden="true">☐</span><p>' not in page


def test_a_heading_inside_the_notes_is_not_drawn_at_the_size_of_the_slides_own(deck: str):
    """`.slide h2` and `_DETAIL_STYLE`'s `.doc h2` are both (0,1,1), and this
    stylesheet is inlined second, so the descendant selector took the tie and
    drew every heading in the body at 1.9rem — a `## Solution` shouting over the
    title it is written under. It matters now that a slide falls back to a
    section of the record and prints that section's own heading.

    Fixed by scoping and not by weight: `.slide > h2` does not enter `.doc` at
    all, so `.doc h2` wins by being the only rule that matches it."""
    sheet = sheet_of(deck)
    own = SLIDE + [el("h2")]
    inside = SLIDE + [el("div", "doc"), el("h2")]

    assert sheet.value(own, "font-size") == "1.9rem", sheet.selectors_reaching(own, "font-size")
    assert sheet.value(inside, "font-size") == "1rem", sheet.selectors_reaching(inside, "font-size")


def test_a_status_on_a_slide_is_a_word_and_not_the_ladder(deck: str):
    """The status fills are a luminance ladder measured against the PAGE, so
    on a white slide under the dark theme the chip came out a solid dark pill
    among hairlines — the app's own device drawn against a ground it was never
    measured on. The ladder exists because a graph node and a timeline bar have
    no words in them; a slide has nothing but words.

    `.slide .who .chip` is (0,3,0) against the shell's `.chip.st-ready` at
    (0,2,0), so it wins on specificity and not on the order two stylesheets
    happen to be inlined in — and one rule beats every rung at once, which is the
    property worth asserting: the override is status-agnostic by design, so it is
    asked about the whole ladder rather than about the words that were on it the
    day it was written."""
    sheet = sheet_of(deck)

    for status in STATUSES:
        chip = SLIDE + [el("p", "who"), el("span", f"chip st-{status}")]
        assert sheet.value(chip, "background") == "transparent", (
            status,
            sheet.selectors_reaching(chip, "background"),
        )
        assert sheet.value(chip, "color") == "var(--paper-muted)", status


def paper_sheet(page: str) -> Sheet:
    """The rules that apply on paper, asked of the same cascade engine.

    Not the `@media print` block on its own, which is the mistake this helper was
    written with the first time: a print rule does not replace the stylesheet, it
    is *added* to it, and everything the shell says unconditionally still
    applies. Asked as a sheet of one block, `:root { color-scheme: light }` won
    trivially because it was the only rule in it — and the thing it has to beat,
    `:root[data-theme="dark"]` in the shell, was not in the sheet at all. Both
    mutations of the fix passed.

    So: the unconditional rules in document order, with the print block unwrapped
    where it sits, and every other at-rule dropped because it answers a different
    condition. This is the one claim Chrome cannot be asked for —
    `--print-to-pdf` says how many sheets came out, not what colour the canvas
    under them was.
    """
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    on_paper = "".join(
        body
        if prelude == "@media print"
        else ""
        if prelude.startswith("@")
        else f"{prelude}{{{body}}}"
        for prelude, body in _blocks(style)
    )
    return Sheet(on_paper)


def test_a_deck_prints_on_paper_whatever_theme_it_was_read_in(deck: str):
    """Found by printing one. `color-scheme` is what paints the canvas beneath
    everything a stylesheet draws, so a deck printed from the dark theme came out
    as white slides on a solid black page — a cartridge per handout, and every
    margin black.

    The shell's `:root[data-theme="dark"]` is (0,1,1), which a bare `:root` at
    (0,1,0) loses to however late it is inlined. So the print block names both,
    and this asks the engine which one wins rather than looking for the text."""
    paper = paper_sheet(deck)

    for described in (
        el("html", states="root"),
        el("html", states="root", data_theme="dark"),
        el("html", states="root", data_theme="light"),
    ):
        assert paper.value([described], "color-scheme") == "light", (
            described,
            paper.selectors_reaching([described], "color-scheme"),
        )
    for tag in ("html", "body"):
        assert paper.value([el(tag)], "background") == "var(--paper)", tag


# --------------------------------------------------------------------------- #
# Personalising a slide
#
# The claims here are about three different things and are asked in three
# different places, for the reason the file's own docstring gives. What is ON a
# slide is a question about a document, so it is parsed. What SURVIVES a save is
# a question about a file, so it goes through `serialise` and `parse_text` and is
# compared byte for byte. And what a write door ACCEPTS is a question about the
# API, so it is asked through the API — hand-editing a fixture would have found
# none of the eleven PATCH bodies that committed and then 500ed every page.
# --------------------------------------------------------------------------- #


def _one(**over) -> Task:
    """A leaf in cycle 37 with a body worth choosing sections out of."""
    body = over.pop(
        "body",
        "The opening sentence.\n\n"
        "## Problem\nWhy this was bet.\n\n"
        "## Solution\nWhat was going to happen.\n\n"
        "## Progress\n- [x] one\n- [ ] two\n\nIt went well.\n",
    )
    fields = {
        "id": "task-d00001",
        "kind": "task",
        "title": "A leaf",
        "status": "in_progress",
        "owner": "ann",
        "cycle": 37,
        "person_weeks": 1,
        "priority": "high",
        "body": body,
    }
    return Task(**{**fields, **over})


def _index_of(*records: Record) -> Index:
    return build_index(list(records), Config(schema_version=2), TODAY)


def _slides_on(index: Index, number: int = 37) -> list[dict]:
    parsed = _Slides()
    parsed.feed(render_deck(index, number))
    # `text` is a list of the strings inside the article, so it is joined here
    # rather than in each test. The title slide has no `.who` row and is told
    # apart by its class, not by looking for the word Review in its prose — a
    # record whose title happens to say Review would have vanished from every
    # assertion in this file.
    for slide in parsed.found:
        slide["said"] = " ".join(slide["text"])
    return [slide for slide in parsed.found if "title" not in slide["classes"]]


def test_a_record_with_no_slide_key_draws_what_it_always_drew():
    """The whole feature has to be invisible until somebody uses it.

    `Record.slide` defaults to `None`, and `None` means generated rather than
    "generated is what was chosen". Collapsing the two would have made shipping
    this a change to every deck in the plan on the day it merged — which is the
    one thing a review deck must never be, because the person holding the sheet
    is the person who cannot check.
    """
    record = _one()
    assert record.slide is None
    drawn = render_deck(_index_of(record), 37)
    assert "It went well." in drawn
    # The bet is still out, which is the rule that predates this field.
    assert "Why this was bet." not in drawn
    assert "What was going to happen." not in drawn


def test_a_chosen_slide_with_nothing_ticked_stays_empty():
    """An author who cleared every box meant it, and the fallback must not argue.

    This is the one branch `chosen` exists for. `_review`'s fallback chain puts
    the Solution on a slide that would otherwise be blank, which is right for a
    GENERATED slide — five of seven slides in the demo's own cycle came out as a
    heading over blank paper without it. Run under a personalised slide it would
    reprint the very section somebody had just unticked, in front of the room.
    """
    record = _one(slide=Slide(sections=[], lead=False))
    drawn = render_deck(_index_of(record), 37)
    assert "It went well." not in drawn
    assert "What was going to happen." not in drawn
    # And not the "nothing is written on this record" line either: something IS
    # written, and the reason the sheet is bare is that somebody chose it.
    assert "Nothing is written on this record" not in drawn


def test_a_section_is_drawn_when_it_is_ticked_and_not_when_it_is_not():
    record = _one(slide=Slide(sections=["solution"], lead=False))
    drawn = render_deck(_index_of(record), 37)
    assert "What was going to happen." in drawn
    assert "It went well." not in drawn


def test_the_opening_prose_has_its_own_box_because_no_section_names_it():
    """`sections` is keyed by heading, so the text above the first one is in none
    of them. Without `lead` a record whose body is plain prose would have had
    nothing to tick, and personalising it would have blanked a slide with no way
    to get the words back."""
    record = _one(slide=Slide(sections=[], lead=True))
    assert "The opening sentence." in render_deck(_index_of(record), 37)
    record = _one(slide=Slide(sections=[], lead=False))
    assert "The opening sentence." not in render_deck(_index_of(record), 37)


def test_newslide_makes_another_slide_and_numbers_it_from_two():
    record = _one(slide=Slide(body="First half.\n\\newslide\nSecond half."))
    slides = _slides_on(_index_of(record))
    assert [slide["heading"] for slide in slides] == ["A leaf", "A leaf (2)"]
    assert "First half." in slides[0]["said"]
    assert "Second half." in slides[1]["said"]
    # The record's own contribution goes on the first slide only. Repeating the
    # ticks and the pull requests under every continuation would print the same
    # list three times, which is what `without_checklist` exists to stop.
    assert "one" in slides[0]["said"] and "one" not in slides[1]["said"]


def test_a_newslide_inside_a_code_fence_is_text_and_not_a_break():
    record = _one(slide=Slide(body="Before.\n```\n\\newslide\n```\nAfter."))
    assert len(_slides_on(_index_of(record))) == 1


def test_a_skipped_slide_is_marked_and_not_removed():
    """Greyed, never hidden — jcanton, 2026-08-25. A slide that vanishes from the
    deck is a slide nobody can find their way back to, and the rail is where you
    put it back. Presentation mode is where it is actually absent, and that is
    the script's job rather than this markup's."""
    record = _one(slide=Slide(skip=True))
    drawn = render_deck(_index_of(record), 37)
    assert 'data-skip="1"' in drawn
    assert "A leaf" in drawn


def test_the_chips_carry_the_marks_every_other_view_carries():
    """The deck drew a status as a bare word while the table, the graph and the
    legend have drawn glyph-and-word since the glyphs existed, and it drew no
    priority at all. The fill is the channel a projector loses first and the one
    `_DECK_STYLE` deliberately gives up, so the mark was the only one left and it
    was missing."""
    record = _one()
    parsed = _Slides()
    parsed.feed(render_deck(_index_of(record), 37))
    text = " ".join(word for slide in parsed.found for word in slide["text"])
    assert STATUS_GLYPH["in_progress"] in text
    assert PRIORITY_GLYPH["high"] in text
    assert "High" in text


def test_a_deck_order_puts_the_listed_first_and_keeps_everything_else():
    """Partial and stale are both ordinary, and neither may take a slide off the
    deck. Somebody re-bets while a tab is open; an order that could silently drop
    the record they just added is an order nobody could trust, on the one page
    whose reader cannot check."""
    a, b, c = (_one(id=f"task-d0000{n}", title=f"T{n}") for n in (1, 2, 3))
    assert [one.id for one in _deck_order([a, b, c], ["task-d00003"])] == [
        "task-d00003",
        "task-d00001",
        "task-d00002",
    ]
    # An id for a record this cycle no longer holds is ignored, not drawn as a gap.
    assert [one.id for one in _deck_order([a, b], ["task-d00009", "task-d00002"])] == [
        "task-d00002",
        "task-d00001",
    ]
    # A repeated id is taken once. The rail deduplicates before it saves, so this
    # is a hand-edited file, and the honest reading is "that record, once".
    assert [one.id for one in _deck_order([a, b], ["task-d00002", "task-d00002"])] == [
        "task-d00002",
        "task-d00001",
    ]
    # Nothing listed is the order the deck had before this field existed.
    assert [one.id for one in _deck_order([a, b, c], [])] == [a.id, b.id, c.id]


def test_a_slide_survives_a_save_byte_for_byte():
    """The prose is the first prose this tool puts in frontmatter, so the round
    trip is the thing to prove. A literal block is what a person hand-editing
    wants to see; a value the block form cannot carry exactly — a line ending in
    a space — falls back to the quoted form, because exact beats pretty in a file
    that is also a record."""
    from openproj.model import parse_text, serialise

    for body in ("A line.\n\n\\newslide\nAnother.", "trailing   \nspace", "", "one line"):
        record = _one(slide=Slide(sections=["progress"], skip=True, body=body))
        back = parse_text(serialise(record), "x")
        assert back.slide is not None
        assert back.slide.body == body
        assert back.slide.sections == ["progress"]
        assert back.slide.skip is True


def test_a_slide_nobody_can_read_costs_that_slide_and_nothing_else():
    """Parse permissively, validate strictly. A record that fails to load takes
    the other four hundred with it, so a hand-edited `slide:` that is nonsense
    has to cost one slide drawn the generated way — never a page."""
    from openproj.model import parse_text

    text = (
        "---\nid: task-d00001\nkind: task\ntitle: A leaf\ncycle: 37\nslide: 5\n---\n\nThe body.\n"
    )
    assert parse_text(text, "x").slide is None
    # And a map whose MEMBERS are nonsense keeps the map and loses the members,
    # so each field falls back to its own declared default rather than to a copy
    # of it written in a validator.
    text = (
        "---\nid: task-d00001\nkind: task\ntitle: A leaf\ncycle: 37\n"
        "slide:\n  progress: banana\n  sections: solution\n  body: 7\n---\n\nThe body.\n"
    )
    slide = parse_text(text, "x").slide
    assert slide is not None
    assert slide.progress is True
    assert slide.sections == ["solution"]
    assert slide.body == ""


def test_a_figure_may_be_sized_and_two_may_stand_side_by_side():
    """`{width=60}` on an image, in a slide and in a record body alike.

    A bare number means per cent because a slide is SCALED — everything on it is
    laid out in one 1280x720 space and multiplied to fit a thumbnail, a preview
    pane or a wall, so a width relative to the sheet is the only one that means
    the same thing at all four sizes. It is also the only spelling that works
    unquoted: the plugin ends a bare value at the first non-word character, so
    `{width=60%}` parses as no attribute and prints as literal text.
    """
    from openproj.render.markdown import _markdown

    one = "assets/0123456789abcdef.png"
    drawn = _markdown(f"![d]({one})" + "{width=60}", ROUTES, {})
    assert 'style="width: 60%"' in drawn
    assert 'style="width: 300px"' in _markdown(f"![d]({one})" + '{width="300px"}', ROUTES, {})


def test_an_image_attribute_that_is_not_a_size_never_reaches_the_page():
    """`attrs_plugin` sets ARBITRARY attributes, and a plan is a repository
    anybody can push to — so `{onerror=…}` and `{style=…}` are one line of
    markdown away from every page that draws the record. Three fences: the
    plugin's own `after` and `allowed`, and `_image`'s rebuild of `token.attrs`.
    The third is the one a version bump cannot change.

    **Asked of a parser and never of a substring**, which is this repository's
    oldest lesson about exactly this class of claim. A rejected `{onerror=…}`
    survives in the page as literal TEXT — the plugin declined to consume it, so
    it is prose, escaped like any other prose — and a substring test cannot tell
    that from a live handler. Five escaping bugs shipped under tests that
    asserted on substrings of the page. So this asserts on the attributes the
    `<img>` actually carries.
    """
    from html.parser import HTMLParser

    from openproj.render.markdown import _markdown

    class _Imgs(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.found: list[dict] = []

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag == "img":
                self.found.append(dict(attrs))

    one = "assets/0123456789abcdef.png"
    for hostile in (
        "{onerror=alert(1)}",
        "{style=position:fixed}",
        "{class=evil}",
        "{width=60%;background:url(http://x)}",
        "{width=99999}",
        '{width="60%\\" onload=\\"alert(1)"}',
        '{width="60%" onerror="alert(1)"}',
    ):
        parsed = _Imgs()
        parsed.feed(_markdown(f"![x]({one})" + hostile, ROUTES, {}))
        assert len(parsed.found) == 1, hostile
        carried = parsed.found[0]
        # Only ever these three, whatever was written in the braces.
        assert set(carried) <= {"src", "alt", "style"}, (hostile, carried)
        assert not any(name.startswith("on") for name in carried), (hostile, carried)
        # A style that survives is a size and nothing else — one declaration,
        # digits and a unit, no second property smuggled in behind a semicolon.
        if "style" in carried:
            assert re.fullmatch(
                r"(?:width|height): [0-9]{1,3}(?:%|px|rem)(?:; (?:width|height): "
                r"[0-9]{1,3}(?:%|px|rem))?",
                carried["style"],
            ), (hostile, carried["style"])
        # And the picture survives every one of them: a hostile attribute costs
        # the attribute, never the figure.
        assert carried["src"].endswith("0123456789abcdef.png"), hostile
