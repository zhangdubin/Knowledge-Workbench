<template>
  <!--
    排版预览
    ---------------------------------------------------------------------------
    「自动排版」最怕两件事：偷偷改了、改坏了。所以这里默认给看：
      · 左边是改了什么（按规范条款列出来）
      · 右边是排完之后长什么样（用笔记正文的同一套渲染）
    用户点「应用」才动正文；点「取消」一个字都不会变。

    这个弹窗**不依赖 AI**：排版是确定性规则（services/note_format.py），
    没配 AI Key 的部署一样能用。
  -->
  <DialogShell
    :model-value="modelValue"
    title="按《笔记 UI 排版规范》排版"
    description="规则排版，不调用模型。先看结果，再决定要不要用。"
    size="lg"
    :loading="loading"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="runPreview"
  >
    <div v-if="error" class="fmt-error">{{ error }}</div>

    <template v-else-if="result">
      <div class="fmt-summary">
        <span class="fmt-badge" :class="{ 'is-clean': !changes.length }">
          {{ changes.length ? `改了 ${changes.length} 类 · ${totalCount} 处` : '已经很规范了' }}
        </span>
        <span class="fmt-stat">
          {{ stats.lines }} 行 · {{ stats.h2 }} 个二级标题 · {{ stats.code_blocks }} 段代码
          <template v-if="stats.secrets"> · {{ stats.secrets }} 处凭证已遮盖</template>
        </span>
        <!-- AI 结构化：TL;DR / 风险表 / 目标表 / 时间线。
             关掉也能排（规则版），打开才做「读懂内容」那一步 -->
        <label class="fmt-ai" title="让模型提取 TL;DR、风险清单、目标资产与时间线（可能需要 30–90 秒；没配 AI 或超时会自动用规则版）">
          <el-switch v-model="useAi" size="small" @change="runPreview" />
          <span>AI 结构化</span>
          <span v-if="result && result.ai" class="fmt-ai-on">已启用</span>
          <span v-else-if="useAi && result" class="fmt-ai-off">未取到（已用规则版）</span>
        </label>
      </div>

      <div class="fmt-tabs" role="tablist">
        <button
          v-for="t in tabs"
          :key="t.key"
          type="button"
          role="tab"
          class="fmt-tab"
          :class="{ 'is-on': tab === t.key }"
          :aria-selected="tab === t.key"
          @click="tab = t.key"
        >{{ t.label }}<span v-if="t.key === 'changes' && changes.length" class="fmt-tab-num">{{ changes.length }}</span></button>
      </div>

      <!-- 改了什么 -->
      <ul v-if="tab === 'changes'" class="fmt-changes">
        <li v-for="c in changes" :key="c.key" class="fmt-change">
          <span class="fmt-change-sec">{{ c.section }}</span>
          <span class="fmt-change-text">{{ c.title }}</span>
        </li>
        <li v-if="!changes.length" class="fmt-empty">
          这篇笔记已经符合规范，排版不会改动任何内容。
        </li>
      </ul>

      <!-- 要素体检：参考样板里那些「该有的东西」有没有 -->
      <ul v-else-if="tab === 'elements'" class="fmt-elements">
        <li
          v-for="e in elements"
          :key="e.id"
          class="fmt-element"
          :class="{ 'is-missing': !e.present }"
        >
          <span class="fmt-element-ico">{{ e.present ? '✓' : '○' }}</span>
          <span class="fmt-element-sec">{{ e.section }}</span>
          <span class="fmt-element-name">{{ e.name }}</span>
        </li>
        <li class="fmt-element-foot">
          缺 {{ missingCount }} 项。选题材模板（渗透/排障/教程）新建，能一次性把这些骨架铺好。
        </li>
      </ul>

      <!-- 排完之后 -->
      <div v-else class="fmt-preview md-body md-body-doc note-body">
        <MarkdownText :content="result.text" variant="doc" />
      </div>
    </template>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="!result || !changes.length"
        @click="apply"
      >
        {{ changes.length ? '应用到正文' : '无需改动' }}
      </el-button>
    </template>
  </DialogShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import DialogShell from './DialogShell.vue'
