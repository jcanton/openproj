"""The vocabulary: the words, glyphs, labels and templates the pages share."""

from __future__ import annotations

from datetime import UTC, datetime

from ..model import KINDS as KIND_LADDER
from ..model import PARENT_KINDS, STATUS_ORDER, Record, required_at, unread_fields
from .icons import _ICON_SVG


# A status is a class, not a colour baked into the markup: the same rect has to
# be one colour on a white ground and another on a dark one, and a `fill`
# attribute written at render time cannot change when somebody flips the toggle.
#
# It is also the *only* way a status is allowed to reach a class attribute.
# `status` is deliberately a permissive `str` — a file written before a
# vocabulary change has to load and be reported, not take the index down — so it
# holds whatever is in the file. Escaping it would have been enough to stop the
# injection and would still have written `class="chip st-ready&#34; onmouseover"`
# into the page; folding it to a rung of the ladder means an attribute that
# names a rule the stylesheet actually has.
def _status_class(status: str) -> str:
    return f"st-{status}" if status in STATUSES else "st-ready"


# What a person owns, in the order they think about it. Everything not named here
# is either derived (start, end, blocks, any rollup) or authoritative (id), and
# neither belongs in a form: a derived value typed by hand is a lie the next
# reschedule contradicts, and an edited id orphans the file from every reference.
#
# KEY ORDER IS THE PAGE. The facts column (`_fact_rows`) and the create form
# (`_new_rows`) both draw in this order, and it is jcanton's, 2026-08-24, given
# after tags ended up above status on the record page: the shape of the work
# first (status, priority, appetite, tags), then its people, then where it sits
# and when. `title` stays first and is the heading, skipped by both readers.
EDITABLE: dict[str, str] = {
    "title": "text",
    "status": "status",
    "priority": "priority",
    "person_weeks": "number",
    "tags": "list",
    "owner": "text",
    "assignees": "list",
    "reviewers": "list",
    "review_waived": "bool",
    "parent": "text",
    "depends_on": "list",
    "prs": "list",
    "cycle": "number",
    "assigned_on": "date",
    # The inbox-only fields, after everything above: they were not in the order
    # jcanton gave because no planned kind reads them, and trailing the shared
    # fields keeps his order intact on every kind rather than threading gaps
    # through it. Within the tail, who to ask before where it went.
    #
    # An issue's and a note's "who to ask". `_editable_for` intersects with
    # `model_fields`, so only the two inbox kinds are ever offered these — the
    # pipeline was built one commit ahead of the kinds on purpose, so the flip
    # commit added rungs and deleted pages without touching a form.
    "reported_by": "text",
    "written_by": "text",
    # The two one-way edges an inbox record carries; rendered through `_links`
    # like `depends_on`, which is links rather than the bare ids both old pages
    # printed. Offered only to the two inbox kinds, same as the pair above.
    "pitched_into": "list",
    "became": "list",
}
# The validator's own ladder, aliased and not retyped. This line was the five
# words written out a second time — the same defect `PREFIX` below records being
# the third copy of the kind ladder — and the two copies could only ever agree
# by luck. `STATUSES` stays as the name this file reads it by.
STATUSES = STATUS_ORDER
# Highest first, which is the order a picker is read in and the order the table
# sorts by. Five rungs, because three left the team writing `High+` in the margin.
PRIORITIES = ("very_high", "high", "medium", "low", "very_low")


# How many bars of five a priority lights. One integer, shipped to the browser in
# the page's own data, because the table draws its rows in JavaScript and the
# legend and the detail page are Jinja — two hand-written copies of this map is
# two ladders that agree until somebody adds a rung.
PRIORITY_LEVEL = {"very_low": 1, "low": 2, "medium": 3, "high": 4, "very_high": 5}

