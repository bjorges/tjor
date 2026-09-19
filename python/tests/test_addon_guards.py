"""Tests for the proxy addon's fail-closed wrapper and resolved-address
(DNS-rebind/SSRF) guard — imported without mitmproxy, like the parity suite."""

import importlib.util
import sys
from pathlib import Path

import pytest

PY_DIR = Path(__file__).resolve().parents[1]
REPO = PY_DIR.parent
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(PY_DIR))


def load_addon():
    spec = importlib.util.spec_from_file_location("tjor_addon_guards", REPO / "proxy" / "addon.py")
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.POLICY_PATH = str(FIXTURES / "parity-policy.toml")
    addon._cache = {"mtime": None, "policy": None}
    addon._ip_cache.clear()
    return addon


class TestFailClosedWrapper:
    def test_exception_in_decision_denies(self, monkeypatch):
        addon = load_addon()
        monkeypatch.setattr(addon, "decide", lambda url: 1 / 0)
        verdict = addon.request_verdict("https://allowed.test/x", "allowed.test")
        assert not verdict.allowed and verdict.rule == "fail-closed:addon-error"

    def test_exception_in_connect_denies(self, monkeypatch):
        addon = load_addon()
        monkeypatch.setattr(addon, "decide_connect", lambda host: (_ for _ in ()).throw(RuntimeError))
        verdict = addon.connect_verdict("allowed.test")
        assert not verdict.allowed and verdict.rule == "fail-closed:addon-error"

    def test_normal_path_unaffected(self):
        addon = load_addon()
        addon._resolver = lambda host: {"140.82.121.3"}
        assert addon.request_verdict("https://allowed.test/x", "allowed.test").allowed
        assert not addon.request_verdict("https://blocked.test/x", "blocked.test").allowed


class TestIdentityAtTheAddon:
    def make(self):
        addon = load_addon()
        import tjor_identity as ti
        addon.IDENTITY = ti.load_identity({"TJOR_SESSION_ID": "sess-1", "TJOR_HARNESS": "opencode"})
        addon.INJECT_HOSTS = ["inject.test"]
        return addon

    def test_forged_stripped_and_logged(self, capsys):
        addon = self.make()
        final, stripped = addon.identity_outcome({"x-agent-session-id": "intruder"}, "other.test")
        assert final == {} and stripped == {"x-agent-session-id": "intruder"}
        addon._log_stripped("other.test", stripped)
        assert "stripped forged" in capsys.readouterr().err

    def test_log_rate_limited(self, capsys):
        addon = self.make()
        capsys.readouterr()  # drain import-time output
        for _ in range(200):
            addon._log_stripped("h.test", {"x-agent-session-id": "x"})
        lines = [l for l in capsys.readouterr().err.splitlines() if "stripped forged" in l]
        assert len(lines) == 22  # first 20 + #100 + #200, not 200

    def test_inject_only_on_configured_host(self):
        addon = self.make()
        final, _ = addon.identity_outcome({}, "inject.test")
        assert final.get("x-agent-session-id") == "sess-1"
        final, _ = addon.identity_outcome({}, "elsewhere.test")
        assert final == {}

    def test_exception_fails_closed(self, monkeypatch):
        addon = self.make()
        monkeypatch.setattr(addon.tjor_identity, "should_inject", lambda *a: 1 / 0)
        final, stripped = addon.identity_outcome({"x-agent-session-id": "sess-1"}, "x.test")
        assert final == {} and stripped == {"x-agent-session-id": "sess-1"}


