<template>
  <div class="page" v-loading="loading">
    <PageTitle
      :title="titleText"
      :subtitle="dash?.description || '卡片式自定义视图：指标、图表、表格、清单、说明文字都能拼在一屏上'"
      icon-key="DataLine"
    >
      <el-button @click="loadData">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button type="success" plain @click="screenOn = true">
        <el-icon><Monitor /></el-icon>大屏
      </el-button>
      <template v-if="edit">
        <el-button @click="addWidget">
          <el-icon><Plus /></el-icon>添加卡片
        </el-button>
        <el-button @click="cancelEdit">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveLayout">
          <el-icon><Check /></el-icon>保存布局
        </el-button>
      </template>
      <el-button v-else-if="canWrite" type="primary" @click="enterEdit">
        <el-icon><EditPen /></el-icon>编辑布局
      </el-button>
    </PageTitle>

    <div v-if="edit" class="edit-bar">
      <el-icon :size="15"><Rank /></el-icon>
      <span>
        这是一整块自由画布：拖动卡片任意摆放，拖四边/四角改大小；右下角可缩放、吸附、自动整理。
        改完点右上角「保存布局」。
      </span>
      <span class="spacer" />
      <span class="eb-count">{{ layout.length }} 张卡片</span>
    </div>

    <div ref="cvWrap" class="cv-wrap" :class="{ 'is-edit': edit }">
      <CockpitCanvas
        :layout="layout"
        :computed="computedMap"
        :edit="edit"
        fit-mode="width"
        @move="onCanvasMove"
        @replace="onCanvasReplace"
        @edit-widget="editWidget"
        @remove="removeWidget"
        @front="frontWidget"
        @add-at="addAt"
        @open-row="openRow"
      />
    </div>

    <div v-if="!loading && !layout.length && !edit" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><DataLine /></el-icon></div>
      <div class="empty-title">这个驾驶舱还是空的</div>
      <div class="empty-desc">
        {{ canWrite ? '点「编辑布局」进入自由画布，双击空白处就能新建第一张卡片' : '管理员还没有配置卡片' }}
      </div>
      <el-button v-if="canWrite" type="primary" style="margin-top:16px" @click="enterEdit">
        <el-icon><EditPen /></el-icon>开始编辑
      </el-button>
    </div>

    <!-- ============ 卡片配置 ============ -->
    <el-drawer v-model="editorOpen" :size="drawerSize" :with-header="false"
               class="widget-drawer" :close-on-click-modal="false">
      <div class="wd">
        <header class="wd-head">
          <h3>{{ editIndex == null ? '添加卡片' : '配置卡片' }}</h3>
          <el-button text @click="editorOpen = false"><el-icon><Close /></el-icon></el-button>
        </header>

        <div class="wd-body">
          <!-- 展示方式 -->
          <section class="wd-sec">
            <div class="wd-label">展示方式</div>
            <el-radio-group v-model="draft.type" size="default" @change="onTypeChange">
              <el-radio-button v-for="t in WIDGET_TYPES" :key="t.key" :value="t.key">
                {{ t.label }}
              </el-radio-button>
            </el-radio-group>
          </section>

          <!-- 通用外观 -->
          <section class="wd-sec">
            <div class="wd-row">
              <div class="wd-field grow">
                <div class="wd-label">标题</div>
                <el-input v-model="draft.title" placeholder="卡片顶部显示的名称" />
              </div>
              <div class="wd-field" style="width:100px" v-if="draft.type === 'stat' || draft.type === 'gauge'">
                <div class="wd-label">单位</div>
                <el-input v-model="draft.unit" placeholder="如 元" />
              </div>
            </div>

            <div class="wd-label" style="margin-top:16px">
              尺寸<span class="wd-opt">（画布上拖四边 / 四角也能改）</span>
            </div>
            <div class="wd-row sz-row">
              <el-radio-group v-model="draftPreset" size="small" @change="applyPreset">
                <el-radio-button v-for="p in SIZE_PRESETS" :key="p.key" :value="p.key">{{ p.label }}</el-radio-button>
              </el-radio-group>
              <div class="wd-field sz-num">
                <div class="wd-label">宽 px</div>
                <el-input-number v-model="draft.w" :min="minSize(draft.type).w" :max="4000" :step="20"
                                 controls-position="right" @change="onSizeInput" />
              </div>
              <div class="wd-field sz-num">
                <div class="wd-label">高 px</div>
                <el-input-number v-model="draft.h" :min="minSize(draft.type).h" :max="2400" :step="20"
                                 controls-position="right" @change="onSizeInput" />
              </div>
            </div>
            <div class="wd-hint">
              卡片只受最小尺寸限制（{{ minSize(draft.type).w }} × {{ minSize(draft.type).h }} px），
              想放多大都行；画布可以往右下无限延伸。
            </div>
          </section>

          <!-- 文本卡 -->
          <section v-if="draft.type === 'text'" class="wd-sec">
            <div class="wd-label">文字内容</div>
            <el-input v-model="draft.text" type="textarea" :rows="8"
                      placeholder="支持 # 标题、- 列表、**加粗**、`代码`" />
            <div class="wd-hint">用「- 」开头是列表项，「# 」「## 」是标题，「**粗**」会加粗。</div>
          </section>

          <!-- 数据源 -->
          <template v-else>
            <section class="wd-sec">
              <div class="wd-label">数据源</div>
              <el-radio-group v-model="draft.source.kind" size="default" @change="onKindChange">
                <el-radio-button v-for="k in kinds" :key="k.key" :value="k.key">{{ k.name }}</el-radio-button>
              </el-radio-group>
              <el-select v-if="draft.source.kind === 'entity'" v-model="draft.source.type_id"
                         placeholder="选择一个数据模型" style="width:100%;margin-top:10px">
                <el-option v-for="t in entityTypes" :key="t.id"
                           :label="`${t.name}（${t.count} 条）`" :value="t.id" />
              </el-select>
            </section>

            <!-- 指标：stat/gauge/kpi/progress/status/rank/chart 都需要 metric -->
            <section class="wd-sec" v-if="['stat','chart','gauge','rank','progress','status','kpi'].includes(draft.type)">
              <div class="wd-row">
                <div class="wd-field grow">
                  <div class="wd-label">计算方式</div>
                  <el-select v-model="draft.source.metric">
                    <el-option v-for="m in metrics" :key="m" :label="metricLabel(m)" :value="m" />
                  </el-select>
                </div>
                <div class="wd-field grow" v-if="draft.source.metric !== 'count'">
                  <div class="wd-label">数值字段</div>
                  <el-select v-model="draft.source.field" filterable clearable placeholder="选择要计算的字段">
                    <el-option v-for="f in numericFields" :key="f.key"
                               :label="`${f.name}（${f.key}）`" :value="f.key" />
                  </el-select>
                </div>
                <div class="wd-field" style="width:140px" v-if="['gauge','progress','kpi'].includes(draft.type)">
                  <div class="wd-label">目标值</div>
                  <el-input-number v-model="draft.source.goal" :min="0"
                                   controls-position="right" placeholder="如 100" />
                </div>
              </div>
              <div class="wd-hint" v-if="draft.type === 'gauge'">
                仪表盘显示「当前值 ÷ 目标值」的达成率；目标值要大于 0。
              </div>
              <div class="wd-hint" v-if="draft.type === 'progress'">
                选择分组字段时显示「分组占比」；不选分组字段且有目标值时显示「达成率」。
              </div>
            </section>

            <!-- 图表 / 排行 / 进度条 / 状态板 特有：分组字段 -->
            <section class="wd-sec" v-if="['chart','rank','progress','status'].includes(draft.type)">
              <div class="wd-label">{{ draft.type === 'status' ? '状态字段' : '分组字段' }}</div>
              <el-select v-model="draft.source.group_by" filterable clearable
                         :placeholder="draft.type === 'status' ? '留空时文件默认按抽取状态分组' : '按哪个字段拆成多组'" style="width:100%">
                <el-option v-for="f in fieldOptions" :key="f.key"
                           :label="`${f.name}（${f.key}）`" :value="f.key" />
              </el-select>
              <div class="wd-row" style="margin-top:10px">
                <div class="wd-field grow" v-if="draft.type === 'chart'">
                  <div class="wd-label">图表类型</div>
                  <el-select v-model="draft.source.chart">
                    <el-option v-for="c in CHART_KIND_OPTIONS" :key="c.value" :label="c.label" :value="c.value" />
                  </el-select>
                </div>
                <div class="wd-field grow">
                  <div class="wd-label">排序</div>
                  <el-select v-model="draft.source.sort">
                    <el-option label="从大到小" value="desc" />
                    <el-option label="从小到大" value="asc" />
                  </el-select>
                </div>
                <div class="wd-field" style="width:100px">
                  <div class="wd-label">{{ draft.type === 'rank' ? '条数' : '最多' }}</div>
                  <el-input-number v-model="draft.source.limit" :min="1" :max="50" controls-position="right" />
                </div>
              </div>
            </section>

            <!-- 表格列 -->
            <section class="wd-sec" v-if="draft.type === 'table'">
              <div class="wd-row">
                <div class="wd-field grow">
                  <div class="wd-label">展示列</div>
                  <el-select v-model="draft.source.columns" multiple collapse-tags
                             placeholder="留空则默认取前 5 个字段" style="width:100%">
                    <el-option v-for="f in fieldOptions" :key="f.key"
                               :label="`${f.name}（${f.key}）`" :value="f.key" />
                  </el-select>
                </div>
                <div class="wd-field" style="width:100px">
                  <div class="wd-label">行数</div>
                  <el-input-number v-model="draft.source.limit" :min="1" :max="100" controls-position="right" />
                </div>
              </div>
            </section>

            <!-- 清单条数 -->
            <section class="wd-sec" v-if="draft.type === 'list'">
              <div class="wd-field" style="width:130px">
                <div class="wd-label">显示条数</div>
                <el-input-number v-model="draft.source.limit" :min="1" :max="50" controls-position="right" />
              </div>
            </section>

            <!-- 时间窗口 -->
            <section class="wd-sec">
              <div class="wd-row">
                <div class="wd-field grow">
                  <div class="wd-label">时间字段<span class="wd-opt">（可选，做环比）</span></div>
                  <el-select v-model="draft.source.range_field" clearable placeholder="不限制时间">
                    <el-option v-for="f in pseudoFields" :key="f.key" :label="f.name" :value="f.key" />
                  </el-select>
                </div>
                <div class="wd-field" style="width:130px">
                  <div class="wd-label">最近 N 天</div>
                  <el-input-number v-model="draft.source.days" :min="0" :max="365"
                                   controls-position="right" :disabled="!draft.source.range_field" />
                </div>
              </div>
              <div class="wd-hint" v-if="draft.source.range_field && draft.source.days">
                指标卡会自动算出与前 {{ draft.source.days }} 天相比的增减与迷你趋势。
              </div>
            </section>

            <!-- 筛选条件 -->
            <section class="wd-sec">
              <div class="wd-head-row">
                <div class="wd-label">筛选条件</div>
                <el-button size="small" link type="primary" @click="addFilter">
                  <el-icon><Plus /></el-icon>加一条
                </el-button>
              </div>
              <div v-for="(f, i) in draft.source.filters" :key="i" class="filter-row">
                <el-select v-model="f.field" filterable placeholder="字段" style="flex:1.2">
                  <el-option v-for="o in fieldOptions" :key="o.key"
                             :label="`${o.name}（${o.key}）`" :value="o.key" />
                </el-select>
                <el-select v-model="f.op" placeholder="条件" style="flex:1">
                  <el-option v-for="o in ops" :key="o" :label="OP_LABELS[o] || o" :value="o" />
                </el-select>
                <el-input v-if="!NO_VALUE_OPS.includes(f.op)" v-model="f.value"
                          :placeholder="f.op === 'in' ? '多个值用逗号分隔' : '值'" style="flex:1.2" />
                <el-button link type="danger" @click="draft.source.filters.splice(i, 1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <div v-if="!draft.source.filters.length" class="wd-hint">
                不加条件就是全部数据。
              </div>
            </section>
          </template>

          <!-- 试算预览 -->
          <section class="wd-sec">
            <div class="wd-head-row">
              <div class="wd-label">实时预览</div>
              <el-button size="small" type="primary" plain :loading="previewing" @click="doPreview">
                <el-icon><View /></el-icon>试算
              </el-button>
            </div>
            <div class="preview-box" :class="{ empty: !preview }">
              <CockpitWidget v-if="preview" :widget="preview" body-height="200px" :table-height="200" />
              <div v-else class="pb-hint">点「试算」按当前配置取一次数，确认无误再应用。</div>
            </div>
          </section>
        </div>

        <footer class="wd-foot">
          <el-button @click="editorOpen = false">取消</el-button>
          <el-button type="primary" @click="applyWidget">
            {{ editIndex == null ? '添加到驾驶舱' : '应用修改' }}
          </el-button>
        </footer>
      </div>
    </el-drawer>
    <!-- ============ 全屏大屏 ============ -->
    <CockpitFullscreen v-model="screenOn" :dash="dash" @open-row="openRow" />
  </div>
