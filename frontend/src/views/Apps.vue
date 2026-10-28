<template>
  <div class="page apps-page">
    <PageTitle
      title="应用中心"
      subtitle="每个应用是一组数据模型的容器 · 可从模板一键生成"
      icon-key="Grid"
    >
      <el-button @click="openTemplateLibrary('create')">
        <el-icon><Files /></el-icon>模板库
      </el-button>
      <el-button type="primary" :disabled="!canManage" @click="openCreate">
        <el-icon><Plus /></el-icon>新建应用
      </el-button>
    </PageTitle>

    <!-- ============ 工具条 ============ -->
    <div class="toolbar apps-toolbar">
      <el-input
        ref="searchInput"
        v-model="keyword"
        class="tb-search"
        placeholder="搜索名称 / 描述 / Key"
        clearable
        :prefix-icon="Search"
      >
        <template #suffix><kbd class="tb-kbd">/</kbd></template>
      </el-input>

      <el-select v-model="groupFilter" class="tb-select" placeholder="全部分组">
        <el-option :label="ALL_GROUP_LABEL" :value="ALL_GROUPS" />
        <el-option
          v-for="g in groups"
          :key="g.name"
          :label="`${g.name}（${g.count}）`"
          :value="g.name"
        />
      </el-select>

      <el-select v-model="sortKey" class="tb-select" placeholder="排序方式">
        <el-option
          v-for="o in SORT_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>

      <div class="tb-spacer" />

      <el-radio-group v-model="viewMode" class="tb-view">
        <el-radio-button value="card">卡片</el-radio-button>
        <el-radio-button value="table">表格</el-radio-button>
      </el-radio-group>

      <el-button :type="multi ? 'primary' : 'default'" @click="toggleMulti">
        <el-icon><Select /></el-icon>{{ multi ? '退出多选' : '多选' }}
      </el-button>
    </div>

    <div class="tb-hint">
      <span v-if="sortKey === 'updated' && !hasUpdatedAt">
        接口暂未返回应用更新时间，「最近更新」当前按默认顺序排列。
      </span>
      <span v-else class="tb-shortcuts">
        <kbd class="tb-kbd">/</kbd> 搜索 · <kbd class="tb-kbd">n</kbd> 新建应用 ·
        <kbd class="tb-kbd">Esc</kbd> 退出多选
      </span>
    </div>

    <!-- ============ 批量操作条 ============ -->
    <div v-if="multi" class="batch-bar">
      <span class="batch-count">已选 {{ selectedKeys.length }} 个应用</span>
      <el-button @click="selectAllVisible">全选当前结果</el-button>
      <el-button @click="clearSelection">取消选择</el-button>

      <div class="tb-spacer" />

      <el-popover placement="bottom-end" :width="280" trigger="click">
        <template #reference>
          <el-button><el-icon><Folder /></el-icon>改分组</el-button>
        </template>
        <div class="grp-pop">
          <div class="grp-pop-title">把选中的应用移到</div>
          <div class="grp-pop-list">
            <button
              v-for="g in groups"
              :key="g.name"
              type="button"
              class="grp-pop-item"
              @click="assignSelected(g.name)"
            >
              {{ g.name }}<span class="grp-pop-count">{{ g.count }}</span>
            </button>
          </div>
          <div class="grp-pop-new">
            <el-input
              v-model="newGroupName"
              size="small"
              placeholder="新分组名称"
              @keyup.enter="assignSelected(newGroupName)"
            />
            <el-button size="small" type="primary" @click="assignSelected(newGroupName)">
              确定
            </el-button>
          </div>
        </div>
      </el-popover>

      <el-dropdown trigger="click" @command="exportSelected">
        <el-button><el-icon><Download /></el-icon>导出</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="csv">导出为 CSV</el-dropdown-item>
            <el-dropdown-item command="json">导出为 JSON</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-button type="danger" plain :disabled="!selectedKeys.length" @click="removeSelected">
        <el-icon><Delete /></el-icon>删除
      </el-button>
    </div>

    <!-- ============ 主体 ============ -->
    <!-- 加载骨架：先给「像样的骨架」，别让页面在等接口时是一片空白 -->
    <div v-if="loading" class="app-grid">
      <div v-for="i in 6" :key="i" class="skeleton-card">
        <el-skeleton :rows="3" animated />
      </div>
    </div>

    <!-- 降级：没权限 / 接口不可用 -->
    <div v-else-if="loadError" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><Lock /></el-icon></div>
      <div class="empty-title">暂时看不到应用列表</div>
      <div class="empty-desc">{{ loadError }}</div>
      <div class="empty-actions">
        <el-button @click="load">重试</el-button>
      </div>
    </div>

    <!-- 第一次使用：引导 -->
    <div v-else-if="!apps.length" class="onboard">
      <div class="onboard-icon"><el-icon :size="26"><Compass /></el-icon></div>
      <div class="onboard-body">
        <div class="onboard-title">三步开始使用</div>
        <div class="onboard-steps">
          <div class="onboard-step"><b>1</b> 新建应用（选业务模板，自动生成数据模型）</div>
          <div class="onboard-step"><b>2</b> 在应用下录入业务记录</div>
          <div class="onboard-step"><b>3</b> 把关键记录「沉淀为笔记」接入知识库</div>
        </div>
      </div>
      <el-button type="primary" :disabled="!canManage" @click="openCreate">立即新建</el-button>
    </div>

    <!-- 筛选后没有结果 -->
    <div v-else-if="!visibleApps.length" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><Search /></el-icon></div>
      <div class="empty-title">没有匹配的应用</div>
      <div class="empty-desc">换个关键词，或把分组筛选清掉再看看。</div>
      <div class="empty-actions">
        <el-button @click="clearFilters">清除筛选</el-button>
      </div>
    </div>

    <template v-else>
      <!-- 卡片视图 -->
      <div v-if="viewMode === 'card'" class="app-grid">
        <AppCard
          v-for="a in visibleApps"
          :key="a.key"
          :app="a"
          :models="modelsOf(a)"
          :group="groupOf(a)"
          :selected="selectedKeys.includes(a.key)"
          :multi="multi"
          :can-manage="canManage"
          @open="openApp"
          @toggle="toggleSelect"
          @new-model="newModel"
          @add-record="addRecord"
          @view-relations="openPreview"
          @edit="openEdit"
          @remove="removeApp"
        />

        <!-- 新建占位卡：用真按钮，键盘能到 -->
        <button v-if="!multi" type="button" class="add-card" @click="openCreate">
          <span class="add-icon"><el-icon :size="24"><Plus /></el-icon></span>
          <span class="add-title">新建应用</span>
          <span class="add-desc">选模板自动生成模型与关联</span>
        </button>
      </div>

      <!-- 表格视图 -->
      <div v-else class="table-wrap card">
        <el-table
          :data="visibleApps"
          class="data-table"
          row-key="key"
          @row-click="openApp"
        >
          <el-table-column v-if="multi" width="52">
            <template #header>
              <el-checkbox
                :model-value="allVisibleSelected"
                :indeterminate="someVisibleSelected"
                aria-label="全选当前结果"
                @change="toggleSelectAll"
              />
            </template>
            <template #default="{ row }">
              <el-checkbox
                :model-value="selectedKeys.includes(row.key)"
                :aria-label="`选中应用 ${row.name}`"
                @click.stop
                @change="toggleSelect(row)"
              />
            </template>
          </el-table-column>

          <el-table-column label="应用" min-width="220">
            <template #default="{ row }">
              <div class="cell-app">
                <div class="cell-app-icon">
                  <el-icon :size="16"><component :is="iconOf(row)" /></el-icon>
                </div>
                <div class="cell-app-text">
                  <div class="cell-app-name">{{ row.name }}</div>
                  <div class="cell-app-key">{{ row.key }}</div>
                </div>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="分组" width="130">
            <template #default="{ row }">
              <span v-if="groupOf(row) && groupOf(row) !== DEFAULT_GROUP" class="cell-group">
                {{ groupOf(row) }}
              </span>
              <span v-else class="cell-empty">未分组</span>
            </template>
          </el-table-column>

          <el-table-column label="模型" width="90" align="right">
            <template #default="{ row }">
              <span class="cell-number">{{ row.entity_count || 0 }}</span>
            </template>
          </el-table-column>

          <el-table-column label="记录" width="90" align="right">
            <template #default="{ row }">
              <span class="cell-number">{{ row.record_count || 0 }}</span>
            </template>
          </el-table-column>

          <el-table-column label="说明" min-width="200">
            <template #default="{ row }">
              <span class="cell-text cell-line">{{ row.description || '暂无说明' }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <div class="cell-actions" @click.stop>
                <el-tooltip content="打开应用" placement="top" :show-after="400">
                  <el-button class="tb-act-btn" text @click="openApp(row)">
                    <el-icon><View /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip content="新建模型" placement="top" :show-after="400">
                  <el-button class="tb-act-btn" text :disabled="!canManage" @click="newModel(row)">
                    <el-icon><Plus /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip content="编辑应用" placement="top" :show-after="400">
                  <el-button class="tb-act-btn" text :disabled="!canManage" @click="openEdit(row)">
                    <el-icon><Edit /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip content="删除应用" placement="top" :show-after="400">
                  <el-button class="tb-act-btn is-danger" text :disabled="!canManage" @click="removeApp(row)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <!-- ============ 应用快速预览（抽屉；点应用本体是进独立页） ============ -->
    <AppDetail
      v-model="detailOpen"
      :app="detailApp"
      :models="detailModels"
      :group="detailApp ? groupOf(detailApp) : ''"
      :can-manage="canManage"
      @edit="openEdit"
    />

    <!-- ============ 模板库（独立抽屉） ============ -->
    <TemplateLibrary
      v-model="templateOpen"
      :mode="templateMode"
      :existing-keys="appKeys"
      @pick="pickTemplate"
      @created="onTemplateCreated"
    />

    <!-- ============ 新建 / 编辑应用 ============ -->
    <el-dialog
      v-model="dialogOpen"
      :title="editingApp ? `编辑应用 · ${editingApp.name}` : '新建应用'"
      :width="editingApp ? '720px' : '860px'"
      destroy-on-close
      class="kb-dialog"
      :close-on-click-modal="false"
    >
      <div class="dialog-summary">
        <el-icon><Grid /></el-icon>
        <div>
          应用是数据模型的分组容器。选模板后系统会自动生成该业务场景所需的
          <b>数据模型、字段与关联关系</b>；也可以用一句话让 AI 先出草稿，确认后再建。
        </div>
      </div>

      <!-- 新建入口切换：AI 生成 / 选模板（编辑时不需要） -->
      <div v-if="!editingApp && canAi" class="entry-switch">
        <el-radio-group v-model="createMode">
          <el-radio-button value="ai">AI 生成</el-radio-button>
          <el-radio-button value="template">选模板</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 自然语言入口（仅新建时） -->
      <div v-if="!editingApp && canAi && createMode === 'ai'" class="ai-section">
        <div class="ai-input-row">
          <el-input
            v-model="aiPrompt"
            type="textarea"
            :rows="2"
            :disabled="aiLoading"
            placeholder="用一句话描述你要的应用，AI 帮你生成数据模型"
            @keyup.ctrl.enter="generateDraft"
          />
          <el-button type="primary" :loading="aiLoading" @click="generateDraft">
            生成
          </el-button>
        </div>

        <!-- AI 没配 / 解析失败等提示：说人话，不甩原始异常 -->
        <el-alert
          v-if="aiNotice"
          :title="aiNotice"
          type="info"
          :closable="false"
          show-icon
          class="ai-alert"
        />
        <el-alert
          v-if="aiWarnings.length"
          :title="`已自动修正 ${aiWarnings.length} 处不合法的地方：${aiWarnings.slice(0, 2).join('；')}`"
          type="warning"
          :closable="false"
          show-icon
          class="ai-alert"
        />

        <!-- 审阅步骤：模型 / 字段 / 关联清单 -->
        <div v-if="aiDraft" class="ai-review">
          <div class="ai-review-head">
            <span>
              AI 生成草稿：{{ aiDraft.types.length }} 个模型 ·
              {{ draftFieldCount }} 个字段 · {{ aiDraft.relations.length }} 条关联
              <span class="apps-hint">应用名称与 Key 在下方修改</span>
            </span>
            <el-button text @click="aiDraft = null">放弃草稿</el-button>
          </div>

          <div v-for="t in aiDraft.types" :key="t.key" class="draft-type">
            <div class="draft-type-head">
              <el-input v-model="t.name" class="draft-type-name" />
              <span class="draft-type-key">{{ t.key }}</span>
              <el-button type="danger" text @click="removeType(t)">删除模型</el-button>
            </div>
            <div class="draft-fields">
              <div
                v-for="(f, fi) in t.fields" :key="`${t.key}_${fi}`" class="draft-field"
              >
                <el-input v-model="f.name" class="draft-f-name" placeholder="字段名" />
                <el-select v-model="f.type" class="draft-f-type">
                  <el-option
                    v-for="ft in FIELD_TYPE_OPTIONS" :key="ft" :label="ft" :value="ft"
                  />
                </el-select>
                <el-input
                  v-if="f.type === 'select' || f.type === 'multiselect'"
                  v-model="f._choices" class="draft-f-choices" placeholder="选项，逗号分隔"
                  @change="syncChoices(f)"
                />
                <el-checkbox v-model="f.required">必填</el-checkbox>
                <el-button type="danger" text @click="t.fields.splice(fi, 1)">删</el-button>
              </div>
              <el-button text @click="addField(t)">+ 添加字段</el-button>
            </div>
          </div>

          <div v-if="aiDraft.relations.length" class="draft-relations">
            <span class="draft-rel-title">关联</span>
            <el-tag
              v-for="r in aiDraft.relations"
              :key="r.key"
              closable
              @close="removeRelation(r)"
            >{{ r.name }}</el-tag>
          </div>
        </div>
      </div>

      <!-- 模板选择（仅新建时） -->
      <div v-if="!editingApp && (createMode === 'template' || !canAi)" class="tpl-section">
        <div class="form-section-title">
          选择模板
          <span v-if="tplMeta" class="tpl-meta">
            将生成 {{ tplMeta.type_count }} 个模型 · {{ tplMeta.field_count }} 个字段 · {{ tplMeta.relation_count }} 条关联
          </span>
        </div>
        <div v-if="!canAi" class="apps-hint apps-hint-block">
          当前账号没有「AI」功能位，不能用一句话生成模型，可直接选模板创建
        </div>
        <div class="tpl-grid">
          <div
            v-for="t in templates"
            :key="t.key"
            class="tpl-card"
            :class="{ active: form.template === t.key }"
            role="button"
            tabindex="0"
            @click="pickTemplate(t)"
            @keydown.enter.prevent="pickTemplate(t)"
            @keydown.space.prevent="pickTemplate(t)"
          >
            <div class="tpl-icon"><el-icon :size="20"><component :is="t.icon" /></el-icon></div>
            <div class="tpl-body">
              <div class="tpl-name">{{ t.name }}</div>
              <div class="tpl-desc">{{ t.description }}</div>
              <div v-if="t.types.length" class="tpl-tags">
                <span v-for="x in t.types" :key="x.key" class="tpl-tag">{{ x.name }}</span>
              </div>
            </div>
          </div>
        </div>
        <el-button text class="tpl-open-lib" @click="openTemplateLibrary('pick')">
          <el-icon><Files /></el-icon>在模板库中查看每个模板会生成哪些字段
        </el-button>
      </div>

      <el-form :model="form" label-width="76px" label-position="right">
        <el-form-item v-if="!editingApp" label="Key">
          <el-input v-model="form.key" placeholder="英文唯一标识，如 crm" />
          <div class="apps-hint">
            创建后不可修改。模板会以此为前缀生成模型 Key，例如 <code>{{ form.key || 'crm' }}_customer</code>
          </div>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：CRM / 库存管理" />
        </el-form-item>
        <el-form-item label="图标">
          <div class="icon-picker">
            <button
              v-for="ic in ICON_CHOICES"
              :key="ic"
              type="button"
              class="icon-choice"
              :class="{ active: form.icon === ic }"
              :aria-label="`图标 ${ic}`"
              @click="form.icon = ic"
            >
              <el-icon :size="18"><component :is="ic" /></el-icon>
            </button>
          </div>
        </el-form-item>
        <el-form-item label="分组">
          <el-select
            v-model="form.group"
            filterable
            allow-create
            default-first-option
            placeholder="未分组"
            class="group-select"
          >
            <el-option label="未分组" value="" />
            <el-option v-for="g in groups" :key="g.name" :label="g.name" :value="g.name" />
          </el-select>
          <div class="apps-hint">分组用于整理应用，目前保存在本机浏览器中</div>
        </el-form-item>
        <el-form-item label="说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="一句话描述这个应用的用途…"
          />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.order" :min="0" />
          <span class="apps-hint apps-hint-inline">数值越小越靠前</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          {{ saveLabel }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Compass, Delete, Download, Edit, Files, Folder, Grid, Lock, Plus, Search, Select, View,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { APP_ICON_CHOICES } from '../utils/icons'
import { useAuthStore } from '../stores/auth'
import { downloadText, safeFileName } from '../utils/download'
import {
  ALL_GROUPS, DEFAULT_GROUP, GROUP_STORE_KEY, SORT_OPTIONS,
  appsToCsv, appsToJson, assignGroup, collectGroups, filterApps,
  parseGroupMap, resolveAppIcon, resolveGroup, serializeGroupMap, sortApps,
} from '../utils/apps'
import PageTitle from '../components/PageTitle.vue'
import AppCard from '../components/AppCard.vue'
import AppDetail from './AppDetail.vue'
import TemplateLibrary from '../components/TemplateLibrary.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const apps = ref([])
const allTypes = ref([])
const templates = ref([])
const loading = ref(true)
const loadError = ref('')

const keyword = ref('')
const groupFilter = ref(ALL_GROUPS)
const sortKey = ref('updated')
const viewMode = ref('card')
const multi = ref(false)
const selectedKeys = ref([])
const groupMap = ref({})

const dialogOpen = ref(false)
const editingApp = ref(null)
const saving = ref(false)

const detailOpen = ref(false)
const detailApp = ref(null)

const templateOpen = ref(false)
const templateMode = ref('create')
const newGroupName = ref('')

const searchInput = ref(null)

// AI 相关状态：草稿只存在前端，确认之前一个字都不落库
const createMode = ref('ai')
const aiPrompt = ref('')
const aiLoading = ref(false)
const aiNotice = ref('')
const aiWarnings = ref([])
const aiDraft = ref(null)

const ICON_CHOICES = APP_ICON_CHOICES
const ALL_GROUP_LABEL = '全部分组'

// 字段类型可选集：与后端 model_json.FIELD_TYPES 一致
const FIELD_TYPE_OPTIONS = [
  'text', 'textarea', 'richtext', 'number', 'date', 'datetime',
  'select', 'multiselect', 'boolean', 'file', 'image', 'reference',
]

// 「ai」是独立授权位：没权限的人直接看不到 AI 入口，省得点了报 403
const canAi = computed(() => auth.can('ai'))
// 建应用等于批量建模，跟数据模型的管理权限走同一把钥匙
const canManage = computed(() => auth.can('model_manage'))

const form = reactive({
  key: '', name: '', icon: 'Grid', description: '', order: 0, template: 'blank', group: '',
})

const appKeys = computed(() => apps.value.map(a => a.key))

const modelsByApp = computed(() => {
  const map = new Map()
  for (const t of allTypes.value) {
    if (!map.has(t.app)) map.set(t.app, [])
    map.get(t.app).push(t)
  }
  return map
})

const groups = computed(() => collectGroups(apps.value, groupMap.value))

const visibleApps = computed(() => sortApps(
  filterApps(apps.value, { keyword: keyword.value, group: groupFilter.value, groupMap: groupMap.value }),
  sortKey.value,
))

// 接口还没给 updated_at，排序里的「最近更新」就退化成默认顺序，这里如实说明
const hasUpdatedAt = computed(() => apps.value.some(a => !!a.updated_at))

const tplMeta = computed(() => templates.value.find(t => t.key === form.template) || null)

const draftFieldCount = computed(() =>
  (aiDraft.value?.types || []).reduce((n, t) => n + (t.fields?.length || 0), 0))

const detailModels = computed(() =>
  detailApp.value ? (modelsByApp.value.get(detailApp.value.key) || []) : [])

const allVisibleSelected = computed(() =>
  visibleApps.value.length > 0 && visibleApps.value.every(a => selectedKeys.value.includes(a.key)))
const someVisibleSelected = computed(() =>
  visibleApps.value.some(a => selectedKeys.value.includes(a.key)) && !allVisibleSelected.value)

// 按钮文案跟着当前入口走，别让用户以为点的是别的流程
const saveLabel = computed(() => {
  if (editingApp.value) return '保存修改'
  if (createMode.value === 'ai' && aiDraft.value?.types?.length) return '按草稿创建'
  if (form.template && form.template !== 'blank') return '按模板创建'
  return '创建应用'
})

function modelsOf(app) {
  return modelsByApp.value.get(app.key) || []
}

function groupOf(app) {
  return resolveGroup(app, groupMap.value)
}

function iconOf(app) {
  return resolveAppIcon(app, ICON_CHOICES)
}

// ============ 数据加载 ============

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    // 三个接口并发：模型一次拉全量，按 app 分组缓存住，
    // 卡片上的「录入记录」、抽屉里的模型列表就都不用再单独请求
    const [list, types] = await Promise.all([
      Api.listApps(),
      Api.listEntityTypes(),
    ])
    apps.value = list || []
    allTypes.value = types || []
  } catch (e) {
    const status = e?.response?.status
    loadError.value = status === 403
      ? '当前账号没有查看应用列表的权限，请联系管理员调整角色。'
      : '应用列表加载失败，请检查后端服务是否正常。'
    apps.value = []
    allTypes.value = []
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  try {
    templates.value = await Api.listAppTemplates()
  } catch (e) {
    templates.value = [{ key: 'blank', name: '空白应用', icon: 'Grid',
                         description: '不预置任何模型', types: [],
                         type_count: 0, field_count: 0, relation_count: 0 }]
  }
}

// ============ 本地分组 ============

function loadGroups() {
  try {
    groupMap.value = parseGroupMap(localStorage.getItem(GROUP_STORE_KEY))
  } catch {
    groupMap.value = {}
  }
}

function saveGroups() {
  try {
    localStorage.setItem(GROUP_STORE_KEY, serializeGroupMap(groupMap.value))
  } catch { /* 隐私模式下写不进去也不该让页面报错 */ }
}

function assignSelected(group) {
  const name = String(group || '').trim()
  if (!selectedKeys.value.length) return
  groupMap.value = assignGroup(groupMap.value, selectedKeys.value, name)
  saveGroups()
  newGroupName.value = ''
  ElMessage.success(name ? `已把 ${selectedKeys.value.length} 个应用移到「${name}」` : '已移出分组')
}

// ============ 详情 / 快捷动作 ============

/**
 * 点应用 → 进应用独立页
 * 为什么不留在抽屉里：应用页是「基于数据模型管理业务数据」的地方，
 * 记录、模型、统计都要占地方，抽屉塞不下也不该塞。
 */
function openApp(app) {
  if (!app) return
  router.push(`/apps/${app.key}`)
}

/** 快速预览：不离开列表就能瞄一眼模型与关联（抽屉） */
function openPreview(app) {
  if (!app) return
  detailApp.value = app
  detailOpen.value = true
}

function newModel(app) {
  router.push({ path: '/types/new', query: { app: app.key } })
}

function addRecord(app, model) {
  if (!model) {
    ElMessage.info('这个应用还没有数据模型，先新建一个才能录入')
    return
  }
  router.push(`/records/${model.id}`)
}

// ============ 多选与批量 ============

function toggleMulti() {
  multi.value = !multi.value
  if (!multi.value) selectedKeys.value = []
}

function toggleSelect(app) {
  const k = app.key
  const next = new Set(selectedKeys.value)
  if (next.has(k)) next.delete(k)
  else next.add(k)
  selectedKeys.value = [...next]
}

function toggleSelectAll() {
  const next = new Set(selectedKeys.value)
  const all = allVisibleSelected.value
  for (const a of visibleApps.value) {
    if (all) next.delete(a.key)
    else next.add(a.key)
  }
  selectedKeys.value = [...next]
}

function selectAllVisible() {
  const next = new Set(selectedKeys.value)
  for (const a of visibleApps.value) next.add(a.key)
  selectedKeys.value = [...next]
}

function clearSelection() {
  selectedKeys.value = []
}

function clearFilters() {
  keyword.value = ''
  groupFilter.value = ALL_GROUPS
  sortKey.value = 'updated'
}

function selectedApps() {
  return apps.value.filter(a => selectedKeys.value.includes(a.key))
}

function exportSelected(format) {
  const list = selectedApps()
  if (!list.length) {
    ElMessage.warning('先选中要导出的应用')
    return
  }
  const stamp = new Date().toISOString().slice(0, 10)
  if (format === 'csv') {
    // CSV 带 BOM：Excel 打开中文才不会乱码
    downloadText(`应用清单-${stamp}.csv`, '\ufeff' + appsToCsv(list, groupMap.value), 'text/csv')
  } else {
    downloadText(`应用清单-${stamp}.json`, appsToJson(list, groupMap.value))
  }
  ElMessage.success(`已导出 ${list.length} 个应用`)
}

async function removeSelected() {
  const list = selectedApps()
  if (!list.length) return
  try {
    await ElMessageBox.confirm(
      `将删除 ${list.length} 个应用：${list.map(a => a.name).join('、')}。此操作不可撤销。`,
      '批量删除应用',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  let ok = 0
  for (const a of list) {
    // 逐个删：接口是单条删除，没有批量端点；
    // 单个失败不打断整批，最后统一汇报
    try {
      await Api.deleteApp(a.id)
      ok++
    } catch { /* 忽略单个失败 */ }
  }
  ElMessage.success(`已删除 ${ok} 个应用`)
  selectedKeys.value = []
  await load()
}

// ============ 新建 / 编辑 ============

function openCreate() {
  if (!canManage.value) {
    ElMessage.warning('当前账号没有管理数据模型的权限')
    return
  }
  editingApp.value = null
  Object.assign(form, {
    key: '', name: '', icon: 'Grid', description: '', order: apps.value.length,
    template: 'blank', group: '',
  })
  // 每次新建都从干净状态开始，别把上一次的草稿带过来
  createMode.value = canAi.value ? 'ai' : 'template'
  aiPrompt.value = ''
  aiNotice.value = ''
  aiWarnings.value = []
  aiDraft.value = null
  dialogOpen.value = true
}

function openEdit(app) {
  if (!canManage.value) {
    ElMessage.warning('当前账号没有管理数据模型的权限')
    return
  }
  editingApp.value = app
  Object.assign(form, {
    key: app.key,
    name: app.name,
    icon: iconOf(app),
    description: app.description || '',
    order: app.order || 0,
    template: 'blank',
    group: app.group ?? groupMap.value[app.key] ?? '',
  })
  dialogOpen.value = true
}

// 选中模板时，把模板风格带进表单，减少输入
function pickTemplate(t) {
  form.template = t.key
  // 模板与 AI 草稿二选一：选了模板就丢掉草稿，免得保存时走错分支
  aiDraft.value = null
  if (t.key === 'blank') return
  if (!form.name || templates.value.some(x => x.name === form.name)) form.name = t.name
  form.icon = ICON_CHOICES.includes(t.icon) ? t.icon : form.icon
  if (!form.description) form.description = t.description
  if (!form.key) form.key = t.key
}

function openTemplateLibrary(mode = 'create') {
  templateMode.value = mode
  templateOpen.value = true
}

function onTemplateCreated(r) {
  load()
  // 建完直接进新应用的应用页，省得用户自己找
  if (r?.app?.key) router.push(`/apps/${r.app.key}`)
}

// ============ AI 生成草稿 ============

// 后端返回的草稿转成前端可编辑结构：
// 选项数组在输入框里不好编辑，补一个 _choices 字符串字段来承载
function prepareDraft(r) {
  const types = (r.types || []).map(t => ({
    key: t.key,
    name: t.name,
    icon: t.icon,
    description: t.description || '',
    fields: (t.fields || []).map(f => ({
      key: f.key,
      name: f.name,
      type: f.type,
      required: !!f.required,
      options: { ...(f.options || {}) },
      help_text: f.help_text || '',
      _choices: ((f.options || {}).choices || []).join('、'),
    })),
  }))
  return {
    key: r.key || '',
    name: r.name || '',
    icon: r.icon || 'Grid',
    description: r.description || '',
    types,
    relations: (r.relations || []).map(x => ({ ...x })),
  }
}

async function generateDraft() {
  const p = (aiPrompt.value || '').trim()
  if (!p) {
    ElMessage.warning('请先描述你要的应用')
    return
  }
  aiLoading.value = true
  aiNotice.value = ''
  aiWarnings.value = []
  try {
    const r = await Api.createAppFromPrompt(p)
    aiDraft.value = prepareDraft(r)
    aiNotice.value = r.notice || ''
    aiWarnings.value = r.warnings || []
    // 草稿带出应用名 / key / 图标 / 说明，但都还能改
    if (r.name) form.name = r.name
    if (!form.key && r.key) form.key = r.key
    if (ICON_CHOICES.includes(r.icon)) form.icon = r.icon
    if (!form.description && r.description) form.description = r.description
    form.template = 'blank'          // 草稿与模板二选一
    if (!aiDraft.value.types.length) {
      ElMessage.warning('这次没生成出可用的模型，换个说法再试一次，或改用「选模板」')
    } else {
      ElMessage.success(
        `已生成 ${aiDraft.value.types.length} 个模型，确认无误后点「${saveLabel.value}」`
      )
    }
  } catch (e) {
    // 不把原始异常甩给用户：给一句能懂的话，并指个替代方案
    const detail = e?.response?.data?.detail
    aiNotice.value = detail
      ? `生成失败：${detail}`
      : '生成失败：AI 服务暂时不可用，可改用「选模板」创建，或稍后再试。'
  } finally {
    aiLoading.value = false
  }
}

function removeType(t) {
  if (!aiDraft.value) return
  // 顺手去掉指向这个模型的关联，否则界面上的关联是死的
  aiDraft.value.types = aiDraft.value.types.filter(x => x.key !== t.key)
  aiDraft.value.relations = aiDraft.value.relations.filter(
    r => r.source !== t.key && r.target !== t.key
  )
}

function removeRelation(r) {
  if (!aiDraft.value) return
  aiDraft.value.relations = aiDraft.value.relations.filter(x => x !== r)
}

function addField(t) {
  const used = new Set((t.fields || []).map(f => f.key))
  let i = 1
  while (used.has(`field_${i}`)) i++
  t.fields.push({
    key: `field_${i}`, name: '新字段', type: 'text', required: false,
    options: {}, help_text: '', _choices: '',
  })
}

function syncChoices(f) {
  f.options = f.options || {}
  f.options.choices = (f._choices || '')
    .split(/[,，、]/)
    .map(s => s.trim())
    .filter(Boolean)
}

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写应用名称')
    return
  }
  if (!editingApp.value && !form.key?.trim()) {
    ElMessage.warning('请填写 Key')
    return
  }
  if (!editingApp.value && !/^[a-zA-Z][a-zA-Z0-9_]*$/.test(form.key.trim())) {
    ElMessage.warning('Key 只能用英文字母、数字、下划线，且以字母开头')
    return
  }
  // Key 全局唯一：先在前端拦一道，别让用户白等一次请求
  if (!editingApp.value && apps.value.some(a => a.key === form.key.trim())) {
    ElMessage.warning(`应用 Key「${form.key.trim()}」已被占用，请换一个`)
    return
  }
  saving.value = true
  try {
    if (editingApp.value) {
      await Api.updateApp(editingApp.value.id, {
        name: form.name,
        icon: form.icon,
        description: form.description,
        order: form.order,
      })
      // 分组是本地概念，单独存一次
      applyLocalGroup(editingApp.value.key, form.group)
      ElMessage.success('已保存')
      dialogOpen.value = false
      await load()
    } else if (createMode.value === 'ai' && aiDraft.value?.types?.length) {
      // 按草稿创建：规格与内置模板共用同一段落库逻辑
      const r = await Api.createAppFromSpec({
        key: form.key.trim(),
        name: form.name.trim(),
        icon: form.icon,
        description: form.description,
        order: form.order,
        spec: {
          key: form.key.trim(),
          name: form.name.trim(),
          icon: form.icon,
          description: form.description,
          types: aiDraft.value.types.map(t => ({
            key: t.key,
            name: t.name,
            icon: t.icon,
            description: t.description,
            fields: t.fields.map(f => ({
              key: f.key,
              name: f.name,
              type: f.type,
              required: f.required,
              options: f.options,
              help_text: f.help_text,
            })),
          })),
          relations: aiDraft.value.relations,
        },
      })
      applyLocalGroup(r.app?.key || form.key.trim(), form.group)
      ElMessage.success(
        `已按 AI 草稿创建：${r.types?.length || 0} 个模型 · ${r.relations?.length || 0} 条关联`
      )
      dialogOpen.value = false
      await load()
      if (r.app?.key) router.push(`/apps/${r.app.key}`)
    } else if (form.template && form.template !== 'blank') {
      const r = await Api.createAppFromTemplate({ ...form })
      applyLocalGroup(r.app?.key || form.key.trim(), form.group)
      ElMessage.success(
        `已按「${tplMeta.value?.name || form.template}」创建：` +
        `${r.types?.length || 0} 个模型 · ${r.relations?.length || 0} 条关联`
      )
      dialogOpen.value = false
      await load()
      if (r.app?.key) router.push(`/apps/${r.app.key}`)
    } else {
      const r = await Api.createApp({
        key: form.key, name: form.name, icon: form.icon,
        description: form.description, order: form.order,
      })
      applyLocalGroup(r?.key || form.key, form.group)
      ElMessage.success('已创建')
      dialogOpen.value = false
      await load()
    }
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}

function applyLocalGroup(key, group) {
  if (!key) return
  const name = String(group || '').trim()
  const next = assignGroup(groupMap.value, [key], name)
  const changed = next[key] !== groupMap.value[key]
  groupMap.value = next
  if (changed) saveGroups()
}

async function removeApp(app) {
  try {
    await ElMessageBox.confirm(
      `删除应用「${app.name}」后不可撤销。该应用下的数据模型与记录会保留，但将失去分组归属。`,
      '删除应用',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteApp(app.id)
    ElMessage.success('已删除')
    selectedKeys.value = selectedKeys.value.filter(k => k !== app.key)
    await load()
  } catch (e) {
    /* 取消 */
  }
}

// ============ 键盘流 ============

// 判断焦点是不是在输入区：输入框里敲 n / / 不该触发快捷键
function isTyping(e) {
  const t = e.target
  if (!t) return false
  if (t.isContentEditable) return true
  const tag = (t.tagName || '').toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select'
}

function onKeydown(e) {
  // 弹层打开时交给弹层自己处理 Esc（el-dialog / el-drawer 自带关闭）
  if (e.key === 'Escape') {
    if (document.querySelector('.el-overlay')) return
    if (multi.value) {
      multi.value = false
      selectedKeys.value = []
    }
    return
  }
  if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key === '/') {
    e.preventDefault()
    searchInput.value?.focus()
  } else if (e.key === 'n' || e.key === 'N') {
    e.preventDefault()
    openCreate()
  }
}

// ============ 生命周期 ============

onMounted(() => {
  load()
  loadTemplates()
  loadGroups()
  document.addEventListener('keydown', onKeydown)
  // 带 ?app=xxx 进来时打开快速预览（老地址兼容）
  if (route.query.app) {
    const key = String(route.query.app)
    const hit = apps.value.find(a => a.key === key)
    if (hit) openPreview(hit)
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})

// 路由上的 ?app= 变化时（例如从工作台跳过来）同步打开预览抽屉
watch(() => route.query.app, async (key) => {
  if (!key) return
  if (!apps.value.length) await load()
  const hit = apps.value.find(a => a.key === String(key))
  if (hit) openPreview(hit)
})
</script>

<style scoped>
/* ============ 工具条 ============ */
.apps-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-3);
}
.tb-search { width: 280px; }
.tb-select { width: 150px; }
.tb-spacer { flex: 1; }
.tb-kbd {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: var(--radius-xs);
  padding: 0 5px;
  line-height: 16px;
  display: inline-block;
}
.tb-hint {
  min-height: 20px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
  padding: 0 2px;
}
.tb-shortcuts { color: var(--text-secondary); }

/* ============ 批量操作条 ============ */
.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}
.batch-count {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  margin-right: var(--space-2);
}

