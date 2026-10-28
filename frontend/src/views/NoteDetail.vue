<template>
  <div class="note-detail">
    <!-- 顶部操作条 -->
    <div class="nd-topbar">
      <button class="nd-back" type="button" @click="$router.push('/notes')">
        <el-icon><ArrowLeft /></el-icon>知识库
      </button>
      <div class="nd-topbar-actions">
        <template v-if="editing">
          <span class="nd-hint"><kbd>⌘</kbd><kbd>↵</kbd> 保存 · <kbd>Esc</kbd> 取消</span>
          <el-button size="small" text @click="cancelEdit">取消</el-button>
          <el-button size="small" type="primary" @click="save">
            <el-icon><Check /></el-icon>保存
          </el-button>
        </template>
        <template v-else>
          <el-button size="small" @click="startEdit">
            <el-icon><Edit /></el-icon>编辑
          </el-button>
          <el-button size="small" text @click="goGraph">
            <el-icon><Share /></el-icon>图谱
          </el-button>
          <el-dropdown trigger="click" @command="openAI">
            <el-button size="small" type="primary" plain>
              <el-icon><MagicStick /></el-icon>AI 辅助
            </el-button>
            <template #dropdown>
              <el-dropdown-item command="summarize">
                <el-icon><Document /></el-icon>生成摘要
              </el-dropdown-item>
              <el-dropdown-item command="tags">
                <el-icon><PriceTag /></el-icon>提取标签
              </el-dropdown-item>
              <el-dropdown-item command="rewrite">
                <el-icon><EditPen /></el-icon>改写润色
              </el-dropdown-item>
              <el-dropdown-item command="title">
                <el-icon><EditPen /></el-icon>生成标题
              </el-dropdown-item>
            </template>
          </el-dropdown>
          <el-popconfirm
            title="确定删除这篇笔记？反向链接和正链都会被解除。"
            confirm-button-text="删除"
            cancel-button-text="取消"
            @confirm="deleteNote"
          >
            <template #reference>
              <el-button size="small" type="danger" plain>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </div>
    </div>

    <div v-if="record" class="nd-layout">
      <!-- 主区 -->
      <main class="nd-main">
        <!-- 标题 + 标签 + 元信息（阅读态的页头） -->
        <header v-if="!editing" class="nd-header">
          <h1 class="nd-title">{{ title }}</h1>
          <div class="nd-tags">
            <button
              v-for="t in tags"
              :key="t"
              class="nd-tag"
              type="button"
              :title="`在知识库里按 #${t} 筛选`"
              @click="goNotesByTag(t)"
            >#{{ t }}</button>
            <span v-if="!tags.length" class="nd-muted">（无标签）</span>
          </div>
          <!-- 所属分组：下拉直接改，改完立刻落库 -->
          <div v-if="groupsAvailable" class="nd-group-row">
            <span
              class="nd-group-dot"
              :style="{ backgroundColor: groupColor }"
              aria-hidden="true"
            ></span>
            <NoteGroupSelect
              class="nd-group-select"
              :model-value="noteGroupId"
              :groups="groups"
              aria-label="变更笔记所属分组"
              @change="changeGroup"
            />
          </div>
          <div class="nd-meta-line">
            <span>更新于 {{ relativeOf('updated_at') }}</span>
            <span class="nd-dot">·</span>
            <span>{{ contentLength }} 字</span>
            <span class="nd-dot">·</span>
            <span>{{ outgoing.length }} 正链 / {{ backlinks.length }} 反链</span>
          </div>
        </header>

        <!-- 正文 -->
        <section class="nd-panel">
          <!-- 阅读态视图切换（Obsidian 的 阅读 / 源码） -->
          <div v-if="!editing" class="nd-switch" role="tablist" aria-label="正文视图">
            <button
              type="button" role="tab" class="nd-switch-btn"
              :class="{ 'is-on': view === 'reading' }" :aria-selected="view === 'reading'"
              @click="view = 'reading'"
            >阅读</button>
            <button
              type="button" role="tab" class="nd-switch-btn"
              :class="{ 'is-on': view === 'source' }" :aria-selected="view === 'source'"
              @click="view = 'source'"
            >源码</button>
            <button
              type="button" role="tab" class="nd-switch-btn"
              :class="{ 'is-on': view === 'json' }" :aria-selected="view === 'json'"
              @click="view = 'json'"
            >JSON</button>
          </div>

          <!-- 编辑态：整页编辑，标题行内可改 -->
          <div v-if="editing" class="nd-editor">
            <NoteEditor
              v-model="formData"
              mode="full"
              :tag-suggestions="tagSuggestions"
              @save="save"
              @cancel="cancelEdit"
            />
          </div>

          <!-- 阅读态 -->
          <div v-else-if="view === 'reading'" ref="readingRef" class="nd-reading" @click="onBodyClick">
            <div v-if="record.data.parent" class="nd-parent">
              <el-icon><Top /></el-icon>
              父笔记：
              <a class="nd-link" @click="goToNote(record.data.parent)">{{ parentTitle }}</a>
            </div>
            <div v-if="record.data.content" class="note-body md-body md-body-doc" v-html="renderedContent"></div>
            <div v-else class="nd-muted nd-empty">（空笔记）</div>
          </div>

          <!-- 源码态 -->
          <pre v-else-if="view === 'source'" class="nd-source">{{ record.data.content || '（空）' }}</pre>

          <!-- JSON 态 -->
          <div v-else class="nd-json">
            <div class="nd-json-meta">
              <el-radio-group v-model="jsonScope" size="small">
                <el-radio-button value="record">记录数据</el-radio-button>
                <el-radio-button value="content">正文</el-radio-button>
              </el-radio-group>
              <span class="nd-json-tip">
                <el-icon><InfoFilled /></el-icon>
                {{ jsonScope === 'record'
                  ? '这条记录的完整字段（标题、标签、双链、时间），标准 JSON，可直接复制给 AI'
                  : '正文本身是 JSON 时可直接展开成树；不是 JSON 会提示到具体行列' }}
              </span>
            </div>
            <JsonViewer v-if="jsonScope === 'record'" :value="record.data || {}" />
            <JsonViewer v-else :text="record.data.content || ''" />
          </div>
        </section>

        <!-- 双向链接 -->
        <section class="nd-panel">
          <div class="nd-panel-title">
            <el-icon class="nd-panel-ico"><Connection /></el-icon>双向链接
          </div>
          <el-tabs v-model="linkTab">
            <el-tab-pane name="outgoing">
              <template #label>
                <span class="nd-tab-label">正向链接
                  <span class="badge badge-primary">{{ outgoing.length }}</span>
                </span>
              </template>
              <div v-if="outgoing.length" class="nd-link-list">
                <div v-for="o in outgoing" :key="o.target_record_id" class="nd-link-item">
                  <el-icon class="nd-link-dir"><Right /></el-icon>
                  <a class="nd-link" @click="goToNote(o.target_record_id)">{{ o.title }}</a>
                  <el-tag v-if="o.placeholder" size="small" type="info" effect="plain">占位</el-tag>
                  <span class="nd-link-sub">原文本 [[{{ o.link_title }}]]</span>
                </div>
              </div>
              <div v-else class="nd-empty">
                <div class="nd-empty-title">没有正向链接</div>
                <div class="nd-empty-desc">在内容中用 [[笔记标题]] 即可创建</div>
              </div>
            </el-tab-pane>
            <el-tab-pane name="backlinks">
              <template #label>
                <span class="nd-tab-label">反向链接
                  <span class="badge badge-success">{{ backlinks.length }}</span>
                </span>
              </template>
              <div v-if="backlinks.length" class="nd-link-list">
                <div v-for="b in backlinks" :key="b.source_record_id" class="nd-link-item is-block">
                  <div class="nd-link-head">
                    <el-icon class="nd-link-dir"><Back /></el-icon>
                    <a class="nd-link" @click="goToNote(b.source_record_id)">{{ b.title }}</a>
                    <span class="nd-link-sub">引用了 [[{{ b.link_title }}]]</span>
                  </div>
                  <div class="nd-link-snippet">{{ b.snippet }}</div>
                </div>
              </div>
              <div v-else class="nd-empty">
                <div class="nd-empty-title">还没有其他笔记引用此笔记</div>
                <div class="nd-empty-desc">在其他笔记中用 [[{{ title }}]] 即可建立关联</div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </section>

        <!-- 关联的业务记录 -->
        <section class="nd-panel">
          <div class="nd-panel-title">
            <el-icon class="nd-panel-ico"><Collection /></el-icon>关联的业务记录
            <span v-if="relatedRecords.length" class="badge badge-ghost">{{ relatedRecords.length }}</span>
          </div>
          <div v-if="relatedRecords.length" class="nd-related-list">
            <div
              v-for="r in relatedRecords"
              :key="`${r.entity_type_id}-${r.record_id}`"
              class="nd-related-item"
              @click="goRecord(r)"
            >
              <div class="nd-related-icon">
                <el-icon><component :is="entityIcon(r.entity_type_key)" /></el-icon>
              </div>
              <div class="nd-related-body">
                <div class="nd-related-label">{{ r.label }}</div>
                <div class="nd-related-sub">{{ r.entity_type_name }} · {{ r.relation_name }}</div>
              </div>
              <el-icon class="nd-related-go"><ArrowRight /></el-icon>
            </div>
          </div>
          <div v-else class="nd-empty">
            <div class="nd-empty-title">还没有业务记录引用这条笔记</div>
            <div class="nd-empty-desc">
              在任意记录的详情里点「关联笔记」或「沉淀为笔记」，即可在此双向呈现。
            </div>
          </div>
        </section>
      </main>

      <!-- 侧栏 -->
      <aside class="nd-side">
        <div class="nd-card">
          <div class="nd-panel-title">
            <el-icon class="nd-panel-ico"><DataBoard /></el-icon>元信息
          </div>
          <div class="nd-meta-list">
            <div class="nd-meta-row">
              <span class="nd-meta-label">ID</span>
              <span class="nd-meta-value">#{{ record.id }}</span>
            </div>
            <div class="nd-meta-row">
              <span class="nd-meta-label">标签</span>
              <span class="nd-meta-value">
                <template v-if="tags.length">
                  <span v-for="t in tags" :key="t" class="nd-tag is-mini">#{{ t }}</span>
                </template>
                <span v-else class="nd-muted">—</span>
              </span>
            </div>
            <div v-if="groupsAvailable" class="nd-meta-row">
              <span class="nd-meta-label">分组</span>
              <span class="nd-meta-value">
                <NoteGroupBadge
                  :name="groupName"
                  :color="groupColor"
                  :muted="!noteGroupId"
                />
              </span>
            </div>
            <div class="nd-meta-row">
              <span class="nd-meta-label">正链 / 反链</span>
              <span class="nd-meta-value">{{ outgoing.length }} / {{ backlinks.length }}</span>
            </div>
            <div class="nd-meta-row">
              <span class="nd-meta-label">字数</span>
              <span class="nd-meta-value is-num">{{ contentLength }}</span>
            </div>
            <div class="nd-meta-row">
              <span class="nd-meta-label">JSON 节点</span>
              <span class="nd-meta-value is-num">{{ jsonSummary.nodeCount || 0 }}</span>
            </div>
            <div class="nd-meta-row">
              <span class="nd-meta-label">创建</span>
              <span class="nd-meta-value">{{ formatTime(record.created_at) }}</span>
            </div>
            <div class="nd-meta-row">
              <span class="nd-meta-label">更新</span>
              <span class="nd-meta-value">{{ formatTime(record.updated_at) }}</span>
            </div>
          </div>
        </div>

        <div v-if="record.data.parent" class="nd-card">
          <div class="nd-panel-title">
            <el-icon class="nd-panel-ico"><FolderOpened /></el-icon>所在层级
          </div>
          <a class="nd-parent-card" @click="goToNote(record.data.parent)">
            <el-icon><Notebook /></el-icon>
            <span>{{ parentTitle }}</span>
          </a>
        </div>
      </aside>
    </div>

    <div v-else class="nd-loading">
      <el-icon :size="24"><Loading /></el-icon>
      <span>加载中…</span>
    </div>

    <!-- AI 助手弹窗 -->
    <AIAssistantDialog
      v-model="aiDialogOpen"
      :task="aiTask"
      :source-text="record?.data?.content || ''"
      @apply="applyAI"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, ArrowRight, Back, Check, Collection, Connection, DataBoard,
  Document, Edit, EditPen, FolderOpened, InfoFilled, Loading, MagicStick, Notebook,
  PriceTag, Right, Share, Top,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { entityIcon } from '../utils/icons'
