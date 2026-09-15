# Design — read-only mounts + untrusted project-config neutralization

## Context

See proposal.md for motivation. Load-bearing current facts:

- `--dir` extras are resolved in `cmd_run` (`bin/tjor`), mounted read-write in
  `run_agent` (`--volume dir:dir`), and folded into `TJOR_SAFE_DIRS`
  (newline-delimited) which the entrypoint consumes twice: git
  `safe.directory` (step 3) and cplt Landlock grants (step 6,
  `--allow-write` per extra dir).
- Dotenv masking iterates the same `safe[]` array; `deny_paths` masking is
  independent of `mask_dotenv` (#48). Status lines route through
  `safeprint()` (v0.15.0 escape-injection fix).
- Config shape validation (#39): a `[landlock]` key absent from
  `config/tjor.toml` aborts the launch — `mask_dirs` must be added to the
  defaults file to become part of the shape.
- Profile staging (`tjor_profile.py stage`) copies a structural allow-list of
  subdirs into `${TJOR_SESSION_DIR}/profile`, mounted `:ro` at
  `/opt/tjor/profile`; the entrypoint overlays every staged file into each
  harness config dir, with `instructions/AGENTS.md` special-cased.
- The entrypoint runs as root until the `gosu` drop, so it can write
  root-owned files the agent user cannot touch.
- git trust is launch-time-only (#53, solved separately AFTER this change):
  `safe.directory` entries are registered once at container start via an
  unset-all-then-re-add idiom, exact-match only (no prefix/ancestor
  semantics, deliberately no `*` — ADR 0008). A repo/worktree created
  mid-session under an approved mounted parent gets filesystem access but
  no git trust.

Ground truth verified against shipped artifacts (2026-09-15):

- `cplt --help` (navikt/cplt, from `tjor-agent-opencode:local`):
  `--allow-read <PATH>` = "Let the agent read files outside the project
  directory"; `--allow-write <PATH>` = "Let the agent read AND write files
  outside the project directory". So the read-only kernel grant is exactly
  `--allow-read`.
- opencode 1.18.28 bundle (same image): the managed config dir on Linux is
  `/etc/opencode` (`function g0(){switch("linux"){...default:return
  "/etc/opencode"}}`), reachable in the shipped code path — the managed tier
  is live in the version we ship.
- Same bundle: `OPENCODE_CONFIG_DIR` **replaces** the global config
  directory (`config: e.OPENCODE_CONFIG_DIR ?? G.config`) and is treated as
  an extra `.opencode`-style discovery dir. Setting it (as issue #46
  proposed) would redirect opencode away from `~/.config/opencode`, where
  the entrypoint deploys the baseline instruction cargo, `autoupdate:
  false`, and the profile overlay. **Decision: do not set it** — the managed
  tier plus `mask_dirs` deliver the ordering guarantee without breaking the
  existing deployment path.

## Goals / Non-Goals

**Goals:**

- Container-level enforcement first: each control must hold on every
  runtime, with the kernel tier as agreement, not as the only enforcement.
- Zero behavior change for sessions that use none of the three features.
- Fail closed on ambiguity (conflicting `--dir`/`--dir-ro`, malformed
  `mask_dirs` entries, invalid managed JSON).

**Non-Goals:**

- Masking or read-only-izing things created *mid-session* (same documented
  residual as dotenv masking).
- A read-only **primary** workspace (`tjor run` in a repo the agent cannot
  edit) — the harness needs a writable cwd for state; a read-only tree is
  attached via `--dir-ro`.
- Neutralizing a repo-root `opencode.json`'s *additive* declarations (npm
  plugins, local MCP servers) beyond what the managed tier overrides —
  tracked honestly as the pairing gap in #46; `mask_dirs` + managed config
  together close the `.opencode/` + override vectors, and the README states
  what remains.

## Decisions

1. **`--dir-ro` rides the existing extras pipeline, marked by a parallel
   list.** `cmd_run` resolves `--dir-ro` paths with the same
   existence/sensitivity/dedupe logic into `TJOR_EXTRA_DIRS_RO`; `run_agent`
   mounts them `:ro` and threads a newline-delimited `TJOR_RO_DIRS` env into
   the container. The entrypoint greps each `TJOR_SAFE_DIRS` entry against
   the RO set: `--allow-read` for members, `--allow-write` otherwise.
   *Alternative rejected:* encoding an `:ro` marker inside `TJOR_SAFE_DIRS`
   entries — overloads a path-only contract that git consumes verbatim.

2. **Same-path conflict dies.** `--dir X --dir-ro X` aborts. *Alternative
   rejected:* "ro wins" (surprising when a script appends flags) and "rw
   wins" (silently weakens the stricter intent — the wrong failure
   direction for a security tool).

3. **`mask_dirs` entries are absolute paths or bare names, nothing else.**
   A leading `/` means "this exact directory"; no `/` anywhere means
   "discover this basename recursively in every mounted tree" (`find -type
   d -name`, `.git` pruned, NUL-delimited). Anything else aborts.
   *Alternative rejected:* full glob patterns (`*/.opencode`) — glob
   semantics over mount trees invite quoting/expansion bugs in bash and are
   not needed for the motivating cases.

4. **Mask source is a fresh empty dir under the session state root.**
   `${TJOR_SESSION_DIR}/mask-empty` is recreated (`rm -rf` + `mkdir`) every
   launch and bind-mounted `:ro` over each target. `/dev/null` cannot mask
   a directory; the session dir is already VM-shared (CA, profile stage,
   denials log all live there). In-cage the target is empty, unwritable
   (`:ro`), and un-unmountable (mount point, non-root agent).

5. **Managed config deploys in the entrypoint root phase; both sides
   validate.** Host-side, `prepare_profile` dies early (best UX) if the
   staged `managed/opencode.json` is invalid JSON; the entrypoint
   re-validates before copying (defense in depth for non-launcher paths)
   and exits with the boundary code (90) on failure — matching the
   "must never look hardened without being it" stance of `require` mode.
   `install -D -m 0644 -o root -g root` semantics; `managed/` excluded from
   the per-harness overlay loop exactly like `instructions/AGENTS.md`.
   Stale-file removal when nothing is staged keeps restarts idempotent
   (same pattern as the gitconfig unset-first idiom).

6. **`mask_dirs` masking is a sibling of `deny_paths`, not a child of
   `mask_dotenv`.** Applied in `run_agent` next to the existing masking
   loops, sharing the `masked[]` dedupe map and the `safeprint` announce
   discipline. The #48 regression class (a security control silently gated
   by an unrelated flag) is called out in the spec and covered by a test.