class TestApplyIdentityMultidict:
    """_apply_identity against mitmproxy's real Headers multidict — plain
    dicts (used elsewhere) cannot exhibit duplicate-name behavior. Skipped
    where mitmproxy is not installed (run locally via uv with mitmproxy)."""

    def make(self):
        import pytest

        pytest.importorskip("mitmproxy")
        import types

        from mitmproxy.http import Headers

        addon = load_addon()
        import tjor_identity as ti

        addon.IDENTITY = ti.load_identity({"TJOR_SESSION_ID": "sess-1", "TJOR_HARNESS": "opencode"})
        addon.INJECT_HOSTS = ["inject.test"]

        def flow(host, pairs):
            return types.SimpleNamespace(
                request=types.SimpleNamespace(
                    headers=Headers([(k.encode(), v.encode()) for k, v in pairs]),
                    host=host,
                )
            )

        return addon, flow

    def test_duplicate_forged_headers_all_removed(self):
        addon, flow = self.make()
        f = flow("elsewhere.test", [
            ("x-agent-session-id", "sess-1"),
            ("x-agent-session-id", "intruder"),
            ("x-agent-custom", "a"),
            ("x-agent-custom", "b"),
            ("accept", "*/*"),
        ])
        addon._apply_identity(f)
        assert f.request.headers.get_all("x-agent-custom") == []
        # duplicate values collapse; whatever survives must be the registered value
        assert f.request.headers.get_all("x-agent-session-id") in ([], ["sess-1"])
        assert f.request.headers["accept"] == "*/*"

    def test_duplicates_toward_inject_host_replaced_wholesale(self):
        addon, flow = self.make()
        f = flow("inject.test", [
            ("x-agent-session-id", "intruder"),
            ("x-agent-session-id", "intruder-2"),
        ])
        addon._apply_identity(f)
        assert f.request.headers.get_all("x-agent-session-id") == ["sess-1"]
        assert f.request.headers.get_all("x-agent-harness") == ["opencode"]


class TestBrokerInjection:
    def make(self, source_hosts="github.com", cred="tok-123"):
        addon = load_addon()
        import tjor_broker as tb
        addon.BROKER_HOSTS = addon.tjor_identity.parse_broker_hosts(source_hosts)
        addon.BROKER = tb.BrokerState({"source": "pat", "token": cred}, clock=lambda: 0.0) if cred else None
        return addon

    def test_authorization_injected_for_destination(self):
        addon = self.make()
        assert addon.broker_authorization("github.com", 443) == "token tok-123"
        assert addon.broker_authorization("api.github.com", 443) is None  # not in hosts here
        assert addon.broker_authorization("evil.test", 443) is None

    def test_portless_entry_covers_any_port(self):
        addon = self.make()
        assert addon.broker_authorization("github.com", 8443) == "token tok-123"

    def test_port_scoped_entry_does_not_leak_across_ports(self):
        # Origin scoping (#49): the kube source emits host:port entries; the
        # same hostname on ANY other port must never receive the credential.
        addon = self.make(source_hosts="api.cluster.example:6443")
        assert addon.broker_authorization("api.cluster.example", 6443) == "token tok-123"
        assert addon.broker_authorization("api.cluster.example", 8443) is None
        assert addon.broker_authorization("api.cluster.example", 443) is None
        assert addon.broker_authorization("other.example", 6443) is None

    def test_disabled_when_no_broker(self):
        addon = self.make(cred=None)
        assert addon.broker_authorization("github.com", 443) is None

    def test_apply_broker_replaces_placeholder(self):
        pytest.importorskip("mitmproxy")
        import types
        from mitmproxy.http import Headers

        addon = self.make()
        flow = types.SimpleNamespace(request=types.SimpleNamespace(
            host="github.com", port=443,
            headers=Headers([(b"authorization", b"Basic cGxhY2Vob2xkZXI=")]),
        ))
        addon._apply_broker(flow)
        assert flow.request.headers["authorization"] == "token tok-123"

    def test_apply_broker_strips_when_no_credential(self, capsys):
        pytest.importorskip("mitmproxy")
        import types
        import tjor_broker as tb
        from mitmproxy.http import Headers

        addon = self.make()
        # a broker configured but unable to mint -> strip the placeholder, inject nothing
        addon.BROKER = tb.BrokerState({"source": "pat"}, clock=lambda: 0.0)  # no token -> None
        flow = types.SimpleNamespace(request=types.SimpleNamespace(
            host="github.com", port=443,
            headers=Headers([(b"authorization", b"Basic cGxhY2Vob2xkZXI=")]),
        ))
        addon._apply_broker(flow)
        assert "authorization" not in flow.request.headers

    def test_apply_broker_untouched_for_non_destination(self):
        pytest.importorskip("mitmproxy")
        import types
        from mitmproxy.http import Headers

        addon = self.make()
        flow = types.SimpleNamespace(request=types.SimpleNamespace(
            host="other.test", port=443,
            headers=Headers([(b"authorization", b"Bearer agent-own")]),
        ))
        addon._apply_broker(flow)
        assert flow.request.headers["authorization"] == "Bearer agent-own"


