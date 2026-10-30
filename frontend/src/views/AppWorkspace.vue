<template>
  <div class="page aw">
    <!-- ============ 页头 ============ -->
    <header class="aw-header">
      <div class="aw-head-main">
        <div class="aw-icon">
          <el-icon :size="24"><component :is="iconName" /></el-icon>
        </div>
        <div class="aw-head-text">
          <div class="aw-title-row">
            <h2 class="aw-title">{{ app?.name || '加载中…' }}</h2>
            <span class="aw-key">{{ app?.key || '' }}</span>
          </div>
          <p class="aw-desc">{{ appDescription }}</p>
        </div>
      </div>

      <div class="aw-stats">
        <div class="aw-stat">
          <b>{{ models.length }}</b><span>数据模型</span>
        </div>
        <div class="aw-stat">
          <b>{{ totalRecords }}</b><span>数据记录</span>
        </div>
        <div class="aw-stat">
          <b>{{ totalFields }}</b><span>字段总数</span>
        </div>
      </div>

      <div class="aw-actions">
        <el-button @click="backToApps">
          <el-icon><ArrowLeft /></el-icon>返回应用中心
        </el-button>
        <el-button :disabled="!canManageModel" @click="newModel">
          <el-icon><Plus /></el-icon>新建模型
        </el-button>
        <!--
          记录操作：导出 / 导入 / 图谱
          以前这一排只有「新建模型 / 录入记录」，记录本身的进出与查看入口全缺，
          用户会以为「应用里的记录只能录不能导」——
          现在与「记录页」完全对齐。
        -->
        <el-button :disabled="!currentType" @click="doExport">
          <el-icon><Download /></el-icon>导出 CSV
        </el-button>
        <el-button :disabled="!currentType" @click="importOpen = true">
          <el-icon><Upload /></el-icon>导入
        </el-button>
        <el-button :disabled="!currentType" @click="openTypeGraph">
          <el-icon><Share /></el-icon>关联图谱
        </el-button>
        <el-button type="primary" :disabled="!canManage || !currentType" @click="createRecord">
          <el-icon><EditPen /></el-icon>录入记录
        </el-button>
      </div>
    </header>

    <!-- 应用下还没有数据模型：给一张引导页，而不是一个空表格 -->
    <EmptyState
      v-if="!loadingModels && !models.length"
      icon="Files"
      title="这个应用还没有数据模型"
      description="数据模型定义了「这张表有哪些字段」。先建一个模型，就能开始录入业务数据了。"
    >
      <el-button type="primary" :disabled="!canManageModel" @click="newModel">
        <el-icon><Plus /></el-icon>新建第一个模型
      </el-button>
    </EmptyState>

    <div v-else class="aw-body">
      <!-- ============ 左侧模型列表 ============ -->
      <aside v-if="!narrow" class="aw-side">
        <div class="aw-side-title">
          数据模型
          <span class="badge badge-ghost">{{ models.length }}</span>
        </div>
        <div class="aw-models">
          <button
            v-for="m in models"
            :key="m.id"
            type="button"
            class="aw-model"
            :class="{ 'is-active': m.id === currentTypeId }"
            :aria-current="m.id === currentTypeId ? 'true' : undefined"
            @click="selectModel(m)"
          >
            <span class="aw-model-icon">
              <el-icon :size="15"><component :is="m.icon || 'Grid'" /></el-icon>
            </span>
            <span class="aw-model-text">
              <span class="aw-model-name">{{ m.name }}</span>
              <span class="aw-model-meta">
                <el-icon><Document /></el-icon>{{ m.record_count || 0 }}
                <el-icon><Files /></el-icon>{{ m.field_count || 0 }}
              </span>
            </span>
          </button>
        </div>
        <button type="button" class="aw-add-model" :disabled="!canManageModel" @click="newModel">
          <el-icon><Plus /></el-icon>新建模型
        </button>
      </aside>

      <!-- ============ 右侧记录区 ============ -->
      <section class="aw-main">
        <div class="aw-bar">
          <!-- 窄屏：模型列表收进抽屉，这里给一个下拉 -->
          <el-select
            v-if="narrow"
            class="aw-model-select"
            :model-value="currentTypeId"
            placeholder="选择数据模型"
            @update:model-value="selectModelById"
          >
            <el-option
              v-for="m in models"
              :key="m.id"
              :label="`${m.name}（${m.record_count || 0}）`"
              :value="m.id"
            />
          </el-select>

          <div class="aw-bar-title">
            <span class="aw-bar-name">{{ currentType?.name || '记录' }}</span>
            <span class="aw-bar-count">{{ total }} 条</span>
          </div>

          <div class="aw-bar-spacer" />

          <el-input
            v-model="keyword"
            class="aw-search"
            placeholder="按字段模糊搜索…"
            clearable
            :prefix-icon="Search"
            @keyup.enter="reload"
            @clear="reload"
          />

          <!--
            筛选器 / 列显示 / 视图切换：与「记录页」共用 RecordToolbar
            （以前这套是本页内联写的，记录页没有，两边手感对不上）
          -->
          <RecordToolbar
            v-model:filters="filters"
            v-model:visible-keys="visibleKeys"
            v-model:view-mode="viewMode"
            :filter-fields="filterFields"
            :choices-map="choicesMap"
            :display-fields="displayFields"
            :default-keys="defaultKeys"
            :selected-count="selected.length"
            :can-manage="canManage"
            @change="reload"
            @clear-selection="clearSelection"
            @batch-remove="batchRemove"
          />

          <el-button type="primary" :disabled="!canManage || !currentType" @click="createRecord">
            <el-icon><Plus /></el-icon>新建记录
          </el-button>
        </div>

        <!-- 记录内容 -->
        <div v-if="loading" class="aw-loading">
          <el-skeleton :rows="6" animated />
        </div>

        <EmptyState
          v-else-if="!currentType"
          icon="Grid"
          title="先选一个数据模型"
          description="左边选一个模型，就能在这里管理它的记录。"
        />

        <EmptyState
          v-else-if="!records.length && (keyword || activeFilterCount)"
          variant="inline"
          icon="Search"
          title="没有符合条件的记录"
          description="换个关键词，或者把筛选条件放宽一点。"
        >
          <el-button @click="clearSearch">清除条件</el-button>
        </EmptyState>

        <EmptyState
          v-else-if="!records.length"
          icon="Document"
          title="还没有记录"
          :description="`「${currentType.name}」下还没有任何数据，建一条就开始了。`"
        >
          <el-button type="primary" :disabled="!canManage" @click="createRecord">
            <el-icon><Plus /></el-icon>新建第一条记录
          </el-button>
        </EmptyState>

        <template v-else>
          <div v-if="viewMode === 'table'" class="aw-table">
            <RecordTable
              :records="records"
              :columns="columns"
              :labels="refLabels"
              :loading="loading"
              :can-manage="canManage"
              selection
              @edit="editRecord"
              @remove="removeRecord"
              @open="openRecord"
              @graph="openGraph"
              @selection-change="onSelectionChange"
            />
          </div>
          <RecordCardGrid
            v-else
            :records="records"
            :fields="cardFields"
            :labels="refLabels"
            :can-manage="canManage"
            @edit="editRecord"
            @remove="removeRecord"
            @open="openRecord"
          />

          <RecordPagination
            :page="page"
            :page-size="pageSize"
            :total="total"
            @update:page="onPageChange"
            @update:page-size="onPageSizeChange"
          />
        </template>
      </section>
    </div>

    <!-- ============ 新建 / 编辑记录 ============ -->
    <RecordFormDrawer
      v-model="formOpen"
      :entity-type="currentType"
      :record="editingRecord"
      :all-types="allTypes"
      @saved="onSaved"
    />

    <!-- ============ 记录详情（与记录页共用同一个抽屉） ============ -->
    <RecordDetailDrawer
      v-model="detailOpen"
      :record="detailRecord"
      :entity-type="currentType"
      :labels="refLabels"
      :can-edit="canManage"
      @edit="editFromDetail"
      @open-reference="openReference"
    >
      <!-- 关联关系 + 关联知识：应用页以前是空的，
           用户从「客户管理 → 某个模型 → 某条记录」进来看不到任何关联，
           会以为应用里的记录没有关联功能。
           现在跟记录页共用同一个面板。 -->
      <template #extra>
        <RecordRelationsPanel v-if="detailRecord" :record="detailRecord" />
      </template>
    </RecordDetailDrawer>

    <!-- 批量导入：与「记录页」共用同一个弹窗 -->
    <RecordImportDialog
      v-model="importOpen"
      :type-id="currentType?.id"
      :type-name="currentType?.name"
      @imported="onImported"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft, Document, Download, EditPen, Files, Plus, Search, Share, Upload,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { useAuthStore } from '../stores/auth'
