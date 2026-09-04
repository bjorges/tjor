"""Parity suite: the corpus must yield identical verdicts at every call
site — the module API, the proxy addon's decide(), and the CLI. Divergence
is silent policy drift (charter L4) and fails this suite."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

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


def cli_verdict(url: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(PY_DIR / "tjor_policy.py"), "check",
         "--policy", POLICY_FILE, "--json", url],
        capture_output=True, text=True,
    )
    verdict = json.loads(proc.stdout)
    assert (proc.returncode == 0) == verdict["allowed"], "CLI exit code disagrees with verdict"
    return verdict


@pytest.mark.parametrize("case", CASES, ids=[c["url"] for c in CASES])
def test_three_call_sites_agree(case):
    api = tp.evaluate(tp.load_policy(POLICY_FILE), case["url"]).as_dict()
    addon = ADDON.decide(case["url"]).as_dict()
    cli = cli_verdict(case["url"])
    assert api == addon == cli, f"call-site divergence for {case['url']}"
    assert api["allowed"] == case["allowed"] and api["rule"] == case["rule"], case
