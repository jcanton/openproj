"""A ```mermaid fence, drawn as a diagram.

Three claims, in three mediums, because no one of them can answer another.

The renderer's half is a parse: which markup a fence becomes, and whether the
text inside it is escaped like every other value that crosses into a page. The
bundle's half is a scan of the vendored bytes: the whole argument for shipping
mermaid is that it needs no `'unsafe-eval'`, fetches nothing, and is never on a
page, and each of those is a property of a file that a re-vendor can change. And
the drawing's half is a real browser against a real server, because "it rendered"
is a claim about pixels and a fetch, and the page it is made of has neither until
Chrome runs it.
"""

from __future__ import annotations

import contextlib
import json
import re
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

import pygit2
import pytest
import uvicorn
from test_store import commit_directly

from openproj.index import build_index
from openproj.model import load_repo
from openproj.render import ROUTES, STATIC, render_help, render_static
from openproj.render.markdown import _markdown
from openproj.vendor import _static_dir
from openproj.web import STATIC_ALLOWLIST, create_app

SECRET = "a-signing-secret-for-tests"

# The fence the whole feature exists for, near enough: `docs/data-model.md`'s
# promotion flowchart is a `flowchart LR` with two subgraphs, and this is the
# same shape without the corpus's own words in it.
DIAGRAM = """```mermaid
flowchart LR
  subgraph inbox["not in the plan"]
    note["note"]
  end
  note --> pitch["pitch"]
```
"""


# --------------------------------------------------------------------------- #
# The renderer: which markup a fence becomes


def test_a_mermaid_fence_is_a_diagram_where_there_is_a_server():
    drawn = str(_markdown(DIAGRAM, ROUTES))
    assert '<pre class="mermaid">' in drawn
    assert "flowchart LR" in drawn
    assert "language-mermaid" not in drawn


def test_a_mermaid_fence_is_a_code_block_where_there_is_not():
    """The static export has no server to fetch 3.5 MB from, and a `<pre>` that
    sits empty for ever is worse than the source it replaced. The prefix decides,
    which is the seam `_image` and `_link` already switch on.
    """
    drawn = str(_markdown(DIAGRAM, STATIC))
    assert '<pre class="mermaid">' not in drawn
    assert "flowchart LR" in drawn


def test_every_other_fence_is_left_alone():
    for info in ("", "python", "bash", "mermaidish"):
        drawn = str(_markdown(f"```{info}\nnot a diagram\n```\n", ROUTES))
        assert '<pre class="mermaid">' not in drawn, info
        assert "not a diagram" in drawn, info
    # And the info string's FIRST word is what decides, so a fence carrying an
    # attribute after the language is still a diagram.
    assert '<pre class="mermaid">' in str(_markdown("```mermaid title=x\nA-->B\n```\n", ROUTES))


def test_the_text_inside_a_fence_is_escaped_like_any_other_value():
    """A fence in a shaping document is text a member typed, and this repository
    has shipped five escaping bugs into pages that all looked like this one.
    `Markup(...).format` is the boundary; nothing here builds markup out of it.
    """
    hostile = "```mermaid\nA --> B</pre><script>alert(1)</script>\n```\n"
    drawn = str(_markdown(hostile, ROUTES))
    assert "<script>" not in drawn
    assert "&lt;/pre&gt;&lt;script&gt;" in drawn
    assert drawn.count('<pre class="mermaid">') == 1


# --------------------------------------------------------------------------- #
# The page: who carries the loader


def index_of(seed_root: Path):
    records, config, unreadable = load_repo(seed_root)
    return build_index(records, config, date(2026, 8, 17), unreadable)


def test_only_a_page_with_a_diagram_on_it_carries_the_loader(seed_root: Path):
    """3.5 MB is fetched by the loader, so the loader is on the pages that have
    something to draw and nowhere else. Help has the data model's flowchart in it;
    the people page has no document at all.
    """
    from openproj.render import render_people

    index = index_of(seed_root)
    served_help = render_help(index, ROUTES)
    assert '<pre class="mermaid">' in served_help
    assert "mermaidLibrary" in served_help

    people = render_people(index, ROUTES)
    assert "mermaidLibrary" not in people


