<template>
  <!--
    Markdown 渲染容器。
    渲染细节在 utils/md.js（零依赖、先转义再解析，可安全 v-html）；
    视觉样式是全局的 .md-body（见 styles/main.css）——
    v-html 出来的节点不带 scoped 属性，写在 scoped 里根本不生效。

    variant：
      chat（默认）—— AI 回答气泡，标题压到 h3 起，字号紧凑
      doc          —— 文档正文，保留原始标题层级，字号放大、行距放宽
  -->
  <div class="md-body" :class="{ 'md-body-doc': variant === 'doc' }" v-html="html" />
</template>

<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../utils/md'

const props = defineProps({
  content: { type: String, default: '' },
  variant: { type: String, default: 'chat' },   // 'chat' | 'doc'
})

// doc 变体不压标题层级：长文档里 h1/h2 的主次关系是重要的阅读线索
// doc 变体还拆 frontmatter：Obsidian 风格的 .md 开头那段 YAML 不该裸着糊在正文里
const html = computed(() =>
  renderMarkdown(props.content, {
    headingOffset: props.variant === 'doc' ? 0 : 2,
    frontmatter: props.variant === 'doc',
  }))
</script>
