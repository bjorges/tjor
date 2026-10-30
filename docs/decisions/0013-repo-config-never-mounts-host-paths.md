# ADR 0013 — Repository configuration never names a host path to mount

**Date:** 2026-10-30 · **Status:** accepted

## Context

A repository may carry its own `.tjor/config.toml`, honored after `tjor
trust` approved its exact content (`repo-config-trust`). Until #69 no
configuration key could create a host mount: the workspace comes from where
`tjor run` is launched, extra roots from `--dir`/`--dir-ro` on the command
line, and `session.root` is read once, before the repository layer can answer
(so a repository cannot move the state root). The task notes feature adds a
key, `task.notes_dir`, whose value is a host path the launcher creates below
and mounts **writable** into the cage.

Approval is a review of the file's content, and a reviewer can read a
template. But a mount is a different kind of consequence from a policy
widening: `~/Documents/{task}` is not in the sensitive-path set, and a
repository that could set it would turn an approved config into a writable
bind of an operator directory the repository chose, on every launch, in every
clone of that repository. The planning review of #69 asked which layer
authorises `[task]`; this ADR records the answer.

## Decision

1. **The `[task]` table is user-config only.** `tjor_cfg.effective()` takes it
   from the packaged defaults and the user config (the layer the operator's
   own environment selects: `TJOR_USER_CONFIG`, `XDG_CONFIG_HOME`) and drops
   it from the repository layer before the merge, trusted or not, with a
   warning naming the file and the table. `check()` reports the same and does
   not count the dropped table as an unknown key.
2. **The rule is general:** no key a repository config can set names a host
   path that tjor mounts. A future key of that kind joins `USER_ONLY_TABLES`
   rather than the repository layer. (`session.root` keeps its own, older
   protection: it is read before the repository layer exists.)
3. **`[task]` is a security table** (`SECURITY_TABLES`): an unknown key under it
   in the user config aborts the launch, like one under `[landlock]` or
   `[broker]`, because a typo would silently switch the directory off while
   the operator believes it is mounted. A misspelled *table* name only warns,
   as for every table: it cannot claim to configure the real one.

## Consequences

- A team cannot ship a notes-directory convention in the repository; each
  operator sets it once in their own config. That is the intended cost: the
  directory is the operator's, and so is the decision to expose it.
- The `repo-config-trust` spec states the carve-out ("approval does not extend
  to the user-only tables"), the `session-launch` merge-path requirement
  states where the table is read from, and the "Config that travels with the
  repo" slide references this ADR.
- "User config" means the layer the operator's environment selects. This ADR
  is about repository content; an environment the operator does not control
  is outside its scope, as for every other user-config key.

## Alternatives considered

- **Honor `[task]` from an approved repository config.** Rejected: approval
  reviews content, not consequence, and the consequence here is a writable
  host mount chosen by the repository.
- **Honor it but gate the template through the sensitive-path set.** Rejected:
  the set names credential directories and tjor's own roots, not every
  directory an operator would not want a repository to pick.