.grp-pop-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}
.grp-pop-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 180px;
  overflow-y: auto;
  margin-bottom: var(--space-3);
}
.grp-pop-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  text-align: left;
  padding: 7px 10px;
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  min-height: 30px;
}
.grp-pop-item:hover { background: var(--surface-hover); }
.grp-pop-item:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 1px;
}
.grp-pop-count {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.grp-pop-new {
  display: flex;
  gap: var(--space-2);
  border-top: 1px solid var(--border-light);
  padding-top: var(--space-3);
}

/* ============ 骨架 / 空态 ============ */
.skeleton-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  box-shadow: var(--shadow-card);
}

/* 上手引导 */
.onboard {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: linear-gradient(135deg, var(--primary-50), var(--bg-card));
  border: 1px solid var(--primary-light);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-4);
}
.onboard-icon {
  width: 48px; height: 48px; flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.onboard-body { flex: 1; min-width: 0; }
.onboard-title { font-weight: 700; font-size: var(--text-md); margin-bottom: 6px; color: var(--text-primary); }
.onboard-steps { display: flex; flex-direction: column; gap: 3px; }
.onboard-step {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  display: flex; align-items: center; gap: 8px;
}
.onboard-step b {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--primary); color: #fff;
  font-size: 11px; flex-shrink: 0;
}

