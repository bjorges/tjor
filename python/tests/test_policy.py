"""Unit tests for the tjor policy engine. Each spec scenario in
openspec/specs/egress-policy/spec.md maps to at least one test here."""

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
        assert tp.evaluate(policy, "https://bad.test/docs/x", "GET").allowed
        assert tp.evaluate(policy, "https://bad.test/docs/x", "GET").rule == "path-allow-carveout"
        assert not tp.evaluate(policy, "https://bad.test/other", "GET").allowed
        assert tp.evaluate(policy, "https://bad.test/other", "GET").rule == "host-block"

    def test_path_block_beats_host_allow(self):
        policy = make(BASE)
        verdict = tp.evaluate(policy, "https://good.test/v1/telemetry/x", "GET")
        assert not verdict.allowed and verdict.rule == "path-block"

    def test_strict_allow_default_deny(self):
        policy = make(BASE)
        verdict = tp.evaluate(policy, "https://unknown.test/", "GET")
        assert not verdict.allowed and verdict.rule == "default-deny"

    def test_default_allow_mode(self):
        policy = make(BASE.replace("strict-allow", "default-allow"))
        assert tp.evaluate(policy, "https://unknown.test/", "GET").rule == "default-allow"
        # blocks still apply in default-allow mode
        assert not tp.evaluate(policy, "https://bad.test/x", "GET").allowed


class TestFailClosed:
    def test_missing_file(self, tmp_path):
        policy = tp.load_policy(str(tmp_path / "nope.toml"))
        assert not policy.valid
        assert not tp.evaluate(policy, "https://good.test/", "GET").allowed
        assert tp.evaluate(policy, "https://good.test/", "GET").rule == "fail-closed:invalid-policy"

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
            '[methods]\nrestirct = []',                                   # unknown methods key
            '[[methods.restrict]]\nhost = "h"',                            # missing allow
            '[[methods.restrict]]\nhost = "h"\nallows = ["GET"]',          # misspelled field
            '[[methods.restrict]]\nhost = "h"\nallow = ["GET"]\nextra = 1', # extra field
            '[[methods.restrict]]\nhost = "h"\nallow = "GET"',             # not a list
            '[[methods.restrict]]\nhost = "h"\nallow = ["get"]',           # lower-case name
            '[[methods.restrict]]\nhost = "h"\nallow = ["GET "]',          # a space in a name
            '[[methods.restrict]]\nhost = "h"\nallow = ["' + "M" * 33 + '"]',  # 33-character name
            '[[methods.except]]\nhost = "h"\npath = "/p"',                 # missing methods
            '[[methods.except]]\nhost = "h"\nmethods = ["POST"]',          # missing path
            '[[methods.except]]\nhost = "h"\npath = "/p"\nmethods = ["POST"]\nx = 1',  # extra field
        ],
    )
    def test_invalid_policies_deny_everything(self, text):
        policy = tp.parse_policy(text)
        assert not policy.valid
        assert policy.errors
        assert not tp.evaluate(policy, "https://good.test/", "GET").allowed

    def test_empty_policy_is_valid_and_denies_by_default(self):
        policy = tp.parse_policy("")
        assert policy.valid
        assert not tp.evaluate(policy, "https://anything.test/", "GET").allowed


class TestEncodingAsymmetry:
    def test_block_fires_on_any_form(self):
        policy = make(BASE)
        for url in (
            "https://good.test/v1/%74elemetry/x",       # encoded once
            "https://good.test/v1/%2574elemetry/x",     # double-encoded
            "https://good.test/a/../v1/telemetry/x",    # dot-segments
        ):
            verdict = tp.evaluate(policy, url, "GET")
            assert not verdict.allowed and verdict.rule == "path-block", url

    def test_allow_requires_all_forms(self):
        policy = make(BASE)
        for url in (
            "https://bad.test/%64ocs/x",           # raw form does not match /docs/*
            "https://bad.test/docs/../secret",     # resolved form escapes /docs/*
            "https://bad.test/docs/%2e%2e/secret", # decoded+resolved form escapes
        ):
            verdict = tp.evaluate(policy, url, "GET")
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
            verdict = tp.evaluate(policy, f"https://good.test/v1/{enc}/x", "GET")
            assert not verdict.allowed and verdict.rule == "path-block", (layers, enc)

    def test_excessive_encoding_fails_closed(self):
        policy = make('mode = "default-allow"')
        enc = "%74"
        for _ in range(tp.MAX_DECODE_ROUNDS + 5):
            enc = enc.replace("%", "%25", 1)
        verdict = tp.evaluate(policy, f"https://any.test/{enc}", "GET")
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
        assert tp.evaluate(policy, "not a url at all \x00", "GET").rule.startswith("fail-closed")


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
            verdict = tp.evaluate(policy, case["url"], case["method"])
            assert verdict.allowed == case["allowed"], case
            assert verdict.rule == case["rule"], case


