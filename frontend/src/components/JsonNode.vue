<template>
  <div class="jn-node">
    <div
      class="jn-row"
      :class="[`k-${node.kind}`, { 'is-container': isContainer, 'is-index': node.isIndex }]"
      @click="onRowClick"
    >
      <span v-if="isContainer" class="jn-toggle" :class="{ open }">
        <el-icon><CaretRight /></el-icon>
      </span>
      <span v-else class="jn-dot"></span>

      <span v-if="showKey" class="jn-key">
        <template v-if="node.isIndex">[{{ node.key }}]</template>
        <template v-else>"{{ node.key }}"</template>
        <span class="jn-colon">:</span>
      </span>

      <template v-if="isContainer">
        <span class="jn-bracket">{{ openBracket }}</span>
        <template v-if="!open">
          <span class="jn-count">
            {{ node.count ? `… ${node.count} ${node.kind === 'array' ? '项' : '个键'} …` : '空' }}
          </span>
          <span class="jn-bracket">{{ closeBracket }}</span>
        </template>
      </template>

      <template v-else>
        <span class="jn-val">{{ display }}</span>
        <span v-if="overflow" class="jn-chars">{{ node.chars }} 字</span>
      </template>

      <span v-if="!last" class="jn-comma">,</span>
    </div>

    <template v-if="isContainer && open">
      <div class="jn-children">
        <JsonNode
          v-for="(child, i) in node.children"
          :key="i"
          :node="child"
          :depth="depth + 1"
          :last="i === node.children.length - 1 && !node.truncated"
          :expand-tick="expandTick"
          :expand-to="expandTo"
        />
        <div v-if="node.truncated" class="jn-row jn-trunc">… 内容过大，已截断</div>
        <div class="jn-row jn-tail">
          <span class="jn-dot"></span>
          <span class="jn-bracket">{{ closeBracket }}</span>
          <span v-if="!last" class="jn-comma">,</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { CaretRight } from '@element-plus/icons-vue'
import { MAX_PREVIEW } from '../utils/jsonview'

defineOptions({ name: 'JsonNode' })

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  last: { type: Boolean, default: true },
  // 展开/折叠全部：用一个自增信号驱动，避免层层透传事件
  expandTick: { type: Number, default: 0 },
  expandTo: { type: Boolean, default: true },
})

const isContainer = computed(() => props.node.kind === 'object' || props.node.kind === 'array')
const openBracket = computed(() => (props.node.kind === 'array' ? '[' : '{'))
const closeBracket = computed(() => (props.node.kind === 'array' ? ']' : '}'))
const showKey = computed(() => props.node.key !== null && props.node.key !== undefined)
const overflow = computed(
  () => props.node.chars != null && props.node.chars > MAX_PREVIEW
)

const display = computed(() => {
  const v = props.node.value
  if (props.node.kind === 'string') return `"${v}"`
  return v
})

// 浅层默认展开，深层默认折叠 —— 大文档一进来不会糊成一片
const open = ref(props.depth < 2)
watch(() => props.node.kind, () => { open.value = props.depth < 2 })
watch(
  () => props.expandTick,
  () => { if (isContainer.value) open.value = props.expandTo }
)

function onRowClick() {
  if (isContainer.value) open.value = !open.value
}
</script>

<style scoped>
.jn-node { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.75; }

.jn-row {
  display: flex;
  align-items: baseline;
  gap: 2px;
  padding-left: 4px;
  border-radius: 3px;
}
.jn-row.is-container { cursor: pointer; }
.jn-row.is-container:hover { background: var(--bg-subtle); }

.jn-toggle {
  width: 16px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  transition: transform var(--duration-fast) var(--ease-out);
}
.jn-toggle.open { transform: rotate(90deg); }
.jn-dot { width: 16px; flex-shrink: 0; }

.jn-key { color: var(--jv-key); white-space: pre-wrap; word-break: break-all; }
.jn-colon { color: var(--text-tertiary); margin-right: 4px; }
.jn-bracket { color: var(--text-tertiary); font-weight: 600; }
.jn-count { color: var(--text-tertiary); font-size: 11.5px; padding: 0 6px; }
.jn-comma { color: var(--text-tertiary); }
.jn-chars { color: var(--text-tertiary); font-size: 11px; margin-left: 6px; }
.jn-trunc { color: var(--text-tertiary); font-size: 11.5px; padding-left: 20px; }

.jn-children {
  margin-left: 7px;
  padding-left: 8px;
  border-left: 1px solid var(--border-light);
}

/* 按类型着色 */
.k-string .jn-val { color: var(--jv-string); white-space: pre-wrap; word-break: break-all; }
.k-number .jn-val { color: var(--jv-number); }
.k-boolean .jn-val { color: var(--jv-bool); }
.k-null .jn-val { color: var(--jv-null); font-style: italic; }
.k-object .jn-bracket, .k-array .jn-bracket { color: var(--jv-bracket); }
.jn-row.is-index .jn-key { color: var(--jv-index); }
</style>
