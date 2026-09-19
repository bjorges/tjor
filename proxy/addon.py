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
would break policy-level tests against non-existent domains. Resolution is
time-bounded (#59): a lookup that hangs past _RESOLVE_TIMEOUT fails CLOSED
(denied / connection killed, uncached) so an adversarial agent cannot stall
the event loop with slow DNS — distinct from a fast unresolvable, which still
passes.

Resolve-and-pin (#41): the CONNECT/request-stage verdicts and mitmproxy's
own upstream connect used to be two separate resolutions, so a low-TTL
record flipping between them could point connect() at an address the guard
never saw (a rebinding TOCTOU). The server_connect hook closes it: it
validates (cache-aware) and pins the connection to an address that passed,
so the address connected to is provably the address judged — no second
resolution exists to attack. Exempt hosts (gateway, kube API) and IP
literals stay unpinned. Disable only for intranet use via TJOR_IP_GUARD=off.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import os
import socket
import sys
import time
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tjor_broker
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

# Credential broker (D2): host-scoped Authorization injection. The broker
# config and any key live ONLY in this sidecar (egress side, unreachable
# from the agent network). The agent holds a placeholder; the proxy swaps in
# the real, short-TTL credential toward the destination host(s) only.
BROKER = None       # pat/github-app: one credential, injected as `token <t>`
KUBE_BROKER = None  # kube (#26/#57): per-origin bearer tokens, injected as `Bearer <t>`
# Origin-scoped (#49): entries may carry a port (`host:6443`); a port-less
# entry covers any port (pat/github-app back-compat). The kube source always
# scopes to each cluster's API server's exact origin.
BROKER_HOSTS = tjor_identity.parse_broker_hosts(os.environ.get("TJOR_BROKER_HOSTS", ""))
_broker_config = os.environ.get("TJOR_BROKER_CONFIG", "")
if _broker_config:
    try:
        _bcfg = tjor_broker.load_config(_broker_config)
        if _bcfg.get("source") == "kube":
            # Kubernetes needs the Bearer scheme and a per-cluster token map;
            # this covers both the single- (one entry) and multi-cluster cases.
            KUBE_BROKER = tjor_broker.KubeMultiBroker(_bcfg)
        elif BROKER_HOSTS:
            BROKER = tjor_broker.BrokerState(_bcfg)
    except (OSError, ValueError, tjor_broker.BrokerError) as exc:
        print(f"tjor: broker config invalid — no credential will be injected: {exc}",
              file=sys.stderr, flush=True)

_cache: dict = {"mtime": None, "policy": None}

# LLM gateway (D4): the configured gateway host + its generated master key. Both
# the host and the key live ONLY in this sidecar (egress side); the agent points
# its base_url at the gateway and holds only a PLACEHOLDER key, which the proxy
# overwrites with GATEWAY_KEY toward GATEWAY_HOST only. Empty = gateway disabled.
_gw_host_raw = os.environ.get("TJOR_GATEWAY_HOST", "").strip()
GATEWAY_HOST = tjor_policy._canon_host(_gw_host_raw) if _gw_host_raw else ""
GATEWAY_KEY = os.environ.get("TJOR_GATEWAY_KEY", "")

# Kube broker (#45, #57): the cluster API server host(s), set by the launcher
# only while the kube broker is active (hostnames only — never a credential).
# A private-endpoint control plane (on-prem, private AKS/EKS) legitimately
# resolves to a non-global address; EACH configured cluster host gets the SAME
# scoped SSRF-guard exemption as the gateway host, so `ip_guard` never needs a
# global opt-out. A set now (one entry for a single-cluster session).
KUBE_API_HOSTS = frozenset(
    tjor_policy._canon_host(h)
    for h in tjor_identity.parse_inject_hosts(os.environ.get("TJOR_KUBE_API_HOSTS", ""))
)

DENIAL_LOG = os.environ.get("TJOR_DENIAL_LOG", "")
_denial_log_count = 0
# Per-session cap so a misbehaving agent hammering a denied host cannot grow the
# log unbounded (the sibling identity-forgery logger is likewise bounded).
_DENIAL_LOG_MAX = 1000


def _safe_ascii(s: str, limit: int = 253) -> str:
    """Collapse anything outside printable, non-space ASCII to '?' (bounded).
    For attacker-influenced strings (a destination hostname, a forged header
    name) that land in a log a human may view — the session denial log, or the
    proxy's own stderr via `docker logs` — so no terminal-control byte (ANSI/OSC
    escape, bidi override) ever reaches a terminal through that path."""
    return "".join(c if 0x20 < ord(c) < 0x7F else "?" for c in s)[:limit] or "?"


def _log_denial(host: str, rule: str) -> None:
    """Append a denied egress to the session denial log (#23) so `tjor
    denials` can surface it. Best-effort — never let logging break a request."""
    global _denial_log_count
    if not DENIAL_LOG or _denial_log_count >= _DENIAL_LOG_MAX:
        return
    _denial_log_count += 1
    # `host` is attacker-influenced (the destination the agent tried to reach)
    # and this file is later printed by `tjor denials`; keep the file itself
    # free of terminal-control bytes (`tjor denials` sanitizes again at display,
    # defense in depth).
    safe_host = _safe_ascii(host)
    try:
        with open(DENIAL_LOG, "a") as fh:
            fh.write(f"{safe_host}\t{rule}\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            if _denial_log_count >= _DENIAL_LOG_MAX:
                fh.write("...(denial log capped for this session; further denials not recorded)\n")
    except OSError:
        pass


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
_IP_TTL_SECONDS = 10.0  # trust window per host; bounds pinned-address staleness, not a TOCTOU
_IP_CACHE_MAX = 1024

# Bounded resolution (#59): the guard resolves hostnames on mitmproxy's event
# loop, so a synchronous getaddrinfo that hangs would freeze every flow in the
# session — a lever an adversarial in-cage agent could pull (self-DoS). Run the
# resolver in a small capped worker pool and wait at most _RESOLVE_TIMEOUT, so
# no single lookup blocks the loop longer than that regardless of the upstream
# DNS. The pool is capped, so at most _RESOLVE_WORKERS hang concurrently; further
# lookups time out (fail closed) without spawning a thread. A hung worker leaks
# until the OS resolver gives up — acceptable for the long-running proxy, and
# tests unblock their injected resolver so teardown never waits on one.
_RESOLVE_TIMEOUT = 5.0
_RESOLVE_WORKERS = 8
_resolve_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=_RESOLVE_WORKERS, thread_name_prefix="tjor-resolve")


class _CacheEntry(NamedTuple):
    """One resolved-address-guard cache row. Named (not a bare tuple) so a
    later field can be added without every positional index silently shifting —
    the pin path (#41) reads `.addresses` and a miscounted index would defeat
    the guard rather than error."""
    ts: float                 # time.monotonic() when validated
    ok: bool                  # did every resolved address pass the guard
    why: str                  # denial reason (or "" / exemption tag)
    addresses: frozenset[str] # the validated addresses (empty unless ok)


_ip_cache: dict[str, _CacheEntry] = {}


def _is_ip_literal(host: str) -> bool:
    """True if `host` is a bare IP literal (v4/v6, optional %zone id). Such a
    host IS already the address the guard judges — there is nothing to resolve
    (the guard judges it directly) and nothing to pin (#41)."""
    try:
        ipaddress.ip_address(host.split("%")[0])  # strip any zone id
        return True
    except ValueError:
        return False

# Explicit non-public ranges rather than trusting ipaddress.is_global alone:
# its CGNAT/mapped-address handling varies by Python version, and the guard
# must not depend on which interpreter the proxy base image happens to bundle.
# Enumerated once against the IANA special-purpose address registries
# (iana-ipv4-special-registry, iana-ipv6-special-registry): every range that
# is not globally reachable, plus multicast and reserved space. Transition-
# mechanism ranges that embed an IPv4 address (mapped, NAT64, 6to4, Teredo)
# are handled by unwrapping in _embedded_ipv4, not by listing here — the
# outer prefix is legitimately routable; the embedded address decides.
_DENY_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
        "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128", "::1/128", "64:ff9b:1::/48", "100::/64", "100:0:0:1::/64",
        "2001::/23", "2001:2::/48", "2001:10::/28", "2001:20::/28",
        "2001:db8::/32", "3fff::/20", "5f00::/16", "fc00::/7", "fe80::/10",
        "ff00::/8",
    )
]