7. **Forward compatibility with #53 (dynamic git trust — designed for,
   not solved here).** The likely #53 fix is a mediated, root-privileged
   trust-registration helper that validates a candidate path is a
   descendant of an operator-approved mount root before adding a
   `safe.directory` entry. This change hands that helper its exact
   eligibility input and avoids blocking it:
   - `TJOR_SAFE_DIRS` (approved roots) + `TJOR_RO_DIRS` (their read-only
     subset) become the durable, in-container record of operator-approved
     roots *and their writability class* — documented as a contract at the
     definition site in `bin/tjor`. Dynamic trust should only ever grow
     under a **writable** approved root: a `:ro` mount cannot grow new repo
     roots mid-session, and `git worktree add` also writes the source
     repo's `.git/worktrees/`, so RO roots are structurally ineligible.
   - The kernel tier needs **no** #53 counterpart: cplt/Landlock grants are
     tree-scoped, so a new worktree under a granted parent is already
     covered. #53 must be fixed at the git-trust layer only — never by
     widening kernel grants.
   - The entrypoint's unset-all-then-re-add `safe.directory` idiom means
     dynamically registered entries vanish on container restart; #53's
     design must persist or re-derive them — recorded here so the helper
     is not designed against a wrong assumption.
   *Alternative rejected:* pre-registering anticipated worktree paths at
   launch — the paths do not exist yet, and prefix trust without mediation
   is the `*` regression ADR 0008 forbids.

## Risks / Trade-offs

- [Docker bind-source staleness: `mask-empty` could be polluted host-side
  mid-session] → recreated at every launch; mounted `:ro` so nothing
  in-cage can write it; host-side pollution requires host access, which is
  outside the threat model (host user is the operator).
- [A `--dir-ro` repo still leaks content read-wise] → intended semantics;
  the sensitive-path refusal still applies, and dotenv/deny masking still
  covers it (spec scenario).
- [opencode could change managed-config semantics in a future version] →
  the version is image-pinned; the design records the verified 1.18.28
  behavior; profile_test.sh asserts the structural deployment so a future
  bump that breaks it fails loudly in CI.
- [`find` over huge mounted trees at launch for name-mode `mask_dirs`
  entries] → same cost class as the existing dotenv discovery (already a
  recursive find per mounted tree); only paid when `mask_dirs` is
  non-empty.
- [Nested mounts ordering: dir mask under a `:ro` repo mount] → Docker
  mounts nest by path; the existing dotenv-mask-inside-workspace mount
  relies on the same property today.
- [Solving #53 later will *amplify* the `mask_dirs` launch-time residual: a
  mid-session worktree becomes usable and git-trusted while its fresh
  `.opencode/` is unmasked] → the managed opencode tier (#46) is the
  control that survives mid-session tree growth — which is exactly why a
  hardened profile pairs `mask_dirs` with a managed config rather than
  relying on masking alone. Whether the #53 helper additionally consults
  `mask_dirs` to warn or refuse under a hardened posture is #53's design
  decision; nothing in this change precludes it.

## Migration Plan

Purely additive; no data or config migration. Rollback = revert the commit.
Config key `mask_dirs` appears in the defaults with `[]`, so older user
configs remain valid; a *newer* user config with `mask_dirs` on an *older*
tjor aborts by the #39 strict-validation design — which is the correct
fail-closed direction and is documented in the config comment.