class TestKubeMultiInjection:
    """Multi-cluster kube broker (#57): each cluster's Bearer token injected
    ONLY toward its own exact origin (#49); no cross-cluster leakage."""

    CFG = {
        "source": "kube",
        "clusters": [
            {"origin": "api.prod:6443", "token": "prod-sa"},
            {"origin": "api.staging:6443", "token": "staging-sa"},
        ],
    }

    def make(self):
        import tjor_broker as tb
        addon = load_addon()
        addon.BROKER = None
        addon.KUBE_BROKER = tb.KubeMultiBroker(self.CFG)
        return addon

    def _flow(self, host, port, auth=None):
        pytest.importorskip("mitmproxy")
        import types
        from mitmproxy.http import Headers
        pairs = [(b"authorization", auth.encode())] if auth else []
        return types.SimpleNamespace(request=types.SimpleNamespace(
            host=host, port=port, headers=Headers(pairs)))

    def test_bearer_scheme_used_not_token(self):
        addon = self.make()
        assert addon.broker_authorization("api.prod", 6443) == "Bearer prod-sa"

    def test_each_origin_gets_its_own_token(self):
        addon = self.make()
        assert addon.broker_authorization("api.prod", 6443) == "Bearer prod-sa"
        assert addon.broker_authorization("api.staging", 6443) == "Bearer staging-sa"

    def test_cross_cluster_isolation(self):
        addon = self.make()
        # prod's origin must never carry staging's token
        assert "staging" not in (addon.broker_authorization("api.prod", 6443) or "")
        assert "prod" not in (addon.broker_authorization("api.staging", 6443) or "")

    def test_non_cluster_host_gets_nothing(self):
        addon = self.make()
        assert addon.broker_authorization("elsewhere.test", 443) is None
        assert addon.broker_authorization("api.prod", 443) is None  # right host, wrong port

    def test_apply_overwrites_placeholder_toward_cluster(self):
        addon = self.make()
        f = self._flow("api.prod", 6443, auth="Bearer tjor-broker-placeholder")
        addon._apply_broker(f)
        assert f.request.headers["authorization"] == "Bearer prod-sa"

    def test_apply_leaves_non_cluster_untouched(self):
        addon = self.make()
        f = self._flow("elsewhere.test", 443, auth="Bearer agent-own")
        addon._apply_broker(f)
        assert f.request.headers["authorization"] == "Bearer agent-own"

    def test_apply_strips_placeholder_when_credential_unavailable(self):
        # Fail-closed (#57 review, Finding B): toward a CLUSTER origin whose
        # credential is momentarily unavailable, the placeholder must be
        # STRIPPED (not forwarded) — matching the pat path's contract.
        addon = self.make()
        addon.KUBE_BROKER.authorization = lambda h, p: None  # covered, but no cred
        f = self._flow("api.prod", 6443, auth="Bearer tjor-broker-placeholder")
        addon._apply_broker(f)
        assert "authorization" not in f.request.headers  # stripped, upstream will reject

    def test_covers_distinguishes_cluster_origin_from_host(self):
        addon = self.make()
        assert addon.KUBE_BROKER.covers("api.prod", 6443) is True
        assert addon.KUBE_BROKER.covers("api.prod", 443) is False   # wrong port
        assert addon.KUBE_BROKER.covers("elsewhere.test", 6443) is False

    def test_apply_does_not_leak_across_ports(self):
        addon = self.make()
        f = self._flow("api.prod", 443, auth="Bearer agent-own")  # not the cluster port
        addon._apply_broker(f)
        assert f.request.headers["authorization"] == "Bearer agent-own"