import { parseJson, summarize } from '../utils/jsonview'
import { noteTitle, relativeTime, renderNoteHtml } from '../utils/notes'
import NoteEditor from '../components/NoteEditor.vue'
import JsonViewer from '../components/JsonViewer.vue'
import AIAssistantDialog from '../components/AIAssistantDialog.vue'
import NoteGroupSelect from '../components/note/NoteGroupSelect.vue'
import NoteGroupBadge from '../components/note/NoteGroupBadge.vue'
import { useNoteGroups } from '../components/note/useNoteGroups'

const route = useRoute()
const router = useRouter()
const noteId = computed(() => Number(route.params.id))

const record = ref(null)
const editing = ref(false)
const formData = ref({ title: '', content: '', tags: [] })
const originalContent = ref('')
const outgoing = ref([])
const backlinks = ref([])
const parentTitle = ref('')
const relatedRecords = ref([])

// 阅读态的视图切换：阅读 / 源码 / JSON
const view = ref('reading')
const linkTab = ref('outgoing')
const jsonScope = ref('record')

// 标签候选（给编辑器的 chips 输入器用）
const tagSuggestions = ref([])
// 标题 → 记录 id 的索引：正文里的 [[双链]] 点击后要能跳过去
const titleIndex = ref({})
const readingRef = ref(null)