</template>

<script setup>
/**
 * 可视化驾驶舱
 *
 * 单一数据源：`layout` 存卡片配置与几何（自由画布坐标 x/y/w/h），
 * `computedMap` 存后端算好的成品数据。视图模式下两者一起渲染；
 * 编辑模式下改 layout，未保存的卡片显示占位，点「试算」拿到准确数据后
 * 立即在画布上呈现。
 *
 * 布局的真相在页面手里，画布组件只负责指针交互，通过 move/replace 事件
 * 把结果提交回来 —— 这样「取消编辑」只要丢弃内存里的 layout 即可。
 */
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'
import { useAuthStore } from '../stores/auth'
import PageTitle from '../components/PageTitle.vue'
import CockpitWidget from '../components/CockpitWidget.vue'
import CockpitCanvas from '../components/CockpitCanvas.vue'
import CockpitFullscreen from '../components/CockpitFullscreen.vue'
import {
  SIZE_PRESETS, clampBox, contentSize, defaultSize, findFreeSlot, minSize, normalizeLayout, stretchLayout,
} from '../utils/canvas'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const WIDGET_TYPES = [
  { key: 'stat', label: '指标' },
  { key: 'kpi', label: 'KPI' },
  { key: 'gauge', label: '仪表盘' },
  { key: 'progress', label: '进度条' },
  { key: 'status', label: '状态板' },
  { key: 'rank', label: '排行' },
  { key: 'chart', label: '图表' },
  { key: 'table', label: '表格' },
  { key: 'list', label: '清单' },
  { key: 'text', label: '文字' },
]