# The same ladder where only text will go: a `<select>` option is a string and
# cannot hold the five-element meter the legend and the table draw. One block
# character per rung, rising with it.
#
# The graph does NOT use this and did for one release. A cytoscape label is drawn
# into a canvas with the font it is given and no fallback chain, and Inter has no
# Block Elements — so every node's name came out with a .notdef box in front of
# it. An `<option>` is drawn by the platform's own widget, which does fall back,
# which is why the same characters are safe here and were not there. If that ever
# stops being true the answer is the one the graph took: draw it.
#
# Text and not an image, which is the argument `STATUS_GLYPH` already makes and
# it applies here unchanged: a shape survives a screenshot, a projector and
# deuteranopia, and it arrives in the label's own ink instead of being drawn by
# the platform's colour font at a different weight on every machine.
# PRIORITY, AS ONE CHARACTER. A block of the height the rung is worth: the meter
# it replaces was five elements, an `inline-flex` and a `data-level`, and this is
# a glyph on a text baseline.
#
# It was five bars, then no mark at all in menus, and it is now this — jcanton,
# 2026-08-20, having seen all three: "it's a font glyph, no alignment problems,
# occupies less horizontal space. it can go back in the dropdowns so it's
# consistent with the status dropdown, better on all fronts".
#
# The vendored face carries 230 codepoints and none of these is one of them, so
# every one of them is drawn by whatever the platform falls back to. That is the
# honest cost and it was weighed: a block element is in every desktop UI font
# there is, the fallback draws a rectangle of the right height where it lands,
# and the alternative — an element that has to be aligned against a word, inside
# a chip, inside a cell, inside a column that tightens — is three alignment
# problems that this repository has now fixed four times.
#
# Colour goes with it wherever colour is possible: the chip in the table, the key
# in the legend, the meter on a node. In a native `<select>` it cannot — an
# option is a string — which is the same bargain the status glyphs already make.
PRIORITY_GLYPH = {
    "very_low": "\u2582",    # ▂ one quarter — an eighth is a hairline at 12px
    "low": "\u2583",         # ▃ three eighths
    "medium": "\u2585",      # ▅ five eighths
    "high": "\u2587",        # ▇ seven eighths
    "very_high": "\u2588",   # █ full
}

# The redundant channel. On the graph and the timeline a fill is the only thing
# telling two shapes apart, and a luminance ladder makes five fills *separable*
# without making any one of them *nameable* — you can see that a bar is darker
# than its neighbour and still not know which state that is. So every status also
# owns a mark that is not colour: drawn at a bar's left edge, prefixed to a node's
# title, and shown inside the legend swatch beside the word it stands for.
#
# Chosen to be different SHAPES, not different weights of one shape: a small dot
# and a large dot are two glyphs a reader has to compare, which is the failure
# the ladder was already meant to fix.
# Six shapes, one per status, and the only place any of them is written.
#
# Text glyphs and not emoji, and that is a constraint rather than a taste: an
# emoji is drawn by the platform's colour font, so it ignores `currentColor` and
# arrives at a different weight on every machine — and these sit inside a 14px
# timeline bar in the bar's own ink.
#
# The argument that used to run on from there — that a drawing cannot replace
# them, because "the same characters go inside `<option>` elements" — is no
# longer true of status and was left standing when it stopped being. Status left
# the native `<select>` when it became the hill (`_control_html` in
# `controls.py` says so), and the facet menus carry no glyph at all; every site
# left is a chip, a legend swatch, an SVG `<text>` or a data-URI image, and each
# of those is somewhere an SVG could go. The constraint still binds
# `PRIORITY_GLYPH`, whose blocks really are in menus, and it is written out
# again there. These stay characters because a character is what they should be,
# not because nothing else would fit.
#
# **They say what the hill says.** Since the detail page draws a status as a ball
# on a hill, a mark that means something unrelated is a second vocabulary for one
# fact — so these are the hill in one character: standing at the foot of it,
# climbing, over the top, coming down. jcanton, 2026-08-22, choosing between four
# mocked options. `done` and `shelved` keep their marks: they are the two the
# hill draws on flat ground, and a tick and a cross are already what they mean.
#
# **`thinking` is a ring, and it is the one mark with nothing inside it.** The
# other five are strokes that go somewhere; a record nobody has started is the
# one state with no direction to draw, so it gets the shape that has none —
# jcanton, 2026-08-24: "a simple circle centered vertically and horizontally,
# like a dot product but empty". Empty is the whole of it, and it is what rules
# out the one candidate that would have cost nothing: `•` U+2022 IS in the
# vendored face, measured, where none of these six is — and it is a filled dot,
# which says "here is a thing" where this has to say "here is a place for one".
#
# U+25CB and not the five rounder-looking alternatives, chosen by measuring
# rather than by eye — ink extents from the font's own metrics, in Chrome, in
# the page's real stacks. At 11px/700 in `--font-sans` the five shipped marks
# put their ink 3.80-3.88 above the baseline and `○` lands at 3.878, which is
# the top of that band and just under a capital M's 4.00; horizontally it is
# 0.03px off the centre of its own advance, inside the -0.09..0.00 the others
# already spread over. `◦`, `⊙` and `•` all sit LOW — 3.13, 3.16, 3.19 — and
# shrink to about 4px of ink at the legend's 9px; `◯` and `◌` sit 0.30 high and
# fill the whole em. `⌒` has always been the outlier at 7.94 and is meant to be:
# it is an arc, and an arc is drawn at the top of the line.
#
# The chip draws its mark in `--font-mono` rather than `--font-sans`, and that
# was measured too because it is a different question: on a monospace cell every
# mark sits on one 6.6px advance and is centred horizontally by construction
# (0.000 for all six), while the vertical spread is much wider than the sans
# stack's — the arrows sit at 2.29-2.35 and the tick at 3.60. `○` lands at 2.86,
# between them. So it is level with its word in the legend, the timeline and the
# graph, and mid-pack in a chip set that was already loose. There is no nudge
# here on purpose: a per-glyph offset would be an offset no other mark has, and
# the fallback that draws these differs by machine.
#
# **None of the six is in the vendored face's latin subset**, and the line that
# used to say "not all five" understated it. Measured by advance: each character
# rendered as `"Inter var", X` for three very different fallbacks — if the face
# had the glyph the advance would not move, and for all six it does. U+2191 and
# U+2193 are the only arrows it holds; `•`, `—` and `€` are in it, which is how
# the method was checked. It does not matter, and here is why it does not. In
# HTML the stack falls back — `--font-sans` names four faces after Inter. On the
# graph the mark is drawn into an SVG data URI, which is an isolated document
# that resolves against the system's own fonts and not the page's `@font-face`
# at all, which is exactly how the tick has been drawing correctly all along.
# The cost of a character no machine has is one 14px mark drawn as a box, not a
# broken page — the same bargain `docs/QUEUE.md` §7.2 struck for the priority
# blocks, and a sixth character costs nothing the five already shipped do not.
STATUS_GLYPH = {
    "thinking": "○",        # a place for one: nothing has started
    "shaping": "↗",         # the climb: figuring out what to do
    "ready": "⌒",           # over the top, and knowing
    "in_progress": "↘",     # the descent: getting it done
    "done": "✓",            # finished
    "shelved": "✕",         # struck out, not failed
}


