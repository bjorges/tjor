## Context

See proposal.md — Why. Current state (`bin/tjor`):

- `resolve_session()` computes `sid="<repobase-lowercased>-<sha256(ws)[:8]>"` and, when `--session` is given, appends `-<name-lowercased>` after validating `[A-Za-z0-9._-]{1,32}` — unconditionally, so an already-qualified value gets double-prefixed.
- Every lifecycle command (`down`, `status`, `denials`, `reset`) funnels through `resolve_session`; `cmd_attach` does not (it matches the positional argument against `tjor.session` labels by exact equality, so it takes full ids only).
- `cmd_down` removes by label and runs `compose down` — both no-ops against a phantom id, so a mis-resolved teardown "succeeds" silently.
- Session state dirs live under one global root (`session.root`, default `~/.tjor/sessions/<sid>`), so a foreign session's existence is checkable from any cwd via its state dir; its containers are checkable via the `tjor.session` label.

## Goals / Non-Goals

**Goals:**
- One canonicalization point inside `resolve_session` so every `--session` consumer inherits the fix.
- Byte-for-byte identical derivation for genuinely-short names (existing sessions keep resolving).
- Paste-safety: every session reference tjor prints next to a command works verbatim.

**Non-Goals:**
- A separate `--session-id` flag (issue option 3): unnecessary once `--session` disambiguates against reality; two flags would just move the confusion.
- Renaming/migrating existing session ids or changing the hash derivation.
- Making `tjor run` able to *launch into* another workspace's session (explicitly refused instead).

## Decisions

1. **Disambiguate against reality, in `resolve_session`.** Given `base="<repobase>-<hash8>"` for the current workspace and a (lowercased) `--session` value `name`, resolve in order:
   - `name == base` → the unnamed session of this workspace (notice).
   - `name` starts with `"${base}-"` → strip the prefix; remainder is the short name (notice). Idempotent acceptance; also what makes the collision-guard's displayed id safe to re-paste into `run` (it then hits the collision guard properly instead of spawning a phantom).
   - `name` matches the qualified shape (`^[a-z0-9._-]+-[0-9a-f]{8}(-[a-z0-9._-]{1,32})?$`) **and** a session with exactly that id exists (state dir under the session root, or any container labeled `tjor.session=<name>`) → for lifecycle commands: honor verbatim with a notice; for `run` (a new launch-mode argument to `resolve_session`, passed by `session_setup`): `die` with guidance. Existence is the disambiguator because a short name theoretically matching the shape (e.g. `release-20260914` — 8 hex-ish chars) must keep working.
   - otherwise → short name, exactly today's path (with a notice when it *looked* qualified but nothing existed).
   Alternative considered: pure shape-based detection without the existence check — rejected, false-positives on legitimate short names would change their meaning.
2. **Factor the base-id derivation into a helper** used by `resolve_session` and `cmd_attach`, so attach can additionally match `"${base}-${want}"` (and `want == base`) against labels without duplicating the hash logic. Attach never *narrows*: exact full-id matches keep working from any cwd.
3. **`cmd_down` no-match report:** before removal, note whether any labeled containers or a state dir exist; if neither, `warn` "nothing found for session <id> — see: tjor ls" and still run the (idempotent, harmless) cleanup. Warn-not-die: teardown must stay safe to re-run.
4. **Collision-guard message** gains the teardown hint and keeps the full id (now paste-safe by decision 1): reattach with `tjor attach <sid>`, tear down with `tjor down --session <sid>`, or start a separate session with a different `--session <name>`.

## Risks / Trade-offs

- [A user's short name that equals an existing *foreign* session's full id changes meaning for lifecycle commands] → requires the short name to embed another workspace's exact `-<hash8>` id while that session exists — pathological; the notice states which interpretation won; `run` is unaffected (refusal, not silent adoption).
- [Existence check adds a `docker ps` per resolution] → only on the qualified-shape path (rare); lifecycle commands already shell out to docker repeatedly.
- [Stripping `"${base}-"` changes behavior for anyone who deliberately used a base-prefixed *short* name] → such a session could only have been created by this very footgun (the doubled id); resolving it to the intended session is the fix, not a regression. The notice makes the interpretation visible.

## Migration Plan

Launcher-only; no state migration. Phantom sessions already created by the footgun remain visible in `tjor ls` and can be removed with `tjor down --session <their-full-id>` — which this change makes work. Rollback: revert the commit.

## Open Questions

None.
