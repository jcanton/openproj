"""What a page is allowed to do, said by the server and carried by the page.

Every response had four headers: date, server, content-length, content-type. No
Content-Security-Policy, no X-Content-Type-Options, no Referrer-Policy, nothing
about framing. This application is unusually well placed to have a strict one —
no npm, no CDN, every library and the typeface inlined — so `default-src 'none'`
costs it nothing it uses.

It is also the second lock on a door already shut once. A remote image is rewritten
into a link at render time so that a shaping document cannot become a tracking
pixel aimed at everyone who opens it; that is one function enforcing one spelling
of one rule. `img-src` closes the same door for every spelling, including the ones
nobody has thought of yet.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openproj.render import CSP
from openproj.web import create_app

SEED = Path(__file__).resolve().parents[1] / "seed"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    import pygit2

    plan = tmp_path / "plan"
    plan.mkdir()
    repo = pygit2.init_repository(str(plan))
    for source in SEED.rglob("*"):
        if source.is_file():
            target = plan / source.relative_to(SEED)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    repo.index.add_all()
    repo.index.write()
    who = pygit2.Signature("d", "d@x")
    repo.create_commit("HEAD", who, who, "seed", repo.index.write_tree(), [])
    with TestClient(create_app(plan, auth="dev", secret="s", client_id="", client_secret="")) as c:
        yield c


@pytest.mark.parametrize(
    "route", ["/", "/graph", "/timeline", "/cycles", "/people", "/detail", "/api/index.json"]
)
def test_every_response_says_what_it_may_do(client: TestClient, route: str):
    answer = client.get(route)

    assert answer.status_code == 200, route
    assert answer.headers["content-security-policy"].startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in answer.headers["content-security-policy"]
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert answer.headers["x-frame-options"] == "DENY"


def test_a_refusal_carries_them_too(client: TestClient):
    """The response nobody remembers to cover. A 404's body is a sentence somebody
    typed and a 500's is a traceback, and a browser renders both."""
    missing = client.get("/detail/task-ffffff")

    assert missing.status_code == 404
    assert "default-src 'none'" in missing.headers["content-security-policy"]
    assert missing.headers["x-content-type-options"] == "nosniff"


def test_the_page_carries_the_policy_the_server_sends(client: TestClient):
    """One policy, two deliveries. A served page has both; they have to agree, or
    the export is running under a rule the server never tested."""
    page = client.get("/").text
    sent = client.get("/").headers["content-security-policy"]

    in_page = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', page
    )
    assert in_page, "the page says nothing on its own"
    assert in_page.group(1) == CSP
    assert sent == f"{CSP}; frame-ancestors 'none'"


def test_the_static_export_carries_it_because_it_has_no_server(tmp_path: Path):
    """`openproj render` writes files that are opened over file://, mailed as
    attachments and kept on memory sticks, and they carry the whole plan and every
    vendored library inside them. A header is not available to any of that."""
    from datetime import date

    from openproj.index import build_index
    from openproj.model import load_repo
    from openproj.render import render_static

    entities, config, unreadable = load_repo(SEED)
    render_static(build_index(entities, config, date(2026, 8, 17), unreadable=unreadable), tmp_path)

    written = sorted(tmp_path.glob("*.html"))
    assert written, "nothing was exported"
    for page in written:
        assert f'content="{CSP}"' in page.read_text(encoding="utf-8"), page.name


def test_frame_ancestors_is_not_claimed_where_it_does_nothing():
    """A `<meta>` ignores frame-ancestors. A directive that silently does nothing
    is worse than a missing one, because it reads as covered — so it is sent as a
    header and left out of the page."""
    assert "frame-ancestors" not in CSP


def test_the_policy_permits_exactly_what_the_pages_actually_do():
    """Every one of these is a thing a rendered page does, and a policy that
    forbade one would be found by a blank page rather than by a test."""
    assert "img-src 'self' data:" in CSP, "assets are same-origin, pasted images are data:"
    assert "font-src data:" in CSP, "the typeface is inlined as a data: URI"
    assert "style-src 'unsafe-inline'" in CSP, "every stylesheet is an inline block"
    assert "script-src 'unsafe-inline'" in CSP, "every script is an inline block"
    # And the part that is the whole point: nothing may be fetched from anywhere.
    assert CSP.startswith("default-src 'none'")
    assert "http" not in CSP, "a policy naming a host is a policy that permits a host"
