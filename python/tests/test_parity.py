"""Parity suite: the corpus must yield identical verdicts at every call
site — the module API, the proxy addon's decide(), and the CLI. Divergence
is silent policy drift (charter L4) and fails this suite."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

PY_DIR = Path(__file__).resolve().parents[1]
REPO = PY_DIR.parent
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(PY_DIR))
import tjor_policy as tp


def load_corpus():
    corpus = json.loads((FIXTURES / "corpus.json").read_text())
    return str(FIXTURES / corpus["policy"]), corpus["cases"]


POLICY_FILE, CASES = load_corpus()


def load_addon():
    spec = importlib.util.spec_from_file_location("tjor_addon", REPO / "proxy" / "addon.py")
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.POLICY_PATH = POLICY_FILE
    addon._cache = {"mtime": None, "policy": None}
    return addon


ADDON = load_addon()


def cli_verdict(url: str, method: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(PY_DIR / "tjor_policy.py"), "check",
         "--policy", POLICY_FILE, "--json", "--method", method, url],
        capture_output=True, text=True,
    )
    verdict = json.loads(proc.stdout)
    assert (proc.returncode == 0) == verdict["allowed"], "CLI exit code disagrees with verdict"
    # The CLI's JSON is the verdict plus ONE declared field: whether the host
    # is method-restricted (the proxy's header guards, unseen by a preview).
    # Checked against the module API here, not discarded, so the schema cannot
    # drift silently; the verdict keys themselves are compared below.
    host = urlsplit(url if "//" in url else "//" + url).netloc
    assert verdict.pop("header_guards") == tp.method_restricted(tp.load_policy(POLICY_FILE), host), url
    assert set(verdict) == {"allowed", "rule", "pattern"}, verdict
    return verdict


def test_every_case_carries_a_method():
    # No call site evaluates a request without its method (charter L4): the
    # corpus has no default for it either.
    assert all("method" in c for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[f"{c['method']} {c['url']}" for c in CASES])
def test_three_call_sites_agree(case):
    api = tp.evaluate(tp.load_policy(POLICY_FILE), case["url"], case["method"]).as_dict()
    addon = ADDON.decide(case["url"], case["method"]).as_dict()
    cli = cli_verdict(case["url"], case["method"])
    assert api == addon == cli, f"call-site divergence for {case['method']} {case['url']}"
    assert api["allowed"] == case["allowed"] and api["rule"] == case["rule"], case
