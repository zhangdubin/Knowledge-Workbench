<template>
  <div class="page">
    <PageTitle
      title="数据模型"
      subtitle="定义实体类型（表结构），承载结构化与非结构化数据"
      icon-key="Files"
    >
      <el-button @click="openJsonImport">
        <el-icon><MagicStick /></el-icon>JSON 导入
      </el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建模型
      </el-button>
    </PageTitle>

    <!-- 工具条：搜索 / 筛选 / 排序 / 视图切换 -->
    <div class="toolbar">
      <el-input
        ref="searchRef"
        v-model="search"
        placeholder="搜索模型名称、标识或描述…（按 / 聚焦）"
        clearable
        class="tb-search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="appFilter" class="tb-select" placeholder="全部应用">
        <el-option label="全部应用" value="all">
          <span class="tb-option"><el-icon><Grid /></el-icon>全部应用</span>
        </el-option>
        <el-option v-for="a in apps" :key="a.key" :label="a.name" :value="a.key">
          <span class="tb-option">
            <el-icon><component :is="appIcon(a.key)" /></el-icon>{{ a.name }}
          </span>
        </el-option>
      </el-select>

      <el-select v-model="fillFilter" class="tb-select">
        <el-option label="全部模型" value="all" />
        <el-option label="有记录的" value="with" />
        <el-option label="空模型" value="empty" />
      </el-select>

      <el-select v-model="sortBy" class="tb-select">
        <el-option label="默认排序" value="default" />
        <el-option label="按名称" value="name" />
        <el-option label="按字段数" value="fields" />
        <el-option label="按记录数" value="records" />
      </el-select>

      <div class="spacer"></div>

      <el-radio-group v-model="viewMode" class="tb-view" aria-label="视图切换">
        <el-radio-button value="card">
          <el-icon><Grid /></el-icon>卡片
        </el-radio-button>
        <el-radio-button value="table">
          <el-icon><Menu /></el-icon>表格
        </el-radio-button>
      </el-radio-group>

      <span class="toolbar-count">共 {{ visible.length }} 个模型</span>
    </div>

    <!-- 批量操作条：只在有勾选时出现 -->
    <div v-if="selectedIds.length" class="batch-bar">
      <span class="batch-count">已选 {{ selectedIds.length }} 个模型</span>
      <div class="batch-actions">
        <el-button @click="openBatchMove">
          <el-icon><FolderOpened /></el-icon>批量改应用
        </el-button>
        <el-button :loading="exporting" @click="batchExport">
          <el-icon><Download /></el-icon>批量导出
        </el-button>
        <el-button type="danger" plain @click="batchDelete">
          <el-icon><Delete /></el-icon>批量删除
        </el-button>
        <el-button text @click="clearSelection">取消选择</el-button>
      </div>
    </div>

    <!-- 卡片视图 -->
    <div v-if="viewMode === 'card'" class="model-grid">
      <div
        v-for="t in visible"
        :key="t.id"
        class="model-card"
        :class="{ 'is-selected': isSelected(t.id) }"
        role="button"
        tabindex="0"
        :aria-label="`模型 ${t.name}，${t.field_count} 个字段，${t.record_count} 条记录`"
        @click="goRecords(t)"
        @keydown.enter.prevent="goRecords(t)"
        @keydown.space.prevent="goRecords(t)"
      >
        <div class="mdl-head">
          <el-checkbox
            class="mdl-check"
            :model-value="isSelected(t.id)"
            :aria-label="`选中模型 ${t.name}`"
            @click.stop
            @keydown.stop
            @change="v => toggleSelect(t.id, v)"
          />
          <span class="mdl-icon">
            <el-icon :size="20"><component :is="entityIcon(t.key)" /></el-icon>
          </span>
          <div class="mdl-titles">
            <div class="mdl-name" :title="t.name">{{ t.name }}</div>
            <div class="mdl-key" :title="t.key">{{ t.key }}</div>
          </div>
          <div class="mdl-menu" @click.stop @keydown.stop>
            <el-dropdown
              trigger="click"
              placement="bottom-end"
              @command="c => onCardCommand(c, t)"
            >
              <button type="button" class="model-menu-btn" aria-label="更多操作" @click.stop>
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="records">
                    <el-icon><Document /></el-icon>查看记录
                  </el-dropdown-item>
                  <el-dropdown-item command="edit">
                    <el-icon><EditPen /></el-icon>编辑模型
                  </el-dropdown-item>
                  <el-dropdown-item command="export">
                    <el-icon><Download /></el-icon>导出 JSON
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided class="dd-danger">
                    <el-icon><Delete /></el-icon>删除模型
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <p class="mdl-desc">{{ t.description || '暂无说明' }}</p>

        <!-- 字段类型标签预览：像 Airtable 那样一眼看到这张表长什么样 -->
        <div class="mdl-tags">
          <span
            v-for="tag in previewTags(t)"
            :key="tag.key"
            class="field-tag"
            :title="`${tag.name} · ${tag.label}${tag.required ? ' · 必填' : ''}`"
          >
            <span class="field-tag-icon" :style="{ background: tag.color }">{{ tag.icon }}</span>
            <span class="field-tag-name">{{ tag.name }}</span>
            <span class="field-tag-type">{{ tag.label }}</span>
          </span>
          <span v-if="restFieldCount(t) > 0" class="field-tag is-rest">+{{ restFieldCount(t) }}</span>
          <span v-if="!previewTags(t).length" class="field-tag-empty">暂无字段</span>
        </div>

        <div class="mdl-meta">
          <span class="mdl-app">
            <el-icon :size="13"><component :is="appIcon(t.app)" /></el-icon>{{ appName(t.app) }}
          </span>
          <span><el-icon :size="13"><Grid /></el-icon>{{ t.field_count }} 字段</span>
          <span><el-icon :size="13"><Document /></el-icon>{{ t.record_count }} 记录</span>
        </div>
      </div>
    </div>

    <!-- 表格视图 -->
    <el-table
      v-else
      :data="visible"
      class="model-table"
      :class="tableDensityClass('default')"
      row-key="id"
    >
      <el-table-column width="46">
        <template #header>
          <el-checkbox
            :model-value="allSelected"
            :indeterminate="someSelected"
            aria-label="全选模型"
            @change="toggleSelectAll"
          />
        </template>
        <template #default="{ row }">
          <el-checkbox
            :model-value="isSelected(row.id)"
            :aria-label="`选中模型 ${row.name}`"
            @change="v => toggleSelect(row.id, v)"
          />
        </template>
      </el-table-column>
      <el-table-column label="模型" min-width="220">
        <template #default="{ row }">
          <div class="cell-model">
            <span class="cell-model-icon">
              <el-icon :size="17"><component :is="entityIcon(row.key)" /></el-icon>
            </span>
            <span class="cell-model-text">
              <span class="cell-model-name">{{ row.name }}</span>
              <span class="cell-model-key">{{ row.key }}</span>
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="所属应用" width="140">
        <template #default="{ row }">{{ appName(row.app) }}</template>
      </el-table-column>
      <el-table-column label="字段" width="80" align="right">
        <template #default="{ row }">{{ row.field_count }}</template>
      </el-table-column>
      <el-table-column label="记录" width="80" align="right">
        <template #default="{ row }">{{ row.record_count }}</template>
      </el-table-column>
      <el-table-column label="字段预览" min-width="280">
        <template #default="{ row }">
          <div class="cell-tags">
            <span
              v-for="tag in previewTags(row)"
              :key="tag.key"
              class="field-tag"
              :title="`${tag.name} · ${tag.label}`"
            >
              <span class="field-tag-icon" :style="{ background: tag.color }">{{ tag.icon }}</span>
              <span class="field-tag-name">{{ tag.name }}</span>
            </span>
            <span v-if="restFieldCount(row) > 0" class="field-tag is-rest">+{{ restFieldCount(row) }}</span>
            <span v-if="!previewTags(row).length" class="field-tag-empty">暂无字段</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button class="cell-btn" text @click="openEdit(row)">
            <el-icon><EditPen /></el-icon>编辑
          </el-button>
          <el-button class="cell-btn" text @click="goRecords(row)">
            <el-icon><Document /></el-icon>记录
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空状态 -->
    <EmptyState
      v-if="!visible.length"
      :icon="hasFilter ? 'Search' : 'Files'"
      :title="hasFilter ? '没有匹配的模型' : '还没有数据模型'"
      :description="hasFilter
        ? '换个关键词，或把筛选条件放宽一点。'
        : '在应用下定义实体类型（表结构），即可承载结构化与非结构化数据。也可以直接粘贴一份 JSON 建模型。'"
    >
      <template v-if="hasFilter">
        <el-button @click="resetFilters">清空筛选</el-button>
      </template>
      <template v-else>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>新建模型
        </el-button>
        <el-button @click="openJsonImport">
          <el-icon><MagicStick /></el-icon>JSON 导入
        </el-button>
      </template>
    </EmptyState>

    <!-- 新建 / 编辑模型：走弹窗，不跳页 -->
    <ModelEditorDialog
      v-model="editorVisible"
      :model-id="editingId"
      :default-app="editorDefaultApp"
      :initial-tab="editorTab"
      @saved="onSaved"
      @deleted="onDeleted"
      @cancel="editorVisible = false"
    />

    <!-- 批量改所属应用 -->
    <DialogShell
      v-model="moveVisible"
      title="批量改所属应用"
      description="选中的模型会整体移动到目标应用，模型结构与记录都不变。"
      size="sm"
    >
      <el-select v-model="moveTargetApp" filterable placeholder="选择目标应用" class="move-select">
        <el-option v-for="a in apps" :key="a.key" :label="a.name" :value="a.key" />
      </el-select>
      <template #footer>
        <el-button @click="moveVisible = false">取消</el-button>
        <el-button type="primary" :loading="moving" @click="doBatchMove">确定移动</el-button>
      </template>
    </DialogShell>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Search, MoreFilled, Document, EditPen, Download, Delete,
  MagicStick, Grid, Menu, FolderOpened,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { entityIcon, appIcon } from '../utils/icons'
