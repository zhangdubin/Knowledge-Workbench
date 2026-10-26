<template>
  <div class="notes-page">
    <!-- 页头：紧凑，不再用大图标砖（Obsidian 的文件列表是克制的） -->
    <div class="notes-head">
      <div class="notes-head-main">
        <h2 class="notes-head-title">知识库</h2>
        <span class="notes-head-count">
          {{ filterHint || `共 ${data.total || 0} 条笔记` }}
        </span>
      </div>
      <div class="notes-head-actions">
        <el-button text size="small" @click="$router.push('/knowledge/graph')">
          <el-icon><DataAnalysis /></el-icon>知识图谱
        </el-button>
        <el-button type="primary" size="small" @click="openCreate">
          <el-icon><Plus /></el-icon>新建笔记
          <kbd class="notes-kbd">⌘N</kbd>
        </el-button>
      </div>
    </div>

    <!-- 工具栏：搜索 + 视图 -->
    <div class="notes-toolbar">
      <div class="notes-search">
        <el-icon class="notes-search-icon"><Search /></el-icon>
        <input
          ref="searchRef"
          v-model="keyword"
          class="notes-search-input"
          type="search"
          placeholder="搜索标题与正文…"
          aria-label="搜索笔记"
          @input="onSearchInput"
          @keydown.enter="load(1)"
          @keydown.down.prevent="moveCursor(1)"
          @keydown.up.prevent="moveCursor(-1)"
        />
        <kbd v-if="!keyword" class="notes-search-kbd">/</kbd>
      </div>
      <div class="notes-toolbar-right">
        <el-segmented
          v-model="viewMode"
          size="small"
          :options="[
            { label: '列表', value: 'list' },
            { label: '网格', value: 'grid' },
          ]"
        />
      </div>
    </div>

    <!-- 标签筛选：chips，点击即筛 -->
    <div v-if="allTags.length" class="notes-tagbar">
      <button
        class="notes-tagchip is-all"
        :class="{ 'is-on': !tagFilter }"
        type="button"
        @click="setTagFilter('')"
      >全部</button>
      <button
        v-for="t in allTags"
        :key="t"
        class="notes-tagchip"
        :class="{ 'is-on': tagFilter === t }"
        type="button"
        @click="setTagFilter(t)"
      >#{{ t }}</button>
    </div>

    <!-- 内联快速新建：不是弹窗，标题栏直接能打字 -->
    <NoteEditor
      v-if="creating"
      v-model="draft"
      mode="quick"
      class="notes-composer"
      :tag-suggestions="allTags"
      @save="createNote"
      @cancel="creating = false"
    />

    <!-- 列表：主界面 -->
    <ul
      v-if="visibleItems.length"
      ref="listRef"
      class="notes-list"
      :class="{ 'is-grid': viewMode === 'grid' }"
      role="listbox"
      aria-label="笔记列表"
      tabindex="-1"
    >
      <li
        v-for="(n, idx) in visibleItems"
        :key="n.id"
        class="note-row"
        :class="{ 'is-active': idx === cursor }"
        role="option"
        :aria-selected="idx === cursor"
        tabindex="-1"
        @click="openNote(n.id)"
        @mouseenter="cursor = idx"
      >
        <span class="note-row-icon"><el-icon><Document /></el-icon></span>
        <div class="note-row-body">
          <div class="note-row-top">
            <span class="note-row-title">{{ titleOf(n) }}</span>
            <span v-if="!n.data?.content" class="note-row-empty">空</span>
            <span class="note-row-chips">
              <button
                v-for="t in (n.data?.tags || []).slice(0, 4)"
                :key="t"
                class="note-chip"
                type="button"
                :title="`按 #${t} 筛选`"
                @click.stop="setTagFilter(t)"
              >#{{ t }}</button>
            </span>
          </div>
          <div class="note-row-snippet">{{ snippetOf(n) }}</div>
        </div>
        <div class="note-row-meta">
          <span class="note-row-time" :title="formatTime(n.updated_at)">
            {{ relativeOf(n) }}
          </span>
          <button
            class="note-row-del"
            type="button"
            :aria-label="`删除笔记 ${titleOf(n)}`"
            title="删除"
            @click.stop="confirmDelete(n)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </div>
      </li>
    </ul>

    <!-- 空状态 -->
    <div v-if="!visibleItems.length && !loading" class="notes-empty">
      <div class="notes-empty-icon"><el-icon :size="26"><Document /></el-icon></div>
      <div class="notes-empty-title">
        {{ keyword || tagFilter ? '没有匹配的笔记' : '还没有笔记' }}
      </div>
      <div class="notes-empty-desc">
        {{ keyword || tagFilter
          ? '换个关键词，或清掉标签筛选再看看。'
          : '随手记一条：用 [[双链]] 把想法串起来，所有笔记都能被检索和图谱找到。' }}
      </div>
      <div v-if="!keyword && !tagFilter" class="notes-empty-actions">
        <el-button type="primary" size="small" @click="openCreate">
          <el-icon><Plus /></el-icon>新建笔记
        </el-button>
      </div>
    </div>

    <!-- 分页：按标签筛选时是全量过滤，不再分页 -->
    <el-pagination
      v-if="visibleItems.length && !tagFilter"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="data.total || 0"
      layout="total, prev, pager, next, jumper"
      @current-change="load()"
      @size-change="load(1)"
      class="notes-pager"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Delete, Document, Plus, Search } from '@element-plus/icons-vue'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { firstLineTitle, noteSnippet, noteTitle, relativeTime } from '../utils/notes'