class TestAddressGuard:
    def test_private_resolution_denied(self):
        addon = load_addon()
        addon._resolver = lambda host: {"10.0.0.5"}
        verdict = addon.request_verdict("https://allowed.test/x", "allowed.test")
        assert not verdict.allowed and verdict.rule.startswith("ip-guard:")

    def test_mixed_resolution_denied(self):
        addon = load_addon()
        addon._resolver = lambda host: {"140.82.121.3", "172.17.0.2"}
        assert not addon.connect_verdict("allowed.test").allowed

    @staticmethod
    def bad(host):
        raise OSError("NXDOMAIN")

    def test_unresolvable_passes_guard(self):
        addon = load_addon()
        addon._resolver = self.bad
        ok, why = addon.resolved_addresses_ok("allowed.test")
        assert ok and why == "unresolvable"
        # ...so the policy verdict stands (upstream connect fails on its own)
        assert addon.connect_verdict("allowed.test").allowed

    def test_loopback_link_local_metadata_denied(self):
        addon = load_addon()
        for ip in ("127.0.0.1", "169.254.169.254", "192.168.1.1", "100.64.0.1", "::1", "fe80::1"):
            addon._ip_cache.clear()
            addon._resolver = lambda host, ip=ip: {ip}
            ok, why = addon.resolved_addresses_ok("allowed.test")
            assert not ok, ip

    def test_ipv4_mapped_ipv6_unwrapped(self):
        addon = load_addon()
        for raw in ("::ffff:169.254.169.254", "::ffff:10.0.0.5", "::ffff:100.64.0.1"):
            addon._ip_cache.clear()
            addon._resolver = lambda host, raw=raw: {raw}
            ok, why = addon.resolved_addresses_ok("allowed.test")
            assert not ok, raw

    def test_cgnat_denied_regardless_of_is_global(self):
        addon = load_addon()
        addon._resolver = lambda host: {"100.64.0.1"}
        assert not addon.resolved_addresses_ok("allowed.test")[0]

    def test_nat64_embedded_private_denied(self):
        # 64:ff9b::/96 well-known prefix (RFC 6052): the low 32 bits encode a
        # translated IPv4 target — a private/metadata one must not sail past.
        addon = load_addon()
        for raw in ("64:ff9b::10.0.0.5", "64:ff9b::169.254.169.254", "64:ff9b::a9fe:a9fe"):
            addon._ip_cache.clear()
            addon._resolver = lambda host, raw=raw: {raw}
            ok, why = addon.resolved_addresses_ok("allowed.test")
            assert not ok, raw

    def test_nat64_embedded_public_passes(self):
        # The prefix itself is legitimately routable; only the embedded
        # address decides — a public target through NAT64 must not be blocked.
        addon = load_addon()
        addon._resolver = lambda host: {"64:ff9b::8.8.8.8"}
        assert addon.resolved_addresses_ok("allowed.test")[0]

    def test_nat64_local_use_prefix_denied(self):
        addon = load_addon()  # 64:ff9b:1::/48 — RFC 8215, never globally reachable
        addon._resolver = lambda host: {"64:ff9b:1::8.8.8.8"}
        assert not addon.resolved_addresses_ok("allowed.test")[0]

    def test_6to4_embedded_private_denied(self):
        addon = load_addon()  # 2002:0a00:0005:: embeds 10.0.0.5
        addon._resolver = lambda host: {"2002:a00:5::1"}
        assert not addon.resolved_addresses_ok("allowed.test")[0]

    def test_ipv4_compatible_embedded_private_denied(self):
        # Deprecated ::/96 IPv4-compatible form: ::169.254.169.254, ::10.0.0.1
        # embed an IPv4 target and must be unwrapped like the other forms.
        addon = load_addon()
        for raw in ("::169.254.169.254", "::10.0.0.1", "::a9fe:a9fe"):
            addon._ip_cache.clear()
            addon._resolver = lambda host, raw=raw: {raw}
            assert not addon.resolved_addresses_ok("allowed.test")[0], raw

    def test_ipv4_compatible_embedded_public_passes(self):
        addon = load_addon()
        addon._resolver = lambda host: {"::8.8.8.8"}
        assert addon.resolved_addresses_ok("allowed.test")[0]

    def test_extra_iana_reserved_ranges_denied(self):
        addon = load_addon()  # the round-4 additions to _DENY_NETS
        for ip in ("255.255.255.255", "2001::1", "100:0:0:1::1"):
            addon._ip_cache.clear()
            addon._resolver = lambda host, ip=ip: {ip}
            assert not addon.resolved_addresses_ok("allowed.test")[0], ip

    def test_teredo_embedded_private_client_denied(self):
        # 2001::/32: last 32 bits are the bit-inverted client IPv4;
        # f5ff:fffa un-obfuscates to 10.0.0.5.
        addon = load_addon()
        addon._resolver = lambda host: {"2001:0:4136:e378:8000:63bf:f5ff:fffa"}
        assert not addon.resolved_addresses_ok("allowed.test")[0]

    def test_documentation_and_benchmark_ranges_denied(self):
        addon = load_addon()
        for ip in (
            "192.0.2.1", "198.51.100.1", "203.0.113.1", "192.88.99.1",
            "100::1", "2001:2::1", "2001:db8::1", "3fff::1", "5f00::1",
        ):
            addon._ip_cache.clear()
            addon._resolver = lambda host, ip=ip: {ip}
            ok, why = addon.resolved_addresses_ok("allowed.test")
            assert not ok, ip

    def test_zone_suffixed_literal_denied(self):
        addon = load_addon()
        addon._resolver = lambda host: (_ for _ in ()).throw(AssertionError("must not resolve literals"))
        ok, _ = addon.resolved_addresses_ok("fe80::1%eth0")
        assert not ok

    def test_ip_literal_checked_directly(self):
        addon = load_addon()
        addon._resolver = lambda host: (_ for _ in ()).throw(AssertionError("must not resolve literals"))
        ok, _ = addon.resolved_addresses_ok("10.1.2.3")
        assert not ok
        addon._ip_cache.clear()
        ok, _ = addon.resolved_addresses_ok("140.82.121.3")
        assert ok

    def test_guard_can_be_disabled(self, monkeypatch):
        addon = load_addon()
        addon._resolver = lambda host: {"10.0.0.5"}
        addon._IP_GUARD = False
        assert addon.connect_verdict("allowed.test").allowed

    def test_cache_respects_ttl_shape(self):
        addon = load_addon()
        addon._resolver = lambda host: {"140.82.121.3"}
        assert addon.resolved_addresses_ok("allowed.test")[0]
        addon._resolver = lambda host: {"10.0.0.5"}
        # cached verdict still served inside the TTL window
        assert addon.resolved_addresses_ok("allowed.test")[0]


