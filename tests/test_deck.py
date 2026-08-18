"""The review deck: one cycle, one slide per piece of work in it.

The team built this by hand in Google Slides at the end of every cycle, out of
records that were already in the plan — so the deck said "PR#2427, under review"
beside a task whose `prs` and `status` said the same thing, and the copy in the
deck went stale the moment either moved. Generating it is the same argument that
made `blocks` derived rather than stored.

The claims here are about three different mediums and are asked in three
different places. What is *on* a slide is a question about a document, so it is
parsed rather than searched for: the shell inlines its own stylesheet into every
page, comments and all, and a substring test for "☑" or for an entity id finds
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
    Entity,
    Pitch,
    Project,
    Task,
    checklist,
    checklist_items,
    load_repo,
    without_checklist,
    without_sections,
)
from openproj.render import ROUTES, STATIC, render_cycle, render_deck

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
                {"classes": frozenset(classes), "under": "", "heading": "",
                 "points": [], "prs": [], "images": [], "doc": "", "text": []}
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

LAND = """## Problem

JSBACH is Fortran and the interface is not.

## Progress

- [x] Read the tiling code
- [x] Generate the bindings
- [ ] Wire up the surface fluxes

## Notes

The gather/scatter seam is the one to watch.

![the driver](assets/0123456789abcdef.png)
"""


def corpus() -> list[Entity]:
    project = Project(id="proj-000001", kind="project", title="Physics")
    land = Pitch(id="pitch-0c0001", kind="pitch", title="Porting land", owner="ann",
                 person_weeks=6.0, parent="proj-000001", status="in_progress", cycle=37,
                 assigned_on=date(2026, 8, 17), reviewers=["bo"])
    jsbach = Task(id="task-0c1001", kind="task", title="Port JSBACH", owner="ann",
                  person_weeks=4.0, parent="pitch-0c0001", status="in_progress",
                  assigned_on=date(2026, 8, 17), reviewers=["bo"],
                  prs=["C2SM/icon4py#1427", "GridTools/gt4py#2765"], body=LAND)
    fluxes = Task(id="task-0c1002", kind="task", title="Coordinate with MPI-M", owner="bo",
                  person_weeks=1.0, parent="pitch-0c0001", status="done",
                  assigned_on=date(2026, 8, 17), reviewers=["ann"], prs=["C2SM/icon4py#1403"])
    # A chore nobody pitched: bettable in its own right, so its cycle is its own.
    chore = Task(id="task-0f0001", kind="task", title="Tidy the serialisation scripts",
                 owner="cy", person_weeks=0.5, status="ready", cycle=37, reviewers=["ann"],
                 body="## Progress\n\n- [ ] Move the docs out of HackMD\n")
    # Bet into a different cycle, and therefore on a different deck.
    other = Pitch(id="pitch-0d0001", kind="pitch", title="Tracer advection", owner="cy",
                  person_weeks=2.0, status="ready", cycle=36, reviewers=["ann"])
    return [project, land, jsbach, fluxes, chore, other]


def plan_of(number: int = 37) -> Cycle:
    return Cycle(cycle=number, starts_on=date(2026, 8, 17), reviews_on=date(2026, 9, 28),
                 availability={"ann": 0.5, "bo": 1.0, "cy": 0.6},
                 body="## Goal\n\nThe land port is the one that cannot slip.\n")


@pytest.fixture
def index() -> Index:
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    return build_index(corpus(), config, TODAY)


@pytest.fixture
def deck(index: Index) -> str:
    return render_deck(index, 37, ROUTES)


@pytest.fixture
def demo_index(demo_root: Path) -> Index:
    entities, config, _ = load_repo(demo_root)
    return build_index(entities, config, TODAY)


@pytest.fixture
def golden_index(seed_root: Path) -> Index:
    """The frozen corpus, which is the only hand-written checklist in the suite."""
    entities, config, _ = load_repo(seed_root)
    return build_index(entities, config, TODAY)


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
        "Port JSBACH",
        "Coordinate with MPI-M",
        "Tidy the serialisation scripts",
    ]
    assert "title" in found[0]["classes"]
    # The pitch these two belong to is a rollup and gets no slide of its own.
    assert not any("Porting land" == s["heading"] for s in found)


def test_a_slide_is_headed_by_what_the_work_belongs_to_and_then_by_itself(deck: str):
    """`[GT4Py] Features` — the real deck's own convention, typed by hand into
    sixteen titles. The bracket is the pitch, so nobody types it; and it is blank
    where the record IS the bet, because a bracket repeating the line under it is
    furniture."""
    under = {s["heading"]: s["under"] for s in slides_in(deck)}

    assert under["Port JSBACH"] == "Porting land"
    assert under["Coordinate with MPI-M"] == "Porting land"
    # A chore nobody pitched is its own bet.
    assert under["Tidy the serialisation scripts"] == ""


def test_the_slides_of_one_bet_are_consecutive(index: Index):
    """Which is what the bracket in the real deck's titles was doing by hand:
    four GT4Py slides in a row, and then four ICON4Py ones. Ordered by id alone
    they interleave, and a deck that jumps between two subjects and back is a
    deck the room cannot follow."""
    more = corpus() + [
        Task(id="task-0a0001", kind="task", title="A chore", owner="cy", person_weeks=1.0,
             status="ready", cycle=37, reviewers=["ann"]),
    ]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    headings = [s["heading"] for s in slides_in(render_deck(build_index(more, config, TODAY),
                                                            37, ROUTES))]

    land = [at for at, name in enumerate(headings)
            if name in ("Port JSBACH", "Coordinate with MPI-M")]
    assert land == [min(land), min(land) + 1], headings


def test_a_slide_shows_the_points_ticked_and_the_share_the_index_counted(deck: str):
    """The tick and the percentage are `index.progress`, which counted them once
    for the table, the detail page and this. Counting them again here is how the
    number above a list and the ticks in it come to disagree."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port JSBACH")

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
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port JSBACH")

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
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port JSBACH")

    assert "JSBACH is Fortran" not in slide["doc"], "the Problem section is the bet"
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
    from openproj.render import TEMPLATES, _bet_headings

    found = _bet_headings()

    assert {"problem", "appetite", "solution", "rabbit holes", "no-gos",
            "for later"} == found
    assert "progress" not in found
    for body in TEMPLATES.values():
        assert not without_sections(body, found | {"progress"}).strip("# \n"), body[:40]


