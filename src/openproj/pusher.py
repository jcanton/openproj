"""One thread that lands the plan on its remote.

One, and a thread rather than an asyncio task, on two grounds that are both
about Cloud Run. `Store.sync()` holds a conversation with GitHub — ~0.9-1.5s of
server-side time per push, measured — and a coroutine holding one would hold
the event loop that answers every page. And CPU is allocated only while a
request is in flight, so a timer cannot be relied on to fire at all; this
thread does no timing of its own except to back off, and is otherwise driven
entirely by the poke a commit makes (docs/deferred-push.md, "Why not batch on
a timer").

The thread owns every conversation with the remote. `sync()` works on a fresh
`pygit2.Repository` handle rather than the store's shared one, so the writer
and the pusher never touch one pygit2 object from two threads — the file's own
pattern, kept because eight writers once lost 87.5% of their commits to shared
state. Nothing here takes `Store._writing`; the one place the recovery needs it
is inside `sync()` itself, for the swap, and this thread must not already hold
it when that happens.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .store import Store, SyncOutcome

_LOG = logging.getLogger(__name__)

_UNREACHABLE = SyncOutcome(landed=None, remapped={}, parked=[], state="unreachable")


class Pusher:
    """Waits on the store's poke, lands the backlog, and says what it did.

    `deliver` is called with every outcome that is not "idle", on THIS thread —
    a caller that lives on an event loop hands the hop across in the callable
    (`loop.call_soon_threadsafe`), because the loop is the caller's to know
    about and this class runs the same under a server as under a test that has
    no loop at all.
    """

    def __init__(
        self,
        store: Store,
        deliver: Callable[[SyncOutcome], None] | None = None,
        backoff: float = 1.0,
        ceiling: float = 60.0,
        grace: float = 5.0,
    ) -> None:
        self._store = store
        self._deliver = deliver
        self._backoff = backoff
        self._ceiling = ceiling
        # How long the shutdown drain may keep trying. Cloud Run allows ~10s
        # between SIGTERM and SIGKILL; this stays under it so the store's own
        # close — releasing the flock — still happens inside the window.
        self._grace = grace
        self._closing = threading.Event()
        # The remote lost a commit this process confirmed it held. Remembered
        # so the shutdown drain can give up at once: a retry cannot land a
        # fork, only a person moving the remote can. While it is set, a poke
        # still runs `sync()` — whose force-push guard fetches on a FRESH
        # repository handle and refuses before any replay — rather than a
        # bare `Store.fetch()`, which runs on the store's shared handle and
        # would put this thread on a pygit2 object the writers are using.
        self._forked = False
        # A daemon, so a process that dies without calling `close` is not held
        # open by this thread waiting on a poke that will never come. The drain
        # on an orderly shutdown does not rely on daemonhood; `close` joins.
        self._thread = threading.Thread(
            target=self._run, name="openproj-pusher", daemon=True
        )

    def start(self) -> None:
        # Poked once at birth: a backlog can predate this process — a laptop
        # reopened on a repository whose last run could not push — and a pusher
        # that waits for the first save would sit on it indefinitely. With no
        # remote, or nothing to send, the pass is a few ref reads.
        self._store.dirty.set()
        self._thread.start()

    def poke(self) -> None:
        """Ask for a pass now — the same poke a commit makes."""
        self._store.dirty.set()

    def close(self) -> None:
        """Land what is still in the backlog, then stop the thread.

        Called before `Store.close` releases the flock, because the drain still
        writes refs. On Cloud Run this drain is the last copy leaving the
        building: the disk is in memory and dies with the instance.
        """
        self._closing.set()
        self._store.dirty.set()
        if self._thread.ident is None:
            # Never started, so nothing is running and nothing was promised.
            return
        self._thread.join(self._grace + 5.0)
        if self._thread.is_alive():
            _LOG.error("the pusher did not stop inside its grace window")

    def _run(self) -> None:
        wait = self._backoff
        while True:
            self._store.dirty.wait()
            if self._closing.is_set():
                break
            self._store.dirty.clear()
            outcome = self._pass()
            if outcome is None or outcome.state != "unreachable":
                wait = self._backoff
                continue
            # Unreachable: the backlog is intact and worth sending unchanged
            # when the network comes back, so wait — but a fresh commit or the
            # shutdown cuts the wait short, which is what `dirty.wait` buys
            # over `sleep`. The re-poke below is this thread reminding itself:
            # nothing else will, because nothing else knows the pass failed.
            self._store.dirty.wait(timeout=wait)
            wait = min(wait * 2, self._ceiling)
            self._store.dirty.set()
        self._drain()

    def _pass(self) -> SyncOutcome | None:
        """One attempt to land the backlog.

        While the store is forked this still runs `sync()` on a poke: the
        recovery's own guard fetches, sees the remote still missing the
        confirmed commit, and answers "diverged" before anything is replayed
        or rewound — so a pass during a fork is one rejected push and one
        fetch, and un-parks by itself on the pass after a person heals the
        remote. Between pokes the thread simply waits, which is the parking:
        no backoff loop hammers a remote that only a person can fix.
        """
        try:
            outcome = self._store.sync()
        except Exception:
            # This thread is the only thing that ever lands a commit, so it
            # must outlive anything a pass can throw — a credential that
            # expired, a filesystem hiccup, a test's monkeypatch. Logged loudly
            # and treated as the remote being away, which is the arm that
            # keeps the backlog and retries.
            _LOG.exception("the pusher's pass failed; treating the remote as unreachable")
            return _UNREACHABLE
        self._forked = outcome.state == "diverged"
        if outcome.state != "idle" and self._deliver is not None:
            try:
                self._deliver(outcome)
            except Exception:
                # The announcement is visibility, never durability: the refs
                # already say everything this said.
                _LOG.exception("delivering a sync outcome failed")
        return outcome

    def _drain(self) -> None:
        """The shutdown flush: keep trying until idle or the grace runs out."""
        deadline = time.monotonic() + self._grace
        while not self._forked:
            # Forked is excluded outright: holding the exit cannot land a
            # fork — a person moving the remote can, and no person moves one
            # inside a SIGTERM grace window.
            outcome = self._pass()
            if outcome is not None and outcome.state == "idle":
                return
            if outcome is not None and outcome.state == "landed":
                # Stragglers may remain; the next pass answers idle if not.
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        left = self._store.condition()
        if left.unpushed or left.parked:
            _LOG.error(
                "shutting down with %d unpushed and %d parked commits still on this disk",
                left.unpushed,
                left.parked,
            )