def test_a_title_that_merely_equals_the_mechanism_does_not_turn_it_on():
    """`_page` decides by searching the finished markup for a literal, which is
    the one thing this repository refuses to do everywhere else — so the reason it
    is safe is asserted rather than asserted-in-a-comment. `_ENV` autoescapes, so
    a value containing these characters reaches the page as `&lt;pre …&gt;` and
    cannot be mistaken for markup the renderer emitted.

    This is round two's question — what if a value *equals* the mechanism instead
    of exploiting it — asked of the mechanism that was added last.
    """
    from openproj.render.shell import _page

    page = _page('<pre class="mermaid">flowchart LR</pre>', "<p>nothing here</p>", links=ROUTES)
    assert "mermaidLibrary" not in page
    assert '<pre class="mermaid">' not in page


def test_the_static_export_carries_no_diagram_and_no_loader(seed_root: Path, tmp_path: Path):
    """`openproj render` writes files opened over `file://`. A page there that
    fetched a bundle would retry against nothing; a page that carried one would
    fail `test_no_page_asks_the_network_for_a_font`. So neither is there, and an
    exported page's bytes are what they were before mermaid was vendored.
    """
    written = render_static(index_of(seed_root), tmp_path)
    for name in written:
        body = (tmp_path / name).read_text(encoding="utf-8")
        assert '<pre class="mermaid">' not in body, name
        assert "mermaidLibrary" not in body, name
        assert "/static/mermaid.min.js" not in body, name


# --------------------------------------------------------------------------- #
# The bundle: the properties the whole argument rests on


def bundle() -> str:
    return (_static_dir() / "mermaid.min.js").read_text(encoding="utf-8")


def test_the_bundle_needs_no_unsafe_eval():
    """**The one property that would have made this a refusal.** Every page ships
    under `script-src 'unsafe-inline'` and no `'unsafe-eval'`, and a library that
    needs one would have cost the whole policy rather than one page. Checked
    against the bytes rather than against the release notes, because it is a
    re-vendor that would change it.
    """
    source = bundle()
    assert "new Function" not in source
    assert not re.search(r"\beval\(", source)


def test_the_bundle_fetches_nothing_of_its_own():
    """It is served from this origin and injected as a script, so anything it went
    on to fetch would be a request this app did not make and cannot see. Three
    ways it could: a dynamic `import()` of a chunk of itself, a CDN, a socket.
    """
    source = bundle()
    assert "import(" not in source, "the bundle loads a chunk of itself at runtime"
    assert "cdn." not in source
    assert "WebSocket" not in source


def test_the_bundle_is_on_no_page():
    """It is 3.5 MB and it holds eighty `url(` tokens that are SVG fragment
    references — `url("+e.svgId+` among them — so a page carrying it fails
    `test_no_page_asks_the_network_for_a_font`, which reads every `url(` on a page
    and demands `data:` or `#`. Both are reasons to fetch it rather than inline
    it, and this is what holds that.
    """
    signature = bundle()[:200]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        records, config, unreadable = load_repo(Path(__file__).resolve().parents[1] / "seed")
        index = build_index(records, config, date(2026, 8, 17), unreadable)
        for name in render_static(index, root):
            assert signature not in (root / name).read_text(encoding="utf-8"), name
    assert signature not in render_help(index, ROUTES)


def test_the_bundle_has_a_route_to_be_fetched_from():
    assert STATIC_ALLOWLIST["mermaid.min.js"] == "application/javascript"


def test_the_route_serves_the_bytes_that_are_checksummed(repo_path: Path):
    from fastapi.testclient import TestClient

    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        response = client.get("/static/mermaid.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.content == (_static_dir() / "mermaid.min.js").read_bytes()


# --------------------------------------------------------------------------- #
# The drawing: a real browser, a real fetch


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    """A bare repository holding one record whose body is three diagrams.

    Written here rather than borrowed from `test_web`, because what this file
    needs of a corpus is exactly one thing no other corpus has: a good fence, a
    fence that will not parse, and a good fence AFTER the broken one.
    """
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, PLAN, "a plan with diagrams in it")
    return path