# The two marks the table's draft row is created and cancelled with, in the same
# frame as the icons above and for the same reason, one page over.
#
# Drawn and not typed. `✓` (U+2713) and `✕` (U+2715) are not in the vendored
# latin subset — 230 codepoints, and neither is among them — so a page that used
# the characters would be asking the reader's machine for them, which is the one
# thing every other mark on this site is arranged not to do. On a workstation
# without a font that has them, the two controls that create and abandon a record
# are two tofu boxes. `.rowgrip` settles the identical question the identical way
# and says so in the stylesheet: `⠿` is not in the subset either, so the grip is
# two drawn rules instead of a character.
#
# They are not entries in `_ICON_ART`. That map IS the icon vocabulary — `ICONS`
# is `tuple(_ICON_ART)`, the picker offers exactly its keys and `web.py` accepts
# exactly its keys — so a `check` in it is a check somebody can store as their
# face. These are furniture on one control; the frame is what they share.
#
# `aria-hidden` comes with the frame, which is what these need: each sits inside
# a button that carries the name, and a drawing announced beside it would be the
# same control said twice.
DRAFT_MARKS = {
    "create": _ICON_SVG.format('<path d="M5 12.6 9.7 17.3 19 6.9"/>'),
    "cancel": _ICON_SVG.format('<path d="M6.6 6.6 17.4 17.4M17.4 6.6 6.6 17.4"/>'),
}


