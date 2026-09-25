<template>
  <div class="note-editor">
    <!-- 标题 -->
    <div class="title-row">
      <el-input
        v-model="localTitle"
        placeholder="笔记标题..."
        size="large"
        class="title-input"
        @blur="emitChange"
      />
    </div>

    <!-- 标签 -->
    <div class="meta-row">
      <el-tag
        v-for="t in localTags"
        :key="t"
        closable
        type="info"
        size="small"
        @close="removeTag(t)"
      >#{{ t }}</el-tag>
      <el-input
        v-if="tagInputVisible"
        ref="tagInputRef"
        v-model="tagInputValue"
        size="small"
        class="tag-input"
        @keyup.enter="addTag"
        @blur="addTag"
      />
      <el-button v-else size="small" plain @click="showTagInput">
        <el-icon><Plus /></el-icon>标签
      </el-button>
    </div>

    <!-- 内容编辑区 -->
    <div class="content-row">
      <div class="editor-wrap">
        <textarea
          ref="textareaRef"
          v-model="localContent"
          class="editor"
          placeholder="开始书写... 使用 [[笔记标题]] 创建双向链接"
          @input="onContentInput"
          @keyup="onKeyUp"
          @blur="emitChange"
        ></textarea>
        <!-- 高亮覆盖层 -->
        <div ref="overlayRef" class="overlay" v-html="highlightedContent"></div>
        <!-- 双链建议（绝对定位在 textarea 内的光标位置） -->
        <div
          v-if="suggestionVisible"
          class="suggestion-popper"
          :style="suggestionStyle"
        >
          <div
            v-for="s in suggestions"
            :key="s.title"
            class="suggestion-item"
            @mousedown.prevent="applySuggestion(s.title)"
          >
            <span>{{ s.exists ? '📄' : '➕' }}</span>
            <span>{{ s.title }}</span>
            <span v-if="!s.exists" style="color:var(--text-tertiary);font-size:12px">（新建）</span>
          </div>
          <div v-if="!suggestions.length" class="suggestion-empty">
            按 Enter 新建「{{ suggestionQuery }}」
          </div>
        </div>
      </div>

      <!-- 实时预览面板 -->
      <div class="preview" v-html="renderedContent"></div>
    </div>

    <div class="footer-hint">
      💡 用 <code>[[标题]]</code> 创建双向链接，反向链接会自动建立
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { Api } from '../api'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  recordId: { type: Number, default: null },
})
const emit = defineEmits(['update:modelValue', 'change'])

const localTitle = ref(props.modelValue.title || '')
const localContent = ref(props.modelValue.content || '')
const localTags = ref(props.modelValue.tags || [])
const tagInputVisible = ref(false)
const tagInputValue = ref('')
const tagInputRef = ref(null)

const textareaRef = ref(null)
const overlayRef = ref(null)

// 双链建议
const suggestionVisible = ref(false)
const suggestionQuery = ref('')
const suggestionStart = ref(0)
const suggestionPos = ref({ top: 0, left: 0 })
const suggestions = ref([])

// 同步 props
watch(() => props.modelValue, (v) => {
  localTitle.value = v.title || ''
  localContent.value = v.content || ''
  localTags.value = v.tags || []
}, { deep: true })

const suggestionStyle = computed(() => ({
  top: suggestionPos.value.top + 'px',
  left: suggestionPos.value.left + 'px',
}))

function emitChange() {
  emit('update:modelValue', {
    title: localTitle.value,
    content: localContent.value,
    tags: localTags.value,
    parent: props.modelValue.parent,
  })
  emit('change')
}

// ============ 双链高亮 ============
const highlightedContent = computed(() => {
  let html = escapeHtml(localContent.value || '')
  html = html.replace(/\[\[([^\[\]\n]+?)\]\]/g, (_, title) => {
    return `<span class="wikilink" data-title="${escapeAttr(title)}">[[${escapeHtml(title)}]]</span>`
  })
  html = html.replace(/\n/g, '<br/>')
  return html
})

const renderedContent = computed(() => {
  let html = escapeHtml(localContent.value || '')
  html = html.replace(/\[\[([^\[\]\n]+?)\]\]/g, (_, title) => {
    return `<a class="wikilink-rendered" data-title="${escapeAttr(title)}" href="#/notes/by-title/${encodeURIComponent(title)}">${escapeHtml(title)}</a>`
  })
  html = html
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
  return html
})

function escapeHtml(s) {
  return (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, '&quot;')
}

// ============ 标签 ============
function showTagInput() {
  tagInputVisible.value = true
  nextTick(() => tagInputRef.value?.focus?.())
}
function addTag() {
  const t = tagInputValue.value.trim()
  if (t && !localTags.value.includes(t)) {
    localTags.value = [...localTags.value, t]
    emitChange()
  }
  tagInputValue.value = ''
  tagInputVisible.value = false
}
function removeTag(t) {
  localTags.value = localTags.value.filter(x => x !== t)
  emitChange()
}

