<template>
  <div class="page">
    <PageTitle
      title="审计日志"
      subtitle="谁在什么时候改了什么东西。只记录写入类操作与登录事件 —— 读操作量大且没有追责价值"
      icon-key="Monitor"
    >
      <el-select v-model="statsDays" size="default" style="width:130px" @change="loadStats">
        <el-option label="近 7 天" :value="7" />
        <el-option label="近 30 天" :value="30" />
        <el-option label="近 90 天" :value="90" />
      </el-select>
      <el-button @click="reload">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </PageTitle>

    <!-- 顶部概览 -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="icon"><el-icon><Histogram /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.total }}</div>
          <div class="label">近 {{ statsDays }} 天写入次数</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="icon"><el-icon><UserFilled /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.by_user.length }}</div>
          <div class="label">活跃账号</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="icon"><el-icon><Coin /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.by_resource.length }}</div>
          <div class="label">涉及资源类型</div>
        </div>
      </div>
      <div class="stat-card info">
        <div class="icon"><el-icon><SetUp /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.by_action.length }}</div>
          <div class="label">操作种类</div>
        </div>
      </div>
    </div>

    <div class="audit-charts">
      <div class="card">
        <div class="card-title">
          <span class="card-title-text"><el-icon class="title-ico"><TrendCharts /></el-icon>写入趋势</span>
        </div>
        <EChart v-if="stats.total" :option="trendOption" height="210px" />
        <div v-else class="chart-empty">该时间范围内没有写入记录</div>
      </div>
      <div class="card">
        <div class="card-title">
          <span class="card-title-text"><el-icon class="title-ico"><UserFilled /></el-icon>按账号</span>
        </div>
        <div v-if="stats.by_user.length" class="rank-list">
          <div v-for="u in stats.by_user" :key="u.name" class="rank-row">
            <span class="rk-name" :title="u.name">{{ u.name }}</span>
            <span class="rk-bar"><i :style="{ width: pct(u.value, maxUser) }" /></span>
            <span class="rk-val">{{ u.value }}</span>
          </div>
        </div>
        <div v-else class="chart-empty">暂无数据</div>
      </div>
      <div class="card">
        <div class="card-title">
          <span class="card-title-text"><el-icon class="title-ico"><Coin /></el-icon>按资源</span>
        </div>
        <div v-if="stats.by_resource.length" class="rank-list">
          <div v-for="u in stats.by_resource" :key="u.name" class="rank-row">
            <span class="rk-name" :title="u.name">{{ resLabel(u.name) }}</span>
            <span class="rk-bar alt"><i :style="{ width: pct(u.value, maxRes) }" /></span>
            <span class="rk-val">{{ u.value }}</span>
          </div>
        </div>
        <div v-else class="chart-empty">暂无数据</div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="toolbar">
      <el-input v-model="filters.keyword" placeholder="搜索路径 / 资源 / 用户 / 对象 ID"
                clearable style="width:260px" @keyup.enter="applyFilters" @clear="applyFilters">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filters.username" placeholder="全部账号" clearable style="width:150px">
        <el-option v-for="u in facets.users" :key="u" :label="u" :value="u" />
      </el-select>
      <el-select v-model="filters.resource" placeholder="全部资源" clearable style="width:160px">
        <el-option v-for="r in facets.resources" :key="r" :label="resLabel(r)" :value="r" />
      </el-select>
      <el-select v-model="filters.action" placeholder="全部操作" clearable style="width:140px">
        <el-option v-for="a in facets.actions" :key="a" :label="actLabel(a)" :value="a" />
      </el-select>
      <el-select v-model="filters.days" placeholder="时间范围" clearable style="width:130px">
        <el-option label="近 1 天" :value="1" />
        <el-option label="近 7 天" :value="7" />
        <el-option label="近 30 天" :value="30" />
      </el-select>
      <el-button type="primary" @click="applyFilters">筛选</el-button>
      <el-button text @click="resetFilters">重置</el-button>
      <span class="spacer" />
      <span class="total-hint">共 {{ total }} 条</span>
    </div>

    <!-- 明细 -->
    <div class="card" style="padding:0;overflow:hidden">
      <el-table :data="items" v-loading="loading" stripe class="data-table">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="row-detail">
              <div class="rd-line"><span class="rd-k">请求路径</span><code>{{ row.method }} {{ row.path }}</code></div>
              <div class="rd-line"><span class="rd-k">来源 IP</span><code>{{ row.ip || '—' }}</code></div>
              <div class="rd-line"><span class="rd-k">对象 ID</span><code>{{ row.resource_id || '—' }}</code></div>
              <div class="rd-line">
                <span class="rd-k">附加信息</span>
                <pre class="rd-json">{{ pretty(row.detail) }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">
            <span class="cell-number">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="账号" width="130">
          <template #default="{ row }">
            <span class="who">{{ row.username || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="actTag(row.action)">{{ actLabel(row.action) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="资源" min-width="140">
          <template #default="{ row }">
            <span class="res-name">{{ resLabel(row.resource) }}</span>
            <code v-if="row.resource_id" class="rid">#{{ row.resource_id }}</code>
          </template>
        </el-table-column>
        <el-table-column label="接口" min-width="230">
          <template #default="{ row }">
            <code class="path">{{ row.method }} {{ row.path }}</code>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="status" :class="row.status < 400 ? 'ok' : 'bad'">{{ row.status }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && !items.length" class="empty-state" style="border:none">
        <div class="empty-icon"><el-icon :size="30"><Monitor /></el-icon></div>
        <div class="empty-title">没有符合条件的记录</div>
        <div class="empty-desc">换个时间范围或清空筛选条件再看看</div>
      </div>
    </div>

    <div v-if="total > pageSize" class="pager">
      <el-pagination
        layout="prev, pager, next, sizes, jumper"
        background
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        @current-change="onPage"
        @size-change="onSize"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Api } from '../../api'
import { formatTime } from '../../utils/format'
import { axisStyle, chartTheme, tooltipStyle } from '../../utils/theme'
import PageTitle from '../../components/PageTitle.vue'
import EChart from '../../components/EChart.vue'

// 后端 action / resource 都是英文枚举，前端统一在这里翻译，
// 避免每个用到的地方各写一份映射（也避免中文散落在模板里）
const ACTION_LABELS = {
  create: '新建', update: '修改', delete: '删除',
  upload: '上传', import: '导入', export: '导出',
  restore: '恢复', reindex: '重建索引', link: '建立关联', unlink: '解除关联',
  login: '登录', login_failed: '登录失败', change_password: '修改密码',
}
const ACTION_TAGS = {
  create: 'success', update: 'primary', delete: 'danger',
  upload: 'warning', import: 'warning', export: 'info',
  restore: 'success', reindex: 'info', link: 'success', unlink: 'warning',
  login: 'info', login_failed: 'danger', change_password: 'warning',
}
const RESOURCE_LABELS = {
  auth: '登录鉴权', entity_type: '数据模型', document: '文件', attachment: '附件',
  record: '业务记录', relation: '关联关系', app: '应用', note: '笔记',
  knowledge: '知识关联', dashboard: '可视化驾驶舱', user: '用户', role: '角色',
  ai: 'AI 能力', json: 'JSON 解析', system: '系统管理',
}

const actLabel = (a) => ACTION_LABELS[a] || a || '—'
const actTag = (a) => ACTION_TAGS[a] || 'info'
const resLabel = (r) => RESOURCE_LABELS[r] || r || '—'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const facets = reactive({ users: [], resources: [], actions: [] })
const filters = reactive({ keyword: '', username: '', resource: '', action: '', days: '' })

const statsDays = ref(7)
const stats = ref({ total: 0, trend: [], by_user: [], by_resource: [], by_action: [] })

const maxUser = computed(() => Math.max(1, ...stats.value.by_user.map(x => x.value)))
const maxRes = computed(() => Math.max(1, ...stats.value.by_resource.map(x => x.value)))

function pct(v, max) {
  return `${Math.max(4, Math.round((v / max) * 100))}%`
}

const trendOption = computed(() => {
  const t = chartTheme()
  const axis = axisStyle()
  return {
    grid: { left: 4, right: 10, top: 18, bottom: 2, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...tooltipStyle() },
    xAxis: {
      type: 'category',
      data: stats.value.trend.map(d => d.day),
      ...axis,
      splitLine: { show: false },
    },
    yAxis: { type: 'value', minInterval: 1, ...axis },
    series: [{
      name: '写入次数',
      type: 'bar',
      data: stats.value.trend.map(d => d.count),
      barMaxWidth: 24,
      itemStyle: { color: t.primary, borderRadius: [4, 4, 0, 0] },
    }],
  }
})

function pretty(detail) {
  const d = detail || {}
  if (!Object.keys(d).length) return '—'
  try { return JSON.stringify(d, null, 2) } catch { return String(d) }
}

function query() {
  return {
    page: page.value,
    page_size: pageSize.value,
    keyword: filters.keyword || '',
    username: filters.username || '',
    resource: filters.resource || '',
    action: filters.action || '',
    days: filters.days || 0,
  }
}

async function load() {
  loading.value = true
  try {
    const r = await Api.listAudit(query())
    items.value = r.items || []
    total.value = r.total || 0
    Object.assign(facets, { users: [], resources: [], actions: [] }, r.facets || {})
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const r = await Api.auditStats(statsDays.value)
    stats.value = { total: 0, trend: [], by_user: [], by_resource: [], by_action: [], ...r }
  } catch (e) { /* 拦截器已提示 */ }
}

function applyFilters() { page.value = 1; load() }

function resetFilters() {
  Object.assign(filters, { keyword: '', username: '', resource: '', action: '', days: '' })
  page.value = 1
  load()
}

function onPage(p) { page.value = p; load() }
function onSize(s) { pageSize.value = s; page.value = 1; load() }

function reload() { load(); loadStats() }

onMounted(reload)
</script>

<style scoped>
.audit-charts {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-4);
}
.audit-charts .card { margin-bottom: var(--space-4); }

.chart-empty {
  display: flex; align-items: center; justify-content: center;
  height: 180px; color: var(--text-tertiary); font-size: var(--text-sm);
}
.rank-list { display: flex; flex-direction: column; gap: 9px; padding: 4px 0; }
.rank-row { display: flex; align-items: center; gap: 9px; }
.rk-name {
  width: 74px; flex-shrink: 0; font-size: var(--text-sm); color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rk-bar {
  flex: 1; height: 7px; border-radius: var(--radius-full);
  background: var(--bg-sunken); overflow: hidden; min-width: 30px;
}
.rk-bar i { display: block; height: 100%; border-radius: var(--radius-full); background: var(--primary); }
.rk-bar.alt i { background: var(--success); }
.rk-val {
  width: 30px; text-align: right; flex-shrink: 0;
  font-size: var(--text-sm); font-variant-numeric: tabular-nums; color: var(--text-tertiary);
}

.total-hint { font-size: var(--text-sm); color: var(--text-tertiary); }

.cell-number { font-variant-numeric: tabular-nums; color: var(--text-secondary); font-size: var(--text-sm); }
.who { font-weight: 600; color: var(--text-primary); }
.res-name { color: var(--text-primary); }
.rid {
  margin-left: 6px; font-family: var(--font-mono); font-size: var(--text-xs);
  color: var(--primary); background: var(--primary-bg);
  padding: 1px 6px; border-radius: var(--radius-xs);
}
.path {
  font-family: var(--font-mono); font-size: var(--text-xs);
  color: var(--text-secondary); word-break: break-all;
}
.status { font-variant-numeric: tabular-nums; font-weight: 600; font-size: var(--text-sm); }
.status.ok { color: var(--success); }
.status.bad { color: var(--danger); }

.row-detail { padding: 6px 40px 14px; display: flex; flex-direction: column; gap: 8px; }
.rd-line { display: flex; gap: 12px; align-items: flex-start; font-size: var(--text-sm); }
.rd-k { width: 68px; flex-shrink: 0; color: var(--text-tertiary); }
.rd-line code {
  font-family: var(--font-mono); font-size: var(--text-xs);
  color: var(--text-secondary); word-break: break-all;
}
.rd-json {
  margin: 0; font-family: var(--font-mono); font-size: var(--text-xs);
  background: var(--bg-subtle); color: var(--text-secondary);
  padding: 8px 10px; border-radius: var(--radius-sm);
  max-height: 160px; overflow: auto; white-space: pre-wrap;
}

.pager { display: flex; justify-content: flex-end; margin-top: var(--space-4); }

@media (max-width: 1100px) {
  .audit-charts { grid-template-columns: 1fr; }
}
</style>