const contentLength = computed(() => (record.value?.data?.content || '').length)
const title = computed(() => noteTitle(record.value, noteId.value))
const tags = computed(() => record.value?.data?.tags || [])

// 分组（接口没上线时 groupsAvailable=false，分组相关的 UI 全部隐藏）
const { groups, available: groupsAvailable, load: loadGroups, groupOf } = useNoteGroups()
const noteGroupId = computed(() => {
  const raw = Number(record.value?.data?.group_id || 0)
  if (!raw) return 0
  // 分组被删了（还留着一个野归属）→ 当未分组处理
  return groupOf(raw) ? raw : 0
})
const groupName = computed(() => {
  const id = noteGroupId.value
  if (!id) return '未分组'
  return groupOf(id)?.name || '未分组'
})
const groupColor = computed(() => {
  const id = noteGroupId.value
  return id ? (groupOf(id)?.color || '') : ''
})

const jsonSummary = computed(() => {
  const empty = { textLength: 0, nodeCount: 0, maxDepth: 0, directChildren: 0 }
  if (!record.value) return empty
  if (jsonScope.value === 'record') return summarize(record.value.data || {})
  const r = parseJson(record.value.data.content || '')
  return r.ok ? summarize(r.value) : empty
})

const renderedContent = computed(() => renderNoteHtml(record.value?.data?.content || ''))

