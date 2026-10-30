"""Egress-side echo fixture for the conformance probes: the "upstream" that
shows what actually crossed the proxy boundary.

Every method is answered with JSON — the method, the request headers as they
arrived, and how many body bytes were received — so identity and broker probes
can see what the proxy rewrote and the enforcement probes can see what was
forwarded. It also RECORDS: every accepted connection and every request it
starts reading (method, path, declared body size, bytes received so far,
complete or not), served at `GET /_seen` (which is excluded from the record).
A denied request that was nevertheless forwarded therefore shows up as a
request entry, complete or not; a connection that carried nothing shows up as
a connection — things a plain per-request counter would miss (ADR 0012).

Listens on :8080 (plain) and, when `/tls/cert.pem` + `/tls/key.pem` are
mounted (conformance only; `tjor conformance` generates them), on :8443 over
TLS advertising ALPN `http/1.1` — the proxy mirrors the upstream's protocol to
the client, so without that the client would negotiate none.

Stdlib only; runs in the conformance image.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TLS_DIR = os.environ.get("TJOR_ECHO_TLS_DIR", "/tls")   # overridable for a local harness
TLS_CERT = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY = os.path.join(TLS_DIR, "key.pem")
CHUNK = 65536

_LOCK = threading.Lock()
_NEXT_CONN = [0]
_CONNECTIONS: dict[int, dict] = {}   # id -> {"observer": bool, "requests": int}
_BY_FD: dict[int, int] = {}          # accepted socket fd -> connection id (set at accept time)
_REQUESTS: list[dict] = []           # every non-/_seen request, in arrival order


def _record_accept(sock) -> None:
    """Record a connection in the server's accept loop, BEFORE a handler
    thread exists for it, so a connection the proxy opened is in the record
    as soon as the kernel handed it over — not once a thread got scheduled."""
    with _LOCK:
        _NEXT_CONN[0] += 1
        _CONNECTIONS[_NEXT_CONN[0]] = {"observer": False, "requests": 0}
        _BY_FD[sock.fileno()] = _NEXT_CONN[0]


def _snapshot() -> dict:
    with _LOCK:
        conns = sum(1 for c in _CONNECTIONS.values() if c["requests"] or not c["observer"])
        return {"connections": conns, "requests": [dict(r) for r in _REQUESTS]}


class Echo(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30   # a stalled peer releases its handler thread

    # --- recording --------------------------------------------------------
    def setup(self):  # noqa: D102 — socketserver hook
        super().setup()
        with _LOCK:
            self.conn_id = _BY_FD.pop(self.request.fileno(), None)
            if self.conn_id is None:            # not seen at accept (should not happen)
                _NEXT_CONN[0] += 1
                self.conn_id = _NEXT_CONN[0]
                _CONNECTIONS[self.conn_id] = {"observer": False, "requests": 0}
        # TLS connections are wrapped without a handshake (so a failing
        # handshake never blocks the accept loop); handshake here, per thread.
        if hasattr(self.request, "do_handshake"):
            try:
                self.request.do_handshake()
            except OSError:            # ssl.SSLError is an OSError
                self.close_connection = True
                self._handshake_failed = True
                return
        self._handshake_failed = False

    def handle(self):  # noqa: D102 — skip connections whose TLS handshake failed
        if getattr(self, "_handshake_failed", False):
            return
        super().handle()

    def handle_one_request(self):  # noqa: D102 — every method, body read and recorded
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = self.request_version = self.command = ""
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            if self.path == "/_seen":
                with _LOCK:
                    _CONNECTIONS[self.conn_id]["observer"] = True
                self._read_body(None)
                self._reply(_snapshot())
                return
            entry = {
                "method": self.command,
                "path": self.path,
                "declared": self._declared(),
                "received": 0,
                "complete": False,
            }
            with _LOCK:
                _REQUESTS.append(entry)
                _CONNECTIONS[self.conn_id]["requests"] += 1
            self._read_body(entry)
            with _LOCK:
                entry["complete"] = True
            if self.path.split("?", 1)[0] == "/redirect":      # the method-gate redirect probe
                self._status(307, [("Location", "/items")])
                return
            if self.path.split("?", 1)[0] == "/switch":        # a 101 whatever the request carried
                self._status(101, [("Upgrade", "websocket"), ("Connection", "Upgrade")])
                self.close_connection = True
                return
            self._reply({
                "method": self.command,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body_len": entry["received"],
            })
        except OSError:                # ConnectionError and TimeoutError are OSErrors
            self.close_connection = True

    # --- body framing -----------------------------------------------------
    def _declared(self) -> int | None:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return None
        try:
            return int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return 0

    def _bump(self, entry: dict | None, n: int) -> None:
        if entry is not None and n:
            with _LOCK:
                entry["received"] += n

    def _read_exact(self, entry: dict | None, remaining: int) -> None:
        while remaining > 0:
            chunk = self.rfile.read(min(CHUNK, remaining))
            if not chunk:
                raise ConnectionError("body cut short")
            remaining -= len(chunk)
            self._bump(entry, len(chunk))

    def _read_body(self, entry: dict | None) -> None:
        declared = self._declared()
        if declared is not None:
            self._read_exact(entry, declared)
            return
        while True:  # chunked; strict: a fixture meant to notice mis-framing
            line = self.rfile.readline(1024)
            if not line.endswith(b"\r\n"):
                raise ConnectionError("chunked body cut short or unterminated chunk-size line")
            token = line[:-2].split(b";", 1)[0].strip()
            if not re.fullmatch(rb"[0-9A-Fa-f]{1,8}", token):     # hex digits only: no sign, no 0x, bounded
                raise ConnectionError(f"malformed chunk size {token[:16]!r}")
            size = int(token, 16)
            if size == 0:
                while True:                                           # trailers end with an empty line, never EOF
                    trailer = self.rfile.readline(1024)
                    if not trailer.endswith(b"\r\n"):
                        raise ConnectionError("chunked body cut short before the final CRLF")
                    if trailer == b"\r\n":
                        return
            self._read_exact(entry, size)
            if self.rfile.read(2) != b"\r\n":
                raise ConnectionError("chunk data not followed by CRLF")

    # --- reply ------------------------------------------------------------
    def _status(self, code: int, headers: list[tuple[str, str]]) -> None:
        self.send_response(code)
        for name, value in headers:
            self.send_header(name, value)
        if code != 101:
            self.send_header("content-length", "0")
        self.end_headers()
        self.wfile.flush()

    def _reply(self, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, *args):  # quiet
        pass


class PlainEcho(ThreadingHTTPServer):
    def get_request(self):  # noqa: D102 — record in the accept loop
        sock, addr = super().get_request()
        _record_accept(sock)
        return sock, addr


class TlsEcho(ThreadingHTTPServer):
    """Wraps each accepted socket without handshaking; Echo.setup handshakes."""

    def __init__(self, address, handler, ctx: ssl.SSLContext):
        super().__init__(address, handler)
        self.ctx = ctx

    def get_request(self):  # noqa: D102 — record in the accept loop, never leak the raw socket
        sock, addr = super().get_request()
        _record_accept(sock)
        try:
            return self.ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr
        except OSError:
            sock.close()
            raise


def main() -> None:
    bind = os.environ.get("TJOR_ECHO_BIND", "")   # all interfaces: the fixture is reachable only on the egress network
    plain = PlainEcho((bind, 8080), Echo)
    plain.daemon_threads = True
    if os.path.isfile(TLS_CERT) and os.path.isfile(TLS_KEY):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        ctx.set_alpn_protocols(["http/1.1"])
        tls = TlsEcho((bind, 8443), Echo, ctx)
        tls.daemon_threads = True
        threading.Thread(target=tls.serve_forever, daemon=True).start()
    plain.serve_forever()


if __name__ == "__main__":
    main()
