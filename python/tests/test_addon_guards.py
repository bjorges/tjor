"""Tests for the proxy addon's fail-closed wrapper and resolved-address
(DNS-rebind/SSRF) guard — imported without mitmproxy, like the parity suite."""

import importlib.util
import sys
from pathlib import Path

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
        for _ in range(200):
            addon._log_stripped("h.test", {"x-agent-session-id": "x"})
        lines = capsys.readouterr().err.strip().splitlines()
        assert 20 <= len(lines) <= 22  # first 20 + every 100th, not 200

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
