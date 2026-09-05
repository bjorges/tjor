# ADR 0005 — LLM credential identity (attribution-only) and Copilot ToS posture

**Date:** 2026-09-04 · **Status:** accepted

**Attribution-only LLM identity in v0.1.** The author's LLM access is billed via GitHub Copilot, whose tokens are per-user, not per-session — true per-session LLM credential isolation is unreachable on this path. v0.1 therefore ships attribution-only identity: sessions share one LLM credential; identity travels as `x-agent-*` metadata for observability and audit. Revisit (LiteLLM virtual keys per session) if non-Copilot billing ever appears. Note this limit applies to **LLM** credentials only — the planned D2 broker (not yet built) will isolate everything else per session (git tokens, service credentials).

**Copilot ToS posture: accept and document.** Routing `github_copilot/*` models through a local LiteLLM gateway to non-IDE harnesses sits in documented ToS ambiguity. For personal, local use of an actively-maintained LiteLLM feature this is accepted knowingly. tjor itself stays backend-agnostic: D4 is an optional gateway sidecar with no privileged backend; each user brings their own provider and their own ToS call.
