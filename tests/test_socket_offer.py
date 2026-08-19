"""Who is offered a socket, and who is not.

Found from jcanton's console on the deployed service: signed out, a detail page
tried `wss://…/api/coedit/<id>` five times and was refused five times. The server
was right — a socket is for somebody who may write — and the page was wrong to
knock. Reads here are public, so *most* page loads are readers, and every one of
them got five red lines in a console for a page working exactly as designed.
That is how a real error comes to be ignored.

The question the page must ask is what the WRITE path would answer, not what the
corner says. `/api/me` answers `viewer` — the session cookie and nothing else —
and under `--auth dev` there is no cookie while `writer` invents a login and
permits the write. So a gate on `/api/me` would refuse the socket in exactly the
mode this tool is tried in, with every test still green, because the tests sign a
cookie. That is the test at the bottom of this file.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import ANN, CLIENT_ID, CLIENT_SECRET, SECRET, SEED

from openproj.auth import sign_session
from openproj.web import SESSION_COOKIE, create_app

ONE = "task-c00001"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


def page_for(repo: Path, *, signed_in: bool, auth: str = "github") -> str:
    app = create_app(
        repo,
        auth=auth,
        secret=SECRET,
        org="C2SM",
        # A real sign-in is what `auth="github"` means, and the app refuses to
        # start without the pair — for the reason it says: nobody could ever
        # write. Nothing here completes one; the session cookie is signed
        # directly, which is what a completed sign-in leaves behind.
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    with TestClient(app) as client:
        if signed_in:
            client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        answer = client.get(f"/detail/{ONE}")
    assert answer.status_code == 200
    return answer.text


def test_a_reader_is_not_offered_a_socket(repo: Path):
    """Signed out, on a page anybody may read. No socket code, and no library to
    open one with — the Yjs bundle was being shipped to readers so they could be
    refused five times."""
    page = page_for(repo, signed_in=False)

    assert "/api/coedit/" not in page, "a reader is handed the socket's own URL"
    assert "new WebSocket" not in page, "a reader is handed something that opens one"
    # And not the library either. Named by something only the bundle contains, so
    # this is a claim about the 300 KB rather than about the word `yjs` appearing
    # in a comment.
    assert "encodeStateVector" not in page, "a reader is handed the CRDT library"


def test_a_member_is(repo: Path):
    """The other half, which is the one that matters: this is a gate, and a gate
    that is on for everybody is not a fix, it is a removal."""
    page = page_for(repo, signed_in=True)

    assert "/api/coedit/" in page
    assert "new WebSocket" in page
    assert "encodeStateVector" in page, "the socket is offered without the library it needs"


def test_a_reader_can_still_read_the_whole_record(repo: Path):
    """What a reader loses is a socket, not a page. Reads are public here and the
    document is the record — a fix that took the record away with the socket
    would be a worse defect than the console lines it was cleaning up."""
    page = page_for(repo, signed_in=False)

    assert "<article" in page
    assert ONE in page


def test_a_dev_run_offers_the_socket_it_would_accept(repo: Path):
    """The reason this asks `writer` and not `/api/me`.

    Under `--auth dev` — every `openproj demo`, and `serve --auth dev` — there is
    no session, so `viewer` answers nobody and the corner draws "Sign in", while
    `writer` invents `dev_login` and the write goes through. A page gated on the
    corner would carry no socket here, and co-editing would be broken for
    everybody trying the tool with the suite green.
    """
    page = page_for(repo, signed_in=False, auth="dev")

    assert "/api/coedit/" in page, "the demo, where writing works, was given no socket"
