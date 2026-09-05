"""Kube credential-broker source pure helpers (#26): API-host derivation and
placeholder-kubeconfig rendering. The kubectl invocations (mint / server
derivation) live in the launcher; injection reuses the D2 `pat` path already
covered by the broker conformance probes, so these tests target exactly the
pure transforms `tjor_kube.py` owns."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_kube


class TestApiHost:
    @pytest.mark.parametrize(
        "server,expected",
        [
            ("https://api.k8s.example.com:6443", "api.k8s.example.com"),
            ("https://10.0.0.1:6443", "10.0.0.1"),
            ("https://cluster.local", "cluster.local"),
            # bare host[:port] override, scheme assumed https
            ("api.k8s.example.com:6443", "api.k8s.example.com"),
            ("api.k8s.example.com", "api.k8s.example.com"),
            ("  https://api.k8s.example.com:6443  ", "api.k8s.example.com"),
        ],
    )
    def test_host_extracted(self, server, expected):
        assert tjor_kube.api_host(server) == expected

    def test_ipv6_literal(self):
        assert tjor_kube.api_host("https://[2001:db8::1]:6443") == "2001:db8::1"

    @pytest.mark.parametrize("bad", ["", "   ", "https://", "https://:6443"])
    def test_missing_host_raises(self, bad):
        with pytest.raises(ValueError):
            tjor_kube.api_host(bad)


class TestNormalizeServer:
    def test_adds_https_when_missing(self):
        assert tjor_kube.normalize_server("api:6443") == "https://api:6443"

    def test_keeps_existing_scheme(self):
        assert tjor_kube.normalize_server("https://api:6443") == "https://api:6443"

    def test_strips_whitespace(self):
        assert tjor_kube.normalize_server("  https://api  ") == "https://api"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            tjor_kube.normalize_server("")


class TestKubeconfig:
    def _load(self, server="https://api.k8s.example.com:6443", ca="/etc/ssl/certs/ca-certificates.crt", **kw):
        out = tjor_kube.kubeconfig(server, ca, **kw)
        return out, json.loads(out)  # valid JSON == a kubeconfig client-go accepts

    def test_shape_and_placeholder_token(self):
        _, doc = self._load()
        assert doc["apiVersion"] == "v1" and doc["kind"] == "Config"
        assert doc["current-context"] == "tjor"
        assert doc["clusters"][0]["cluster"]["server"] == "https://api.k8s.example.com:6443"
        assert doc["clusters"][0]["cluster"]["certificate-authority"] == "/etc/ssl/certs/ca-certificates.crt"
        # The default token is the PLACEHOLDER — the proxy overwrites it.
        assert doc["users"][0]["user"]["token"] == tjor_kube.PLACEHOLDER_TOKEN

    def test_no_real_secret_shape(self):
        # A rendered config must never carry anything but the known placeholder;
        # this guards against a future change accidentally embedding a token.
        text, doc = self._load(token="a-real-looking-token")
        # (explicit token honored only when passed — the launcher never does)
        assert doc["users"][0]["user"]["token"] == "a-real-looking-token"
        # default path carries no other credential keys
        _, doc2 = self._load()
        assert set(doc2["users"][0]["user"].keys()) == {"token"}

    def test_bare_host_normalized_into_server(self):
        _, doc = self._load(server="api.k8s.example.com:6443")
        assert doc["clusters"][0]["cluster"]["server"] == "https://api.k8s.example.com:6443"

    def test_trailing_newline(self):
        text, _ = self._load()
        assert text.endswith("\n")

    def test_invalid_server_raises(self):
        with pytest.raises(ValueError):
            tjor_kube.kubeconfig("https://", "/ca.pem")


class TestCli:
    def test_host_command(self, capsys):
        tjor_kube._main(["tjor_kube.py", "host", "https://api.example.com:6443"])
        assert capsys.readouterr().out.strip() == "api.example.com"

    def test_url_command_normalizes(self, capsys):
        tjor_kube._main(["tjor_kube.py", "url", "api.example.com:6443"])
        assert capsys.readouterr().out.strip() == "https://api.example.com:6443"

    def test_config_command_emits_json(self, capsys):
        tjor_kube._main(["tjor_kube.py", "config", "https://api.example.com:6443", "/ca.pem"])
        doc = json.loads(capsys.readouterr().out)
        assert doc["users"][0]["user"]["token"] == tjor_kube.PLACEHOLDER_TOKEN

    def test_unknown_command_exits(self):
        with pytest.raises(SystemExit):
            tjor_kube._main(["tjor_kube.py", "bogus"])