import { resolveAppIcon } from '../utils/apps'
import { APP_ICON_CHOICES } from '../utils/icons'
import {
  recordDisplayName, defaultColumnKeys,
} from '../utils/recordFields'
import EmptyState from '../components/EmptyState.vue'
import RecordTable from '../components/record/RecordTable.vue'
import RecordRelationsPanel from '../components/record/RecordRelationsPanel.vue'
import RecordCardGrid from '../components/record/RecordCardGrid.vue'
import RecordFormDrawer from '../components/record/RecordFormDrawer.vue'
import RecordPagination from '../components/record/RecordPagination.vue'
import RecordDetailDrawer from '../components/record/RecordDetailDrawer.vue'
import RecordToolbar from '../components/record/RecordToolbar.vue'
import RecordImportDialog from '../components/record/RecordImportDialog.vue'
import { useRecordFields, useRecordView } from '../components/record/useRecordFields'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const app = ref(null)
const models = ref([])
const allTypes = ref([])
const currentTypeId = ref(null)
const currentTypeFull = ref(null)

const records = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const keyword = ref('')

// 批量删除：选中的记录
const selected = ref([])

// 导入记录弹窗
const importOpen = ref(false)

const loadingModels = ref(true)
const loading = ref(false)

const formOpen = ref(false)
const editingRecord = ref(null)
const detailOpen = ref(false)
const detailRecord = ref(null)