PLAN = {
    "config/defaults.yaml": "schema_version: 2\nnominal_availability: 1.0\n",
    "pitches/pitch-aaaaaa.md": (
        "---\n"
        "id: pitch-aaaaaa\n"
        "kind: pitch\n"
        "title: Three diagrams\n"
        "status: shaping\n"
        "---\n"
        "\n"
        "One that draws:\n"
        "\n"
        "```mermaid\n"
        "flowchart TD\n"
        '  a["shape"] --> b["bet"]\n'
        "```\n"
        "\n"
        "One that will not parse:\n"
        "\n"
        "```mermaid\n"
        "flowchart TD\n"
        '  a[["\n'
        "```\n"
        "\n"
        "And one after it, which must still draw — and which is deliberately\n"
        "wider than a phone, because the rule that keeps a drawing inside its\n"
        "column is an `!important` against mermaid's own inline `max-width`, and\n"
        "a corpus of small diagrams cannot tell whether that rule does anything:\n"
        "\n"
        "```mermaid\n"
        "flowchart LR\n"
        '  a["a shaping document"] --> b["the betting table said yes"]\n'
        '  b --> c["six weeks of building"]\n'
        '  c --> d["the review meeting"]\n'
        "```\n"
    ),
}


@contextlib.contextmanager
def serving(app):
    """A real uvicorn on a real port. `TestClient` cannot answer any question in
    this section: the claim is that a browser fetches 3.5 MB from this origin and
    runs it, and there is no browser and no origin in an ASGI shim.
    """
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level="error", timeout_graceful_shutdown=1
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the server never came up"
    try:
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(10)


# The empty string and not `null` while the page is still working, and it is the
# difference between a test and a test that lies. `in_a_live_page` polls until
# the expression is truthy — and `JSON.stringify(null)` is the four-character
# string `"null"`, which is truthy, so a "not ready yet" spelled that way is
# accepted as the answer on the first poll, before mermaid has been fetched.
ASKED = """
(() => {
  const blocks = [...document.querySelectorAll('pre.mermaid')];
  // **Ready is every block settled, not the first one drawn.** They are rendered
  // one at a time, so a question asked the moment block one has an `<svg>`
  // reports `drawn: 1` on a page that goes on to draw two — a test that fails on
  // timing rather than on the thing it is about. A block is settled when it has
  // a drawing or a line beside it saying why it has not.
  const settled = b => b.querySelector('svg')
    || (b.nextElementSibling && b.nextElementSibling.className === 'mermaidwhy');
  if (!blocks.length || !blocks.every(settled)) return '';
  const first = blocks[0].querySelector('svg');
  const shape = blocks[0].querySelector('.node .basic, .node rect, .node polygon');
  const label = blocks[0].querySelector('.node text');
  // Resolved the way the page resolves it, so this compares the drawing against
  // the stylesheet rather than against a colour written down in a test — which
  // is what lets it stay true across nine schemes and two polarities.
  const swatch = document.createElement('span');
  swatch.style.color = getComputedStyle(document.documentElement)
    .getPropertyValue('--surface-2').trim();
  document.body.appendChild(swatch);
  const surface2 = getComputedStyle(swatch).color;
  swatch.remove();
  return JSON.stringify({
    blocks: blocks.length,
    drawn: blocks.filter(b => b.querySelector('svg')).length,
    foreignObjects: document.querySelectorAll('pre.mermaid foreignObject').length,
    why: [...document.querySelectorAll('.mermaidwhy')].map(p => p.textContent),
    brokenKeptItsSource: (blocks[1].textContent || '').includes('flowchart TD'),
    whyIsBesideTheBroken: !!(blocks[1].nextElementSibling
      && blocks[1].nextElementSibling.className === 'mermaidwhy'),
    fill: shape ? getComputedStyle(shape).fill : null,
    surface2,
    font: label ? getComputedStyle(label).fontFamily : null,
    injected: document.querySelectorAll('script[data-injected-bundle="mermaid"]').length,
    wider: Math.round(first.getBoundingClientRect().width) > innerWidth,
    pageScrolls: document.documentElement.scrollWidth > innerWidth,
  });
})()
"""


