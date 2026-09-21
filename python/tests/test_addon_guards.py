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

    def test_unresolvable_fails_closed(self):
        # #6-review remediation: an unresolvable host is DENIED, not permitted.
        # The guard has no address to validate or pin, and permitting it would
        # leave server_connect unpinned so mitmproxy resolves independently — the
        # #41 rebind vector. (Was permitted pre-fix; a black-holed allowed host
        # under the #61 RES_OPTIONS bound reaches this path in ~2s.)
        addon = load_addon()
        addon._resolver = self.bad
        ok, why = addon.resolved_addresses_ok("allowed.test")
        assert not ok and why == "unresolvable"
        # ...so the policy verdict is now a fail-closed ip-guard deny
        assert not addon.connect_verdict("allowed.test").allowed

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

    def test_agent_reason_takes_the_class_token(self):
        # Structural: the class is the first whitespace-delimited token; the
        # operator detail (after the space) is dropped. Rewording the detail
        # cannot change the class (the #60-review fragility fix).
        addon = load_addon()
        assert addon._agent_reason("non-global-address 10.0.0.5") == "non-global-address"
        assert addon._agent_reason("non-global-address fd00::1 (embeds 10.0.0.5)") == "non-global-address"
        assert addon._agent_reason("unparseable-address 'weird'") == "unparseable-address"

    def test_agent_reason_passes_through_literal_free(self):
        addon = load_addon()
        for why in ("resolve-timeout", "resolve-capacity", "unresolvable", "gateway-exempt", "kube-exempt"):
            assert addon._agent_reason(why) == why

    def test_agent_reason_is_structural_not_wording_dependent(self):
        # The exact detail wording is irrelevant — only the first token matters,
        # so a future reword of _address_public's detail can't re-leak an IP.
        addon = load_addon()
        for detail in ("10.0.0.5", "totally reworded 10.0.0.5 blah", "169.254.169.254 (embeds x)"):
            out = addon._agent_reason(f"non-global-address {detail}")
            assert out == "non-global-address" and "." not in out

    def test_agent_rule_handles_ip_guard_prefix_and_others(self):
        addon = load_addon()
        assert addon._agent_rule("ip-guard:non-global-address 10.0.0.5") == "ip-guard:non-global-address"
        assert addon._agent_rule("ip-guard:resolve-timeout") == "ip-guard:resolve-timeout"
        # non-guard rules (policy blocks / default-deny) are the agent's own
        # request and pass through unchanged
        assert addon._agent_rule("default-deny") == "default-deny"
        assert addon._agent_rule("block:host") == "block:host"

    def test_no_ip_literal_reaches_the_agent(self):
        addon = load_addon()
        rule = "ip-guard:non-global-address 10.0.0.5"
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
    event loop (#59). Both transient failures fail CLOSED: a hang (resolve-timeout)
    and an unresolvable/black-hole (OSError). The security result no longer
    depends on WHICH timeout fires first (#6-review remediation)."""

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

    def test_timeout_negative_cached_then_recovers(self):
        # A timed-out host is briefly negative-cached (so repeat hits don't
        # re-consume a worker), and once the window expires it recovers on a
        # fresh resolution — a transient stall never poisons the host forever
        # (#59 re-review; reverses #59's original "never cached").
        import threading
        gate = threading.Event()
        addon = self._hanging_addon(gate)
        addon._RESOLVE_NEGATIVE_TTL = 60.0  # keep it cached for the within-window check
        try:
            ok, why, _ = addon._validated_addresses("flaky.test")
            assert not ok and why == "resolve-timeout"
        finally:
            gate.set()
        # DNS has recovered, but within the negative window the guard serves the
        # cached denial WITHOUT resolving again (resolver must not be called).
        addon._resolver = lambda host: (_ for _ in ()).throw(AssertionError("must not re-resolve within the negative window"))
        ok_w, why_w, _ = addon._validated_addresses("flaky.test")
        assert not ok_w and why_w == "resolve-timeout"
        # Once the window expires, the host is re-evaluated fresh and recovers.
        addon._RESOLVE_NEGATIVE_TTL = -1.0  # force the negative entry expired
        addon._resolver = lambda host: {"140.82.121.3"}
        ok2, why2, _ = addon._validated_addresses("flaky.test")
        assert ok2 and why2 == ""

    def test_fast_unresolvable_fails_closed(self):
        # #6-review: a fast OSError (a black-hole giving up quickly under the #61
        # RES_OPTIONS bound, or a genuine NXDOMAIN) now DENIES — the same
        # fail-closed result as a hang, so the outcome no longer depends on
        # whether the OS resolver or the addon timeout fires first.
        addon = load_addon()
        def boom(host):
            raise OSError("NXDOMAIN")  # fast failure, not a hang
        addon._resolver = boom
        ok, why = addon.resolved_addresses_ok("nonexistent.test")
        assert not ok and why == "unresolvable"

    def test_unresolvable_negative_cached_then_recovers(self):
        # Mirrors the timeout negative-cache: a black-holed allowed host is denied
        # from cache for the short window (so it doesn't re-consume a worker each
        # request — the pool-pressure angle #61 cared about), and recovers on a
        # fresh resolution once the window expires and DNS comes back.
        addon = load_addon()
        addon._RESOLVE_NEGATIVE_TTL = 60.0
        addon._resolver = lambda host: (_ for _ in ()).throw(OSError("EAI_AGAIN"))
        ok, why, _ = addon._validated_addresses("blackhole.test")
        assert not ok and why == "unresolvable"
        # Within the window: served from cache, resolver must NOT be called again.
        addon._resolver = lambda host: (_ for _ in ()).throw(AssertionError("must not re-resolve within the negative window"))
        ok_w, why_w, _ = addon._validated_addresses("blackhole.test")
        assert not ok_w and why_w == "unresolvable"
        # Window expired + DNS recovered -> re-evaluated fresh and permitted.
        addon._RESOLVE_NEGATIVE_TTL = -1.0
        addon._resolver = lambda host: {"140.82.121.3"}
        ok2, why2, _ = addon._validated_addresses("blackhole.test")
        assert ok2 and why2 == ""


class TestPoolAvailability:
    """One slow host must not exhaust resolution capacity for others (#59
    re-review). Driven deterministically by seeding _inflight, since the addon's
    hooks run serially on the event loop (no real concurrency to race)."""

    def test_coalesces_onto_existing_inflight_resolution(self):
        import concurrent.futures
        addon = load_addon()
        addon._RESOLVE_TIMEOUT = 0.2
        calls = []
        addon._resolver = lambda h: calls.append(h) or {"1.2.3.4"}
        stuck = concurrent.futures.Future()          # a resolution already in flight
        addon._inflight = {"slow.test": stuck}
        try:
            ok, why, _ = addon._validated_addresses("slow.test")
            # waited on the EXISTING future (timed out); did NOT submit a new worker
            assert not ok and why == "resolve-timeout"
            assert calls == []
        finally:
            stuck.cancel()

    def test_one_stuck_host_leaves_capacity_for_others(self):
        import concurrent.futures
        addon = load_addon()
        addon._RESOLVE_MAX_INFLIGHT = 8
        addon._resolver = lambda h: {"140.82.121.3"}
        stuck = concurrent.futures.Future()
        addon._inflight = {"stuck.test": stuck}      # one host stuck, cap not reached
        try:
            ok, why, _ = addon._validated_addresses("fast.test")
            assert ok and why == ""                  # a different host still resolves
        finally:
            stuck.cancel()

    def test_negative_cache_expired_entry_gets_fresh_window(self):
        # review v0.18.9 item 1: a re-timeout for a host whose negative entry has
        # already EXPIRED must start a FRESH window (fresh ts), not re-inherit the
        # stale timestamp — otherwise a persistently-failing host stays perpetually
        # expired and re-resolves on every request, silently defeating the DoS
        # guard. (Within a LIVE window, coalesced waiters still preserve the ts so
        # the window isn't extended — see TestNegativeCacheWindow.)
        import concurrent.futures, time as _t
        addon = load_addon()
        addon._RESOLVE_TIMEOUT = 0.2
        addon._RESOLVE_NEGATIVE_TTL = 0.05  # tiny: the seeded entry is already expired
        old_ts = _t.monotonic() - 10.0
        addon._ip_cache["slow.test"] = addon._CacheEntry(old_ts, False, "resolve-timeout", frozenset())
        stuck = concurrent.futures.Future()
        addon._inflight = {"slow.test": stuck}   # still hung -> this attempt also times out
        try:
            before = _t.monotonic()
            ok, why, _ = addon._validated_addresses("slow.test")
            assert not ok and why == "resolve-timeout"
            # ts refreshed to ~now (not stuck at the stale old_ts) -> the entry
            # suppresses re-resolution again for a fresh window.
            assert addon._ip_cache["slow.test"].ts >= before
        finally:
            stuck.cancel()

    def test_cap_fails_fast_when_saturated(self):
        import concurrent.futures, time as _t
        addon = load_addon()
        addon._RESOLVE_MAX_INFLIGHT = 2
        addon._RESOLVE_TIMEOUT = 5.0                  # would be a long stall if it queued
        f1, f2 = concurrent.futures.Future(), concurrent.futures.Future()
        addon._inflight = {"a.slow": f1, "b.slow": f2}   # saturated
        addon._resolver = lambda h: pytest.fail("must not submit when capacity is saturated")
        try:
            start = _t.monotonic()
            ok, why, _ = addon._validated_addresses("c.new")
            elapsed = _t.monotonic() - start
            assert not ok and why == "resolve-capacity"
            assert elapsed < 1.0, f"capacity denial took {elapsed:.2f}s — it queued instead of failing fast"
        finally:
            f1.cancel(); f2.cancel()

    def test_saturation_emits_rate_limited_operator_signal(self, capsys):
        # #61: cap saturation surfaces a rate-limited, sanitized stderr line —
        # bounded (first-N/every-Nth), not one per call, host escape-sanitized.
        import concurrent.futures
        addon = load_addon()
        addon._RESOLVE_MAX_INFLIGHT = 1
        addon._resolve_saturation_count = 0
        stuck = concurrent.futures.Future()
        addon._inflight = {"stuck.host": stuck}   # saturated at cap=1
        try:
            capsys.readouterr()  # drain import-time stderr
            for _ in range(150):
                ok, why, _ = addon._validated_addresses("evil\x1b]0;x\x07.test")
                assert not ok and why == "resolve-capacity"
            err = capsys.readouterr().err
            lines = [l for l in err.splitlines() if "resolver capacity saturated" in l]
            # first 20 + #100 == 21 lines for 150 hits (rate-limited, not 150)
            assert len(lines) == 21, f"expected 21 rate-limited lines, got {len(lines)}"
            assert "\x1b" not in err                 # host escape-sanitized
            assert "?" in lines[0]                    # the sanitized host is shown
        finally:
            stuck.cancel()


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

    def test_denial_log_redacts_discovered_secret(self, tmp_path):
        # #6 proof: a secret quoted into an attacker-influenced denial value must
        # not be persisted in the clear. _log_denial redacts before it writes.
        addon = load_addon()
        log = tmp_path / "denials.log"
        addon.DENIAL_LOG = str(log)
        addon._denial_log_count = 0
        token = "ghp_" + "a" * 36
        addon._log_denial(f"exfil.test/?leak={token}", "default-deny")
        contents = log.read_text()
        assert token not in contents                 # the secret never hits disk
        assert "[redacted:github-token]" in contents  # replaced in place
        assert "exfil.test" in contents               # the rest of the line survives
        assert "default-deny" in contents             # rule column intact


class TestDenyHooksFailClosed:
    """The #6-review Critical: _log_denial runs INSIDE the deny hooks before the
    403 is set, and a mitmproxy hook exception is logged but does not re-run the
    hook — so a throw there must NOT skip enforcement. The hooks now fail closed."""

    def _flow(self, host="blocked.test"):
        import types
        from mitmproxy.http import Headers
        return types.SimpleNamespace(
            request=types.SimpleNamespace(host=host,
                                          pretty_url=f"https://{host}/x",
                                          headers=Headers()),
            response=None)

    def test_log_denial_is_total_even_if_redact_throws(self, tmp_path, monkeypatch):
        # redact() is total, but _log_denial must swallow ANY failure regardless.
        # (monkeypatch, not direct assignment: tjor_secrets is a shared module.)
        addon = load_addon()
        addon.DENIAL_LOG = str(tmp_path / "denials.log")
        addon._denial_log_count = 0
        monkeypatch.setattr(addon.tjor_secrets, "redact",
                            lambda s: (_ for _ in ()).throw(RecursionError("boom")))
        addon._log_denial("blocked.test", "default-deny")  # must NOT raise

    def test_request_denies_even_if_log_denial_throws(self):
        # The bypass regression: a denied request whose _log_denial throws must
        # STILL get a 403 — never forwarded to its real destination. blocked.test
        # is default-denied at the request stage by the fixture policy.
        pytest.importorskip("mitmproxy")
        addon = load_addon()
        addon._log_denial = lambda *a, **k: (_ for _ in ()).throw(RecursionError("boom"))
        flow = self._flow()
        addon.TjorPolicy().request(flow)
        assert flow.response is not None and flow.response.status_code == 403
        assert flow.response.headers["x-tjor-rule"] == "fail-closed:hook-error"

    def test_http_connect_denies_even_if_log_denial_throws(self):
        # The fixture allows CONNECT to allowed.test but the IP guard denies it
        # when it resolves to a private address — a real connect-stage deny.
        pytest.importorskip("mitmproxy")
        addon = load_addon()
        addon._resolver = lambda host: {"10.0.0.5"}  # allowed host resolves private -> deny
        addon._log_denial = lambda *a, **k: (_ for _ in ()).throw(RecursionError("boom"))
        flow = self._flow("allowed.test")
        addon.TjorPolicy().http_connect(flow)
        assert flow.response is not None and flow.response.status_code == 403
        assert flow.response.headers["x-tjor-rule"] == "fail-closed:hook-error"

    def test_normal_denial_still_sets_rule_and_403(self):
        # The guard must not change the happy-path deny (rule preserved, 403 set).
        pytest.importorskip("mitmproxy")
        addon = load_addon()
        addon._resolver = lambda host: {"10.0.0.5"}
        flow = self._flow("allowed.test")
        addon.TjorPolicy().http_connect(flow)
        assert flow.response.status_code == 403
        assert flow.response.headers["x-tjor-rule"] != "fail-closed:hook-error"

    def test_response_set_even_if_stderr_logging_fails(self, monkeypatch):
        # review v0.18.9 item 2: the fail-closed 403 is assigned BEFORE the
        # diagnostic log, so a failure in stderr I/O can't leave it un-denied.
        pytest.importorskip("mitmproxy")
        addon = load_addon()
        addon._log_denial = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("body boom"))
        monkeypatch.setattr("builtins.print",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("stderr boom")))
        flow = self._flow()  # blocked.test -> request-stage deny
        addon.TjorPolicy().request(flow)  # must not raise
        assert flow.response is not None and flow.response.status_code == 403


