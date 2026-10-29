"""tjor conformance probes (GitHub #13).

Runs INSIDE the cage on the agent network, against the parity fixture
policy (python/tests/fixtures/parity-policy.toml). Each probe attempts
something the cage must prevent; a probe passes when the attempt fails the
way the spec demands. Exit code 0 = boundary holds.

Stdlib only. Plain-HTTP requests exercise the proxy's request-stage policy
without needing the CA; a raw CONNECT exercises the pre-TLS stage; the
host-identity and transport probes open TLS tunnels with the session CA
(TJOR_PROXY_CA) toward the echo fixture's TLS listener.

Every denial a probe provokes is declared with expect_denial(); the runner
(`tjor conformance`) requires the session's denial log to hold each declared
(host, rule) pair exactly as many times, so a closed connection is shown to
have been a denial by the right rule (ADR 0012).
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import sys
import time

PROXY_IP = os.environ.get("TJOR_PROXY_IP", "")
DNS_IP = os.environ.get("TJOR_DNS_IP", "")
PROXY_PORT = int(os.environ.get("TJOR_PROXY_PORT", "8080"))
SESSION_ID = os.environ.get("TJOR_SESSION_ID", "")
BROKER_TOKEN = os.environ.get("TJOR_TEST_BROKER_TOKEN", "")
PROXY_CA = os.environ.get("TJOR_PROXY_CA", "/etc/tjor/ca/ca.pem")

ECHO = "echo-noinject.tjor-test"      # the recording echo fixture (plain :8080, TLS :8443)
MIB = 1024 * 1024

RESULTS: list[tuple[bool, str, str]] = []
EXPECTED_DENIALS: list[tuple[str, str]] = []


def expect_denial(host: str, rule: str) -> None:
    """Declare a denial this probe provoked; the runner checks the log by count."""
    EXPECTED_DENIALS.append((host, rule))


class Closed(Exception):
    """The proxy closed the connection without answering: the headers-stage
    kill for an unbounded or already-streaming denied body."""


_CLOSED_ERRORS = (http.client.RemoteDisconnected, ConnectionResetError,
                  BrokenPipeError, ConnectionAbortedError)


def probe(name: str):
    def deco(fn):
        def run():
            try:
                fn()
                RESULTS.append((True, name, ""))
            except AssertionError as exc:
                RESULTS.append((False, name, str(exc)))
            except Exception as exc:  # unexpected error = failed probe, loudly
                RESULTS.append((False, name, f"unexpected {type(exc).__name__}: {exc}"))
        return run
    return deco


def _chunks(body: bytes, size: int = 65536):
    for i in range(0, len(body), size):
        yield body[i:i + size]


def via_proxy(url: str, timeout: float = 15.0, method: str = "GET", headers: dict | None = None,
              body: bytes | None = None, chunked: bool = False,
              conn: http.client.HTTPConnection | None = None) -> http.client.HTTPResponse:
    """Absolute-form request through the proxy. Returns the response; raises
    Closed when the proxy closed the connection without answering. A chunked
    body is sent as Transfer-Encoding: chunked (no Content-Length). Pass `conn`
    to reuse a connection across requests."""
    conn = conn or http.client.HTTPConnection(PROXY_IP, PROXY_PORT, timeout=timeout)
    hdrs = {"Host": url.split("/")[2]}
    hdrs.update(headers or {})
    try:
        conn.request(method, url, body=_chunks(body) if chunked else body, headers=hdrs)
        return conn.getresponse()
    except _CLOSED_ERRORS as exc:
        raise Closed(repr(exc)) from exc


def tunnel(host: str, port: int, tls: bool = False, timeout: float = 15.0,
           alpn: list[str] | None = None) -> http.client.HTTPConnection:
    """An http.client connection tunnelled through the proxy with CONNECT;
    with tls=True the connection inside the tunnel is TLS, verified against the
    session CA, SNI = host."""
    if tls:
        ctx = ssl.create_default_context(cafile=PROXY_CA)
        if alpn:
            ctx.set_alpn_protocols(alpn)
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            PROXY_IP, PROXY_PORT, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(PROXY_IP, PROXY_PORT, timeout=timeout)
    conn.set_tunnel(host, port)
    return conn


def in_tunnel(conn: http.client.HTTPConnection, method: str, path: str,
              headers: dict | None = None, body: bytes | None = None) -> http.client.HTTPResponse:
    """A request inside a tunnel. http.client sets Host from the tunnel target
    unless the caller supplies one (the host-identity probes do)."""
    try:
        conn.request(method, path, body=body, headers=dict(headers or {}))
        return conn.getresponse()
    except _CLOSED_ERRORS as exc:
        raise Closed(repr(exc)) from exc


def seen() -> dict:
    """The echo fixture's record of connections and requests (its own /_seen
    requests excluded). Polls until two consecutive snapshots agree, so a
    request the fixture is still recording in a handler thread is in the
    record before it is compared."""
    last = None
    for _ in range(40):
        resp = via_proxy(f"http://{ECHO}:8080/_seen")
        assert resp.status == 200, f"/_seen unreachable: {resp.status}"
        snap = json.loads(resp.read())
        if snap == last:
            return snap
        last = snap
        time.sleep(0.1)
    return last


def nothing_forwarded(before: dict, what: str) -> None:
    """After a denied attempt: send a sentinel allowed request and assert the
    record grew by exactly that sentinel. The sentinel orders the proxy's side
    (a forwarded request leaves the proxy before its answer to the client,
    which precedes the sentinel); on the fixture's side a connection is
    recorded in the accept loop before any thread runs and `seen()` waits for
    a settled snapshot, so the fixture's own threads cannot reorder the
    record past the comparison."""
    sentinel = f"/sentinel-{time.time_ns()}"
    resp = via_proxy(f"http://{ECHO}:8080{sentinel}")
    assert resp.status == 200, f"{what}: sentinel request failed ({resp.status})"
    resp.read()
    after = seen()
    new = after["requests"][len(before["requests"]):]
    assert len(new) == 1 and new[0]["path"] == sentinel and new[0]["complete"], (
        f"{what}: the upstream saw more than the sentinel: {new}")
    assert after["connections"] - before["connections"] <= 1, (
        f"{what}: the upstream accepted a connection the sentinel does not account for "
        f"({before['connections']} -> {after['connections']})")


def positive_control(path: str, body: bytes, chunked: bool, what: str) -> None:
    """The same request shape, allowed: it must arrive complete, so a closed
    connection on the denied attempt cannot be an unrelated failure."""
    resp = via_proxy(f"http://{ECHO}:8080{path}", method="POST", body=body, chunked=chunked)
    assert resp.status == 200, f"{what}: positive control was not served ({resp.status})"
    got = json.loads(resp.read())["body_len"]
    assert got == len(body), f"{what}: positive control arrived with {got} of {len(body)} bytes"


def is_policy_deny(resp) -> bool:
    return resp is not None and resp.status == 403 and resp.getheader("x-tjor-policy") == "deny"


def echo_headers(host: str, extra: dict | None = None) -> dict:
    """GET the egress-side echo fixture through the proxy; returns the header
    set that actually arrived upstream. Retries briefly (fixture boot)."""
    last = None
    for _ in range(5):
        try:
            conn = http.client.HTTPConnection(PROXY_IP, PROXY_PORT, timeout=15)
            headers = {"Host": f"{host}:8080"}
            headers.update(extra or {})
            conn.request("GET", f"http://{host}:8080/", headers=headers)
            resp = conn.getresponse()
            if resp.status == 200:
                return json.loads(resp.read())["headers"]
            last = f"status {resp.status}"
        except OSError as exc:
            last = repr(exc)
        time.sleep(1)
    raise AssertionError(f"echo fixture unreachable through the proxy: {last}")


@probe("direct egress bypassing the proxy is impossible")
def p_direct_egress():
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=5).close()
        raise AssertionError("direct TCP connection to 1.1.1.1:443 SUCCEEDED — internal network is not internal")
    except (TimeoutError, OSError):
        pass


@probe("DNS for an unlisted zone fails closed (NXDOMAIN, no forwarding)")
def p_dns_unlisted():
    try:
        socket.getaddrinfo("exfil-payload.tjor-canary-unlisted.example", 443)
        raise AssertionError("unlisted zone RESOLVED — DNS sidecar is forwarding beyond policy")
    except socket.gaierror:
        pass


@probe("blocked host is denied at the proxy")
def p_blocked_host():
    resp = via_proxy("http://blocked.test/secret")
    assert is_policy_deny(resp), f"expected policy deny, got {resp.status if resp else 'no response'}"
    expect_denial("blocked.test", "host-block")


@probe("path carve-out on a blocked host passes policy")
def p_carveout_passes():
    resp = via_proxy("http://blocked.test/docs/guide")
    assert not is_policy_deny(resp), "carve-out path was denied — carve-outs broken"
    # .test is unresolvable upstream, so pass-through shows up as a gateway error, never a policy deny.


@probe("encoding cannot widen an allow carve-out")
def p_encoded_allow_widening():
    resp = via_proxy("http://blocked.test/%64ocs/guide")
    assert is_policy_deny(resp), "encoded path slipped through a carve-out (allow widened by encoding)"
    expect_denial("blocked.test", "host-block")


@probe("encoding cannot evade a path block")
def p_encoded_block_bypass():
    resp = via_proxy("http://api.vendor.test/v1/%74elemetry/send")
    assert is_policy_deny(resp), "encoded path evaded a block rule"
    expect_denial("api.vendor.test", "path-block")


@probe("dot-segments cannot escape a carve-out")
def p_dot_segment_escape():
    resp = via_proxy("http://blocked.test/docs/../secret")
    assert is_policy_deny(resp), "dot-segment path escaped the carve-out"
    expect_denial("blocked.test", "host-block")


@probe("CONNECT to a non-allowed host is denied before TLS")
def p_connect_denied():
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=10) as sock:
        sock.sendall(b"CONNECT unknown.test:443 HTTP/1.1\r\nHost: unknown.test:443\r\n\r\n")
        line = sock.makefile("rb").readline().decode("latin1")
    assert " 403" in line, f"CONNECT not denied: {line.strip()!r}"
    expect_denial("unknown.test", "default-deny")


@probe("strict-allow default-deny holds for unknown hosts")
def p_default_deny():
    resp = via_proxy("http://notlisted.test/")
    assert is_policy_deny(resp), "unknown host was not denied in strict-allow mode"
    expect_denial("notlisted.test", "default-deny")


@probe("no sidecar admin surface is reachable from the agent network")
def p_admin_surfaces():
    targets = [(PROXY_IP, p) for p in (8081, 8082, 8888, 9090, 9999)]
    targets += [(DNS_IP, p) for p in (8080, 8181, 9153, 853)]
    open_ports = []
    for host, port in targets:
        if not host:
            continue
        try:
            socket.create_connection((host, port), timeout=2).close()
            open_ports.append(f"{host}:{port}")
        except OSError:
            pass
    assert not open_ports, f"admin/management ports reachable from agent network: {open_ports}"


@probe("raw TCP passthrough is disabled (tunnels cannot smuggle non-HTTP bytes)")
def p_rawtcp_disabled():
    # Open a legitimate CONNECT tunnel to the echo fixture, then speak
    # something that is neither TLS nor HTTP. With mitmproxy's rawtcp
    # default (true!) these bytes would be relayed verbatim and the echo
    # HTTP server would answer with its distinctive BaseHTTP 400. The cage
    # must never relay them (rawtcp=false).
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=10) as sock:
        sock.sendall(
            b"CONNECT echo-noinject.tjor-test:8080 HTTP/1.1\r\n"
            b"Host: echo-noinject.tjor-test:8080\r\n\r\n"
        )
        reader = sock.makefile("rb")
        status = reader.readline()
        assert b" 200" in status, f"CONNECT to allowed host failed: {status!r}"
        while reader.readline() not in (b"\r\n", b""):
            pass
        # Not TLS (first byte != 0x16), not HTTP (non-ASCII method), but
        # newline-terminated so a relayed-to HTTP server WOULD answer.
        sock.sendall(b"\x00\x01\x02\x03 not-tls-not-http\r\n\r\n")
        sock.settimeout(6)
        received = b""
        try:
            while chunk := sock.recv(4096):
                received += chunk
        except (TimeoutError, OSError):
            pass
    assert b"BaseHTTP" not in received, (
        f"raw bytes were RELAYED to the upstream (rawtcp passthrough active): {received[:80]!r}"
    )


@probe("identity: forged x-agent-* headers are stripped before egress")
def p_zid_forged_stripped():
    arrived = echo_headers(
        "echo-noinject.tjor-test",
        {"x-agent-session-id": "intruder-session", "x-agent-custom": "smuggled"},
    )
    leaked = [k for k in arrived if k.startswith("x-agent-")]
    assert not leaked, f"forged/unknown identity headers reached upstream: {leaked}"


@probe("identity: matching self-identification passes through")
def p_zid_matching_passes():
    arrived = echo_headers("echo-noinject.tjor-test", {"x-agent-session-id": SESSION_ID})
    assert arrived.get("x-agent-session-id") == SESSION_ID, "legitimate identity header did not survive"


@probe("identity: injected exactly on configured hosts")
def p_zid_injected_on_configured():
    arrived = echo_headers("echo-inject.tjor-test")
    assert arrived.get("x-agent-session-id") == SESSION_ID, "identity not injected on inject_hosts target"
    assert arrived.get("x-agent-harness"), "identity set incomplete on inject_hosts target"


@probe("identity: no leakage toward unconfigured hosts")
def p_zid_no_leak():
    arrived = echo_headers("echo-noinject.tjor-test")
    leaked = [k for k in arrived if k.startswith("x-agent-")]
    assert not leaked, f"identity leaked to a non-inject host: {leaked}"


@probe("broker: real credential injected toward the destination host")
def p_broker_injected():
    if not BROKER_TOKEN:
        raise AssertionError("TJOR_TEST_BROKER_TOKEN not set")
    arrived = echo_headers("echo-broker.tjor-test")
    assert arrived.get("authorization") == f"token {BROKER_TOKEN}", \
        f"expected injected token, got {arrived.get('authorization')!r}"


@probe("broker: the agent's placeholder is overwritten, never forwarded")
def p_broker_overwrites_placeholder():
    # git's placeholder: Basic x-access-token:tjor-broker-placeholder. The proxy
    # re-issues the credential in the CLIENT's scheme (#65): GitHub's git
    # endpoint accepts only Basic x-access-token:<token>, so upstream must see
    # Basic with the real token — and the placeholder nowhere, decoded either.
    import base64
    arrived = echo_headers(
        "echo-broker.tjor-test",
        {"authorization": "Basic eC1hY2Nlc3MtdG9rZW46dGpvci1icm9rZXItcGxhY2Vob2xkZXI="},
    )
    auth = arrived.get("authorization", "")
    expected = "Basic " + base64.b64encode(f"x-access-token:{BROKER_TOKEN}".encode()).decode()
    assert auth == expected, f"placeholder was not overwritten in git's scheme, got {auth!r}"
    decoded = base64.b64decode(auth.split(" ", 1)[1]).decode(errors="replace")
    assert "placeholder" not in auth and "placeholder" not in decoded, "placeholder leaked upstream"


@probe("broker: gh's token-scheme placeholder is overwritten in its own scheme")
def p_broker_overwrites_gh_placeholder():
    # gh sends `Authorization: token <placeholder>` (#65); api.github.com
    # accepts the token scheme, so it is kept and only the secret is swapped.
    arrived = echo_headers(
        "echo-broker.tjor-test",
        {"authorization": "token tjor-broker-placeholder"},
    )
    assert arrived.get("authorization") == f"token {BROKER_TOKEN}", \
        f"gh placeholder was not overwritten, got {arrived.get('authorization')!r}"


@probe("broker: credential does not leak to a non-destination host")
def p_broker_no_leak():
    arrived = echo_headers("echo-noinject.tjor-test", {"authorization": "Bearer agent-own"})
    assert BROKER_TOKEN not in str(arrived), "broker token leaked to a non-destination host"


# ---------------------------------------------------------------------------
# Headers-stage enforcement, one host identity, HTTP/1.1 only (ADR 0012).

@probe("enforcement: a large denied body is never forwarded")
def p_enf_large_denied():
    big = b"x" * (2 * MIB)
    positive_control("/upload-large", big, False, "large body")
    before = seen()
    try:
        resp = via_proxy(f"http://{ECHO}:8080/phone-home/big", method="POST", body=big)
        raise AssertionError(f"a denied 2 MiB upload was answered {resp.status} instead of closed at the headers stage")
    except Closed:
        pass
    expect_denial(ECHO, "path-block")
    nothing_forwarded(before, "large denied body")


@probe("enforcement: a chunked denied body is never forwarded")
def p_enf_chunked_denied():
    big = b"c" * (2 * MIB)
    positive_control("/upload-chunked", big, True, "chunked body")
    before = seen()
    host = "echo-inject.tjor-test"   # a distinct host, so the log check cannot be satisfied by another probe
    try:
        resp = via_proxy(f"http://{host}:8080/phone-home/chunked", method="POST", body=big, chunked=True)
        raise AssertionError(f"a denied chunked upload was answered {resp.status} instead of closed at the headers stage")
    except Closed:
        pass
    expect_denial(host, "path-block")
    nothing_forwarded(before, "chunked denied body")


@probe("enforcement: a bounded denied request gets the 403 and the connection survives")
def p_enf_bounded_denied():
    before = seen()
    conn = http.client.HTTPConnection(PROXY_IP, PROXY_PORT, timeout=15)
    resp = via_proxy(f"http://{ECHO}:8080/phone-home/small", method="POST", body=b"y" * 10240, conn=conn)
    assert resp.status == 403 and resp.getheader("x-tjor-rule") == "path-block", (
        f"bounded denied POST: expected 403 path-block, got {resp.status} {resp.getheader('x-tjor-rule')!r}")
    resp.read()
    expect_denial(ECHO, "path-block")
    follow = via_proxy(f"http://{ECHO}:8080/after-denial", conn=conn)   # same connection
    assert follow.status == 200, f"the connection did not survive the 403: {follow.status}"
    follow.read()
    after = seen()
    new = after["requests"][len(before["requests"]):]
    assert [r["path"] for r in new] == ["/after-denial"], f"the upstream saw: {new}"


@probe("enforcement: a denied request with Expect gets no 100 Continue")
def p_enf_expect():
    # With a body to wait for, the connection is closed at once: the proxy can
    # only answer after the body, and a client that honours Expect sends the
    # body only after a 100 — so a 403 could never arrive promptly, and a
    # client that never sends its body must not be left hanging.
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=15) as sock:
        sock.sendall(
            f"POST http://{ECHO}:8080/phone-home/expect HTTP/1.1\r\nHost: {ECHO}:8080\r\n"
            f"Content-Length: 10\r\nExpect: 100-continue\r\n\r\n".encode())
        sock.settimeout(10)
        try:
            data = sock.recv(4096)
        except OSError:
            data = b""                       # a reset is a close too
    assert data == b"", f"expected the connection closed at once (no 100, no body wait), got {data[:60]!r}"
    expect_denial(ECHO, "path-block")
    # With no body to wait for, the 403 is the answer, and no 100 precedes it.
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=15) as sock:
        sock.sendall(
            f"POST http://{ECHO}:8080/phone-home/expect-empty HTTP/1.1\r\nHost: {ECHO}:8080\r\n"
            f"Content-Length: 0\r\nExpect: 100-continue\r\n\r\n".encode())
        data = b""
        while b"\r\n\r\n" not in data:
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            data += chunk
    assert data.startswith(b"HTTP/1.1 403") and b" 100 " not in data, f"expected a 403 and no 100, got {data[:60]!r}"
    expect_denial(ECHO, "path-block")


@probe("enforcement: an interrupted denied upload is still logged")
def p_enf_interrupted():
    before = seen()
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=15) as sock:
        sock.sendall(
            f"POST http://{ECHO}:8080/phone-home/interrupted HTTP/1.1\r\nHost: {ECHO}:8080\r\n"
            f"Content-Length: {2 * MIB}\r\n\r\n".encode())
        try:
            sock.sendall(b"z" * 65536)   # part of the body, then hang up
        except OSError:
            pass                         # the proxy may already have closed
    expect_denial(ECHO, "path-block")    # denied at the headers stage, logged whether or not a 403 was read
    nothing_forwarded(before, "interrupted denied upload")


@probe("broker: a streamed request still receives the real credential")
def p_broker_streamed():
    if not BROKER_TOKEN:
        raise AssertionError("TJOR_TEST_BROKER_TOKEN not set")
    big = b"b" * (2 * MIB)
    resp = via_proxy("http://echo-broker.tjor-test:8080/upload", method="POST", body=big,
                     headers={"authorization": "token tjor-broker-placeholder",
                              "x-agent-session-id": "intruder-session"})
    assert resp.status == 200, f"streamed broker upload not served: {resp.status}"
    data = json.loads(resp.read())
    assert data["body_len"] == len(big), f"streamed body arrived with {data['body_len']} bytes"
    assert data["headers"].get("authorization") == f"token {BROKER_TOKEN}", (
        f"streamed request carried {data['headers'].get('authorization')!r}, not the real credential")
    leaked = [k for k in data["headers"] if k.startswith("x-agent-")]
    assert not leaked, f"forged identity header reached upstream on a streamed request: {leaked}"


@probe("host identity: a Host header inside a tunnel cannot steer the verdict")
def p_host_lie_in_tunnel():
    conn = tunnel(ECHO, 8080)
    resp = in_tunnel(conn, "GET", "/x", headers={"Host": "readonly.test:8080"})
    assert resp.status == 403 and resp.getheader("x-tjor-rule") == "fail-closed:host-mismatch", (
        f"a Host lie inside a tunnel was judged under the lie: {resp.status} {resp.getheader('x-tjor-rule')!r}")
    expect_denial(ECHO, "fail-closed:host-mismatch")


@probe("host identity: an absolute-form Host header cannot steer the verdict")
def p_host_lie_absolute():
    resp = via_proxy(f"http://{ECHO}:8080/x", headers={"Host": "readonly.test:8080"})
    assert resp.status == 403 and resp.getheader("x-tjor-rule") == "fail-closed:host-mismatch", (
        f"an absolute-form Host lie was judged under the lie: {resp.status} {resp.getheader('x-tjor-rule')!r}")
    expect_denial(ECHO, "fail-closed:host-mismatch")


@probe("host identity: a TLS tunnel is judged on its server name")
def p_host_tls_tunnel():
    conn = tunnel("readonly.test", 8443, tls=True)
    resp = in_tunnel(conn, "GET", "/items")
    assert resp.status == 200, f"TLS tunnel to the fixture failed: {resp.status}"
    assert json.loads(resp.read())["method"] == "GET"
    lie = tunnel("readonly.test", 8443, tls=True)
    resp = in_tunnel(lie, "GET", "/items", headers={"Host": f"{ECHO}:8443"})
    assert resp.status == 403 and resp.getheader("x-tjor-rule") == "fail-closed:host-mismatch", (
        f"a Host lie inside a TLS tunnel was judged under the lie: {resp.status} {resp.getheader('x-tjor-rule')!r}")
    expect_denial("readonly.test", "fail-closed:host-mismatch")


@probe("transport: HTTP/2 is not negotiated")
def p_transport_http11_only():
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=15) as sock:
        sock.sendall(b"CONNECT readonly.test:8443 HTTP/1.1\r\nHost: readonly.test:8443\r\n\r\n")
        reader = sock.makefile("rb")
        status = reader.readline()
        assert b" 200" in status, f"CONNECT to the TLS fixture failed: {status!r}"
        while reader.readline() not in (b"\r\n", b""):
            pass
        ctx = ssl.create_default_context(cafile=PROXY_CA)
        ctx.set_alpn_protocols(["h2", "http/1.1"])   # h2 first: the proxy must not take it
        with ctx.wrap_socket(sock, server_hostname="readonly.test") as tls:
            negotiated = tls.selected_alpn_protocol()
            assert negotiated == "http/1.1", f"the proxy negotiated {negotiated!r}, not http/1.1"
            tls.sendall(b"GET /items HTTP/1.1\r\nHost: readonly.test:8443\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                data += chunk
    assert data.startswith(b"HTTP/1.1 200"), f"the request inside the http/1.1 tunnel was not served: {data[:60]!r}"


@probe("transport: the conformance trust anchor does not disable upstream verification")
def p_transport_trust_anchor_scoped():
    # Positive control first: the anchor trusts the fixture certificate for
    # readonly.test, so that tunnel is served — a down fixture cannot pass as
    # a refusal below.
    conn = tunnel("readonly.test", 8443, tls=True)
    resp = in_tunnel(conn, "GET", "/items")
    assert resp.status == 200, f"positive control: TLS tunnel to readonly.test not served ({resp.status})"
    resp.read()
    # echo-inject.tjor-test is deliberately NOT in the certificate's SAN: the
    # proxy's upstream verification must refuse it, which mitmproxy reports to
    # the client as its own 502 naming the verification failure.
    before = seen()
    conn = tunnel("echo-inject.tjor-test", 8443, tls=True)
    resp = in_tunnel(conn, "GET", "/items")
    body = resp.read()
    assert resp.status == 502 and b"Certificate verify failed" in body, (
        f"expected the proxy's own verification failure (502), got {resp.status} {body[:80]!r}")
    after = seen()
    reached = [r for r in after["requests"][len(before["requests"]):] if r["path"] == "/items"]
    assert not reached, f"the upstream served a request the proxy should have refused to verify: {reached}"


@probe("host identity: an absolute-form target inside a tunnel cannot steer the verdict")
def p_host_authority_in_tunnel():
    # The request line names another host while Host matches the tunnel; the
    # retained authority would be re-emitted upstream as absolute-form.
    conn = tunnel(ECHO, 8080)
    resp = in_tunnel(conn, "GET", "http://readonly.test:8080/x", headers={"Host": f"{ECHO}:8080"})
    assert resp.status == 403 and resp.getheader("x-tjor-rule") == "fail-closed:host-mismatch", (
        f"an absolute-form target inside a tunnel was not refused: {resp.status} {resp.getheader('x-tjor-rule')!r}")
    expect_denial(ECHO, "fail-closed:host-mismatch")


# Multi-cluster kube isolation (#57): cross-cluster token isolation — cluster
# A's token never reaching cluster B's origin — is asserted authoritatively by
# the addon unit suite (python/tests/test_addon_guards.py::TestKubeMultiInjection),
# which drives the real per-origin injection path with a two-cluster broker.
# It is NOT a live probe here for the same reason the #41 rebinding case is a
# unit test, not a conformance probe: this topology runs a single stub broker
# with TJOR_IP_GUARD=off, so it cannot stand up two private-endpoint clusters
# to exercise the isolation end-to-end. A live two-cluster fixture is tracked
# as future work if the boundary results matrix (#38) wants an e2e datapoint.


def main() -> int:
    if not PROXY_IP or not DNS_IP:
        print("conformance: TJOR_PROXY_IP / TJOR_DNS_IP not set", file=sys.stderr)
        return 2
    if not SESSION_ID:
        print("conformance: TJOR_SESSION_ID not set", file=sys.stderr)
        return 2
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("p_")]:
        fn()
    failed = 0
    for ok, name, detail in RESULTS:
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
        failed += 0 if ok else 1
    for host, rule in EXPECTED_DENIALS:
        print(f"expect-denial\t{host}\t{rule}")
    print(f"\nconformance: {len(RESULTS) - failed}/{len(RESULTS)} probes passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
