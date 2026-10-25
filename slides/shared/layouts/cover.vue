<script setup lang="ts">
// Title slide: mark, name, the one-line thesis, version chip.
import { useSlideContext } from '@slidev/client'
const { $frontmatter } = useSlideContext()
const version = __TJOR_VERSION__
</script>

<template>
  <div class="slidev-layout cover">
    <div class="grid">
      <img class="mark" src="/tjor-mark.svg" alt="" />
      <div>
        <p class="tjor-eyebrow">github.com/bjorges/tjor · v{{ version }}</p>
        <h1>{{ $frontmatter.title }}</h1>
        <div class="lede"><slot /></div>
      </div>
    </div>
    <footer class="foot">
      <span>
        tjor (nynorsk): <em>tether</em> — the rope that lets an animal graze freely, but only within
        a safe radius.
      </span>
    </footer>
  </div>
</template>