class TestAgentFacingReason:
    """Guard denials do not disclose the resolved address to the agent (#60):
    the operator log keeps the full reason; the agent gets only the class."""

    def test_agent_reason_generalizes_specifics(self):
        addon = load_addon()
        assert addon._agent_reason("non-global address 10.0.0.5") == "non-global-address"
        assert addon._agent_reason("non-global address fd00::1 (embeds 10.0.0.5)") == "non-global-address"
        assert addon._agent_reason("unparseable address 'weird'") == "unparseable-address"

    def test_agent_reason_passes_through_literal_free(self):
        addon = load_addon()
        for why in ("resolve-timeout", "unresolvable", "gateway-exempt", "kube-exempt"):
            assert addon._agent_reason(why) == why

    def test_agent_rule_handles_ip_guard_prefix_and_others(self):
        addon = load_addon()
        assert addon._agent_rule("ip-guard:non-global address 10.0.0.5") == "ip-guard:non-global-address"
        assert addon._agent_rule("ip-guard:resolve-timeout") == "ip-guard:resolve-timeout"
        # non-guard rules (policy blocks / default-deny) are the agent's own
        # request and pass through unchanged
        assert addon._agent_rule("default-deny") == "default-deny"
        assert addon._agent_rule("block:host") == "block:host"

    def test_no_ip_literal_reaches_the_agent(self):
        addon = load_addon()
        rule = "ip-guard:non-global address 10.0.0.5"
        assert "10.0.0.5" not in addon._agent_rule(rule)  # the whole point

    def test_end_to_end_403_omits_ip_but_log_keeps_it(self, tmp_path):
        # A non-global resolution: the agent 403 body + x-tjor-rule header carry
        # no IP literal, while the operator denial log still records it.
        pytest.importorskip("mitmproxy")
        import types
        from mitmproxy.http import Headers
        addon = load_addon()
        log = tmp_path / "denials.log"
        addon.DENIAL_LOG = str(log)
        addon._resolver = lambda host: {"10.0.0.5"}  # allowed.test resolves private
        pol = addon.TjorPolicy()
        flow = types.SimpleNamespace(
            request=types.SimpleNamespace(host="allowed.test",
                                          pretty_url="https://allowed.test/x",
                                          headers=Headers()),
            response=None)
        pol.request(flow)
        body = flow.response.content.decode()
        assert "10.0.0.5" not in body                                  # agent body redacted
        assert "non-global-address" in body
        assert "10.0.0.5" not in flow.response.headers["x-tjor-rule"]  # agent header redacted
        assert "10.0.0.5" in log.read_text()                           # operator log keeps it


