# tjor slides — design system and sync contract

Slide decks about tjor, built with [Slidev](https://sli.dev), published to GitHub Pages at
`https://bjorges.github.io/tjor/<deck>/`. This file is written for whoever edits a deck next,
human or coding agent: the rules are tables and invariants, not taste.

## Keeping the deck in sync (the contract)

**The `overview` deck explains every capability tjor ships, one or more slides per problem, and
is updated whenever functionality is added or changed.** This is enforced, not hoped for:

| Invariant                                                            | Enforced by                                                                                                                         |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Every `openspec/specs/<capability>/` is tagged by at least one slide | `tests/slides_consistency.sh` (runs in `ci.yml` **unit** and in `slides.yml`)                                                       |
| Every tag names an existing capability                               | same                                                                                                                                |
| Every tag's pin equals the spec's current `### Requirement:` count   | same — a changed spec fails CI until the slide is reviewed and the pin bumped                                                       |
| Every `adrs:` reference names an existing `docs/decisions/NNNN-*.md` | same                                                                                                                                |
| Version, guarantee and check counts shown in the deck are current    | read from `VERSION`, `docs/boundary-matrix.md`, `openspec/specs`, `docs/decisions` at build time (`shared/build/project-facts.mjs`) |

A slide is tagged in its frontmatter:

```yaml
---
layout: problem
title: The agent holds the secret
specs: [credential-broker@17] # <capability>@<requirement count when last reviewed>
adrs: ['0007'] # optional
---
```

**When you add or change functionality:**

1. New capability (new `openspec/specs/<cap>/`): add a `problem` slide tagged `specs: [<cap>@N]`
   where N is its requirement count, and add the problem to the map slide's `groups:`.
2. Changed capability (requirement added/removed/renamed): CI prints
   `'<cap>' now has N requirements; a slide was reviewed against M`. Re-read the spec, update the
   slide's bullets so they still describe what ships, then set the pin to `@N`.
3. New ADR that changes behaviour: reference it with `adrs:` on the slide it affects.
4. Run `tests/slides_consistency.sh` (no node needed), then `cd slides && pnpm check && pnpm build`.

The pin is deliberately a count, not a hash: a human can read it, and fixing it is one edit after
the review it exists to force. It does not catch a reworded requirement with the same count; that
review happens when the spec changes, as part of the OpenSpec change that reworded it (see
`openspec/config.yaml` rules).

## Layout

```
slides/
  package.json            pnpm workspace root: dev / build / assemble / check
  pnpm-workspace.yaml     packages: presentations/*
  agents.md               this file
  shared/
    theme.css             design tokens + the layout frame (imported by every deck's style.css)
    uno.config.ts         theme colors as UnoCSS utilities + icon safelist (re-exported per deck)
    facts.d.ts            types for the build-time constants
    build/project-facts.mjs   reads VERSION, boundary matrix, specs, ADRs → Vite `define`
    components/           Vue building blocks (auto-registered in every deck)
    layouts/              slot-based slide frames (auto-registered in every deck)
    public/               tjor-mark.svg, favicon.svg
  presentations/
    overview/
      components -> ../../shared/components     (symlink, committed)
      layouts    -> ../../shared/layouts        (symlink, committed)
      public     -> ../../shared/public         (symlink, committed)
      slides.md  style.css  uno.config.ts  vite.config.ts  package.json
  scripts/assemble.mjs    merges presentations/*/dist into dist/<deck>/ + generated landing page
```

Share by symlink, not by package: Slidev auto-discovers `components/`, `layouts/` and `public/`
in a deck root, so three symlinks give every deck the whole design system with hot reload.
Windows contributors need developer mode or WSL for the symlinks.

## Commands

| Command                          | Where     | Does                                                                 |
| -------------------------------- | --------- | -------------------------------------------------------------------- |
| `pnpm install --frozen-lockfile` | `slides/` | reproducible install (Node ≥ 22.12, pnpm 10 via `packageManager`)    |
| `pnpm dev`                       | `slides/` | dev server for `overview` on port 3030, hot reload                   |
| `pnpm build`                     | `slides/` | every deck → `presentations/<deck>/dist/` (`PAGES_BASE=/tjor` in CI) |
| `pnpm assemble`                  | `slides/` | one site in `slides/dist/` with a generated landing page             |
| `pnpm check`                     | `slides/` | Prettier check + `tests/slides_consistency.sh`                       |
| `tests/slides_consistency.sh`    | repo root | the spec↔slide gate alone, no node needed                            |
| `pnpm --filter overview export`  | `slides/` | PDF via Playwright (install `playwright-chromium` first; not in CI)  |

## Design tokens

Declared twice on purpose: as CSS custom properties in `shared/theme.css` (for component styles,
`var(--tjor-accent)`) and as UnoCSS theme colors in `shared/uno.config.ts` (for markdown
utilities, `text-tjor-accent`). Same hex values; change both.

| Token              | Dark      | Light     | Use                                              |
| ------------------ | --------- | --------- | ------------------------------------------------ |
| `--tjor-ground`    | `#0b1020` | `#f5f7fc` | slide background                                 |
| `--tjor-surface`   | `#131a2c` | `#ffffff` | panels, cards                                    |
| `--tjor-surface-2` | `#1c2540` | `#e8edf7` | inline code, callouts                            |
| `--tjor-line`      | `#2a3553` | `#cfd8ea` | borders, header rule                             |
| `--tjor-ink`       | `#eef2fa` | `#0f172a` | text                                             |
| `--tjor-muted`     | `#9aa6c2` | `#4c5a74` | secondary text, footer                           |
| `--tjor-accent`    | `#f2b84b` | `#9a6400` | the tether: eyebrows, section numbers, ADR chips |
| `--tjor-teal`      | `#3dd6c3` | `#0b8f82` | the boundary: links, spec chips, proof notes     |
| `--tjor-problem`   | `#ff7b8a` | `#c0243a` | problem panel accent only                        |
| `--tjor-solution`  | `#5fe3a1` | `#0f8a4a` | solution panel accent only                       |

Type: Inter (sans), JetBrains Mono (mono), loaded through Slidev's `fonts:` headmatter. The deck
is dark-first (`colorSchema: dark`); light tokens exist so a forced light render stays legible.

## Geometry

Every framed layout renders through `components/SlideFrame.vue`: a **5rem header** (eyebrow +
title left, spec/ADR chips right), **flexible content**, a **2.5rem footer** whose text is slot
fallback (`tjor v<version> · github.com/bjorges/tjor` and `page / total`), so every slide gets it
without writing it. Slides never use `SlideFrame` directly; they pick a layout.

## Layouts

| Layout     | Frontmatter it reads                | Slots                        | Use for                          |
| ---------- | ----------------------------------- | ---------------------------- | -------------------------------- |
| `cover`    | `title`                             | default (lede)               | the first slide only             |
| `section`  | `number`, `title`                   | default (one line)           | theme dividers                   |
| `problem`  | `title`, `specs`, `adrs`, `eyebrow` | `::problem::` `::solution::` | one problem, one answer          |
| `default`  | `title`, `specs`, `adrs`, `eyebrow` | default, `::header::`        | diagrams, grids, anything framed |
| `two-cols` | `title`, `specs`, `adrs`, `eyebrow` | `::left::` `::right::`       | comparisons                      |
| `end`      | `title`                             | default                      | the last slide only              |

Named slots in markdown, no raw wrapper divs for the frame itself:

```md
---
layout: problem
title: A policy that can be bent
specs: [egress-policy@5]
---

::problem::

- bullet

::solution::

- bullet

<Plainly><p>The residual this mechanism leaves.</p></Plainly>
```

## Components

| Component      | Props                        | Notes                                                                                                              |
| -------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `Plainly`      | `tag?`, `proof?`             | "Stated plainly" callout for limits; `proof` variant for evidence. Place last in a panel; it sticks to the bottom. |
| `Stat`         | `value`, `label`, `hint?`    | one figure; feed it build-time constants, never typed numbers                                                      |
| `Facts`        | `kind: version               | checks                                                                                                             | guarantees | specs | adrs` | inline build-time figure in prose |
| `SpecChips`    | `specs?`, `adrs?`            | used by `SlideFrame`; strips `@N` for display, links to GitHub                                                     |
| `ProblemMap`   | `groups: {title, items[]}[]` | the agenda grid; data lives in that slide's frontmatter                                                            |
| `CageTopology` | —                            | inline SVG of the compose topology; colors from tokens                                                             |

Build-time constants available in component `<script>` blocks: `__TJOR_VERSION__`,
`__TJOR_CHECKS__`, `__TJOR_GUARANTEES__`, `__TJOR_SPECS__` (names), `__TJOR_ADR_COUNT__`,
`__TJOR_ADR_FILES__`. They are **not** visible in markdown template expressions (Vue compiles
those to `_ctx.X`, which Vite's `define` does not touch): in `slides.md` use `<Facts kind="…" />`
or `<Stat fact="…" />`. Never type a number that one of these can supply.

Icons: UnoCSS `presetIcons` with the Carbon set (`i-carbon-*`). An icon passed as a component
**prop** is invisible to the static scan: add it to `safelist` in `shared/uno.config.ts` or it
renders as nothing.

## Content rules

- One problem per `problem` slide. Left panel: 2–4 bullets stating the problem in the reader's
  terms. Right panel: 3–5 bullets naming the mechanism, then `Plainly` for the residual.
- Use the repo's own words for mechanisms (README, specs, ADRs). Bold the mechanism's name once.
- State limits the way the README does. A slide without a residual should have none, not hide one.
- No numbers in prose that the build can supply. No marketing adjectives.
- Commands go in ` ```console ` blocks, with a short trailing comment per line.
- Max ~110 words per panel; the frame does not scroll.

## Add a deck (≈5 minutes)

1. `mkdir slides/presentations/<name>` and copy `package.json`, `style.css`, `uno.config.ts`,
   `vite.config.ts`, `tsconfig.json` from `overview`. Set `name`, `description`, a unique `--port`,
   and `--base "${PAGES_BASE:-}/<name>/"` in `build`.
2. `cd slides/presentations/<name> && ln -s ../../shared/components components && ln -s ../../shared/layouts layouts && ln -s ../../shared/public public`
3. Write `slides.md`. Start with `layout: cover`, end with `layout: end`.
4. `cd slides && pnpm install && pnpm build && pnpm assemble`. The landing page is generated from
   each deck's `package.json`, and `slides.yml` picks the deck up through the `presentations/*` glob;
   nothing else to register.

## Dependency notes

- `markdown-it@^14` is declared on each deck on purpose: Slidev 53's parser (`@comark/markdown-it`)
  imports markdown-it 14 internals, while `@shikijs/markdown-it` brings 15. Declaring 14 on the
  deck makes it the peer the parser resolves against; without it `slidev build` fails at startup
  with `ERR_PACKAGE_PATH_NOT_EXPORTED ./lib/token.mjs`. Drop it once upstream reconciles.
- `vite.config.ts` exports a plain object rather than importing `defineConfig` from `vite`: the
  decks do not depend on vite directly, and pnpm (correctly) does not hoist it.

## Pipeline

`.github/workflows/slides.yml`: **check** (`tests/slides_consistency.sh`, Prettier) → **build**
(`pnpm build` with `PAGES_BASE=/tjor`, `pnpm assemble`, upload `slides/dist`) → **deploy**
(`actions/deploy-pages`, `main` only). Actions are pinned by commit SHA like every other workflow
in this repo. The consistency gate also runs in `ci.yml`'s unit job, so a spec change on a branch
that never touches `slides/` still fails until the deck is reviewed.
