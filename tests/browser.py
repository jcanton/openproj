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


def screenshot(browser: str, html: Path, png: Path) -> bytes:
    """One page, one window, one PNG. 700px wide so the table has more columns
    than room and can actually be scrolled sideways."""
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", "--window-size=700,600",
         f"--screenshot={png}", "--virtual-time-budget=2500", str(html)],
        capture_output=True, check=True,
    )
    return png.read_bytes()


def measured_in(
    browser: str, page: str, where: Path, width: int, script: str, height: int = 900
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
    """
    where.write_text(page.replace(
        "</body>",
        "<script>setTimeout(() => { document.body.dataset.report = JSON.stringify("
        f"(() => {{ {script} }})()); }}, 1200);</script></body>",
    ))
    done = subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={width},{height}",
         "--virtual-time-budget=2500", "--dump-dom", str(where)],
        capture_output=True, text=True, check=True,
    )
    found = re.search(r'data-report="([^"]*)"', done.stdout)
    assert found, "the page reported nothing: it did not lay out, or the script threw"
    return json.loads(unescape(found.group(1)))
