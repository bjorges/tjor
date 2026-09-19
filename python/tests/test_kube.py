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


class TestApiOrigin:
    """Exact host:port injection scope (#49)."""

    @pytest.mark.parametrize(
        "server,expected",
        [
            ("https://api.k8s.example.com:6443", "api.k8s.example.com:6443"),
            ("https://api.k8s.example.com", "api.k8s.example.com:443"),  # https default
            ("api.k8s.example.com:6443", "api.k8s.example.com:6443"),
            ("https://10.0.0.1:6443", "10.0.0.1:6443"),
            ("https://[2001:db8::1]:6443", "[2001:db8::1]:6443"),
            ("https://[2001:db8::1]", "[2001:db8::1]:443"),
            ("http://api.k8s.example.com", "api.k8s.example.com:80"),  # http default
            ("http://api.k8s.example.com:8080", "api.k8s.example.com:8080"),
            ("http://[2001:db8::1]", "[2001:db8::1]:80"),
        ],
    )
    def test_origin_composed(self, server, expected):
        assert tjor_kube.api_origin(server) == expected

    @pytest.mark.parametrize("bad", ["", "https://", "https://:6443"])
    def test_missing_host_raises(self, bad):
        with pytest.raises(ValueError):
            tjor_kube.api_origin(bad)


class TestSameServer:
    """Canonical server-identity equality (#58): the `kube_api_host` pin is
    validated against the active context's server with this, so equivalent
    spellings must agree and any real identity difference must not."""

    @pytest.mark.parametrize(
        "a,b",
        [
            # bare host[:port] override vs the kubeconfig's full https URL
            ("api.k8s.example.com:6443", "https://api.k8s.example.com:6443"),
            # implicit vs explicit https default port
            ("https://api.k8s.example.com", "https://api.k8s.example.com:443"),
            ("api.k8s.example.com", "https://api.k8s.example.com:443"),
            # hostnames compare case-insensitively (urlparse lowercases)
            ("https://API.K8S.Example.COM:6443", "https://api.k8s.example.com:6443"),
            ("https://[2001:db8::1]:6443", "[2001:db8::1]:6443"),
            ("  https://api.k8s.example.com:6443  ", "api.k8s.example.com:6443"),
        ],
    )
    def test_equivalent_spellings_are_the_same_server(self, a, b):
        assert tjor_kube.same_server(a, b)

    @pytest.mark.parametrize(
        "a,b",
        [
            ("https://api-a.example.com:6443", "https://api-b.example.com:6443"),
            ("https://api.example.com:6443", "https://api.example.com:6444"),
            ("https://api.example.com", "https://api.example.com:6443"),
            # same host:port, different scheme — still not the same server
            ("http://api.example.com:6443", "https://api.example.com:6443"),
        ],
    )
    def test_different_identity_is_a_mismatch(self, a, b):
        assert not tjor_kube.same_server(a, b)

    @pytest.mark.parametrize("bad", ["", "   ", "https://", "https://:6443"])
    def test_invalid_input_raises(self, bad):
        with pytest.raises(ValueError):
            tjor_kube.same_server(bad, "https://api.example.com:6443")
        with pytest.raises(ValueError):
            tjor_kube.same_server("https://api.example.com:6443", bad)

    # Hardening (#58 review): userinfo and IPv6 zone-ids. The property that
    # matters is no FALSE POSITIVE — same_server must never call two different
    # servers the same (that would let a mismatched pin through); a false
    # negative only fails closed (broker disabled), which is safe.
    def test_userinfo_is_ignored_not_part_of_identity(self):
        # credentials in the URL are not the server; the same host matches
        assert tjor_kube.same_server(
            "https://user:pass@api.example.com:6443", "https://api.example.com:6443")

    def test_userinfo_cannot_forge_a_match_to_a_different_host(self):
        # a different real host must NOT match just because the other host name
        # appears in userinfo — urlparse takes the authority host, not userinfo
        assert not tjor_kube.same_server(
            "https://api.example.com@evil.example.net:6443", "https://api.example.com:6443")

    def test_ipv6_zone_id_same_spelling_matches(self):
        assert tjor_kube.same_server(
            "https://[fe80::1%25eth0]:6443", "[fe80::1%25eth0]:6443")

    def test_ipv6_different_zone_id_is_not_a_match(self):
        # distinct interfaces are distinct servers — must fail closed, not merge
        assert not tjor_kube.same_server(
            "https://[fe80::1%25eth0]:6443", "https://[fe80::1%25eth1]:6443")


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


