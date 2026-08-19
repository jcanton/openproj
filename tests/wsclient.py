"""A WebSocket client made of wsproto and a socket.

The suite needs none of this for the room itself: `TestClient` speaks the ASGI
side directly, which is the right level for every question about convergence,
attribution and the commit. This exists for the one question that is not — does a
real browser open this socket, against a real server, under this application's
Content-Security-Policy — where the answer has to come from Chrome and Chrome
cannot be two people at once. So the second participant is this, signed in as
somebody else, and what the browser draws in its presence list is the evidence.

`wsproto` and not a client library, because `wsproto` is already a dependency:
uvicorn refuses every upgrade with a 403 without a websocket implementation
installed, and this is the one that is pure Python.
"""

from __future__ import annotations

import json
import socket

from wsproto import WSConnection
from wsproto.connection import ConnectionType
from wsproto.events import AcceptConnection, CloseConnection, Ping, Request, TextMessage
from wsproto.frame_protocol import CloseReason


class Client:
    """One connection. Blocking, because a test reads one message at a time."""

    def __init__(
        self, host: str, port: int, path: str, cookie: str = "", receive_buffer: int = 0
    ) -> None:
        self._socket = socket.socket()
        if receive_buffer:
            # A window small enough that a member who stops reading stops
            # accepting writes within a few frames instead of within a few
            # megabytes. This is how the one test that needs an unresponsive
            # member makes one: not by pretending, but by having a real client
            # on a real socket genuinely stop draining. The kernel is free to
            # round this up and does — `SO_RCVBUF` is a request — so the test
            # measures where the writes actually stop rather than assuming.
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_buffer)
        self._socket.settimeout(10)
        self._socket.connect((host, port))
        self._connection = WSConnection(ConnectionType.CLIENT)
        self._waiting: list[str] = []
        headers = [(b"cookie", cookie.encode())] if cookie else []
        self._out(
            self._connection.send(
                Request(host=f"{host}:{port}", target=path, extra_headers=headers)
            )
        )
        while True:
            event = self._next()
            if isinstance(event, AcceptConnection):
                return
            if isinstance(event, CloseConnection):
                raise AssertionError(f"the handshake was refused: {event.code}")

    def _out(self, data: bytes) -> None:
        self._socket.sendall(data)

    def _next(self):
        """The next protocol event, reading more bytes only when there are none."""
        while True:
            for event in self._connection.events():
                if isinstance(event, Ping):
                    self._out(self._connection.send(event.response()))
                    continue
                return event
            data = self._socket.recv(65536)
            if not data:
                raise AssertionError("the server closed the connection")
            self._connection.receive_data(data)

    def send_json(self, payload: dict) -> None:
        self._out(self._connection.send(TextMessage(data=json.dumps(payload))))

    def receive_json(self) -> dict:
        # A text message can arrive in pieces; `message_finished` is the only
        # thing that says the string is whole, and a JSON decode of half a frame
        # is a failure that reads as a protocol bug.
        while True:
            event = self._next()
            if isinstance(event, CloseConnection):
                raise AssertionError(f"the server closed: {event.code} {event.reason}")
            if isinstance(event, TextMessage):
                self._waiting.append(event.data)
                if event.message_finished:
                    whole = "".join(self._waiting)
                    self._waiting = []
                    return json.loads(whole)

    def close(self) -> None:
        try:
            self._out(self._connection.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE)))
        except Exception:  # pragma: no cover - the socket may already be gone
            pass
        self._socket.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