const narrow = ref(false)

// 记录区要用到的字段分组
const {
  fields, displayFields, cardFields, filterFields, choicesMap, refLabels, loadRefLabels,
} = useRecordFields(currentTypeFull, { allTypesRef: allTypes })

// 筛选 / 列显示 / 视图切换：与「记录页」共用同一份状态逻辑
const {
  filters, visibleKeys, viewMode, columns, resetForType, clearFilters, filterParams,
} = useRecordView(currentTypeFull)

// 默认勾选的列（恢复默认时用）
const defaultKeys = computed(() => defaultColumnKeys(currentTypeFull.value?.fields || []))

// 模型结构归 model_manage 管；记录能不能写归模型级权限管（models: {key: read|write}）
const canManageModel = computed(() => auth.can('model_manage'))
const canManage = computed(() => {
  const t = currentType.value
  return !!t && auth.canModel(t.key, 'write')
})
const iconName = computed(() => resolveAppIcon(app.value, APP_ICON_CHOICES))
const appDescription = computed(() => app.value?.description || '暂无说明')
const currentType = computed(() => currentTypeFull.value)
const totalRecords = computed(() => models.value.reduce((s, m) => s + (m.record_count || 0), 0))
const totalFields = computed(() => models.value.reduce((s, m) => s + (m.field_count || 0), 0))
const activeFilterCount = computed(() =>
  Object.values(filters.value).filter(v =>
    v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length)).length)

// ============ 加载 ============

async function loadApp() {
  try {
    const list = await Api.listApps()
    const hit = (list || []).find(a => a.key === route.params.appKey)
    app.value = hit || null
    if (!hit) {
      ElMessage.warning('没有找到这个应用')
      return
    }
  } catch {
    ElMessage.error('应用信息加载失败')
  }
}

async function loadModels() {
  loadingModels.value = true
  try {
    models.value = (await Api.listEntityTypes(route.params.appKey)) || []
    // 全量模型列表：外键下拉与显示名解析都要用
    allTypes.value = (await Api.listEntityTypes()) || []
    if (models.value.length) {
      // 默认选中记录最多的模型：多数应用最关心的是「哪张表有数据」
      const first = [...models.value].sort((a, b) =>
        (b.record_count || 0) - (a.record_count || 0))[0]
      await selectModel(first)
    }
  } catch {
    ElMessage.error('数据模型加载失败')
  } finally {
    loadingModels.value = false
  }
}

async function selectModel(m) {
  if (!m) return
  currentTypeId.value = m.id
  page.value = 1
  keyword.value = ''
  try {
    // 列表接口不返回字段定义，字段要单独取一份完整的
    currentTypeFull.value = await Api.getEntityType(m.id)
    // 换模型时重置视图状态：上一个模型的列名对不上新模型
    resetForType()
    await loadRefLabels()
    await loadRecords()
  } catch {
    ElMessage.error('模型定义加载失败')
  }
}

async function selectModelById(id) {
  const m = models.value.find(x => x.id === id)
  if (m) selectModel(m)
}

