<template>
  <div class="page">
    <PageTitle
      :title="entityType?.name || '加载中...'"
      :subtitle="(entityType?.description || '') + (entityType?.app ? ' · ' + entityType.app : '')"
      icon-key="Document"
    >
      <el-button @click="goGraph">
        <el-icon><Share /></el-icon>关联图谱
      </el-button>
      <el-button @click="doExport">
        <el-icon><Download /></el-icon>导出 CSV
      </el-button>
      <el-button @click="importOpen = true">
        <el-icon><Upload /></el-icon>导入
      </el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建记录
      </el-button>
    </PageTitle>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索记录…"
        clearable
        style="width:300px"
        @keyup.enter="load(1)"
        @clear="load(1)"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button @click="load(1)">搜索</el-button>
      <div class="spacer"></div>
      <span class="badge badge-ghost">共 {{ data.total || 0 }} 条</span>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建记录
      </el-button>
    </div>

    <!-- 列表 -->
    <div class="card" style="padding:0;overflow:hidden">
      <div v-if="!data.items?.length && !loading" class="empty-state" style="border:none;box-shadow:none">
        <div class="empty-icon"><el-icon :size="32"><Document /></el-icon></div>
        <div class="empty-title">暂无记录</div>
        <div class="empty-desc">该实体类型下还没有记录，点击「新建记录」开始录入第一条数据。</div>
        <div class="empty-actions">
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>新建记录
          </el-button>
        </div>
      </div>
      <el-table
        v-else
        :data="data.items || []"
        v-loading="loading"
        stripe
        class="data-table"
        @row-click="openDetail"
        :row-style="{ cursor:'pointer' }"
      >
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <span class="row-title">
              {{ row.data.name || row.data.title || row.data.code || `#${row.id}` }}
            </span>
          </template>
        </el-table-column>
        <el-table-column
          v-for="f in displayFields"
          :key="f.key"
          :label="f.name"
          :min-width="130"
        >
          <template #default="{ row }">
            <component
              :is="renderCell(f, row.data[f.key])"
            />
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click.stop="openEdit(row)">
              <el-icon><Edit /></el-icon>编辑
            </el-button>
            <el-button size="small" link @click.stop="goRecordGraph(row.id)">
              <el-icon><Share /></el-icon>图谱
            </el-button>
            <el-button size="small" link type="danger" @click.stop="del(row)">
              <el-icon><Delete /></el-icon>删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="data.items?.length"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="data.total || 0"
        layout="total, prev, pager, next, jumper"
        @current-change="load()"
        @size-change="load(1)"
        style="padding:16px 20px;justify-content:flex-end"
      />
    </div>

    <!-- 编辑/创建抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      :title="editingRecord ? '编辑记录' : '新建记录'"
      size="640px"
      direction="rtl"
      destroy-on-close
    >
      <div v-if="entityType">
        <DynamicForm
          :entity-type="entityType"
          :all-types="allTypes"
          v-model="formData"
          :record-id="editingRecord?.id || null"
          ref="formRef"
        />
      </div>
      <template #footer>
        <div style="padding:0 16px">
          <el-button @click="drawerOpen = false">取消</el-button>
          <el-button type="primary" @click="save">保存</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 详情侧栏（含关系） -->
    <el-drawer
      v-model="detailOpen"
      :title="detailRecord ? `详情 · ${displayName(detailRecord)}` : '详情'"
      size="640px"
      direction="rtl"
      destroy-on-close
    >
      <div v-if="detailRecord && entityType">
        <div class="card" style="margin-bottom:12px">
          <div class="card-title">
            <span><el-icon :size="16"><Document /></el-icon> 字段</span>
          </div>
          <div class="detail-fields">
            <div v-for="f in entityType.fields" :key="f.key" class="detail-field">
              <div class="detail-field-label">{{ f.name }}</div>
              <div class="detail-field-value">
                <span v-if="f.type === 'boolean'" :class="detailRecord.data[f.key] ? 'status-yes' : 'status-no'">
                  <span :class="['status-dot', detailRecord.data[f.key] ? 'success' : '']"></span>
                  {{ detailRecord.data[f.key] ? '是' : '否' }}
                </span>
                <span v-else-if="f.type === 'file' || f.type === 'image'">
                  <a
                    v-for="a in detailRecord.data[f.key] || []"
                    :key="a.id"
                    :href="previewUrlOf(a)"
                    target="_blank"
                    rel="noopener"
                    class="attachment-link"
                  >
                    <el-icon><Paperclip /></el-icon>{{ a.filename }}
                  </a>
                  <span v-if="!(detailRecord.data[f.key] || []).length" class="cell-empty">—</span>
                </span>
                <span v-else-if="f.type === 'reference'">
                  <a class="cell-reference" @click="goTargetRecord(detailRecord.data[f.key])">
                    {{ displayNameById(detailRecord.data[f.key], f) }}
                  </a>
                </span>
                <span v-else-if="!detailRecord.data[f.key]" class="cell-empty">—</span>
                <span v-else class="cell-text">{{ detailRecord.data[f.key] }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-bottom:12px">
          <div class="card-title">
            <span class="card-title-text">
              <el-icon class="title-ico"><Connection /></el-icon>关联关系
            </span>
            <el-button size="small" @click="addRelationDialog = true">
              <el-icon><Plus /></el-icon>添加关联
            </el-button>
          </div>
          <div v-if="relations.length">
            <div v-for="r in relations" :key="r.link_id" class="relation-item">
              <span class="rel-name">{{ r.relation }}</span>
              <span class="dir-badge" :class="r.direction">{{ r.direction === 'out' ? '指向' : '来自' }}</span>
              <a class="rel-other" @click="goOther(r)">
                <span class="ro-ico">{{ r.other_icon || '📦' }}</span>
                {{ r.other_label }}
                <el-tag v-if="r.other_kind === 'document'" size="small" effect="plain" type="info">文件</el-tag>
              </a>
              <el-button size="small" type="danger" text @click="delRelation(r.link_id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
          <div v-else class="empty-hint">
            <span>暂无关联</span>
            <el-button link type="primary" size="small" @click="$router.push('/relations')">
              去「关联定义」配置关系
            </el-button>
          </div>
        </div>

        <!-- 关联知识（记录 ↔ 知识库） -->
        <div v-if="!knowledge.is_note" class="card" style="margin-bottom:12px">
          <div class="card-title">
            <span class="card-title-text">
              <el-icon class="title-ico"><Notebook /></el-icon>关联知识
              <span v-if="knowledge.notes?.length" class="badge badge-ghost">{{ knowledge.notes.length }}</span>
            </span>
            <div class="card-actions">
              <el-button size="small" @click="openNoteLink">
                <el-icon><Link /></el-icon>关联笔记
              </el-button>
              <el-button size="small" type="primary" plain :loading="materializing" @click="materialize">
                <el-icon><MagicStick /></el-icon>沉淀为笔记
              </el-button>
            </div>
          </div>

          <div v-if="knowledge.notes?.length" class="kb-note-list">
            <div v-for="n in knowledge.notes" :key="n.note_id" class="kb-note-item">
              <div class="kb-note-icon"><el-icon><Notebook /></el-icon></div>
              <div class="kb-note-body">
                <div class="kb-note-title">
                  <a @click="$router.push(`/notes/${n.note_id}`)">{{ n.title }}</a>
                  <el-tag v-for="t in (n.tags || []).slice(0, 3)" :key="t" size="small" effect="plain">#{{ t }}</el-tag>
                  <el-tag v-if="n.empty" size="small" type="info">空笔记</el-tag>
                </div>
                <div class="kb-note-snippet">{{ n.snippet || '（暂无内容）' }}</div>
              </div>
              <el-button size="small" text @click="$router.push(`/notes/${n.note_id}`)">
                <el-icon><View /></el-icon>
              </el-button>
              <el-button size="small" type="danger" text @click="unlinkNote(n.note_id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
          <div v-else class="empty-hint">
            <span>还没有关联任何笔记。业务记录挂接知识库后，可在知识图谱中一起呈现。</span>
          </div>
        </div>

        <div class="card">
          <div class="card-title">元信息</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="ID">#{{ detailRecord.id }}</el-descriptions-item>
            <el-descriptions-item label="所属模型">{{ entityType.name }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(detailRecord.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ formatTime(detailRecord.updated_at) }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
    </el-drawer>

    <!-- 关联笔记弹窗 -->
    <el-dialog
      v-model="noteLinkDialog"
      title="关联知识库笔记"
      width="560px"
      class="rich-dialog"
      :close-on-click-modal="false"
    >
      <div class="dialog-summary">
        <el-icon :size="18"><Notebook /></el-icon>
        <span>把当前记录与知识库中的笔记挂接起来。关联后，可在笔记详情与关联图谱中双向看到。</span>
      </div>
      <div class="form-section" style="margin-bottom:0">
        <div class="form-section-title">选择笔记</div>
        <el-select
          v-model="selectedNoteId"
          filterable
          remote
          reserve-keyword
          clearable
          placeholder="输入关键词搜索笔记…"
          :remote-method="searchNotes"
          :loading="noteSearching"
          style="width:100%"
        >
          <el-option v-for="o in noteOptions" :key="o.id" :label="o.label" :value="o.id" />
        </el-select>
        <div class="form-hint" style="margin-top:8px">
          找不到？先去
          <a style="color:var(--primary);cursor:pointer" @click="$router.push('/notes')">知识库</a>
          新建笔记，或点「沉淀为笔记」由当前记录自动生成。
        </div>
      </div>
      <template #footer>
        <el-button @click="noteLinkDialog = false">取消</el-button>
        <el-button type="primary" :loading="linking" @click="linkNote">
          <el-icon><Link /></el-icon>建立关联
        </el-button>
      </template>
    </el-dialog>

    <!-- 添加关联（记录端 / 文件端统一由 RelationLinker 处理） -->
    <RelationLinker
      v-model="addRelationDialog"
      :defs="relationDefs"
      self-kind="record"
      :self-id="detailRecord?.id"
      :self-label="detailRecord ? (detailRecord.data?.name || detailRecord.data?.title || `#${detailRecord.id}`) : ''"
      @linked="reloadRelations"
    />

    <!-- 批量导入 -->
    <el-dialog v-model="importOpen" title="批量导入记录" width="620px">
      <el-alert type="info" :closable="false" style="margin-bottom:14px"
        title="CSV 列头需用字段 Key（先「导出 CSV」看一眼格式最稳）；JSON 支持数组或 {items:[]}" />
      <div style="margin-bottom:10px">
        <input type="file" accept=".csv,.json,.txt" @change="onImportFile" />
      </div>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="10"
        placeholder="或直接把 CSV / JSON 内容粘贴到这里…"
      />
      <template #footer>
        <span style="float:left;color:var(--el-text-color-secondary);font-size:12px">
          逐行校验：合法行照常入库，错误行会报出位置和原因
        </span>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="doImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { Api } from '../api'
import DynamicForm from '../components/DynamicForm.vue'
import PageTitle from '../components/PageTitle.vue'
import RelationLinker from '../components/RelationLinker.vue'
import { formatTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const typeId = computed(() => parseInt(route.params.typeId))

const entityType = ref(null)
const allTypes = ref([])
const data = ref({ items: [], total: 0 })
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)

const drawerOpen = ref(false)
const editingRecord = ref(null)
const formData = ref({})
const formRef = ref(null)

const detailOpen = ref(false)
const detailRecord = ref(null)
const relations = ref([])

const addRelationDialog = ref(false)
const relationDefs = ref([])

// 知识关联（记录 ↔ 笔记）
const knowledge = ref({ notes: [], is_note: false, note_type: null })
const noteLinkDialog = ref(false)
const noteOptions = ref([])
const noteSearching = ref(false)
const selectedNoteId = ref(null)
const linking = ref(false)
const materializing = ref(false)

// 外键显示名缓存：`${typeKey}:${id}` -> label
const refLabelCache = ref({})

function previewUrlOf(att) {
  return att?.preview_url || `/api/attachments/${att?.id}/preview`
}

// 用于列表显示的字段：排除 file/image/textarea/richtext
const displayFields = computed(() => {
  if (!entityType.value) return []
  return entityType.value.fields.filter(f =>
    !['file', 'image', 'textarea', 'richtext'].includes(f.type)
  ).slice(0, 6)
})

function renderCell(f, val) {
  if (val === null || val === undefined || val === '') {
    return h('span', { class: 'cell-empty' }, '—')
  }
  if (f.type === 'select') {
    return h(ElTag, { size: 'small', type: 'primary', effect: 'light' }, () => String(val))
  }
  if (f.type === 'boolean') {
    return val
      ? h('span', { class: 'status-yes' }, [h('span', { class: 'status-dot success' }), ' 是'])
      : h('span', { class: 'status-no' }, [h('span', { class: 'status-dot' }), ' 否'])
  }
  if (f.type === 'reference') {
    const label = refLabelCache.value[`${f.options?.target}:${val}`] || `#${val}`
    return h('span', { class: 'cell-reference' }, label)
  }
  if (f.type === 'number') {
    return h('span', { class: 'cell-number' }, String(val))
  }
  if (['date', 'datetime'].includes(f.type)) {
    return h('span', { class: 'cell-time' }, formatTime(val))
  }
  return h('span', { class: 'cell-text' }, String(val).slice(0, 60))
}

function displayName(r) {
  return r.data?.name || r.data?.title || r.data?.code || `#${r.id}`
}

async function load(p) {
  if (p) page.value = p
  loading.value = true
  try {
    data.value = await Api.listRecords(typeId.value, {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value,
    })
  } finally {
    loading.value = false
  }
}

async function loadEntityType() {
  const [et, all] = await Promise.all([
    Api.getEntityType(typeId.value),
    Api.listEntityTypes(),
  ])
  entityType.value = et
  allTypes.value = all
}

async function loadRelations() {
  relationDefs.value = await Api.listRelationDefs()
}

function openCreate() {
  editingRecord.value = null
  formData.value = {}
  drawerOpen.value = true
}

function openEdit(row) {
  editingRecord.value = row
  formData.value = { ...(row.data || {}) }
  drawerOpen.value = true
}

async function save() {
  try {
    if (editingRecord.value) {
      await Api.updateRecord(editingRecord.value.id, formData.value)
    } else {
      await Api.createRecord(typeId.value, formData.value)
    }
    ElMessage.success('保存成功')
    drawerOpen.value = false
    load()
  } catch (e) {}
}

async function del(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 "${displayName(row)}"？删除后进入回收站，可恢复。`,
      '确认', { type: 'warning' })
    await Api.deleteRecord(row.id)
    ElMessage.success('已移入回收站')
    load()
  } catch (e) {
    if (e !== 'cancel') {} // 忽略
  }
}

// ============ 导入 / 导出 ============
const importOpen = ref(false)
const importText = ref('')
const importFormat = ref('csv')
const importing = ref(false)

function doExport() {
  // 走原生链接让浏览器处理下载（带 cookie 的同源请求）
  window.open(Api.exportRecordsUrl(typeId.value), '_blank')
}

async function doImport() {
  if (!importText.value.trim()) {
    ElMessage.warning('内容为空')
    return
  }
  importing.value = true
  try {
    const r = await Api.importRecords(typeId.value, importText.value, importFormat.value)
    const parts = [`新增 ${r.created} 条`]
    if (r.failed) parts.push(`失败 ${r.failed} 行`)
    if (r.warnings?.length) parts.push(r.warnings.join('；'))
    if (r.failed) {
      ElMessage.warning({
        message: parts.join('；') + '。详情：' + r.errors.slice(0, 3).map(e => `第${e.row}行 ${e.reason}`).join(' / '),
        duration: 8000,
      })
    } else {
      ElMessage.success(parts.join('；'))
    }
    importOpen.value = false
    importText.value = ''
    load(1)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}

function onImportFile(ev) {
  const file = ev.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    importText.value = String(reader.result || '')
    importFormat.value = file.name.toLowerCase().endsWith('.json') ? 'json' : 'csv'
  }
  reader.readAsText(file)
  ev.target.value = ''
}

async function openDetail(row) {
  detailRecord.value = await Api.getRecord(row.id)
  relations.value = await Api.relationsForRecord(row.id)
  detailOpen.value = true
  // 异步补齐，不阻塞抽屉打开
  loadKnowledge(row.id)
  loadRefLabels()
}

// ============ 知识关联 ============

async function loadKnowledge(recordId) {
  try {
    knowledge.value = await Api.getRecordKnowledge(recordId)
  } catch (e) {
    knowledge.value = { notes: [], is_note: false, note_type: null }
  }
}

function openNoteLink() {
  selectedNoteId.value = null
  noteOptions.value = []
  noteLinkDialog.value = true
  searchNotes('')
}

async function searchNotes(q) {
  const ntId = knowledge.value.note_type?.id
  if (!ntId) return
  noteSearching.value = true
  try {
    const r = await Api.listRecords(ntId, { keyword: q || '', page_size: 50 })
    // 已关联的笔记不再出现在候选里
    const linked = new Set((knowledge.value.notes || []).map(n => n.note_id))
    noteOptions.value = (r.items || [])
      .filter(x => !linked.has(x.id))
      .map(x => ({ id: x.id, label: x.data?.title || `#${x.id}` }))
  } catch (e) {
    noteOptions.value = []
  } finally {
    noteSearching.value = false
  }
}

async function linkNote() {
  if (!selectedNoteId.value) {
    ElMessage.warning('请先选择一条笔记')
    return
  }
  linking.value = true
  try {
    await Api.linkKnowledge(detailRecord.value.id, selectedNoteId.value)
    ElMessage.success('已关联')
    noteLinkDialog.value = false
    await loadKnowledge(detailRecord.value.id)
  } finally {
    linking.value = false
  }
}

async function unlinkNote(noteId) {
  try {
    await Api.unlinkKnowledge(detailRecord.value.id, noteId)
    ElMessage.success('已解除关联')
    await loadKnowledge(detailRecord.value.id)
  } catch (e) { /* 拦截器已提示 */ }
}

async function materialize() {
  materializing.value = true
  try {
    const r = await Api.noteFromRecord(detailRecord.value.id)
    ElMessage.success('已生成笔记并关联')
    await loadKnowledge(detailRecord.value.id)
    router.push(`/notes/${r.note_id}`)
  } catch (e) { /* 拦截器已提示 */ } finally {
    materializing.value = false
  }
}

// ============ 外键显示名 ============

async function loadRefLabels() {
  if (!entityType.value) return
  const refFields = entityType.value.fields.filter(f => f.type === 'reference')
  for (const f of refFields) {
    const tkey = f.options?.target
    if (!tkey) continue
    const et = allTypes.value.find(t => t.key === tkey)
    if (!et) continue
    try {
      const r = await Api.listRecords(et.id, { page_size: 200 })
      const next = { ...refLabelCache.value }
      for (const rec of (r.items || [])) {
        next[`${tkey}:${rec.id}`] = rec.data?.name || rec.data?.title
          || rec.data?.code || `#${rec.id}`
      }
      refLabelCache.value = next
    } catch (e) { /* 忽略 */ }
  }
}

async function delRelation(rid) {
  try {
    await Api.deleteRelationRecord(rid)
    relations.value = relations.value.filter(r => r.link_id !== rid)
    ElMessage.success('已删除')
  } catch {}
}

async function reloadRelations() {
  if (!detailRecord.value) return
  relations.value = await Api.relationsForRecord(detailRecord.value.id)
}

/** 关联对象的跳转：文件进数据中心，记录进对应模型 */
function goOther(link) {
  if (!link?.other_id) return
  if (link.other_kind === 'document') {
    router.push({ path: '/library', query: { id: link.other_id } })
    return
  }
  const tid = link.other_type_id
  if (tid) router.push({ path: `/records/${tid}`, query: { id: link.other_id } })
  else goTargetRecord(link.other_id)
}

function goTargetRecord(id) {
  // 通过 id 找对应的实体类型，跳转到该类型
  // 简化处理：通过查询该记录跳转
  if (!id) return
  Api.getRecord(id).then(r => {
    if (r) {
      router.push(`/records/${r.entity_type_id}?id=${r.id}`)
    }
  })
}

function displayNameById(id, field) {
  if (!id) return '—'
  const tkey = field?.options?.target
  if (tkey) {
    const cached = refLabelCache.value[`${tkey}:${id}`]
    if (cached) return cached
  }
  return `#${id}`
}

function goRecordGraph(id) {
  router.push(`/graph?record=${id}`)
}

function goGraph() {
  router.push(`/graph?type=${typeId.value}`)
}

onMounted(async () => {
  await loadEntityType()
  await loadRelations()
  await load(1)
  loadRefLabels()
  // 如果 URL 带 id，自动打开详情
  if (route.query.id) {
    const rec = await Api.getRecord(parseInt(route.query.id))
    if (rec) openDetail(rec)
  }
})

watch(typeId, async () => {
  await loadEntityType()
  await load(1)
})

// 监听行点击：详情还是编辑？用 modifier 区分？简化：双击详情，点击编辑
// 这里改成默认点击编辑，详情按钮触发
</script>

<style scoped>
.relation-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  margin-bottom: 8px;
  transition: background var(--duration-fast) var(--ease-out);
}
.relation-item:hover { background: var(--primary-50); }
.rel-name {
  background: var(--primary-bg);
  color: var(--primary);
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
  flex-shrink: 0;
}
/* 方向用文字徽标而不是箭头：箭头看不出「谁指向谁」 */
.dir-badge {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  padding: 1px 7px;
  flex-shrink: 0;
}
.rel-other {
  flex: 1; min-width: 0; display: inline-flex; align-items: center; gap: 6px;
  color: var(--primary); cursor: pointer; font-size: var(--text-base);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rel-other:hover { text-decoration: underline; }
.ro-ico { font-size: 13px; line-height: 1; }
.arrow { color: var(--text-tertiary); font-weight: 700; }

.detail-fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px 24px;
}
.detail-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.detail-field-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.detail-field-value {
  font-size: var(--text-base);
  color: var(--text-primary);
  line-height: 1.5;
  word-break: break-word;
}
.attachment-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--primary);
  text-decoration: none;
  padding: 3px 8px;
  background: var(--primary-bg);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  margin-right: 6px;
  margin-bottom: 4px;
}
.attachment-link:hover { text-decoration: underline; }

/* 卡片头部的次级按钮组 */
.card-actions { display: flex; gap: 6px; }

/* 空态提示（卡片内） */
.empty-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 14px 16px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

/* 关联知识列表 */
.kb-note-list { display: flex; flex-direction: column; gap: 8px; }
.kb-note-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  border-left: 3px solid var(--primary);
  transition: background var(--duration-fast) var(--ease-out);
}
.kb-note-item:hover { background: var(--primary-50); }
.kb-note-icon {
  width: 28px; height: 28px;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.kb-note-body { flex: 1; min-width: 0; }
.kb-note-title {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-weight: 600;
}
.kb-note-title a { color: var(--primary); cursor: pointer; }
.kb-note-title a:hover { text-decoration: underline; }
.kb-note-snippet {
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}
</style>