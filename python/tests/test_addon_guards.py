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
        addon.BROKER_HOSTS = addon.tjor_identity.parse_inject_hosts(source_hosts)
        addon.BROKER = tb.BrokerState({"source": "pat", "token": cred}, clock=lambda: 0.0) if cred else None
        return addon

    def test_authorization_injected_for_destination(self):
        addon = self.make()
        assert addon.broker_authorization("github.com") == "token tok-123"
        assert addon.broker_authorization("api.github.com") is None  # not in hosts here
        assert addon.broker_authorization("evil.test") is None

    def test_disabled_when_no_broker(self):
        addon = self.make(cred=None)
        assert addon.broker_authorization("github.com") is None

    def test_apply_broker_replaces_placeholder(self):
        pytest.importorskip("mitmproxy")
        import types
        from mitmproxy.http import Headers

        addon = self.make()
        flow = types.SimpleNamespace(request=types.SimpleNamespace(
            host="github.com",
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
            host="github.com",
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
            host="other.test",
            headers=Headers([(b"authorization", b"Bearer agent-own")]),
        ))
        addon._apply_broker(flow)
        assert flow.request.headers["authorization"] == "Bearer agent-own"


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
