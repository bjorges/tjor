<script setup lang="ts">
// The geometry contract every framed layout shares: a 5rem header, flexible
// content, a 2.5rem footer. The footer text is slot *fallback*, so every slide
// carries it without writing it. Layouts compose this; slides never use it directly.
import { computed } from 'vue'
import { useSlideContext } from '@slidev/client'

const props = defineProps<{
  title?: string
  eyebrow?: string
  specs?: string[]
  adrs?: string[]
}>()

const { $slidev } = useSlideContext()
const page = computed(() => `${$slidev.nav.currentPage} / ${$slidev.nav.total}`)
const version = __TJOR_VERSION__
</script>

<template>
  <div class="tjor-frame">
    <header class="tjor-header">
      <div>
        <p v-if="props.eyebrow" class="tjor-eyebrow">{{ props.eyebrow }}</p>
        <slot name="header">
          <h1>{{ props.title }}</h1>
        </slot>
      </div>
      <SpecChips :specs="props.specs" :adrs="props.adrs" />
    </header>
    <main class="tjor-content">
      <slot />
    </main>
    <footer class="tjor-footer">
      <slot name="footer">
        <span>tjor v{{ version }} · github.com/bjorges/tjor</span>
      </slot>
      <span>{{ page }}</span>
    </footer>
  </div>
</template>
