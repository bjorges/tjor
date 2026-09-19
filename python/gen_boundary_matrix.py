#!/usr/bin/env python3
"""Generate the adversarial boundary results matrix (#38) from the suites.

tjor's boundary is proven by two adversarial suites — the conformance probes
(`images/conformance/probes.py`, each an `@probe("...")`) and the kernel-sandbox
integration test (`tests/integration/landlock_test.sh`, each a `check "..."` or
`ok "..."`). Their results otherwise live only in CI logs. This renders a
human-readable matrix (`docs/boundary-matrix.md`) mapping each adversarial
guarantee to the probe that proves it, its suite, and the spec capability it
backs.

Regenerated from the suites, drift-checked: REGISTRY below maps every check name
to (suite, capability, guarantee, boundary). The generator asserts REGISTRY's
keys equal the names actually parsed from the suite sources — a new/renamed
probe with no entry, or a stale entry with no probe, is a hard error. `boundary`
curates the matrix: True rows are the adversarial guarantees the matrix renders;
False marks a functional / config-validation / launch-UX check that the suite
also runs but which is not an adversarial cage boundary (acknowledged here so it
can't be silently ignored, but not rendered as a "guarantee").

`--check` (used by tests/doc_consistency.sh) runs the cross-check and diffs the
regenerated matrix against the committed file; nonzero exit on any drift.

Coverage, not per-run pass/fail: each rendered guarantee is backed by a live
probe the CI `conformance` and `landlock` jobs run green; this doc makes that
coverage legible rather than embedding transient results.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES_FILE = ROOT / "images" / "conformance" / "probes.py"
LANDLOCK_FILE = ROOT / "tests" / "integration" / "landlock_test.sh"
MATRIX_FILE = ROOT / "docs" / "boundary-matrix.md"

CONFORMANCE = "conformance"
LANDLOCK = "landlock"

# name -> (suite, capability, guarantee, boundary)
# boundary=True  -> an adversarial cage guarantee (rendered in the matrix)
# boundary=False -> a functional / config / launch-UX check the suite also runs
#                   (acknowledged for the drift cross-check; not a "guarantee")
REGISTRY: dict[str, tuple[str, str, str, bool]] = {
    # --- conformance probes (all adversarial) ---
    "direct egress bypassing the proxy is impossible":
        (CONFORMANCE, "cage-network", "No direct egress off the internal network", True),
    "DNS for an unlisted zone fails closed (NXDOMAIN, no forwarding)":
        (CONFORMANCE, "cage-network", "DNS fails closed for unlisted zones (NXDOMAIN, no forwarding)", True),
    "blocked host is denied at the proxy":
        (CONFORMANCE, "egress-policy", "A blocked host is denied at the proxy", True),
    "path carve-out on a blocked host passes policy":
        (CONFORMANCE, "egress-policy", "A path carve-out on a blocked host is allowed (precedence)", True),
    "encoding cannot widen an allow carve-out":
        (CONFORMANCE, "egress-policy", "Percent-encoding cannot widen an allow carve-out", True),
    "encoding cannot evade a path block":
        (CONFORMANCE, "egress-policy", "Percent-encoding cannot evade a path block", True),
    "dot-segments cannot escape a carve-out":
        (CONFORMANCE, "egress-policy", "Dot-segments cannot escape a carve-out", True),
    "CONNECT to a non-allowed host is denied before TLS":
        (CONFORMANCE, "egress-policy", "CONNECT to a non-allowed host is denied before TLS", True),
    "strict-allow default-deny holds for unknown hosts":
        (CONFORMANCE, "egress-policy", "Strict-allow default-deny for unknown hosts", True),
    "no sidecar admin surface is reachable from the agent network":
        (CONFORMANCE, "cage-network", "No sidecar admin surface reachable from the agent network", True),
    "raw TCP passthrough is disabled (tunnels cannot smuggle non-HTTP bytes)":
        (CONFORMANCE, "cage-network", "Raw-TCP tunnels cannot smuggle non-HTTP bytes", True),
    "identity: forged x-agent-* headers are stripped before egress":
        (CONFORMANCE, "session-identity", "Forged x-agent-* headers are stripped before egress", True),
    "identity: matching self-identification passes through":
        (CONFORMANCE, "session-identity", "Matching self-identification passes through", True),
    "identity: injected exactly on configured hosts":
        (CONFORMANCE, "session-identity", "Identity injected only on configured hosts", True),
    "identity: no leakage toward unconfigured hosts":
        (CONFORMANCE, "session-identity", "No identity leakage toward unconfigured hosts", True),
    "broker: real credential injected toward the destination host":
        (CONFORMANCE, "credential-broker", "Real credential injected toward the destination host", True),
    "broker: the agent's placeholder is overwritten, never forwarded":
        (CONFORMANCE, "credential-broker", "The agent's placeholder is overwritten, never forwarded", True),
    "broker: credential does not leak to a non-destination host":
        (CONFORMANCE, "credential-broker", "Credential never leaks to a non-destination host", True),

    # --- kernel-sandbox suite: adversarial guarantees (rendered) ---
    "outside-tree read is kernel-denied":
        (LANDLOCK, "kernel-sandbox", "Outside-tree read is kernel-denied", True),
    "outside-tree write is kernel-denied":
        (LANDLOCK, "kernel-sandbox", "Outside-tree write is kernel-denied", True),
    "workspace .env reads empty (masked)":
        (LANDLOCK, "kernel-sandbox", "Workspace dotenv is masked (reads empty)", True),
    "nested sub/.env reads empty (masked)":
        (LANDLOCK, "kernel-sandbox", "Nested dotenv is masked (reads empty)", True),
    "secret string is absent from the masked file":
        (LANDLOCK, "kernel-sandbox", "The secret is absent from the masked dotenv", True),
    "masked .env cannot be unlinked in-cage":
        (LANDLOCK, "kernel-sandbox", "A masked dotenv cannot be unlinked in-cage", True),
    "secret nowhere in the agent env":
        (LANDLOCK, "kernel-sandbox", "The dotenv secret is absent from the agent environment", True),
    "masked .opencode lists empty in-cage":
        (LANDLOCK, "kernel-sandbox", "A masked dir lists empty in-cage", True),
    "nested .opencode lists empty in-cage":
        (LANDLOCK, "kernel-sandbox", "A nested masked dir lists empty in-cage", True),
    "plugin file unreadable at its path":
        (LANDLOCK, "kernel-sandbox", "A file in a masked dir is unreadable", True),
    "write into the masked dir refused":
        (LANDLOCK, "kernel-sandbox", "A write into a masked dir is refused", True),
    "masked dir cannot be removed in-cage":
        (LANDLOCK, "kernel-sandbox", "A masked dir cannot be removed in-cage", True),
    "plugin content nowhere in the probe result":
        (LANDLOCK, "kernel-sandbox", "Masked-dir content is absent from results", True),
    "require+unavailable aborts with the boundary exit code 90":
        (LANDLOCK, "kernel-sandbox", "require mode aborts (exit 90) when Landlock is unavailable", True),
    "require+unavailable did NOT run the harness":
        (LANDLOCK, "kernel-sandbox", "require mode never runs the harness when Landlock is unavailable", True),
    "auto+unavailable degrades to INACTIVE":
        (LANDLOCK, "kernel-sandbox", "auto mode degrades to INACTIVE (fail-safe) when Landlock is unavailable", True),
    # escape-injection defense on attacker-influenced launch output
    "hostile parent dir name announced escape-sanitized":
        (LANDLOCK, "session-launch", "A hostile dir name is escape-sanitized in launch output", True),
    "no raw ESC byte on any dir-mask line":
        (LANDLOCK, "session-launch", "No raw terminal-escape byte on a dir-mask line", True),
    "hostile dotenv filename is announced escape-sanitized":
        (LANDLOCK, "session-launch", "A hostile dotenv filename is escape-sanitized in launch output", True),
    "no raw ESC byte on any dotenv-mask line":
        (LANDLOCK, "session-launch", "No raw terminal-escape byte on a dotenv-mask line", True),

    # --- kernel-sandbox suite: functional / config / launch-UX (acknowledged, not rendered) ---
    ".env.example (template) is NOT masked": (LANDLOCK, "kernel-sandbox", "masking precision (template not masked)", False),
    "workspace is writable under the wrap": (LANDLOCK, "kernel-sandbox", "functional: workspace writable", False),
    "HTTP_PROXY survives the wrap": (LANDLOCK, "kernel-sandbox", "functional: proxy env survives", False),
    "lowercase http_proxy survives the wrap": (LANDLOCK, "kernel-sandbox", "functional: proxy env survives", False),
    "an allowed host egresses through the proxy": (LANDLOCK, "kernel-sandbox", "functional: allowed egress works", False),
    "entrypoint logged kernel-sandbox ACTIVE": (LANDLOCK, "kernel-sandbox", "functional: status line printed", False),
    "launch announced the dotenv masks": (LANDLOCK, "kernel-sandbox", "launch-UX: mask announced", False),
    "launch announced the nested dotenv mask": (LANDLOCK, "kernel-sandbox", "launch-UX: mask announced", False),
    "launch announced the .opencode mask": (LANDLOCK, "kernel-sandbox", "launch-UX: mask announced", False),
    "launch announced the nested .opencode mask": (LANDLOCK, "kernel-sandbox", "launch-UX: mask announced", False),
    "deny_paths mask applied with mask_dotenv=false (#48)": (LANDLOCK, "kernel-sandbox", "config: deny_paths independence", False),
    "mask_dotenv=false skips automatic dotenv discovery": (LANDLOCK, "kernel-sandbox", "config: mask_dotenv toggle", False),
    "mask_dirs applied with mask_dotenv=false (independence)": (LANDLOCK, "kernel-sandbox", "config: mask_dirs independence", False),
    "dotenv mask applied with landlock mode=off": (LANDLOCK, "kernel-sandbox", "config: masking independent of mode", False),
    "invalid mask_dirs entry aborts the launch": (LANDLOCK, "policy-ergonomics", "config-validation: invalid mask_dirs aborts", False),
    "invalid mask_dirs error names the key": (LANDLOCK, "policy-ergonomics", "config-validation: error names key", False),
    "auto+unavailable still runs the harness": (LANDLOCK, "kernel-sandbox", "functional: auto still runs", False),
    "require+unavailable states FATAL with the reason": (LANDLOCK, "kernel-sandbox", "UX: fatal reason stated", False),
    "off states disabled-by-config": (LANDLOCK, "kernel-sandbox", "UX: off state stated", False),
    "off runs the harness unwrapped": (LANDLOCK, "kernel-sandbox", "functional: off runs unwrapped", False),
    "invalid mode aborts (exit nonzero)": (LANDLOCK, "policy-ergonomics", "config-validation: invalid mode aborts", False),
    "invalid mode names the bad value": (LANDLOCK, "policy-ergonomics", "config-validation: error names value", False),
}

# Order capabilities are grouped in the rendered matrix.
CAPABILITY_ORDER = [
    "cage-network", "egress-policy", "credential-broker",
    "session-identity", "kernel-sandbox", "session-launch",
]


def parse_probes(text: str) -> list[str]:
    return re.findall(r'@probe\("([^"]+)"\)', text)


def parse_landlock(text: str) -> list[str]:
    """`check "<literal>"` / `ok "<literal>"` at statement start; skip literals
    with `$` (the ok()/check() plumbing and variable-bearing messages)."""
    names: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = re.match(r'\s*(?:check|ok)\s+"([^"]*)"', line)
        if not m:
            continue
        name = m.group(1)
        if "$" in name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def parsed_names() -> list[str]:
    return parse_probes(PROBES_FILE.read_text()) + parse_landlock(LANDLOCK_FILE.read_text())


def cross_check(names: list[str]) -> list[str]:
    """Return human-readable errors if REGISTRY and the suite sources disagree."""
    src, reg = set(names), set(REGISTRY)
    errors = []
    for missing in sorted(src - reg):
        errors.append(f"probe/check not in REGISTRY (add a mapping): {missing!r}")
    for stale in sorted(reg - src):
        errors.append(f"REGISTRY entry has no matching probe/check (remove/rename): {stale!r}")
    return errors


def render(names: list[str]) -> str:
    n_boundary = sum(1 for n in names if REGISTRY[n][3])
    lines = [
        "# Adversarial boundary results matrix",
        "",
        "<!-- GENERATED by python/gen_boundary_matrix.py — do not edit by hand.",
        "     Regenerate: python3 python/gen_boundary_matrix.py",
        "     Drift-checked by tests/doc_consistency.sh (`--check`). -->",
        "",
        f"Each row is an adversarial guarantee the cage enforces, the probe that "
        f"proves it, and the spec capability it backs. **Status is coverage, not a "
        f"per-run result**: every guarantee here is exercised by a live probe that the "
        f"CI `conformance` and `landlock` jobs run — a red CI blocks merge, so "
        f"\"listed here\" means \"proven green in CI\". Generated from the suite "
        f"sources ({len(names)} checks total; {n_boundary} adversarial guarantees "
        f"below, the rest functional/config checks the suites also run).",
        "",
    ]
    for cap in CAPABILITY_ORDER:
        rows = sorted(
            (REGISTRY[n][2], n, REGISTRY[n][0]) for n in names
            if REGISTRY[n][1] == cap and REGISTRY[n][3]
        )
        if not rows:
            continue
        lines += [f"## {cap}", "", "| Guarantee | Probe | Suite |", "|---|---|---|"]
        for guarantee, probe, suite in rows:
            lines.append(f"| {guarantee} | `{probe}` | {suite} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _rel(p: Path) -> Path | str:
    """Path relative to ROOT for messages, or the path itself if it's outside
    ROOT (e.g. a test tmp dir) — relative_to raises otherwise."""
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p


def main(argv: list[str]) -> int:
    check = "--check" in argv[1:]
    names = parsed_names()
    errors = cross_check(names)
    if errors:
        print("boundary-matrix: REGISTRY is out of sync with the suites:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    rendered = render(names)
    if check:
        current = MATRIX_FILE.read_text() if MATRIX_FILE.exists() else ""
        if current != rendered:
            print(f"boundary-matrix: {_rel(MATRIX_FILE)} is stale — "
                  f"regenerate with `python3 python/gen_boundary_matrix.py`", file=sys.stderr)
            return 1
        print("boundary-matrix: up to date")
        return 0
    MATRIX_FILE.write_text(rendered)
    print(f"boundary-matrix: wrote {_rel(MATRIX_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
