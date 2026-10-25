// Facts every deck states, read from the repository at build time so a slide
// can never quote a stale version or guarantee count: VERSION, the generated
// boundary matrix's totals, and how many spec capabilities / ADRs exist.
// Consumed by each deck's vite.config.ts as Vite `define` constants.
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
export const repoRoot = resolve(here, '../../..')

function read(rel) {
  return readFileSync(resolve(repoRoot, rel), 'utf8')
}

export function projectFacts() {
  const version = read('VERSION').trim()
  if (!/^\d+\.\d+\.\d+/.test(version)) {
    throw new Error(`slides: VERSION does not look like a version: ${JSON.stringify(version)}`)
  }

  // "(261 checks total; 93 adversarial guarantees below, …)" in the generated header.
  const matrix = read('docs/boundary-matrix.md')
  const m = matrix.match(/\((\d+) checks total; (\d+) adversarial guarantees/)
  if (!m) {
    throw new Error(
      'slides: cannot parse "(N checks total; M adversarial guarantees" from docs/boundary-matrix.md — ' +
        'the generator wording changed; update shared/build/project-facts.mjs',
    )
  }

  const specs = readdirSync(resolve(repoRoot, 'openspec/specs'), { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort()
  const adrs = readdirSync(resolve(repoRoot, 'docs/decisions')).filter((f) =>
    /^\d{4}-.*\.md$/.test(f),
  )

  return {
    version,
    checks: Number(m[1]),
    guarantees: Number(m[2]),
    specs,
    adrs,
    adrCount: adrs.length,
  }
}

/** Vite `define` map: every value JSON-encoded, as `define` requires. */
export function defineFacts() {
  const f = projectFacts()
  return {
    __TJOR_VERSION__: JSON.stringify(f.version),
    __TJOR_CHECKS__: JSON.stringify(f.checks),
    __TJOR_GUARANTEES__: JSON.stringify(f.guarantees),
    __TJOR_SPECS__: JSON.stringify(f.specs),
    __TJOR_ADR_COUNT__: JSON.stringify(f.adrCount),
    __TJOR_ADR_FILES__: JSON.stringify(f.adrs),
  }
}
