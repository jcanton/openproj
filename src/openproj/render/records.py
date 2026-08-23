"""The landing list, and the two inbox views held to one kind each."""

from __future__ import annotations

from ..index import Index, _product_of, _project_of, predicates_of
from ..model import RUNG, unread_fields
from .controls import _FILTER_JS, _facets_html
from .env import _compiled
from .shell import _NAV, STATIC, Links, _page
from .styles import _SCROLL_STYLE
from .tokens import _ago

_RECORDS = """
{#- Announced, not drawn: the lit nav item already says which view this is. -#}
<h1 class="sr-only">{{ heading }}</h1>
<p class="hint">{{ describe }}</p>
{%- if editable %}
<p class="editbar"><a class="button" href="{{ create.href }}">{{ create.label }}</a></p>
{%- endif %}
{{ facets }}
<div class="table-scroll" data-fills><table id="records"><thead><tr>
  {%- for column in columns %}
  <th data-col="{{ column }}">{{ label(column) }}</th>
  {%- endfor %}
</tr></thead><tbody>
{%- for r in rows %}
  <tr data-id="{{ r.id }}">
    <td data-col="kind"><span class="chip kind-{{ r.kind }}">{{ r.kind }}</span></td>
    <td data-col="title"><a href="{{ links.record }}{{ r.id }}">{{ r.title or r.id }}</a></td>
    <td data-col="who">{{ r.who or '—' }}</td>
    <td data-col="tags">{{ r.tags|join(', ') or '—' }}</td>
    {%- if timed %}<td data-col="edited">{{ r.ago }}</td>{% endif %}
  </tr>
{%- endfor %}
{#- The no-records state is server-rendered so it is right before any script
    runs and in an export where none may — and inside the table body, with the
    control that gets you out of it, the shape every empty record table here
    takes. The script below redraws the same row for the states only the
    browser can reach; it rewrites the two sentences and never the create
    link, which only the empty-view state can be showing. -#}
  <tr class="nothing" id="records-empty"{% if rows %} hidden{% endif %}><td
      colspan="{{ columns|length }}">
    <p class="headline">{% if not rows %}{{ said.empty_headline }}{% endif %}</p>
    <p class="hint">{% if not rows %}{{ said.empty_hint }}{% endif %}</p>
    {%- if not rows and editable %}
    <a class="button primary" href="{{ create.href }}">{{ create.label }}</a>
    {%- endif %}
  </td></tr>
</tbody></table></div>
<script id="landing" type="application/json">{{ payload|tojson }}</script>
{{ filters }}
<script>
// The bar above is `_facets_html`, which renders #q, #query-error and #unfilter
// unconditionally — exactly what `_FILTER_JS` requires, because its listeners
// are unguarded. The rows are server-rendered; this script only hides them, so
// a payload that did not survive the trip degrades to an unfiltered list
// rather than an empty page.
let RECORDS = null;
try {
  RECORDS = JSON.parse(document.getElementById('landing').textContent);
} catch (error) { RECORDS = null; }
const RECORDS_LOADED = RECORDS !== null;
if (!RECORDS_LOADED) RECORDS = {rows: {}};

const recordItems = [...document.querySelectorAll('#records tbody tr[data-id]')];
const recordsEmpty = document.getElementById('records-empty');

// The sentences the server also draws, handed over rather than retyped: the
// empty-view pair was already rendered into the row above when the view was
// empty, and a second spelling here is what would let the two drift.
const SAID = {{ said|tojson }};

// Four states, four sentences, and they must not look like each other: a view
// with no records at all, a payload that did not load, a query that cannot be
// read (whose parse error `sayQueryError` already puts beside the box — the
// row only points at it), and a search that matched nothing. The empty view is
// asked FIRST: with nothing to filter, a sentence about the search box would
// be true and useless.
function recordsApply() {
  let shown = 0;
  for (const item of recordItems) {
    const row = RECORDS.rows[item.dataset.id];
    const kept = !RECORDS_LOADED || (!!row && matches(row));
    item.hidden = !kept;
    shown += kept ? 1 : 0;
  }
  let headline = '', hint = '', spoken = '';
  if (!recordItems.length) {
    headline = SAID.empty_headline;
    hint = SAID.empty_hint;
  } else if (!RECORDS_LOADED) {
    headline = 'This search cannot run.';
    hint = 'The page arrived without its search data, so the list is shown unfiltered.';
    spoken = headline;
  } else if (queryError()) {
    headline = 'That search cannot be read.';
    hint = 'What is wrong with it is beside the search box.';
  } else if (!shown) {
    headline = SAID.none_headline;
    hint = SAID.none_hint;
    spoken = headline;
  }
  recordsEmpty.querySelector('.headline').textContent = headline;
  recordsEmpty.querySelector('.hint').textContent = hint;
  recordsEmpty.hidden = !headline;
  // The row is not a live region, and must not be: role="status" on the tr or
  // its cell would overwrite the table's row and cell semantics. So the two
  // states only this script can reach a reader through go out over the shell's
  // `announce` into the sr-only #announce region (this page has no #state).
  // NOT the query-error state — #query-error is role="status" and speaks the
  // parse error itself, so a second sentence here would double-speak — and not
  // the empty view, which is server-rendered and never changes under a reader.
  // '' when rows are showing again, so the region does not hold a stale "no
  // match" and a later identical state is a change the region announces.
  announce(spoken);
}
addEventListener('openproj:filter', recordsApply);
recordsApply();
</script>
"""