import { downloadText, safeFileName } from '../utils/download'
import { confirmAndDeleteModel } from '../utils/modelDelete'
import { tableDensityClass } from '../utils/ui'
import { filterModels, sortModels, fieldPreviewTags } from '../utils/modelFields'
import PageTitle from '../components/PageTitle.vue'
import EmptyState from '../components/EmptyState.vue'
import DialogShell from '../components/DialogShell.vue'
import ModelEditorDialog from '../components/ModelEditorDialog.vue'

const router = useRouter()

const types = ref([])
const apps = ref([])
const relDefs = ref([])
const search = ref('')
const appFilter = ref('all')
const fillFilter = ref('all')
const sortBy = ref('default')
const viewMode = ref('card')
const selectedIds = ref([])
const searchRef = ref(null)

// 字段预览：列表接口只给字段数，字段本身要逐个模型取。
// 这里做一层缓存 + 限并发，避免一屏模型同时打十几个请求把后端打懵。
const fieldCache = reactive({})
const pendingIds = new Set()

const filtered = computed(() => filterModels(types.value, {
  app: appFilter.value,
  keyword: search.value,
  fill: fillFilter.value,
}))

const visible = computed(() => sortModels(filtered.value, sortBy.value))

const hasFilter = computed(() =>
  !!search.value.trim() || appFilter.value !== 'all' || fillFilter.value !== 'all')

