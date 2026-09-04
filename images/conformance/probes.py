"""tjor conformance probes (GitHub #13).

Runs INSIDE the cage on the agent network, against the parity fixture
policy (python/tests/fixtures/parity-policy.toml). Each probe attempts
something the cage must prevent; a probe passes when the attempt fails the
way the spec demands. Exit code 0 = boundary holds.

Stdlib only. Plain-HTTP requests exercise the proxy's request-stage policy
without needing the CA; a raw CONNECT exercises the pre-TLS stage.
"""

from __future__ import annotations

import http.client
import os
import socket
import sys

PROXY_IP = os.environ.get("TJOR_PROXY_IP", "")
DNS_IP = os.environ.get("TJOR_DNS_IP", "")
PROXY_PORT = int(os.environ.get("TJOR_PROXY_PORT", "8080"))

RESULTS: list[tuple[bool, str, str]] = []


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


def via_proxy(url: str, timeout: float = 15.0) -> http.client.HTTPResponse | None:
    """Absolute-form GET through the proxy. Returns the response, or None if
    the proxy let the request through but the (fake) upstream failed —
    callers distinguish policy denial from pass-through."""
    conn = http.client.HTTPConnection(PROXY_IP, PROXY_PORT, timeout=timeout)
    conn.request("GET", url, headers={"Host": url.split("/")[2]})
    return conn.getresponse()


def is_policy_deny(resp) -> bool:
    return resp is not None and resp.status == 403 and resp.getheader("x-tjor-policy") == "deny"


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


@probe("path carve-out on a blocked host passes policy")
def p_carveout_passes():
    resp = via_proxy("http://blocked.test/docs/guide")
    assert not is_policy_deny(resp), "carve-out path was denied — carve-outs broken"
    # .test is unresolvable upstream, so pass-through shows up as a gateway error, never a policy deny.


@probe("encoding cannot widen an allow carve-out")
def p_encoded_allow_widening():
    resp = via_proxy("http://blocked.test/%64ocs/guide")
    assert is_policy_deny(resp), "encoded path slipped through a carve-out (allow widened by encoding)"


@probe("encoding cannot evade a path block")
def p_encoded_block_bypass():
    resp = via_proxy("http://api.vendor.test/v1/%74elemetry/send")
    assert is_policy_deny(resp), "encoded path evaded a block rule"


@probe("dot-segments cannot escape a carve-out")
def p_dot_segment_escape():
    resp = via_proxy("http://blocked.test/docs/../secret")
    assert is_policy_deny(resp), "dot-segment path escaped the carve-out"


@probe("CONNECT to a non-allowed host is denied before TLS")
def p_connect_denied():
    with socket.create_connection((PROXY_IP, PROXY_PORT), timeout=10) as sock:
        sock.sendall(b"CONNECT unknown.test:443 HTTP/1.1\r\nHost: unknown.test:443\r\n\r\n")
        line = sock.makefile("rb").readline().decode("latin1")
    assert " 403" in line, f"CONNECT not denied: {line.strip()!r}"


@probe("strict-allow default-deny holds for unknown hosts")
def p_default_deny():
    resp = via_proxy("http://notlisted.test/")
    assert is_policy_deny(resp), "unknown host was not denied in strict-allow mode"


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


def main() -> int:
    if not PROXY_IP or not DNS_IP:
        print("conformance: TJOR_PROXY_IP / TJOR_DNS_IP not set", file=sys.stderr)
        return 2
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("p_")]:
        fn()
    failed = 0
    for ok, name, detail in RESULTS:
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
        failed += 0 if ok else 1
    print(f"\nconformance: {len(RESULTS) - failed}/{len(RESULTS)} probes passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
