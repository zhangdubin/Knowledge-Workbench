<template>
  <el-dialog
    v-model="visible"
    title="引用养料库基因"
    width="720px"
    append-to-body
    destroy-on-close
    class="gene-picker"
    @open="onOpen"
  >
    <div class="gp-head">
      <el-input
        v-model="q"
        placeholder="搜基因：标题、正文里的词（Ctrl+Enter 复制第一条）"
        clearable
        autofocus
        @keyup.enter="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="kind" size="default" class="gp-kind">
        <el-option label="全部种类" value="" />
        <el-option v-for="k in KINDS" :key="k.key" :label="k.label" :value="k.key" />
      </el-select>
    </div>

    <div class="gp-body">
      <div class="gp-list">
        <div v-if="loading" class="gp-empty">找基因中…</div>
        <div v-else-if="!items.length" class="gp-empty">
          没找到基因。换个词，或者去养料库吸收点东西。
        </div>
        <button
          v-for="g in items"
          :key="g.id"
          type="button"
          class="gp-item"
          :class="{ picked: picked.includes(g.id) }"
          @click="toggle(g)"
        >
          <span class="gp-kind-tag" :class="g.kind">{{ g.kind_label || g.kind }}</span>
          <span class="gp-item-title">{{ g.title }}</span>
          <span class="gp-item-src">{{ g.source_title || '养料库' }}</span>
          <span v-if="picked.includes(g.id)" class="gp-pick">已选</span>
        </button>
      </div>

      <div class="gp-preview">
        <div v-if="!preview" class="gp-empty">选一条看内容</div>
        <template v-else>
          <div class="gp-pv-head">
            <span class="gp-kind-tag" :class="preview.kind">{{ preview.kind_label || preview.kind }}</span>
            <span class="gp-pv-title">{{ preview.title }}</span>
          </div>
          <pre class="gp-pv-body">{{ preview.content }}</pre>
          <div class="gp-pv-meta">
            <span>被用 {{ preview.usage_count || 0 }} 次</span>
            <span>置信 {{ preview.confidence }}</span>
            <span v-if="preview.source_title">出处 {{ preview.source_title }}</span>
          </div>
        </template>
      </div>
    </div>

    <template #footer>
      <div class="gp-foot">
        <span class="gp-tip">已选 {{ picked.length }} 条</span>
        <div>
          <el-button @click="visible = false">取消</el-button>
          <el-button v-if="mode === 'insert'" type="primary" :disabled="!picked.length" @click="doInsert">
            <el-icon><EditPen /></el-icon>插入
          </el-button>
          <el-button v-else-if="mode === 'copy'" type="primary" :disabled="!picked.length" @click="doCopy">
            <el-icon><CopyDocument /></el-icon>复制引用
          </el-button>
          <el-button v-else type="primary" :disabled="!picked.length" @click="doPick">
            <el-icon><Select /></el-icon>使用
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 基因选择器 —— 养料库在系统任何地方的入口
 *
 * 为什么要有这个组件：
 *   养料库里的知识如果只能通过「去养料库页面找」来用，
 *   那它就只是个列表，不是能用的库。
 *   这个组件让「找一条知识 → 用上它」变成两步，
 *   而且可以在任何页面叫起来。
 *
 * mode:
 *   pick   —— 选中（AI 问答里钉住基因）
 *   insert —— 插入一段 Markdown 引用（笔记编辑器）
 *   copy   —— 复制一段带出处的引用（任何地方）
 */
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  mode: { type: String, default: 'pick' },
  multiple: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue', 'pick', 'insert', 'copy'])

const KINDS = [
  { key: 'fact', label: '事实' },
  { key: 'method', label: '方法' },
  { key: 'experience', label: '经验' },
  { key: 'interface', label: '接口' },
  { key: 'policy', label: '约定' },
]

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const q = ref('')
const kind = ref('')
const items = ref([])
const picked = ref([])
const preview = ref(null)
const loading = ref(false)

function onOpen() {
  picked.value = []
  preview.value = null
  q.value = ''
  kind.value = ''
  search()
}