def test_the_progress_section_is_what_a_review_slide_is_for(index: Index):
    """The checklist is lifted to the points at the top, and whatever else
    somebody wrote under `## Progress` is the sentence they are about to say out
    loud. It was being deleted along with the rest of the template."""
    said = Task(id="task-0c1001", kind="task", title="Port JSBACH", owner="ann",
                person_weeks=4.0, parent="pitch-0c0001", status="in_progress",
                assigned_on=TODAY, reviewers=["bo"],
                body="## Problem\n\nFortran.\n\n## Progress\n\n- [x] Bindings\n\n"
                     "Blocked on a savepoint nobody has generated yet.\n")
    other = [e for e in corpus() if e.id != "task-0c1001"]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    found = slides_in(render_deck(build_index([*other, said], config, TODAY), 37, ROUTES))
    slide = next(s for s in found if s["heading"] == "Port JSBACH")

    assert "Blocked on a savepoint nobody has generated yet." in slide["doc"]
    assert "Fortran" not in slide["doc"]
    # Lifted to the points, so it is not printed twice.
    assert [p["text"] for p in slide["points"]] == ["Bindings"]
    assert "Bindings" not in slide["doc"]


def test_a_pull_request_on_a_slide_is_a_link_to_the_pull_request(deck: str):
    """A dead reference teaches people the field is decorative, and the deck is
    where the field is most read: the real one links a PR on nearly every slide.
    The same `_pr_link` the facts list uses, so the two cannot point differently."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port JSBACH")

    assert slide["prs"] == [
        "https://github.com/C2SM/icon4py/pull/1427",
        "https://github.com/GridTools/gt4py/pull/2765",
    ]


def test_the_title_slide_names_the_cycle_its_review_and_what_it_was_for(deck: str):
    """The real deck's first slide is "Cycle 37 - 07/26 Review" and nothing else,
    because its goal lived in a different tool. Here the goal is on the cycle
    record, and a review that opens by saying what the cycle was for is the one
    thing the room needs before the first slide."""
    title = slides_in(deck)[0]

    assert title["heading"] == "Cycle 37"
    assert "Review" in title["text"]
    assert "2026-09-28" in title["text"]
    assert "The land port is the one that cannot slip." in title["text"]


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
    assert re.search(r"\d{4}-\d{2}-\d{2}", guessed["text"])


def test_work_bet_into_another_cycle_is_on_another_deck(deck: str):
    """A deck is a cycle review. `cycle:` records where a bet was made and is
    never re-stamped, so this is the same question every page asks."""
    assert "Tracer advection" not in " ".join(s["text"] for s in slides_in(deck))
    assert "pitch-0d0001" not in deck


def test_a_review_shows_what_was_finished_and_what_was_parked(index: Index):
    """`counts_in` is the wrong question here and this is why: it drops `done`
    and `shelved` because it exists to add up weeks still to be spent. A review
    is about what happened, so finished work is the most interesting thing on it
    and parked work is a decision the room will be asked about."""
    from openproj.model import Task as T

    parked = T(id="task-0f0002", kind="task", title="Circuit broken", owner="cy",
               person_weeks=1.0, status="shelved", cycle=37)
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    headings = [s["heading"] for s in
                slides_in(render_deck(build_index(corpus() + [parked], config, TODAY),
                                      37, ROUTES))]

    assert not any(index.counts_in(e, 37) for e in (parked,))
    assert "Coordinate with MPI-M" in headings, "a done task is what a review is about"
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
    slide = next(s for s in slides_in(page) if s["heading"] == "Port JSBACH")

    assert slide["images"] == [f"data:image/png;base64,{B64}"]
    # Nothing is left pointing at a directory that will not be there.
    assert "/assets/" not in page


def test_bytes_that_will_not_come_back_cost_the_picture_and_not_the_page(index: Index):
    """An asset that has been deleted, or a reader that has nothing to read from
    — the test that renders every entry point passes no reader at all. A missing
    image must fall back to what every other page draws, not to a traceback."""
    for read in (None, lambda name: None):
        page = render_deck(index, 37, ROUTES, read)
        slide = next(s for s in slides_in(page) if s["heading"] == "Port JSBACH")

        assert slide["images"] == ["/assets/0123456789abcdef.png"]


def test_the_media_type_of_an_asset_is_not_written_down_twice(index: Index):
    """The pattern that decides what an asset IS is built from the map that says
    what to call it. Written separately, a fifth format added to one and forgotten
    in the other is an image that draws on the site and silently stops travelling
    — which nobody would find until a deck arrived somewhere without it."""
    from openproj.render import _ASSET_MEDIA, _ASSET_SRC

    for suffix in _ASSET_MEDIA:
        assert _ASSET_SRC.fullmatch(f"assets/0123456789abcdef{suffix}"), suffix
    assert not _ASSET_SRC.fullmatch("assets/0123456789abcdef.svg")


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
    """The nav names the six views of the whole plan. A deck is one cycle's
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

    So the assertion is not that a page was returned. It is that every slide has
    something on it a person could stand up and read out — a sentence of prose,
    or ticked points, or a pull request — and enough of it to be worth a sheet of
    paper."""
    found = slides_in(render_deck(demo_index, 37, ROUTES))
    work = found[1:]

    assert len(found) == 7, [s["heading"] for s in found]
    assert "CI for the standalone driver v1.5" in [s["heading"] for s in found]

    blank = [
        s["heading"] for s in work
        if not s["points"] and not s["prs"] and len(s["doc"]) < 80
    ]
    assert blank == [], f"{len(blank)} of {len(work)} slides have nothing to present"
    for slide in work:
        # Words, and the record's own words: the heading, the chip and the id are
        # already excluded by reading `doc` rather than `text`.
        assert len(slide["doc"].split()) >= 20, slide["heading"]


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
    slide = next(s for s in slides_in(render_deck(demo_index, 37, ROUTES))
                 if s["heading"] == "Port JSBACH")

    assert slide["doc"].startswith("Solution")
    assert "Finish the forward-elimination half" in slide["doc"]
    # And still not the rest of the argument.
    assert "The first slice of ICON-Land" not in slide["doc"], "Problem is the bet"
    assert "Do not write a fourth TDMA" not in slide["doc"], "Rabbit holes are the bet"


def test_a_note_somebody_wrote_beats_the_plan_it_would_have_fallen_back_to(deck: str):
    """The fallback is a floor and not a preference. Where there is a note about
    what happened, that is the slide; the Solution appears only where the record
    said nothing else at all."""
    slide = next(s for s in slides_in(deck) if s["heading"] == "Port JSBACH")

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
        entity = next(e for e in golden_index.entities.values() if e.title == heading)
        counted = golden_index.progress[entity.id]

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
    "prs: [\"C2SM/icon4py#1403\"]\n"
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
        f"/api/entity/{BET_ID}",
        json={"base_commit": git_head(repo), "fields": {},
              "body": f"## Progress\n\n- [x] Gather to rank 0\n\n## Notes\n\n![a run]({path})\n"},
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
    bodies = [LAND, "- [X] upper\n- [ ] lower\n", "", "no list at all",
              "```\n- [x] an example, not a point\n```\n"]

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
            states, sheet.selectors_reaching(link, "color")
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
    assert '--paper: #ffffff' in bare.group(1)
    assert re.search(r':root\[data-theme="dark"\] \{', style), "so do the theme blocks"
    assert re.findall(r"--paper[\w-]*\s*:", bare.group(1)) == re.findall(
        r"--paper[\w-]*\s*:", style
    ), "a paper token is defined somewhere a reader can fail to match"


def test_the_deck_prints_one_slide_to_a_page(deck: str, tmp_path: Path):
    """The claim is about paper, so it is asked of paper. A `break-after: page`
    that resolves is a promise a stylesheet cannot keep on its own — the same
    trap the frozen column's edge fell into, where the asserted value resolved
    exactly and Chrome painted nothing at all."""
    from browser import chrome, printed

    where = tmp_path / "deck.html"
    where.write_text(deck, encoding="utf-8")

    assert printed(chrome(), where, tmp_path / "deck.pdf") == len(slides_in(deck))


def test_a_point_is_a_line_of_markdown_and_is_rendered_as_one(index: Index):
    """The corpus writes `` `jsbach_setup` `` and `C2SM/icon4py#1403` inside its
    points, and the real deck links exactly those references from exactly those
    bullets. Taken as plain text a point came out with literal backticks and a
    dead reference — the field looking decorative, which is the thing `_pr_link`
    exists to stop."""
    more = [e for e in corpus() if e.id != "task-0f0001"] + [
        Task(id="task-0f0001", kind="task", title="Tidy the serialisation scripts",
             owner="cy", person_weeks=0.5, status="ready", cycle=37, reviewers=["ann"],
             body="- [ ] call `inspect_savepoints` from C2SM/icon4py#1409\n"),
    ]
    config = Config(known_people=["ann", "bo", "cy"]).with_plans([plan_of()])
    page = render_deck(build_index(more, config, TODAY), 37, ROUTES)
    slide = next(s for s in slides_in(page)
                 if s["heading"] == "Tidy the serialisation scripts")

    assert "<code>inspect_savepoints</code>" in page
    assert slide["prs"] == [], "the links inside a point are not the PR field"
    assert "https://github.com/C2SM/icon4py/pull/1409" in page
    # And it stays on the row with its own tick rather than starting a paragraph.
    assert "<li class=\"\"><span class=\"box\" aria-hidden=\"true\">☐</span><p>" not in page


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
    assert sheet.value(inside, "font-size") == "1rem", (
        sheet.selectors_reaching(inside, "font-size")
    )


def test_a_status_on_a_slide_is_a_word_and_not_the_ladder(deck: str):
    """The five status fills are a luminance ladder measured against the PAGE, so
    on a white slide under the dark theme the chip came out a solid dark pill
    among hairlines — the app's own device drawn against a ground it was never
    measured on. The ladder exists because a graph node and a timeline bar have
    no words in them; a slide has nothing but words.

    `.slide .who .chip` is (0,3,0) against the shell's `.chip.st-ready` at
    (0,2,0), so it wins on specificity and not on the order two stylesheets
    happen to be inlined in — and one rule beats all five rungs."""
    sheet = sheet_of(deck)

    for status in ("ready", "in_progress", "done", "shelved", "shaping"):
        chip = SLIDE + [el("p", "who"), el("span", f"chip st-{status}")]
        assert sheet.value(chip, "background") == "transparent", (
            status, sheet.selectors_reaching(chip, "background")
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
        body if prelude == "@media print" else "" if prelude.startswith("@")
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
            described, paper.selectors_reaching([described], "color-scheme")
        )
    for tag in ("html", "body"):
        assert paper.value([el(tag)], "background") == "var(--paper)", tag
