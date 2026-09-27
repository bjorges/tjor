# Tasks

## 1. The module

- [x] 1.1 `python/tjor_gitcheck.py`: the dangerous-key predicate (design D2) with a module docstring listing the set; `discover(roots)` (design D3); `snapshot(roots) -> dict` per git dir: config path + symlink flag, dangerous keys via `git config --file … --no-includes --list -z`, includes, worktree pointers (`.git` file text, `worktrees/*/{gitdir,commondir}`), hook hashes, nested repositories; `diff(baseline, current) -> findings` with the classes in the spec; CLI `snapshot --out FILE ROOT…` / `check BASELINE [--json]` (exit 1 on findings); untrusted strings rendered through the shared sanitizer. Verify: 1.2 passes
- [x] 1.2 `python/tests/test_gitcheck.py`: temp repos via `git init`; every planted pattern reported (dangerous key added/changed/removed, include added, symlinked config, re-pointed worktree `.git` file and `commondir`, hook file added, nested `.git` planted, baseline repo vanished); `branch.*`/`remote.*.url`/`user.*` writes are clean; `alias.x = !cmd` flagged while `alias.x = status` is not; a `--dir` root and a nested repo both baselined; JSON round-trip. Verify: `uvx … pytest python/tests/test_gitcheck.py -q` passes

## 2. Launcher wiring

- [x] 2.1 `bin/tjor`: `gitcheck_baseline()` called in `run_agent` once the mount set is final and before any container starts — writes `${TJOR_SESSION_DIR}/gitcheck/baseline.json` and `pending`, announces the repo count; `gitcheck_run <dir> <moment>` renders findings via `safeprint`, clears the marker when clean, never alters the caller's exit code; called before the attached exit in `run_agent` and in `cmd_down` after the topology is removed (design D4/D5). Verify: `shellcheck --severity=warning bin/tjor` clean; 3.1 checks
- [x] 2.2 `cmd_ls`: after the table, scan the session root for `gitcheck/pending` markers and print one warning per session naming its repos and `tjor git-check --session <id>`. Verify: 3.1 pending-report check
- [x] 2.3 `cmd_git_check [<repo> | --session <id>] [--ack] [--json]` dispatched before preflight: `--session` → that session's baseline; `<repo>` → every baseline whose roots cover the canonical path; no argument → the current workspace's default session; exit non-zero on findings, zero after `--ack`; usage line (design D6). Verify: 3.1 exit-code and ack checks

## 3. Launcher test (daemon-free, `unit` job)

- [x] 3.1 `tests/integration/gitcheck_test.sh` (pattern: `workspace_gate_test.sh`; docker shim): baseline for a temp repo + `--dir` repo via `gitcheck_baseline` with a temp session dir; marker exists; plant `core.hooksPath` → `cmd_git_check --session` exits 1, names repo/key/value, marker stays; `--ack` clears, exits 0; re-baseline, benign `branch.*` write → `cmd_git_check` exits 0 and clears; `<repo>` argument finds the covering session; `gitcheck_pending_report` lists a session with a marker and nothing after ack; `tjor ls`'s pending line via the same function. Verify: `bash tests/integration/gitcheck_test.sh` passes; wired into the `unit` CI job
- [x] 3.2 `python/gen_boundary_matrix.py`: a `gitcheck` suite (launcher-side) with REGISTRY entries; rendered rows under a new `git-tamper-detection` capability: planted key reported, marker survives findings, ack clears, benign write clean, pending session surfaced; regenerate `docs/boundary-matrix.md`. Verify: `--check` clean; `tests/doc_consistency.sh`

## 4. Docs

- [x] 4.1 README: a "Git metadata check" subsection under the kernel-sandbox section — the three moments, the dangerous set (why `url.*.insteadOf` and `safe.*` are in it), the marker and `tjor ls`, the gate recipe (`tjor git-check "$(git rev-parse --show-toplevel)" || …` in the operator's own shell), the honest limits. Verify: `tests/doc_consistency.sh`
- [x] 4.2 CHANGELOG `[Unreleased]` — Security (not breaking): what is detected, when, the marker, the gate, the limits, #72/#71 references. Verify: entry present

## 5. Verification

- [x] 5.1 Local gate: `uvx … pytest python/tests -q`, `bash tests/integration/gitcheck_test.sh`, `bash tests/integration/workspace_gate_test.sh`, `tests/doc_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/*.sh`, `npx --yes @fission-ai/openspec@latest validate git-tamper-detection`. Verify: all green
- [x] 5.2 End-to-end on the live engine (**observed 2026-09-27 on colima**: a session that set `core.hooksPath` and exited produced one FINDING line at session exit naming the repo, the key and `null -> ".planted"`; `tjor ls` listed the session as UNCHECKED with the repo and the clearing command; `tjor git-check --session` exited 1 with the finding; `--ack` exited 0, cleared the marker and re-baselined; `tjor down` then reported a clean check and completed): a session whose command sets `core.hooksPath` in the workspace config, then exits → the launcher reports the finding at exit; `tjor ls` shows the session as unchecked; `tjor git-check` exits 1; `--ack` clears; `tjor down` runs clean. Record the observations in tasks.md. Verify: recorded