/* 新建占位卡：用真按钮，键盘可聚焦 */
.add-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  border: 2px dashed var(--border-strong);
  background: transparent;
  border-radius: var(--radius-md);
  min-height: 190px;
  gap: 6px;
  cursor: pointer;
  font: inherit;
  color: var(--text-secondary);
  transition: border-color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out);
}
.add-card:hover {
  border-color: var(--primary);
  background: var(--primary-50);
}
.add-card:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.add-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 4px;
}
.add-title { font-weight: 600; font-size: var(--text-md); color: var(--text-primary); }
.add-desc { font-size: var(--text-xs); color: var(--text-secondary); }

/* ============ 表格视图 ============ */
.table-wrap { padding: 0; overflow: hidden; }
.cell-app { display: flex; align-items: center; gap: var(--space-3); }
.cell-app-icon {
  width: 28px; height: 28px; flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex; align-items: center; justify-content: center;
}
.cell-app-text { min-width: 0; }
.cell-app-name {
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cell-app-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cell-group {
  display: inline-block;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--primary-dark);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
  padding: 1px 8px;
  border-radius: var(--radius-full);
}
.cell-actions { display: flex; align-items: center; gap: 2px; }
/* 表格里的图标按钮同样要够大：小按钮在触屏上点不准 */
.tb-act-btn {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
}
.tb-act-btn:hover { color: var(--primary); }
.tb-act-btn.is-danger:hover { color: var(--danger); }
.tb-act-btn.is-danger :deep(.el-icon) { color: var(--danger); }