# The toolbar's first group, drawn for exactly the reason `DRAFT_MARKS` above is.
#
# Every arrow anybody would reach for here is outside the vendored latin subset —
# measured against the 230 codepoints in `inter-latin-wght-normal.woff2`: U+21B6
# and U+21B7 (the curved arrows), U+27F2 and U+27F3 (the circular ones), U+2190,
# U+2192, U+21A9, U+21AA and U+238C are all absent, and `•` (U+2022) and `—`
# (U+2014) are the only two marks the shipped toolbar types that are present. So
# a typed arrow makes the two most-pressed buttons on the bar a pair of tofu
# boxes on any machine without a font that has them, which is precisely the
# failure the draft row's check and cross were redrawn to avoid.
#
# Hand-drawn rather than copied, on the rule `_ICON_ART` is written under:
# stroked outlines in `currentColor` at the interface's own weight, so they
# follow the theme and the drawing in the file is the drawing on screen. The two
# are mirrored about x=12 so that "the other direction" is legible as the same
# shape reversed rather than as a second icon to learn.
#
# Sized by `.marks .hist svg` — an SVG nothing sizes lays out at 0x0, and this
# application has shipped that twice.
HISTORY_MARKS = {
    "undo": _ICON_SVG.format('<path d="M9.5 4.5 5 9l4.5 4.5"/>'
                             '<path d="M5 9h9a5 5 0 0 1 0 10h-3.5"/>'),
    "redo": _ICON_SVG.format('<path d="M14.5 4.5 19 9l-4.5 4.5"/>'
                             '<path d="M19 9h-9a5 5 0 0 0 0 10h3.5"/>'),
}


# Off the ladder. This was the third hand-written copy of it in this file.
PREFIX = {rung.name: rung.prefix for rung in KIND_LADDER}
# The validator's own gate, asked rather than copied — and asked through the front
# door. This module used to import `model._status_problems` at import time and run
# the derivation itself, which put the shape of a problem tuple in the renderer's
# hands; the derivation lives with the rule now, and `test_the_gates_are_the_
# validator_s_own_and_not_a_second_copy` is what keeps it honest.
REQUIRED_AT = required_at()

# The reader's name for a field. `appetite_weeks` and `effort_weeks` were two
# storage fields holding one quantity, and calling it Effort here, Appetite on the
# detail page and weeks in the table made it look like three different numbers
# nobody could reconcile. They are one field now — `person_weeks`, named for the
# unit that D1 got wrong — and Appetite is still the word a reader gets, because
# it is the domain's and the team's own template's.
LABELS = {
    "title": "Title", "status": "Status", "owner": "Owner", "assignees": "Assignees",
    "reviewers": "Reviewers", "review_waived": "Review waived", "assigned_on": "Assigned on",
    "priority": "Priority", "cycle": "Cycle", "parent": "Parent", "depends_on": "Blocked by",
    "tags": "Tags", "prs": "PRs", "person_weeks": "Appetite (person-weeks)",
    "reported_by": "Reported by", "written_by": "Written by",
    "pitched_into": "Pitched into", "became": "Became",
    "opened_on": "Opened on", "written_on": "Written on",
    # The records list's two columns that are not one stored field. `who` is
    # `Rung.who` — owner, reported_by or written_by by rung — and the header is
    # "Who", not "Created by": `owner` is who HOLDS a pitch, not who typed it,
    # and a header promising authorship over a field recording ownership is
    # exactly the copy drift HUMAN exists to prevent. `edited` is the history
    # walk's stamp, a fact about commits rather than about any field.
    "who": "Who", "edited": "Last modified",
    # Not stored fields: a facet and a derived column. They are read by the same
    # people in the same control bar, so they take their words from here too.
    "kind": "Kind", "project": "Project", "product": "Product",
    "size": "Appetite", "blocked_by": "Blockers",
    "progress": "Progress",
    "start": "Start", "end": "End", "id": "Id", "predicate": "Flags",
    # The people page's own facet. Which hat somebody is wearing is not stored on
    # a record at all — it is which field their name is in — but it is read in
    # the same control bar as the rest, so it takes its word from the same map.
    "role": "Role",
}

