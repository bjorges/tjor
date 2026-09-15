# Read-only mounts + untrusted project-config neutralization

## Why

A hardened tjor profile (the SPV read-only investigation use case) currently
cannot make its two central claims structurally. First, every mounted repo is
read-write and there is no tjor-native way to grant a genuinely non-writable
tree — harness-level `permission.edit: deny` is advisory and a shell
redirection defeats it (#44). Second, a mounted repo's own config can weaken
the harness posture from inside: `.opencode/plugins`/`.opencode/tools` are
auto-loaded with full command execution outside the permission matcher (#43),
and project-local `opencode.json` config loads after the profile's curated
config and can override it — including redefining a curated agent with broader
permissions (#46). Today these are at best detectable, not containable.

## What Changes

- **`tjor run --dir-ro <path>` (repeatable)** — a true read-only repo mount:
  `:ro` at the container level (enforced container-wide, `docker exec`
  included), granted `--allow-read` instead of `--allow-write` in the
  kernel-sandbox (cplt/Landlock) wrap so the kernel tier agrees, still added
  to git `safe.directory` and still covered by dotenv-mask discovery.
  Sensitive-path refusal applies exactly as for `--dir` (read-only still
  exfiltrates); the same path given to both `--dir` and `--dir-ro` aborts.
- **`[landlock] mask_dirs = []`** — extends the launch-time `/dev/null`-style
  masking from files to directories: each entry is an absolute path (masked
  directly, like `deny_paths`) or a bare directory name (e.g. `".opencode"`)
  discovered recursively in every mounted tree; a matching directory is
  bind-mounted over with a read-only **empty** directory, making it
  structurally empty in-cage on every runtime. Applied independently of
  `mask_dotenv` (the #48 lesson). Announcements are escape-sanitized
  (untrusted repo dir names). Default `[]`; hardened setups opt in.
- **Managed opencode config tier** — a profile may stage
  `managed/opencode.json`; the entrypoint deploys it root-owned and
  agent-immutable to `/etc/opencode/opencode.json` (opencode's documented
  managed-settings path, which loads after ALL user/project config) before
  the privilege drop. Invalid JSON refuses the launch (a profile must never
  look hardened without being it); with no managed file staged, a stale
  managed file is removed. The issue's proposed `OPENCODE_CONFIG_DIR` export
  is deliberately dropped — verified against the shipped opencode bundle, it
  *replaces* the global config dir and would displace the baseline cargo
  (see design.md).

Together, #43 + #46 give a hardened profile the "project config fully
neutralized" pairing the issues call for; #44 gives it a true read-only tree.
Closes #43, #44, #46.

**Designed-for, not solved:** #53 (git trust for repos/worktrees created
mid-session) is a separate follow-up change. This change deliberately shapes
its contracts for that fix — the approved-roots env lists carry writability
class, which is the eligibility input #53's mediated trust helper needs —
without implementing any of it (see design.md, decision 7).

## Capabilities

### New Capabilities

None — all three land in existing capabilities.

### Modified Capabilities

- `session-launch`: `--dir-ro` joins `--dir` (new requirement for read-only
  extra mounts; the existing verify-before-mount requirement extends to it).
- `kernel-sandbox`: the deny-list requirement grows directory masking
  (`mask_dirs`), with the same independence-from-`mask_dotenv` guarantee as
  `deny_paths`.
- `agent-profiles`: new requirement for the managed opencode config tier
  (staging, root-owned deployment, fail-closed validation, stale removal).

## Impact

- `bin/tjor` — `--dir-ro` parsing/resolution, `:ro` mounts, `TJOR_RO_DIRS`
  env, `mask_dirs` discovery + empty-dir masking, managed-JSON preflight.
- `images/agent/entrypoint.sh` — `--allow-read` grants for read-only dirs;
  managed config deployment/removal in the root phase.
- `python/tjor_profile.py` — `managed` joins the structural allow-list.
- `config/tjor.toml` — `[landlock] mask_dirs` default (shape validation).
- Tests: `python/tests/` (profile staging, cfg shape), integration
  (`multirepo_test.sh`, `landlock_test.sh`, `profile_test.sh`).
- Docs: README (flags, config, residuals), CHANGELOG.
- No breaking changes: every behavior is opt-in; a session using none of the
  three flags/keys is byte-for-byte unchanged.