# ---------------------------------------------------------------------------
# Method gate (#66): openspec/specs/egress-policy "A method restriction denies
# unlisted methods on a host", "A method exception admits a listed method on
# a path", "The request method is an exact HTTP token", precedence scenarios.

GATED = BASE + """
[[methods.restrict]]
host = "good.test"
allow = ["GET", "HEAD"]
[[methods.except]]
host = "good.test"
path = "/rest/api/2/search"
methods = ["POST"]
"""


def verdict(policy, url, method):
    return tp.evaluate(policy, url, method)


class TestMethodsParsing:
    def test_valid_section_and_empty_allow(self):
        policy = make(GATED + '[[methods.restrict]]\nhost = "vault.test"\nallow = []\n')
        assert policy.valid, policy.errors
        assert ("good.test", frozenset({"GET", "HEAD"})) in policy.method_restrict
        assert ("vault.test", frozenset()) in policy.method_restrict
        assert policy.method_except == [("good.test", "/rest/api/2/search", frozenset({"POST"}))]

    def test_absent_section_leaves_verdicts_unchanged(self):
        plain, gated = make(BASE), make(GATED)
        for url in ("https://good.test/x", "https://bad.test/docs/x", "https://unknown.test/"):
            for m in ("GET", "POST"):
                assert verdict(plain, url, m) == verdict(plain, url, "GET")
        assert verdict(gated, "https://good.test/x", "GET") == verdict(plain, "https://good.test/x", "GET")

    def test_method_restricted_helper(self):
        policy = make(GATED)
        assert tp.method_restricted(policy, "good.test") and tp.method_restricted(policy, "GOOD.test:443")
        assert not tp.method_restricted(policy, "bad.test")
        assert not tp.method_restricted(tp.parse_policy("mode = [broken"), "good.test")


