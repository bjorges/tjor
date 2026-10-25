<script setup lang="ts">
// Framed two-column slide. Slots: ::left:: ::right::
import { useSlideContext } from '@slidev/client'
const { $frontmatter } = useSlideContext()
</script>

<template>
  <div class="slidev-layout two-cols">
    <SlideFrame
      :title="$frontmatter.title"
      :eyebrow="$frontmatter.eyebrow"
      :specs="$frontmatter.specs"
      :adrs="$frontmatter.adrs"
    >
      <div class="cols">
        <div><slot name="left" /></div>
        <div><slot name="right" /></div>
      </div>
    </SlideFrame>
  </div>
</template>
