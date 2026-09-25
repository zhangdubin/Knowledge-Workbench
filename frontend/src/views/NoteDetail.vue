<template>
  <div class="page">
    <el-button text @click="$router.push('/notes')" style="margin-bottom:8px">
      <el-icon><ArrowLeft /></el-icon>返回笔记列表
    </el-button>
    <PageTitle
      v-if="!editing && record"
      :title="record.data.title || `未命名 #${noteId}`"
      :subtitle="record.data.tags?.length ? record.data.tags.map(t => '#' + t).join(' · ') : '（无标签）'"
      icon-key="Notebook"
    >
      <el-button v-if="!editing" @click="startEdit">
        <el-icon><Edit /></el-icon>编辑
      </el-button>
      <el-button v-else @click="cancelEdit">取消</el-button>
      <el-button v-if="editing" type="primary" @click="save">
        <el-icon><Check /></el-icon>保存
      </el-button>
      <el-button v-if="!editing" @click="goGraph">
        <el-icon><Share /></el-icon>图谱
      </el-button>
      <el-dropdown v-if="!editing" trigger="click" @command="openAI">
        <el-button type="primary" plain>
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
        v-if="!editing"
        title="确定删除这篇笔记？反向链接和正链都会被解除。"
        confirm-button-text="删除"
        cancel-button-text="取消"
        @confirm="deleteNote"
      >
        <template #reference>
          <el-button type="danger" plain>
            <el-icon><Delete /></el-icon>删除
          </el-button>
        </template>
      </el-popconfirm>
    </PageTitle>

    <div v-if="record" class="note-layout">
      <!-- 主内容区 -->
      <div class="note-main">
        <div class="card">
          <el-tabs v-if="!editing" v-model="viewTab">
            <el-tab-pane name="rendered">
              <template #label>
                <span class="tab-label"><el-icon><Reading /></el-icon>阅读</span>
              </template>
              <div v-if="record.data.tags?.length" class="tag-list" style="margin-bottom:12px">
                <el-tag v-for="t in record.data.tags" :key="t" size="small" effect="plain">#{{ t }}</el-tag>
              </div>
              <div v-if="record.data.parent" class="parent-link">
                <el-icon><Top /></el-icon>
                父笔记：
                <a class="link-inline" @click="goToNote(record.data.parent)">
                  {{ parentTitle }}
                </a>
              </div>
              <div class="rendered" v-html="renderedContent"></div>
              <div v-if="!record.data.content" class="empty">（空笔记）</div>
            </el-tab-pane>
            <el-tab-pane name="json">
              <template #label>
                <span class="tab-label"><el-icon><MagicStick /></el-icon>JSON</span>
              </template>
              <div class="json-meta">
                <el-radio-group v-model="jsonScope" size="small">
                  <el-radio-button value="record">记录数据</el-radio-button>
                  <el-radio-button value="content">正文</el-radio-button>
                </el-radio-group>
                <span class="json-tip">
                  <el-icon><InfoFilled /></el-icon>
                  {{ jsonScope === 'record'
                    ? '这条记录的完整字段（标题、标签、双链、时间），标准 JSON，可直接复制给 AI'
                    : '正文本身是 JSON 时可直接展开成树；不是 JSON 会提示到具体行列' }}
                </span>
              </div>
              <JsonViewer v-if="jsonScope === 'record'" :value="record.data || {}" />
              <JsonViewer v-else :text="record.data.content || ''" />
            </el-tab-pane>
            <el-tab-pane name="raw">
              <template #label>
                <span class="tab-label"><el-icon><Document /></el-icon>原文</span>
              </template>
              <pre class="raw-content">{{ record.data.content || '（空）' }}</pre>
            </el-tab-pane>
          </el-tabs>

          <NoteEditor
            v-else
            v-model="formData"
            :record-id="record.id"
            @change="onChange"
          />
        </div>

        <!-- 关联面板 -->
        <div class="card" style="margin-top:12px">
          <div class="card-title">
            <span class="card-title-text">
              <el-icon class="title-ico"><Connection /></el-icon>双向链接
            </span>
          </div>
          <el-tabs v-model="linkTab">
            <el-tab-pane name="outgoing">
              <template #label>
                <span class="tab-label">正向链接
                  <span class="badge badge-primary">{{ outgoing.length }}</span>
                </span>
              </template>
              <div v-if="outgoing.length" class="link-list">
                <div v-for="o in outgoing" :key="o.target_record_id" class="link-item">
                  <el-icon class="link-dir"><Right /></el-icon>
                  <a class="link-title" @click="goToNote(o.target_record_id)">
                    {{ o.title }}
                  </a>
                  <el-tag v-if="o.placeholder" size="small" type="info" effect="plain">占位</el-tag>
                  <span class="link-subtitle">原文本 [[{{ o.link_title }}]]</span>
                </div>
              </div>
              <div v-else class="empty" style="padding:32px 20px">
                <div class="empty-icon" style="font-size:28px"><el-icon><Connection /></el-icon></div>
                <div class="empty-title">没有正向链接</div>
                <div class="empty-desc">在内容中用 [[笔记标题]] 即可创建</div>
              </div>
            </el-tab-pane>
            <el-tab-pane name="backlinks">
              <template #label>
                <span class="tab-label">反向链接
                  <span class="badge badge-success">{{ backlinks.length }}</span>
                </span>
              </template>
              <div v-if="backlinks.length" class="link-list">
                <div v-for="b in backlinks" :key="b.source_record_id" class="link-item block">
                  <div class="link-head">
                    <el-icon class="link-dir"><Back /></el-icon>
                    <a class="link-title" @click="goToNote(b.source_record_id)">
                      {{ b.title }}
                    </a>
                    <span class="link-subtitle">引用了 [[{{ b.link_title }}]]</span>
                  </div>
                  <div class="link-snippet">{{ b.snippet }}</div>
                </div>
              </div>
              <div v-else class="empty" style="padding:32px 20px">
                <div class="empty-icon" style="font-size:28px"><el-icon><Connection /></el-icon></div>
                <div class="empty-title">还没有其他笔记引用此笔记</div>
                <div class="empty-desc">在其他笔记中用 [[{{ record.data.title }}]] 即可建立关联</div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>

        <!-- 关联的业务记录 -->
        <div class="card" style="margin-top:12px">
          <div class="card-title">
            <span class="card-title-text">
              <el-icon class="title-ico"><Collection /></el-icon>关联的业务记录
              <span v-if="relatedRecords.length" class="badge badge-ghost">{{ relatedRecords.length }}</span>
            </span>
          </div>
          <div v-if="relatedRecords.length" class="related-list">
            <div
              v-for="r in relatedRecords"
              :key="`${r.entity_type_id}-${r.record_id}`"
              class="related-item"
              @click="goRecord(r)"
            >
              <div class="related-icon">
                <el-icon><component :is="entityIcon(r.entity_type_key)" /></el-icon>
              </div>
              <div class="related-body">
                <div class="related-label">{{ r.label }}</div>
                <div class="related-sub">
                  {{ r.entity_type_name }} · {{ r.relation_name }}
                </div>
              </div>
              <el-icon class="related-go"><ArrowRight /></el-icon>
            </div>
          </div>
          <div v-else class="empty" style="padding:28px 20px">
            <div class="empty-icon" style="font-size:26px"><el-icon><Collection /></el-icon></div>
            <div class="empty-title">还没有业务记录引用这条笔记</div>
            <div class="empty-desc">
              在任意记录的详情里点「关联笔记」或「沉淀为笔记」，即可在此双向呈现。
            </div>
            <el-button size="small" style="margin-top:10px" @click="$router.push('/apps')">
              <el-icon><Grid /></el-icon>去应用中心
            </el-button>
          </div>
        </div>
      </div>

      <!-- 侧栏 -->
      <div class="note-side">
        <div class="card">
          <div class="card-title">
            <span class="card-title-text">
              <el-icon class="title-ico"><DataBoard /></el-icon>元信息
            </span>
          </div>
          <div class="meta-list">
            <div class="meta-row">
              <span class="meta-label">ID</span>
              <span class="meta-value">#{{ record.id }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">标签</span>
              <span class="meta-value">
                <template v-if="record.data.tags?.length">
                  <el-tag v-for="t in record.data.tags" :key="t" size="small" effect="plain">#{{ t }}</el-tag>
                </template>
                <span v-else class="cell-empty">—</span>
              </span>
            </div>
            <div class="meta-row">
              <span class="meta-label">正链 / 反链</span>
              <span class="meta-value">{{ outgoing.length }} / {{ backlinks.length }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">字数</span>
              <span class="meta-value num">{{ contentLength }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">JSON 节点</span>
              <span class="meta-value num">{{ jsonSummary.nodeCount || 0 }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">创建</span>
              <span class="meta-value">{{ formatTime(record.created_at) }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">更新</span>
              <span class="meta-value">{{ formatTime(record.updated_at) }}</span>
            </div>
          </div>
        </div>

        <div v-if="record.data.parent" class="card">
          <div class="card-title">
            <span class="card-title-text">
              <el-icon class="title-ico"><FolderOpened /></el-icon>所在层级
            </span>
          </div>
          <a class="parent-card" @click="goToNote(record.data.parent)">
            <el-icon><Notebook /></el-icon>
            <span>{{ parentTitle }}</span>
          </a>
        </div>
      </div>
    </div>

    <div v-else class="empty-state" style="border:none;background:transparent">
      <div class="empty-icon"><el-icon :size="28"><Loading /></el-icon></div>
      <div class="empty-title">加载中…</div>
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
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { entityIcon } from '../utils/icons'
import { parseJson, summarize } from '../utils/jsonview'
import NoteEditor from '../components/NoteEditor.vue'
import JsonViewer from '../components/JsonViewer.vue'
import AIAssistantDialog from '../components/AIAssistantDialog.vue'
import PageTitle from '../components/PageTitle.vue'

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

const viewTab = ref('rendered')
const linkTab = ref('outgoing')

const contentLength = computed(() => (record.value?.data?.content || '').length)

// JSON 视图范围：记录数据（永远合法）/ 正文（用户自己写的 JSON 才解析得出来）
const jsonScope = ref('record')

const jsonSummary = computed(() => {
  const empty = { textLength: 0, nodeCount: 0, maxDepth: 0, directChildren: 0 }
  if (!record.value) return empty
  if (jsonScope.value === 'record') return summarize(record.value.data || {})
  const r = parseJson(record.value.data.content || '')
  return r.ok ? summarize(r.value) : empty
})

const renderedContent = computed(() => {
  const text = record.value?.data?.content || ''
  let html = escapeHtml(text)
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

async function load() {
  record.value = await Api.getRecord(noteId.value)
  outgoing.value = await Api.getNoteOutgoing(noteId.value)
  backlinks.value = await Api.getNoteBacklinks(noteId.value)
  loadRelatedRecords()
  if (record.value?.data?.parent) {
    try {
      const p = await Api.getRecord(record.value.data.parent)
      parentTitle.value = p?.data?.title || `#${record.value.data.parent}`
    } catch {
      parentTitle.value = `#${record.value.data.parent}`
    }
  }
}

// 关联的业务记录（由业务侧「关联知识 / 沉淀为笔记」反向而来）
const relatedRecords = ref([])
async function loadRelatedRecords() {
  try {
    const r = await Api.getNoteRecords(noteId.value)
    relatedRecords.value = r.records || []
  } catch (e) {
    relatedRecords.value = []
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
    await Api.updateRecord(noteId.value, formData.value)
    if (formData.value.content !== originalContent.value) {
      await Api.syncNoteLinks(noteId.value, formData.value.content)
    }
    ElMessage.success('已保存')
    editing.value = false
    await load()
  } catch (e) {}
}

function onChange() {}

function goToNote(id) {
  router.push(`/notes/${id}`)
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
    // 把摘要加到内容末尾
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

onMounted(async () => {
  await load()
})

watch(noteId, async () => {
  editing.value = false
  await load()
})
</script>

<style scoped>
.note-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--space-4);
  align-items: start;
}
@media (max-width: 1080px) {
  .note-layout { grid-template-columns: 1fr; }
}

.tab-label { display: inline-flex; align-items: center; gap: 6px; }
.card-title-text { display: inline-flex; align-items: center; gap: 8px; }
.title-ico { color: var(--primary); font-size: 18px; }

.tag-list { display: flex; gap: 6px; flex-wrap: wrap; }
.parent-link {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--space-3);
  font-size: var(--text-base);
  color: var(--text-secondary);
}
.link-inline { color: var(--primary); cursor: pointer; font-weight: 600; }
.link-inline:hover { text-decoration: underline; }

.rendered {
  line-height: 1.9;
  font-size: var(--text-md);
  min-height: 200px;
  color: var(--text-primary);
}
.rendered :deep(.wikilink-rendered) {
  color: var(--primary);
  text-decoration: none;
  background: var(--primary-bg);
  padding: 1px 5px;
  border-radius: var(--radius-xs);
  font-weight: 500;
  cursor: pointer;
}
.rendered :deep(.wikilink-rendered:hover) { background: var(--primary-bg-strong); }
.rendered :deep(h1) {
  font-size: var(--text-3xl);
  margin: 20px 0 10px;
  font-weight: 700;
  letter-spacing: -0.5px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-light);
}
.rendered :deep(h2) {
  font-size: var(--text-2xl);
  margin: 18px 0 8px;
  font-weight: 700;
  letter-spacing: -0.3px;
}
.rendered :deep(h3) { font-size: var(--text-xl); margin: 14px 0 6px; font-weight: 600; }
.rendered :deep(code) {
  background: var(--bg-subtle);
  padding: 2px 5px;
  border-radius: var(--radius-xs);
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--primary-dark);
}
.rendered :deep(strong) { font-weight: 700; }

.raw-content {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  padding: var(--space-4);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 500px;
  overflow-y: auto;
  margin: 0;
  color: var(--text-primary);
}

.json-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
}
.json-tip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.json-tip .el-icon { color: var(--primary); }

/* 侧栏元信息 */
.meta-list { display: flex; flex-direction: column; }
.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  padding: 9px 0;
  border-bottom: 1px solid var(--border-light);
  font-size: var(--text-sm);
}
.meta-row:last-child { border-bottom: none; }
.meta-label { color: var(--text-tertiary); flex-shrink: 0; }
.meta-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
}
.meta-value.num { font-variant-numeric: tabular-nums; font-weight: 700; font-size: var(--text-md); }

