"""tjor mitmproxy addon: enforce the egress policy on every request.

The policy decision itself lives in tjor_policy (the single shared matcher);
this file only wires it to mitmproxy. The verdict helpers are importable
without mitmproxy installed — the parity and guard test suites use them as
call sites.

Fail-closed, everywhere: an invalid policy denies everything, and ANY
unhandled exception in verdict computation yields a deny — an addon
exception must never let mitmproxy pass a request through unfiltered.

Resolved-address guard: an allowed hostname says nothing about where it
resolves. A DNS-rebound or hijacked allowed domain pointing at a private,
loopback, or link-local address would let the (dual-homed) proxy be used as
a bridge into the internal network or VM metadata (SSRF). The guard denies
any host that resolves to a non-global address. An UNRESOLVABLE host passes
the guard: no connection can result, so nothing can flow — while denying it
would break policy-level tests against non-existent domains. Residual
TOCTOU (re-resolution at connect time) is documented in the change's
design.md. Disable only for intranet use via TJOR_IP_GUARD=off.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tjor_identity
import tjor_policy

POLICY_PATH = os.environ.get("TJOR_POLICY_FILE", "/policy/policy.toml")

IDENTITY = tjor_identity.load_identity(os.environ)
INJECT_HOSTS = tjor_identity.parse_inject_hosts(os.environ.get("TJOR_INJECT_HOSTS", ""))
if not IDENTITY.valid:
    print(
        "tjor: session identity missing/invalid — stripping ALL x-agent-* headers: "
        + "; ".join(IDENTITY.errors),
        file=sys.stderr,
        flush=True,
    )

_cache: dict = {"mtime": None, "policy": None}


def _current_policy() -> tjor_policy.Policy:
    try:
        mtime = os.stat(POLICY_PATH).st_mtime_ns
    except OSError:
        mtime = None
    if _cache["policy"] is None or _cache["mtime"] != mtime:
        _cache["policy"] = tjor_policy.load_policy(POLICY_PATH)
        _cache["mtime"] = mtime
        if not _cache["policy"].valid:
            print(
                "tjor: POLICY INVALID — failing closed, all egress denied: "
                + "; ".join(_cache["policy"].errors),
                file=sys.stderr,
                flush=True,
            )
    return _cache["policy"]


def decide(url: str) -> tjor_policy.Verdict:
    """Parity call site: identical inputs must yield identical verdicts to
    the module API and the CLI."""
    return tjor_policy.evaluate(_current_policy(), url)


def decide_connect(host: str) -> tjor_policy.Verdict:
    """Host-level parity call site for CONNECT-time decisions."""
    return tjor_policy.evaluate_connect(_current_policy(), host)


# --------------------------------------------------- resolved-address guard

_IP_GUARD = os.environ.get("TJOR_IP_GUARD", "on").lower() not in ("off", "0", "false")
_IP_TTL_SECONDS = 30.0
_IP_CACHE_MAX = 1024
_ip_cache: dict[str, tuple[float, bool, str]] = {}


def _system_resolver(host: str) -> set[str]:
    return {info[4][0] for info in socket.getaddrinfo(host, None)}


_resolver = _system_resolver  # injectable for tests


def resolved_addresses_ok(host: str) -> tuple[bool, str]:
    """True unless the host resolves to any non-global address."""
    host = tjor_policy._canon_host(host)
    now = time.monotonic()
    hit = _ip_cache.get(host)
    if hit and now - hit[0] < _IP_TTL_SECONDS:
        return hit[1], hit[2]

    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            addresses = _resolver(host)
        except OSError:
            return True, "unresolvable"

    ok, why = True, ""
    for raw in addresses:
        try:
            addr = ipaddress.ip_address(raw.split("%")[0])
        except ValueError:
            ok, why = False, f"unparseable address {raw!r}"
            break
        if not addr.is_global:
            ok, why = False, f"non-global address {addr}"
            break

    if len(_ip_cache) >= _IP_CACHE_MAX:
        _ip_cache.clear()
    _ip_cache[host] = (now, ok, why)
    return ok, why


# ------------------------------------------------------- verdict computation

def _fail_closed(compute) -> tjor_policy.Verdict:
    try:
        return compute()
    except Exception as exc:  # noqa: BLE001 — the whole point: never pass through
        print(f"tjor: addon error — failing closed: {exc!r}", file=sys.stderr, flush=True)
        return tjor_policy.Verdict(False, "fail-closed:addon-error")


def connect_verdict(host: str) -> tjor_policy.Verdict:
    def compute():
        verdict = decide_connect(host)
        if verdict.allowed and _IP_GUARD:
            ok, why = resolved_addresses_ok(host)
            if not ok:
                return tjor_policy.Verdict(False, f"ip-guard:{why}")
        return verdict

    return _fail_closed(compute)


def request_verdict(url: str, host: str) -> tjor_policy.Verdict:
    def compute():
        verdict = decide(url)
        if verdict.allowed and _IP_GUARD:
            ok, why = resolved_addresses_ok(host)
            if not ok:
                return tjor_policy.Verdict(False, f"ip-guard:{why}")
        return verdict

    return _fail_closed(compute)


# ---------------------------------------------------------- session identity

_strip_log_count = 0


def _log_stripped(host: str, stripped: dict) -> None:
    global _strip_log_count
    _strip_log_count += 1
    if _strip_log_count <= 20 or _strip_log_count % 100 == 0:
        print(
            f"tjor: stripped forged/unknown identity headers toward {host} "
            f"(#{_strip_log_count}): {sorted(stripped)}",
            file=sys.stderr,
            flush=True,
        )


def identity_outcome(existing: dict[str, str], host: str) -> tuple[dict, dict]:
    """Testable seam: final and stripped x-agent-* sets for one request.
    Fail-closed: any error means nothing is trusted."""
    try:
        inject = tjor_identity.should_inject(INJECT_HOSTS, host)
        return tjor_identity.transform(IDENTITY, existing, inject)
    except Exception as exc:  # noqa: BLE001
        print(f"tjor: identity error — stripping all x-agent-*: {exc!r}", file=sys.stderr, flush=True)
        return {}, dict(existing)


def _apply_identity(flow) -> None:
    existing = {
        name.lower(): value
        for name, value in flow.request.headers.items()
        if name.lower().startswith("x-agent-")
    }
    final, stripped = identity_outcome(existing, flow.request.host)
    for name in [n for n in flow.request.headers if n.lower().startswith("x-agent-")]:
        del flow.request.headers[name]
    for name, value in final.items():
        flow.request.headers[name] = value
    if stripped:
        _log_stripped(flow.request.host, stripped)


# ------------------------------------------------------------ mitmproxy glue

class TjorPolicy:
    def http_connect(self, flow) -> None:
        from mitmproxy import http

        verdict = connect_verdict(flow.request.host)
        if not verdict.allowed:
            flow.response = http.Response.make(
                403,
                f"tjor egress policy: DENY CONNECT ({verdict.rule})\n".encode(),
                {"x-tjor-policy": "deny", "x-tjor-rule": verdict.rule},
            )

    def request(self, flow) -> None:
        from mitmproxy import http

        verdict = request_verdict(flow.request.pretty_url, flow.request.host)
        if verdict.allowed:
            _apply_identity(flow)
        if not verdict.allowed:
            flow.response = http.Response.make(
                403,
                (
                    f"tjor egress policy: DENY ({verdict.rule}"
                    + (f": {verdict.pattern}" if verdict.pattern else "")
                    + ")\n"
                ).encode(),
                {
                    "content-type": "text/plain",
                    "x-tjor-policy": "deny",
                    "x-tjor-rule": verdict.rule,
                },
            )


addons = [TjorPolicy()]