function relativeOf(field) {
  return relativeTime(record.value?.[field])
}

async function load() {
  record.value = await Api.getRecord(noteId.value)
  outgoing.value = await Api.getNoteOutgoing(noteId.value)
  backlinks.value = await Api.getNoteBacklinks(noteId.value)
  await loadRelatedRecords()
  if (record.value?.data?.parent) {
    try {
      const p = await Api.getRecord(record.value.data.parent)
      parentTitle.value = p?.data?.title || `#${record.value.data.parent}`
    } catch {
      parentTitle.value = `#${record.value.data.parent}`
    }
  }
  await loadTitleIndex()
}

/** 换分组：立刻落库（分组和正文是两回事，不必进编辑态） */
async function changeGroup(id) {
  const next = Number(id) || null
  if ((next || 0) === noteGroupId.value) return
  try {
    // update 是整份 data 覆盖，所以先把原字段带上（parent / tags 等不能丢）。
    // group_id: null = 移出分组（未分组）。
    await Api.updateRecord(noteId.value, {
      ...(record.value?.data || {}),
      group_id: next,
    })
    ElMessage.success(`已移到「${next ? (groupOf(next)?.name || '未分组') : '未分组'}」`)
    // 分组计数会变 → 顺手刷新一次（侧栏下次进来也会自己刷）
    loadGroups(true)
    await load()
  } catch (e) {
    ElMessage.error('变更分组失败：' + (e?.message || e))
  }
}