# The NAT64 well-known prefix (RFC 6052): the low 32 bits are a translated
# IPv4 address, so it must be unwrapped and judged, not denied wholesale.
_NAT64_NET = ipaddress.ip_network("64:ff9b::/96")
# The deprecated IPv4-compatible prefix (::/96): also embeds an IPv4 address
# in its low 32 bits. Modern kernels no longer route it, but a fix that
# claims to close the transition-embedding CLASS must unwrap it too.
_V4COMPAT_NET = ipaddress.ip_network("::/96")


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """Every IPv4 address embedded in an IPv6 transition-mechanism form.
    An IPv6 route to a translator is an IPv4 reach: judging only the outer
    v6 form lets e.g. 64:ff9b::10.0.0.5 encode a private target straight
    past a v4-only denylist (the NAT64/6to4/Teredo/v4-compatible family of
    SSRF bypasses)."""
    embedded: list[ipaddress.IPv4Address] = []
    if addr.ipv4_mapped is not None:
        embedded.append(addr.ipv4_mapped)
    if addr in _NAT64_NET:
        embedded.append(ipaddress.IPv4Address(int(addr) & 0xFFFF_FFFF))
    if addr in _V4COMPAT_NET and int(addr) & 0xFFFF_FFFF:  # skip ::/:: (all-zero) and ::1 (caught as-is)
        embedded.append(ipaddress.IPv4Address(int(addr) & 0xFFFF_FFFF))
    if addr.sixtofour is not None:  # 2002::/16
        embedded.append(addr.sixtofour)
    if addr.teredo is not None:  # 2001::/32 — (server, client), judge both
        embedded.extend(addr.teredo)
    return embedded


