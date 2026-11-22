<template>
  <div class="daily-workspace">
    <section class="daily-intro" aria-labelledby="daily-heading">
      <h1 id="daily-heading">今天，想了解什么？</h1>
      <form v-if="canUseAI || canSearch" class="daily-composer" @submit.prevent="submitQuestion">
        <label class="daily-question">
          <el-icon aria-hidden="true"><MagicStick v-if="canUseAI" /><Search v-else /></el-icon>
          <textarea
            v-model="question"
            :aria-label="canUseAI ? '向 AI 助手提问' : '搜索工作区内容'"
            :placeholder="canUseAI ? '问一个关于笔记、文件或业务记录的问题…' : '搜索笔记、文件或业务记录…'"
            rows="2"
            @keydown="onQuestionKey"
          ></textarea>
        </label>
        <div class="daily-composer-actions">
          <button v-if="canUseAI && canSearch" class="daily-search" type="button" :disabled="!question.trim()" @click="searchContent">
            <el-icon aria-hidden="true"><Search /></el-icon>搜索内容
          </button>
          <button class="daily-submit" type="submit" :disabled="!question.trim()">
            {{ canUseAI ? '询问 AI 助手' : '搜索内容' }}
            <el-icon aria-hidden="true"><ArrowRight /></el-icon>
          </button>
        </div>
      </form>

      <div v-if="canImport || canWriteNote" class="daily-actions">
        <RouterLink v-if="canImport" :to="{ name: 'library', query: { action: 'upload' } }" class="daily-action">
          <el-icon aria-hidden="true"><Upload /></el-icon>导入资料
        </RouterLink>
        <RouterLink v-if="canWriteNote" :to="{ name: 'notes', query: { action: 'create' } }" class="daily-action">
          <el-icon aria-hidden="true"><EditPen /></el-icon>写笔记
        </RouterLink>
      </div>
    </section>

    <div v-if="contentScope || canSeeFiles" class="daily-recent">
      <WorkspaceRecentList
        v-if="contentScope"
        title="最近内容"
        icon="Clock"
        :items="recentContent"
        :state="contentState"
        :more="canReadNotes ? '/notes' : ''"
        more-label="查看笔记"
        :empty="contentScope === 'notes' ? '暂无最近笔记' : '已加载的最近更新中，暂无可打开的记录'"
        error="最近内容加载失败"
        @retry="loadContent"
      />
      <WorkspaceRecentList
        v-if="canSeeFiles"
        title="最近文件"
        icon="FolderOpened"
        :items="recentFiles"
        :state="filesState"
        more="/library"
        more-label="打开资料库"
        empty="暂无可查看的文件"
        error="最近文件加载失败"
        @retry="loadFiles"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Api } from '../api'
import WorkspaceRecentList from '../components/workspace/WorkspaceRecentList.vue'
import { useWorkspaceActions } from '../composables/useWorkspaceActions'
import { useAuthStore } from '../stores/auth'
import { formatSize, formatTime } from '../utils/format'
import { loadWorkspaceRecents } from '../utils/workspaceRecents'

const auth = useAuthStore()
const router = useRouter()
const { openAssistant } = useWorkspaceActions()
const question = ref('')
const canUseAI = computed(() => auth.can('ai'))
const canSearch = computed(() => auth.canPage('search'))
const canSeeFiles = computed(() => auth.canPage('library'))
const canReadNotes = computed(() => auth.canPage('notes') && auth.canModel('note'))
const canReadRecords = computed(() => auth.canPage('records'))
const contentScope = computed(() => {
  if (canReadRecords.value) return 'records'
  if (canReadNotes.value) return 'notes'
  return ''
})
const canImport = computed(() => canSeeFiles.value && auth.can('file_write'))
const canWriteNote = computed(() => auth.canPage('notes') && auth.canModel('note', 'write'))

function searchContent() {
  const kw = question.value.trim()
  if (canSearch.value && kw) router.push({ name: 'search', query: { kw } })
}

function submitQuestion() {
  const text = question.value.trim()
  if (!text) return
  if (!canUseAI.value) {
    searchContent()
    return
  }
  openAssistant(text)
  question.value = ''
}

function onQuestionKey(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submitQuestion()
}

