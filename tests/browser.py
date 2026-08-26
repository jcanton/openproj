"""Chrome, driven for the questions a stylesheet cannot answer.

A resolved value is a promise about pixels that a stylesheet cannot keep on its
own. The frozen column's edge is the proof: it resolved to exactly the value
every test asserted, on exactly the element they asserted it on, and Chrome
painted nothing at all — an outset `box-shadow` on a cell in a collapsed table is
not a dimmer line, it is no line. So the claims that are about *where a box ends
up* or *whether anything was drawn* are asked here, of the browser, instead.

These helpers were `_chrome`, `_screenshot` and `_measured_in` inside
`test_table.py`, where the table's own pixel tests could reach them and nobody
else could. The graph, the timeline and the table now all size one box to the
window, which is a question about geometry on three pages at six window heights,
and a second copy of a headless runner is a second thing to keep in step with the
first.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from contextlib import contextmanager
from html import unescape
from pathlib import Path

import pytest

# The browsers this will drive if one of them is installed. Named rather than
# searched for, because a headless run of *something* is not evidence about the
# browser the plan is read in.
CHROMES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
)


def chrome() -> str:
    found = next((path for name in CHROMES if (path := shutil.which(name))), None)
    if found is None:  # pragma: no cover - depends on the machine, not on the code
        pytest.skip("no Chrome on this machine, so nothing here can be said about pixels")
    return found


def screenshot(
    browser: str, html: Path, png: Path, width: int = 700, height: int = 600
) -> bytes:
    """One page, one window, one PNG. 700px wide by default so the table has more
    columns than room and can actually be scrolled sideways.

    The size is a parameter for the same reason `measured_in`'s is: the editing
    surface is `position: fixed; inset: 0`, so what it draws is a function of the
    window and 700x600 is a window nothing in it is designed for.

    5000ms of virtual time and not the 2500 it was. The table settles in three
    measured passes now — fit the columns, then tighten status, priority and the
    two date columns against what the fit gave them — and at 2500 the byte
    comparison in `test_the_frozen_edge_is_a_pixel_a_browser_draws` caught one
    page mid-settle on CI while passing here. A pixel test that races is a pixel
    test that fails for a reason nobody can reproduce; virtual time costs
    wall-clock only while there is something left to run.
    """
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={width},{height}",
         f"--screenshot={png}", "--virtual-time-budget=5000", str(html)],
        capture_output=True, check=True,
    )
    return png.read_bytes()


# A page object in a PDF's object table. `/Type /Page` and not `/Type /Pages`,
# which is the tree node above them and would add one to every count.
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?![sA-Za-z])")


def printed(browser: str, html: Path, pdf: Path) -> int:
    """How many sheets this page prints on.

    The one question about paper in the suite, and the only medium that can
    answer it: `break-after: page` resolving in a stylesheet says nothing about
    where Chrome puts the cut, which is the same gap the frozen column's
    unpainted edge fell through. `--no-pdf-header-footer` because the default
    stamps a URL and a date on every sheet — which changes no count, but a
    printed deck with a `file:///var/folders/...` across the bottom of every
    slide is not the artefact this is about.
    """
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", "--virtual-time-budget=2500", str(html)],
        capture_output=True, check=True,
    )
    return len(_PDF_PAGE.findall(pdf.read_bytes()))


# When the script is run, measured from load. The table's fit and the shell's
# measurement both run again when the inlined typeface lands, and an answer taken
# before that is an answer about the fallback's metrics.
SETTLE = 1200


def measured_in(
    browser: str,
    page: str,
    where: Path,
    width: int,
    script: str,
    height: int = 900,
    flags: tuple[str, ...] = (),
    query: str = "",
    patience: int = 1300,
) -> dict:
    """Lay the page out in Chrome at this size, run `script` over the result and
    bring back what it found.

    The DOM is the only channel out of a headless run, so the script writes its
    answer onto the body and `--dump-dom` carries it back. After a delay, because
    the table's fit and the shell's measurement both run again when the inlined
    typeface lands, and an answer taken before that is an answer about the
    fallback's metrics.

    `height` is a parameter and not the 900 it used to be fixed at: the box each
    view sizes to the window is right or wrong *per window*, and one window is
    the one thing that cannot show it.

    `patience` is how long the script itself is given after that, and it exists
    because the failure it prevents is silent. A script that answers from a
    continuation — anything waiting on a delay the page owns, like the hover
    card's — writes `data-report` a second time, and if the virtual clock runs
    out first the harness reads the placeholder and the test reports nothing at
    all. That looks exactly like a card that never came up. Two waits of 700ms
    were over the old fixed budget by eighty milliseconds, which is not a number
    anybody would guess from the failure.

    `flags` is how a test asks about a reader who is not the default one.
    `--force-prefers-reduced-motion` is the only user in the suite: the media
    query it flips cannot be reached from the page, and a test that asserted the
    block was *in* the stylesheet would be the same test that missed the frozen
    column's edge. Passed through rather than baked in, because a run under a
    forced setting has to be comparable to a run without it — the assertion is
    the difference between the two.

    `query` is appended to the `file://` URL, so a test can ask what the page
    does when it is opened at `?both`. A deep link is read off `location.search`
    and there is no other way to give it one: a script cannot change the search
    without navigating, and navigating loses the script.

    The script is awaited, so it may be written `async` and may wait for
    something the page does on its own clock — a debounce, a frame, a fetch. A
    plain value is unaffected, because awaiting a non-promise is that value. That
    waiting is what `patience` bounds, and it is why the editor's questions pass
    numbers in the thousands: a script that outlives the clock reports nothing at
    all, which surfaces as "the page reported nothing" rather than as a wrong
    answer — so a question about a 300ms debounce asked three times over has to
    raise `patience` rather than shorten the debounce it is asking about.
    """
    where.write_text(page.replace(
        "</body>",
        "<script>setTimeout(async () => { document.body.dataset.report = JSON.stringify("
        f"await (async () => {{ {script} }})()); }}, {SETTLE});</script></body>",
    ))
    done = subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={width},{height}",
         # A URL and not a path, because a path is all Chrome will take it for:
         # `…/deep.html?both=` handed over as a filename is a file that does not
         # exist, and what loads instead is a blank page that reports nothing.
         *flags, f"--virtual-time-budget={SETTLE + patience}", "--dump-dom",
         where.as_uri() + query],
        capture_output=True, text=True, check=True,
    )
    found = re.search(r'data-report="([^"]*)"', done.stdout)
    assert found, "the page reported nothing: it did not lay out, or the script threw"
    return json.loads(unescape(found.group(1)))


@contextmanager
def _devtools(browser: str, url: str, profile: Path, flags: tuple[str, ...] = ()):
    """One headless Chrome on one page, and the two things a caller needs from
    it: `call(method, params)` for any DevTools method, and the list the console
    accumulates into.

    `flags` is how a test asks about a machine that is not this one, and it is
    the same knob `measured_in` has for `--force-prefers-reduced-motion`. The
    user here is the hover wash: headless Chrome's pointer depends on the host —
    a Mac reports `(hover: hover)` and CI's Linux reports `(hover: none)` — so a
    test that took the default asserted one thing here and its opposite there.
    `Emulation.setEmulatedMedia` cannot fix it, and that was measured rather than
    assumed: it carries `prefers-*` and the media TYPE and ignores `hover`
    outright, so forcing `hover: none` through it changed nothing at all.
    `--blink-settings` is what the engine actually reads.

    Split out of `in_a_live_page` when a second question needed the same plumbing
    — a *trusted* press, which is `Input.dispatchMouseEvent` and therefore a
    DevTools method like any other. Copying forty lines of Popen, port discovery
    and message pumping to send one extra method is how two harnesses come to
    disagree about which one is telling the truth, and this file has already
    written down what a harness that lies costs.
    """
    import time
    from urllib.parse import quote

    import httpx
    from wsclient import Client

    profile.mkdir(parents=True, exist_ok=True)
    chrome_process = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--no-first-run", *flags,
         "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # Chrome writes the port it actually took into the profile, which is the
        # only way to ask for an ephemeral one and still find it.
        where = profile / "DevToolsActivePort"
        for _ in range(400):
            if where.exists():
                break
            time.sleep(0.05)
        assert where.exists(), "Chrome never wrote DevToolsActivePort"
        port = int(where.read_text().splitlines()[0])

        target = httpx.put(f"http://127.0.0.1:{port}/json/new?{quote(url, safe='')}").json()
        page_path = target["webSocketDebuggerUrl"].split(f"127.0.0.1:{port}", 1)[1]

        said: list[str] = []
        with Client("127.0.0.1", port, page_path) as devtools:
            asked = 0

            def call(method: str, params: dict | None = None) -> dict:
                nonlocal asked
                asked += 1
                mine = asked
                devtools.send_json({"id": mine, "method": method, "params": params or {}})
                while True:
                    message = devtools.receive_json()
                    if message.get("method") == "Log.entryAdded":
                        said.append(message["params"]["entry"]["text"])
                    if message.get("method") == "Runtime.consoleAPICalled":
                        said.extend(str(one.get("value")) for one in message["params"]["args"])
                    if message.get("id") == mine:
                        return message

            call("Log.enable")
            call("Runtime.enable")
            yield call, said
    finally:
        chrome_process.terminate()
        chrome_process.wait(timeout=30)


def _evaluated(call, expression: str, patient: bool = False):
    """One expression, awaited, with whatever it threw reported as itself.

    A `Runtime.evaluate` that throws answers 200 with an `exceptionDetails` and
    no value, so a caller that reads `result.value` sees `None` and reports the
    page as having answered nothing — which is the same shape as a page that did
    not lay out, and points at the harness instead of at the line that threw.

    **`patient` is the difference between the two callers, and it is not a knob.**
    `in_a_live_page` asks the SAME expression over and over until something
    truthy comes back, so a throw there is an ordinary step of the walk: the
    element is not drawn yet, or a click has just begun a navigation and the
    context this ran in no longer exists. Reporting those would fail a test on
    its first turn of a loop written to have many. `pressed_in` asks once, after
    the press, and a throw there is the answer.
    """
    answer = call("Runtime.evaluate",
                  {"expression": expression, "returnByValue": True, "awaitPromise": True})
    thrown = answer.get("result", {}).get("exceptionDetails")
    if thrown and patient:
        return None
    assert not thrown, f"the page threw: {thrown.get('exception', {}).get('description', thrown)}"
    return answer.get("result", {}).get("result", {}).get("value")


def pressed_in(
    browser: str, url: str, profile: Path, *, setup: str, at: str, then: str,
    settle: float = 1.5,
) -> tuple[object, list[str]]:
    """Put the page in a state, press a point on it the way a mouse does, and ask
    what happened.

    **`Input.dispatchMouseEvent` and not `element.click()`, and that distinction
    is the whole reason this exists.** A synthetic event carries `isTrusted:
    false` and runs no default action, so it moves no focus, blurs nothing, and
    is *dispatched* rather than synthesised — which means it cannot ask the one
    question that matters here: whether the browser decides to synthesise a
    `click` at all. It does not when the element that took the `mousedown` is
    detached before the `mouseup`, and a page that rebuilds a container on blur
    detaches it in between. Every cheaper harness — `drive.js`, which has no
    focus model and no bubbling, and `measured_in`, whose script can only
    dispatch — passes with that defect in place, because in both of them the
    press lands by construction.

    `setup` puts the page where the press has to find it and is expected to
    scroll the target into view; `at` is an expression answering `[x, y]` in
    viewport coordinates, asked after `setup` so it sees the layout the press
    will actually meet; `then` is the question, asked after `settle` seconds of
    real time so a write path has run to its end.
    """
    import time

    with _devtools(browser, url, profile) as (call, said):
        # The page has to have drawn before anything can be pressed on it, and
        # `--dump-dom`'s network-idle wait is not available here (see
        # `in_a_live_page`). A short fixed wait is honest about what it is.
        time.sleep(2)
        _evaluated(call, setup)
        where = _evaluated(call, at)
        assert isinstance(where, list) and len(where) == 2, (
            f"`at` must answer [x, y] in viewport coordinates; it answered {where!r}"
        )
        x, y = where
        for kind in ("mousePressed", "mouseReleased"):
            call("Input.dispatchMouseEvent", {
                "type": kind, "x": x, "y": y, "button": "left", "clickCount": 1,
                "buttons": 1 if kind == "mousePressed" else 0,
            })
            time.sleep(0.1)
        time.sleep(settle)
        return _evaluated(call, then), said


def in_a_live_page(
    browser: str, url: str, expression: str, profile: Path, seconds: float = 20
) -> tuple[object, list[str]]:
    """Open a URL in Chrome, then ask it a question once the page has settled.

    `--dump-dom` cannot answer this one, and the way it fails is worth writing
    down: it waits for the network to go idle, and a page holding a WebSocket
    open never does. Chrome sat on the co-editing page until the test killed it
    at three minutes — with the socket working perfectly, which is the sort of
    green-looking red this file exists to avoid.

    So this drives DevTools instead, over the same kind of socket the page under
    test uses. That also buys the thing `--dump-dom` structurally cannot give: a
    question asked *after* the page has settled, and asked again until it
    answers, rather than one asked at load and answered by whatever had happened
    by then.

    Returns (the expression's value, every console message the page produced).
    The console is half the evidence: a connection a policy refuses is a console
    line naming the directive, and nothing else on these pages produces one.
    """
    import time

    with _devtools(browser, url, profile) as (call, said):
        value = None
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = _evaluated(call, expression, patient=True)
            if value:
                break
            time.sleep(0.25)
        return value, said