def _address_public(raw: str) -> tuple[bool, str]:
    """Version-independent publicness check for one address literal.
    IPv4-embedding IPv6 forms (mapped, NAT64, 6to4, Teredo) are unwrapped
    and every embedded address judged alongside the literal itself.

    Note (#60): the returned reason names the specific offending address. That
    detail is kept for the OPERATOR (denial log / stderr), but the AGENT-facing
    denial is generalized by `_agent_reason`/`_agent_rule` at the response
    sites, so a guard denial never hands the agent the concrete internal
    address it resolved to."""
    try:
        addr = ipaddress.ip_address(raw.split("%")[0])  # strip any zone id
    except ValueError:
        return False, f"unparseable address {raw!r}"
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped  # a mapped literal IS its IPv4 form; judge only that
    forms: list = [addr]
    if isinstance(addr, ipaddress.IPv6Address):
        forms.extend(_embedded_ipv4(addr))
    for form in forms:
        if any(form in net for net in _DENY_NETS) or not form.is_global:
            detail = f" (embeds {form})" if form is not addr else ""
            return False, f"non-global address {addr}{detail}"
    return True, ""


def _system_resolver(host: str) -> set[str]:
    return {info[4][0] for info in socket.getaddrinfo(host, None)}


_resolver = _system_resolver  # injectable for tests


