# Tasks: add-agent-profiles

## 1. Profile resolution + credential-safe staging (launcher)

- [x] 1.1 Config: `[profiles]` table (name → host dir) — verified by config resolution (`cfg profiles.<name>`)
- [x] 1.2 `tjor run --profile <name>` (resolve via `[profiles]`) and `--profile-dir <path>` (ad-hoc); mutually exclusive; unknown name fails loudly — implemented in `prepare_profile`
- [x] 1.3 Host-side allow-list stage (`python/tjor_profile.py`): copy only definition subdirs (`agent`/`agents`, `command`/`commands`, `skill`/`skills`, `prompt`/`prompts`, `mode`/`modes`) from the source into `${SESSION_DIR}/profile/`, skipping everything else and any file whose real path escapes the source (out-of-tree symlink) — verified by the filter unit tests (definitions in; `auth.json`/`.credentials.json`/API-key/unknown out; escaping symlink skipped; internal symlink allowed). NOTE: staging runs host-side into the session dir, which is already VM-share-verified (`verify_bind_source(TJOR_SESSION_DIR)`), so the profile mount needs no separate share check and the source may live anywhere the launcher can read.
- [x] 1.4 Mount the staging dir read-only at `/opt/tjor/profile` and set `TJOR_PROFILE_DIR` (empty unless a profile is active) — via `compose run --volume`/`-e` in `run_agent`

## 2. Overlay deploy (entrypoint)

- [x] 2.1 When `TJOR_PROFILE_DIR` is set, copy the staged profile into the active harness config dir on top of instruction cargo (profile wins), symlink-safe — verified in-cage (profile_test.sh: agent + command land in the harness config dir)
- [x] 2.2 Confirm no credential file from the source is present anywhere in the container (the host-side staging filter is the guarantee) — verified by profile_test.sh (a secret placed in the source appears nowhere in the container)

## 3. Docs & test

- [x] 3.1 README "Agent profiles" section — `--profile`/`[profiles]`, the credential allow-list, the overlay/precedence rule, the opt-in-is-consent trust note, and that content must match the active harness format
- [x] 3.2 Unit tests (`python/tests/test_profile.py`, allow-list filter, 9) + integration test (`tests/integration/profile_test.sh`, 5: deployed + overlay + no leak) — verified green
