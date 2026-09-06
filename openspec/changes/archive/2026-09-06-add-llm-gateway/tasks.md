# Tasks: add-llm-gateway (D4)

## 1. Config + generated master key

- [x] 1.1 `[gateway]` config: `enabled` (default false), `host`, `port`, `models` (name → LiteLLM model/provider spec), `provider_key_envs` — verified by config resolution + the wiring test
- [x] 1.2 Launcher: generate a per-install master key (CSPRNG) into a 0600 file under the user config dir if absent; never print it, never a label/hash — `tjor_gateway.ensure_master_key` (unit-tested) + `gateway_test.sh` asserts 0600 and NOT inside the session dir

## 2. Sidecar + topology

- [x] 2.1 Compose: a `litellm` service (profile `gateway`) on the **egress** network only, with the master key + provider env_file + rendered config mount — verified by smoke (`docker inspect` shows egress, not internal)
- [x] 2.2 Launcher: render the LiteLLM `config.yaml` (model_list from `[gateway].models`) into an egress-side mount; start the sidecar when enabled — `tjor_gateway.render_config` (unit-tested, secret-free) + `prepare_gateway`
- [x] 2.3 Launcher: set the harness `base_url` env to the gateway (via `compose run -e`, only when enabled); the gateway is the ONE host added to the session — verified by smoke (`OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL`) and the policy augmentation

## 3. Proxy: chokepoint enforcement

- [x] 3.1 Inject the master key toward the gateway host (D2-style); the agent holds a placeholder — `_apply_gateway` (addon unit tests: injected toward the gateway only; placeholder stripped when no key)
- [x] 3.2 Path policy toward the gateway host: inference-ONLY via host-block + `paths.allow` carve-out (exhaustive default-deny of admin) — `tjor_gateway.augment_policy` (unit + `gateway_test.sh`: `/v1/chat/completions` ALLOW, `/key/generate` + `/ui` DENY, even percent-encoded)
- [x] 3.3 IP-guard: exempt exactly the configured gateway host — addon unit test (gateway exempt; another private-resolving host still denied; no exemption when disabled)

## 4. Docs & test

- [x] 4.1 README "LLM gateway" section + ADR 0009: topology, admin-unreachable-by-construction, generated-key/never-in-agent, `[gateway]` config example
- [x] 4.2 Tests: `test_gateway.py` (key + config render + policy augmentation), addon gateway tests, `gateway_test.sh` (host-side wiring). A live provider e2e (completion works; `/key/generate` 403s through the proxy) is a documented manual check — CI has no keys
