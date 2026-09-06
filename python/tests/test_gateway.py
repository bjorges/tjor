"""LLM gateway (D4) host-side helpers: the per-install master key (generated,
0600, reused, never in the rendered config) and the LiteLLM config render (no
secret literals)."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_gateway


class TestMasterKey:
    def test_generated_then_reused(self, tmp_path):
        f = tmp_path / "gw.key"
        k1 = tjor_gateway.ensure_master_key(f)
        assert k1.startswith(tjor_gateway.MASTER_KEY_PREFIX)
        assert len(k1) > 20
        k2 = tjor_gateway.ensure_master_key(f)
        assert k2 == k1  # stable across calls (per-install, not per-session)

    def test_persisted_0600(self, tmp_path):
        f = tmp_path / "gw.key"
        tjor_gateway.ensure_master_key(f)
        mode = stat.S_IMODE(f.stat().st_mode)
        assert mode == 0o600

    def test_unique_per_install(self, tmp_path):
        a = tjor_gateway.ensure_master_key(tmp_path / "a.key")
        b = tjor_gateway.ensure_master_key(tmp_path / "b.key")
        assert a != b  # CSPRNG

    def test_path_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TJOR_GATEWAY_KEY_FILE", str(tmp_path / "override.key"))
        assert tjor_gateway.master_key_path() == tmp_path / "override.key"

    def test_path_default_under_xdg(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TJOR_GATEWAY_KEY_FILE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert tjor_gateway.master_key_path() == tmp_path / "tjor" / "gateway-master.key"

    def test_blank_file_regenerates(self, tmp_path):
        f = tmp_path / "gw.key"
        f.write_text("\n")   # empty/whitespace -> treated as absent
        k = tjor_gateway.ensure_master_key(f)
        assert k.startswith(tjor_gateway.MASTER_KEY_PREFIX)


class TestRenderConfig:
    def test_model_list_shape(self):
        out = tjor_gateway.render_config([
            {"name": "gpt-4o", "model": "openai/gpt-4o", "api_key": "os.environ/OPENAI_API_KEY"},
            {"name": "claude", "model": "anthropic/claude-sonnet-4", "api_key": "os.environ/ANTHROPIC_API_KEY"},
        ])
        doc = json.loads(out)
        assert [m["model_name"] for m in doc["model_list"]] == ["gpt-4o", "claude"]
        assert doc["model_list"][0]["litellm_params"]["model"] == "openai/gpt-4o"

    def test_no_secret_and_no_master_key(self):
        # The rendered config must reference provider keys by env, not literal,
        # and must NOT contain the master key at all.
        out = tjor_gateway.render_config([
            {"name": "gpt-4o", "model": "openai/gpt-4o", "api_key": "os.environ/OPENAI_API_KEY"},
        ])
        doc = json.loads(out)
        assert doc["model_list"][0]["litellm_params"]["api_key"] == "os.environ/OPENAI_API_KEY"
        assert "master_key" not in out and "general_settings" not in out
        assert "sk-" not in out   # no key material

    def test_missing_name_raises(self):
        with pytest.raises(ValueError):
            tjor_gateway.render_config([{"model": "openai/gpt-4o"}])


import tjor_policy

BASE_POLICY = """
mode = "strict-allow"
[hosts]
allow = ["github.com", "api.anthropic.com"]
block = ["telemetry.evil.test"]
[[paths.block]]
host = "api.githubcopilot.com"
path = "/telemetry*"
"""


class TestAugmentPolicy:
    def _policy(self, host="tjor-gateway"):
        toml = tjor_gateway.augment_policy(BASE_POLICY, host)
        pol = tjor_policy.parse_policy(toml)
        assert pol.valid, pol.errors
        return pol, toml

    def test_inference_path_allowed_admin_denied(self):
        pol, _ = self._policy()
        # inference carve-outs -> allowed
        for p in ("/v1/chat/completions", "/chat/completions", "/v1/models", "/v1/messages"):
            v = tjor_policy.evaluate(pol, f"http://tjor-gateway:4000{p}")
            assert v.allowed, (p, v.rule)
        # every management path -> denied by the host-block (no carve-out)
        for p in ("/key/generate", "/user/new", "/ui", "/model/new", "/team/list", "/anything"):
            v = tjor_policy.evaluate(pol, f"http://tjor-gateway:4000{p}")
            assert not v.allowed, (p, v.rule)
            assert v.rule == "host-block"

    def test_base_allows_and_blocks_preserved(self):
        pol, _ = self._policy()
        assert tjor_policy.evaluate(pol, "https://github.com/x").allowed
        assert tjor_policy.evaluate(pol, "https://api.anthropic.com/v1/messages").allowed
        assert not tjor_policy.evaluate(pol, "https://telemetry.evil.test/x").allowed
        # existing path-block still fires
        assert not tjor_policy.evaluate(pol, "https://api.githubcopilot.com/telemetry/x").allowed

    def test_gateway_not_reachable_off_inference_even_with_encoding(self):
        # a percent-encoded admin path must not sneak past the carve-out
        pol, _ = self._policy()
        v = tjor_policy.evaluate(pol, "http://tjor-gateway:4000/key/%67enerate")
        assert not v.allowed

    def test_idempotent(self):
        once = tjor_gateway.augment_policy(BASE_POLICY, "tjor-gateway")
        twice = tjor_gateway.augment_policy(once, "tjor-gateway")
        # augmenting an already-augmented policy doesn't duplicate the host/carve-outs
        assert twice.count('host = "tjor-gateway"') == once.count('host = "tjor-gateway"')
        assert twice.count('"tjor-gateway"') == once.count('"tjor-gateway"')


class TestCli:
    def test_master_key_command(self, tmp_path, capsys):
        tjor_gateway._main(["tjor_gateway.py", "master-key", str(tmp_path / "k.key")])
        out = capsys.readouterr().out.strip()
        assert out.startswith(tjor_gateway.MASTER_KEY_PREFIX)

    def test_render_config_command(self, capsys):
        models = json.dumps([{"name": "m", "model": "openai/gpt-4o"}])
        tjor_gateway._main(["tjor_gateway.py", "render-config", models])
        doc = json.loads(capsys.readouterr().out)
        assert doc["model_list"][0]["model_name"] == "m"

    def test_bad_usage_exits(self):
        with pytest.raises(SystemExit):
            tjor_gateway._main(["tjor_gateway.py", "bogus"])