class TestBoundedResolution:
    """The resolver call is time-bounded so a hung DNS answer cannot stall the
    event loop (#59). Fail closed on timeout; fast-unresolvable unchanged."""

    def _hanging_addon(self, gate, monkeypatch=None):
        addon = load_addon()
        addon._RESOLVE_TIMEOUT = 0.2  # keep the suite fast; real default is 5s
        addon._resolver = lambda host: (gate.wait(), {"1.2.3.4"})[1]  # blocks until gate is set
        return addon

    def test_hang_returns_fail_closed_within_the_bound(self):
        import threading, time as _t
        gate = threading.Event()
        addon = self._hanging_addon(gate)
        try:
            start = _t.monotonic()
            ok, why, addrs = addon._validated_addresses("slow.test")
            elapsed = _t.monotonic() - start
            assert not ok and why == "resolve-timeout" and addrs == frozenset()
            assert elapsed < 2.0, f"resolution blocked {elapsed:.2f}s — did not bound"
        finally:
            gate.set()  # unblock the worker so pool teardown never waits

    def test_timeout_denies_verdict_and_kills_pin(self):
        import threading
        pytest.importorskip("mitmproxy")
        from mitmproxy import connection
        from mitmproxy.proxy import server_hooks
        gate = threading.Event()
        addon = self._hanging_addon(gate)
        try:
            # allowed.test is policy-allowed, so the verdict reaches the guard.
            v = addon.request_verdict("https://allowed.test/x", "allowed.test")
            assert not v.allowed and v.rule == "ip-guard:resolve-timeout"
            addon._ip_cache.clear()
            cv = addon.connect_verdict("allowed.test")
            assert not cv.allowed and cv.rule == "ip-guard:resolve-timeout"
            addon._ip_cache.clear()
            data = server_hooks.ServerConnectionHookData(
                server=connection.Server(address=("allowed.test", 443)),
                client=connection.Client(peername=("10.0.0.2", 5), sockname=("10.0.0.1", 8080)))
            addon.TjorPolicy().server_connect(data)
            assert data.server.error and "resolve-timeout" in data.server.error
            assert data.server.address == ("allowed.test", 443)  # never pinned to an unvalidated addr
        finally:
            gate.set()

    def test_timeout_is_not_cached(self):
        import threading
        gate = threading.Event()
        addon = self._hanging_addon(gate)
        try:
            ok, why, _ = addon._validated_addresses("flaky.test")
            assert not ok and why == "resolve-timeout"
        finally:
            gate.set()
        # DNS recovers: the next resolution must be judged fresh, not a cached denial
        addon._resolver = lambda host: {"140.82.121.3"}
        ok2, why2, _ = addon._validated_addresses("flaky.test")
        assert ok2 and why2 == ""

    def test_fast_unresolvable_unchanged(self):
        addon = load_addon()
        def boom(host):
            raise OSError("NXDOMAIN")  # fast failure, not a hang
        addon._resolver = boom
        ok, why = addon.resolved_addresses_ok("nonexistent.test")
        assert ok and why == "unresolvable"  # permitted (nothing can connect), not a timeout


class TestSafeAscii:
    """The shared sanitizer for attacker-influenced strings written to logs a
    human may view (denial log, proxy stderr via docker logs)."""

    def test_ansi_escape_collapsed(self):
        addon = load_addon()
        out = addon._safe_ascii("evil\x1b[31mred\x1b[0m.example.com")
        assert "\x1b" not in out
        assert out == "evil?[31mred?[0m.example.com"   # each ESC byte -> '?'

    def test_controls_and_c1_and_bidi_collapsed(self):
        addon = load_addon()
        s = "a\nb\tc\x00\x7f\x9b‮"   # newline/tab are controls too here
        out = addon._safe_ascii(s)
        assert all(0x20 < ord(c) < 0x7F for c in out)  # only printable non-space ASCII survives

    def test_printable_ascii_preserved(self):
        addon = load_addon()
        assert addon._safe_ascii("api.githubcopilot.com") == "api.githubcopilot.com"

    def test_bounded_and_empty(self):
        addon = load_addon()
        assert addon._safe_ascii("x" * 500) == "x" * 253
        assert addon._safe_ascii("", 253) == "?"
        assert addon._safe_ascii("\x1b\x1b") == "?" * 2

    def test_log_stripped_sanitizes_host(self, capsys):
        addon = load_addon()
        addon._strip_log_count = 0
        addon._log_stripped("evil\x1b]0;pwned\x07.example.com", {"x-agent-\x1bfoo": "1"})
        err = capsys.readouterr().err
        assert "\x1b" not in err            # no raw escape reaches stderr
        assert "example.com" in err          # the printable part still shown


class _GwReq:
    def __init__(self, host, headers=None):
        self.host = host
        self.headers = headers if headers is not None else {}


class _GwFlow:
    def __init__(self, host, headers=None):
        self.request = _GwReq(host, headers)


