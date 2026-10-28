<script setup lang="ts">
import { useSlideContext } from '@slidev/client'
const { $frontmatter } = useSlideContext()
const version = __TJOR_VERSION__
</script>

<template>
  <div class="slidev-layout end">
    <div class="wrap">
      <img class="mark" src="/tjor-mark.svg" alt="" />
      <h1>{{ $frontmatter.title }}</h1>
      <div class="body"><slot /></div>
      <p class="foot">tjor v{{ version }} · MIT · github.com/bjorges/tjor</p>
    </div>
  </div>
</template>
