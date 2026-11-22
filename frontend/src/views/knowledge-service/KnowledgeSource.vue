<template>
  <div class="ks-stack">
    <div v-if="source.group_revisions?.some(item => item.id !== source.id)" class="ks-form">
      <label>
        <span>对照版本</span>
        <select :disabled="checking" :value="comparison.target || ''" @change="$emit('compare', $event.target.value)">
          <option value="">选择同组资料版本</option>
          <option v-for="item in source.group_revisions.filter(row => row.id !== source.id)" :key="item.id" :value="item.id">
            {{ item.label }} · {{ effectivePeriod(item) }}
          </option>
        </select>
      </label>
    </div>
    <p v-if="source.group_incomplete" class="ks-muted">仅显示检索限额内的同组版本。</p>
    <p v-if="comparison.busy" role="status">正在打开对照版本…</p>
    <p v-if="comparison.error" role="alert" class="ks-error">{{ comparison.error }}</p>
    <p v-if="comparison.data" class="ks-meta">
      {{ source.text === comparison.data.text ? '两版快照文字相同。' : '两版快照文字存在差异，可对照下方原文。' }}
    </p>

    <div class="ks-snapshots" :class="{ 'ks-snapshots-pair': comparison.data }">
      <article v-for="(version, index) in versions" :key="version.id" class="ks-stack ks-snapshot">
        <div>
          <p v-if="comparison.data" class="ks-kicker">{{ index === 0 ? '所选版本' : '对照版本' }}</p>
          <h4>{{ version.label }}</h4>
        </div>
        <div class="ks-meta">
          <span>{{ effectivePeriod(version) }}</span>
          <span v-if="version.scope">{{ version.scope }}</span>
          <span v-if="version.topic">{{ version.topic }}</span>
          <span>登记于 {{ dateTime(version.recorded_at) }}</span>
        </div>
        <div v-if="predecessor(version) || successor(version)" class="ks-meta">
          <span v-if="predecessor(version)">明确替代 {{ predecessor(version).label }}</span>
          <span v-if="successor(version)">由 {{ successor(version).label }} 自 {{ successor(version).effective_from }} 起替代</span>
        </div>
        <div v-if="index === 0 && citation" class="ks-stack">
          <p v-if="parts" class="ks-meta" role="status">已在固定快照中定位引文（第 {{ citation.start + 1 }} 至 {{ citation.end }} 个字符）。</p>
          <p v-else class="ks-error" role="alert">当前固定快照中的文字与引文位置无法核对。</p>
          <button v-if="parts" type="button" class="ks-button ks-text" @click="focusQuote">
            跳到高亮引文
          </button>
        </div>
        <div class="ks-snapshot-entry">
          <h5>固定原文快照</h5>
          <div class="ks-snapshot-text" tabindex="0" :aria-label="`固定原文快照 · ${version.label}`">
            <template v-if="index === 0 && parts">{{ parts[0] }}<mark ref="quoteMark" tabindex="-1">{{ parts[1] }}</mark>{{ parts[2] }}</template>
            <template v-else>{{ version.text || '该资料未提供可显示的抽取文字。' }}</template>
          </div>
        </div>
        <div class="ks-stack">
          <a v-if="version.original_document_url" class="ks-button ks-text" :href="version.original_document_url" target="_blank" rel="noopener">
            打开当前原文件（新窗口）
          </a>
          <p v-if="version.original_document_changed" class="ks-muted">当前原文件有更新。引用定位以固定原文快照为准。</p>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { dateTime, effectivePeriod, quoteParts } from '../../utils/knowledgeService.js'

const props = defineProps({
  source: { type: Object, required: true },
  comparison: { type: Object, required: true },
  citation: { type: Object, default: null },
  checking: Boolean,
})
defineEmits(['compare'])
const quoteMark = ref([])
const versions = computed(() => [props.source, props.comparison.data].filter(Boolean))
const parts = computed(() => {
  const { source, citation } = props
  if (!citation || citation.snapshot_id !== source.snapshot_id || citation.document_id !== source.document_id) return null
  return quoteParts(source.text, citation)
})
const predecessor = version => version.group_revisions?.find(row => row.id === version.supersedes_id)
const successor = version => version.group_revisions?.find(row => row.supersedes_id === version.id)
function focusQuote() {
  quoteMark.value[0]?.focus()
}
</script>
