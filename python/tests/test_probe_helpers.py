"""The conformance probes' helpers, driven against local peers without the
cage (ADR 0012): a probe that must see a *closed* connection must not be
satisfied by a proxy that merely stalls."""

import importlib.util
import os
import socket
import struct
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load_probes():
    os.environ.setdefault("TJOR_PROXY_IP", "127.0.0.1")
    os.environ.setdefault("TJOR_DNS_IP", "127.0.0.1")
    spec = importlib.util.spec_from_file_location("tjor_probes", REPO / "images" / "conformance" / "probes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Peer:
    """A listening peer that, per accepted connection, closes, resets, or stays open."""

    def __init__(self, behaviour: str):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.behaviour = behaviour
        self.stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        self.srv.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, _ = self.srv.accept()
            except TimeoutError:
                continue
            with conn:
                conn.recv(4096)
                if self.behaviour == "reset":
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                elif self.behaviour == "stall":
                    self.stop.wait(5)
                # "close": fall out of the with-block

    def close(self):
        self.stop.set()
        self.srv.close()


def _client(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(b"POST /x HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\nExpect: 100-continue\r\n\r\n")
    return sock


@pytest.mark.parametrize("behaviour", ["close", "reset"])
def test_closed_at_once_accepts_eof_and_reset(behaviour):
    probes = load_probes()
    peer = _Peer(behaviour)
    try:
        with _client(peer.port) as sock:
            probes.closed_at_once(sock, timeout=5)      # no exception: the peer closed
    finally:
        peer.close()


def test_closed_at_once_rejects_a_peer_that_stays_open():
    # The original defect: the proxy stopped reading but left the socket open.
    probes = load_probes()
    peer = _Peer("stall")
    try:
        with _client(peer.port) as sock:
            t0 = time.monotonic()
            with pytest.raises(AssertionError, match="stalled"):
                probes.closed_at_once(sock, timeout=0.5)
            assert time.monotonic() - t0 < 3
    finally:
        peer.close()
