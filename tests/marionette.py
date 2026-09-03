"""Firefox, driven over Marionette, for the questions Chrome answers wrongly.

Chrome is what the rest of this suite drives, and for pixels that is the right
choice — it is what the plan is read in. This exists because one defect was
invisible to it, and would have been invisible to any number of Chrome tests:
`display: none` destroys a scroll frame, and the two engines disagree about what
happens to that frame's scroll offset. Chrome drops it. Firefox SAVES it, keyed
by where the box sits in its parent rather than by the element, and restores it
onto whatever frame is built there next — so the hover card, hidden between two
hovers, opened the second record's shaping document at the first one's offset,
on a page where every Chrome probe came back at the top. jcanton reported it from
Firefox on 2026-09-03, against a commit whose Chrome test was green.

Marionette rather than geckodriver or a WebDriver client, because it is already
there: it is Firefox's own remote protocol, spoken over a TCP socket with
`<length>:<json>` framing, and the whole client is the fifty lines below. A
WebDriver library would be a dependency for one test, and `No npm, no build step,
no CDN` is the neighbouring rule for the other language.

Two things about the sandbox scripts run through this. They are DOM-only: the
pages this drives send a CSP without `unsafe-eval`, so `window.eval` — the usual
way into a page's `const` and `let`, which live in the global lexical scope and
not on `window` — is refused by the page's own policy, correctly. And a page
expando reached deliberately needs `window.wrappedJSObject`, because Xray vision
hides it. Neither is a limitation worth working around here: what these tests ask
about is what the DOM ended up looking like.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

# The browsers this will drive, named rather than searched for, the same way
# `browser.CHROMES` is: a headless run of *something* is not evidence about the
# engine the defect was reported from.
FIREFOXES = (
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    "firefox",
    "firefox-esr",
)


def firefox() -> str:
    found = next((path for name in FIREFOXES if (path := shutil.which(name))), None)
    if found is None:  # pragma: no cover - depends on the machine, not on the code
        pytest.skip("no Firefox on this machine, so nothing here can be said about Gecko")
    return found


def _free_port() -> int:
    """A port nobody is on, asked of the kernel rather than picked.

    2828 is Marionette's default and would be fine for one test on a laptop; CI
    runs eight legs at once on eight machines today and there is no promise it
    stays that way. The window between closing this socket and Firefox binding it
    is a race nobody else on the machine is trying to win.
    """
    with socket.socket() as probing:
        probing.bind(("127.0.0.1", 0))
        return probing.getsockname()[1]


class Firefox:
    """One headless Firefox, one Marionette session, closed on the way out."""

    def __init__(self, binary: str) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="marionette-"))
        port = _free_port()
        # The port through a pref and not a flag: `--marionette` is the only
        # command line switch for this, and it takes no argument.
        (self.profile / "user.js").write_text(
            "\n".join(
                (
                    f'user_pref("marionette.port", {port});',
                    # Nothing may reach the network from a test, and nothing may
                    # ask a question in front of the page being measured.
                    'user_pref("browser.shell.checkDefaultBrowser", false);',
                    'user_pref("app.update.enabled", false);',
                    'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
                    'user_pref("toolkit.telemetry.enabled", false);',
                    'user_pref("browser.startup.homepage_override.mstone", "ignore");',
                )
            )
            + "\n"
        )
        self.process = subprocess.Popen(
            [binary, "--headless", "--marionette", "--profile", str(self.profile), "about:blank"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.socket = self._connect(port)
        self.buffer = b""
        self._next()  # the server's hello packet
        self.n = 0
        self.call("WebDriver:NewSession", {})

    def _connect(self, port: int) -> socket.socket:
        # Twenty seconds, because a cold profile is a first run: Firefox writes
        # one, compiles startup caches and only then listens.
        for _ in range(80):
            if self.process.poll() is not None:  # pragma: no cover - a machine fact
                raise AssertionError(f"Firefox exited with {self.process.returncode}")
            try:
                opened = socket.create_connection(("127.0.0.1", port), timeout=60)
            except OSError:
                time.sleep(0.25)
            else:
                return opened
        raise AssertionError("Firefox started but Marionette never listened")  # pragma: no cover

    # --- the protocol -------------------------------------------------------

    def _next(self) -> object:
        """One `<length>:<json>` packet, reading only as much as it needs."""
        while b":" not in self.buffer:
            self.buffer += self.socket.recv(65536)
        size, _, rest = self.buffer.partition(b":")
        want = int(size)
        while len(rest) < want:
            rest += self.socket.recv(65536)
        self.buffer = rest[want:]
        return json.loads(rest[:want])

    def call(self, command: str, params: dict) -> dict:
        self.n += 1
        packet = json.dumps([0, self.n, command, params]).encode()
        self.socket.sendall(str(len(packet)).encode() + b":" + packet)
        while True:
            answer = self._next()
            # [1, id, error, result] — and an id of somebody else's is an
            # emitted event, which this client has no use for.
            if isinstance(answer, list) and answer[0] == 1 and answer[1] == self.n:
                if answer[2]:
                    raise AssertionError(f"{command}: {json.dumps(answer[2])[:400]}")
                return answer[3]

    # --- what a test asks ---------------------------------------------------

    def go(self, url: str) -> None:
        self.call("WebDriver:Navigate", {"url": url})

    def js(self, script: str):
        """Evaluate an expression in the page and bring the value back."""
        return self.call(
            "WebDriver:ExecuteScript",
            {"script": f"return ({script});", "args": [], "sandbox": "default"},
        )["value"]

    def close(self) -> None:
        try:
            self.socket.close()
        finally:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - a machine fact
                self.process.kill()
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self) -> Firefox:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def driving(page: str, where: Path) -> Firefox:
    """The page written to a file and opened, with the load waited for.

    `file://` and not a server, like every other browser test here: what is being
    driven is the document this repository renders, and a server in front of it is
    one more thing that can be the reason a test failed.
    """
    where.write_text(page)
    browser = Firefox(firefox())
    try:
        browser.go(where.as_uri())
        # `WebDriver:Navigate` returns on load, and the shell's own scripts run
        # then. The card's payload and the table's fit are the same tick.
        browser.js("document.readyState")
        return browser
    except BaseException:  # pragma: no cover - only on a failed launch
        browser.close()
        raise