def _validated_addresses(host: str) -> tuple[bool, str, frozenset[str]]:
    """Shared validation: (ok, why, addresses judged). The verdict hooks use
    ok/why; the server_connect pin uses the addresses — exactly the set that
    passed the guard, so the connection provably goes where the guard looked
    (#41). Exemptions and unresolvable hosts carry an empty set (nothing to
    pin); a failed validation does too (nothing may be connected)."""
    host = tjor_policy._canon_host(host)
    # Gateway (D4): the configured LiteLLM gateway is an INTENTIONAL internal
    # endpoint that resolves to a private docker IP. Exempt exactly it (and only
    # when a gateway is configured) from the SSRF/DNS-rebind guard — a single,
    # config-scoped host, not a blanket TJOR_IP_GUARD=off.
    if GATEWAY_HOST and host == GATEWAY_HOST:
        return True, "gateway-exempt", frozenset()
    # Kube broker (#45, #57): the same config-scoped exemption for EACH
    # configured cluster API server — a private-endpoint control plane must be
    # reachable without disabling the guard for every other allowed host.
    if host in KUBE_API_HOSTS:
        return True, "kube-exempt", frozenset()
    now = time.monotonic()
    hit = _ip_cache.get(host)
    if hit and now - hit.ts < _IP_TTL_SECONDS:
        return hit.ok, hit.why, hit.addresses

    if _is_ip_literal(host):
        addresses = {host}  # IP literal (possibly zone-suffixed): judge directly
    else:
        # Bound the resolver so a hung lookup can't stall the loop (#59). Order
        # matters: TimeoutError (from .result) is an OSError subclass on 3.11+,
        # so catch the bound-exceeded case FIRST. A timeout fails CLOSED and is
        # NOT cached (a transient stall denies only this attempt); a FAST OSError
        # (NXDOMAIN/gaierror) keeps the documented unresolvable-passes behavior.
        try:
            addresses = _resolve_pool.submit(_resolver, host).result(timeout=_RESOLVE_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return False, "resolve-timeout", frozenset()
        except OSError:
            return True, "unresolvable", frozenset()

    ok, why = True, ""
    for raw in addresses:
        ok, why = _address_public(raw)
        if not ok:
            break

    validated = frozenset(addresses) if ok else frozenset()
    if len(_ip_cache) >= _IP_CACHE_MAX:
        _ip_cache.clear()
    _ip_cache[host] = _CacheEntry(now, ok, why, validated)
    return ok, why, validated


def resolved_addresses_ok(host: str) -> tuple[bool, str]:
    """True unless the host resolves to any non-public address."""
    ok, why, _ = _validated_addresses(host)
    return ok, why


def _pick_pinned(addresses: frozenset[str]) -> str | None:
    """Deterministic pin choice from a validated set: prefer IPv4 (the
    proxy's container network reality), then lexicographic — resolver order
    is not stable and the pinned address must be reproducible."""
    if not addresses:
        return None

    def key(raw: str):
        is_v6 = isinstance(ipaddress.ip_address(raw.split("%")[0]), ipaddress.IPv6Address)
        return (is_v6, raw)

    return min(addresses, key=key)


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
        # `host` and the stripped header names are both attacker-influenced and
        # go to the proxy's stderr (visible via `docker logs`) — sanitize both
        # so a hostile hostname/header can't inject escapes into that view.
        safe_host = _safe_ascii(host)
        safe_keys = sorted(_safe_ascii(k, 64) for k in stripped)
        print(
            f"tjor: stripped forged/unknown identity headers toward {safe_host} "
            f"(#{_strip_log_count}): {safe_keys}",
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
    # set, not list: mitmproxy's multidict yields a duplicated header name once
    # per occurrence, while del removes every occurrence — a second del on the
    # same name would raise outside the fail-closed wrapper.
    for name in {n for n in flow.request.headers if n.lower().startswith("x-agent-")}:
        del flow.request.headers[name]
    for name, value in final.items():
        flow.request.headers[name] = value
    if stripped:
        _log_stripped(flow.request.host, stripped)


# ---------------------------------------------------------- credential broker

def broker_authorization(host: str, port: int) -> str | None:
    """Testable seam: the Authorization value to inject toward `host:port`, or
    None if this origin is not a broker destination or no credential is
    available (fail-closed). Origin-scoped (#49): a port-scoped destination
    entry never matches the same hostname on a different port. The kube source
    returns a per-cluster `Bearer <t>` (the scheme the K8s API requires); the
    pat/github-app source returns `token <t>` toward BROKER_HOSTS."""
    if KUBE_BROKER is not None:
        try:
            return KUBE_BROKER.authorization(host, port)  # Bearer, exact origin, or None
        except Exception as exc:  # noqa: BLE001
            print(f"tjor: kube broker error — no credential injected: {exc!r}", file=sys.stderr, flush=True)
            return None
    if BROKER is None or not tjor_identity.broker_covers(BROKER_HOSTS, host, port):
        return None
    try:
        return BROKER.authorization()
    except Exception as exc:  # noqa: BLE001
        print(f"tjor: broker error — no credential injected: {exc!r}", file=sys.stderr, flush=True)
        return None


def _apply_broker(flow) -> None:
    """Toward a broker destination host, replace Authorization with the real
    short-TTL credential. The agent only ever holds a placeholder; whatever
    it sent is overwritten. Fail-closed: if no credential is available, the
    placeholder is STRIPPED (never forwarded) so the upstream rejects rather
    than the agent's placeholder leaking or a stale token being used."""
    host, port = flow.request.host, flow.request.port
    if KUBE_BROKER is not None:
        # kube: a destination is exactly a configured cluster origin (#49/#57).
        # Toward a non-cluster host, leave the request untouched. Toward a
        # cluster origin, the placeholder is STRIPPED and replaced with that
        # cluster's real Bearer token — and if no credential is available
        # (KUBE_BROKER.authorization returned None unexpectedly), the
        # placeholder is still stripped so the upstream rejects rather than the
        # agent's placeholder being forwarded. This matches the pat path's
        # documented fail-closed contract.
        if not KUBE_BROKER.covers(host, port):
            return
        auth = broker_authorization(host, port)
        if "authorization" in flow.request.headers:
            del flow.request.headers["authorization"]
        if auth is not None:
            flow.request.headers["authorization"] = auth
        return
    if BROKER is None or not tjor_identity.broker_covers(BROKER_HOSTS, host, port):
        return
    auth = broker_authorization(host, port)
    if "authorization" in flow.request.headers:
        del flow.request.headers["authorization"]
    if auth is not None:
        flow.request.headers["authorization"] = auth


def _apply_gateway(flow) -> None:
    """LLM gateway (D4): toward the gateway host, replace Authorization with the
    generated master key. The agent's harness holds only a placeholder key; the
    real key lives only here (and in the gateway sidecar) and never enters the
    sandbox. Fail-closed: the placeholder is always stripped toward the gateway,
    so a missing key yields an upstream 401 rather than leaking the placeholder.
    Admin paths are refused by the egress policy — the gateway host is on the
    block list with only inference paths carved back in (host-block + paths.allow,
    NOT an admin-prefix denylist) — so this key only ever authenticates inference;
    the management API is unreachable by construction regardless."""
    if not GATEWAY_HOST or tjor_policy._canon_host(flow.request.host) != GATEWAY_HOST:
        return
    if "authorization" in flow.request.headers:
        del flow.request.headers["authorization"]
    if GATEWAY_KEY:
        flow.request.headers["authorization"] = f"Bearer {GATEWAY_KEY}"


# ------------------------------------------------------- agent-facing reasons

def _agent_reason(why: str) -> str:
    """The literal-free form of a guard reason for the AGENT (#60). The
    operator denial log keeps the full reason (including the specific resolved
    address), but a guard denial returned to the agent should state only the
    denial CLASS, not the concrete internal address it resolved to (or the raw
    input it echoed). Only these specifics-bearing guard reasons are
    generalized; every other reason is already literal-free and passes through
    unchanged (and policy blocks / default-deny describe the agent's own
    request, so they stay informative)."""
    if why.startswith("non-global address"):
        return "non-global-address"
    if why.startswith("unparseable address"):
        return "unparseable-address"
    return why


def _agent_rule(rule: str) -> str:
    """`_agent_reason` applied to a full `ip-guard:<why>` verdict rule."""
    prefix = "ip-guard:"
    return prefix + _agent_reason(rule[len(prefix):]) if rule.startswith(prefix) else rule


# ------------------------------------------------------------ mitmproxy glue

class TjorPolicy:
    def server_connect(self, data) -> None:
        # Resolve-and-pin (#41): validate the destination HERE — the hook that
        # decides where the upstream socket actually goes — and pin the address
        # so no second resolution exists between judgment and connect. TLS is
        # unaffected: mitmproxy derives upstream SNI/verification from the
        # client's SNI (the hostname); this hook never touches server.sni.
        # Fail-closed: validation failure or ANY error kills the connection.
        if not _IP_GUARD:
            return
        try:
            host, port = data.server.address
            canon = tjor_policy._canon_host(host)
            # Deliberate internal endpoints keep live docker DNS (their IPs
            # change on container restart): never pinned, same scoped
            # exemptions as the verdict path.
            if (GATEWAY_HOST and canon == GATEWAY_HOST) or canon in KUBE_API_HOSTS:
                return
            if _is_ip_literal(canon):
                return  # an IP literal IS the judged address — nothing to pin
            ok, why, validated = _validated_addresses(canon)
            if not ok:
                _log_denial(canon, f"ip-guard-pin:{why}")  # operator log keeps the address
                data.server.error = f"tjor ip-guard: {_agent_reason(why)}"  # agent gets the class only (#60)
                return
            pinned = _pick_pinned(validated)
            if pinned is None:
                # Unresolvable (guard's documented pass): stay unpinned —
                # mitmproxy's own resolution fails and nothing flows.
                return
            data.server.address = (pinned, port)
        except Exception as exc:  # noqa: BLE001 — never pass through unpinned
            print(f"tjor: ip-guard pin error — killing connection: {exc!r}",
                  file=sys.stderr, flush=True)
            data.server.error = "tjor ip-guard: pin failure (fail-closed)"

    def http_connect(self, flow) -> None:
        from mitmproxy import http

        verdict = connect_verdict(flow.request.host)
        if not verdict.allowed:
            _log_denial(flow.request.host, verdict.rule)  # operator log keeps the full reason
            agent_rule = _agent_rule(verdict.rule)         # agent gets the class only (#60)
            flow.response = http.Response.make(
                403,
                f"tjor egress policy: DENY CONNECT ({agent_rule})\n".encode(),
                {"x-tjor-policy": "deny", "x-tjor-rule": agent_rule},
            )

    def request(self, flow) -> None:
        from mitmproxy import http

        verdict = request_verdict(flow.request.pretty_url, flow.request.host)
        if verdict.allowed:
            _apply_identity(flow)
            _apply_broker(flow)
            _apply_gateway(flow)
        if not verdict.allowed:
            _log_denial(flow.request.host, verdict.rule)  # operator log keeps the full reason
            agent_rule = _agent_rule(verdict.rule)         # agent gets the class only (#60)
            flow.response = http.Response.make(
                403,
                (
                    f"tjor egress policy: DENY ({agent_rule}"
                    + (f": {verdict.pattern}" if verdict.pattern else "")
                    + ")\n"
                ).encode(),
                {
                    "content-type": "text/plain",
                    "x-tjor-policy": "deny",
                    "x-tjor-rule": agent_rule,
                },
            )

    def done(self) -> None:
        # Best-effort revocation on proxy shutdown (tjor down / gc gives the
        # sidecar a stop grace period). Installation tokens also auto-expire
        # (~1h), the reliable backstop; PATs have nothing to revoke.
        if BROKER is not None:
            try:
                ok = BROKER.teardown()
                if ok:
                    print("tjor: broker credential revoked on shutdown", file=sys.stderr, flush=True)
                else:
                    print("tjor: broker revoke on shutdown did NOT succeed (token auto-expires ~1h)",
                          file=sys.stderr, flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"tjor: broker revoke on shutdown failed (token auto-expires): {exc!r}",
                      file=sys.stderr, flush=True)
        # Kube broker (#57): forget the per-cluster SA tokens too (the
        # credential-broker spec's teardown requirement applies here as well;
        # the tokens are short-TTL and non-revocable, so this drops them from
        # memory rather than calling an API).
        if KUBE_BROKER is not None:
            try:
                KUBE_BROKER.teardown()
                print("tjor: kube broker tokens forgotten on shutdown (short-TTL, auto-expire)",
                      file=sys.stderr, flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"tjor: kube broker teardown failed (tokens auto-expire): {exc!r}",
                      file=sys.stderr, flush=True)


addons = [TjorPolicy()]
