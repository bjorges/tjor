## Why

Setting `[landlock] mask_dotenv = false` silently disables all configured `deny_paths` masks too (#48): the deny-paths loop in `run_agent` is nested inside the `mask_dotenv != false` block. These are independent settings — the toggle governs automatic `.env` discovery, while `deny_paths` is an explicit operator instruction — and the kernel-sandbox spec already demands that configuration "only extend the default deny set, never weaken it". An unrelated setting silently dropping explicit deny masks fails in the dangerous direction for a security tool.

## What Changes

- `deny_paths` masks are applied unconditionally in `run_agent`, regardless of `mask_dotenv`; only the automatic dotenv discovery stays behind the toggle.
- A regression test in `tests/integration/landlock_test.sh`: with `mask_dotenv = false` plus a configured deny path, the launch masks the deny path and skips the dotenv discovery.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `kernel-sandbox`: "Operator can extend the deny list" gains the explicit independence guarantee — `deny_paths` SHALL apply regardless of `mask_dotenv`.

## Impact

- `bin/tjor` (`run_agent` masking block): move the deny-paths handling out of the `mask_dotenv` conditional (~structural, no behavior change when `mask_dotenv` is default-on).
- `tests/integration/landlock_test.sh`: one new launch case with scoped `XDG_CONFIG_HOME` config.
- No image, proxy, entrypoint, or topology changes.