/**
 * 只刷新模型列表（记录数变了），不重置当前选中的模型
 * 增删记录之后要更新侧栏的计数，但不能把用户切好的模型又跳回默认那个。
 */
async function refreshModels() {
  try {
    models.value = (await Api.listEntityTypes(route.params.appKey)) || []
  } catch { /* 计数刷新失败不影响主流程 */ }
}

async function loadRecords() {
  if (!currentType.value) {
    records.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    // 筛选交给服务端做。
    //
    // 为什么不本地筛：本地筛要把这个模型的记录**整个拉下来**再筛，
    // 一次最多 500 条 —— 超过这个数，后面的记录用户根本筛不到，
    // 而且分页数字是假的（第 2 页可能是空的）。
    // 服务端筛是「在库里过滤 + 过滤后的 total」，才是真的。
    const active = filterParams()
    const r = await Api.listRecords(currentType.value.id, {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      filters: Object.keys(active).length ? JSON.stringify(active) : undefined,
    })
    records.value = r.items || []
    total.value = r.total || 0
  } catch {
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadRecords()
}

/** 翻页：页码变了就重新取数据 */
function onPageChange(p) {
  page.value = p
  loadRecords()
}

/** 每页条数变了：回到第一页，否则可能停在一个已经不存在的页码上 */
function onPageSizeChange(s) {
  pageSize.value = s
  page.value = 1
  loadRecords()
}

function clearSearch() {
  keyword.value = ''
  clearFilters()
  page.value = 1
  loadRecords()
}

// ============ 记录操作 ============

function createRecord() {
  if (!currentType.value) return
  editingRecord.value = null
  formOpen.value = true
}

function editRecord(rec) {
  editingRecord.value = rec
  formOpen.value = true
}

function openRecord(rec) {
  detailRecord.value = rec
  detailOpen.value = true
}

function editFromDetail() {
  if (!detailRecord.value) return
  detailOpen.value = false
  editRecord(detailRecord.value)
}

function openGraph(rec) {
  router.push(`/graph?record=${rec.id}`)
}

/** 整个模型的关联图谱：与「记录页」的「关联图谱」按钮去同一个地方 */
function openTypeGraph() {
  if (!currentType.value) return
  router.push(`/graph?type=${currentType.value.id}`)
}

/**
 * 导出 CSV
 * 走原生链接让浏览器处理下载（带 cookie 的同源请求）
 */
function doExport() {
  if (!currentType.value) return
  window.open(Api.exportRecordsUrl(currentType.value.id), '_blank')
}

// ============ 批量删除 ============

function onSelectionChange(rows) {
  selected.value = rows || []
}

function clearSelection() {
  selected.value = []
}

/**
 * 批量删除
 *
 * 后端没有批量删除接口（只有 DELETE /api/records/{id}），
 * 所以这里顺序调用单条删除 —— 顺序而不是并发，是为了别把后端打爆。
 */
async function batchRemove() {
  const rows = selected.value
  if (!rows.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${rows.length} 条记录吗？删除后可在回收站找回。`,
      '批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  let ok = 0
  let failed = 0
  for (const row of rows) {
    try {
      await Api.deleteRecord(row.id)
      ok++
    } catch {
      failed++
    }
  }
  clearSelection()
  if (failed) {
    ElMessage.warning(`成功删除 ${ok} 条，${failed} 条失败`)
  } else {
    ElMessage.success(`已删除 ${ok} 条记录`)
  }
  await refreshModels()
  await loadRecords()
}

/** 点关联字段里的名字：跳到被关联的那条记录 */
async function openReference(id) {
  if (!id) return
  try {
    const r = await Api.getRecord(id)
    if (r?.entity_type_id) router.push(`/records/${r.entity_type_id}?id=${r.id}`)
  } catch {
    ElMessage.warning('这条关联记录打不开')
  }
}

async function removeRecord(rec) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${recordDisplayName(rec)}」这条记录吗？删除后可在回收站找回。`,
      '删除记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await Api.deleteRecord(rec.id)
    ElMessage.success('已删除')
    detailOpen.value = false
    await refreshModels()
    await loadRecords()
  } catch {
    ElMessage.error('删除失败')
  }
}

function onSaved() {
  refreshModels()
  loadRecords()
}

/** 导入记录后刷新：记录数变了，侧栏的模型计数也要跟着变 */
function onImported() {
  refreshModels()
  loadRecords(1)
}

function newModel() {
  router.push({ path: '/types/new', query: { app: route.params.appKey } })
}

function backToApps() {
  router.push('/apps')
}

// ============ 响应式：窄屏把模型列表收起来 ============

function updateNarrow() {
  narrow.value = window.innerWidth < 1100
}

onMounted(async () => {
  updateNarrow()
  window.addEventListener('resize', updateNarrow)
  await loadApp()
  await loadModels()
})

onUnmounted(() => {
  window.removeEventListener('resize', updateNarrow)
})

// 切换路由上的应用时重新加载
watch(() => route.params.appKey, async () => {
  currentTypeFull.value = null
  records.value = []
  await loadApp()
  await loadModels()
})
</script>

<style scoped>
/* ============ 页头 ============ */
.aw-header {
  /* 头部
   *
   * 原来是一行里塞「图标 + 标题 + 3 个统计 + 6 个按钮」——
   * 空间不够时 flex 把标题压成一条竖线（「销售管理」变成 销/售/管/理 四个字一行，
   * 实测过），非常难看。
   *
   * 现在分两层：
   *   第一层：身份（图标 + 标题 + 描述）  ·  统计（靠右）
   *   第二层：操作按钮
   */
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'main stats'
    'actions actions';
  align-items: center;
  gap: var(--space-3) var(--space-5);
  padding: var(--space-4) var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-4);
}
.aw-head-main {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  flex: 1;
}
.aw-icon {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}
.aw-head-text { min-width: 0; }
.aw-title-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.aw-title {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.5px;
  font-family: var(--font-display);
}
.aw-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
}
.aw-desc {
  margin: 4px 0 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
}

