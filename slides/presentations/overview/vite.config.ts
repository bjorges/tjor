import { defineFacts } from '../../shared/build/project-facts.mjs'

// Slidev merges this with its own Vite config. The constants are read from the
// repo (VERSION, docs/boundary-matrix.md, openspec/specs, docs/decisions) at
// build time — see shared/build/project-facts.mjs and shared/facts.d.ts.
// A plain object, not vite's defineConfig: the deck does not depend on vite
// directly (pnpm keeps it un-hoisted), and the helper is only a type aid.
export default {
  define: defineFacts(),
}