function appName(key) {
  const a = apps.value.find(x => x.key === key)
  return a ? a.name : (key || '未分组')
}

function previewTags(t) {
  const fields = fieldCache[t.id]
  if (!fields) return []
  return fieldPreviewTags(fields, 4)
}

function restFieldCount(t) {
  return Math.max(0, (t.field_count || 0) - previewTags(t).length)
}

/** 该模型参与的关联定义条数：删除会一起带走，得先告诉用户 */
function relationCount(typeId) {
  return relDefs.value.filter(
    d => d.source_type_id === typeId || d.target_type_id === typeId
  ).length
}

// ---------- 载入 ----------
async function load() {
  types.value = await Api.listEntityTypes()
  if (!apps.value.length) {
    apps.value = await Api.listApps()
  }
  // 关联定义的失败不影响主列表，单独兜住
  try {
    relDefs.value = await Api.listRelationDefs()
  } catch (e) {
    relDefs.value = []
  }
}

onMounted(load)

/** 拉取可见模型的字段（限并发 4），只补没缓存过的 */
async function loadFieldPreviews(list) {
  const targets = list.filter(t => t.id != null && !fieldCache[t.id] && !pendingIds.has(t.id))
  if (!targets.length) return
  targets.forEach(t => pendingIds.add(t.id))
  const queue = [...targets]
  const workers = Array.from({ length: Math.min(4, queue.length) }, async () => {
    while (queue.length) {
      const t = queue.shift()
      try {
        const full = await Api.getEntityType(t.id)
        fieldCache[t.id] = full?.fields || []
      } catch (e) {
        // 取不到就记成空：不让失败的模型每渲染一次就重试一次
        fieldCache[t.id] = []
      } finally {
        pendingIds.delete(t.id)
      }
    }
  })
  await Promise.all(workers)
}

watch(visible, (list) => { loadFieldPreviews(list) }, { immediate: true })

// ---------- 勾选 ----------
function isSelected(id) {
  return selectedIds.value.includes(id)
}

function toggleSelect(id, checked) {
  const s = new Set(selectedIds.value)
  if (checked) s.add(id)
  else s.delete(id)
  selectedIds.value = [...s]
}

const allSelected = computed(() =>
  visible.value.length > 0 && visible.value.every(t => isSelected(t.id)))
