# Proposal

## Why

With tjor 0.23.0 (opencode 2.2.7, Bun 1.4.4) a session launched under the kernel-sandbox tier cannot start opencode: `opencode --standalone` fails with `Standalone server exited before reporting readiness`, and the same session with `[landlock] mode = "off"` works (#103). The oc-personal and oc-tieto profiles are unusable with the tier active.

The trigger is now identified and reproduced in the released image. cplt's Landlock backend without Bubblewrap grants `/proc/self` to the first sandboxed process only: the rule is resolved in the child before `exec`, so it becomes a rule on that one pid's `/proc/<pid>` directory. Every process forked below it gets `EACCES` on its own `/proc/self/*`. opencode v1 ran in one process. v2 spawns a second Bun process for its server (`opencode serve --stdio` under `--standalone`, `opencode serve --service` otherwise), and Bun aborts during JavaScriptCore VM creation when it cannot read its own `/proc/self/maps` (glibc's `pthread_getattr_np` reads it to find the main thread's stack; the crash report decodes to `JSC::VM::tryCreate` → `abort()`). cplt's maintainers met the identical failure (navikt/cplt PR 740: "the service is a child of the client and does not get the client's /proc/self grant, so Bun aborts at startup") and answered it with Bubblewrap, whose pid namespace makes granting all of `/proc` safe; without Bubblewrap the current cplt refuses opencode v2 outright.

The failure is not opencode-specific. Claude Code's binary is Bun-compiled too, and any Bun child under the wrap (an MCP server, `bunx`, a Bun test runner the agent installs) has been latently broken since the tier shipped; v2 only made it unconditional. It is not seccomp, not `--standalone`, and not fixed by a cplt bump: the 2026-11-06 release crashes the same way in `exec` mode and prints a hint that names `--allow-read /proc` as the fix when the exposure is acceptable.

Charter lessons answered: L18 (a hardening tier degrades loudly, never silently) and the AGENTS.md rule that a mechanism without a stated residual is suspicious: a kernel grant on `/proc` is a residual and is stated as one.

## What Changes

- **The wrap grants `/proc` read-only.** `images/agent/entrypoint.sh` adds `--allow-read /proc` to the cplt invocation, for every harness and every launch mode. The container already provides what cplt wants from Bubblewrap, its own pid namespace, so the grant exposes the cage's own processes; no host process is visible. Verified in the released image with the entrypoint's flag set and the pinned cplt: `opencode --standalone run ping` answers; `session list`, `debug config` and `models` succeed with networking disabled; a forked child reads its own `/proc/self/maps`; a path the ruleset denies stays denied when reached through `/proc/<pid>/root`.
- **The kernel-sandbox spec's granted-trees requirement is modified** to name both grants among the system paths needed to run, with the read-only scope, the link invariant, what the `/proc` grant exposes and what bounds it.
- **The wrap grants `/etc/opencode` read-only when it exists.** Found while proving the fix: the directory holding a hardened profile's root-owned `managed/opencode.json` is outside cplt's system grants, so under the wrap the managed settings silently did not load. The grant makes them apply under the tier.
- **Proof in the Landlock suite, which becomes a CI job.** The live-session probe pairs each direct denial with its `/proc` link (`/proc/self/root`, a `/proc/self/cwd` traversal, PID 1's `environ`/`root`/`cwd`, an unsandboxed same-uid process's `fd` and `environ`), records the stated residuals (command lines, kernel status files, same-sandbox `environ`), asserts `/proc` is not writable, loads a sentinel key from the managed config, and launches opencode v2 both with `--standalone` and in the shipped default service mode (fresh state, a second invocation reusing the service, the service reachable on its loopback URL, no service surviving `tjor down`, a relaunch with the stale registration starting a fresh service). A new `landlock` job runs the suite on a Linux runner in strict mode, where a missing Landlock or a missing `opencode` fails instead of skipping. Every check is registered in `python/gen_boundary_matrix.py`; the matrix is regenerated.
- **Documentation.** README kernel-sandbox section: the grant and its residual. `docs/decisions/0015-proc-read-inside-the-kernel-tier.md`: why the grant is the right answer in-cage and what it exposes. The kernel-sandbox slide is re-read and re-pinned. `CHANGELOG.md` gets a Fixed entry under Unreleased.

Deferred, deliberately: making `--standalone` the shipped default for opencode (`config/tjor.toml` ships `args = []`, the service mode; it is now tested, and a stdio child would only be the simpler lifecycle); a cplt pin bump (unrelated to this failure); an upstream report to Bun asking for a graceful fallback when `/proc/self/maps` is unreadable.

Rollback: `[landlock] mode = "off"` disables the tier without a rebuild (the #103 workaround, which this change makes unnecessary), or the previous image tag.

Compatibility: additive. A session whose runtime has no Landlock is unchanged. A session with the tier active gains one read-only kernel grant; nothing else in the wrap moves.

## Capabilities

### Modified Capabilities
- `kernel-sandbox`: the granted-trees requirement now names `/proc` and `/etc/opencode` among the read-only system grants, with the link invariant and the stated residual.

## Impact

- `images/agent/entrypoint.sh`: two grants in the `wrap` array and their rationale comments.
- `tests/integration/landlock_test.sh` (strict mode, the part A probe, a second launch), `.github/workflows/ci.yml` (the `landlock` job; the ruleset on `main` must list it by name before merge, CONTRIBUTING "Repository settings"), `python/gen_boundary_matrix.py`, `docs/boundary-matrix.md` (regenerated).
- `openspec/specs/kernel-sandbox/spec.md` (via archive), `slides/presentations/overview/slides.md` (kernel-sandbox slide re-pinned, residual sentence), `README.md`, `CHANGELOG.md`, `docs/decisions/0015-proc-read-inside-the-kernel-tier.md`.