import NoteEditor from '../components/NoteEditor.vue'

const router = useRouter()
const route = useRoute()
const noteTypeId = ref(null)
const data = ref({ items: [], total: 0 })
const keyword = ref('')
const tagFilter = ref('')
const allTags = ref([])
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const viewMode = ref('list')

// 内联快速新建
const creating = ref(false)
const draft = ref({ title: '', content: '', tags: [] })

// 键盘游标（选中项）
const cursor = ref(-1)
const listRef = ref(null)
const searchRef = ref(null)

let searchTimer = null

// 标签筛选是前端过滤（后端列表接口没有 tag 参数），
// 所以选中标签时一次性把笔记全部拉下来再筛，否则只会筛到当前页。
const filtered = computed(() => {
  if (!tagFilter.value) return data.value.items || []
  const key = tagFilter.value.toLowerCase()
  return (data.value.items || []).filter(n =>
    (n.data?.tags || []).some(t => String(t).toLowerCase() === key)
  )
})
const visibleItems = computed(() => filtered.value)

const filterHint = computed(() => {
  if (!tagFilter.value) return ''
  return `共 ${data.value.total || 0} 条 · 筛选 #${tagFilter.value}（${filtered.value.length}）`
})

function titleOf(n) {
  return noteTitle(n, n?.id)
}

function snippetOf(n) {
  return noteSnippet(n?.data?.content || '', 160) || '（空笔记）'
}

function relativeOf(n) {
  return relativeTime(n?.updated_at)
}

async function load(p) {
  if (!noteTypeId.value) return
  if (p) page.value = p
  loading.value = true
  try {
    const filtering = !!tagFilter.value
    data.value = await Api.listRecords(noteTypeId.value, {
      page: filtering ? 1 : page.value,
      page_size: filtering ? 500 : pageSize.value,
      keyword: keyword.value,
    })
    const tags = new Set()
    for (const n of (data.value.items || [])) {
      for (const t of (n.data?.tags || [])) {
        if (t) tags.add(t)
      }
    }
    allTags.value = [...tags].sort((a, b) => a.localeCompare(b, 'zh'))
    // 游标保持在合法范围内
    if (cursor.value >= visibleItems.value.length) cursor.value = visibleItems.value.length - 1
  } finally {
    loading.value = false
  }
}

function onSearchInput() {
  // 搜索框与列表联动：输入即筛（防抖，别每敲一个字都打后端）
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(1), 250)
}

function setTagFilter(t) {
  tagFilter.value = tagFilter.value === t ? '' : t
  cursor.value = -1
  load(1)
}

