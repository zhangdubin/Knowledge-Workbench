<template>
  <!--
    AI 回答的排版容器。
    渲染细节在 utils/md.js（零依赖、先转义再解析，可安全 v-html）；
    视觉样式是全局的 .md-body（见 styles/main.css）——
    v-html 出来的节点不带 scoped 属性，写在 scoped 里根本不生效。
  -->
  <div class="md-body" v-html="html" />
</template>

<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../utils/md'

const props = defineProps({
  content: { type: String, default: '' },
})

const html = computed(() => renderMarkdown(props.content))
</script>