// 关联的业务记录（由业务侧「关联知识 / 沉淀为笔记」反向而来）
async function loadRelatedRecords() {
  try {
    const r = await Api.getNoteRecords(noteId.value)
    relatedRecords.value = r.records || []
  } catch (e) {
    relatedRecords.value = []
  }
}

// 一次性拉全量笔记，建「标题 → id」索引：
// 正文里的 [[双链]] 要能真的跳过去（旧实现指向一个根本不存在的路由）。
async function loadTitleIndex() {
  try {
    const et = await Api.getEntityTypeByKey('note')
    const res = await Api.listRecords(et.id, { page: 1, page_size: 500 })
    const map = {}
    const tagSet = new Set()
    for (const n of (res.items || [])) {
      const t = (n.data?.title || '').trim()
      if (t && !map[t.toLowerCase()]) map[t.toLowerCase()] = n.id
      for (const tag of (n.data?.tags || [])) if (tag) tagSet.add(tag)
    }
    titleIndex.value = map
    tagSuggestions.value = [...tagSet].sort((a, b) => a.localeCompare(b, 'zh'))
  } catch (e) {
    titleIndex.value = {}
  }
}

function goRecord(rec) {
  router.push(`/records/${rec.entity_type_id}?id=${rec.record_id}`)
}

function startEdit() {
  formData.value = {
    title: record.value.data.title || '',
    content: record.value.data.content || '',
    tags: [...(record.value.data.tags || [])],
    parent: record.value.data.parent,
  }
  originalContent.value = formData.value.content
  editing.value = true
}

function cancelEdit() {
  editing.value = false
}

async function save() {
  try {
    // update 是整份 data 覆盖，所以先把原字段带上（parent 等不能丢）
    await Api.updateRecord(noteId.value, {
      ...(record.value?.data || {}),
      title: formData.value.title,
      content: formData.value.content,
      tags: formData.value.tags,
    })
    if (formData.value.content !== originalContent.value) {
      await Api.syncNoteLinks(noteId.value, formData.value.content)
    }
    ElMessage.success('已保存')
    editing.value = false
    await load()
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.message || e))
  }
}

function goToNote(id) {
  router.push(`/notes/${id}`)
}

function goNotesByTag(tag) {
  router.push({ path: '/notes', query: { tag } })
}

function goGraph() {
  router.push(`/graph?record=${noteId.value}`)
}

async function deleteNote() {
  try {
    await Api.deleteRecord(noteId.value)
    ElMessage.success('已删除')
    router.push('/notes')
  } catch (e) {
    ElMessage.error('删除失败：' + (e.message || e))
  }
}