const CHART_KIND_OPTIONS = [
  { value: 'bar', label: '柱状图' },
  { value: 'line', label: '折线图' },
  { value: 'area', label: '面积图' },
  { value: 'bar_h', label: '横向条形' },
  { value: 'pie', label: '饼图' },
  { value: 'donut', label: '环形图' },
  { value: 'radar', label: '雷达图' },
]

const METRIC_LABELS = { count: '计数（行数）', sum: '求和', avg: '平均值', min: '最小值', max: '最大值' }
const OP_LABELS = {
  eq: '等于', ne: '不等于', contains: '包含', not_contains: '不包含',
  gt: '大于', lt: '小于', gte: '大于等于', lte: '小于等于',
  not_empty: '不为空', empty: '为空', in: '属于',
}
const NO_VALUE_OPS = ['empty', 'not_empty']

const metricLabel = (m) => METRIC_LABELS[m] || m

const dash = ref(null)
const layout = ref([])
const computedMap = ref({})
const options = ref({ entity_types: [], document_fields: [], relation_fields: [], kinds: [] })

const loading = ref(false)
const saving = ref(false)
const edit = ref(false)
const editorOpen = ref(false)
const editIndex = ref(null)
const previewing = ref(false)
const preview = ref(null)

const windowWidth = ref(1440)
const screenOn = ref(false)
const cvWrap = ref(null)