.aw-stats {
  grid-area: stats;
  display: flex;
  gap: var(--space-2);
  justify-self: end;
}
.aw-stat {
  min-width: 76px;
  /* 统计块不能被压扁（压扁了数字就换行，一行变成两行） */
  flex-shrink: 0;
  white-space: nowrap;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  text-align: center;
}
.aw-stat b {
  display: block;
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.aw-stat span { font-size: var(--text-xs); color: var(--text-secondary); }

.aw-actions {
  grid-area: actions;
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light); display: flex; gap: var(--space-2); flex-wrap: wrap; }

/* ============ 主体两栏 ============ */
.aw-body {
  display: grid;
  grid-template-columns: 264px 1fr;
  gap: var(--space-4);
  align-items: start;
}

/* ============ 左侧模型列表 ============ */
.aw-side {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-3);
  position: sticky;
  top: var(--space-4);
  max-height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
}
.aw-side-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-primary);
  padding: var(--space-1) var(--space-2) var(--space-3);
}
.aw-models {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  flex: 1;
}
.aw-model {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  text-align: left;
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}
.aw-model:hover { background: var(--surface-hover); }
.aw-model:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: -2px;
}
.aw-model.is-active {
  background: var(--primary-bg);
  border-color: var(--primary-200);
  color: var(--text-primary);
}
.aw-model-icon {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.aw-model.is-active .aw-model-icon {
  background: var(--primary-bg);
  color: var(--primary-dark);
}
.aw-model-text { min-width: 0; flex: 1; }
.aw-model-name {
  display: block;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.aw-model-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 2px;
}
.aw-model-meta .el-icon { margin-left: 4px; }
.aw-model-meta .el-icon:first-child { margin-left: 0; }
.aw-add-model {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  margin-top: var(--space-3);
  padding: var(--space-2);
  min-height: 34px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}
.aw-add-model:hover { border-color: var(--primary); color: var(--primary); }
.aw-add-model:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}

/* ============ 右侧记录区 ============ */
.aw-main {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
  min-width: 0;
}
.aw-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
}
.aw-model-select { width: 180px; }
.aw-bar-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
}
.aw-bar-name {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.2px;
}
.aw-bar-count { font-size: var(--text-sm); color: var(--text-secondary); }
.aw-bar-spacer { flex: 1; }
.aw-search { width: 230px; }

/* 筛选器 / 列显示的样式已经搬进 RecordToolbar（两页共用），
   这里不再留一份 —— 留两份迟早会改漏一边，用户又会看到「两个入口不一样」。 */

.aw-table {
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  overflow: hidden;
}
.aw-loading { padding: var(--space-2) 0; }

@media (max-width: 1100px) {
  .aw-body { grid-template-columns: 1fr; }
  .aw-header { gap: var(--space-3); }
  .aw-search { width: 100%; }
}
</style>