async function search() {
  loading.value = true
  try {
    const r = await Api.dnaLibraryGenes({
      q: q.value, kind: kind.value, status: 'active', limit: 40,
      sort: 'usage',
    })
    items.value = r.items || []
    if (!preview.value && items.value.length) preview.value = items.value[0]
  } catch (e) {
    ElMessage.error('搜基因失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function toggle(g) {
  const i = picked.value.indexOf(g.id)
  if (i >= 0) {
    picked.value = picked.value.filter((x) => x !== g.id)
  } else if (!props.multiple) {
    picked.value = [g.id]
  } else {
    picked.value = [...picked.value, g.id]
  }
  preview.value = g
}

function chosen() {
  return items.value.filter((g) => picked.value.includes(g.id))
}

function doPick() {
  emit('pick', chosen())
  visible.value = false
}

async function doInsert() {
  try {
    const r = await Api.dnaLibraryCite({ gene_ids: picked.value, format: 'markdown' })
    emit('insert', r.text || '')
    visible.value = false
  } catch (e) {
    ElMessage.error('生成引用失败：' + (e?.message || e))
  }
}

async function doCopy() {
  try {
    const r = await Api.dnaLibraryCite({ gene_ids: picked.value, format: 'markdown' })
    const text = r.text || ''
    try {
      await navigator.clipboard.writeText(text)
    } catch (e) {
      // 没有剪贴板权限时退回到临时 textarea
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    emit('copy', text)
    ElMessage.success(`已复制 ${picked.value.length} 条基因的引用`)
    visible.value = false
  } catch (e) {
    ElMessage.error('复制失败：' + (e?.message || e))
  }
}
</script>

<style scoped>
.gp-head { display: flex; gap: 10px; margin-bottom: 12px; }
.gp-kind { width: 132px; flex-shrink: 0; }
.gp-body {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  height: 380px;
}
.gp-list {
  overflow-y: auto; border: 1px solid var(--border-light);
  border-radius: 10px; padding: 6px; background: var(--bg-card);
}
.gp-item {
  display: flex; align-items: center; gap: 7px; width: 100%;
  padding: 7px 8px; border: none; background: transparent;
  border-radius: 7px; cursor: pointer; text-align: left;
  font-family: inherit; color: var(--text-primary);
}
.gp-item:hover { background: var(--bg-subtle); }
.gp-item.picked { background: var(--primary-bg); }
.gp-kind-tag {
  flex-shrink: 0; font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: var(--bg-subtle); color: var(--text-secondary);
}
.gp-kind-tag.fact { background: rgba(59, 111, 212, .12); color: var(--accent-blue); }
.gp-kind-tag.method { background: rgba(15, 139, 141, .12); color: var(--accent-teal); }
.gp-kind-tag.experience { background: rgba(192, 124, 23, .13); color: var(--accent-amber); }
.gp-kind-tag.interface { background: rgba(47, 143, 78, .12); color: var(--accent-green); }
.gp-kind-tag.policy { background: rgba(107, 75, 196, .12); color: var(--accent-violet); }
.gp-item-title {
  flex: 1; min-width: 0; font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gp-item-src {
  font-size: 11px; color: var(--text-secondary); flex-shrink: 0;
  max-width: 92px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gp-pick { font-size: 11px; color: var(--primary); flex-shrink: 0; }
.gp-preview {
  border: 1px solid var(--border-light); border-radius: 10px;
  padding: 12px; background: var(--bg-subtle); overflow-y: auto;
}
.gp-pv-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.gp-pv-title { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.gp-pv-body {
  margin: 0; font-size: 12px; line-height: 1.7; white-space: pre-wrap;
  word-break: break-word; color: var(--text-primary);
  font-family: var(--font-mono, ui-monospace, monospace);
}
.gp-pv-meta {
  display: flex; gap: 12px; margin-top: 10px; padding-top: 8px;
  border-top: 1px dashed var(--border-light);
  font-size: 11.5px; color: var(--text-secondary); flex-wrap: wrap;
}
.gp-empty {
  padding: 24px 12px; text-align: center; color: var(--text-secondary);
  font-size: 13px;
}
.gp-foot { display: flex; align-items: center; justify-content: space-between; }
.gp-tip { font-size: 12.5px; color: var(--text-secondary); }
@media (max-width: 760px) {
  .gp-body { grid-template-columns: 1fr; height: auto; }
  .gp-list { max-height: 220px; }
  .gp-preview { max-height: 220px; }
}
</style>
