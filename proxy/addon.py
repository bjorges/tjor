"""tjor mitmproxy addon: enforce the egress policy on every request.

The policy decision itself lives in tjor_policy (the single shared matcher);
this file only wires it to mitmproxy. ``decide()`` is importable without
mitmproxy installed — the parity suite uses it as a call site.

Fail-closed: if the policy file is invalid or missing, every request is
denied. The addon re-checks the policy file's mtime on each request so a
reload never races a stale in-memory copy into permissiveness.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tjor_policy

POLICY_PATH = os.environ.get("TJOR_POLICY_FILE", "/policy/policy.toml")

_cache: dict = {"mtime": None, "policy": None}


def _current_policy() -> tjor_policy.Policy:
    try:
        mtime = os.stat(POLICY_PATH).st_mtime_ns
    except OSError:
        mtime = None
    if _cache["policy"] is None or _cache["mtime"] != mtime:
        _cache["policy"] = tjor_policy.load_policy(POLICY_PATH)
        _cache["mtime"] = mtime
        if not _cache["policy"].valid:
            print(
                "tjor: POLICY INVALID — failing closed, all egress denied: "
                + "; ".join(_cache["policy"].errors),
                file=sys.stderr,
                flush=True,
            )
    return _cache["policy"]


def decide(url: str) -> tjor_policy.Verdict:
    """Parity call site: identical inputs must yield identical verdicts to
    the module API and the CLI."""
    return tjor_policy.evaluate(_current_policy(), url)


class TjorPolicy:
    def request(self, flow) -> None:
        from mitmproxy import http  # deferred so decide() imports host-side

        verdict = decide(flow.request.pretty_url)
        if not verdict.allowed:
            flow.response = http.Response.make(
                403,
                (
                    f"tjor egress policy: DENY ({verdict.rule}"
                    + (f": {verdict.pattern}" if verdict.pattern else "")
                    + ")\n"
                ).encode(),
                {
                    "content-type": "text/plain",
                    "x-tjor-policy": "deny",
                    "x-tjor-rule": verdict.rule,
                },
            )


addons = [TjorPolicy()]
