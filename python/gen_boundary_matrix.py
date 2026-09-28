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
MATRIX_FILE = ROOT / "docs" / "boundary-matrix.md"

CONFORMANCE = "conformance"
LANDLOCK = "landlock"
WORKSPACE_GATE = "workspace-gate"
SELF_MOUNT = "self-mount"
GITCHECK = "gitcheck"
WORKTREE = "worktree"

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
}

# Order capabilities are grouped in the rendered matrix.
CAPABILITY_ORDER = [
    "cage-network", "egress-policy", "credential-broker",
    "session-identity", "kernel-sandbox", "session-launch", "launcher-integrity",
    "git-tamper-detection",
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
            + parse_landlock(WORKTREE_FILE.read_text()))


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
        f"`self-mount` and `gitcheck` suites are launcher-side (host guarantees the cage cannot "
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
