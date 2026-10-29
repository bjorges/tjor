# Design

## Context

See proposal.md — Why. What exists today, verified in the code, and shapes the approach:

- `python/tjor_policy.py` is the single matcher (charter L4). `parse_policy` is strict: `_TOP_KEYS = {mode, hosts, paths}`, a rule entry has exactly `{host, path}`, and any unknown key or wrong type makes the whole policy `valid=False`, which `evaluate` and `evaluate_connect` turn into deny-everything. `evaluate(policy, url)` runs: invalid policy → bad URL → excessive encoding → host blocklist, where a matching block pattern either returns an all-forms carve-out allow or a `host-block` deny → any-form path blocks → default mode. The carve-out returns before the path blocks are consulted; that precedence is spec'd and tested.
- `Verdict.rule` names the deciding stage and already carries detail after a colon where there is detail: `fail-closed:bad-url`, `ip-guard:<why>`, `connect-defer:carveout`. `Verdict.pattern` is the matched pattern (`{host}{path}` for path rules). The 403 body and the `x-tjor-rule` header show the rule; the session denial log is `host\trule\ttime` and `tjor denials` prints it as is, while the teardown recap reads only the host column.
- Three call sites: `proxy/addon.py` (`decide(url)` from `request_verdict`, called by the `request` hook with `flow.request.pretty_url`; `decide_connect(host)` from `http_connect`), `tjor_policy.py check` (the CLI behind `tjor policy <url> [--explain]`), and the module API used by tests, `tjor_gateway` and `tjor_policy_edit`. `python/tests/test_parity.py` runs `python/tests/fixtures/corpus.json` (21 URL cases, no method) against all three.
- `python/tjor_gateway.py` `augment_policy` re-emits the session policy from the parsed base policy: it writes `mode`, `hosts` and the two `paths` lists and nothing else. Any section it does not know is silently absent from the session policy. Today there is no such section; with `methods` there would be.
- `python/tjor_policy_edit.py` inserts new hosts after the first `allow = [` that follows `[hosts]`, anywhere in the file. A restrict rule has an `allow` list too; if `[hosts]` has no `allow` of its own, the regex would run into the restrict rule. The parse and the semantic re-check would refuse the write, but with a misleading message.
- The conformance suite runs `images/conformance/probes.py` inside the cage against `images/conformance/policy.toml` (the parity fixture's rules plus the echo hosts). `via_proxy` sends GETs only. Every probe name is registered in `python/gen_boundary_matrix.py`, and `tests/doc_consistency.sh` fails when the registry and the probe sources disagree or `docs/boundary-matrix.md` is stale.
- `python/gen_corefile.py` derives DNS zones from `host_allow` only; the broker and identity modules use `host_matches` only. None of them evaluates a request.
- mitmproxy hands the `request` hook the inner request of a CONNECT tunnel after TLS termination, with its real method; plain-HTTP absolute-form requests reach the same hook directly. The method is therefore available at exactly the point where the path already is.

## Goals / Non-Goals

**Goals:**
- A restrict/except pair in the policy that can only narrow, with the same encoding asymmetry as the path rules, evaluated by the one matcher and proven at all three call sites.
- No silent path by which a method restriction is lost: not by a call site that forgets the method, not by the gateway augmentation, not by `tjor policy add`.
- The refused method visible wherever a denial is visible: the 403, the denial log, `tjor policy --method`.
- Conformance probes that prove the gate from inside the cage on the Linux engine.

**Non-Goals:**
- Method rules keyed on anything but host and path (headers, bodies, query strings). The gate decides on the verb; a request's semantics are the upstream's business, and the README says so.
- Gating CONNECT by method. The verb is inside the tunnel; the inner request is gated.
- A `tjor policy` subcommand that writes restrict or except rules. They are written by hand; `tjor policy add` keeps adding hosts only.
- Changing the default policy's verdicts. The packaged default gains a commented example only.
- Per-broker or per-credential method scopes. The policy is per session; a brokered host is restricted by restricting the host.

## Decisions

**D1. Schema: `methods.restrict` and `methods.except` as arrays of tables, parsed as strictly as the path rules.**
`[[methods.restrict]]` has exactly `host` (string) and `allow` (list of strings); `[[methods.except]]` has exactly `host`, `path` (strings) and `methods` (list of strings). A method name in the policy must match `^[A-Z]{1,16}$` as written — `"get"` or `"GET "` is a format error, not normalised — because every other parse error in this file is loud rather than forgiving, and a policy is written once and reviewed. An empty `allow = []` is valid and means "no method unless excepted" (for example a host where only one POST path is wanted). Any violation makes the whole policy invalid, i.e. deny-everything, like every other malformed section. `Policy` gains `method_restrict: list[tuple[str, frozenset[str]]]` and `method_except: list[tuple[str, str, frozenset[str]]]`.
Alternative: `method = "POST"` on the existing `paths` rules — rejected in the issue: path blocks have no exception mechanism and carve-outs only rescue blocked hosts, so a read-only host with one POST path is not expressible.

**D2. `evaluate(policy, url, method)` with a required method; the method is validated right after the URL, before any rule.**
Order inside `evaluate`: invalid policy → bad URL → bad method (`fail-closed:bad-method`) → excessive encoding → stages. The method is `.strip().upper()`-ed and must match `^[A-Z]{1,16}$`; the check applies to every request, restricted host or not, because a comparison against a restrict list is only sound on a canonical token and "deny the malformed thing everywhere" is the simpler rule to state. The parameter has no default so that a caller that forgets it raises `TypeError` in the first test run instead of silently evaluating a POST as a GET — the one way the gate could be bypassed by construction. The CLI alone defaults to `GET`, for the operator typing a URL. `check(policy_path, url, method)` follows.
Alternative: `method="GET"` default at the API — rejected for the reason above.

**D3. The gate runs after stages 1–2 and before any allow is returned, without changing stage 1–2 precedence.**
Stage 1 no longer returns the carve-out allow immediately; it records it as the pending verdict and skips stage 2 (so a carve-out still beats a path block, exactly as today). Stage 2 runs only without a pending carve-out. Then the gate: collect every restrict rule whose host matches; if none, pass; if the method is listed by all of them, pass; otherwise look for an except rule whose host matches, whose list contains the method, and whose path pattern matches every form of the path (`all(...)` over `path_forms`, the allow-side asymmetry); if one matches, pass; else deny with `Verdict(False, f"method-block:{METHOD}", <host pattern of the first matching restrict that omits the method>)`. After the gate, return the pending carve-out if there is one, else the default-mode verdict. The deny-only property is then structural: the only new return is a deny, and every allow path is the old one. Intersection over matching restricts rather than first-match, because the order of `[[…]]` tables in a hand-written file should not decide what a host may do; deny-wins is the fail-closed reading and the README states it.

**D4. The rule string carries the method: `method-block:<METHOD>`, pattern is the restrict host pattern.**
This follows the existing `stage:detail` convention (`ip-guard:<why>`, `fail-closed:<what>`), so the denial log's three-column format, `tjor denials`, the teardown recap and `_agent_rule` need no change, and the agent's 403 reads `DENY (method-block:POST: api.example.test)`. The parity corpus compares the full rule string, so all three call sites must agree on the method spelling too.
Alternative: a fourth log column with the method for every denial — rejected: it changes a format two readers parse for one stage's benefit.

**D5. Call sites: the addon passes `flow.request.method`; the CLI gains `--method`; `tjor policy` forwards it.**
`decide(url, method)` and `request_verdict(url, host, method)` take the method; the `request` hook passes `flow.request.method` (mitmproxy keeps it as sent; normalisation happens in the matcher so every call site normalises identically). `tjor_policy.py check --policy P [--method M] [--json] URL`, default `GET`. `cmd_policy` in `bin/tjor` accepts `--method <M>` next to `--explain` and forwards it; the usage line shows it. The corpus gains a `method` field on every case (explicit, no loader default), method-denial cases, an exception case and an encoded-exception case; the parity test passes the method to all three call sites and the pytest id becomes `"<METHOD> <url>"`.

**D6. `augment_policy` re-emits `methods`; `tjor_policy_edit` anchors its insert to the `[hosts]` table.**
The gateway augmentation reads `methods.restrict`/`methods.except` from the base policy with the same tolerant shape it uses for `paths`, and writes them back as `[[methods.restrict]]`/`[[methods.except]]` tables after the path rules; the downstream parse validates the result as before. The policy editor's regex becomes "the `[hosts]` table header, then any lines that do not start a new table, then `allow = [`", so a restrict rule's `allow` list after a `[hosts]` without one cannot become the insertion point; the fallback (append a `[hosts]` table) is unchanged.

**D7. Proof: unit, parity, conformance.**
Unit tests in `test_policy.py` for every spec scenario plus a property test: for every corpus case and each of `GET HEAD POST PUT PATCH DELETE OPTIONS`, the verdict under the fixture policy either equals the verdict under the same policy with both method lists emptied (`dataclasses.replace`), or is a `method-block:*` deny where the stripped verdict allows. Four conformance probes against `readonly.test` (allow-listed, restricted to `GET`/`HEAD`, with `POST` excepted on `/search*`): a POST to `/items` is denied with `x-tjor-rule: method-block:POST`, a GET passes policy, a POST to `/search` passes policy, a POST to `/%73earch` is denied. `via_proxy` gains a `method` parameter. The registry in `gen_boundary_matrix.py` gets the four names under `egress-policy` and the matrix is regenerated. The conformance policy and the parity fixture gain the same rules so the corpus and the probes read one policy shape.

**D8. Docs state the residual.**
README "Egress policy": the example (read-only host, one POST exception), the deny-only property, intersection of overlapping restricts, and the residual: the gate sees the verb, not what the request does; a GET that mutates on the server side is still a GET, and a POST exception is exactly as wide as its path pattern. `config/policy.toml`: the same example, commented out. CHANGELOG under `[Unreleased]`. Slides: "A policy that can be bent" gets the method gate in its precedence line and a bullet with the residual; "Policy has to see the request" says the method as well as the path is decided after TLS termination; the ergonomics slide shows `--method`; all four pins updated.

## Risks / Trade-offs

- [An operator restricts a host the harness writes to, e.g. the LLM endpoint] → loud and specific: every request fails with `method-block:POST`, `tjor denials` shows it, `tjor policy <url> --method POST` previews it; the README example restricts an API host, never a harness endpoint.
- [The gate is mistaken for a semantic read-only guarantee] → the README, the spec requirement and the slide say the gate sees the verb only; the exception example uses a search endpoint because that is where POST-as-read is common.
- [A future call site evaluates without a method] → impossible by signature; the parity suite additionally fails if any call site disagrees on a method case.
- [Overlapping restricts surprise an operator expecting first-match] → stated in the README and the spec (intersection); `tjor policy --method` shows which pattern decided.
- [The Python API signature change] → in-repo callers only; all updated in the same change.

## Migration Plan

Additive. Policies without a `methods` section are unaffected; `tjor policy <url>` without `--method` evaluates `GET`. No data or config migrates. Rollback is reverting the change; a policy file carrying a `methods` section would then fail to parse (unknown top-level key) and deny everything — the loud direction.