class TestMultiKubeconfig:
    """Multi-context placeholder kubeconfig (#57): one context per cluster,
    each with the placeholder token, first as current-context."""

    ENTRIES = [
        ("prod-aks", "https://api.prod:6443"),
        ("staging-eks", "stg.example.com:6443"),  # bare host, assumed https
    ]

    def _load(self, entries=None, ca="/etc/ssl/certs/ca.crt", **kw):
        out = tjor_kube.multi_kubeconfig(entries or self.ENTRIES, ca, **kw)
        return out, json.loads(out)

    def test_one_context_per_cluster(self):
        _, doc = self._load()
        assert [c["name"] for c in doc["contexts"]] == ["prod-aks", "staging-eks"]
        assert [c["name"] for c in doc["clusters"]] == ["prod-aks", "staging-eks"]
        assert [u["name"] for u in doc["users"]] == ["prod-aks", "staging-eks"]
        # each context binds to its own cluster + user
        for c in doc["contexts"]:
            assert c["context"]["cluster"] == c["name"]
            assert c["context"]["user"] == c["name"]

    def test_first_is_current_context(self):
        _, doc = self._load()
        assert doc["current-context"] == "prod-aks"

    def test_placeholder_token_only_in_every_user(self):
        _, doc = self._load()
        for u in doc["users"]:
            assert u["user"] == {"token": tjor_kube.PLACEHOLDER_TOKEN}

    def test_servers_normalized_and_ca_set(self):
        _, doc = self._load()
        servers = {c["name"]: c["cluster"]["server"] for c in doc["clusters"]}
        assert servers["prod-aks"] == "https://api.prod:6443"
        assert servers["staging-eks"] == "https://stg.example.com:6443"  # bare host got https
        for c in doc["clusters"]:
            assert c["cluster"]["certificate-authority"] == "/etc/ssl/certs/ca.crt"

    def test_no_real_secret_ever(self):
        # even a single entry never embeds anything but the placeholder by default
        _, doc = self._load(entries=[("only", "https://api.only:6443")])
        assert doc["users"][0]["user"]["token"] == tjor_kube.PLACEHOLDER_TOKEN

    def test_duplicate_context_refused(self):
        with pytest.raises(ValueError):
            tjor_kube.multi_kubeconfig(
                [("dup", "https://a:6443"), ("dup", "https://b:6443")], "/ca.pem")

    def test_empty_list_refused(self):
        with pytest.raises(ValueError):
            tjor_kube.multi_kubeconfig([], "/ca.pem")

    def test_invalid_server_refused(self):
        with pytest.raises(ValueError):
            tjor_kube.multi_kubeconfig([("c", "https://")], "/ca.pem")

    def test_cli_multiconfig_emits_json(self, capsys):
        tjor_kube._main(["tjor_kube.py", "multiconfig", "/ca.pem",
                         "prod-aks", "https://api.prod:6443",
                         "staging-eks", "stg.example.com:6443"])
        doc = json.loads(capsys.readouterr().out)
        assert doc["current-context"] == "prod-aks"
        assert len(doc["contexts"]) == 2
        assert all(u["user"]["token"] == tjor_kube.PLACEHOLDER_TOKEN for u in doc["users"])

    def test_cli_multiconfig_odd_args_exit(self):
        with pytest.raises(SystemExit):
            tjor_kube._main(["tjor_kube.py", "multiconfig", "/ca.pem", "prod-aks"])


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

    def test_same_command_exit_codes(self):
        with pytest.raises(SystemExit) as exc:
            tjor_kube._main(["tjor_kube.py", "same", "api.example.com:6443", "https://api.example.com:6443"])
        assert exc.value.code == 0
        with pytest.raises(SystemExit) as exc:
            tjor_kube._main(["tjor_kube.py", "same", "https://api-a:6443", "https://api-b:6443"])
        assert exc.value.code == 1

    def test_unknown_command_exits(self):
        with pytest.raises(SystemExit):
            tjor_kube._main(["tjor_kube.py", "bogus"])