function openNote(id) {
  router.push(`/notes/${id}`)
}

function openCreate() {
  draft.value = { title: '', content: '', tags: [] }
  creating.value = true
}

async function createNote() {
  const content = draft.value.content || ''
  // Obsidian 行为：没起标题就用正文首行当标题；都空了就先建空笔记（先建后填）
  const title = (draft.value.title || '').trim() || firstLineTitle(content)
  try {
    const r = await Api.createRecord(noteTypeId.value, {
      title,
      content,
      tags: draft.value.tags,
    })
    if (content) {
      await Api.syncNoteLinks(r.id, content)
    }
    ElMessage.success('已创建')
    creating.value = false
    // 新建完直接进详情页继续写（Obsidian 的「新建文件 → 光标已在正文里」）
    router.push(`/notes/${r.id}`)
  } catch (e) {
    ElMessage.error('创建失败：' + (e?.message || e))
  }
}

async function confirmDelete(note) {
  try {
    await ElMessageBox.confirm(
      `确定删除笔记「${titleOf(note)}」？反向链接和正链都会被解除。`,
      '删除笔记',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await Api.deleteRecord(note.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e === 'cancel' || e?.code === 'cancel' || e?.message === 'cancel') return
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

// ============ 键盘优先（Obsidian 的手感）============
function moveCursor(delta) {
  const total = visibleItems.value.length
  if (!total) return
  let next = cursor.value + delta
  if (cursor.value < 0) next = delta > 0 ? 0 : total - 1
  cursor.value = Math.min(Math.max(next, 0), total - 1)
  // 选中项滚进视野
  nextTick(() => {
    const el = listRef.value?.querySelector('.note-row.is-active')
    el?.scrollIntoView({ block: 'nearest' })
  })
}

function onKeydown(e) {
  const el = e.target
  const tag = el?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable
  const inSearch = el === searchRef.value
  const inComposer = !!el?.closest?.('.notes-composer')

  // ⌘/Ctrl + N —— 新建笔记
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault()
    openCreate()
    return
  }
  // 快速新建开着时，Esc 一律取消（焦点在编辑器内由编辑器自己处理，这里是兜底）
  if (e.key === 'Escape' && creating.value) {
    // 有弹窗（删除确认等）时不抢 Esc
    if (document.querySelector('.el-overlay, .el-message-box__wrapper')) return
    e.preventDefault()
    creating.value = false
    return
  }
  // 编辑器内部的按键不参与列表导航
  if (inComposer) return
  // / —— 聚焦搜索（Obsidian 的老习惯）
  if (e.key === '/' && !typing) {
    e.preventDefault()
    searchRef.value?.focus()
    return
  }
  if (typing && !inSearch) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveCursor(1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveCursor(-1)
    return
  }
  if (e.key === 'Enter' && cursor.value >= 0 && visibleItems.value[cursor.value]) {
    e.preventDefault()
    openNote(visibleItems.value[cursor.value].id)
  }
}

// nextTick 需要显式引入（Vue 3 里它是自动导入的编译宏，但显式更清楚）

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  const et = await Api.getEntityTypeByKey('note')
  noteTypeId.value = et.id
  // 详情页点标签跳回来时带着 ?tag=xxx，直接接上筛选
  const qTag = route.query.tag
  if (qTag) tagFilter.value = String(qTag)
  await load(1)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  clearTimeout(searchTimer)
})
</script>

<style scoped>
.notes-page {
  padding: var(--space-6) var(--space-8);
  max-width: 1180px;
  margin: 0 auto;
}

/* 页头 */
.notes-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}
.notes-head-main {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  min-width: 0;
}
.notes-head-title {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: 650;
  letter-spacing: -0.5px;
  font-family: var(--font-display);
  color: var(--text-primary);
}
.notes-head-count {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.notes-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.notes-kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 15px;
  padding: 0 4px;
  margin-left: 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

/* 工具栏 */
.notes-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.notes-search {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  max-width: 420px;
  height: 32px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-card);
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast);
}
.notes-search:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-ring);
}
.notes-search-icon { color: var(--text-tertiary); }
.notes-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.notes-search-input::-webkit-search-cancel-button { cursor: pointer; }
.notes-search-kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 16px;
  padding: 0 5px;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-tertiary);
  background: var(--bg-subtle);
}
.notes-toolbar-right { margin-left: auto; }

