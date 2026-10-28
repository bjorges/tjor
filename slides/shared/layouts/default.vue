<script setup lang="ts">
// Framed free-form slide. Title from frontmatter `title`; `::header::` overrides it.
import { useSlideContext } from '@slidev/client'
const { $frontmatter } = useSlideContext()
</script>

<template>
  <div class="slidev-layout default">
    <SlideFrame
      :title="$frontmatter.title"
      :eyebrow="$frontmatter.eyebrow"
      :specs="$frontmatter.specs"
      :adrs="$frontmatter.adrs"
    >
      <template v-if="$slots.header" #header><slot name="header" /></template>
      <slot />
    </SlideFrame>
  </div>
</template>
