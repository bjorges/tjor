"""Tests for the single config merge path and the Corefile generator."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gen_corefile
import tjor_cfg
import tjor_policy as tp


class TestConfigMerge:
    def test_deep_merge_tables_and_scalars(self):
        base = {"a": {"x": 1, "y": 2}, "b": 1, "c": [1, 2]}
        override = {"a": {"y": 9, "z": 3}, "c": [7]}
        merged = tjor_cfg.deep_merge(base, override)
        assert merged == {"a": {"x": 1, "y": 9, "z": 3}, "b": 1, "c": [7]}

    def test_user_layer_wins(self, tmp_path, monkeypatch):
        user = tmp_path / "config.toml"
        user.write_text('[proxy]\nport = 9999\n')
        monkeypatch.setenv("TJOR_USER_CONFIG", str(user))
        config = tjor_cfg.effective()
        assert tjor_cfg.get(config, "proxy.port") == 9999
        # untouched defaults survive the merge
        assert tjor_cfg.get(config, "versions.opencode")

    def test_defaults_only(self, monkeypatch):
        monkeypatch.setenv("TJOR_USER_CONFIG", "/nonexistent/config.toml")
        config = tjor_cfg.effective()
        assert tjor_cfg.get(config, "proxy.port") == 8080
        assert tjor_cfg.get(config, "images.mitmproxy", "").startswith("mitmproxy/")

    def test_get_missing_returns_default(self):
        assert tjor_cfg.get({}, "no.such.key", "fallback") == "fallback"

    def test_broken_user_config_is_a_clean_hard_error(self, tmp_path, monkeypatch):
        import pytest

        user = tmp_path / "config.toml"
        user.write_text("[proxy\nbroken")
        monkeypatch.setenv("TJOR_USER_CONFIG", str(user))
        with pytest.raises(SystemExit) as exc:
            tjor_cfg.effective()
        assert "invalid TOML" in str(exc.value)


class TestCorefile:
    def test_zones_derived_from_allow_list(self):
        policy = tp.parse_policy(
            'mode = "strict-allow"\n[hosts]\nallow = ["github.com", "*.github.com", "pypi.org"]\nblock = []'
        )
        zones, warnings = gen_corefile.zones_from_policy(policy, [])
        assert zones == ["github.com", "pypi.org"]
        assert not warnings

    def test_unscopable_pattern_stays_closed_with_warning(self):
        policy = tp.parse_policy('mode = "strict-allow"\n[hosts]\nallow = ["git*.example.com"]')
        zones, warnings = gen_corefile.zones_from_policy(policy, [])
        assert zones == []
        assert any("cannot zone-scope" in w for w in warnings)

    def test_invalid_policy_forwards_nothing(self):
        policy = tp.parse_policy("mode = [broken")
        zones, warnings = gen_corefile.zones_from_policy(policy, ["github.com"])
        assert zones == [] and any("fail-closed" in w for w in warnings)

    def test_default_allow_uses_extra_zones_only(self):
        policy = tp.parse_policy('mode = "default-allow"\n[hosts]\nallow = ["ignored.example"]')
        zones, _ = gen_corefile.zones_from_policy(policy, ["corp.example"])
        assert zones == ["corp.example"]

    def test_render_always_has_nxdomain_catchall(self):
        out = gen_corefile.render(["github.com"])
        assert "github.com:53" in out and "forward . /etc/resolv.conf" in out
        assert "rcode NXDOMAIN" in out
        empty = gen_corefile.render([])
        assert "forward" not in empty and "rcode NXDOMAIN" in empty