import MarkdownText from './MarkdownText.vue'
import { Api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  content: { type: String, default: '' },
  title: { type: String, default: '' },
  tags: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'apply'])

const loading = ref(false)
const error = ref('')
const result = ref(null)
const tab = ref('changes')

const tabs = [
  { key: 'changes', label: '改了什么' },
  { key: 'result', label: '排完之后' },
  { key: 'elements', label: '要素体检' },
]

// AI 结构化：默认开（有 AI 就多用一点），没配 AI 时后端会自动退回规则版
// 默认关：AI 结构化要调模型（当前模型一次 30–90 秒），
// 交互式预览默认不能等。需要用的时候打开，结果会缓存。
const useAi = ref(false)

const changes = computed(() => result.value?.changes || [])
const elements = computed(() => result.value?.elements || [])
const missingCount = computed(() => elements.value.filter(e => !e.present).length)
const stats = computed(() => result.value?.stats || { lines: 0, h2: 0, code_blocks: 0, secrets: 0 })
const totalCount = computed(() => changes.value.reduce((n, c) => n + (c.count || 1), 0))

async function runPreview() {
  result.value = null
  error.value = ''
  if (!(props.content || '').trim()) {
    error.value = '正文是空的，没什么可排的。先去写两句。'
    return
  }
  loading.value = true
  try {
    const r = await Api.noteFormat({
      content: props.content,
      title: props.title || '',
      tags: props.tags || [],
      use_ai: useAi.value,
    })
    result.value = r
    tab.value = (r.changes || []).length ? 'changes' : 'result'
  } catch (e) {
    error.value = '排版失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

function apply() {
  if (!result.value) return
  emit('apply', result.value.text)
  emit('update:modelValue', false)
}
</script>

<style scoped>
.fmt-error {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--danger-bg, #fdedec);
  color: var(--danger, #c0392b);
  font-size: var(--text-sm);
}

.fmt-summary {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.fmt-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--primary-bg);
  color: var(--primary);
}
.fmt-badge.is-clean {
  background: var(--bg-subtle);
  color: var(--text-secondary);
}
.fmt-stat {
  font-size: 12px;
  color: var(--text-tertiary);
}

.fmt-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border-light);
  margin-bottom: 10px;
}
.fmt-tab {
  border: none;
  background: none;
  padding: 7px 12px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.fmt-tab.is-on {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}
.fmt-tab-num {
  font-size: 11px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.fmt-changes {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 46vh;
  overflow-y: auto;
}
.fmt-change {
  display: flex;
  gap: 10px;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border-light);
  font-size: var(--text-sm);
}
.fmt-change:last-child { border-bottom: none; }
.fmt-change-sec {
  flex-shrink: 0;
  width: 64px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.fmt-change-text { color: var(--text-primary); }
.fmt-empty {
  padding: 14px 4px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

/* AI 开关 */
.fmt-ai {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}
.fmt-ai-off {
  font-size: 11px;
  color: var(--text-tertiary);
}
.fmt-ai-on {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--primary-bg);
  color: var(--primary);
}

/* 要素体检 */
.fmt-elements {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 16px;
  max-height: 46vh;
  overflow-y: auto;
}
.fmt-element {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  font-size: var(--text-sm);
  border-bottom: 1px solid var(--border-light);
}
.fmt-element-ico {
  width: 14px;
  text-align: center;
  color: var(--success, #2a9d8f);
  font-weight: 700;
}
.fmt-element.is-missing .fmt-element-ico { color: var(--text-tertiary); }
.fmt-element.is-missing .fmt-element-name { color: var(--text-tertiary); }
.fmt-element-sec {
  flex-shrink: 0;
  width: 56px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.fmt-element-name { color: var(--text-primary); }
.fmt-element-foot {
  grid-column: 1 / -1;
  padding-top: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.fmt-preview {
  max-height: 52vh;
  overflow-y: auto;
  padding: 4px 10px 10px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
}
</style>
