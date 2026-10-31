<template>
  <!--
    Obsidian 风格的笔记编辑器
    ---------------------------------------------------------------------------
    两种用法：
      mode="quick" —— 知识库列表页顶部的「随手记」内联编辑器：
                      打开即聚焦标题栏，下面直接是正文，没有表单字段挡路。
      mode="full"  —— 笔记详情页的整页编辑：标题行内可编辑，正文可切「源码 / 预览」。

    键盘：
      ⌘/Ctrl + Enter  保存
      Esc             取消（先关掉双链候选，再退出编辑）
      标题里回车      跳到正文
  -->
  <div
    class="composer"
    :class="`composer-${mode}`"
    :style="{ '--composer-body-h': bodyHeight + 'px' }"
    @keydown="onKeydown"
  >
    <!-- 标题：Obsidian 里文件名就是第一行，所以标题框是主入口 -->
    <div class="composer-title-row">
      <el-icon class="composer-icon"><Notebook /></el-icon>
      <input
        ref="titleRef"
        :value="localTitle"
        class="composer-title"
        type="text"
        :placeholder="titlePlaceholder"
        aria-label="笔记标题"
        @input="onTitleInput"
        @keydown.enter.prevent="focusBody"
      />
      <span v-if="mode === 'full'" class="composer-mode-hint">标题行内可编辑</span>
    </div>

    <!-- 标签：chips 输入器 -->
    <TagInput
      :model-value="localTags"
      class="composer-tags"
      :suggestions="tagSuggestions"
      placeholder="添加标签（输入 # 选候选，, 确认）"
      aria-label="笔记标签"
      @update:model-value="onTagsChange"
      @tag-click="emit('tag-click', $event)"
    />

    <!-- 正文：源码 / 预览 -->
    <div class="composer-body" :class="{ 'is-preview': preview }">
      <div v-if="mode === 'full'" class="composer-switch" role="tablist" aria-label="正文视图">
        <button
          type="button"
          role="tab"
          class="composer-switch-btn"
          :class="{ 'is-on': !preview }"
          :aria-selected="!preview"
          @click="preview = false"
        >源码</button>
        <button
          type="button"
          role="tab"
          class="composer-switch-btn"
          :class="{ 'is-on': preview }"
          :aria-selected="preview"
          @click="preview = true"
        >预览</button>
      </div>

      <div v-if="!preview" class="composer-editor-wrap">
        <textarea
          ref="bodyRef"
          :value="localContent"
          class="composer-editor"
          placeholder="开始书写… 用 [[笔记标题]] 建立双向链接"
          aria-label="笔记正文"
          spellcheck="false"
          @input="onBodyInput"
          @keydown="onBodyKeydown"
          @scroll="onBodyScroll"
        ></textarea>
        <!-- 双链高亮覆盖层（与 textarea 同字体同间距，逐字对齐） -->
        <div ref="overlayRef" class="composer-overlay" aria-hidden="true" v-html="highlightedContent"></div>

        <!-- 双链候选：输入 [[ 时提示已有笔记 -->
        <div v-if="suggestVisible" class="composer-suggest" role="listbox" aria-label="双链候选">
          <button
            v-for="s in suggestions"
            :key="s.title"
            type="button"
            class="composer-suggest-item"
            role="option"
            :aria-selected="false"
            @mousedown.prevent="applySuggestion(s.title)"
          >
            <span class="composer-suggest-title">{{ s.title }}</span>
            <span v-if="!s.exists" class="composer-suggest-new">新建</span>
          </button>
          <div v-if="!suggestions.length" class="composer-suggest-empty">
            回车创建「{{ suggestQuery }}」
          </div>
        </div>
      </div>

      <div v-else class="composer-preview md-body md-body-doc note-body">
        <div v-if="localContent" v-html="renderedContent"></div>
        <div v-else class="composer-preview-empty">（空笔记）</div>
      </div>
    </div>

    <!-- 正文里写了 #标签 时的提示：Obsidian 里行内标签就是属性 -->
    <div v-if="inlineTags.length" class="composer-inline-tags">
      <span class="composer-inline-label">正文中的标签</span>
      <button
        v-for="t in inlineTags"
        :key="t"
        type="button"
        class="composer-inline-tag"
        :title="`把 #${t} 设为标签`"
        @click="addInlineTag(t)"
      >#{{ t }}</button>
    </div>

    <!-- 底部：快捷键提示 + 保存/取消 -->
    <div class="composer-foot">
      <span class="composer-hint">
        <kbd>⌘</kbd><kbd>↵</kbd> 保存
        <span class="composer-hint-sep">·</span>
        <kbd>Esc</kbd> 取消
      </span>
      <div class="composer-actions">
        <el-button size="small" text @click="emit('cancel')">取消</el-button>
        <el-button size="small" type="primary" @click="emit('save')">
          {{ mode === 'quick' ? '保存笔记' : '保存' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Notebook } from '@element-plus/icons-vue'
import { Api } from '../api'
import TagInput from './TagInput.vue'
import { extractHashtags, firstLineTitle, renderNoteHtml } from '../utils/notes'
import { highlightEditorText } from '../utils/editorHighlight'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  // quick = 列表页内联快速新建；full = 详情页整页编辑
  mode: { type: String, default: 'quick' },
  tagSuggestions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'save', 'cancel', 'change', 'tag-click'])

const localTitle = ref(props.modelValue.title || '')
const localContent = ref(props.modelValue.content || '')
const localTags = ref([...(props.modelValue.tags || [])])
const preview = ref(false)

const titleRef = ref(null)
const bodyRef = ref(null)
const overlayRef = ref(null)

// 双链候选
const suggestVisible = ref(false)
const suggestQuery = ref('')
const suggestStart = ref(0)
const suggestions = ref([])
const titleIndex = ref([])

// 标题为空时，用正文首行兜底（Obsidian 的文件名规则）
const titlePlaceholder = computed(() => {
  const derived = firstLineTitle(localContent.value)
  return derived || '未命名笔记'
})

const renderedContent = computed(() => renderNoteHtml(localContent.value))

// 正文里出现但还没设成标签的 #标签
const inlineTags = computed(() =>
  extractHashtags(localContent.value).filter(
    t => !localTags.value.some(x => x.toLowerCase() === t.toLowerCase())
  )
)

/**
 * 编辑器随内容变高
 *
 * 原来编辑区是固定 180px，长文本全挤在里面要滚动 ——
 * 而下面还压着一个同样 180px 的高亮覆盖层，两层**各滚各的**，
 * 于是「滑动没反应」：文字框动了，高亮层没动，看着像卡住了。
 *
 * 现在：
 *   1. 内容超过阈值时，编辑区跟着长高（到上限为止）
 *   2. 覆盖层与文字框滚动位置始终同步
 */
const MAX_AUTO_HEIGHT = 620   // 再高就该在页面里滚了，编辑器内部不再无限长

/** 编辑区实际高度（px） */
const bodyHeight = ref(0)

function autoGrow() {
  const ta = bodyRef.value
  if (!ta) return
  const cs = getComputedStyle(ta)
  const padY = parseFloat(cs.paddingTop || '0') + parseFloat(cs.paddingBottom || '0')
  const borderY = parseFloat(cs.borderTopWidth || '0') + parseFloat(cs.borderBottomWidth || '0')
  // scrollHeight 含内边距，减掉自身已有的 padding/border 才是内容高度
  const content = ta.scrollHeight - padY - borderY
  const base = props.mode === 'full' ? 420 : 180
  const next = Math.min(Math.max(base, content), MAX_AUTO_HEIGHT)
  bodyHeight.value = next
  ta.style.height = `${next}px`
  syncScroll()
}

/** 覆盖层跟着文字框滚 —— 两层不同步就是「滑动没反应」的元凶 */
function syncScroll() {
  const ta = bodyRef.value
  const ov = overlayRef.value
  if (!ta || !ov) return
  if (Math.abs(ov.scrollTop - ta.scrollTop) > 0.5) {
    ov.scrollTop = ta.scrollTop
  }
  if (Math.abs(ov.scrollLeft - ta.scrollLeft) > 0.5) {
    ov.scrollLeft = ta.scrollLeft
  }
}

function onBodyScroll() {
  syncScroll()
}

/**
 * 编辑区的高亮层
 *
 * 之前只把 [[双链]] 包成 span，别的什么都不管 ——
 * 所以在编辑器里写 ```bash 代码块，看着就是普通文字，
 * 「代码没被识别」就是这么来的。
 *
 * 现在用 editorHighlight 做**行内**高亮：标题、代码块围栏、
 * 行内代码、强调、任务列表、callout、双链都能认出来。
 *
 * 为什么不用 renderMarkdown：那个产出的是块级 HTML，
 * 行高和内外边距跟 textarea 对不上，字会错位、光标会飘。
 */
const highlightedContent = computed(() =>
  highlightEditorText(localContent.value || '', escapeHtml)
    .replace(/\n/g, '<br/>')
)

watch(() => props.modelValue, v => {
  localTitle.value = v.title || ''
  localContent.value = v.content || ''
  localTags.value = [...(v.tags || [])]
  // 外部换了内容（比如切了别的笔记）→ 高度要重算
  nextTick(autoGrow)
}, { deep: true })

function emitChange() {
  emit('update:modelValue', {
    title: localTitle.value,
    content: localContent.value,
    tags: [...localTags.value],
  })
  emit('change')
}

// 标题、标签、正文都走「先改本地值、再同步给父组件」：
// 直接用 v-model + @input 的组合时，两个处理器的执行顺序不够直观，
// 容易出现「父组件拿到的是上一次的旧值」。
function onTitleInput(e) {
  localTitle.value = e.target.value
  emitChange()
}

function onTagsChange(tags) {
  localTags.value = tags
  emitChange()
}

function focusBody() {
  nextTick(() => bodyRef.value?.focus())
}

function addInlineTag(t) {
  if (localTags.value.some(x => x.toLowerCase() === t.toLowerCase())) return
  localTags.value = [...localTags.value, t]
  emitChange()
}

// ============ 双键键位 ============
function onKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    // 阻止继续冒泡：避免页面级快捷键再处理一次（比如重复保存）
    e.stopPropagation()
    emit('save')
    return
  }
  if (e.key === 'Escape') {
    // 先关候选，再取消编辑 —— 否则按一次 Esc 会把候选和编辑一起关掉
    if (suggestVisible.value) {
      suggestVisible.value = false
      e.stopPropagation()
      return
    }
    e.preventDefault()
    e.stopPropagation()
    emit('cancel')
  }
}