// 点击正文里的 [[双链]] → 跳到对应笔记
function onBodyClick(e) {
  const a = e.target?.closest?.('a.note-wikilink')
  if (!a) return
  e.preventDefault()
  const key = (a.dataset?.wikilink || '').trim().toLowerCase()
  const id = titleIndex.value[key]
  if (id) {
    goToNote(id)
    return
  }
  ElMessage.info(`知识库里还没有「${a.dataset?.wikilink}」这篇笔记`)
}

// 未解析的双链弱化显示（Obsidian 里「还没写过的链接」是灰的）
watch([renderedContent, titleIndex], async () => {
  await nextTick()
  const root = readingRef.value
  if (!root) return
  root.querySelectorAll('a.note-wikilink').forEach(a => {
    const key = (a.dataset?.wikilink || '').trim().toLowerCase()
    a.classList.toggle('is-missing', !titleIndex.value[key])
  })
})

// AI 辅助
const aiDialogOpen = ref(false)
const aiTask = ref('summarize')

function openAI(task) {
  aiTask.value = task
  aiDialogOpen.value = true
}

function applyAI({ task, value, tags }) {
  if (!record.value) return
  if (task === 'summarize') {
    formData.value.content = (formData.value.content || '') + '\n\n## 摘要\n' + value
  } else if (task === 'tags') {
    const existing = formData.value.tags || []
    formData.value.tags = [...new Set([...existing, ...tags])]
  } else if (task === 'rewrite') {
    formData.value.content = value
  } else if (task === 'title') {
    formData.value.title = value
  }
  // 切到编辑模式让用户保存
  editing.value = true
}

// 编辑态的页面级快捷键：焦点不在编辑器里时，⌘↵ 仍然保存、Esc 仍然取消
function onKeydown(e) {
  if (!editing.value) return
  if (e.target?.closest?.('.composer')) return   // 编辑器内部由编辑器自己处理
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    save()
    return
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    cancelEdit()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  // 分组接口可能还没上线：不可用时安静降级（隐藏分组相关 UI）
  await loadGroups(true)
  await load()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

watch(noteId, async () => {
  editing.value = false
  view.value = 'reading'
  await load()
})
</script>

<style scoped>
.note-detail {
  padding: var(--space-6) var(--space-8);
  max-width: 1180px;
  margin: 0 auto;
}

/* 顶部条 */
.nd-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}
.nd-back {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: 3px 6px;
  border-radius: var(--radius-xs);
}
.nd-back:hover { background: var(--bg-subtle); color: var(--text-primary); }
.nd-topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nd-hint {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-right: 2px;
}
.nd-hint kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 15px;
  padding: 0 4px;
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

/* 布局 */
.nd-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: var(--space-5);
  align-items: start;
}
@media (max-width: 1080px) {
  .nd-layout { grid-template-columns: 1fr; }
}

/* 页头 */
.nd-header { margin-bottom: var(--space-4); }
.nd-title {
  margin: 0 0 8px;
  font-size: 27px;
  font-weight: 680;
  letter-spacing: -0.6px;
  line-height: 1.3;
  font-family: var(--font-display);
  color: var(--text-primary);
}
.nd-tags {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}
.nd-tag {
  border: none;
  background: var(--primary-bg);
  color: var(--primary-dark);
  border-radius: var(--radius-xs);
  padding: 1px 8px;
  font-size: var(--text-xs);
  line-height: 1.6;
  cursor: pointer;
}
html.dark .nd-tag { color: var(--primary-light); }
.nd-tag:hover { background: var(--primary-bg-strong); }
.nd-tag.is-mini { cursor: default; }
.nd-meta-line {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* 所属分组：色点 + 下拉 */
.nd-group-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.nd-group-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-disabled);
}
.nd-group-select { width: 150px; }
.nd-dot { color: var(--border-strong); }
.nd-muted { color: var(--text-tertiary); font-size: var(--text-sm); }