const someSelected = computed(() =>
  selectedIds.value.length > 0 && !allSelected.value)

function toggleSelectAll(checked) {
  if (checked) {
    selectedIds.value = [...new Set([...selectedIds.value, ...visible.value.map(t => t.id)])]
  } else {
    const ids = new Set(visible.value.map(t => t.id))
    selectedIds.value = selectedIds.value.filter(id => !ids.has(id))
  }
}

function clearSelection() {
  selectedIds.value = []
}

function resetFilters() {
  search.value = ''
  appFilter.value = 'all'
  fillFilter.value = 'all'
}

// ---------- 弹窗 ----------
const editorVisible = ref(false)
const editingId = ref(null)
const editorTab = ref('visual')
const editorDefaultApp = computed(() => (appFilter.value === 'all' ? '' : appFilter.value))

function openCreate() {
  editingId.value = null
  editorTab.value = 'visual'
  editorVisible.value = true
}

/** JSON 导入入口：直接落在 JSON 页签，并预填一份能跑的示例 */
function openJsonImport() {
  editingId.value = null
  editorTab.value = 'json'
  editorVisible.value = true
}

function openEdit(t) {
  editingId.value = t.id
  editorTab.value = 'visual'
  editorVisible.value = true
}

/** 保存成功：原地刷新列表，不跳页 */
async function onSaved() {
  editorVisible.value = false
  if (editingId.value) delete fieldCache[editingId.value]
  await load()
}

async function onDeleted() {
  const id = editingId.value
  editorVisible.value = false
  if (id) delete fieldCache[id]
  selectedIds.value = selectedIds.value.filter(x => x !== id)
  await load()
}

// ---------- 卡片操作 ----------
function goRecords(t) {
  router.push(`/records/${t.id}`)
}

function onCardCommand(cmd, t) {
  if (cmd === 'records') return goRecords(t)
  if (cmd === 'edit') return openEdit(t)
  if (cmd === 'export') return exportModel(t)
  if (cmd === 'delete') return removeModel(t)
}

/** 导出模型定义（不含记录）——删除前的「留个底」 */
async function exportModel(t) {
  try {
    const r = await Api.exportEntityType(t.id)
    downloadText(`${safeFileName(t.key)}.model.json`,
      r.json || JSON.stringify(r.model, null, 2))
    ElMessage.success(`已导出「${t.name}」的模型定义`)
  } catch (e) {
    // 拦截器已提示
  }
}

/** 删除单个模型：影响范围（字段数 / 记录数 / 关联数）由 modelDelete 统一提示 */
async function removeModel(t) {
  const ok = await confirmAndDeleteModel({ ...t, relation_count: relationCount(t.id) })
  if (ok) {
    delete fieldCache[t.id]
    selectedIds.value = selectedIds.value.filter(id => id !== t.id)
    await load()
  }
}

// ---------- 批量操作 ----------
const moveVisible = ref(false)
const moveTargetApp = ref('')
const moving = ref(false)
const exporting = ref(false)

function openBatchMove() {
  moveTargetApp.value = ''
  moveVisible.value = true
}

async function doBatchMove() {
  if (!moveTargetApp.value) {
    ElMessage.warning('请选择目标应用')
    return
  }
  moving.value = true
  try {
    let ok = 0
    for (const id of selectedIds.value) {
      try {
        // 改应用的接口要整份模型定义，所以先取全量再回写
        const full = await Api.getEntityType(id)
        await Api.updateEntityType(id, {
          key: full.key,
          name: full.name,
          icon: full.icon,
          description: full.description,
          app: moveTargetApp.value,
          order: full.order,
          fields: (full.fields || []).map((f, i) => ({
            key: f.key,
            name: f.name,
            type: f.type,
            required: !!f.required,
            options: f.options || {},
            order: i + 1,
          })),
        })
        ok++
      } catch (e) {
        // 拦截器已提示；单个失败不打断整批
      }
    }
    ElMessage.success(`已把 ${ok} 个模型移到「${appName(moveTargetApp.value)}」`)
    moveVisible.value = false
    await load()
  } finally {
    moving.value = false
  }
}

/** 批量导出：合成一个文件，避免浏览器拦下连续多次下载 */
async function batchExport() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  exporting.value = true
  try {
    const models = []
    for (const id of ids) {
      try {
        const r = await Api.exportEntityType(id)
        models.push(r.json ? JSON.parse(r.json) : r.model)
      } catch (e) {
        // 拦截器已提示
      }
    }
    if (!models.length) {
      ElMessage.warning('没有可导出的模型')
      return
    }
    downloadText(`models-${new Date().toISOString().slice(0, 10)}.json`,
      JSON.stringify({ exported_at: new Date().toISOString(), models }, null, 2))
    ElMessage.success(`已导出 ${models.length} 个模型的定义`)
  } finally {
    exporting.value = false
  }
}

