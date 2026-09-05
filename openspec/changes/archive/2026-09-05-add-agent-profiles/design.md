# Design: add-agent-profiles

## Context

Instruction cargo (#24) already renders image-baked instructions into each
harness's config dir at start, symlink-safe. A profile is the same idea from a
*host* source the user chose: overlay their agent/command/skill definitions on
that baseline. The `--dir` machinery (#20) already resolves a host path, checks
it is shareable into the VM engine, and mounts it. This change composes those
two mechanisms; the only genuinely new decision is how to do it without
importing host credentials.

## Goals / Non-Goals

**Goals:** opt-in, per-session, reusable population of harness definitions from
a host dir; zero host credentials in the cage, enforced structurally; overlay
semantics (profile wins over the versioned baseline); the agent cannot mutate
the source.

**Non-Goals:** converting definitions between harness formats; a profile
registry/marketplace; writing definitions back out; the broader "task profile"
(permission tier + runtime + model route).

## Decisions

- **Allow-list, host-side, copy-not-mount-the-source.** The launcher copies
  only known definition subdirectories (`agent`/`agents`, `command`/`commands`,
  `skill`/`skills`, `prompt`/`prompts`, `mode`/`modes`) from the profile source
  into `${SESSION_DIR}/profile/`, then mounts *that* staging dir read-only. The
  source is never mounted, so a sibling `auth.json` / API key in `~/.opencode`
  is neither copied nor readable from inside the cage. Filtering host-side (not
  in the entrypoint) means secrets never cross the container boundary at all.
  *Alternative — mount the source read-only and filter in the entrypoint:*
  rejected, because the whole source (creds included) would then be readable at
  the mount path even if we only *deploy* a subset. *Alternative — blocklist
  auth files:* rejected; an allow-list fails safe when a harness introduces a
  new secret filename we haven't heard of.
- **Overlay on instruction cargo, profile wins.** The entrypoint deploys image
  instruction cargo first (versioned baseline), then copies the staged profile
  over it into the active harness config dir. Conflicts resolve to the user's
  definition. Symlink-safe (de-symlink each target as instruction cargo does),
  since the home persists across sessions.
- **Opt-in selection is the trust boundary.** A repo config (#22) needs
  `tjor trust` because it rides along with code you may not have written; a
  profile is you naming your own directory, so the `--profile`/`--profile-dir`
  /`[profiles]` selection *is* the consent — no content-hash store. Documented
  clearly that a profile carries instructions the agent will follow.
- **Deploy into the active harness config dir.** The staged profile is copied
  into the same per-harness dir instruction cargo targets (opencode
  `~/.config/opencode/`, claude `~/.claude/`, copilot `~/.copilot/`). A
  profile's contents must already be in that harness's format — tjor deploys,
  it does not translate. Documented.
- **Stage host-side into the session dir — no VM-share check on the source.**
  The launcher reads the profile source directly (host process) and copies the
  filtered definitions into `${SESSION_DIR}/profile/`; only that staged dir is
  bind-mounted, and it lives under the session dir, which is already
  VM-share-verified. So the profile *source* may live anywhere the launcher can
  read (not just under `$HOME` on Colima), and no separate `verify_bind_source`
  is needed — an improvement over `--dir`, whose source must itself be shared.

## Risks / Trade-offs

- **A profile is instructions the agent executes.** Populating a session from a
  profile is a trust choice (it's the user's own dir, opted into explicitly) —
  documented, not gated by a hash store. The credential allow-list bounds the
  *data* exposure; the *instruction* exposure is the point of the feature.
- **Format mismatch across harnesses.** An opencode profile deployed into a
  claude/copilot session lands as files those harnesses may ignore. Harmless
  (no error), documented; translation is a non-goal.
- **Symlinked definitions in the source.** The host-side copy dereferences
  files it copies but only from within allow-listed subdirs; a symlink inside
  `agent/` pointing at `~/.ssh/id_rsa` would be followed by a naive copy — so
  the staging copy refuses to follow symlinks that escape the source subtree
  (copy is `cp -RL`-free: we copy regular files/dirs, skipping symlinks that
  resolve outside the profile source).

## Verification approach

Unit tests for the allow-list filter: allowed subdirs are staged; `auth.json`,
`.credentials.json`, an API-key file, and unknown top-level files are NOT; a
symlink escaping the source is not followed. An integration test runs the real
entrypoint with a staged profile and asserts an agent definition lands in the
harness config dir while a credential file placed in the source never appears
anywhere in the container. No live model run needed.