/* ============ 新建 / 编辑弹窗 ============ */
.entry-switch {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.ai-section { margin-bottom: var(--space-5); }
.ai-input-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.ai-input-row .el-textarea { flex: 1; }
.ai-alert { margin-top: var(--space-3); }
.ai-review {
  margin-top: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-subtle);
  padding: var(--space-3);
  max-height: 360px;
  overflow-y: auto;
}
.ai-review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-sm);
  font-weight: 600;
  margin-bottom: var(--space-3);
  color: var(--text-primary);
}
.draft-type {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-2);
}
.draft-type-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.draft-type-name { max-width: 220px; }
.draft-type-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.draft-fields { display: flex; flex-direction: column; gap: 6px; }
.draft-field { display: flex; align-items: center; gap: 6px; }
.draft-f-name { width: 150px; }
.draft-f-type { width: 116px; }
.draft-f-choices { flex: 1; min-width: 120px; }
.draft-relations {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  margin-top: var(--space-2); padding-top: var(--space-2);
  border-top: 1px dashed var(--border);
}
.draft-rel-title { font-size: var(--text-xs); color: var(--text-secondary); }

/* 模板选择 */
.tpl-section { margin-bottom: var(--space-5); }
.tpl-meta {
  float: right;
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: none;
  letter-spacing: 0;
}
.tpl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: var(--space-3);
  max-height: 320px;
  overflow-y: auto;
  padding: 2px;
}
.tpl-card {
  display: flex;
  gap: 10px;
  padding: 12px;
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out);
}
.tpl-card:hover { border-color: var(--primary-light); background: var(--primary-50); }
.tpl-card:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.tpl-card.active {
  border-color: var(--primary);
  background: var(--primary-50);
  box-shadow: 0 0 0 2px var(--primary-bg);
}
.tpl-icon {
  width: 34px; height: 34px; flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex; align-items: center; justify-content: center;
}
.tpl-body { min-width: 0; flex: 1; }
.tpl-name { font-weight: 700; font-size: var(--text-sm); margin-bottom: 3px; color: var(--text-primary); }
.tpl-desc {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 6px;
}
.tpl-tags { display: flex; flex-wrap: wrap; gap: 3px; }
.tpl-tag {
  font-size: 10px;
  height: 18px;
  line-height: 16px;
  padding: 0 5px;
  border-radius: var(--radius-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}
.tpl-open-lib { margin-top: var(--space-2); }

/* 图标选择器 */
.icon-picker {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 6px;
  width: 100%;
  max-height: 132px;
  overflow-y: auto;
}
.icon-choice {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-secondary);
  transition: border-color var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
  padding: 0;
  min-height: 28px;
}
.icon-choice:hover { border-color: var(--primary-light); color: var(--primary); background: var(--primary-50); }
.icon-choice:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.icon-choice.active {
  border-color: var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-bg);
}
.group-select { width: 100%; }

/* 本视图里的提示文字：一律用 --text-secondary，
   --text-tertiary 在浅底上只有 3.2:1，读起来发虚 */
.apps-hint {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 6px;
  line-height: 1.6;
}
.apps-hint-block { margin-bottom: var(--space-2); }
.apps-hint-inline { margin-left: 10px; }
.apps-hint code {
  background: var(--bg-subtle);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: var(--font-mono);
}

/* Element Plus 的占位文字默认是禁用色，浅底上几乎看不见 —— 换成正文色 */
:deep(.el-select__placeholder),
:deep(.el-select__placeholder span) { color: var(--text-secondary); }

@media (max-width: 900px) {
  .tb-search { width: 100%; }
  .tb-select { flex: 1; min-width: 130px; }
}
</style>