_RECORDS_STYLE = _SCROLL_STYLE + """
/* One row per record: chip, title, who, tags, time. The chips come from the
   shell (`.chip.kind-…`), so a kind added to the ladder arrives here already
   drawn; the scroll box and the frozen header row are `_SCROLL_STYLE`, the
   same mechanism the plan's table stands on. Every rule below is resolved
   against that block by name: each is (1,1,1) against its bare (0,0,2)
   elements, wins exactly its own properties, and none of them positions a
   cell — the move that once stole `position: sticky` from the plan table's
   title column. */
/* Against the browser's own `[hidden]` at (0,1,0) — which already hides an
   unmatched row today, since no author rule gives these rows a display.
   Pinned anyway: a future `#records tr { display: … }` is (1,0,1), quietly
   beats the UA rule, and puts every filtered-out row back on screen — the
   `.commitbar[hidden]` failure, which this page shipped once already as
   `#records li { display: flex }` over the UA rule. */
#records tbody tr[hidden] { display: none; }
/* The column that is a sentence, and the row's link. The nothing row's cell
   has no data-col, so it needs no exception the way `:nth-child(2)` once did. */
#records td[data-col="title"] { font-weight: 600; }
/* A time and a login are tokens, not sentences: wrapped, "17 hours ago" reads
   as two facts and "msimberg" as two names (seen at 700px). `nowrap` makes
   the shared block's `overflow-wrap: anywhere` moot in these two columns,
   which is the point — when the window is too narrow the row scrolls
   sideways inside `.table-scroll`, the shared box's job. Titles and tags
   keep wrapping. */
#records td[data-col="who"] { white-space: nowrap; }
/* The header too: "Last modified" broke over two lines at 1200px while every
   cell under it held one — a two-line label over one-line values reads as a
   different column. Beats only the UA's `white-space: normal`; nothing else
   sets the property on a th. */
#records th[data-col="edited"] { white-space: nowrap; }
#records td[data-col="edited"] { color: var(--muted); font-size: 12px;
                                 white-space: nowrap;
                                 font-variant-numeric: tabular-nums; }
"""


def _record_row(index: Index, record_id: str) -> dict:
    """One landing row: what the page draws, and what the search box may ask.

    The queryable values mirror `query_fields` (`index.py`) — the same
    `unread_fields` gate, the same holder walk, and both resolved against the
    TOTAL map — because the box's `matches()` and the server's `apply_filters`
    must find the same records: the row used to carry only id, kind, title and
    tags, so `status:done` typed into the box, or an `/?owner=…` URL pasted
    from the table, resolved to `[]` and hid every row under "no match" while
    the server answered them all. `predicates` is real for the same reason.

    Values are RAW where the server lowers its own, because `matches()`'s
    dropdown loop compares a row against URL params without lowering and the
    params carry the table's raw facet values; the query language lowers both
    sides itself. Resolved against `index.records`, unlike the table's `_row`:
    this page lists records the plan does not hold, and `query_fields` — the
    contract this map is held to — walks the total map too.
    """
    record = index.records[record_id]
    unread = unread_fields(record.kind)

    def read(name):
        return None if name in unread else getattr(record, name)

    return {
        "id": record.id,
        "kind": record.kind,
        "title": record.title,
        "tags": record.tags,
        "status": read("status"),
        "owner": read("owner"),
        "assignees": read("assignees"),
        "reviewers": read("reviewers"),
        "priority": read("priority"),
        "cycle": read("cycle"),
        "prs": read("prs"),
        "project": _project_of(record, index.records),
        "product": _product_of(record, index.records),
        "predicates": predicates_of(index, record_id),
        "search": index.search_blob[record_id],
    }


