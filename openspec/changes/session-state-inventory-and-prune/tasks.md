# Tasks

## 1. State helper (`python/tjor_state.py`)

- [ ] 1.1 Create `python/tjor_state.py` with the tier definitions (`cache`, `sessions`, `creds`, `all`) as the single source of truth and a `tier <name> <state-dir>` subcommand printing absolute paths one per line; verify `python/tests/test_state.py` asserts the `creds` tier equals today's `cmd_reset` list (`broker`, `proxy-ca`, `ca.pem`, `home/.local/share/opencode/auth.json`, `home/.config/gh`) and that `all` is the directory itself.
- [ ] 1.2 Add `duration <text>` (`Nd`, `Nh`, `Nm`, `Ns` → seconds; anything else exits non-zero with a message); verify unit tests cover each unit, `0d`, and rejection of `30`, `-1d`, `1w`.
- [ ] 1.3 Add `meta-write <state-dir> --session --workspace --harness [--profile-name|--profile-dir] [--task]`: read-modify-write via a temp file and `os.replace`, preserve `created`, bump `launches`, set `last_launch`, `schema: 1`; verify unit tests cover first write, relaunch with a new task (created kept, launches 2), an unreadable existing file (rewritten, not crashed), and that the written keys are exactly the documented set.
- [ ] 1.4 Add `inventory <root> --json`: one record per entry of the root (`id`, `is_dir`, `meta` or null, `last_active` = max `lstat` mtime over the entry and its contents to depth 3 with `followlinks=False`, floored by `meta.last_launch`, `creds` = the present `creds`-tier paths); verify unit tests cover a legacy dir (meta null, mtime from `home/`), a current dir, a symlink entry (reported with `is_dir: false`, target untouched: a canary file behind the link is never stat'ed, asserted with a fake `lstat`/`os.walk` spy or an unreadable target), and the depth bound.
- [ ] 1.5 Run `python -m pytest python/tests -q` and verify every new test passes alongside the 503 existing ones.

## 2. Launcher: metadata and reset refactor (`bin/tjor`)

- [ ] 2.1 In `cmd_run`, right before `ensure_topology`, call `meta-write` with `TJOR_SESSION`, `TJOR_WORKSPACE`, the harness, the `--profile`/`--profile-dir` value and `TJOR_TASK_ID`; verify a live launch produces `<state>/meta.json` with those fields and a refused launch (sensitive `--dir`) creates none.
- [ ] 2.2 Replace `cmd_reset`'s tier `case` with `mapfile -t paths < <(python3 "${TJOR_ROOT}/python/tjor_state.py" tier "${tier}" "${TJOR_SESSION_DIR}")`, keeping the running-session guard, dry-run and `ancestors_are_real_dirs` loop unchanged; verify the lifecycle suite's reset section (tier contents, leaf symlink removed, intermediate symlink refused) still passes and `shellcheck --severity=warning bin/tjor` is clean.

## 3. Launcher: `ls --state` and `prune` (`bin/tjor`)

- [ ] 3.1 Add `--state` to `cmd_ls`: run `inventory` on the resolved `session.root`, join with `docker ps --filter label=tjor.session=<id> --filter status=running` per id (`?` when docker fails), print `SESSION RUNNING LAST-ACTIVE CREDS WORKSPACE` sorted by id plus one line per non-directory entry; plain `ls` unchanged; verify live: a legacy dir (no meta) shows `unknown`, a current one shows its workspace, a running session shows `yes`, and the plain `ls` output is identical to before.
- [ ] 3.2 Add `cmd_prune` (dispatch + `usage` line): parse `--older-than <dur>` (via `duration`), repeatable `--session` (each through `resolve_session`, as `reset` does), `--creds-only`, `--dry-run`, `--force`; refuse with usage and exit 1 when no selector; select the union; verify live: bare `tjor prune` exits 1 and removes nothing; `--older-than` with one old and one fresh dir names only the old one.
- [ ] 3.3 Per selected session, in this order: refuse if any container is running (any role; no override) naming `tjor down`; refuse if docker cannot be queried; refuse if `<state>/gitcheck/pending` exists unless `--force`, naming `tjor git-check --session <id>`; then delete the whole directory (`ancestors_are_real_dirs "${root}" "${dir}"`) or, with `--creds-only`, each `creds`-tier path (`ancestors_are_real_dirs "${dir}" "${p}"`), `loud` on refusal and continue, exit non-zero if anything was refused; print `would remove` / `removed` / `refused: …` with the credential flags and "forgotten, not revoked" when a broker file goes; verify live via the checks in 4.1.

## 4. Live checks (`tests/integration/lifecycle_test.sh`)

- [ ] 4.1 Add a section after the reset section: plant a legacy dir (no meta) and a fresh one with creds-tier files; `ls --state` lists both with correct `unknown`/workspace and credential flags; bare `prune` refused; `prune --session a` refused while `a` runs (agent) and again with only sidecars (stop the agent container first); a pending marker refuses without `--force` and prunes with it; a planted intermediate symlink under a selected dir is refused for `--creds-only` while the other path is still removed and the outside canary survives; `--dry-run` lists and preserves; `--creds-only` removes exactly the creds tier and keeps `home/.local/state`; a real `--older-than 0d` prune of the legacy dir removes it and leaves the running session's dir; verify the suite passes locally with Docker and in the CI lifecycle job.
- [ ] 4.2 Verify `tjor gc --dry-run` output and behaviour are unchanged by grepping the existing gc checks still pass in the same run.

## 5. Docs and deck

- [ ] 5.1 README "Managing sessions": add `tjor ls --state` and `tjor prune --older-than 30d --dry-run` to the console block and a paragraph: state persists until you prune; prune is explicit, dry-runnable, refuses running sessions and pending git-check markers, forgets rather than revokes (revocation is `down`/`gc`); `usage()` in `bin/tjor` lists both; verify `tests/doc_consistency.sh` passes and the README commands run as written.
- [ ] 5.2 `CHANGELOG.md` under `## [Unreleased]` → `### Added`: metadata at launch, `ls --state`, `prune` with its refusals, the shared tier definition (#68); verify `tests/doc_consistency.sh` passes.
- [ ] 5.3 Overview deck (`slides/agents.md`, "Keeping the deck in sync"): re-read the lifecycle slide for both changed specs, add `tjor ls --state` / `tjor prune` to its command block and state the residual (state stays until pruned; prune forgets, does not revoke), re-pin `session-lifecycle@…` and `session-launch@…` on every slide that tags them; verify `tests/slides_consistency.sh` passes and `cd slides && pnpm check && pnpm build` renders the slide without overflow.

## 6. Integration gate

- [ ] 6.1 Run every local gate and report: `python -m pytest python/tests -q`, `tests/doc_consistency.sh`, `tests/slides_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/lifecycle_test.sh`, `openspec validate --specs`; then open the pull request from the branch (never push `main`) and verify every CI job including the live lifecycle job is green.

## Workflow follow-up

- Archive the change on the same branch (syncs the two spec deltas into `openspec/specs/`), then re-run `tests/slides_consistency.sh` and fix the pins if the sync changed the spec files' bytes.
- Close #68 from the pull request body.
