# ADR 0014 — Repository configuration never shapes the harness launch

**Date:** 2026-10-30 · **Status:** accepted

## Context

With #73 tjor can own the harness command line: a per-harness `args` list is
passed to the harness verbatim, a `[task] prompt` template becomes the first
message of a fresh conversation, and `[task] resume` decides whether the
harness's `--continue` flag is added. The first draft read `[harness.<name>]
args` from the trusted repository layer too, on the reasoning that an approved
repository already shapes the session and the arguments run inside the cage.

Review showed that the split did not hold. A repository that can set `args`
can supply `["--prompt", "…"]` to opencode, `["--interactive", "…"]` to Copilot
CLI or a bare positional to Claude Code, and so steer the agent exactly the
way the user-only `[task]` rule exists to prevent; it can also pass
`--continue` against the operator's `resume = "never"`, or flags that relax
the harness's own permission checks (`--auto`,
`--dangerously-skip-permissions`, `--allow-all-tools`). The structural cage is
unchanged by any of these: arguments run after the privilege drop and inside
the Landlock wrapper, no flag can create a Docker mount, and endpoint
overrides stay bounded by the proxy policy. But tjor already treats the
harness's own controls as meaningful: a hardened profile deploys a root-owned
managed opencode config precisely so a repository-shipped `opencode.json`
cannot relax the permission policy, and `mask_dirs = [".opencode"]` closes the
plugin surface. Handing the repository the command line would reopen by
another door what those mechanisms close. ADR 0013's reasoning applies
unchanged: approval reviews content, not consequence.

## Decision

1. **The `[harness]` table is user-config only.** `tjor_cfg.effective()` takes
   it from the packaged defaults and the user config (the layer the operator's
   own environment selects) and drops it from a trusted repository layer before
   the merge, with a warning naming the file and the table. An unapproved
   repository file is ignored whole, as every unapproved file is; no
   table-specific warning is owed there. `check()` reports the drop the same
   way and does not count the dropped table as an unknown key.
2. **The general rule of ADR 0013 is extended:** no key a repository config can
   set names a host path that tjor mounts *or shapes the harness's command
   line*. A future key of either kind joins `USER_ONLY_TABLES`.
3. **`[harness]` is a security table** (`SECURITY_TABLES`): an unknown key under
   it, or under a nested `[harness.<name>]`, in the user config aborts the
   launch, because a typo would silently drop an argument the operator believes
   is passed. A misspelled *table* name only warns, as for every table.
4. **tjor does not inspect `args`.** They are the operator's, passed as given.
   The one exception is exact and small: an entry equal to a flag tjor is
   adding in the same launch (`--continue`/`-c`, or the harness's prompt flag
   when a prompt is being delivered) refuses, so a duplicate is a visible
   mistake rather than two flags. A denylist of permission-relaxing flags
   across three CLIs was rejected: unmaintainable, and false assurance.

## Consequences

- A team cannot ship harness arguments or a task prompt in the repository;
  each operator sets them once in their own config. Wrapper scripts that
  select a harness carry their own user config (`TJOR_USER_CONFIG`) or share
  one.
- The `repo-config-trust` requirement that names the user-only tables names
  both; the trust slide carries ADR 0013 and ADR 0014.
- The limits stay stated in the README: `args` may change the harness's mode
  (a resume or session flag, a positional prompt, a subcommand name, a short
  cluster, a parser abbreviation) without tjor noticing; `resume = "never"`
  and `--no-resume` suppress only what tjor adds; the launch line reports
  tjor's decision, not verified harness behaviour.

## Alternatives considered

- **Honor `[harness]` from an approved repository config.** Rejected: see the
  context; the consequence is a steered or relaxed harness in every clone.
- **A flag denylist.** Rejected: three CLIs, abbreviations, clusters, renames
  at every pin bump; it would read as assurance it cannot give.
- **Reserve only the prompt, resume and session-selection flags when tjor
  manages the launch.** Rejected as the general rule (the same drift problem,
  smaller), kept as the exact same-launch collision check in decision 4.
- **Per-profile arguments in a `profile.toml`.** Deferred, not rejected: it
  adds a host-side control file and parser to a structural profile model, and
  a profile directory inside a writable mount would let the agent rewrite it.
  A per-profile variant keyed by `--profile` name in the user config needs no
  new file and can follow if wanted.