def render_records(
    index: Index,
    links: Links = STATIC,
    base_commit: str | None = None,
    edited: dict[str, int] | None = None,
    now: int = 0,
    only: str | None = None,
) -> str:
    """The landing list — and, held to one kind each, the two inbox views.

    One renderer because they are one page: `/` is every record, `/issues` and
    `/notes` are the same rows with `kind` decided by the route — quick access
    to what would otherwise be a click on a filter. What varies is the
    population and the words; the columns, the search box and the scroll
    mechanism do not. There is deliberately no state dropdown, which the old
    inbox pages carried: the query box already says `status:shelved`, and a
    second control saying the same thing in different vocabulary is the drift
    the shared bar exists to end.

    One row is a kind chip, a title linking to the record's page, who is
    behind it (`Rung.who` — the holder for plan kinds, the reporter or writer
    for the inbox ones), its tags, and one relative time. Sorted last-edited
    descending.

    `edited` is record id -> epoch seconds (`Store.last_edited` joined through
    `edited_by_id`), or None where there is no history to ask — `openproj
    render` over a plain directory. None OMITS the time column rather than
    leaving it blank, because blank looks broken; the list then sorts by id,
    the one order that exists without a clock. File mtimes are never consulted:
    they lie after a fresh clone.

    `base_commit` is what says a server is behind the page: with it the create
    button is drawn, kind pre-filled per view. Without it — the static
    export — there is nowhere to post and no button.
    """
    timed = edited is not None
    editable = base_commit is not None
    # The Links field, the nav slot and the export filename in one word,
    # off the ladder rather than a second map: `RUNG["issue"].directory`
    # is "issues".
    key = RUNG[only].directory if only else "records"
    word = only or "record"
    asks: dict[str, dict] = {}
    rows = []
    for record_id, record in index.records.items():
        if only and record.kind != only:
            continue
        asks[record_id] = _record_row(index, record_id)
        epoch = (edited or {}).get(record_id, 0)
        rung = RUNG[record.kind]
        rows.append(
            asks[record_id]
            | {
                "epoch": epoch,
                # Empty when the id has no stamp (a path collision the pages
                # already report as a blocker): nothing, not 1970.
                "ago": _ago(epoch, now) if timed and epoch else "",
                # Through the same gate `_record_row` reads by, so a product —
                # whose `owner` is a field it does not read — answers Who with
                # nothing rather than with a stray value from its file.
                "who": None if rung.who in unread_fields(record.kind)
                       else getattr(record, rung.who),
            }
        )
    if timed:
        rows.sort(key=lambda row: (-row["epoch"], row["id"]))
    else:
        rows.sort(key=lambda row: row["id"])
    create = {
        "label": f"Create {word}",
        # On `/` the kind picker opens on its default; the inbox views
        # pre-fill theirs.
        "href": links.new if only is None else f"{links.new}?kind={only}",
    }
    empty_headline, empty_hint = {
        "records": (
            "This plan has no records yet.",
            "Everything here starts as a record: work to plan, an issue "
            "somebody noticed, half a thought in a note.",
        ),
        "issues": (
            "No issues are open.",
            "An issue is something somebody noticed and nobody has fixed. "
            "There is nothing here, which is good news.",
        ),
        "notes": (
            "Nothing has been written down yet.",
            "A note is where an idea goes before anybody knows what it is — "
            "no owner, no size, no cycle.",
        ),
    }[key]
    said = {
        "empty_headline": empty_headline,
        "empty_hint": empty_hint,
        "none_headline": f"No {word} matches this search.",
        "none_hint": f"Every {word} is hidden by what is in the box.",
    }
    describe = {
        "records": "Everything written down in this plan, newest edit first — "
                   "the plan's work, its issues and its notes.",
        "issues": "Something somebody noticed. At the betting table somebody "
                  "reads what is open and writes a pitch for what matters.",
        "notes": "Something somebody is thinking about, before anybody knows "
                 "what it is. A note has no owner, no size and no cycle — when "
                 "it turns out to be work, promote it and it becomes a "
                 "project, a pitch or a task.",
    }[key]
    body = _compiled(_RECORDS).render(
        rows=rows,
        timed=timed,
        editable=editable,
        links=links,
        heading=dict(_NAV)[key],
        describe=describe,
        create=create,
        said=said,
        columns=("kind", "title", "who", "tags") + (("edited",) if timed else ()),
        payload={"rows": asks},
        # No dropdowns: facets are plan vocabulary and this page is the whole
        # record population. The bar still renders #q, #query-error and
        # #unfilter, which is all `_FILTER_JS`'s unguarded listeners need.
        facets=_facets_html(index.facets, fields=()),
        filters=_FILTER_JS,
    )
    return _page(
        f"openproj — {key}", body, _RECORDS_STYLE, links, key, index.unreadable
    )