class TestNegativeCacheWindow:
    """review v0.18.9 item 1: timestamp preservation must not leave a
    persistently-failing host perpetually expired (which would silently defeat
    the negative-cache DoS guard for it)."""

    def test_fresh_window_after_expiry(self):
        addon = load_addon()
        addon._RESOLVE_NEGATIVE_TTL = 5.0
        addon._negative_cache("h.test", "unresolvable", 0.0)
        assert addon._ip_cache["h.test"].ts == 0.0
        # Re-cache AFTER the window expired -> a FRESH timestamp, not stuck at 0.
        addon._negative_cache("h.test", "unresolvable", 100.0)
        assert addon._ip_cache["h.test"].ts == 100.0

    def test_coalesced_within_window_preserves_timestamp(self):
        # A near-simultaneous coalesced failure keeps the original window start,
        # so waiters can't push the window past the TTL (@homer edge case).
        addon = load_addon()
        addon._RESOLVE_NEGATIVE_TTL = 5.0
        addon._negative_cache("h.test", "resolve-timeout", 10.0)
        addon._negative_cache("h.test", "resolve-timeout", 10.5)
        assert addon._ip_cache["h.test"].ts == 10.0


class TestLogVolume:
    """Workload-log read-volume counter (#50): observability only. Counts
    pods/log bytes on a configured cluster API host, streaming-aware, never
    altering the body, fail-safe."""

    KUBE = "api.cluster.internal"

    def _addon(self, tmp_path):
        addon = load_addon()
        addon.KUBE_API_HOSTS = frozenset({self.KUBE})
        addon.LOG_VOLUME_LOG = str(tmp_path / "logvolume.log")
        addon._log_volume_count = 0
        return addon

    def _flow(self, host, path, status=200):
        import types
        return types.SimpleNamespace(
            request=types.SimpleNamespace(host=host, path=path),
            response=types.SimpleNamespace(status_code=status, stream=None))

    def test_matches_pods_log_only_on_kube_host(self):
        addon = load_addon()
        addon.KUBE_API_HOSTS = frozenset({self.KUBE})
        assert addon._pods_log_pod(self.KUBE, "/api/v1/namespaces/ns/pods/web-7/log") == "web-7"
        assert addon._pods_log_pod(self.KUBE, "/api/v1/namespaces/ns/pods/web-7/log?follow=true&container=c") == "web-7"
        assert addon._pods_log_pod(self.KUBE, "/api/v1/namespaces/ns/pods/web-7/status") is None
        assert addon._pods_log_pod(self.KUBE, "/api/v1/nodes") is None
        assert addon._pods_log_pod("other.host", "/api/v1/namespaces/ns/pods/web-7/log") is None  # non-kube host

    def test_counts_and_returns_body_unchanged(self, tmp_path):
        addon = self._addon(tmp_path)
        flow = self._flow(self.KUBE, "/api/v1/namespaces/ns/pods/mypod/log")
        addon.TjorPolicy().responseheaders(flow)
        assert callable(flow.response.stream)  # passthrough installed
        # Drive the stream: chunks returned identical, tallied on the way.
        assert flow.response.stream(b"hello ") == b"hello "
        assert flow.response.stream(b"world") == b"world"
        assert flow.response.stream(b"") == b""   # end-of-stream flush
        assert (tmp_path / "logvolume.log").read_text() == "mypod\t11\n"

    def test_streamed_multichunk_fully_counted(self, tmp_path):
        addon = self._addon(tmp_path)
        flow = self._flow(self.KUBE, "/api/v1/namespaces/ns/pods/streamer/log?follow=true")
        addon.TjorPolicy().responseheaders(flow)
        for chunk in (b"a" * 1000, b"b" * 2000, b"c" * 500):
            assert flow.response.stream(chunk) == chunk
        flow.response.stream(b"")
        assert (tmp_path / "logvolume.log").read_text() == "streamer\t3500\n"

    def test_non_log_and_non_kube_not_counted(self, tmp_path):
        addon = self._addon(tmp_path)
        for host, path in ((self.KUBE, "/api/v1/nodes"),
                           ("other.host", "/api/v1/namespaces/ns/pods/p/log")):
            flow = self._flow(host, path)
            addon.TjorPolicy().responseheaders(flow)
            assert flow.response.stream is None  # no passthrough installed
        assert not (tmp_path / "logvolume.log").exists() or (tmp_path / "logvolume.log").read_text() == ""

    def test_non_2xx_log_read_not_counted(self, tmp_path):
        addon = self._addon(tmp_path)
        flow = self._flow(self.KUBE, "/api/v1/namespaces/ns/pods/denied/log", status=403)
        addon.TjorPolicy().responseheaders(flow)
        assert flow.response.stream is None  # a 403 read no log content

    def test_counting_is_failsafe(self, tmp_path, monkeypatch):
        # If the sink throws, the stream passthrough must still return the chunk
        # unchanged and never raise — observability can't corrupt a response.
        addon = self._addon(tmp_path)
        monkeypatch.setattr(addon, "_record_log_volume",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        flow = self._flow(self.KUBE, "/api/v1/namespaces/ns/pods/p/log")
        addon.TjorPolicy().responseheaders(flow)
        assert flow.response.stream(b"data") == b"data"
        assert flow.response.stream(b"") == b""  # flush throws internally, swallowed

    def test_hook_outer_exception_is_swallowed(self, tmp_path, monkeypatch):
        # The hook's OUTER guard: if matching itself throws (before a stream is
        # installed), the response must be untouched and no exception escapes.
        addon = self._addon(tmp_path)
        monkeypatch.setattr(addon, "_pods_log_pod",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        flow = self._flow(self.KUBE, "/api/v1/namespaces/ns/pods/p/log")
        addon.TjorPolicy().responseheaders(flow)  # must not raise
        assert flow.response.stream is None        # no passthrough installed; body untouched

    def test_zero_byte_read_records_nothing(self, tmp_path):
        addon = self._addon(tmp_path)
        flow = self._flow(self.KUBE, "/api/v1/namespaces/ns/pods/empty/log")
        addon.TjorPolicy().responseheaders(flow)
        assert flow.response.stream(b"") == b""
        assert not (tmp_path / "logvolume.log").exists() or (tmp_path / "logvolume.log").read_text() == ""


class TestEgressSecretTripwire:
    """#62 observe-only tripwire: scan outbound inference bodies for known secret
    shapes and record a signal (count + kinds, never the value); never alter,
    block, or deny; bounded; fail-safe."""

    GW = "tjor-gateway"
    TOKEN = "ghp_" + "a" * 36

    def _addon(self, tmp_path):
        addon = load_addon()
        addon.SCAN_HOSTS = frozenset({self.GW})
        addon.SECRET_SCAN_LOG = str(tmp_path / "secretscan.log")
        addon._secret_scan_count = 0
        return addon

    def _flow(self, host, body):
        import types
        return types.SimpleNamespace(request=types.SimpleNamespace(host=host, content=body))

    def test_secret_body_recorded_and_body_unchanged(self, tmp_path):
        addon = self._addon(tmp_path)
        body = f'{{"prompt":"my key is {self.TOKEN}"}}'.encode()
        flow = self._flow(self.GW, body)
        addon._scan_request_body(flow)
        assert flow.request.content == body                     # never mutated
        contents = (tmp_path / "secretscan.log").read_text()
        assert "github-token" in contents and self.GW in contents

    def test_signal_never_contains_the_value(self, tmp_path):
        addon = self._addon(tmp_path)
        addon._scan_request_body(self._flow(self.GW, f"leak={self.TOKEN}".encode()))
        assert self.TOKEN not in (tmp_path / "secretscan.log").read_text()  # kind only, never the value

    def test_non_scan_host_not_scanned(self, tmp_path):
        addon = self._addon(tmp_path)
        addon._scan_request_body(self._flow("api.example.com", f"x {self.TOKEN}".encode()))
        assert not (tmp_path / "secretscan.log").exists() or (tmp_path / "secretscan.log").read_text() == ""

    def test_bounded_to_max_bytes(self, tmp_path):
        addon = self._addon(tmp_path)
        addon.SCAN_MAX_BYTES = 10                                # secret sits past the cap
        addon._scan_request_body(self._flow(self.GW, (b"x" * 50) + self.TOKEN.encode()))
        assert not (tmp_path / "secretscan.log").exists() or (tmp_path / "secretscan.log").read_text() == ""

    def test_streamed_or_empty_body_forwarded_unscanned(self, tmp_path):
        addon = self._addon(tmp_path)
        addon._scan_request_body(self._flow(self.GW, None))      # streamed past stream_large_bodies
        addon._scan_request_body(self._flow(self.GW, b""))       # empty
        assert not (tmp_path / "secretscan.log").exists() or (tmp_path / "secretscan.log").read_text() == ""

    def test_scan_is_failsafe(self, tmp_path, monkeypatch):
        # A raising detector must not propagate out of the scan.
        addon = self._addon(tmp_path)
        monkeypatch.setattr(addon.tjor_secrets, "kinds_present",
                            lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
        addon._scan_request_body(self._flow(self.GW, f"x {self.TOKEN}".encode()))  # must NOT raise

    def test_scan_never_denies_a_legitimate_request(self, monkeypatch):
        # The scan sits in the fail-closed request hook. Even if scanning throws,
        # an ALLOWED request must be forwarded (flow.response stays None), NOT 403'd.
        pytest.importorskip("mitmproxy")
        import types
        from mitmproxy.http import Headers
        addon = load_addon()
        addon.SCAN_HOSTS = frozenset({"allowed.test"})
        addon._resolver = lambda host: {"140.82.121.3"}          # allowed.test resolves public -> allowed
        monkeypatch.setattr(addon.tjor_secrets, "kinds_present",
                            lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
        flow = types.SimpleNamespace(
            request=types.SimpleNamespace(host="allowed.test", port=443,
                                          pretty_url="https://allowed.test/v1/x",
                                          headers=Headers(), content=f"k={self.TOKEN}".encode()),
            response=None)
        addon.TjorPolicy().request(flow)
        assert flow.response is None                             # forwarded, never denied by a scan error


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

    def test_pin_kill_redacts_non_global_reason_from_agent(self, tmp_path):
        # #60 coverage gap (@homer): the pin-kill path's agent-facing error for
        # a NON-GLOBAL reason must omit the resolved IP, while the operator log
        # keeps it. (The earlier pin tests only exercised resolve-timeout.)
        addon = self._addon()
        log = tmp_path / "denials.log"
        addon.DENIAL_LOG = str(log)
        addon._resolver = lambda host: {"10.0.0.5"}   # allowed host resolves private
        data = self._hookdata("allowed.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error and "non-global-address" in data.server.error
        assert "10.0.0.5" not in data.server.error    # agent gets the class only
        assert "10.0.0.5" in log.read_text()          # operator log keeps the address

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

    def test_unresolvable_host_fails_closed_at_pin(self):
        # #6-review remediation: an unresolvable host must NOT be left unpinned —
        # that let mitmproxy do its own unguarded resolution (the #41 rebind
        # vector). The pin hook now kills the connection instead.
        addon = self._addon()
        addon._resolver = lambda host: (_ for _ in ()).throw(OSError("NXDOMAIN"))
        data = self._hookdata("nonexistent.test")
        addon.TjorPolicy().server_connect(data)
        assert data.server.error and "ip-guard" in data.server.error
        assert data.server.address == ("nonexistent.test", 443)  # never rewritten; connection killed

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
