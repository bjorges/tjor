# Proposal

## Why

v0.21.0 masks `.git/hooks` structurally and offers an opt-in pin for `.git/config`. What it cannot prevent, it says so: with the pin off (the default), a session can still set `core.hooksPath`, `core.fsmonitor`, a filter driver or a `!`-alias in a writable repo's config; it can re-point a worktree's `.git` file or `commondir`; it can plant a nested `.git/` inside the working tree. Each of those runs code in the operator's **host** git the next time an ordinary command touches the repo, and the write lands on the host filesystem the moment the cage makes it. If the operator runs host-side git before the session ends, or the session dies abnormally so no teardown report ever runs, the exploit already fired with zero warning (#72). This change narrows that window and makes exposure visible. It does not close it, and never claims to.

## What Changes

- **A baseline at launch, stored out of the agent's reach.** For every writable mount root the launcher records, per discovered git directory: the dangerous config keys present (a documented set: hook, editor, pager, ssh, credential, filter, diff/merge driver, alias `!`, include, remote helper/proxy, `url.*.insteadOf`, `safe.*`, `extensions.*`), whether the config file is a symlink, the worktree pointers (`.git` files, `worktrees/*/{gitdir,commondir}`), hashes of hook files, and the nested repositories already present. The baseline and a **pending marker** live under the session state directory, which is never mounted into the cage.
- **A check that diffs the present against the baseline.** It reports, loudly and escape-sanitized: a dangerous key added, changed or removed (repo, key, old, new); an include added; a config file that became a symlink; a worktree pointer that changed; a hook file that changed; a nested repository that appeared; a baseline repository that vanished. Benign writes — `branch.*`, `remote.*.url/fetch/push`, `user.*` — are not findings, so `push -u` never trips it.
- **Three moments the check runs.** When an attached session's harness exits, at `tjor down`, and on demand with `tjor git-check [<repo> | --session <id>] [--ack] [--json]`. The pending marker clears **only** on a clean check or an explicit `--ack`; findings leave it in place.
- **Crash-safety.** A session killed with `SIGKILL`, crashed, or closed with its terminal never reaches a check, so its marker stays. `tjor ls` lists every session with a pending marker and the command that clears it.
- **A pre-use gate.** `tjor git-check <repo>` exits non-zero on findings, so an operator can wire it into their own shell before running host-side git in a repo with a pending marker. tjor ships no hook of its own.

## Capabilities

### New Capabilities

- `git-tamper-detection`: the launch-time baseline, the check and its finding classes, the three check moments, the pending marker's lifecycle, the `ls` surfacing, the on-demand command and its exit code, and the benign-write exclusion.

### Modified Capabilities

(none — `kernel-sandbox`'s masks are the preventive half and are unchanged; this capability is the detection half and stands on its own.)

## Impact

- **Code**: `python/tjor_gitcheck.py` (snapshot, check, the dangerous-key set, the diff; the one place that decides); `bin/tjor` — baseline + marker in `run_agent` once the mount set is final, the check before the attached exit and in `cmd_down`, the pending report in `cmd_ls`, `cmd_git_check` dispatched before preflight (needs git and python, not a daemon), usage.
- **Tests**: `python/tests/test_gitcheck.py` (every planted pattern reported; `push -u`-shaped writes clean; symlinked config; worktree pointers; nested repo; hooks); `tests/integration/gitcheck_test.sh` (daemon-free, `unit` job: baseline + marker through the launcher's helpers, `git-check` exit codes, `--ack`, the pending report); a new `gitcheck` suite in the boundary matrix.
- **Docs**: README (a "Git metadata check" subsection under the kernel-sandbox section, the dangerous-key set, the three moments, the gate recipe), CHANGELOG `[Unreleased]` (Security, not breaking).
- **Behavior change**: three new report surfaces; no launch is refused; nothing is prevented. Patch release.
- **Honest limits**: detection only; a write fires on the host the moment it lands, so the window is narrowed, not closed; the nested-repo scan is depth-limited; a repository created mid-session is checked only if it appears under a baseline root.