def drew(url: str, profile: Path, seconds: float = 45) -> dict:
    from browser import chrome, in_a_live_page

    value, said = in_a_live_page(chrome(), url, ASKED, profile, seconds=seconds)
    assert value, "no diagram was drawn before the deadline"
    found = json.loads(value)
    found["console"] = [line for line in said if line.strip()]
    return found


def test_a_diagram_is_drawn_in_the_apps_own_colours(repo_path: Path, tmp_path: Path):
    """Rendered, fetched and painted — none of which a parsed document can show.

    The console is half the evidence: a policy that refused the fetch, or a
    library reaching for `eval`, is a line naming the directive and nothing else
    on this page produces one.
    """
    with serving(create_app(repo_path, auth="dev", secret=SECRET)) as url:
        found = drew(f"{url}/detail/pitch-aaaaaa", tmp_path)
    assert found["console"] == []
    assert found["injected"] == 1, "the bundle was fetched and injected exactly once"
    assert found["blocks"] == 3
    # The app's own ground, and asserted as the value the stylesheet resolves
    # rather than as "not mermaid's default" — `#ECECFF` is what the `base` theme
    # fills a node with when nothing tells it otherwise, and a test that only
    # ruled that one out would pass on any colour at all.
    assert found["fill"] == found["surface2"], (found["fill"], found["surface2"])
    assert "Inter" in (found["font"] or ""), found["font"]
    # `htmlLabels: false` in both places. Set on `flowchart` alone this was 5.
    assert found["foreignObjects"] == 0


def test_one_diagram_that_will_not_parse_costs_that_diagram(repo_path: Path, tmp_path: Path):
    """The defect this test is written for, watched failing before it was fixed.

    `suppressErrorRendering` makes `run` reject, but mermaid has already stamped
    `data-processed` and emptied the element — so a check on that attribute left
    an empty box and no message. And the first version of the line beside it
    called a helper that is not on this scope, threw inside the loop, and took the
    diagram AFTER the broken one down with it: measured at 1 drawn of 3.
    """
    with serving(create_app(repo_path, auth="dev", secret=SECRET)) as url:
        found = drew(f"{url}/detail/pitch-aaaaaa", tmp_path)
    assert found["drawn"] == 2, "a bad fence cost a good one"
    assert found["brokenKeptItsSource"], "the source was thrown away with the diagram"
    assert found["whyIsBesideTheBroken"], "an empty box with nothing to say about it"
    assert found["why"] == ["This diagram could not be drawn. Its text is below."]


def test_a_diagram_does_not_push_the_page_sideways(repo_path: Path, tmp_path: Path):
    """A tripwire, and it is written down as one rather than dressed up as a
    check of a rule of ours.

    Nothing in this app's stylesheet is what keeps the drawing inside the column
    today: mermaid's `useMaxWidth` default writes `max-width: <computed>px` and
    `width: 100%` onto its own `<svg>`, and the third diagram in the fixture —
    laid out at 716px, deliberately wider than a phone — comes out 460 in a 460px
    column without help. The `!important` rule written to outrank that inline
    style was measured doing nothing and deleted.

    So what this holds is mermaid's behaviour rather than ours, which is exactly
    the kind of thing a vendored library changes in a minor release. The page not
    scrolling sideways is the app's oldest visual rule, and this is the one place
    a 3.5 MB library gets to break it.

    Asked through `_devtools` rather than `in_a_live_page`, which takes no window
    size — and a question about a page being too wide, asked at 1200px, is a
    question that answers itself.
    """
    import browser as browsing

    with serving(create_app(repo_path, auth="dev", secret=SECRET)) as url:
        with browsing._devtools(
            browsing.chrome(),
            f"{url}/detail/pitch-aaaaaa",
            tmp_path,
            flags=("--window-size=390,780",),
        ) as (call, said):
            found = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                answer = browsing._evaluated(call, ASKED, patient=True)
                if answer:
                    found = json.loads(answer)
                    break
                time.sleep(0.25)
    assert found, "no diagram was drawn before the deadline"
    assert found["drawn"] == 2
    assert not found["wider"], "the drawing is wider than the window it is in"
    assert not found["pageScrolls"], "the page scrolls sideways beside a diagram"
    assert [line for line in said if line.strip()] == []