class TestGateway:
    """LLM gateway (D4): the SSRF-guard exemption for the gateway host, and the
    master-key injection toward it (agent holds only a placeholder)."""

    def test_ip_guard_exempts_only_the_gateway_host(self):
        addon = load_addon()
        addon.GATEWAY_HOST = "tjor-gateway"
        addon._resolver = lambda h: {"172.20.0.5"}   # private docker IP for any host
        ok, why = addon.resolved_addresses_ok("tjor-gateway")
        assert ok and why == "gateway-exempt"
        # a DIFFERENT host resolving to a private IP is still denied
        ok2, _ = addon.resolved_addresses_ok("sneaky.internal.test")
        assert not ok2

    def test_no_exemption_when_gateway_disabled(self):
        addon = load_addon()
        addon.GATEWAY_HOST = ""
        addon._resolver = lambda h: {"172.20.0.5"}
        ok, _ = addon.resolved_addresses_ok("tjor-gateway")
        assert not ok   # no gateway configured -> guard applies normally

    def test_ip_guard_exempts_only_the_kube_api_host(self):
        # Kube broker (#45): a private-endpoint cluster API server gets the
        # same config-scoped exemption as the gateway.
        addon = load_addon()
        addon.KUBE_API_HOSTS = frozenset({"api.private-cluster.internal"})
        addon._resolver = lambda h: {"10.12.0.4"}   # private for any host
        ok, why = addon.resolved_addresses_ok("api.private-cluster.internal")
        assert ok and why == "kube-exempt"
        ok2, _ = addon.resolved_addresses_ok("sneaky.internal.test")
        assert not ok2

    def test_ip_guard_exempts_every_configured_cluster_host(self):
        # #57: each configured cluster host is exempt; a non-cluster private
        # host is still denied.
        addon = load_addon()
        addon.KUBE_API_HOSTS = frozenset({"api.prod.internal", "api.staging.internal"})
        addon._resolver = lambda h: {"10.9.0.7"}
        for host in ("api.prod.internal", "api.staging.internal"):
            ok, why = addon.resolved_addresses_ok(host)
            assert ok and why == "kube-exempt"
        assert not addon.resolved_addresses_ok("other.internal.test")[0]

    def test_no_exemption_when_kube_broker_inactive(self):
        addon = load_addon()
        addon.KUBE_API_HOSTS = frozenset()
        addon._resolver = lambda h: {"10.12.0.4"}
        ok, _ = addon.resolved_addresses_ok("api.private-cluster.internal")
        assert not ok   # no kube broker -> guard applies normally

    def test_injects_master_key_toward_gateway_only(self):
        addon = load_addon()
        addon.GATEWAY_HOST = "tjor-gateway"
        addon.GATEWAY_KEY = "sk-tjor-REALKEY"
        f = _GwFlow("tjor-gateway", {"authorization": "Bearer placeholder"})
        addon._apply_gateway(f)
        assert f.request.headers["authorization"] == "Bearer sk-tjor-REALKEY"
        g = _GwFlow("api.example.com", {"authorization": "Bearer placeholder"})
        addon._apply_gateway(g)
        assert g.request.headers["authorization"] == "Bearer placeholder"   # untouched elsewhere

    def test_strips_placeholder_when_key_missing(self):
        addon = load_addon()
        addon.GATEWAY_HOST = "tjor-gateway"
        addon.GATEWAY_KEY = ""
        f = _GwFlow("tjor-gateway", {"authorization": "Bearer placeholder"})
        addon._apply_gateway(f)
        assert "authorization" not in f.request.headers   # fail-closed strip


class TestPinSelection:
    """Deterministic pin choice from a validated address set (#41): resolver
    order is unstable, so the pinned address must be reproducible."""

    def test_prefers_ipv4_over_ipv6(self):
        addon = load_addon()
        picked = addon._pick_pinned(frozenset({"2606:2800:220::1", "93.184.216.34"}))
        assert picked == "93.184.216.34"

    def test_ipv6_only_set_pins_ipv6(self):
        addon = load_addon()
        picked = addon._pick_pinned(frozenset({"2606:2800:220::1", "2606:2800:220::2"}))
        assert picked == "2606:2800:220::1"  # lexicographic within a version

    def test_multiple_ipv4_lexicographic(self):
        addon = load_addon()
        picked = addon._pick_pinned(frozenset({"93.184.216.34", "93.184.216.5", "1.2.3.4"}))
        assert picked == "1.2.3.4"

    def test_single_address(self):
        addon = load_addon()
        assert addon._pick_pinned(frozenset({"140.82.121.3"})) == "140.82.121.3"

    def test_empty_set_is_none(self):
        addon = load_addon()
        assert addon._pick_pinned(frozenset()) is None


