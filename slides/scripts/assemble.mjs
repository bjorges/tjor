#!/usr/bin/env node
// Assemble every built deck into one static site for GitHub Pages:
//   slides/dist/<deck>/        ← presentations/<deck>/dist/
//   slides/dist/index.html     generated landing page (one card per deck, from
//                              each deck's package.json name + description)
//   slides/dist/tjor-mark.svg  shared assets copied from shared/public/, so the
//   slides/dist/favicon.svg    landing page depends on no particular deck
// The landing page is generated, not hand-maintained — the playbook's own
// "known drift" item — so a new deck can never be missing from it.
import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { projectFacts } from '../shared/build/project-facts.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const slidesRoot = resolve(here, '..')
const presentations = join(slidesRoot, 'presentations')
const out = join(slidesRoot, 'dist')
const base = (process.env.PAGES_BASE ?? '').replace(/\/$/, '')
const sharedPublic = join(slidesRoot, 'shared', 'public')

const facts = projectFacts()

const decks = readdirSync(presentations, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => {
    const dir = join(presentations, d.name)
    const pkg = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'))
    return { name: d.name, description: pkg.description ?? '', dist: join(dir, 'dist') }
  })
  .sort((a, b) => a.name.localeCompare(b.name))

if (decks.length === 0) {
  console.error('assemble: no decks under presentations/')
  process.exit(1)
}
const missing = decks.filter((d) => !existsSync(join(d.dist, 'index.html')))
if (missing.length) {
  console.error(
    `assemble: not built: ${missing.map((d) => d.name).join(', ')} (run pnpm build first)`,
  )
  process.exit(1)
}

rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })
for (const d of decks) {
  cpSync(d.dist, join(out, d.name), { recursive: true })
}
for (const asset of ['tjor-mark.svg', 'favicon.svg']) {
  cpSync(join(sharedPublic, asset), join(out, asset))
}

const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  )

const cards = decks
  .map(
    (d) => `
      <a class="card" href="${base}/${esc(d.name)}/">
        <span class="name">${esc(d.name)}</span>
        <span class="desc">${esc(d.description)}</span>
        <span class="go">open deck →</span>
      </a>`,
  )
  .join('\n')

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tjor slides</title>
<link rel="icon" href="${base}/favicon.svg">
<style>
  :root { --ground:#0b1020; --surface:#131a2c; --line:#2a3553; --ink:#eef2fa; --muted:#9aa6c2; --accent:#f2b84b; --teal:#3dd6c3; }
  @media (prefers-color-scheme: light) {
    :root { --ground:#f5f7fc; --surface:#fff; --line:#cfd8ea; --ink:#0f172a; --muted:#4c5a74; --accent:#9a6400; --teal:#0b8f82; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--ground); color:var(--ink); font:16px/1.55 Inter,system-ui,sans-serif; }
  .wrap { max-width: 820px; margin: 0 auto; padding: 3.5rem 1.25rem 4rem; }
  header { display:flex; align-items:center; gap:1.5rem; padding-bottom:1.5rem; border-bottom:1px solid var(--line); margin-bottom:2rem; }
  header img { width:84px; height:84px; flex:none; }
  .eyebrow { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size:.7rem; letter-spacing:.14em; text-transform:uppercase; color:var(--accent); margin:0 0 .4rem; }
  h1 { margin:0 0 .3rem; font-size:2rem; line-height:1.1; }
  .lede { margin:0; color:var(--muted); max-width:56ch; }
  .cards { display:grid; gap:.9rem; }
  .card { display:flex; flex-direction:column; gap:.3rem; background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--teal); border-radius:10px; padding:1rem 1.2rem; color:inherit; text-decoration:none; }
  .card:hover { border-color: var(--accent); }
  .name { font-family: 'JetBrains Mono', ui-monospace, monospace; font-weight:700; }
  .desc { color:var(--muted); font-size:.95rem; }
  .go { color:var(--teal); font-size:.85rem; margin-top:.2rem; }
  footer { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line); font-family:'JetBrains Mono', ui-monospace, monospace; font-size:.75rem; color:var(--muted); }
  footer a { color: var(--teal); text-decoration:none; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <img src="${base}/tjor-mark.svg" alt="">
    <div>
      <p class="eyebrow">tjor · v${esc(facts.version)}</p>
      <h1>tjor slides</h1>
      <p class="lede">Decks about <strong>tjor</strong>, the fail-closed container cage for AI coding agents. Built from the repository, so every figure and spec reference is current as of the version above.</p>
    </div>
  </header>
  <div class="cards">${cards}
  </div>
  <footer>
    source: <a href="https://github.com/bjorges/tjor/tree/main/slides">github.com/bjorges/tjor/slides</a> · ${decks.length} deck${decks.length === 1 ? '' : 's'} · ${facts.specs.length} spec capabilities · ${facts.guarantees} adversarial guarantees
  </footer>
</div>
</body>
</html>
`
writeFileSync(join(out, 'index.html'), html)
console.log(`assemble: ${decks.length} deck(s) → ${out} (base "${base || '/'}")`)