/** 批量删除：先说清影响范围，再让用户敲一个字确认 */
async function batchDelete() {
  const models = types.value.filter(t => selectedIds.value.includes(t.id))
  if (!models.length) return
  const fieldTotal = models.reduce((s, m) => s + (m.field_count || 0), 0)
  const recordTotal = models.reduce((s, m) => s + (m.record_count || 0), 0)
  const lines = [
    `即将把 <b>${models.length}</b> 个数据模型移入回收站。`,
    `它们连同 <b>${fieldTotal}</b> 个字段定义、<b>${recordTotal}</b> 条记录会一起移入回收站，`,
    '随时可在「系统管理 → 回收站」恢复。',
    '<div class="md-del-confirm">请输入「删除」确认：</div>',
  ].join('<br>')
  try {
    await ElMessageBox.prompt(lines, '批量删除数据模型', {
      type: 'warning',
      dangerouslyUseHTMLString: true,
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
      inputPlaceholder: '删除',
      inputValidator: v => (v || '').trim() === '删除' || '请输入「删除」',
      inputErrorMessage: '请输入「删除」',
    })
  } catch {
    return
  }
  let ok = 0
  for (const m of models) {
    try {
      await Api.deleteEntityType(m.id)
      delete fieldCache[m.id]
      ok++
    } catch (e) {
      // 拦截器已提示
    }
  }
  ElMessage.success(`已把 ${ok} 个模型移入回收站`)
  clearSelection()
  await load()
}

// ---------- 键盘流 ----------
function onKeydown(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const tag = (e.target?.tagName || '').toLowerCase()
  const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable
  if (typing) return
  // 弹窗打开时别抢快捷键：Esc 交给弹窗自己处理
  if (editorVisible.value || moveVisible.value) return
  if (e.key === '/') {
    e.preventDefault()
    searchRef.value?.focus()
  } else if (e.key === 'n' || e.key === 'N') {
    e.preventDefault()
    openCreate()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
/* ---------- 工具条 ---------- */
.tb-search { width: 320px; }
.tb-select { width: 150px; }
.tb-option { display: inline-flex; align-items: center; gap: 6px; }
.tb-view { flex-shrink: 0; }
.toolbar-count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* ---------- 批量操作条 ---------- */
.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
  border-radius: var(--radius-lg);
}
.batch-count {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-primary);
}
.batch-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ---------- 卡片 ---------- */
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-3);
}
.model-card {
  background: var(--bg-card);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: border-color var(--duration) var(--ease-out),
              box-shadow var(--duration) var(--ease-out),
              transform var(--duration) var(--ease-out);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.model-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
  border-color: var(--primary-200);
}
/* 焦点环交给设计系统的全局规则，这里只保证不被自己的样式盖掉 */
.model-card:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.model-card.is-selected {
  border-color: var(--primary);
  background: var(--primary-bg);
}
.mdl-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.mdl-check { margin-top: 10px; }
.mdl-icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.mdl-titles { flex: 1; min-width: 0; }
.mdl-name {
  font-size: var(--text-lg);
  font-weight: 650;
  color: var(--text-primary);
  letter-spacing: -0.25px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mdl-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mdl-menu { flex-shrink: 0; }
.model-menu-btn {
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all var(--duration-fast) var(--ease-out);
}
.model-menu-btn:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
}
.mdl-desc {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--text-secondary);
  min-height: 38px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.mdl-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-height: 26px;
}
.mdl-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: 500;
}
.mdl-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.mdl-app {
  background: var(--bg-subtle);
  border-radius: var(--radius-full);
  padding: 2px 9px;
  color: var(--text-secondary);
}

/* 字段类型标签：像 Airtable 那样露出字段名和它的类型 */
.field-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 190px;
  padding: 2px 8px 2px 3px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.field-tag-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-xs);
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.field-tag-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-weight: 600;
}
.field-tag-type {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.field-tag.is-rest {
  color: var(--text-secondary);
  font-weight: 600;
}
.field-tag-empty {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

/* ---------- 表格 ---------- */
.cell-model { display: flex; align-items: center; gap: var(--space-2); }
.cell-model-icon {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.cell-model-text { display: flex; flex-direction: column; min-width: 0; }
.cell-model-name {
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-model-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.cell-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.cell-btn { color: var(--text-secondary); }

/* ---------- 批量改应用 ---------- */
.move-select { width: 100%; }
</style>
