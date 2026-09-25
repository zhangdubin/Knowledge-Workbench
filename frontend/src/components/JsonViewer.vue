<template>
  <div class="json-viewer">
    <div v-if="error" class="jv-msg is-error">
      <el-icon><WarningFilled /></el-icon>
      <span class="jv-msg-text">{{ error }}</span>
    </div>

    <div v-else-if="!nodes.length" class="jv-msg">
      <el-icon><DocumentRemove /></el-icon>
      <span class="jv-msg-text">（空）</span>
    </div>

    <template v-else>
      <div v-if="showToolbar" class="jv-toolbar">
        <div class="jv-badges">
          <span class="jv-badge jv-badge-type">{{ kindLabel(rootKind) }}</span>
          <span class="jv-badge">节点 {{ summary.nodeCount }}</span>
          <span v-if="summary.maxDepth" class="jv-badge">深度 {{ summary.maxDepth }}</span>
          <span v-if="summary.textLength" class="jv-badge">文本 {{ summary.textLength }} 字</span>
        </div>
        <div class="jv-actions">
          <el-button size="small" text @click="expandAll(true)">展开全部</el-button>
          <el-button size="small" text @click="expandAll(false)">折叠</el-button>
          <el-button v-if="copyable" size="small" text @click="copy">
            <el-icon><CopyDocument /></el-icon>{{ copied ? '已复制' : '复制 JSON' }}
          </el-button>
        </div>
      </div>

      <div class="jv-body">
        <JsonNode
          v-for="(n, i) in nodes"
          :key="i"
          :node="n"
          :depth="0"
          :last="true"
          :expand-tick="expandTick"
          :expand-to="expandTo"
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { WarningFilled, DocumentRemove, CopyDocument } from '@element-plus/icons-vue'
import JsonNode from './JsonNode.vue'
import { parseJson, toTree, summarize, stringifyJson, kindLabel } from '../utils/jsonview'

const props = defineProps({
  /** 服务端返回的节点数组（优先） */
  tree: { type: Array, default: null },
  /** 原始文本，前端自行解析 */
  text: { type: String, default: '' },
  /** 原始对象，直接渲染 */
  value: { type: null, default: undefined },
  /** 只有节点树、拿不到对象时，提供原文用于「复制 JSON」 */
  copyText: { type: String, default: '' },
  showToolbar: { type: Boolean, default: true },
})

const expandTick = ref(0)
const expandTo = ref(true)
const copied = ref(false)

function expandAll(to) {
  expandTo.value = to
  expandTick.value += 1
}

/** 统一入口：tree / value / text 三种来源归一成 { nodes, value, error } */
const resolved = computed(() => {
  if (props.tree && props.tree.length) {
    return { nodes: props.tree, value: undefined, error: '' }
  }
  if (props.value !== undefined && props.value !== null) {
    return { nodes: toTree(props.value), value: props.value, error: '' }
  }
  const raw = props.text || ''
  if (!raw.trim()) return { nodes: [], value: undefined, error: '' }
  const r = parseJson(raw)
  if (!r.ok) return { nodes: [], value: undefined, error: r.error }
  return { nodes: toTree(r.value), value: r.value, error: '' }
})

const nodes = computed(() => resolved.value.nodes)
const error = computed(() => resolved.value.error)

const rootKind = computed(() => nodes.value[0]?.kind || 'object')

/** 有原始值时按值统计，只有节点时按节点统计 —— 两者口径一致 */
const summary = computed(() => {
  if (resolved.value.value !== undefined) return summarize(resolved.value.value)
  const stat = { nodeCount: 0, textLength: 0, maxDepth: 0 }
  const walk = (n, depth) => {
    stat.nodeCount += 1
    if (n.kind === 'string') stat.textLength += n.chars || 0
    if (n.kind === 'object' || n.kind === 'array') {
      if (depth > stat.maxDepth) stat.maxDepth = depth
      for (const c of n.children || []) walk(c, depth + 1)
    }
  }
  for (const n of nodes.value) walk(n, 0)
  return stat
})

const copyable = computed(() =>
  resolved.value.value !== undefined || !!props.copyText)

async function copy() {
  const text = resolved.value.value !== undefined
    ? stringifyJson(resolved.value.value)
    : (props.copyText || '')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    copied.value = false
  }
}
</script>

<style scoped>
.json-viewer {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.jv-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: 8px 12px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-light);
}
.jv-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.jv-badge {
  font-size: 11.5px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.jv-badge-type { background: var(--primary-bg); color: var(--primary); font-weight: 600; }
.jv-actions { margin-left: auto; display: flex; gap: 2px; }

.jv-body {
  padding: 12px;
  max-height: 520px;
  overflow: auto;
}

.jv-msg {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 20px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.jv-msg.is-error {
  color: var(--danger);
  background: var(--danger-bg);
}
.jv-msg-text { word-break: break-word; }
</style>