class TestServerConnectPin:
    """The resolve-and-pin server_connect hook (#41), driven through the real
    mitmproxy ServerConnectionHookData the proxy passes it."""

    def _hookdata(self, host, port=443):
        pytest.importorskip("mitmproxy")
        from mitmproxy import connection
        from mitmproxy.proxy import server_hooks

        server = connection.Server(address=(host, port))
        client = connection.Client(peername=("10.0.0.2", 5555), sockname=("10.0.0.1", 8080))
        return server_hooks.ServerConnectionHookData(server=server, client=client)

    def _addon(self):
        addon = load_addon()
        addon._IP_GUARD = True
        return addon

    def test_rebinding_flip_between_check_and_connect_cannot_redirect(self, capsys):
        # The #41 TOCTOU: public at verdict time, private at connect time.
        addon = self._addon()
        addon.DENIAL_LOG = ""  # denial goes to the (unset) log; we assert on address/error
        seq = iter([{"93.184.216.34"}, {"10.0.0.5"}])

        def flipping(host):
            try:
                return next(seq)
            except StopIteration:
                return {"10.0.0.5"}

        # First resolution (verdict path) sees public and caches the validated
        # set. allowed.test is policy-allowed, so the verdict reaches the guard.
        addon._resolver = flipping
        assert addon.connect_verdict("allowed.test").allowed
        # Now the pin hook runs; even though DNS has since flipped to private,
        # the pin must land on the validated public address — never 10.0.0.5.
        data = self._hookdata("allowed.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error is None
        assert data.server.address == ("93.184.216.34", 443)

    def test_private_at_connect_kills_and_logs(self, tmp_path):
        addon = self._addon()
        log = tmp_path / "denials.log"
        addon.DENIAL_LOG = str(log)
        addon._resolver = lambda host: {"10.0.0.5"}
        data = self._hookdata("sneaky.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error and "ip-guard" in data.server.error
        assert data.server.address == ("sneaky.test", 443)  # never rewritten to the private IP
        assert "ip-guard-pin" in log.read_text()

    def test_pin_rewrites_address_preserves_port_and_leaves_sni(self):
        addon = self._addon()
        addon._resolver = lambda host: {"140.82.121.3"}
        data = self._hookdata("allowed.test", port=8443)
        assert data.server.sni is None
        addon.TjorPolicy().server_connect(data)
        assert data.server.address == ("140.82.121.3", 8443)
        assert data.server.sni is None  # the addon never touches SNI

    def test_guard_off_does_not_pin(self):
        addon = self._addon()
        addon._IP_GUARD = False
        addon._resolver = lambda host: {"10.0.0.5"}
        data = self._hookdata("allowed.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error is None
        assert data.server.address == ("allowed.test", 443)

    def test_gateway_and_kube_exempt_hosts_not_pinned(self):
        addon = self._addon()
        addon._resolver = lambda host: {"172.20.0.5"}
        addon.GATEWAY_HOST = "tjor-gateway"
        addon.KUBE_API_HOSTS = frozenset({"api.prod.internal", "api.staging.internal"})
        for host in ("tjor-gateway", "api.prod.internal", "api.staging.internal"):
            data = self._hookdata(host)
            addon.TjorPolicy().server_connect(data)
            assert data.server.error is None
            assert data.server.address == (host, 443)  # unpinned, live docker DNS

    def test_ip_literal_destination_not_pinned(self):
        addon = self._addon()
        addon._resolver = lambda host: (_ for _ in ()).throw(AssertionError("must not resolve literals"))
        data = self._hookdata("140.82.121.3")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error is None
        assert data.server.address == ("140.82.121.3", 443)

    def test_unresolvable_host_left_unpinned(self):
        addon = self._addon()
        addon._resolver = lambda host: (_ for _ in ()).throw(OSError("NXDOMAIN"))
        data = self._hookdata("nonexistent.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error is None
        assert data.server.address == ("nonexistent.test", 443)  # mitmproxy's own resolve fails later

    def test_resolver_exception_fails_closed(self):
        addon = self._addon()

        def boom(host):
            raise RuntimeError("resolver blew up")

        addon._resolver = boom
        # _validated_addresses catches OSError only; a RuntimeError propagates
        # into the hook, whose fail-closed wrapper must kill the connection.
        data = self._hookdata("allowed.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error and "fail-closed" in data.server.error
        assert data.server.address == ("allowed.test", 443)