// ============ 双链自动补全 ============
async function onContentInput() {
  const ta = textareaRef.value
  if (!ta) return
  const pos = ta.selectionStart
  const text = localContent.value.slice(0, pos)

  // 检测 [[... 模式
  const m = /\[\[([^\[\]\n]*)$/.exec(text)
  if (!m) {
    suggestionVisible.value = false
    return
  }
  suggestionStart.value = pos - m[1].length - 2
  suggestionQuery.value = m[1]

  // 计算光标位置（粗略：从行号算 top，列号算 left）
  const before = localContent.value.slice(0, suggestionStart.value)
  const lines = before.split('\n')
  const lineIdx = lines.length - 1
  const col = lines[lineIdx].length
  // 假设每行约 22px，行高 1.7 * 14 = 24px，字符宽约 8px
  suggestionPos.value = {
    top: 16 + (lineIdx + 1) * 24 + 4,
    left: 16 + col * 8,
  }
  suggestionVisible.value = true

  // 查询匹配笔记
  try {
    const noteType = await Api.getEntityTypeByKey('note')
    const res = await Api.listRecords(noteType.id, {
      keyword: m[1], page_size: 10,
    })
    suggestions.value = (res.items || []).map(r => ({
      title: r.data.title,
      exists: true,
    }))
  } catch (e) {
    suggestions.value = []
  }
}

function onKeyUp(e) {
  // Enter 应用建议
  if (e.key === 'Enter' && suggestionVisible.value) {
    if (suggestions.value.length) {
      applySuggestion(suggestions.value[0].title)
    } else if (suggestionQuery.value) {
      applySuggestion(suggestionQuery.value)
    }
    e.preventDefault()
  }
  // Esc 关闭建议
  if (e.key === 'Escape') {
    suggestionVisible.value = false
  }
}

function applySuggestion(title) {
  const ta = textareaRef.value
  if (!ta) return
  const pos = ta.selectionStart
  const before = localContent.value.slice(0, suggestionStart.value)
  const after = localContent.value.slice(pos)
  const insertion = `${title}]]`
  localContent.value = before + insertion + after
  suggestionVisible.value = false
  nextTick(() => {
    const newPos = before.length + insertion.length
    ta.setSelectionRange(newPos, newPos)
    ta.focus()
    emitChange()
  })
}
</script>

<style scoped>
.note-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.title-row {
  display: flex;
  align-items: center;
}
.title-input :deep(.el-input__wrapper) {
  background: transparent;
  box-shadow: none !important;
  font-size: 24px;
  font-weight: 600;
}
.title-input :deep(.el-input__inner) {
  font-size: 24px;
  font-weight: 600;
}
.meta-row {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.tag-input { width: 120px; }

.content-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  min-height: 500px;
}
.editor-wrap {
  position: relative;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
}
.editor, .overlay {
  position: absolute;
  inset: 0;
  padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-wrap: break-word;
  overflow-y: auto;
  margin: 0;
  border: 0;
  outline: none;
}
.editor {
  background: transparent;
  color: transparent;
  caret-color: var(--text-primary);
  resize: none;
  z-index: 2;
}
.overlay {
  color: var(--text-primary);
  z-index: 1;
  pointer-events: none;
}
.overlay :deep(.wikilink) {
  color: var(--primary);
  background: rgba(64, 158, 255, 0.08);
  padding: 0 4px;
  border-radius: 3px;
}
.preview {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  background: var(--bg-card);
  overflow-y: auto;
  max-height: 600px;
  line-height: 1.7;
}
.preview :deep(.wikilink-rendered) {
  color: var(--primary);
  text-decoration: none;
  background: rgba(64, 158, 255, 0.08);
  padding: 1px 4px;
  border-radius: 3px;
}
.preview :deep(.wikilink-rendered):hover {
  background: rgba(64, 158, 255, 0.16);
}
.preview :deep(h1) { font-size: 24px; margin: 16px 0 8px; }
.preview :deep(h2) { font-size: 20px; margin: 14px 0 6px; }
.preview :deep(h3) { font-size: 16px; margin: 12px 0 4px; }
.preview :deep(code) {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 13px;
}

.suggestion-popper {
  position: absolute;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 4px;
  max-height: 240px;
  overflow-y: auto;
  min-width: 240px;
  z-index: 10;
}
.suggestion-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}
.suggestion-item:hover {
  background: var(--bg);
}
.suggestion-empty {
  padding: 8px 12px;
  color: var(--text-tertiary);
  font-size: 13px;
}

.footer-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  padding: 4px 0;
}
.footer-hint code {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, monospace;
}
</style>