/* 链接列表 */
.link-list { display: flex; flex-direction: column; gap: var(--space-2); }
.link-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 11px 14px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast);
}
.link-item:hover { background: var(--primary-50); }
html.dark .link-item:hover { background: var(--bg-elevated); }
.link-item.block { flex-direction: column; align-items: stretch; gap: 6px; }
.link-head { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.link-dir { color: var(--text-tertiary); flex-shrink: 0; }
.link-title {
  color: var(--primary);
  cursor: pointer;
  font-weight: 600;
}
.link-title:hover { text-decoration: underline; }
.link-subtitle {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  margin-left: auto;
  font-family: var(--font-mono);
}
.link-item.block .link-subtitle { margin-left: 0; }
.link-snippet {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.6;
  padding-left: 6px;
  border-left: 2px solid var(--border);
}

.parent-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 12px 14px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--text-primary);
  font-weight: 600;
  transition: all var(--duration-fast);
  border: 1px solid transparent;
}
.parent-card:hover {
  background: var(--primary-50);
  border-color: var(--primary-light);
}
.parent-card .el-icon { color: var(--primary); }

/* 关联的业务记录 */
.related-list { display: flex; flex-direction: column; gap: 8px; }
.related-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  border-left: 3px solid var(--success);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.related-item:hover { background: var(--primary-50); }
.related-icon {
  width: 30px; height: 30px;
  border-radius: var(--radius-sm);
  background: var(--success-bg);
  color: var(--success);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.related-body { flex: 1; min-width: 0; }
.related-label { font-weight: 600; color: var(--text-primary); }
.related-sub { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 2px; }
.related-go { color: var(--text-tertiary); flex-shrink: 0; }
.related-item:hover .related-go { color: var(--primary); }
</style>