/* 标签筛选条 */
.notes-tagbar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}
.notes-tagchip {
  border: 1px solid var(--border-light);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  border-radius: var(--radius-full);
  padding: 2px 10px;
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.notes-tagchip:hover {
  border-color: var(--primary-light);
  color: var(--primary-dark);
}
html.dark .notes-tagchip:hover { color: var(--primary-light); }
.notes-tagchip.is-on {
  background: var(--primary-bg);
  border-color: var(--primary-light);
  color: var(--primary-dark);
  font-weight: 600;
}
html.dark .notes-tagchip.is-on { color: var(--primary-light); }
.notes-tagchip.is-all { color: var(--text-tertiary); }

/* 快速新建 */
.notes-composer {
  margin-bottom: var(--space-3);
}

/* 列表 */
.notes-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  overflow: hidden;
}
.notes-list:focus { outline: none; }

.note-row {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 12px 10px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.note-row:last-child { border-bottom: none; }
.note-row:hover { background: var(--bg-subtle); }
.note-row.is-active {
  background: var(--primary-bg);
}
.note-row.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--primary);
}

.note-row-icon {
  color: var(--text-tertiary);
  margin-top: 2px;
  flex-shrink: 0;
  transition: color var(--duration-fast);
}
.note-row:hover .note-row-icon,
.note-row.is-active .note-row-icon { color: var(--primary); }

.note-row-body {
  flex: 1;
  min-width: 0;
}
.note-row-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.note-row-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}
.note-row-empty {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-disabled);
  border: 1px solid var(--border-light);
  border-radius: 3px;
  padding: 0 4px;
}
.note-row-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
}
.note-chip {
  border: none;
  background: var(--primary-bg);
  color: var(--primary-dark);
  border-radius: var(--radius-xs);
  padding: 1px 6px;
  font-size: var(--text-xs);
  line-height: 1.5;
  cursor: pointer;
  white-space: nowrap;
}
html.dark .note-chip { color: var(--primary-light); }
.note-chip:hover { background: var(--primary-bg-strong); }

.note-row-snippet {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-row-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-top: 1px;
}
.note-row-time {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.note-row-del {
  border: none;
  background: transparent;
  color: var(--text-disabled);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  opacity: 0;
  transition: opacity var(--duration-fast), color var(--duration-fast);
}
.note-row:hover .note-row-del,
.note-row.is-active .note-row-del { opacity: 1; }
.note-row-del:hover { color: var(--danger); background: var(--danger-bg); }

/* 网格视图 */
.notes-list.is-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(258px, 1fr));
  gap: 1px;
  background: var(--border-light);
}
.notes-list.is-grid .note-row {
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  background: var(--bg-card);
  border-bottom: none;
}
.notes-list.is-grid .note-row.is-active { background: var(--primary-bg); }
.notes-list.is-grid .note-row-top { flex-wrap: wrap; gap: 4px 8px; }
.notes-list.is-grid .note-row-title { max-width: 100%; white-space: normal; }
.notes-list.is-grid .note-row-snippet {
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  min-height: 3em;
}
.notes-list.is-grid .note-row-meta { width: 100%; justify-content: space-between; }

/* 空状态 */
.notes-empty {
  padding: 48px 20px;
  text-align: center;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
}
.notes-empty-icon {
  color: var(--text-disabled);
  margin-bottom: 10px;
}
.notes-empty-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.notes-empty-desc {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  line-height: 1.7;
  max-width: 420px;
  margin: 0 auto;
}
.notes-empty-actions { margin-top: 14px; }

.notes-pager {
  margin-top: var(--space-4);
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .notes-page { padding: var(--space-4); }
  .notes-toolbar { flex-wrap: wrap; }
  .notes-search { max-width: none; }
}
</style>