# The reader's word for a value. `in_progress`, `missing_required_fields` and
# `overruns_cycle` are identifiers: they belong in a `value=`, a class and a
# `data-*` attribute, and nowhere a person reads. One map rather than one per
# page, because five pages inventing their own is how `in_progress` became
# "In progress", "in progress" and "in_progress" on the same screen.
#
# Statuses, priorities, kinds and predicates share it: their identifiers do not
# collide, and a caller rendering an option has no reason to know which family a
# value came from. Anything unknown comes back unchanged, so a value added to the
# model still renders — badly, but it renders.
HUMAN = {
    # statuses
    "shaping": "Shaping",
    "ready": "Ready",
    "in_progress": "In progress",
    "done": "Done",
    "shelved": "Shelved",
    # A note's two, and the third it is only ever given by what it became. They
    # are here rather than left to print as themselves for the reason the map
    # exists: five pages inventing their own capitalisation is how `in_progress`
    # came to be spelled three ways on one screen.
    "thinking": "Thinking",
    "dropped": "Dropped",
    "promoted": "Promoted",
    # priorities
    "very_high": "Very high",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "very_low": "Very low",
    # kinds
    "product": "Product",
    "project": "Project",
    "pitch": "Pitch",
    "task": "Task",
    # The two inbox kinds, fed the day they joined the ladder: chips masked the
    # gap with `text-transform: uppercase`, and the /new kind picker did not —
    # it read "Product, Project, Pitch, Task, issue, note".
    "issue": "Issue",
    "note": "Note",
    # predicates, as COMPUTED_PREDICATES spells them. `missing_required_fields`
    # is not what it does — it matches any problem of any severity — so it says so.
    "blocked": "Blocked",
    "unblocked": "Not blocked",
    "overruns_cycle": "Overruns its cycle",
    "missing_required_fields": "Has a problem",
    "has_blocker": "Has a blocking problem",
    "review_waived": "Review waived",
    "past_cycle_build": "Still running past its cycle",
    "in_progress_without_prs": "In progress, nothing linked",
    "untracked": "No checklist",
    "for_later": "Has a for-later list",
    # roles, which the people page filters by. Already English, but a dropdown
    # reading "owner, Pitch, Ready" is three labelling conventions in one bar.
    "owner": "Owner",
    "assignee": "Assignee",
    "reviewer": "Reviewer",
}


def _human(value: object) -> str:
    """The word a reader gets for an identifier the data model uses."""
    if value is None:
        return ""
    return HUMAN.get(str(value), str(value))


# What the word MEANS, beside the control, while somebody is setting it.
#
# Neither `LABELS` nor `HUMAN`, and the difference is who reads it and when.
# Those two name a field and spell a value, and both are read on every view of
# every page; these are teaching copy and are edit-only (`.teach`, in
# `_DETAIL_STYLE`). Since the record page landed on preview, a read is roughly
# nine views in ten, and teaching copy on all of them is how the one sentence in
# this slot that is a FACT about the record — the derived-status lock, in
# `_STATE_HINT` — stops being read.
#
# The test a line had to pass to be here: does it change what somebody does at
# that moment? Most fields fail it. `title` and `tags` need nothing, `owner`
# needs nothing, and help that is everywhere is help nobody reads. Five entries
# across the two maps below, and the count is the design — a facts list that
# doubles in height turns every hint into wallpaper.
#
# Paraphrase, never quotation. Shape Up is free to read online but the
# reproduction terms are somebody's to check, and a lifted Basecamp paragraph
# reads as an import beside this codebase's own voice — in the team's own words
# the licence question never arises. The long form is `docs/shape-up.md`.
FIELD_TEACH = {
    "person_weeks": (
        "Appetite is a budget, not an estimate: how much this is worth, "
        "not how long it will take."
    ),
    # The circuit breaker, and the one Shape Up idea the scheduler most quietly
    # assumes. A newcomer reading a derived end date otherwise expects a slip to
    # push it out, which is the opposite of the rule the review meeting keeps.
    "cycle": (
        "A bet is for one cycle. Work that overruns is re-bet, "
        "not extended by default."
    ),
}

# The same thing keyed by status word rather than by field, because status is one
# field whose control is six places to stand. Swapped as the ball moves rather
# than rendered once — `attachHill` does it — so the sentence describes the stop
# somebody is about to choose and not the one the record arrived at. A person
# dragging onto `shelved` is deciding what shelved means; a sentence about where
# they came from is help for the wrong decision.
#
# Three of the six carry copy. `ready`, `in_progress` and `done` are words a
# person already owns before meeting this tool, and a hint that restates a word's
# ordinary meaning is the one that teaches people to skim the ones that do not.
#
# Read only by the `record` ladder. An issue has no `thinking` at all, and a
# note's `thinking` is a different idea — "still turning this over", not "written
# down, nobody has started" — so one shared sentence would be false on one of
# them. See `_LADDER_OF`.
STATUS_TEACH = {
    "thinking": (
        "Somebody has written this down as possible work — nobody has started "
        "shaping it yet."
    ),
    # The one line that measured three, in a column where every other lesson
    # measured two. jcanton, 2026-08-24, choosing the shorter of two drafts after
    # seeing it painted: "outlining a solution the appetite can hold" and "has bet
    # ON IT yet" were the two clauses carrying the wrap, and neither was saying
    # anything the shorter one does not.
    "shaping": (
        "Somebody is narrowing the problem to a solution that fits the appetite "
        "— nobody has bet yet."
    ),
    "shelved": "A decision, not a failure: we looked, and we are not doing this.",
}


