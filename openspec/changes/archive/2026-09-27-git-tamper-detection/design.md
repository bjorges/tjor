# Design

## Context

See proposal.md — Why. Grounding (observed at v0.21.0):

- `run_agent` finalizes `safe[]` / `ro_dirs` (the mount set) before the masks and before any container starts; it ends with `docker attach` (unless `--detach`) and then `exit "${code}"` from inside the function — so "attached-session exit" is the line before that exit. `cmd_down` prints the denial, log-volume and secret-scan recaps after removing the topology. `cmd_ls` is label-driven and never reads the state root today.
- The session state directory (`${TJOR_SESSION_DIR}`) holds `home/` (mounted), `broker/`, `proxy-ca/`, `mask-empty` and the signal files (bind-mounted individually); a new `gitcheck/` subdirectory is never mounted, so the agent cannot read or alter it.
- v0.21.0's mask discovery (`.git` dirs and files under writable roots) is the same walk the baseline needs; `git rev-parse --path-format=absolute --git-common-dir` resolves worktree pointers. `git config --file <f> --no-includes --list -z` reads a config file without executing anything and without following includes.
- `python/tjor_safeprint.py` is the shared escape sanitizer for attacker-influenced strings; the launcher renders untrusted names through it.
- `tests/integration/workspace_gate_test.sh` is the daemon-free pattern (sourced launcher, temp home, custom session root); `python/gen_boundary_matrix.py` takes one file per suite.

## Goals / Non-Goals

**Goals:**
- Make every cage-written metadata pattern that host git would execute visible at the earliest moment tjor gets: harness exit, teardown, or on demand.
- Survive crashes: the marker is written before the agent starts and removed only by a clean check or an acknowledgement.
- Zero false positives on everyday git: the dangerous set is explicit and documented; everything else is not a finding.

**Non-Goals:**
- Prevention (that is #71's masks and pin).
- Blocking host git automatically: the gate is a command the operator wires in themselves.
- Content analysis of hooks or filters: a hash change is the finding.

## Decisions

1. **One Python module decides; bash orchestrates.** `tjor_gitcheck.py snapshot --out FILE ROOT…` and `check BASELINE [--json]`. The dangerous-key predicate, the discovery walk, the diff and the finding classes live in one place with unit tests; the launcher only calls it and renders. *Alternative rejected:* bash-side diffing of `git config --list` output — the key set, `!`-alias detection and worktree pointer logic are exactly what should be tested in Python.
2. **The dangerous set is a predicate over lowercase keys, listed in the module and the README.** Exact keys (`core.hooksPath`, `core.fsmonitor`, `core.sshCommand`, `core.pager`, `core.editor`, `core.askPass`, `core.gitProxy`, `core.alternateRefsCommand`, `core.attributesFile`, `sequence.editor`, `gpg.program`, `diff.external`, `interactive.diffFilter`, `credential.helper`, `uploadpack.packObjectsHook`, `sendemail.sendmailCmd`, `include.path`), prefixed families (`gpg.*.program`, `filter.*.clean|smudge|process`, `diff.*.textconv|command`, `merge.*.driver`, `mergetool.*.cmd`, `difftool.*.cmd`, `browser.*.cmd`, `pager.*`, `credential.*.helper`, `remote.*.uploadpack|receivepack|proxy|vcs`, `url.*.insteadOf|pushInsteadOf`, `includeIf.*.path`, `safe.*`, `extensions.*`), and value-dependent ones (`alias.*` and `submodule.*.update` when the value starts with `!`). `url.*.insteadOf` and `safe.*` are not code execution but redirect where code comes from and widen trust; they are in the set and the README says why.
3. **Discovery mirrors the masks: `.git` entries under each writable root, depth-limited.** A `.git` directory is a repository; a `.git` file is a worktree pointer (its text is part of the baseline; its target's `commondir` too). Walk depth is capped (12) and `node_modules`-style noise is not special-cased: a nested `.git` anywhere in the tree is worth knowing about. Read-only roots are skipped (unwritable in-cage).
4. **Marker semantics are file-based and dumb on purpose.** `gitcheck/baseline.json` + `gitcheck/pending` (launch timestamp and roots). Written before the containers start; removed only by a clean check or `--ack`; set again by any check with findings (the flag reflects the latest verdict). **Found in the live run:** `--ack` must also re-baseline — otherwise the teardown check re-reported the very findings the operator had just acknowledged — so an acknowledgement accepts the current state as the new baseline and only later writes are reported. A crash cannot run code that removes it, so a crash leaves it — that is the whole crash-safety story, and `tjor ls` scanning the state root for markers is what makes it visible.
5. **Three call sites, one helper.** `gitcheck_run <session dir> <moment>` runs the check, renders findings through `safeprint`, clears the marker when clean, and never changes its caller's exit code at exit/teardown (a teardown must complete; the harness exit code is the harness's). `tjor git-check` is the one caller whose exit code carries the verdict.
6. **`tjor git-check <repo>` searches baselines, not containers.** It canonicalizes the path and picks every session baseline whose roots cover it (equal or ancestor), so a repository mounted in several sessions is checked against each; no argument means the current workspace's default session. Dispatched before preflight: it needs git and python, not a daemon.
7. **Announcements and rendering.** Findings print one line each: `tjor: git-check FINDING <repo>: <class> <key/path> <old> -> <new>`, every untrusted field through `safeprint`. A clean check prints one line naming the moment. `tjor ls` prints one warning line per pending session.

## Risks / Trade-offs

- [The window is narrowed, not closed] → said in the proposal, the spec's purpose, the README and every report line's wording ("would run on the host"); the pre-use gate is the operator's tool for the gap.
- [A busy repo could produce noise from legitimate config edits] → only the dangerous set is diffed; `branch.*`, `remote.*.url/fetch/push`, `user.*` and everything else are excluded by construction and tested.
- [Deep trees make the baseline slow] → depth cap of 12 and a walk that prunes at each `.git`; the announcement names the count.
- [Hook hashes change if the operator edits hooks on the host mid-session] → reported as a hook change; the operator recognizes their own edit and acknowledges.
- [`tjor ls` now reads the state root] → read-only, marker files only; no change to the label-driven table.

## Migration Plan

Additive: a module, a command, three report lines. Patch release. Rollback is a revert; markers under `gitcheck/` are inert files.

## Open Questions

None that change the specs or tasks. Whether `tjor down` should exit non-zero on findings is deliberately no: teardown must complete; the gate is `git-check`.
