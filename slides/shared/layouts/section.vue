<script setup lang="ts">
// Theme divider: a big number, the theme title, one line of what it covers.
import { useSlideContext } from '@slidev/client'
const { $frontmatter } = useSlideContext()
</script>

<template>
  <div class="slidev-layout section">
    <div class="wrap">
      <div class="num">{{ $frontmatter.number }}</div>
      <div>
        <p class="tjor-eyebrow">Theme</p>
        <h1>{{ $frontmatter.title }}</h1>
        <div class="lede"><slot /></div>
      </div>
    </div>
  </div>
</template>