const recentRecords = ref([])
const documents = ref([])
const contentState = ref('loading')
const filesState = ref('loading')
const recentContent = computed(() => {
  const items = []
  for (const record of recentRecords.value) {
    const { record_id: id, entity_type_id: typeId, entity_type_key: type, entity_type_name: name } = record
    if (!id) continue
    const note = type === 'note'
    if (note ? !canReadNotes.value : !typeId || !canReadRecords.value) continue
    const { title, name: recordName, code } = record.data || {}
    items.push({
      key: id,
      title: String(title || recordName || code || `#${id}`),
      icon: note ? 'Notebook' : 'Document',
      meta: [note ? '笔记' : name, formatTime(record.updated_at)].filter(Boolean).join(' · '),
      to: note ? { name: 'note-detail', params: { id } } : { name: 'records', params: { typeId }, query: { id } },
    })
    if (items.length === 5) break
  }
  return items
})
const recentFiles = computed(() => documents.value.filter(file => file.id).map(file => ({
  key: file.id,
  title: file.filename,
  icon: 'Document',
  meta: [formatSize(file.size), formatTime(file.created_at)].filter(Boolean).join(' · '),
  to: { name: 'library', query: { doc: file.id } },
})))

let contentRequest = 0

async function loadContent() {
  const request = ++contentRequest
  const scope = contentScope.value
  recentRecords.value = []
  if (!scope) return
  contentState.value = 'loading'
  try {
    const records = await loadWorkspaceRecents(Api, scope)
    if (request !== contentRequest) return
    recentRecords.value = records
    contentState.value = 'ready'
  } catch {
    if (request === contentRequest) contentState.value = 'error'
  }
}

async function loadFiles() {
  if (!canSeeFiles.value) return
  filesState.value = 'loading'
  try {
    const data = await Api.listDocuments({ page: 1, page_size: 5 })
    documents.value = data.items || []
    filesState.value = 'ready'
  } catch {
    filesState.value = 'error'
  }
}

watch(contentScope, loadContent, { immediate: true })
watch(canSeeFiles, allowed => { if (allowed) loadFiles() }, { immediate: true })
</script>

<style scoped>
.daily-workspace {
  width: min(100%, 1024px);
  margin: 0 auto;
  padding: clamp(46px, 8vh, 84px) clamp(24px, 5vw, 64px) var(--space-12);
}
.daily-intro { max-width: 700px; margin: 0 auto; }
.daily-intro h1 {
  margin: 0 0 var(--space-5);
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: clamp(26px, 3.8vw, 36px);
  font-weight: 680;
  line-height: 1.25;
  letter-spacing: -0.035em;
}
.daily-composer {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  box-shadow: var(--shadow-xs);
}
.daily-composer:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-ring); }
.daily-question { display: flex; align-items: flex-start; gap: var(--space-3); color: var(--primary); }
.daily-question .el-icon { flex: none; margin-top: 5px; font-size: 17px; }
.daily-question textarea {
  width: 100%;
  min-width: 0;
  padding: 0;
  color: var(--text-primary);
  border: 0;
  outline: none;
  background: transparent;
  resize: vertical;
  font: inherit;
  font-size: var(--text-lg);
  line-height: 1.65;
}
.daily-question textarea::placeholder { color: var(--text-tertiary); }
.daily-composer-actions, .daily-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.daily-composer-actions { justify-content: flex-end; }
.daily-actions { margin-top: var(--space-4); }
.daily-action, .daily-submit, .daily-search {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 38px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
  color: var(--text-secondary);
  font: inherit;
  text-decoration: none;
  cursor: pointer;
}
.daily-action:hover, .daily-search:hover { border-color: var(--border-strong); color: var(--text-primary); }
.daily-search { border-color: transparent; }
.daily-submit { border-color: transparent; background: var(--primary-grad); color: #fff; font-weight: 600; }
.daily-submit:hover { filter: brightness(1.05); }
.daily-submit:disabled { background: var(--primary-bg-strong); color: var(--primary); }
.daily-search:disabled { color: var(--text-disabled); }
.daily-submit:disabled, .daily-search:disabled { cursor: default; }
.daily-recent {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: var(--space-4);
  margin-top: var(--space-10);
}
.daily-recent > :only-child { grid-column: 1 / -1; }
@media (max-width: 680px) {
  .daily-workspace { padding: var(--space-8) var(--space-4) var(--space-8); }
  .daily-intro h1 { margin-bottom: var(--space-4); }
  .daily-recent { grid-template-columns: minmax(0, 1fr); margin-top: var(--space-7); }
}
</style>
