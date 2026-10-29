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
      <el-button type="primary" :disabled="!canManage" @click="openCreate">
        <el-icon><Plus /></el-icon>新建记录
      </el-button>
    </PageTitle>

    <!--
      工具条：搜索 + 筛选 + 列显示 + 视图切换
      后三个是 RecordToolbar（与应用独立页共用同一个组件），
      以前只有应用页有，用户会觉得「记录页功能少」——
    -->
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
        @change="load(1)"
        @clear-selection="clearSelection"
        @batch-remove="batchRemove"
      />
      <div class="spacer"></div>
      <span class="badge badge-ghost">共 {{ data.total || 0 }} 条</span>
      <el-button type="primary" :disabled="!canManage" @click="openCreate">
        <el-icon><Plus /></el-icon>新建记录
      </el-button>
    </div>

    <!-- 列表：与「应用独立页」共用同一套记录表格 -->
    <div class="card" style="padding:0;overflow:hidden">
      <template v-if="data.items?.length">
        <RecordTable
          v-if="viewMode === 'table'"
          :records="data.items"
          :columns="columns"
          :labels="refLabels"
          :loading="loading"
          :can-manage="canManage"
          selection
          @edit="openEdit"
          @remove="del"
          @open="openDetail"
          @graph="goRecordGraph"
          @selection-change="onSelectionChange"
        />
        <RecordCardGrid
          v-else
          :records="data.items"
          :fields="cardFields"
          :labels="refLabels"
          :can-manage="canManage"
          @edit="openEdit"
          @remove="del"
          @open="openDetail"
        />
      </template>
      <div v-else-if="!loading" class="empty-state" style="border:none;box-shadow:none">
        <div class="empty-icon"><el-icon :size="32"><Document /></el-icon></div>
        <div class="empty-title">暂无记录</div>
        <div class="empty-desc">该实体类型下还没有记录，点击「新建记录」开始录入第一条数据。</div>
        <div class="empty-actions">
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>新建记录
          </el-button>
        </div>
      </div>
      <RecordPagination
        v-if="data.items?.length"
        :page="page"
        :page-size="pageSize"
        :total="data.total || 0"
        style="padding:16px 20px"
        @update:page="load"
        @update:page-size="onSizeChange"
      />
    </div>

    <!-- 编辑/创建抽屉：表单按模型字段定义自动生成 -->
    <RecordFormDrawer
      v-model="drawerOpen"
      :entity-type="entityType"
      :record="editingRecord"
      :all-types="allTypes"
      @saved="onSaved"
    />

    <!-- 详情侧栏：字段区与元信息用公共抽屉，关系/知识往 extra 插槽里塞 -->
    <RecordDetailDrawer
      v-model="detailOpen"
      :record="detailRecord"
      :entity-type="entityType"
      :labels="refLabels"
      size="640px"
      @edit="openEdit"
      @open-reference="goTargetRecord"
    >
      <template #extra>
        <!-- 关联关系 + 关联知识：与应用页共用同一个面板（以前只有记录页有） -->
        <RecordRelationsPanel v-if="detailRecord" :record="detailRecord" />
      </template>
    </RecordDetailDrawer>

    <!-- 批量导入：与应用独立页共用同一个弹窗 -->
    <RecordImportDialog
      v-model="importOpen"
      :type-id="entityType?.id"
      :type-name="entityType?.name"
      @imported="load(1)"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'
import { useAuthStore } from '../stores/auth'
import PageTitle from '../components/PageTitle.vue'
import RecordTable from '../components/record/RecordTable.vue'
import RecordCardGrid from '../components/record/RecordCardGrid.vue'
import RecordFormDrawer from '../components/record/RecordFormDrawer.vue'
import RecordDetailDrawer from '../components/record/RecordDetailDrawer.vue'
import RecordRelationsPanel from '../components/record/RecordRelationsPanel.vue'
import RecordPagination from '../components/record/RecordPagination.vue'
import RecordToolbar from '../components/record/RecordToolbar.vue'
import RecordImportDialog from '../components/record/RecordImportDialog.vue'
import { useRecordFields, useRecordView } from '../components/record/useRecordFields'
import { recordDisplayName, defaultColumnKeys } from '../utils/recordFields'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
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

const detailOpen = ref(false)
const detailRecord = ref(null)

const importOpen = ref(false)

// 批量删除：选中的记录
const selected = ref([])

// 外键显示名缓存与「哪些字段显示成列」都走公共逻辑：
// 应用页与记录页共用同一套，否则两个入口的列和外键显示会对不上
const { displayFields, cardFields, filterFields, choicesMap, refLabels, loadRefLabels } =
  useRecordFields(entityType, { allTypesRef: allTypes })

// 筛选 / 列显示 / 视图切换：与应用独立页共用同一份状态逻辑
const {
  filters, visibleKeys, viewMode, columns, resetForType, filterParams,
} = useRecordView(entityType)

// 默认勾选的列（恢复默认时用）
const defaultKeys = computed(() => defaultColumnKeys(entityType.value?.fields || []))

// 这个模型的记录能不能写：与应用独立页同一把尺子
const canManage = computed(() => {
  const t = entityType.value
  if (!t) return false
  return auth.canModel(t.key, 'write')
})

async function load(p) {
  if (p) page.value = p
  loading.value = true
  try {
    const active = filterParams()
    data.value = await Api.listRecords(typeId.value, {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      // 筛选交给服务端：本地筛要把记录整个拉下来（上限 500 条），
      // 超过这个数后面的记录筛不到，分页数字也是假的
      filters: Object.keys(active).length ? JSON.stringify(active) : undefined,
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

function openCreate() {
  editingRecord.value = null
  drawerOpen.value = true
}

function openEdit(row) {
  editingRecord.value = row
  drawerOpen.value = true
}

/** 表单抽屉保存成功后刷新列表 */
function onSaved() {
  load()
}

function onSizeChange(size) {
  pageSize.value = size
  load(1)
}

async function del(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 "${recordDisplayName(row)}"？删除后进入回收站，可恢复。`,
      '确认', { type: 'warning' })
    await Api.deleteRecord(row.id)
    ElMessage.success('已移入回收站')
    load()
  } catch (e) {
    if (e !== 'cancel') {} // 忽略
  }
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
  load()
}

// ============ 导入 / 导出 ============

function doExport() {
  // 走原生链接让浏览器处理下载（带 cookie 的同源请求）
  window.open(Api.exportRecordsUrl(typeId.value), '_blank')
}

async function openDetail(row) {
  detailRecord.value = await Api.getRecord(row.id)
  detailOpen.value = true
  // 关联关系与关联知识由 RecordRelationsPanel 自己加载（它 watch 记录变化）
  loadRefLabels()
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

function goRecordGraph(id) {
  router.push(`/graph?record=${id}`)
}

function goGraph() {
  router.push(`/graph?type=${typeId.value}`)
}

onMounted(async () => {
  await loadEntityType()
  // 换模型时重置视图状态：上一个模型的列名对不上新模型
  resetForType()
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
  resetForType()
  await load(1)
})
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
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
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