function canvasWidth() {
  const el = cvWrap.value
  const w = el ? el.clientWidth : windowWidth.value
  // 画布至少保持基准宽度，避免超窄屏把卡片压得太扁；
  // 如果容器更宽就用容器宽，确保一行能铺满
  return Math.max(1180, w)
}


/** 尺寸预设当前选中项；手填宽高后自动清空 */
const draftPreset = ref('md')
let lastType = 'stat'

const canWrite = computed(() => auth.can('dashboard_write'))
const titleText = computed(() => `${dash.value?.icon || '📊'} ${dash.value?.name || '驾驶舱'}`)
const drawerSize = computed(() => (windowWidth.value < 760 ? '100%' : '580px'))

const entityTypes = computed(() => options.value.entity_types || [])
const kinds = computed(() => options.value.kinds || [])
const metrics = computed(() => options.value.metrics || [])
const ops = computed(() => options.value.ops || [])

function measure() {
  windowWidth.value = window.innerWidth
}

/** 当前数据源的字段清单（含伪字段 _created_at / _updated_at） */
const baseFields = computed(() => {
  const k = draft.source.kind
  if (k === 'document') return options.value.document_fields || []
  if (k === 'relation') return options.value.relation_fields || []
  const t = entityTypes.value.find(x => x.id === draft.source.type_id)
  return t?.fields || []
})