function onBodyKeydown(e) {
  if (e.key === 'Enter' && suggestVisible.value) {
    e.preventDefault()
    if (suggestions.value.length) applySuggestion(suggestions.value[0].title)
    else applySuggestion(suggestQuery.value)
  }
}

// ============ 双链候选 ============
let noteTypePromise = null
function getNoteTypeId() {
  // 类型 id 不会变，缓存一次，省得每敲一个字符都问后端
  if (!noteTypePromise) {
    noteTypePromise = Api.getEntityTypeByKey('note').then(t => t.id).catch(() => null)
  }
  return noteTypePromise
}

async function loadTitleIndex() {
  const typeId = await getNoteTypeId()
  if (!typeId) return
  try {
    const res = await Api.listRecords(typeId, { page: 1, page_size: 200 })
    titleIndex.value = (res.items || [])
      .map(r => r.data?.title)
      .filter(Boolean)
  } catch (e) {
    titleIndex.value = []
  }
}

function onBodyInput(e) {
  localContent.value = e.target.value
  emitChange()
  // 内容变了 → 编辑区高度要跟着变
  autoGrow()
  const ta = bodyRef.value
  if (!ta) return
  const pos = ta.selectionStart
  const text = localContent.value.slice(0, pos)
  const m = /\[\[([^\[\]\n]*)$/.exec(text)
  if (!m) {
    suggestVisible.value = false
    return
  }
  suggestStart.value = pos - m[1].length - 2
  suggestQuery.value = m[1]
  const q = m[1].toLowerCase()
  const hit = titleIndex.value
    .filter(t => !q || t.toLowerCase().includes(q))
    .slice(0, 8)
    .map(title => ({ title, exists: true }))
  const exact = q && !titleIndex.value.some(t => t.toLowerCase() === q)
  suggestions.value = exact
    ? [...hit, { title: m[1], exists: false }]
    : hit
  suggestVisible.value = true
}

function applySuggestion(title) {
  const ta = bodyRef.value
  if (!ta || !title) return
  const pos = ta.selectionStart
  const before = localContent.value.slice(0, suggestStart.value)
  const after = localContent.value.slice(pos)
  const insertion = `${title}]]`
  localContent.value = before + insertion + after
  suggestVisible.value = false
  nextTick(() => {
    const newPos = before.length + insertion.length
    ta.setSelectionRange(newPos, newPos)
    ta.focus()
    emitChange()
  })
}

function escapeHtml(s) {
  return (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

onMounted(async () => {
  await loadTitleIndex()
  // 初始高度按内容算（长笔记一打开就是够高的，不用先滚动才知道下面还有）
  nextTick(autoGrow)
  // 打开即聚焦标题：Obsidian 的「随手记」手感全靠这一点
  if (props.mode === 'quick') nextTick(() => titleRef.value?.focus())
})
</script>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px 10px;
  background: var(--bg-card);
  border: 1px solid var(--primary-ring);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow);
}

/* 标题行 */
.composer-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.composer-icon {
  color: var(--primary);
  flex-shrink: 0;
}
.composer-title {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.3px;
  padding: 2px 0;
}
.composer-title::placeholder { color: var(--text-disabled); font-weight: 500; }
.composer-mode-hint {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* 标签行 */
.composer-tags {
  padding-left: 2px;
}

/* 正文 */
/* 编辑区高度由 JS 按内容算（autoGrow）——
   写死 180px 的话长笔记全挤在里面要滚动，
   而下面还压着同样高度的高亮层，两层各滚各的，看着就像「滑动没反应」。 */
.composer-body {
  position: relative;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  min-height: 180px;
  height: var(--composer-body-h, 180px);
  transition: height var(--duration-fast) var(--ease-out);
}
.composer-full .composer-body { min-height: 420px; height: var(--composer-body-h, 420px); }

.composer-switch {
  position: absolute;
  top: 6px;
  right: 8px;
  z-index: 5;
  display: flex;
  gap: 2px;
  padding: 2px;
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
}
.composer-switch-btn {
  border: none;
  background: transparent;
  padding: 2px 10px;
  border-radius: 3px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  cursor: pointer;
}
.composer-switch-btn.is-on {
  background: var(--bg-card);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
}

.composer-editor-wrap {
  position: relative;
  height: 100%;
  min-height: inherit;
  /* 高度跟着 .composer-body 走 */
}
.composer-editor,
.composer-overlay {
  position: absolute;
  inset: 0;
  margin: 0;
  padding: 12px 14px;
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
  border: none;
  outline: none;
  box-sizing: border-box;
}
.composer-editor {
  z-index: 2;
  background: transparent;
  color: transparent;
  caret-color: var(--text-primary);
  resize: none;
}
.composer-overlay {
  z-index: 1;
  color: var(--text-primary);
  pointer-events: none;
}
.composer-overlay :deep(.composer-wikilink) {
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: 3px;
  padding: 0 3px;
}

/* ============ 编辑器行内高亮 ============
   覆盖层与 textarea 逐字对齐，所以这些 span **只能改颜色/背景**，
   绝不能改字号、行高、内外边距 —— 改了就错行、光标会飘。
   （之前只高亮 [[双链]]，写代码块时看着就是普通文字，
     「编辑器没识别代码」就是这么来的）

   ⚠️ 必须用 :deep()：覆盖层的内容来自 v-html，
   v-html 渲染出来的节点**没有 scoped 属性**，
   不加 :deep() 的话这些样式一条都落不上（实测背景是透明的、
   字体也不是等宽）。 */

:deep(.ed-h) { color: var(--text-primary); font-weight: 700; }

:deep(.ed-fence) { color: var(--primary-dark); font-weight: 600; }
:deep(.ed-lang) { color: var(--text-tertiary); font-weight: 500; font-size: 0.9em; margin-left: 4px; }
html.dark :deep(.ed-fence) { color: var(--primary-light); }

/* 代码块正文：等宽 + 浅底，整行一眼看出「这是代码」 */
:deep(.ed-code-line) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

:deep(.ed-inline-code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--bg-subtle);
  color: var(--primary-dark);
  border-radius: 3px;
  padding: 0 3px;
}
html.dark :deep(.ed-inline-code) { color: var(--primary-light); }

:deep(.ed-em) { font-weight: 650; color: var(--text-primary); }
:deep(.ed-wikilink) {
  color: var(--primary);
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
}
:deep(.ed-link) { color: var(--info); text-decoration: underline; }

:deep(.ed-task) { color: var(--text-tertiary); }
:deep(.ed-task.is-done) { color: var(--success); }

:deep(.ed-bullet) { color: var(--text-tertiary); }

:deep(.ed-callout-tag) { color: var(--primary-dark); font-weight: 650; }
html.dark :deep(.ed-callout-tag) { color: var(--primary-light); }

.composer-preview {
  padding: 12px 16px;
  max-height: 620px;
  overflow-y: auto;
}
.composer-preview-empty {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

/* 双链候选 */
.composer-suggest {
  position: absolute;
  top: 26px;
  left: 14px;
  z-index: 30;
  min-width: 200px;
  max-width: 320px;
  max-height: 220px;
  overflow-y: auto;
  padding: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-lg);
}
.composer-suggest-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  border: none;
  background: transparent;
  padding: 5px 8px;
  border-radius: var(--radius-xs);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}
.composer-suggest-item:hover { background: var(--primary-bg); color: var(--primary-dark); }
html.dark .composer-suggest-item:hover { color: var(--primary-light); }
.composer-suggest-new {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.composer-suggest-empty {
  padding: 6px 8px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* 正文里的 #标签 */
.composer-inline-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.composer-inline-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.composer-inline-tag {
  border: 1px dashed var(--border-strong);
  background: transparent;
  color: var(--text-secondary);
  border-radius: var(--radius-xs);
  padding: 1px 7px;
  font-size: var(--text-xs);
  cursor: pointer;
}
.composer-inline-tag:hover {
  border-style: solid;
  border-color: var(--primary);
  color: var(--primary-dark);
}

/* 底部 */
.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.composer-hint {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.composer-hint kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 16px;
  min-width: 16px;
  text-align: center;
  padding: 0 4px;
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}
.composer-hint-sep { margin: 0 4px; }
.composer-actions { display: flex; align-items: center; gap: 4px; }

.composer-full {
  border: none;
  box-shadow: none;
  padding: 0;
  background: transparent;
}
.composer-full .composer-title { font-size: 26px; }
</style>