# Where "how long ago" stops being the useful answer and "when" begins.
# docs/hackmd-observed.md reads the boundary off the pixels: one column runs
# `17 hours ago` … `10 days ago` and then switches to `2026-07-08` (about 43
# days before the shot), so the threshold falls somewhere past ten days and
# before forty-three. Fourteen keeps every relative form the screenshot shows
# and abandons the form at the first round boundary after them — two weeks —
# because the same observation says the relative answer stops being useful
# before the absolute one does, so when in doubt, switch early.
_ABSOLUTE_AFTER = 14 * 24 * 3600


def _ago(epoch: int, now: int) -> str:
    """`17 hours ago`, or `2026-05-26` once "ago" stops meaning anything.

    Past the threshold the relative form is abandoned rather than extended —
    nobody is shown "2 years ago". A stamp ahead of `now` is a wrong clock on
    some committer's machine; "in 3 hours" under a last-edited column reads as
    broken, so the absolute date — which is at least true — is the answer there
    too.

    Arithmetic and f-strings only: this file is AST-banned from every
    `.replace` attribute call (`test_no_page_is_assembled_by_substitution`),
    and `datetime.replace` is spelled exactly like `str.replace` to that test.
    """
    gone = now - epoch
    if gone < 0 or gone >= _ABSOLUTE_AFTER:
        return datetime.fromtimestamp(epoch, tz=UTC).date().isoformat()
    if gone < 60:
        return "just now"
    if gone < 3600:
        minutes = gone // 60
        return "a minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if gone < 86400:
        hours = gone // 3600
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    days = gone // 86400
    return "a day ago" if days == 1 else f"{days} days ago"


# A date, the way this app reads one out loud: `14.07.2026`, day first, dots.
# jcanton, 2026-08-21: "I'd like to reverse the order of the dates in the entire
# app". Only what is DRAWN — what is stored, sorted, put in a `<input type=date>`
# and sent over the API stays `2026-07-14`, which is the one format that sorts as
# text, parses without a locale and cannot be read as a different day in another
# country.
def _read_date(value: object) -> str:
    text = str(value or "")
    parts = text.split("-")
    return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else text


# Fields that name a person. They get a datalist of everyone already in the corpus,
# so a typo shows up as "not in the list" rather than as a reviewer who does not exist.
PEOPLE_FIELDS = ("owner", "assignees", "reviewers", "reported_by", "written_by")
# Which suggestion list each field draws from. A datalist only completes a whole
# value, so the comma-separated ones also get an "add" picker that appends a token
# — otherwise the suggestions are useless the moment there is more than one name.
SUGGESTS = {
    "owner": "people", "assignees": "people", "reviewers": "people",
    "parent": "records", "depends_on": "records", "tags": "tags", "prs": "prs",
    "reported_by": "people", "written_by": "people",
    "pitched_into": "records", "became": "records",
    # A cycle number is a reference too. Typed from memory it is off by one as
    # often as it is right, and a record bet into a cycle nobody has named is
    # weeks that never appear on anybody's capacity.
    "cycle": "cycles",
}


# The two fields whose empty box says who the server will write. The placeholder
# is the signed-in login because that is the value `POST /api/record` stamps when
# the box is left empty — a hint that tells the truth about what will happen.
_LOGIN_PLACEHOLDER = ("reported_by", "written_by")