const pseudoFields = computed(() => (
  draft.source.kind === 'relation'
    ? [{ key: '_created_at', name: '创建时间', type: 'datetime' }]
    : [
        { key: '_created_at', name: '创建时间', type: 'datetime' },
        { key: '_updated_at', name: '更新时间', type: 'datetime' },
      ]
))

const fieldOptions = computed(() => [...baseFields.value, ...pseudoFields.value])

/** 能参与 sum/avg 的字段：数值类型，外加看起来是数字的 */
const numericFields = computed(() => {
  const nums = baseFields.value.filter(f => ['number'].includes(f.type))
  return nums.length ? nums : baseFields.value
})

const draft = reactive({
  id: '', type: 'stat', title: '', unit: '', text: '',
  w: defaultSize('stat').w, h: defaultSize('stat').h,
  source: emptySource(),
})

function emptySource() {
  return {
    kind: 'entity', type_id: null, metric: 'count', field: '',
    group_by: '', chart: 'bar', filters: [], sort: 'desc', limit: 10,
    columns: [], range_field: '', days: 0, goal: null,
  }
}

function newId() {
  return `w_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

// ---------- 取数 ----------

async function loadMeta() {
  try {
    const [d, o] = await Promise.all([Api.getDashboard(route.params.id), Api.dashboardOptions()])
    dash.value = d
    options.value = { entity_types: [], document_fields: [], relation_fields: [], kinds: [], ...o }
    // 老驾驶舱存的是 span（1~4 列），在这里一次性换算成自由画布坐标。
    // 用当前容器宽度做 shelf-pack + 自动拉伸，确保一行不会空出右边。
    const cw = canvasWidth()
    let normalized = normalizeLayout(d.layout || [], { width: cw, fill: true })
      .map(w => ({ ...w, id: w.id || newId() }))
    // 后端残留的旧 1440 宽度坐标，且内容比当前容器窄时，自适应拉伸行
    const contentW = contentSize(normalized, { margin: 0 }).w
    if (contentW < cw * 0.95) {
      normalized = stretchLayout(normalized, cw)
    }
    layout.value = normalized
  } catch (e) { /* 拦截器已提示 */ }
}

async function loadData() {
  if (!dash.value) return
  loading.value = true
  try {
    const r = await Api.dashboardData(route.params.id)
    computedMap.value = Object.fromEntries((r.widgets || []).map(w => [w.id, w]))
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function reload() {
  await loadMeta()
  await loadData()
}

/** 卡片渲染数据：有算好的就用，没有就给占位（编辑态的未保存卡片） */
function computedFor(w) {
  return computedMap.value[w.id] || { ...w, data: null, error: '' }
}

// ---------- 画布交互 ----------

/** 拖动 / 缩放 / 键盘微调的结果：只改这一张卡的几何，其余不动 */
function onCanvasMove(index, box) {
  const w = layout.value[index]
  if (!w) return
  layout.value[index] = { ...w, ...clampBox(box, w.type) }
}

/** 自动整理：整盘替换 */
function onCanvasReplace(next) {
  layout.value = next.map(w => ({ ...w }))
}

/** 置顶：数组顺序就是叠放顺序，放最后 = 压在最上面 */
function frontWidget(i) {
  if (i < 0 || i >= layout.value.length) return
  const arr = [...layout.value]
  const [item] = arr.splice(i, 1)
  arr.push(item)
  layout.value = arr
}

/** 双击画布空白：就地新建一张卡片 */
function addAt(pos) {
  pendingSlot.value = { x: Math.max(0, pos.x - 60), y: Math.max(0, pos.y - 24) }
  addWidget()
}

// ---------- 编辑 ----------

function enterEdit() {
  layout.value = normalizeLayout(layout.value, { width: canvasWidth(), fill: true })
  edit.value = true
  ElMessage.info('画布已解锁：拖动卡片摆放，拖四边/四角缩放')
}

async function cancelEdit() {
  if (saving.value) return
  try {
    await ElMessageBox.confirm('放弃本次未保存的布局修改？', '取消编辑',
      { type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' })
  } catch { return }
  edit.value = false
  await reload()
}

async function saveLayout() {
  saving.value = true
  try {
    await Api.updateDashboard(dash.value.id, { layout: layout.value })
    ElMessage.success('布局已保存')
    edit.value = false
    await reload()
  } catch (e) { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

/** 新卡片落点：优先用双击的位置，否则自己找一块空地 */
const pendingSlot = ref(null)

function addWidget() {
  editIndex.value = null
  const size = defaultSize('stat')
  Object.assign(draft, {
    id: '', type: 'stat', title: '', unit: '', text: '',
    w: size.w, h: size.h, source: emptySource(),
  })
  draftPreset.value = 'md'
  lastType = 'stat'
  draft.source.type_id = entityTypes.value[0]?.id ?? null
  preview.value = null
  editorOpen.value = true
}

function editWidget(i) {
  editIndex.value = i
  const w = layout.value[i]
  Object.assign(draft, {
    id: w.id, type: w.type || 'stat', title: w.title || '',
    unit: w.unit || '', text: w.text || '',
    w: Number(w.w) || defaultSize(w.type).w,
    h: Number(w.h) || defaultSize(w.type).h,
    source: { ...emptySource(), ...(w.source || {}) },
  })
  draft.source.filters = (w.source?.filters || []).map(f => ({ ...f }))
  draft.source.columns = [...(w.source?.columns || [])]
  draftPreset.value = ''
  lastType = draft.type
  preview.value = null
  editorOpen.value = true
}

/** 尺寸预设：按类型的默认尺寸等比缩放，避免「表格的尺寸套到指标卡上」 */
function applyPreset(key) {
  const p = SIZE_PRESETS.find(x => x.key === key)
  if (!p || !key) return
  const d = defaultSize(draft.type)
  const min = minSize(draft.type)
  draft.w = Math.max(min.w, Math.round(d.w * (p.w || p.scale || 1)))
  draft.h = Math.max(min.h, Math.round(d.h * (p.h || p.scale || 1)))
}

function onSizeInput() {
  draftPreset.value = ''
}

function applyWidget() {
  const isText = draft.type === 'text'
  const src = { ...draft.source, filters: draft.source.filters.map(cleanFilter) }
  const box = clampBox({ x: 0, y: 0, w: draft.w, h: draft.h }, draft.type)
  const cfg = {
    id: draft.id || newId(),
    type: draft.type,
    title: draft.title.trim() || defaultTitle(draft),
    unit: draft.unit || '',
    w: box.w,
    h: box.h,
  }
  if (isText) cfg.text = draft.text
  else cfg.source = stripEmpties(src)

  if (editIndex.value == null) {
    // 双击空白处新建就落在鼠标那里，否则自己找一块空地
    const slot = pendingSlot.value || findFreeSlot(layout.value, { w: box.w, h: box.h }, { width: canvasWidth() })
    pendingSlot.value = null
    layout.value = [...layout.value, { ...cfg, x: slot.x, y: slot.y }]
    ElMessage.success('已添加，记得保存布局')
  } else {
    const old = layout.value[editIndex.value] || { x: 0, y: 0 }
    layout.value.splice(editIndex.value, 1, {
      ...cfg, x: Number(old.x) || 0, y: Number(old.y) || 0,
    })
    ElMessage.success('已应用，记得保存布局')
  }

  // 试算过就用真实数据立刻呈现，否则先占位，等保存后统一取数
  const next = { ...computedMap.value }
  if (preview.value && preview.value.id === draft.id) next[cfg.id] = preview.value
  else delete next[cfg.id]
  computedMap.value = next

  editorOpen.value = false
}

function defaultTitle(d) {
  const t = WIDGET_TYPES.find(x => x.key === d.type)?.label || '卡片'
  const name = entityTypes.value.find(x => x.id === d.source.type_id)?.name
  return name && d.type !== 'text' ? `${name} ${t}` : t
}

function cleanFilter(f) {
  const out = { field: f.field, op: f.op || 'eq' }
  if (!NO_VALUE_OPS.includes(out.op)) {
    out.value = out.op === 'in'
      ? String(f.value ?? '').split(',').map(s => s.trim()).filter(Boolean)
      : f.value
  }
  return out
}

/** 空字符串会让后端当成有效条件，保存前统一剔除 */
function stripEmpties(src) {
  const out = {}
  Object.entries(src).forEach(([k, v]) => {
    if (v === '' || v === null || v === undefined) return
    if (Array.isArray(v) && !v.length) return
    if (k === 'days' && !Number(v)) return
    out[k] = v
  })
  return out
}

function removeWidget(i) {
  if (i < 0 || i >= layout.value.length) return
  const w = layout.value[i]
  ElMessageBox.confirm(`从画布上移除「${w.title || '这张卡片'}」？保存布局后才会真正生效。`, '移除卡片', {
    type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消',
  }).then(() => {
    layout.value.splice(i, 1)
    ElMessage.success('已移除，记得保存布局')
  }).catch(() => {})
}

// ---------- 编辑器联动 ----------

function onTypeChange(t) {
  // 尺寸还是「上一个类型的默认值」时跟着类型走，用户手动改过就不动它
  const prev = defaultSize(lastType)
  if (draft.w === prev.w && draft.h === prev.h) {
    const d = defaultSize(t)
    draft.w = d.w
    draft.h = d.h
    draftPreset.value = 'md'
  } else {
    const min = minSize(t)
    draft.w = Math.max(min.w, draft.w)
    draft.h = Math.max(min.h, draft.h)
  }
  lastType = t
  preview.value = null
}

function onKindChange() {
  draft.source.field = ''
  draft.source.group_by = ''
  draft.source.columns = []
  draft.source.range_field = ''
  draft.source.filters = []
  if (draft.source.kind === 'entity') draft.source.type_id = entityTypes.value[0]?.id ?? null
  preview.value = null
}

function addFilter() {
  draft.source.filters.push({ field: '', op: 'eq', value: '' })
}

async function doPreview() {
  if (draft.type === 'text') {
    preview.value = { id: draft.id, type: 'text', title: draft.title, text: draft.text }
    return
  }
  if (draft.source.kind === 'entity' && !draft.source.type_id) {
    ElMessage.warning('请先选择数据模型')
    return
  }
  if (['gauge','progress','kpi'].includes(draft.type) && !(Number(draft.source.goal) > 0)) {
    ElMessage.warning('目标值要大于 0')
    return
  }
  if ((draft.type === 'chart' || draft.type === 'rank' || draft.type === 'progress' || draft.type === 'status') && !draft.source.group_by) {
    if (draft.type !== 'status' || draft.source.kind !== 'document') {
      ElMessage.warning(`${draft.type === 'rank' ? '排行榜' : draft.type === 'progress' ? '进度条' : draft.type === 'status' ? '状态板' : '图表'}需要选择分组/状态字段`)
      return
    }
  }
  previewing.value = true
  try {
    const widget = {
      id: draft.id || 'preview', type: draft.type, title: draft.title,
      unit: draft.unit, text: draft.text,
      source: stripEmpties({ ...draft.source, filters: draft.source.filters.map(cleanFilter) }),
    }
    preview.value = await Api.previewWidget(widget)
    if (preview.value?.error) ElMessage.warning(preview.value.error)
  } catch (e) { /* 拦截器已提示 */ } finally {
    previewing.value = false
  }
}

function openRow(w, row) {
  const id = row?._id ?? row?.id
  if (!id) return
  if (w.source?.kind === 'document') router.push({ path: '/library', query: { id } })
  else if (w.source?.kind === 'entity' && w.source.type_id) {
    router.push({ path: `/records/${w.source.type_id}`, query: { id } })
  }
}

function onResize() { measure() }

watch(() => route.params.id, reload)
onMounted(async () => {
  measure()
  window.addEventListener('resize', onResize)
  await reload()
})
onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.edit-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 10px 16px; margin-bottom: var(--space-4);
  background: var(--primary-bg); border: 1px solid var(--primary-200);
  border-radius: var(--radius-md); font-size: var(--text-sm);
  color: var(--text-secondary);
}
.edit-bar .spacer { flex: 1; min-width: 8px; }
.eb-count { color: var(--primary); font-weight: 600; }

/* 画布容器：给一个确定的视口高度，画布内部自己滚 */
.cv-wrap {
  height: max(520px, calc(100vh - 232px));
  min-height: 0;
}
.cv-wrap.is-edit { height: max(520px, calc(100vh - 274px)); }

/* 尺寸预设 + 宽高输入 */
.sz-row { align-items: flex-end; gap: 10px; }
.sz-num { width: 116px; flex: 0 0 auto; }
.sz-num .wd-label { margin-bottom: 6px; }
.sz-num :deep(.el-input-number) { width: 100%; }

/* ---------- 配置抽屉 ---------- */
.wd { display: flex; flex-direction: column; height: 100%; }
.wd-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid var(--border);
}
.wd-head h3 { margin: 0; font-size: var(--text-lg); font-weight: 650; color: var(--text-primary); }
.wd-body { flex: 1; overflow: auto; padding: 18px 20px; }
.wd-foot {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 20px; border-top: 1px solid var(--border); background: var(--bg-card);
}

.wd-sec { margin-bottom: 22px; }
.wd-label {
  font-size: var(--text-sm); font-weight: 600; color: var(--text-secondary);
  margin-bottom: 8px; display: flex; align-items: center; gap: 6px;
}
.wd-opt { font-weight: 400; color: var(--text-tertiary); }
.wd-head-row {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  margin-bottom: 8px;
}
.wd-head-row .wd-label { margin-bottom: 0; }
.wd-row { display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.wd-field { display: flex; flex-direction: column; }
.wd-field.grow { flex: 1; min-width: 130px; }
.wd-field .wd-label { margin-bottom: 6px; }
.wd-hint { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 7px; line-height: 1.6; }

.filter-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }

.preview-box {
  border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 14px; background: var(--bg-card); min-height: 120px;
}
.preview-box.empty { border-style: dashed; background: var(--bg-subtle); }
.pb-hint {
  display: flex; align-items: center; justify-content: center;
  min-height: 92px; font-size: var(--text-sm); color: var(--text-tertiary);
}

@media (max-width: 768px) {
  /* 窄屏：画布给固定视口高度，靠缩放和滚动看全，不做重排——
     自由画布的坐标是用户排的，重排会打乱它 */
  .cv-wrap { height: 72vh; }
  .sz-num { width: 96px; }
}
</style>