class TestMethodGate:
    def test_post_to_read_only_host_denied_get_allowed(self):
        policy = make(GATED)
        v = verdict(policy, "https://good.test/anything", "POST")
        assert not v.allowed and v.rule == "method-block:POST" and v.pattern == "good.test"
        v = verdict(policy, "https://good.test/anything", "GET")
        assert v.allowed and v.rule == "host-allow"            # same stage and rule as without the restriction

    def test_restrictions_intersect(self):
        policy = make(BASE + """
[[methods.restrict]]
host = "*.test"
allow = ["GET"]
[[methods.restrict]]
host = "good.test"
allow = ["GET", "POST"]
""")
        v = verdict(policy, "https://good.test/x", "POST")
        assert not v.allowed and v.rule == "method-block:POST" and v.pattern == "*.test"
        assert verdict(policy, "https://good.test/x", "GET").allowed

    def test_path_block_wins_over_the_gate(self):
        policy = make(GATED)
        v = verdict(policy, "https://good.test/v1/telemetry/x", "GET")
        assert not v.allowed and v.rule == "path-block"

    def test_empty_allow_list_denies_every_method(self):
        policy = make(BASE + '[[methods.restrict]]\nhost = "good.test"\nallow = []\n'
                      '[[methods.except]]\nhost = "good.test"\npath = "/ping"\nmethods = ["GET"]\n')
        for m in ("GET", "HEAD", "POST", "OPTIONS"):
            assert verdict(policy, "https://good.test/x", m).rule == f"method-block:{m}"
        assert verdict(policy, "https://good.test/ping", "GET").allowed

    def test_no_method_implies_another(self):
        policy = make(BASE + '[[methods.restrict]]\nhost = "good.test"\nallow = ["GET"]\n')
        assert verdict(policy, "https://good.test/x", "HEAD").rule == "method-block:HEAD"
        assert verdict(policy, "https://good.test/x", "OPTIONS").rule == "method-block:OPTIONS"

    def test_exception_admits_the_listed_method_on_its_path(self):
        policy = make(GATED)
        v = verdict(policy, "https://good.test/rest/api/2/search?jql=x", "POST")
        assert v.allowed and v.rule == "host-allow"
        assert verdict(policy, "https://good.test/rest/api/2/issue", "POST").rule == "method-block:POST"

    def test_encoding_cannot_widen_an_exception(self):
        policy = make(GATED)
        for url in ("https://good.test/rest/api/2/%73earch", "https://good.test/rest/api/2/search/../issue"):
            v = verdict(policy, url, "POST")
            assert not v.allowed and v.rule == "method-block:POST", url

    def test_exception_does_not_bypass_default_deny(self):
        policy = make(BASE + '[[methods.except]]\nhost = "unknown.test"\npath = "/x"\nmethods = ["POST"]\n')
        assert verdict(policy, "https://unknown.test/x", "POST").rule == "default-deny"

    def test_exception_is_as_wide_as_its_host_pattern(self):
        policy = make("""
mode = "strict-allow"
[hosts]
allow = ["*.internal.test"]
[[methods.restrict]]
host = "*.internal.test"
allow = ["GET"]
[[methods.restrict]]
host = "vault.internal.test"
allow = []
[[methods.except]]
host = "*.internal.test"
path = "/webhook"
methods = ["POST"]
""")
        assert verdict(policy, "https://vault.internal.test/webhook", "POST").allowed
        assert verdict(policy, "https://vault.internal.test/other", "GET").rule == "method-block:GET"

    def test_carved_out_path_is_still_gated(self):
        policy = make(BASE + '[[methods.restrict]]\nhost = "bad.test"\nallow = ["GET"]\n')
        assert verdict(policy, "https://bad.test/docs/x", "GET").rule == "path-allow-carveout"
        assert verdict(policy, "https://bad.test/docs/x", "POST").rule == "method-block:POST"

    def test_earlier_denial_is_reported_as_such(self):
        policy = make(BASE + '[[methods.restrict]]\nhost = "unknown.test"\nallow = ["GET"]\n')
        assert verdict(policy, "https://unknown.test/x", "POST").rule == "default-deny"

    def test_deny_only_property_over_the_corpus(self):
        import dataclasses, json
        corpus = json.loads((FIXTURES / "corpus.json").read_text())
        gated = tp.load_policy(str(FIXTURES / corpus["policy"]))
        stripped = dataclasses.replace(gated, method_restrict=[], method_except=[])
        for case in corpus["cases"]:
            for m in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                with_gate = verdict(gated, case["url"], m)
                without = verdict(stripped, case["url"], m)
                assert with_gate == without or (
                    without.allowed and not with_gate.allowed and with_gate.rule.startswith("method-block:")
                ), (case["url"], m, with_gate, without)


class TestMethodToken:
    def test_case_is_not_folded(self):
        policy = make(GATED)
        assert verdict(policy, "https://good.test/x", "post").rule == "method-block:post"
        assert verdict(policy, "https://good.test/x", "get").rule == "method-block:get"

    @pytest.mark.parametrize("bad", ["bad method", "GET\t", "", "G\u00c9T", "\u017fET", "M" * 33, "GET/"])
    def test_malformed_method_denied_everywhere(self, bad):
        for text in (BASE, GATED):
            policy = make(text)
            for url in ("https://good.test/x", "https://unknown.test/x", "https://bad.test/docs/x"):
                assert verdict(policy, url, bad).rule == "fail-closed:bad-method", (bad, url)

    def test_length_bound(self):
        policy = make(GATED)
        assert verdict(policy, "https://good.test/x", "M" * 32).rule == "method-block:" + "M" * 32
        plain = make(BASE)
        assert verdict(plain, "https://good.test/x", "M" * 32).rule == "host-allow"
        assert verdict(plain, "https://good.test/x", "M" * 33).rule == "fail-closed:bad-method"

    def test_uncommon_tokens_unaffected(self):
        plain = make(BASE)
        assert verdict(plain, "https://good.test/x", "VERSION-CONTROL").rule == "host-allow"
        assert verdict(plain, "https://good.test/x", "UPDATEREDIRECTREF").rule == "host-allow"

    def test_method_is_required(self):
        with pytest.raises(TypeError):
            tp.evaluate(make(BASE), "https://good.test/x")  # type: ignore[call-arg]

    def test_connect_is_unchanged(self):
        policy = make(GATED)
        assert tp.evaluate_connect(policy, "good.test").allowed    # the tunnel is opened on the host decision alone