/* 面板 */
.nd-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  margin-bottom: var(--space-3);
}
.nd-panel-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
}
.nd-panel-ico { color: var(--primary); font-size: 16px; }
.nd-tab-label { display: inline-flex; align-items: center; gap: 6px; }

/* 视图切换 */
.nd-switch {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  margin-bottom: 12px;
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
}
.nd-switch-btn {
  border: none;
  background: transparent;
  padding: 3px 12px;
  border-radius: 3px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  cursor: pointer;
}
.nd-switch-btn.is-on {
  background: var(--bg-card);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
}

/* 正文 */
.nd-reading { min-height: 120px; }
.nd-editor { margin: -4px 0; }
.nd-parent {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.nd-link {
  color: var(--primary);
  cursor: pointer;
  font-weight: 600;
}
.nd-link:hover { text-decoration: underline; }
.nd-source {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  padding: var(--space-4);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 520px;
  overflow-y: auto;
  margin: 0;
  color: var(--text-primary);
}
.nd-json-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
}
.nd-json-tip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.nd-json-tip .el-icon { color: var(--primary); }
.nd-empty {
  padding: 26px 12px;
  text-align: center;
}
.nd-empty-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.nd-empty-desc {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  line-height: 1.7;
}

/* 链接列表 */
.nd-link-list { display: flex; flex-direction: column; gap: var(--space-2); }
.nd-link-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 9px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast);
}
.nd-link-item:hover { background: var(--primary-bg); }
.nd-link-item.is-block { flex-direction: column; align-items: stretch; gap: 6px; }
.nd-link-head { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.nd-link-dir { color: var(--text-tertiary); flex-shrink: 0; }
.nd-link-sub {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  margin-left: auto;
  font-family: var(--font-mono);
}
.nd-link-item.is-block .nd-link-sub { margin-left: 0; }
.nd-link-snippet {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.6;
  padding-left: 6px;
  border-left: 2px solid var(--border);
}

/* 关联的业务记录 */
.nd-related-list { display: flex; flex-direction: column; gap: 8px; }
.nd-related-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  border-left: 3px solid var(--success);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.nd-related-item:hover { background: var(--primary-bg); }
.nd-related-icon {
  width: 28px; height: 28px;
  border-radius: var(--radius-sm);
  background: var(--success-bg);
  color: var(--success);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.nd-related-body { flex: 1; min-width: 0; }
.nd-related-label { font-weight: 600; color: var(--text-primary); font-size: var(--text-sm); }
.nd-related-sub { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 2px; }
.nd-related-go { color: var(--text-tertiary); flex-shrink: 0; }
.nd-related-item:hover .nd-related-go { color: var(--primary); }

/* 侧栏 */
.nd-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 13px 14px;
  margin-bottom: var(--space-3);
}
.nd-meta-list { display: flex; flex-direction: column; }
.nd-meta-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  padding: 7px 0;
  border-bottom: 1px solid var(--border-light);
  font-size: var(--text-sm);
}
.nd-meta-row:last-child { border-bottom: none; }
.nd-meta-label { color: var(--text-tertiary); flex-shrink: 0; }
.nd-meta-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
}
.nd-meta-value.is-num { font-variant-numeric: tabular-nums; font-weight: 700; }

.nd-parent-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer;
  color: var(--text-primary);
  font-weight: 600;
  font-size: var(--text-sm);
  transition: all var(--duration-fast);
}
.nd-parent-card:hover {
  background: var(--primary-bg);
  border-color: var(--primary-light);
}
.nd-parent-card .el-icon { color: var(--primary); }

.nd-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 0;
  color: var(--text-tertiary);
}

@media (max-width: 768px) {
  .note-detail { padding: var(--space-4); }
  .nd-title { font-size: 22px; }
}
</style>
