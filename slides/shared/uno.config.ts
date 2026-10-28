// One UnoCSS config for every deck (the playbook's "extract a shared preset"
// fix): each deck's uno.config.ts re-exports this file, so theme colors and the
// icon safelist cannot drift between decks.
import { defineConfig } from 'unocss'

export default defineConfig({
  theme: {
    colors: {
      // Same hex values as the CSS custom properties in shared/theme.css —
      // declared twice on purpose: `var(--tjor-accent)` in component CSS,
      // `text-tjor-accent` in markdown utilities.
      tjor: {
        ground: '#0b1020',
        surface: '#131a2c',
        surface2: '#1c2540',
        line: '#2a3553',
        ink: '#eef2fa',
        muted: '#9aa6c2',
        accent: '#f2b84b', // the tether: warm rope amber
        teal: '#3dd6c3', // the boundary
        problem: '#ff7b8a',
        solution: '#5fe3a1',
      },
    },
  },
  // Icons passed as component *props* are invisible to UnoCSS's static scan;
  // every icon any component accepts by prop must be listed here.
  safelist: [
    'i-carbon-warning-alt',
    'i-carbon-checkmark-outline',
    'i-carbon-locked',
    'i-carbon-network-4',
    'i-carbon-password',
    'i-carbon-kubernetes',
    'i-carbon-chip',
    'i-carbon-document-security',
    'i-carbon-tools',
    'i-carbon-rule',
    'i-carbon-view',
    'i-carbon-container-services',
    'i-carbon-fingerprint-recognition',
    'i-carbon-user-multiple',
    'i-carbon-dot-mark',
  ],
})
