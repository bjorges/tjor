# Proposal: add-agent-profiles

## Why

The cage deliberately isolates from host config, so the agents, commands, and
skills you've defined for your harness (e.g. in `~/.opencode`) don't reach a
caged session — the agent runs without *your* setup. This is correct as a
default (the cage shouldn't silently absorb host state), but you should be able
to **opt in** to bringing your own agent profile into a session and reuse it
across sessions. tjor's job is not to own your agent definitions; it's to
provide the *mechanism* to populate a session with them, safely.

The one hard constraint: doing this must not smuggle host **credentials** into
the cage. A harness config dir like `~/.opencode` often also holds an
`auth.json` / API keys, and the cage's whole point is that the agent never
holds those. So a profile must carry *definitions* (agents/commands/skills),
never secrets — enforced structurally, not by asking the user to be careful.

## What Changes

- A **profile** is a host directory of harness definitions. Select one per
  session with `tjor run --profile <name>` (resolved from a `[profiles]`
  config map of name → host dir) or ad-hoc with `--profile-dir <path>` (e.g.
  `~/.opencode`).
- **Credential-safe by construction.** The launcher copies only an
  **allow-list of definition subdirectories** (`agent`/`agents`,
  `command`/`commands`, `skill`/`skills`, `prompt`/`prompts`, `mode`/`modes`)
  from the source into a per-session staging dir, host-side. Auth/credential
  files (`auth.json`, `*.credentials*`, dotfiles, anything not on the
  allow-list) are never copied and never mounted, so they cannot reach the
  agent even by direct read. Only the filtered staging dir is exposed to the
  container (read-only).
- **Deployed as an overlay** on the image's instruction cargo: the entrypoint
  copies the staged profile into the active harness's config dir on top of the
  versioned baseline (your definitions win on conflict), symlink-safe, per the
  same render-at-start mechanism as instruction cargo (#24).
- **Opt-in is the trust decision.** Unlike a repo config (#22, which travels
  with untrusted code and needs `tjor trust`), a profile is *you* pointing at
  *your own* directory — the explicit `--profile`/config selection is the
  consent. Documented: a profile carries instructions the agent will follow.

Out of scope: turning profiles into full "task profiles" (instruction bundle +
permission tier + runtime + model route — the agent bundle is one axis of that
larger idea, tracked separately); syncing definitions back out of the cage;
per-harness *translation* of definitions (a profile's content must match the
active harness's format — tjor deploys, it does not convert).

## Capabilities

### Added Capabilities

- `agent-profiles`: opt-in population of a session's harness config with
  host-defined agent/command/skill definitions from a chosen profile dir,
  credential-safe by an allow-list, deployed as an overlay on instruction cargo.

## Impact

- Code: profile resolution + host-side allow-list staging in the launcher
  (`--profile`/`--profile-dir`, `[profiles]` config), a read-only staging mount
  + env, an entrypoint overlay-deploy stage, docs. Reuses the bind-source
  VM-share check (like `--dir`) and the symlink-safe deploy (like instruction
  cargo). Unit tests for the allow-list filter (esp. that credential files are
  excluded) + an integration test that a profile's agents land in the harness
  config while `auth.json` does not.
- No breaking changes: no profile selected → behavior is exactly as today.
