# Proposal

## Why

When tjor runs from a git checkout, the host executes `bin/tjor` and `python/*.py` from that checkout on every invocation, and ADR 0008 makes a checkout always build the agent and proxy images from the same tree. If that checkout — or any ancestor of it — is mounted **writable** into a session (as the workspace or a `--dir`), code running in the cage can rewrite the launcher and host-side Python (which then run **unsandboxed** on the next `tjor` call), the proxy image sources (the component holding the session MITM CA key and brokered credentials, ADR 0007), and the agent entrypoint (which runs as root at the start of every later cage). One write persists into every future session and onto the host (#67). The natural trigger is legitimate: developing tjor inside a tjor session, launched via the checkout's own `bin/tjor`, with the checkout (or a parent) as the workspace. Nothing warns today.

## What Changes

- **BREAKING (by design): the running tjor tree is refused as a writable mount.** At launch, after every mount root is canonical and final, the launcher compares its own root (`TJOR_ROOT`, already physical) against each writable root — the workspace and every `--dir`. Equal, under, or containing a writable root aborts the launch, naming both paths and the three remedies. `--allow-self-mount` is the explicit, loud override (disposable setups). A read-only overlap (`--dir-ro` of the checkout) is allowed with a one-line notice. This applies to any root, checkout or installed: an installed tree inside a writable mount is the same write→execute path.
- **`tjor self-install [--ref <commit-ish>]`** produces an immutable copy of a committed tree: `git archive <ref>` into `~/.tjor/install/<sha>/`, a `.tjor-source-sha` marker, `chmod -R a-w`, and a `~/.tjor/install/current` symlink to point launchers at. It prints the path and, when a previous install exists, `git log --oneline` between the two. Idempotent for an already-installed sha. Honest scope: `a-w` is a guard against accidental edits (the agent runs as the host uid and could re-add write permission); the boundary is the refusal above plus the fact that the install root lives outside every ordinary workspace — which is exactly what lets a developer work on the checkout from inside a session launched by an installed tjor.
- **The install root joins the sensitive set (#64).** `~/.tjor/install` (or the configured install root) is refused as a workspace or `--dir`/`--dir-ro` like the session root and config dir: a session launched by *another* tjor must not be able to rewrite an installed tree that a launcher points at. `--unsafe-dir` overrides, loudly.
- **A self-installed tree builds locally, like a checkout.** ADR 0008 decision 1 extends from "a git checkout" to "a source tree" — `.git` or the `.tjor-source-sha` marker. Only a release install (Homebrew) pulls prebuilt images.
- **Images record their source.** Every local `docker build` (agent, proxy, conformance) carries `--label tjor.source-sha=<sha>`: the marker's sha for an installed tree, `git rev-parse HEAD` (`-dirty` when the work tree has changes) for a checkout, `release-<VERSION>` otherwise.
- **`tjor doctor` reports launcher mutability.** The root line says which kind of tree is running (mutable git checkout; self-installed `<sha>`, read-only; installed release). For a checkout it also warns when launching from the current directory would mount that checkout writable, with the remedy. Scoping note: the issue's "whether any configured profile mounts it writable" has no equivalent in tjor — profiles (#29) overlay agent definitions and declare no mounts; mounts are per-invocation flags — so doctor checks the launch-from-here case instead.
- **Coverage becomes visible.** A daemon-free launcher test in the `unit` CI job proves the refusal, the override, the read-only notice, self-install's properties, the marker-driven local build, the label, and the doctor report; the boundary matrix gains a `self-mount` suite; specs are amended.

## Capabilities

### New Capabilities

- `launcher-integrity`: the launcher's own code tree is protected from the sessions it launches — the writable self-mount refusal and its override, `tjor self-install` and the immutable source tree it produces, the `tjor.source-sha` image label, and the `tjor doctor` mutability report.

### Modified Capabilities

- `image-distribution`: "Launcher prefers a published image, falls back to build" gains the source-tree exception that ADR 0008 records but the spec never stated — a git checkout **or a self-installed tree** always builds locally; only a release install pulls.
- `session-launch`: "Sensitive host paths are refused as the primary workspace" — the sensitive set gains the effective tjor install root (equal, ancestor, descendant), with one scenario.

## Impact

- **Code**: `bin/tjor` — self-mount guard in `cmd_run` (after the overlap check, before image resolution), `--allow-self-mount` flag, `cmd_self_install`, `source_sha()` + `--label` on the three builds, `resolve_agent_image` marker condition, `init_sensitive_roots` third root, `cmd_doctor` report, usage text and `main` dispatch. `python/gen_boundary_matrix.py` — `self-mount` suite; `docs/boundary-matrix.md` regenerated.
- **Tests**: new `tests/integration/self_mount_test.sh` (sourced launcher, docker shim, temp `HOME` under `~/.tjor/tmp`; the real checkout as `TJOR_ROOT`), wired into the `unit` job.
- **Docs**: README (running from a checkout: the refusal and `self-install`), INSTALL.md (a "Developing tjor inside tjor" recipe), ADR 0008 amendment (source tree, label), CHANGELOG `[Unreleased]` (Security, **BREAKING**).
- **Behavior change**: launches that mount the running tjor tree writable are refused unless `--allow-self-mount`; `~/.tjor/install` is refused as a mount unless `--unsafe-dir`; images gain a label; `tjor doctor` prints one more line. Homebrew installs and ordinary repository workspaces are unaffected.
- **Out of scope**: image signing/attestation (ADR 0008 follow-up), masking the checkout read-only inside the cage (rejected in #67: it breaks developing tjor inside a session, which refusal + `self-install` keeps).