def _editable_for(record: Record, prefix: str = "field", signed_in: str = "") -> list[dict]:
    """The fields this kind actually has, with the type a form must coerce back to.

    The prefix is what makes a control's id unique on the page it lands on: the
    static detail export holds every record in one file, so `owner` alone would
    be the same id sixteen times over and every `<label for>` on the page would
    point at the first of them.
    """
    return [
        {
            "name": name,
            "id": f"{prefix}-{name}",
            "type": kind,
            "value": getattr(record, name),
            "gates": REQUIRED_AT.get(name, ()),
            "list": SUGGESTS.get(name),
            "placeholder": signed_in if name in _LOGIN_PLACEHOLDER else "",
            "text": ", ".join(str(v) for v in getattr(record, name))
            if kind == "list"
            else ("" if getattr(record, name) is None else getattr(record, name)),
        }
        for name, kind in EDITABLE.items()
        # What the kind has, minus what its rung does not read. A product
        # inherits every field a record has and is a container: offering a box
        # for an owner it will then be warned about is the form and the validator
        # disagreeing in the most annoying possible order.
        if name in type(record).model_fields
        and name not in unread_fields(record.kind)
        # And nothing to file the top rung under. Not routed through
        # `unread_fields`: a parent written on a product is already reported, by
        # the containment rule that knows what it may be filed under, and two
        # warnings about one field is one of them being noise.
        and not (name == "parent" and not PARENT_KINDS[record.kind])
    ]


_SIZE_FIELD_NAME = "person_weeks"


# Off the ladder, so the create form and the table offer a rung the moment one is
# added rather than the day somebody remembers this line. It was written out here,
# and this file already imports `PARENT_KINDS` from the same place — two spellings
# of the same list, and the one that got stale was always going to be this one.
KINDS = tuple(rung.name for rung in KIND_LADDER)
# The model behind each of them, once. This was a dict literal inside `_new_rows`
# and is now asked two more questions — which fields a kind has, for the create
# form and for the row a person types straight into the table — and three copies
# of "these are the three kinds" is three places to forget a fourth.
_KIND_MODELS: dict[str, type[Record]] = {rung.name: rung.model for rung in KIND_LADDER}

# The body a new record starts from, per kind.
#
# The pitch one is the team's own shaping template, copied from the note they
# already write pitches against, minus its three header lines: `Appetite` and
# `Developers` are fields here, `Shaped by` is what `owner` records now, and a
# heading restating a field is the two-copies-of-one-fact problem this tool
# exists to end. The guidance stays
# in HTML comments exactly as it is written there — invisible on the page, see
# `without_comments` — so a pitch drafted in HackMD and one drafted here are the
# same document.
#
# It is also missing that template's `## Progress`, and that is the one real
# departure: a pitch's progress is its TASKS, each one a record with an owner, a
# size and a status of its own. The HackMD list becomes those tasks, its
# sub-items stay as checkboxes inside them — which is what the task template
# below keeps a `## Progress` for — and the pitch page draws the roll-up.
#
# A template is a starting point and nothing else: no heading here is required,
# validated, or read by anything but `_shaping_hints`, which only prints a note.
_PITCH_TEMPLATE = """## Problem
<!-- The raw idea, a use case, or something we have seen that motivates us to
     work on this. -->

## Appetite
<!-- How much time this deserves and how that shapes the solution. The number
     itself is the Appetite field beside the body; this is the reasoning. -->

## Solution
<!-- The core elements, in a form that is easy to understand immediately.
     Too vague and nobody can tell when it is done. Too concrete and you have
     made the decisions the people building it should be making. -->

## Rabbit holes
<!-- Details worth calling out now to avoid trouble later. -->

## No-gos
<!-- What is deliberately excluded, to fit the appetite or to keep the problem
     tractable. -->

## For later
<!-- Anything cut to fit the appetite, kept where the next shaping will find it. -->
"""

_TASK_TEMPLATE = """## Problem
<!-- What is wrong or missing, concretely. -->

## Solution
<!-- What will be done about it. -->

## Progress

- [ ]
"""

_PROJECT_TEMPLATE = """## Problem
<!-- What this milestone exists to make possible. -->

## Appetite
<!-- Which cycles this is expected to span, and what happens if it does not fit. -->

## Solution
<!-- The pitches that add up to it, and the order they matter in. -->

## No-gos
<!-- What this milestone is not, so its pitches do not grow into it. -->
"""

_PRODUCT_TEMPLATE = """<!-- A sentence or two: what this codebase is, and what
     the plan is doing with it. A product groups projects and holds no work of
     its own, so there is nothing here to shape. -->
"""

TEMPLATES = {
    "pitch": _PITCH_TEMPLATE,
    "task": _TASK_TEMPLATE,
    "project": _PROJECT_TEMPLATE,
    "product": _PRODUCT_TEMPLATE,
    "blank": "",
}
