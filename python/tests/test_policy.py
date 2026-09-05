"""Unit tests for the tjor policy engine. Each spec scenario in
openspec/changes/add-cage-core/specs/egress-policy/spec.md maps to at
least one test here."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_policy as tp

FIXTURES = Path(__file__).parent / "fixtures"


def make(text: str) -> tp.Policy:
    return tp.parse_policy(text)


BASE = """
mode = "strict-allow"
[hosts]
allow = ["good.test"]
block = ["bad.test"]
[[paths.allow]]
host = "bad.test"
path = "/docs/*"
[[paths.block]]
host = "good.test"
path = "*/telemetry*"
"""


class TestPrecedence:
    def test_carveout_on_blocked_host(self):
        policy = make(BASE)
        assert tp.evaluate(policy, "https://bad.test/docs/x").allowed
        assert tp.evaluate(policy, "https://bad.test/docs/x").rule == "path-allow-carveout"
        assert not tp.evaluate(policy, "https://bad.test/other").allowed
        assert tp.evaluate(policy, "https://bad.test/other").rule == "host-block"

    def test_path_block_beats_host_allow(self):
        policy = make(BASE)
        verdict = tp.evaluate(policy, "https://good.test/v1/telemetry/x")
        assert not verdict.allowed and verdict.rule == "path-block"

    def test_strict_allow_default_deny(self):
        policy = make(BASE)
        verdict = tp.evaluate(policy, "https://unknown.test/")
        assert not verdict.allowed and verdict.rule == "default-deny"

    def test_default_allow_mode(self):
        policy = make(BASE.replace("strict-allow", "default-allow"))
        assert tp.evaluate(policy, "https://unknown.test/").rule == "default-allow"
        # blocks still apply in default-allow mode
        assert not tp.evaluate(policy, "https://bad.test/x").allowed


class TestFailClosed:
    def test_missing_file(self, tmp_path):
        policy = tp.load_policy(str(tmp_path / "nope.toml"))
        assert not policy.valid
        assert not tp.evaluate(policy, "https://good.test/").allowed
        assert tp.evaluate(policy, "https://good.test/").rule == "fail-closed:invalid-policy"

    @pytest.mark.parametrize(
        "text",
        [
            "mode = [broken",                          # parse error
            'mode = "sometimes"',                      # invalid mode
            'surprise = true',                         # unknown top-level key
            '[hosts]\nallow = "github.com"',           # wrong type
            '[hosts]\npermit = ["x"]',                 # unknown hosts key
            '[[paths.allow]]\nhost = "h"',             # missing path
            '[[paths.block]]\nhost = "h"\npath = "/p"\nextra = 1',  # unknown rule key
        ],
    )
    def test_invalid_policies_deny_everything(self, text):
        policy = tp.parse_policy(text)
        assert not policy.valid
        assert policy.errors
        assert not tp.evaluate(policy, "https://good.test/").allowed

    def test_empty_policy_is_valid_and_denies_by_default(self):
        policy = tp.parse_policy("")
        assert policy.valid
        assert not tp.evaluate(policy, "https://anything.test/").allowed


class TestEncodingAsymmetry:
    def test_block_fires_on_any_form(self):
        policy = make(BASE)
        for url in (
            "https://good.test/v1/%74elemetry/x",       # encoded once
            "https://good.test/v1/%2574elemetry/x",     # double-encoded
            "https://good.test/a/../v1/telemetry/x",    # dot-segments
        ):
            verdict = tp.evaluate(policy, url)
            assert not verdict.allowed and verdict.rule == "path-block", url

    def test_allow_requires_all_forms(self):
        policy = make(BASE)
        for url in (
            "https://bad.test/%64ocs/x",           # raw form does not match /docs/*
            "https://bad.test/docs/../secret",     # resolved form escapes /docs/*
            "https://bad.test/docs/%2e%2e/secret", # decoded+resolved form escapes
        ):
            verdict = tp.evaluate(policy, url)
            assert not verdict.allowed and verdict.rule == "host-block", url


class TestMatching:
    def test_wildcard_subdomain_not_apex(self):
        assert tp.host_matches("*.example.com", "a.example.com")
        assert tp.host_matches("*.example.com", "a.b.example.com")
        assert not tp.host_matches("*.example.com", "example.com")

    def test_host_canonicalization(self):
        assert tp.host_matches("example.com", "EXAMPLE.com.")
        assert tp.host_matches("example.com", "example.com:8443")

    def test_no_suffix_confusion(self):
        assert not tp.host_matches("allowed.test", "allowed.test.evil.test")

    def test_dot_segments(self):
        assert tp.remove_dot_segments("/a/b/../c") == "/a/c"
        assert tp.remove_dot_segments("/a/./b/") == "/a/b/"
        assert tp.remove_dot_segments("/../x") == "/x"
        assert tp.remove_dot_segments("") == "/"

    def test_path_forms_bounded_and_unique(self):
        forms, complete = tp.path_forms("/%2564ocs/../x")
        assert complete
        assert len(forms) == len(set(forms))
        assert "/x" in forms  # fully decoded and resolved form present

    def test_deeply_nested_encoding_cannot_evade_block(self):
        policy = make(BASE)
        # 4..10 layers of %-nesting around "telemetry" — every one must be
        # decoded to the fixpoint and caught by the any-form block rule.
        for layers in range(4, 11):
            enc = "%74elemetry"
            for _ in range(layers - 1):
                enc = enc.replace("%", "%25", 1)
            verdict = tp.evaluate(policy, f"https://good.test/v1/{enc}/x")
            assert not verdict.allowed and verdict.rule == "path-block", (layers, enc)

    def test_excessive_encoding_fails_closed(self):
        policy = make('mode = "default-allow"')
        enc = "%74"
        for _ in range(tp.MAX_DECODE_ROUNDS + 5):
            enc = enc.replace("%", "%25", 1)
        verdict = tp.evaluate(policy, f"https://any.test/{enc}")
        assert not verdict.allowed and verdict.rule == "fail-closed:excessive-encoding"

    def test_wildcard_matcher_semantics(self):
        cases = [
            ("*", "anything/at/all", True),
            ("", "", True),
            ("", "x", False),
            ("a*", "a", True),
            ("*a*b*", "xxaxxbxx", True),
            ("*a*b*", "xxbxxaxx", False),
            ("?", "x", True),
            ("?", "", False),
            ("/api/*/data/*", "/api/v1/data/x", True),
            ("/api/*/data/*", "/api/v1/other/x", False),
        ]
        for pattern, text, expected in cases:
            assert tp._wildcard_match(pattern, text) is expected, (pattern, text)

    def test_wildcard_matcher_no_redos(self):
        import time
        pattern = "*/a/*/b/*/c/*/d/*"
        text = "/" + "x" * 8000
        start = time.monotonic()
        tp._wildcard_match(pattern, text)
        assert time.monotonic() - start < 0.5  # regex .* chains take far longer

    def test_bad_url_denied(self):
        policy = make(BASE)
        assert tp.evaluate(policy, "not a url at all \x00").rule.startswith("fail-closed")


class TestConnect:
    """CONNECT-time (pre-TLS) host decisions: everything decidable at the
    host level is decided fail-closed; only hosts a path carve-out could
    apply to get a deferred tunnel (full evaluate() runs post-MITM)."""

    def test_blocked_host_without_carveout_denied(self):
        policy = make('mode="strict-allow"\n[hosts]\nblock=["bad.test"]\nallow=[]')
        verdict = tp.evaluate_connect(policy, "bad.test:443")
        assert not verdict.allowed and verdict.rule == "host-block"

    def test_blocked_host_with_carveout_defers(self):
        policy = make(BASE)
        verdict = tp.evaluate_connect(policy, "bad.test:443")
        assert verdict.allowed and verdict.rule == "connect-defer:carveout"

    def test_strict_unknown_host_denied(self):
        policy = make(BASE)
        assert not tp.evaluate_connect(policy, "unknown.test:443").allowed

    def test_allowed_host_tunnels(self):
        policy = make(BASE)
        assert tp.evaluate_connect(policy, "good.test:443").rule == "host-allow"

    def test_invalid_policy_denies_connect(self):
        policy = tp.parse_policy("mode = [broken")
        assert tp.evaluate_connect(policy, "good.test:443").rule == "fail-closed:invalid-policy"

    def test_default_allow_mode_tunnels(self):
        policy = make('mode="default-allow"')
        assert tp.evaluate_connect(policy, "anything.test:443").rule == "default-allow"


class TestCorpusExpectations:
    """The corpus is also the parity input; assert it holds via the API."""

    def test_corpus(self):
        import json

        corpus = json.loads((FIXTURES / "corpus.json").read_text())
        policy = tp.load_policy(str(FIXTURES / corpus["policy"]))
        assert policy.valid
        for case in corpus["cases"]:
            verdict = tp.evaluate(policy, case["url"])
            assert verdict.allowed == case["allowed"], case
            assert verdict.rule == case["rule"], case
