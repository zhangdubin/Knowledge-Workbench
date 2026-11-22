<template>
  <figure class="citation">
    <blockquote>{{ evidence.quote }}</blockquote>
    <figcaption>
      <router-link :to="{ path: '/library', query: { doc: evidence.document_id } }">{{
        evidence.title || '文档 #' + evidence.document_id
      }}</router-link>
      · 字符 [{{ evidence.start }}, {{ evidence.end }})
    </figcaption>
    <details>
      <summary>固定证据位置</summary>
      <p>快照 {{ evidence.snapshot_id }} · 解析器 {{ evidence.parser }}</p>
      <p>原文摘要 {{ evidence.text_sha }}</p>
      <p v-if="evidence.chunk_id">片段 #{{ evidence.chunk_id }}</p>
    </details>
  </figure>
</template>
<script setup>
defineProps({ evidence: { type: Object, required: true } })
</script>
<style scoped>
.citation {
  border-inline-start: 3px solid var(--el-color-primary);
  padding-inline-start: 12px;
  margin: 12px 0;
  color: var(--el-text-color-regular);
  overflow-wrap: anywhere;
  font-size: 13px;
}
.citation blockquote {
  white-space: pre-wrap;
  margin: 4px 0;
}
.citation a {
  color: var(--el-color-primary);
}
</style>
