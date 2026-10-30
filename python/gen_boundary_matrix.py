#!/usr/bin/env python3
"""Generate the adversarial boundary results matrix (#38) from the suites.

tjor's boundary is proven by three suites — the conformance probes
(`images/conformance/probes.py`, each an `@probe("...")`), the kernel-sandbox
integration test (`tests/integration/landlock_test.sh`, each a `check "..."` or
`ok "..."`), and the launcher-side workspace-gate test
(`tests/integration/workspace_gate_test.sh`, same `check`/`ok` form; #64) plus
its sibling for launcher integrity (`tests/integration/self_mount_test.sh`; #67).
Those two are HOST guarantees, not cage probes: they prove what the launcher
refuses before any container exists (a sensitive workspace or mount; its own
code tree mounted writable), which the cage cannot re-check for itself. Their results otherwise live only in CI logs. This
renders a human-readable matrix (`docs/boundary-matrix.md`) mapping each
adversarial guarantee to the probe that proves it, its suite, and the spec
capability it backs.

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
WORKSPACE_GATE_FILE = ROOT / "tests" / "integration" / "workspace_gate_test.sh"
SELF_MOUNT_FILE = ROOT / "tests" / "integration" / "self_mount_test.sh"
GITCHECK_FILE = ROOT / "tests" / "integration" / "gitcheck_test.sh"
WORKTREE_FILE = ROOT / "tests" / "integration" / "worktree_test.sh"
TASK_NOTES_FILE = ROOT / "tests" / "integration" / "task_notes_test.sh"
MATRIX_FILE = ROOT / "docs" / "boundary-matrix.md"

CONFORMANCE = "conformance"
LANDLOCK = "landlock"
WORKSPACE_GATE = "workspace-gate"
SELF_MOUNT = "self-mount"
GITCHECK = "gitcheck"
WORKTREE = "worktree"
TASK_NOTES = "task-notes"

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
    "broker: gh's token-scheme placeholder is overwritten in its own scheme":
        (CONFORMANCE, "credential-broker", "gh's token-scheme placeholder is overwritten in its own scheme", True),
    "broker: credential does not leak to a non-destination host":
        (CONFORMANCE, "credential-broker", "Credential never leaks to a non-destination host", True),
    # --- headers-stage enforcement, one host identity, HTTP/1.1 only (ADR 0012) ---
    "enforcement: a large denied body is never forwarded":
        (CONFORMANCE, "egress-policy", "A denied body above the streaming threshold is never forwarded", True),
    "enforcement: a chunked denied body is never forwarded":
        (CONFORMANCE, "egress-policy", "A chunked denied body is never forwarded", True),
    "enforcement: a bounded denied request gets the 403 and the connection survives":
        (CONFORMANCE, "egress-policy", "A bounded denied request is answered 403 and never forwarded", True),
    "enforcement: a denied request with Expect gets no 100 Continue":
        (CONFORMANCE, "egress-policy", "A denied request never receives 100 Continue", True),
    "enforcement: an interrupted denied upload is still logged":
        (CONFORMANCE, "egress-policy", "An interrupted denied upload is denied and logged at the headers stage", True),
    "broker: a streamed request still receives the real credential":
        (CONFORMANCE, "credential-broker", "A streamed request is rewritten before its first byte goes upstream", True),
    "host identity: a Host header inside a tunnel cannot steer the verdict":
        (CONFORMANCE, "egress-policy", "A Host header inside a tunnel cannot steer the verdict", True),
    "host identity: an absolute-form Host header cannot steer the verdict":
        (CONFORMANCE, "egress-policy", "An absolute-form Host header cannot steer the verdict", True),
    "host identity: a TLS tunnel is judged on its server name":
        (CONFORMANCE, "egress-policy", "A TLS tunnel is judged on its server name", True),
    "host identity: an absolute-form target inside a tunnel cannot steer the verdict":
        (CONFORMANCE, "egress-policy", "An absolute-form target inside a tunnel cannot steer the verdict", True),
    "transport: HTTP/2 is not negotiated":
        (CONFORMANCE, "egress-policy", "HTTP/2 is not negotiated: HTTP/1.1 only, so every body is declared", True),
    "transport: the conformance trust anchor does not disable upstream verification":
        (CONFORMANCE, "egress-policy", "Upstream TLS verification holds; the conformance trust anchor is scoped", True),
    # --- method gate (#66) ---
    "method gate: a write to a read-only host is denied":
        (CONFORMANCE, "egress-policy", "A write to a read-only host is denied (method-block)", True),
    "method gate: a read on the read-only host reaches the upstream":
        (CONFORMANCE, "egress-policy", "A read on a read-only host is served", True),
    "method gate: an exception admits the listed method on its path":
        (CONFORMANCE, "egress-policy", "A method exception admits the listed method on its exact path", True),
    "method gate: encoding cannot widen a method exception":
        (CONFORMANCE, "egress-policy", "Percent-encoding cannot widen a method exception", True),
    "method gate: a redirect does not carry a method past the gate":
        (CONFORMANCE, "egress-policy", "A redirected request is judged on its own", True),
    "method gate: a write inside a tunnel is judged on the tunnel target":
        (CONFORMANCE, "egress-policy", "A write inside a tunnel is gated on the tunnel target", True),
    "method gate: a write inside a TLS tunnel is judged on the server name":
        (CONFORMANCE, "egress-policy", "A write inside a TLS tunnel is gated on the server name", True),
    "header guard: a protocol upgrade on a read-only host is refused":
        (CONFORMANCE, "egress-policy", "A protocol switch on a read-only host is refused", True),
    "header guard: a method-override header on a read-only host is refused":
        (CONFORMANCE, "egress-policy", "A method-override header on a read-only host is refused", True),
    "header guard: a 101 from the upstream of a read-only host is refused":
        (CONFORMANCE, "egress-policy", "A 101 from a read-only host is refused before it reaches the agent", True),

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

    # git metadata masks (#71)
    "git hooks: workspace hooks dir lists empty in-cage":
        (LANDLOCK, "kernel-sandbox", "Git hooks directory is masked (lists empty) in a writable mount", True),
    "git hooks: write into the masked hooks dir refused":
        (LANDLOCK, "kernel-sandbox", "A masked git hooks directory cannot be written in-cage", True),
    "git hooks: a host-installed pre-commit hook does not fire in-cage":
        (LANDLOCK, "kernel-sandbox", "A host-installed git hook does not fire on an in-cage commit", True),
    "git hooks: nested repo hooks dir lists empty in-cage":
        (LANDLOCK, "kernel-sandbox", "A nested repository's hooks directory is masked", True),
    "git hooks: worktree common-dir hooks list empty in-cage":
        (LANDLOCK, "kernel-sandbox", "A linked worktree's common hooks directory is masked", True),
    "config pin: git config write refused in-cage":
        (LANDLOCK, "kernel-sandbox", "A pinned .git/config refuses writes in-cage (opt-in)", True),

    # --- kernel-sandbox suite: functional / config / launch-UX (acknowledged, not rendered) ---
    "git hooks: launch announced the workspace hooks mask": (LANDLOCK, "kernel-sandbox", "launch-UX: hooks mask announced", False),
    "git hooks: launch announced the nested repo hooks mask": (LANDLOCK, "kernel-sandbox", "launch-UX: nested hooks mask announced", False),
    "git hooks: in-cage commit still succeeds": (LANDLOCK, "kernel-sandbox", "functional: commit works with hooks masked", False),
    "git hooks: mask_git_hooks=false announces no hooks mask": (LANDLOCK, "kernel-sandbox", "config: hooks mask opt-out (no announcement)", False),
    "git hooks: mask_git_hooks=false leaves the host hook visible": (LANDLOCK, "kernel-sandbox", "config: hooks mask opt-out (hook visible)", False),
    "config pin: launch announced the pin": (LANDLOCK, "kernel-sandbox", "launch-UX: config pin announced", False),
    "config pin: git remote add refused in-cage": (LANDLOCK, "kernel-sandbox", "functional: remote add refused under the pin", False),
    "config pin: commit still succeeds": (LANDLOCK, "kernel-sandbox", "functional: commit works under the pin", False),
    "config pin: config stays readable": (LANDLOCK, "kernel-sandbox", "functional: config readable under the pin", False),
    "config pin: host config file unchanged": (LANDLOCK, "kernel-sandbox", "functional: host config unchanged", False),
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

    # --- workspace-gate suite (#64, launcher-side): adversarial guarantees (rendered) ---
    "workspace gate: home-rooted dotfiles repo refused from the home dir":
        (WORKSPACE_GATE, "session-launch", "Sensitive host path refused as the primary workspace", True),
    "workspace gate: non-repo subdir of a home-rooted repo refused":
        (WORKSPACE_GATE, "session-launch", "A workspace reached by git climbing to a sensitive toplevel is refused", True),
    "workspace gate: no state dir created after a refusal":
        (WORKSPACE_GATE, "session-launch", "A refused launch leaves no session state directory behind", True),
    "workspace gate: session root refused as the workspace":
        (WORKSPACE_GATE, "session-launch", "The session state root is refused as the workspace", True),
    "extra-dir gate: session root refused via --dir":
        (WORKSPACE_GATE, "session-launch", "The session state root is refused as a writable extra mount", True),
    "extra-dir gate: session root refused via --dir-ro":
        (WORKSPACE_GATE, "session-launch", "The session state root is refused as a read-only extra mount", True),

    # --- workspace-gate suite: functional / launch-UX (acknowledged, not rendered) ---
    "sensitive roots: session root derived from config": (WORKSPACE_GATE, "session-launch", "functional: session root derivation", False),
    "sensitive roots: config dir derived from XDG_CONFIG_HOME": (WORKSPACE_GATE, "session-launch", "functional: config dir derivation", False),
    "sensitive roots: TJOR_USER_CONFIG dirname wins over XDG": (WORKSPACE_GATE, "session-launch", "functional: TJOR_USER_CONFIG precedence", False),
    "session root itself is sensitive": (WORKSPACE_GATE, "session-launch", "rule: session root equal", False),
    "a dir under the session root is sensitive": (WORKSPACE_GATE, "session-launch", "rule: session root descendant", False),
    "an ancestor of the session root is sensitive": (WORKSPACE_GATE, "session-launch", "rule: session root ancestor", False),
    "a sibling whose name extends the session root is not sensitive": (WORKSPACE_GATE, "session-launch", "rule: component-boundary precision", False),
    "config dir itself is sensitive": (WORKSPACE_GATE, "session-launch", "rule: config dir equal", False),
    "a dir under the config dir is sensitive": (WORKSPACE_GATE, "session-launch", "rule: config dir descendant", False),
    "an ordinary repo is not sensitive": (WORKSPACE_GATE, "session-launch", "rule: ordinary repo passes", False),
    "workspace gate: refusal names the home dir as a sensitive workspace": (WORKSPACE_GATE, "session-launch", "launch-UX: refusal names the path", False),
    "workspace gate: git-climb refusal names cwd, toplevel and git dir": (WORKSPACE_GATE, "session-launch", "launch-UX: git-climb explanation", False),
    "workspace gate: git-climb refusal names the remedy": (WORKSPACE_GATE, "session-launch", "launch-UX: git-climb remedy", False),
    "workspace gate: ancestor of the session root refused as the workspace": (WORKSPACE_GATE, "session-launch", "gate: session root ancestor as workspace", False),
    "workspace gate: dir under the session root refused as the workspace": (WORKSPACE_GATE, "session-launch", "gate: session root descendant as workspace", False),
    "workspace gate: config dir refused as the workspace": (WORKSPACE_GATE, "session-launch", "gate: config dir as workspace", False),
    "workspace gate: dir under the config dir refused as the workspace": (WORKSPACE_GATE, "session-launch", "gate: config dir descendant as workspace", False),
    "workspace gate: still no state dir after every refusal": (WORKSPACE_GATE, "session-launch", "gate: no state dir after any refusal", False),
    "workspace gate: refusals never reached docker": (WORKSPACE_GATE, "session-launch", "gate: refusals precede docker", False),
    "workspace gate: --unsafe-dir launches the home-rooted workspace": (WORKSPACE_GATE, "session-launch", "override: --unsafe-dir launches", False),
    "workspace gate: --unsafe-dir warns, naming the exposed workspace": (WORKSPACE_GATE, "session-launch", "override: loud warning names the path", False),
    "workspace gate: ordinary repo launches with no gate output": (WORKSPACE_GATE, "session-launch", "functional: ordinary repo launches", False),
    "workspace gate: ordinary repo launch prints no refusal or override text": (WORKSPACE_GATE, "session-launch", "functional: ordinary repo is silent", False),
    "workspace gate: --unsafe-dir on an ordinary repo stays silent": (WORKSPACE_GATE, "session-launch", "override: silent when nothing overridden", False),
    "workspace gate: no override warning when nothing was overridden": (WORKSPACE_GATE, "session-launch", "override: no spurious warning", False),
    "lifecycle path: resolve without the launch marker skips the gate": (WORKSPACE_GATE, "session-launch", "functional: lifecycle commands skip the gate", False),
    "lifecycle path: no refusal or override text": (WORKSPACE_GATE, "session-launch", "functional: lifecycle commands are silent", False),
    "extra-dir gate: --dir refusal names the sensitive path": (WORKSPACE_GATE, "session-launch", "launch-UX: --dir refusal names the path", False),
    "extra-dir gate: --dir-ro refusal states the read-only exposure": (WORKSPACE_GATE, "session-launch", "launch-UX: --dir-ro refusal wording", False),
    "extra-dir gate: refusals never reached docker": (WORKSPACE_GATE, "session-launch", "gate: extra-dir refusals precede docker", False),
    "extra-dir gate: --unsafe-dir warns on an actually-overridden --dir": (WORKSPACE_GATE, "session-launch", "override: loud warning on --dir", False),
    "extra-dir gate: no override warning for an ordinary --dir": (WORKSPACE_GATE, "session-launch", "override: no spurious --dir warning", False),
    "help text names the workspace gate": (WORKSPACE_GATE, "session-launch", "launch-UX: help text", False),
    # core.worktree redirect (#76): the reported toplevel must contain the launch dir
    "core.worktree: redirect toward a harmless directory is refused":
        (WORKSPACE_GATE, "session-launch", "A core.worktree redirect of the workspace is refused", True),
    "core.worktree: refusal names the launch dir and the reported work tree": (WORKSPACE_GATE, "session-launch", "launch-UX: containment refusal names both paths", False),
    "core.worktree: refusal names the setting and its config file": (WORKSPACE_GATE, "session-launch", "launch-UX: containment refusal names core.worktree", False),
    "core.worktree: no state dir for the redirected path": (WORKSPACE_GATE, "session-launch", "gate: no state dir after a redirect refusal", False),
    "core.worktree: lifecycle resolution refuses the redirect too": (WORKSPACE_GATE, "session-launch", "gate: lifecycle commands refuse a redirect", False),
    "core.worktree: redirect toward an ancestor holding other repos is refused":
        (WORKSPACE_GATE, "session-launch", "A core.worktree redirect toward an ancestor directory is refused", True),
    "core.worktree: ancestor refusal names the nearest repository": (WORKSPACE_GATE, "session-launch", "launch-UX: ancestor refusal names the found repository", False),
    "core.worktree: redirect toward the home directory is refused as a redirect": (WORKSPACE_GATE, "session-launch", "gate: home redirect refused", False),
    "core.worktree: home redirect names core.worktree, not the not-a-repository wording": (WORKSPACE_GATE, "session-launch", "launch-UX: redirect wording precedes the climb wording", False),
    "core.worktree: a linked worktree launches (containment holds)": (WORKSPACE_GATE, "session-launch", "functional: linked worktree", False),
    "core.worktree: a subdirectory launch is unchanged": (WORKSPACE_GATE, "session-launch", "functional: subdirectory launch", False),
    "core.worktree: attach's short-name qualification refuses the redirect":
        (WORKSPACE_GATE, "session-launch", "A core.worktree redirect cannot steer attach to another session", True),
    "core.worktree: attach refusal never reached docker": (WORKSPACE_GATE, "session-launch", "gate: attach refusal precedes docker", False),
    "core.worktree: repo_root (trust/init/policy) refuses the redirect": (WORKSPACE_GATE, "session-launch", "gate: trusted-repo resolution refuses a redirect", False),
    # v0.20.4 review: the refusal must PROPAGATE out of command substitution
    "core.worktree: tjor init stops on the redirect (exit status propagates through the subshell)":
        (WORKSPACE_GATE, "session-launch", "tjor init stops on a core.worktree redirect", True),
    "core.worktree: tjor trust stops on the redirect": (WORKSPACE_GATE, "session-launch", "gate: trust stops on a redirect", False),
    "core.worktree: tjor policy (policy_file) stops on the redirect instead of using the user policy":
        (WORKSPACE_GATE, "session-launch", "tjor policy stops on a core.worktree redirect instead of falling through", True),
    "core.worktree: tjor doctor stops on the redirect": (WORKSPACE_GATE, "session-launch", "gate: doctor stops on a redirect", False),
    "core.worktree: no .tjor scaffold was created on the redirected path": (WORKSPACE_GATE, "session-launch", "functional: no scaffold on refusal", False),
    "extra-dir gate: a refused --dir minted no credential material":
        (WORKSPACE_GATE, "session-launch", "A refused extra dir leaves no minted credential behind", True),
    "extra-dir gate: a launch that passes every gate does mint (control)": (WORKSPACE_GATE, "session-launch", "functional: control for the mint-order check", False),

    # --- self-mount suite (#67, launcher-side): adversarial guarantees (rendered) ---
    "self-mount guard: the checkout as the workspace is refused":
        (SELF_MOUNT, "launcher-integrity", "The running tjor tree is refused as the workspace", True),
    "self-mount guard: a dir inside the checkout via --dir is refused":
        (SELF_MOUNT, "launcher-integrity", "A directory inside the running tjor tree is refused as a writable mount", True),
    "self-mount guard: a parent of the checkout via --dir is refused":
        (SELF_MOUNT, "launcher-integrity", "A parent of the running tjor tree is refused as a writable mount", True),
    "self-install: the installed tree builds locally, never pulls":
        (SELF_MOUNT, "launcher-integrity", "A self-installed tree builds its images locally and never pulls", True),
    "install root refused via --dir":
        (SELF_MOUNT, "session-launch", "The tjor install root is refused as a mount", True),
    "a workspace inside an installed tree is refused":
        (SELF_MOUNT, "session-launch", "A workspace inside an installed launcher tree is refused", True),

    # --- self-mount suite: functional / launch-UX (acknowledged, not rendered) ---
    "self-mount rule: the checkout itself overlaps": (SELF_MOUNT, "launcher-integrity", "rule: equal", False),
    "self-mount rule: a dir inside the checkout overlaps": (SELF_MOUNT, "launcher-integrity", "rule: descendant", False),
    "self-mount rule: a parent of the checkout overlaps": (SELF_MOUNT, "launcher-integrity", "rule: ancestor", False),
    "self-mount rule: a sibling whose name extends the checkout does not overlap": (SELF_MOUNT, "launcher-integrity", "rule: component-boundary precision", False),
    "self-mount rule: an ordinary repo does not overlap": (SELF_MOUNT, "launcher-integrity", "rule: disjoint passes", False),
    "self-mount guard: refusal names the tree and the writable root": (SELF_MOUNT, "launcher-integrity", "launch-UX: refusal names both paths", False),
    "self-mount guard: refusal names the three remedies": (SELF_MOUNT, "launcher-integrity", "launch-UX: refusal names the remedies", False),
    "self-mount guard: refusals never reached docker": (SELF_MOUNT, "launcher-integrity", "gate: refusals precede docker", False),
    "self-mount guard: a disjoint workspace prints no self-mount text": (SELF_MOUNT, "launcher-integrity", "functional: disjoint is silent", False),
    "self-mount guard: read-only self-mount is allowed with a notice": (SELF_MOUNT, "launcher-integrity", "functional: read-only overlap notice", False),
    "self-mount guard: read-only self-mount is not refused": (SELF_MOUNT, "launcher-integrity", "functional: read-only overlap allowed", False),
    "self-mount guard: --allow-self-mount proceeds with a loud warning": (SELF_MOUNT, "launcher-integrity", "override: loud warning", False),
    "self-install: symbolic links are kept as links resolving inside the tree": (SELF_MOUNT, "launcher-integrity", "functional: archive keeps relative links", False),
    "image label: a checkout build carries tjor.source-sha=HEAD (dirty-aware)": (SELF_MOUNT, "launcher-integrity", "provenance: checkout label", False),
    "self-install: installs the committed HEAD tree": (SELF_MOUNT, "launcher-integrity", "functional: self-install runs", False),
    "self-install: tree contains the launcher, compose, config, python, images, VERSION": (SELF_MOUNT, "launcher-integrity", "functional: tree contents", False),
    "self-install: marker holds the sha": (SELF_MOUNT, "launcher-integrity", "functional: marker", False),
    "self-install: nothing under the tree is writable": (SELF_MOUNT, "launcher-integrity", "functional: read-only tree", False),
    "self-install: current points at the sha": (SELF_MOUNT, "launcher-integrity", "functional: current symlink", False),
    "self-install: output names the launcher path": (SELF_MOUNT, "launcher-integrity", "launch-UX: launcher path", False),
    "self-install: output says uncommitted changes are excluded": (SELF_MOUNT, "launcher-integrity", "launch-UX: uncommitted note", False),
    "self-install: re-installing the same sha is idempotent": (SELF_MOUNT, "launcher-integrity", "functional: idempotent", False),
    "self-install: a bogus ref fails": (SELF_MOUNT, "launcher-integrity", "functional: bad ref refused", False),
    "self-install: the installed tree is a source tree": (SELF_MOUNT, "launcher-integrity", "functional: marker is source", False),
    "self-install: source_sha of the installed tree is the marker": (SELF_MOUNT, "launcher-integrity", "functional: source_sha", False),
    "self-install: self-install from an installed tree is refused": (SELF_MOUNT, "launcher-integrity", "functional: needs a checkout", False),
    "image label: an installed-tree build carries the marker sha": (SELF_MOUNT, "launcher-integrity", "provenance: installed-tree label", False),
    "sensitive roots: install root derived from TJOR_INSTALL_ROOT": (SELF_MOUNT, "session-launch", "functional: install root derivation", False),
    "install root itself is sensitive": (SELF_MOUNT, "session-launch", "rule: install root equal", False),
    "an installed tree under the install root is sensitive": (SELF_MOUNT, "session-launch", "rule: install root descendant", False),
    "an ancestor of the install root is sensitive": (SELF_MOUNT, "session-launch", "rule: install root ancestor", False),
    "a sibling whose name extends the install root is not sensitive": (SELF_MOUNT, "session-launch", "rule: component-boundary precision (install root)", False),
    "install root --dir refusal is the sensitive-path error": (SELF_MOUNT, "session-launch", "launch-UX: install-root refusal wording", False),
    "install-root refusals never reached docker": (SELF_MOUNT, "session-launch", "gate: install-root refusals precede docker", False),
    "doctor: inside the checkout names a mutable git checkout": (SELF_MOUNT, "launcher-integrity", "doctor: mutable checkout", False),
    "doctor: inside the checkout warns that a launch from here is refused": (SELF_MOUNT, "launcher-integrity", "doctor: launch-from-here warning", False),
    "doctor: from an installed tree names the sha, read-only": (SELF_MOUNT, "launcher-integrity", "doctor: installed tree", False),
    "doctor: from an installed tree has no self-mount warning": (SELF_MOUNT, "launcher-integrity", "doctor: no spurious warning", False),
    "doctor: succeeds outside any repository": (SELF_MOUNT, "launcher-integrity", "doctor: no repo needed", False),
    "help text names --allow-self-mount and self-install": (SELF_MOUNT, "launcher-integrity", "launch-UX: help text", False),

    # --- gitcheck suite (#72, launcher-side): detection guarantees (rendered) ---
    "gitcheck: planted core.hooksPath makes git-check exit non-zero":
        (GITCHECK, "git-tamper-detection", "A cage-written dangerous git config key is reported", True),
    "gitcheck: marker survives findings":
        (GITCHECK, "git-tamper-detection", "Findings keep the pending marker", True),
    "gitcheck: --ack clears the marker":
        (GITCHECK, "git-tamper-detection", "Only an acknowledgement or a clean check clears the marker", True),
    "gitcheck: push -u shaped writes are clean (exit zero)":
        (GITCHECK, "git-tamper-detection", "Everyday git writes are not findings", True),
    "gitcheck: ls surfaces the unchecked session":
        (GITCHECK, "git-tamper-detection", "An unchecked session is surfaced in tjor ls", True),
    "gitcheck: <repo> argument finds the covering session and reports":
        (GITCHECK, "git-tamper-detection", "The on-demand gate checks a repo against every covering baseline", True),
    # --- gitcheck suite: functional / launch-UX (acknowledged, not rendered) ---
    "gitcheck: baseline records every writable root": (GITCHECK, "git-tamper-detection", "functional: baseline coverage", False),
    "gitcheck: pending marker written at baseline": (GITCHECK, "git-tamper-detection", "functional: marker at baseline", False),
    "gitcheck: launch announced the baseline": (GITCHECK, "git-tamper-detection", "launch-UX: baseline announced", False),
    "gitcheck: the finding names the repo, key and value": (GITCHECK, "git-tamper-detection", "launch-UX: finding wording", False),
    "gitcheck: findings say the marker stays and how to ack": (GITCHECK, "git-tamper-detection", "launch-UX: ack hint", False),
    "gitcheck: --json emits the finding class": (GITCHECK, "git-tamper-detection", "functional: json output", False),
    "gitcheck: --ack <token> exits zero": (GITCHECK, "git-tamper-detection", "functional: token ack exit code", False),
    # --- v0.21.1 review follow-ups: token-bound ack, fail-closed findings ---
    "gitcheck: --json carries the ack token": (GITCHECK, "git-tamper-detection", "functional: json token", False),
    "gitcheck: --json findings set the marker (same rule as the human path)":
        (GITCHECK, "git-tamper-detection", "A scripted (--json) check with findings sets the pending marker", True),
    "gitcheck: a bare --ack with findings is refused (exit non-zero)":
        (GITCHECK, "git-tamper-detection", "An acknowledgement without the reviewed state's token is refused", True),
    "gitcheck: the refused ack shows the findings and the token to accept them": (GITCHECK, "git-tamper-detection", "launch-UX: refused ack shows findings + token", False),
    "gitcheck: marker survives a refused ack": (GITCHECK, "git-tamper-detection", "functional: refused ack keeps the marker", False),
    "gitcheck: a wrong token is refused": (GITCHECK, "git-tamper-detection", "functional: wrong token refused", False),
    "gitcheck: a stale token (the state moved on) is refused":
        (GITCHECK, "git-tamper-detection", "An acknowledgement token for a state that has since changed is refused", True),
    "gitcheck: the stale refusal names the current token": (GITCHECK, "git-tamper-detection", "launch-UX: stale refusal names the current token", False),
    "gitcheck: an ext:: remote url is a finding":
        (GITCHECK, "git-tamper-detection", "An ext:: transport on a remote URL is a finding", True),
    "gitcheck: the ext:: finding names the remote url key": (GITCHECK, "git-tamper-detection", "launch-UX: ext:: finding wording", False),
    "gitcheck: a config git cannot parse is a finding, not clean":
        (GITCHECK, "git-tamper-detection", "A config file git cannot parse is a finding (fail closed)", True),
    "gitcheck: the unparseable config is reported as UNKNOWN, with git's error": (GITCHECK, "git-tamper-detection", "launch-UX: unreadable config wording", False),
    "gitcheck: the repaired config checks clean again": (GITCHECK, "git-tamper-detection", "functional: repaired config clean", False),
    "gitcheck: a directory tree deeper than git_check_depth is a NEW truncation, reported":
        (GITCHECK, "git-tamper-detection", "A new truncation of the repository walk is a finding, never silent", True),
    "gitcheck: the truncation finding names the depth cap and UNCHECKED": (GITCHECK, "git-tamper-detection", "launch-UX: truncation wording", False),
    "gitcheck: a baseline taken over a truncated tree announces the truncation at launch":
        (GITCHECK, "git-tamper-detection", "A truncated walk at baseline is announced at launch", True),
    "gitcheck: the truncation known at baseline is not re-reported": (GITCHECK, "git-tamper-detection", "functional: known truncation quiet", False),
    "gitcheck: a repository appearing under a non-repo root is a finding (repo-added)":
        (GITCHECK, "git-tamper-detection", "A repository created under a non-repository root is a finding", True),
    "git hooks: an ordinary hooks dir is masked": (GITCHECK, "kernel-sandbox", "functional: mask planner masks hooks", False),
    "git hooks: a symlinked hooks dir refuses the launch instead of masking through the link":
        (GITCHECK, "kernel-sandbox", "A symlinked git hooks directory is refused at launch, never masked through", True),
    "git hooks: the refusal names the fix (replace the link)": (GITCHECK, "kernel-sandbox", "launch-UX: symlink refusal wording", False),
    "git hooks: a symlinked config is refused even with the pin off":
        (GITCHECK, "kernel-sandbox", "A symlinked git config is refused at launch regardless of the pin setting", True),
    "git hooks: a symlinked .git entry is refused too":
        (GITCHECK, "kernel-sandbox", "A symlinked .git entry is refused at launch", True),
    "git hooks: with the real directories back the plan succeeds": (GITCHECK, "kernel-sandbox", "functional: mask planner control", False),
    "gitcheck: after --ack the acknowledged state is the new baseline (next check clean)":
        (GITCHECK, "git-tamper-detection", "An acknowledgement accepts the current state as the new baseline", True),
    "gitcheck: a change after --ack is reported again": (GITCHECK, "git-tamper-detection", "functional: post-ack writes reported", False),
    "gitcheck: findings after an ack set the marker again": (GITCHECK, "git-tamper-detection", "functional: findings set the marker", False),
    "gitcheck: ls is silent once acknowledged": (GITCHECK, "git-tamper-detection", "functional: ls silent after ack", False),
    "gitcheck: a clean check clears the marker": (GITCHECK, "git-tamper-detection", "functional: clean clears", False),
    "gitcheck: the extra repo's finding is attributed to it": (GITCHECK, "git-tamper-detection", "launch-UX: attribution", False),
    "gitcheck: a repo no session covers is refused clearly": (GITCHECK, "git-tamper-detection", "launch-UX: uncovered repo", False),
    "gitcheck: help text names git-check": (GITCHECK, "git-tamper-detection", "launch-UX: help text", False),
    # --- worktree suite (#79): common-dir resolution, refusals, wiring, masks ---
    "worktree: a linked worktree resolves to its main repository's common dir":
        (WORKTREE, "session-launch", "A linked worktree's common git directory is resolved through git's own linkage", True),
    "worktree: a .git directory root needs no common dir": (WORKTREE, "session-launch", "functional: .git dir needs nothing", False),
    "worktree: a separate-git-dir checkout with core.worktree resolves to its git dir": (WORKTREE, "session-launch", "functional: separate git dir with back-link", False),
    "worktree: a bare repository's worktree resolves to the bare common dir": (WORKTREE, "session-launch", "functional: bare common dir", False),
    "worktree: a planted pointer without a back-link is refused":
        (WORKTREE, "session-launch", "A .git pointer whose target does not link back to the root is refused, never mounted", True),
    "worktree: the planted refusal names the mismatch": (WORKTREE, "session-launch", "launch-UX: planted refusal wording", False),
    "worktree: a pointer git cannot resolve is refused, naming the pointer":
        (WORKTREE, "session-launch", "A .git pointer git cannot resolve refuses the launch instead of failing in-cage", True),
    "worktree: a separate-git-dir checkout without core.worktree is refused with the fix": (WORKTREE, "session-launch", "launch-UX: separate git dir without back-link", False),
    "worktree: a symlinked .git is refused": (WORKTREE, "session-launch", "functional: symlinked .git refused", False),
    "worktree: a forged private dir with a commondir pointing elsewhere is refused (never mounted)":
        (WORKTREE, "session-launch", "A forged worktree structure inside a writable root cannot mount another host directory", True),
    "worktree: the forgery refusal names git's native layout as the only trusted linkage": (WORKTREE, "session-launch", "launch-UX: forgery refusal wording", False),
    "worktree: without --allow-worktree-mount an unlisted common dir refuses the launch, naming the path and the remedies":
        (WORKTREE, "session-launch", "A common directory the operator did not name is never mounted without explicit approval", True),
    "worktree: naming the common dir with --dir needs no flag": (WORKTREE, "session-launch", "functional: explicit --dir approval", False),
    "worktree: launch from a worktree without the flag is refused before docker": (WORKTREE, "session-launch", "gate: unapproved common dir refusal precedes docker", False),
    "worktree: a sensitive common dir is refused":
        (WORKTREE, "session-launch", "A sensitive common git directory is refused with no override", True),
    "worktree: --unsafe-dir does not override a sensitive common dir": (WORKTREE, "session-launch", "functional: no override", False),
    "worktree: a common dir under an existing root adds no mount": (WORKTREE, "session-launch", "functional: covered common dir", False),
    "worktree: the workspace's common dir is appended writable and announced":
        (WORKTREE, "session-launch", "The common directory is mounted alongside the worktree with its writability and announced", True),
    "worktree: a shared common dir mounts once, writable": (WORKTREE, "session-launch", "functional: shared common dir", False),
    "worktree: a read-only worktree's common dir is appended read-only": (WORKTREE, "session-launch", "functional: read-only worktree", False),
    "worktree: a writable worktree under a read-only root warns and adds nothing": (WORKTREE, "session-launch", "functional: read-only parent warning", False),
    "worktree: launch from a worktree with --allow-worktree-mount passes the resolver (announce, then docker reached)": (WORKTREE, "session-launch", "functional: launch wiring", False),
    "worktree: launch from a planted pointer is refused before docker": (WORKTREE, "session-launch", "gate: pointer refusals precede docker", False),
    "git hooks: a bare-named git-dir root has its hooks masked":
        (WORKTREE, "kernel-sandbox", "A mount root that is itself a git directory has its hooks masked", True),
    "git hooks: a .git-named common dir root is masked exactly once": (WORKTREE, "kernel-sandbox", "functional: mask planner dedupes", False),
    # --- landlock suite, section A5: the worktree workspace live ---
    "worktree: launch announced the common dir mount": (LANDLOCK, "session-launch", "launch-UX: common dir mount announced", False),
    "worktree: launch announced the common dir hooks mask": (LANDLOCK, "kernel-sandbox", "launch-UX: common dir hooks mask announced", False),
    "worktree: git status works in-cage from a worktree workspace":
        (LANDLOCK, "session-launch", "Git works inside a worktree workspace whose main repository lies outside it", True),
    "worktree: git log works in-cage from a worktree workspace": (LANDLOCK, "session-launch", "functional: git log in a worktree workspace", False),
    "worktree: git commit works in-cage from a worktree workspace":
        (LANDLOCK, "session-launch", "An in-cage commit from a worktree workspace succeeds", True),
    "worktree: the in-cage commit landed in the main repository": (LANDLOCK, "session-launch", "functional: commit reaches the main repository", False),
    "worktree: the common dir's hooks list empty in-cage":
        (LANDLOCK, "kernel-sandbox", "A mounted worktree common directory's hooks directory is masked in-cage", True),
    "worktree: the main repository's pre-commit hook did not fire":
        (LANDLOCK, "kernel-sandbox", "The main repository's host hook does not fire on an in-cage worktree commit", True),
    "worktree: git resolves the common dir at its host path in-cage": (LANDLOCK, "session-launch", "functional: common dir at its host path", False),
    # --- task notes (launcher-side, #69; spec: task-notes) ---
    'task notes: --task resolves the directory from the template, with no side effect':
        (TASK_NOTES, 'task-notes', '--task resolves the directory from the template, with no side effect', False),
    'task notes: resolution created no directory':
        (TASK_NOTES, 'task-notes', 'Resolution created no directory', True),
    'task notes: the launch names the per-task session and how to address it':
        (TASK_NOTES, 'session-launch', 'The launch names the per-task session and how to address it', False),
    'task notes: no state dir is created by resolution':
        (TASK_NOTES, 'task-notes', 'No state dir is created by resolution', True),
    'task notes: an upper-case id is refused once it names a directory':
        (TASK_NOTES, 'task-notes', 'An upper-case id is refused once it names a directory', True),
    'task notes: the refusal names the grammar':
        (TASK_NOTES, 'task-notes', 'The refusal names the grammar', False),
    'task notes: a dot-leading id is refused':
        (TASK_NOTES, 'task-notes', 'A dot-leading id is refused', True),
    "task notes: '..' as a task id is refused":
        (TASK_NOTES, 'task-notes', "'..' as a task id is refused", True),
    'task notes: a 33-character id is refused':
        (TASK_NOTES, 'task-notes', 'A 33-character id is refused', True),
    'task notes: a dotted id is refused':
        (TASK_NOTES, 'task-notes', 'A dotted id is refused', True),
    'task notes: no directory was created by any refusal':
        (TASK_NOTES, 'task-notes', 'No directory was created by any refusal', True),
    'task notes: refusals never reached docker':
        (TASK_NOTES, 'task-notes', 'Refusals never reached docker', True),
    'task notes: launching from inside the notes repository is refused':
        (TASK_NOTES, 'task-notes', 'Launching from inside the notes repository is refused', True),
    'task notes: the refusal names the workspace and the notes root':
        (TASK_NOTES, 'task-notes', 'The refusal names the workspace and the notes root', False),
    'task notes: the refusal points at launching from the code repository':
        (TASK_NOTES, 'task-notes', 'The refusal points at launching from the code repository', False),
    'task notes: launching from the notes repository root is refused':
        (TASK_NOTES, 'task-notes', 'Launching from the notes repository root is refused', True),
    'task notes: no state dir after the notes-root refusals':
        (TASK_NOTES, 'task-notes', 'No state dir after the notes-root refusals', True),
    'task notes: a workspace below the notes root is not an ancestor and launches':
        (TASK_NOTES, 'task-notes', 'A workspace below the notes root is not an ancestor and launches', False),
    'task notes: another spelling of the notes repository (a link) is refused by identity':
        (TASK_NOTES, 'task-notes', 'Another spelling of the notes repository (a link) is refused by identity', True),
    'task notes: --task <base id> is refused (it reads as the default session)':
        (TASK_NOTES, 'session-launch', '--task <base id> is refused (it reads as the default session)', True),
    'task notes: --task <base id>-x is refused (it reads as a qualified id)':
        (TASK_NOTES, 'session-launch', '--task <base id>-x is refused (it reads as a qualified id)', True),
    'task notes: the round-trip refusal names tjor down --session':
        (TASK_NOTES, 'session-launch', 'The round-trip refusal names tjor down --session', True),
    "task notes: a qualified-looking id naming an existing session's state dir is refused":
        (TASK_NOTES, 'session-launch', "A qualified-looking id naming an existing session's state dir is refused", True),
    'task notes: that refusal never asked docker (the state dir decided)':
        (TASK_NOTES, 'task-notes', 'That refusal never asked docker (the state dir decided)', True),
    'task notes: a qualified-looking id naming a labelled container is refused':
        (TASK_NOTES, 'session-launch', 'A qualified-looking id naming a labelled container is refused', True),
    'task notes: the container lookup went through docker ps':
        (TASK_NOTES, 'session-launch', 'The container lookup went through docker ps', False),
    'task notes: a qualified-looking id with Docker unreachable is refused, not guessed':
        (TASK_NOTES, 'session-launch', 'A qualified-looking id with Docker unreachable is refused, not guessed', True),
    'task notes: the unreachable-engine refusal says so':
        (TASK_NOTES, 'session-launch', 'The unreachable-engine refusal says so', False),
    'task notes: a qualified-looking id no session uses launches':
        (TASK_NOTES, 'session-launch', 'A qualified-looking id no session uses launches', False),
    'task notes: a plain id never consults docker':
        (TASK_NOTES, 'session-launch', 'A plain id never consults docker', True),
    'task notes: no docker call for the plain id':
        (TASK_NOTES, 'session-launch', 'No docker call for the plain id', True),
    'task notes: the lifecycle resolver reads the derived name back as the same session':
        (TASK_NOTES, 'session-lifecycle', 'The lifecycle resolver reads the derived name back as the same session', False),
    "task notes: the resolver's qualified-looking notice is printed for it":
        (TASK_NOTES, 'session-launch', "The resolver's qualified-looking notice is printed for it", False),
    'task notes: a collision that appears later is refused as ambiguous':
        (TASK_NOTES, 'session-lifecycle', 'A collision that appears later is refused as ambiguous', True),
    'task notes: the ambiguity refusal says so':
        (TASK_NOTES, 'session-lifecycle', 'The ambiguity refusal says so', False),
    "task notes: the ambiguity refusal names this workspace's full id":
        (TASK_NOTES, 'session-lifecycle', "The ambiguity refusal names this workspace's full id", True),
    'task notes: with only the foreign session present the full id is used verbatim':
        (TASK_NOTES, 'session-lifecycle', 'With only the foreign session present the full id is used verbatim', False),
    'task notes: --session names the session and --task stays the label and directory':
        (TASK_NOTES, 'session-launch', '--session names the session and --task stays the label and directory', False),
    'task notes: without [task] a label-only id keeps the old grammar':
        (TASK_NOTES, 'task-notes', 'Without [task] a label-only id keeps the old grammar', False),
    'task notes: without [task] a dot-leading label is still accepted':
        (TASK_NOTES, 'task-notes', 'Without [task] a dot-leading label is still accepted', False),
    'task notes: session_per_task alone applies the grammar and derives the name, mounts nothing':
        (TASK_NOTES, 'session-launch', 'Session_per_task alone applies the grammar and derives the name, mounts nothing', True),
    'task notes: session_per_task alone still refuses an upper-case id':
        (TASK_NOTES, 'session-launch', 'Session_per_task alone still refuses an upper-case id', False),
    'task notes: a TRUSTED repo config cannot move the notes directory':
        (TASK_NOTES, 'repo-config-trust', 'A TRUSTED repo config cannot move the notes directory', True),
    "task notes: the repo config's [task] table is reported as ignored":
        (TASK_NOTES, 'repo-config-trust', "The repo config's [task] table is reported as ignored", True),
    'task notes: a relative template is refused':
        (TASK_NOTES, 'task-notes', 'A relative template is refused', True),
    'task notes: a template without the placeholder is refused':
        (TASK_NOTES, 'task-notes', 'A template without the placeholder is refused', True),
    'task notes: a template with the placeholder twice is refused':
        (TASK_NOTES, 'task-notes', 'A template with the placeholder twice is refused', True),
    'task notes: a template with a dot-dot component is refused':
        (TASK_NOTES, 'task-notes', 'A template with a dot-dot component is refused', True),
    'task notes: a template with a trailing separator is refused':
        (TASK_NOTES, 'task-notes', 'A template with a trailing separator is refused', True),
    'task notes: a template whose root does not exist is refused':
        (TASK_NOTES, 'task-notes', 'A template whose root does not exist is refused', True),
    'task notes: the root is never created by tjor':
        (TASK_NOTES, 'task-notes', 'The root is never created by tjor', True),
    'task notes: a malformed template leaves no directory':
        (TASK_NOTES, 'task-notes', 'A malformed template leaves no directory', True),
    'task notes: a sensitive template is refused by the --dir gate before anything is created':
        (TASK_NOTES, 'task-notes', 'A sensitive template is refused by the --dir gate before anything is created', True),
    'task notes: the gate refusal names the sensitive path':
        (TASK_NOTES, 'task-notes', 'The gate refusal names the sensitive path', False),
    'task notes: the gate refusal created nothing':
        (TASK_NOTES, 'task-notes', 'The gate refusal created nothing', True),
    'task notes: the gate refusal left no session state dir':
        (TASK_NOTES, 'task-notes', 'The gate refusal left no session state dir', True),
    'task notes: prepare creates the directory and appends it to the writable extras once':
        (TASK_NOTES, 'task-notes', 'Prepare creates the directory and appends it to the writable extras once', True),
    'task notes: the created directory is real':
        (TASK_NOTES, 'task-notes', 'The created directory is real', True),
    'task notes: the directory is created component by component below the root':
        (TASK_NOTES, 'task-notes', 'The directory is created component by component below the root', True),
    'task notes: both components are real directories':
        (TASK_NOTES, 'task-notes', 'Both components are real directories', True),
    'task notes: an equal --dir is not appended twice':
        (TASK_NOTES, 'task-notes', 'An equal --dir is not appended twice', True),
    'task notes: a directory covered by a --dir root is mounted with it, not again':
        (TASK_NOTES, 'task-notes', 'A directory covered by a --dir root is mounted with it, not again', True),
    'task notes: the covered case says which root covers it':
        (TASK_NOTES, 'task-notes', 'The covered case says which root covers it', False),
    'task notes: a notes root inside the workspace is the notes-root refusal (the code repo would be the notes repo)':
        (TASK_NOTES, 'task-notes', 'A notes root inside the workspace is the notes-root refusal (the code repo would be the notes repo)', True),
    'task notes: that refusal names the workspace as containing the notes root':
        (TASK_NOTES, 'task-notes', 'That refusal names the workspace as containing the notes root', False),
    'task notes: the same path via --dir-ro is a writability conflict':
        (TASK_NOTES, 'task-notes', 'The same path via --dir-ro is a writability conflict', True),
    'task notes: the conflict names --dir-ro':
        (TASK_NOTES, 'task-notes', 'The conflict names --dir-ro', True),
    'task notes: a symbolic link at the task directory is refused':
        (TASK_NOTES, 'task-notes', 'A symbolic link at the task directory is refused', True),
    'task notes: the link refusal names it':
        (TASK_NOTES, 'task-notes', 'The link refusal names it', True),
    'task notes: nothing was created through the link':
        (TASK_NOTES, 'task-notes', 'Nothing was created through the link', True),
    'task notes: create = false refuses a missing directory':
        (TASK_NOTES, 'task-notes', 'Create = false refuses a missing directory', False),
    'task notes: the create=false refusal names task.create':
        (TASK_NOTES, 'task-notes', 'The create=false refusal names task.create', True),
    'task notes: create = false accepts an existing directory':
        (TASK_NOTES, 'task-notes', 'Create = false accepts an existing directory', False),
    'task notes: lifecycle resolution creates nothing':
        (TASK_NOTES, 'task-notes', 'Lifecycle resolution creates nothing', True),
    'task notes: no directory after a lifecycle resolution':
        (TASK_NOTES, 'task-notes', 'No directory after a lifecycle resolution', True),
    'task notes: credential-shaped files produce a loud warning and the launch continues':
        (TASK_NOTES, 'task-notes', 'Credential-shaped files produce a loud warning and the launch continues', False),
    'task notes: the warning counts the findings':
        (TASK_NOTES, 'task-notes', 'The warning counts the findings', False),
    'task notes: the warning names the key file':
        (TASK_NOTES, 'task-notes', 'The warning names the key file', False),
    'task notes: the warning names the file whose content looks like a token':
        (TASK_NOTES, 'task-notes', 'The warning names the file whose content looks like a token', False),
    'task notes: a FIFO does not block the scan':
        (TASK_NOTES, 'task-notes', 'A FIFO does not block the scan', True),
    'task notes: the scan says it was partial and names the FIFO':
        (TASK_NOTES, 'task-notes', 'The scan says it was partial and names the FIFO', False),
    'task notes: the partial notice is loud':
        (TASK_NOTES, 'task-notes', 'The partial notice is loud', False),
    'task notes: a probe the container does not see refuses the launch':
        (TASK_NOTES, 'task-notes', 'A probe the container does not see refuses the launch', False),
    'task notes: the share refusal names the directory':
        (TASK_NOTES, 'task-notes', 'The share refusal names the directory', False),
    'task notes: the share refusal names the remedy':
        (TASK_NOTES, 'task-notes', 'The share refusal names the remedy', False),
    'task notes: the probe file is removed after a refusal':
        (TASK_NOTES, 'task-notes', 'The probe file is removed after a refusal', True),
    'task notes: a probe the container sees passes':
        (TASK_NOTES, 'task-notes', 'A probe the container sees passes', False),
    'task notes: the probe file is removed after a pass':
        (TASK_NOTES, 'task-notes', 'The probe file is removed after a pass', True),
    'task notes: the probe container has no network':
        (TASK_NOTES, 'task-notes', 'The probe container has no network', True),
    'task notes: the probe container runs a plain shell entrypoint':
        (TASK_NOTES, 'task-notes', 'The probe container runs a plain shell entrypoint', False),
    'task notes: the probe runs on the pinned proxy image':
        (TASK_NOTES, 'task-notes', 'The probe runs on the pinned proxy image', False),
    'task notes: the probe binds the notes directory read-only':
        (TASK_NOTES, 'task-notes', 'The probe binds the notes directory read-only', True),
    'task notes: the probe binds nothing else':
        (TASK_NOTES, 'task-notes', 'The probe binds nothing else', True),
    'task notes: the probe passes no environment and no socket':
        (TASK_NOTES, 'task-notes', 'The probe passes no environment and no socket', True),
    'task notes: the probe name is a trailing argument, never inside the shell string':
        (TASK_NOTES, 'task-notes', 'The probe name is a trailing argument, never inside the shell string', True),
    'task notes: attach --task picks the agent carrying that task label':
        (TASK_NOTES, 'session-lifecycle', 'Attach --task picks the agent carrying that task label', False),
    'task notes: attach --task resolved the right container':
        (TASK_NOTES, 'session-lifecycle', 'Attach --task resolved the right container', False),
    'task notes: attach --task with no such agent exits non-zero':
        (TASK_NOTES, 'session-lifecycle', 'Attach --task with no such agent exits non-zero', False),
    'task notes: attach --task with no such agent says so':
        (TASK_NOTES, 'session-lifecycle', 'Attach --task with no such agent says so', False),
    'task notes: the same task id in two repositories offers the picker':
        (TASK_NOTES, 'task-notes', 'The same task id in two repositories offers the picker', False),
    'task notes: the picker, declined, selects nothing':
        (TASK_NOTES, 'task-notes', 'The picker, declined, selects nothing', False),
    'task notes: attach --task without a value is a usage error':
        (TASK_NOTES, 'session-lifecycle', 'Attach --task without a value is a usage error', False),
    'task notes: the usage error says the value is needed':
        (TASK_NOTES, 'task-notes', 'The usage error says the value is needed', False),
    'task notes: attach with a session and --task is a usage error':
        (TASK_NOTES, 'session-lifecycle', 'Attach with a session and --task is a usage error', False),
    'task notes: the usage error says not both':
        (TASK_NOTES, 'task-notes', 'The usage error says not both', False),
    'task notes: help text names the per-task notes directory':
        (TASK_NOTES, 'task-notes', 'Help text names the per-task notes directory', False),
    'task notes: help text names attach --task':
        (TASK_NOTES, 'session-lifecycle', 'Help text names attach --task', False),
}

# Order capabilities are grouped in the rendered matrix.
CAPABILITY_ORDER = [
    "cage-network", "egress-policy", "credential-broker",
    "session-identity", "kernel-sandbox", "session-launch", "task-notes", "session-lifecycle",
    "repo-config-trust", "launcher-integrity", "git-tamper-detection",
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
    return (parse_probes(PROBES_FILE.read_text())
            + parse_landlock(LANDLOCK_FILE.read_text())
            + parse_landlock(WORKSPACE_GATE_FILE.read_text())
            + parse_landlock(SELF_MOUNT_FILE.read_text())
            + parse_landlock(GITCHECK_FILE.read_text())
            + parse_landlock(WORKTREE_FILE.read_text())
            + parse_landlock(TASK_NOTES_FILE.read_text()))


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
        f"Each row is an adversarial guarantee tjor enforces, the probe that "
        f"proves it, and the spec capability it backs. **Status is coverage, not a "
        f"per-run result**: every guarantee here is exercised by a live probe that the "
        f"CI `conformance`, `landlock` and `unit` jobs run — a red CI blocks merge, so "
        f"\"listed here\" means \"proven green in CI\". The `conformance` and "
        f"`landlock` suites probe the cage from inside; the `workspace-gate`, "
        f"`self-mount`, `gitcheck` and `task-notes` suites are launcher-side (host guarantees the cage cannot "
        f"re-check: what `tjor run` refuses before any container exists). Generated from the suite "
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
