<template>
  <div class="cw" :class="[`cw-${widget.type}`, { empty: isEmpty, 'cw-screen': screen }]">
    <!-- 标题：指标卡/KPI 自己排版，其余类型统一在顶部 -->
    <div v-if="widget.title && widget.type !== 'stat' && widget.type !== 'kpi' && widget.type !== 'gauge'" class="cw-head">
      <span class="cw-title">{{ widget.title }}</span>
      <span v-if="unitSuffix" class="cw-unit">{{ unitSuffix }}</span>
    </div>

    <!-- 配置错误只影响这一张卡，其他卡片照常显示 -->
    <div v-if="widget.error" class="cw-error">
      <el-icon :size="14"><WarningFilled /></el-icon>
      <span>{{ widget.error }}</span>
    </div>

    <!-- 指标卡 -->
    <template v-else-if="widget.type === 'stat'">
      <div class="cw-stat-label">{{ widget.title || '指标' }}</div>
      <div class="cw-stat-value" :class="dirClass">
        <span class="sv-num">{{ statText }}</span>
        <span v-if="suffix" class="sv-unit">{{ suffix }}</span>
      </div>
      <div v-if="widget.data?.delta" class="cw-stat-delta" :class="dirClass">
        <el-icon :size="12">
          <component :is="deltaIcon" />
        </el-icon>
        {{ widget.data.delta.value }}<template v-if="pctText">（{{ pctText }}）</template>
        <span class="dd-cmp">{{ widget.data.delta.compared }}</span>
      </div>
      <div v-else-if="widget.data" class="cw-stat-sub">
        {{ metricLabel }}<template v-if="widget.data.field_label && widget.data.field"> · {{ widget.data.field_label }}</template>
      </div>
      <div v-if="widget.data?.spark?.length" class="cw-spark">
        <i v-for="(v, i) in widget.data.spark" :key="i"
           :style="{ height: sparkH(v) }" :title="`${v}`" />
      </div>
    </template>

    <!-- KPI 卡 -->
    <template v-else-if="widget.type === 'kpi'">
      <div class="cw-kpi-label">{{ widget.title || 'KPI' }}</div>
      <div class="cw-kpi-value" :class="dirClass">
        <span class="kv-num">{{ kpiText }}</span>
        <span v-if="kpiSuffix" class="kv-unit">{{ kpiSuffix }}</span>
      </div>
      <div v-if="widget.data?.delta" class="cw-kpi-delta" :class="dirClass">
        <el-icon :size="12"><component :is="deltaIcon" /></el-icon>
        {{ widget.data.delta.value }}<template v-if="kpiPctText">（{{ kpiPctText }}）</template>
        <span class="dd-cmp">{{ widget.data.delta.compared }}</span>
      </div>
      <div v-else-if="widget.data" class="cw-kpi-sub">
        {{ metricLabel }}<template v-if="widget.data.field_label && widget.data.field"> · {{ widget.data.field_label }}</template>
      </div>
      <div v-if="widget.data?.goal" class="cw-kpi-goal">
        <span class="kg-track"><i class="kg-bar" :style="{ width: Math.min(100, widget.data.percent || 0) + '%' }" /></span>
        <span class="kg-txt">目标 {{ widget.data.goal_text || widget.data.goal }}</span>
      </div>
    </template>

    <!-- 仪表盘卡 -->
    <template v-else-if="widget.type === 'gauge'">
      <EChart v-if="widget.data" :option="gaugeOption" :height="bodyHeight" />
    </template>

    <!-- 排行榜卡 -->
    <template v-else-if="widget.type === 'rank'">
      <div v-if="widget.data?.items?.length" class="cw-rank">
        <div v-for="(it, i) in widget.data.items" :key="it.name" class="rk-row">
          <span class="rk-medal" :class="`rk-${i < 3 ? i + 1 : 'n'}`">{{ i < 3 ? ['🥇','🥈','🥉'][i] : i + 1 }}</span>
          <span class="rk-name" :title="it.name">{{ it.name }}</span>
          <span class="rk-bar-track">
            <i class="rk-bar" :style="{ width: rankPct(it.value) }" />
          </span>
          <span class="rk-val">{{ rankVal(it.value) }}</span>
        </div>
      </div>
      <div v-else class="cw-blank">
        <el-icon :size="20"><TrophyBase /></el-icon>
        <span>该分组下没有数据</span>
      </div>
    </template>

    <!-- 进度条卡 -->
    <template v-else-if="widget.type === 'progress'">
      <div v-if="widget.data?.mode === 'goal'" class="cw-progress cw-progress-goal">
        <div class="pg-main">
          <span class="pg-num">{{ widget.data.percent }}%</span>
          <span class="pg-sub">{{ widget.data.value_text || widget.data.value }} / {{ widget.data.goal_text || widget.data.goal }}</span>
        </div>
        <div class="pg-track"><i class="pg-bar" :style="{ width: Math.min(100, widget.data.percent || 0) + '%' }" /></div>
      </div>
      <div v-else-if="widget.data?.segments?.length" class="cw-progress cw-progress-stack">
        <div class="pg-stack-track">
          <i v-for="(s, i) in widget.data.segments" :key="s.name"
             class="pg-stack-seg" :class="`seg-${i % 8}`"
             :style="{ width: s.percent + '%' }" :title="`${s.name} ${s.value}（${s.percent}%）`" />
        </div>
        <div class="pg-legend">
          <span v-for="(s, i) in widget.data.segments" :key="s.name" class="pg-leg-item">
            <i class="pg-dot" :class="`seg-${i % 8}`" />{{ s.name }}
            <b>{{ s.percent }}%</b>
          </span>
        </div>
      </div>
      <div v-else class="cw-blank">
        <el-icon :size="20"><Histogram /></el-icon>
        <span>缺少分组或目标值配置</span>
      </div>
    </template>

    <!-- 状态板卡 -->
    <template v-else-if="widget.type === 'status'">
      <div v-if="widget.data?.items?.length" class="cw-status">
        <div v-for="(it, i) in widget.data.items" :key="it.name" class="st-row">
          <i class="st-dot" :class="`seg-${i % 8}`" />
          <span class="st-name" :title="it.name">{{ it.name }}</span>
          <span class="st-bar"><i :class="`seg-${i % 8}`" :style="{ width: Math.min(100, it.percent || 0) + '%' }" /></span>
          <span class="st-val">{{ statusVal(it) }}</span>
        </div>
      </div>
      <div v-else class="cw-blank">
        <el-icon :size="20"><Warning /></el-icon>
        <span>没有状态数据</span>
      </div>
    </template>

    <!-- 图表卡 -->
    <template v-else-if="widget.type === 'chart'">
      <EChart v-if="hasChartData" :option="chartOption" :height="bodyHeight" />
      <div v-else class="cw-blank">
        <el-icon :size="20"><DataLine /></el-icon>
        <span>该分组下没有数据</span>
      </div>
    </template>

    <!-- 表格卡 -->
    <template v-else-if="widget.type === 'table'">
      <el-table v-if="widget.data?.rows?.length" :data="widget.data.rows" size="small"
                :max-height="tableHeight" class="cw-table" @row-click="r => emit('open-row', r)">
        <el-table-column v-for="c in widget.data.columns" :key="c.key"
                         :prop="c.key" :label="c.label" show-overflow-tooltip min-width="110" />
      </el-table>
      <div v-else class="cw-blank">
        <el-icon :size="20"><Grid /></el-icon>
        <span>没有符合条件的记录</span>
      </div>
      <div v-if="widget.data?.total > widget.data?.rows?.length" class="cw-foot">
        共 {{ widget.data.total }} 条，显示前 {{ widget.data.rows.length }} 条
      </div>
    </template>

    <!-- 列表卡 -->
    <template v-else-if="widget.type === 'list'">
      <div v-if="widget.data?.items?.length" class="cw-list">
        <div v-for="(it, i) in widget.data.items" :key="it.id ?? i" class="cw-li"
             @click="emit('open-row', it)">
          <span class="cl-main">
            <span class="cl-title">{{ it.title }}</span>
            <span v-if="it.sub" class="cl-sub">{{ it.sub }}</span>
          </span>
          <span class="cl-meta">
            <el-tag v-for="t in it.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
            <span v-if="it.time" class="cl-time">{{ shortTime(it.time) }}</span>
          </span>
        </div>
      </div>
      <div v-else class="cw-blank">
        <el-icon :size="20"><Document /></el-icon>
        <span>暂无内容</span>
      </div>
    </template>

    <!-- 文本卡 -->
    <template v-else-if="widget.type === 'text'">
      <div v-if="widget.text" class="cw-md" v-html="html" />
      <div v-else class="cw-blank"><span>在编辑里写点说明文字</span></div>
    </template>

    <!-- 编辑态新卡片 / 尚未取数 -->
    <div v-else class="cw-blank">
      <el-icon :size="20"><Plus /></el-icon>
      <span>保存后显示数据</span>
    </div>
  </div>
</template>

<script setup>
/**
 * 单张驾驶舱卡片的渲染器
 *
 * 只认后端 /data 返回的「成品数据」结构，不做任何取数。
 * 编辑器里的实时预览复用同一个组件，保证「预览 = 保存后看到的」。
 *
 * `screen` 为 true 时是全屏大屏模式：调色板换成霓虹系（大屏底色深、
 * 卡片透明），字号加大 —— 大屏是投在墙上给人扫一眼的，与桌面浏览
 * 是两种阅读距离。
 */
import { computed } from 'vue'
import {
  CaretTop, CaretBottom, Minus, WarningFilled, Grid,
  Document, DataLine, Plus, TrophyBase, Histogram, Warning,
} from '@element-plus/icons-vue'
import { axisStyle, chartTheme, tooltipStyle } from '../utils/theme'
import { miniMarkdown } from '../utils/md'
import { formatSize } from '../utils/format'
import EChart from './EChart.vue'

const props = defineProps({
  widget: { type: Object, required: true },
  bodyHeight: { type: String, default: '260px' },
  tableHeight: { type: Number, default: 300 },
  /** 全屏大屏模式：霓虹调色板 + 放大字号 */
  screen: { type: Boolean, default: false },
  /** 大屏当前主题 key：换主题时图表 option 必须重算（cssVar 不具响应性） */
  screenTheme: { type: String, default: '' },
})
const emit = defineEmits(['open-row'])

const METRIC_LABELS = { count: '计数', sum: '合计', avg: '平均', min: '最小值', max: '最大值' }

/** 大屏专用霓虹色板：深底上要的是「亮」，品牌色系在大屏底色上会发闷 */
const SCREEN_COLORS = ['#22d3ee', '#818cf8', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#a78bfa', '#2dd4bf']
const SCREEN_THEMES = {
  nebula: ['#22d3ee', '#818cf8', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#a78bfa', '#2dd4bf'],
  aurora: ['#a78bfa', '#f472b6', '#60a5fa', '#34d399', '#fbbf24', '#22d3ee', '#e879f9', '#818cf8'],
  abyss: ['#2dd4bf', '#38bdf8', '#34d399', '#fbbf24', '#a78bfa', '#f472b6', '#7dd3fc', '#22d3ee'],
}

const palette = computed(() => {
  if (!props.screen) return chartTheme()
  // 大屏模式不能用 chartTheme()：它读的是 html 根令牌（可能是浅色），
  // 而大屏容器里永远是我们自己那套深色底 + 霓虹点缀，必须显式给值
  const colors = SCREEN_THEMES[props.screenTheme] || SCREEN_THEMES.nebula
  return {
    dark: true,
    text: '#e8ecf4',
    muted: '#8b96ab',
    line: 'rgba(148,163,184,.22)',
    split: 'rgba(148,163,184,.12)',
    card: '#0a1020',
    primary: colors[0],
    colors,
  }
})

const isEmpty = computed(() => {
  if (props.widget.type === 'text') return !props.widget.text
  return props.widget.data == null && !props.widget.error
})

const metricLabel = computed(() => METRIC_LABELS[props.widget.data?.metric] || '计数')

/** byte 单位要走人类可读的 KB/MB，而不是后端指标里的「万」 */
const statText = computed(() => {
  const d = props.widget.data
  if (!d) return '—'
  if (props.widget.unit === 'byte' && typeof d.raw === 'number') return formatSize(d.raw)
  return d.value
})

/** 单位后缀：byte 已经并进数值了，不再重复显示 */
const suffix = computed(() => {
  const u = props.widget.unit
  if (!u || u === 'byte') return ''
  return u
})

const unitSuffix = computed(() => suffix.value)

const pctText = computed(() => {
  const p = props.widget.data?.delta?.pct
  return p == null ? '' : `${p > 0 ? '+' : ''}${p}%`
})

const dir = computed(() => props.widget.data?.delta?.direction || 'flat')
const dirClass = computed(() => `d-${dir.value}`)
const deltaIcon = computed(() => ({ up: CaretTop, down: CaretBottom }[dir.value] || Minus))

function sparkH(v) {
  const arr = props.widget.data?.spark || []
  const max = Math.max(1, ...arr)
  return `${Math.max(8, Math.round((v / max) * 100))}%`
}

const hasChartData = computed(() => {
  const c = props.widget.data
  if (!c?.categories?.length) return false
  // 后端在没有分组值时会给一个「（空）」占位，全是 0 就不必画
  return c.series.some(s => (s.data || []).some(v => v))
})

/** 仪表盘：当前值 / 目标值 → 达成率 */
const gaugeOption = computed(() => {
  const d = props.widget.data
  const t = palette.value
  if (!d) return {}
  const pct = Math.min(d.percent ?? 0, 100)
  return {
    series: [{
      type: 'gauge',
      center: ['50%', '58%'],
      radius: '92%',
      startAngle: 210,
      endAngle: -30,
      min: 0,
      max: 100,
      splitNumber: 5,
      progress: {
        show: true, width: props.screen ? 16 : 12,
        itemStyle: { color: t.colors[0], shadowColor: t.colors[0], shadowBlur: props.screen ? 10 : 0 },
      },
      axisLine: { lineStyle: { width: props.screen ? 16 : 12, color: [[1, 'rgba(148,163,184,.18)']] } },
      axisTick: { show: false },
      splitLine: { length: 6, distance: 4, lineStyle: { color: 'rgba(148,163,184,.4)' } },
      axisLabel: { distance: 18, color: t.muted, fontSize: props.screen ? 12 : 10 },
      pointer: { show: false },
      anchor: { show: false },
      title: { show: false },
      detail: {
        offsetCenter: [0, '2%'],
        formatter: () => `${d.percent}%`,
        color: t.colors[0],
        fontSize: props.screen ? 34 : 26,
        fontWeight: 700,
      },
      data: [{ value: pct }],
    }],
  }
})

/** 排行榜进度条宽度：相对榜首 */
function rankPct(v) {
  const items = props.widget.data?.items || []
  const max = Math.max(1, ...items.map(x => x.value))
  return `${Math.max(2, Math.round((v / max) * 100))}%`
}
function rankVal(v) {
  const m = props.widget.data?.metric
  return m && m !== 'count'
    ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1))
    : String(v)
}

/** KPI 数值/单位 */
const kpiText = computed(() => {
  const d = props.widget.data
  if (!d) return '—'
  if (props.widget.unit === 'byte' && typeof d.raw === 'number') return formatSize(d.raw)
  return d.value || '—'
})
const kpiSuffix = computed(() => {
  const u = props.widget.unit
  if (!u || u === 'byte') return ''
  return u
})
const kpiPctText = computed(() => {
  const p = props.widget.data?.delta?.pct
  return p == null ? '' : `${p > 0 ? '+' : ''}${p}%`
})

function statusVal(it) {
  const m = props.widget.data?.metric
  const v = it.value
  if (m && m !== 'count') return Number.isInteger(v) ? v.toLocaleString() : Number(v).toFixed(1)
  return String(v)
}

const chartOption = computed(() => {
  const c = props.widget.data
  const t = palette.value
  // 大屏模式下不能用 axisStyle()：它读的是 html 根令牌（可能是浅色系），
  // 深底上会发白刺眼 —— 用调色板重建一套
  const axis = props.screen
    ? {
        axisLine: { lineStyle: { color: t.line } },
        axisTick: { show: false },
        axisLabel: { color: t.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: t.split, type: 'dashed' } },
      }
    : axisStyle()
  if (!c) return {}
  const kind = c.chart || 'bar'
  const cats = c.categories.map(x => (String(x).length > 10 ? String(x).slice(0, 10) + '…' : x))
  const seriesData = c.series[0]?.data || []
  const name = c.series[0]?.name || '数量'
  const big = props.screen

  if (kind === 'pie' || kind === 'donut') {
    return {
      tooltip: { trigger: 'item', ...tooltipStyle() },
      legend: {
        type: 'scroll', bottom: 0, icon: 'circle',
        textStyle: { color: t.muted, fontSize: big ? 13 : 11 },
      },
      color: t.colors,
      series: [{
        name: name,
        type: 'pie',
        radius: kind === 'donut' ? ['42%', '66%'] : ['0%', '66%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: t.card, borderWidth: 2 },
        label: { color: t.text, fontSize: big ? 13 : 11, formatter: '{b} {d}%' },
        labelLine: { lineStyle: { color: t.line } },
        data: cats.map((k, i) => ({ name: k, value: seriesData[i] })),
      }],
    }
  }

  if (kind === 'radar') {
    const max = Math.max(1, ...seriesData.map(v => Math.abs(v || 0)))
    return {
      tooltip: { ...tooltipStyle() },
      color: t.colors,
      radar: {
        indicator: cats.map(k => ({ name: k, max: Math.ceil(max * 1.2) })),
        radius: '64%',
        center: ['50%', '52%'],
        axisName: { color: t.muted, fontSize: big ? 13 : 11 },
        splitArea: { areaStyle: { color: ['transparent'] } },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,.25)' } },
        axisLine: { lineStyle: { color: 'rgba(148,163,184,.35)' } },
      },
      series: [{
        type: 'radar',
        symbolSize: big ? 6 : 4,
        data: [{
          value: seriesData,
          name,
          areaStyle: { color: t.colors[0], opacity: t.dark ? 0.35 : 0.2 },
          lineStyle: { color: t.colors[0], width: 2 },
          itemStyle: { color: t.colors[0] },
        }],
      }],
    }
  }

  // 横向条形：类目轴放 y，一眼比大小比竖柱轻松
  if (kind === 'bar_h') {
    const idx = [...cats.keys()].sort((a, b) => (seriesData[a] || 0) - (seriesData[b] || 0))
    return {
      grid: { left: 4, right: 24, top: 6, bottom: 2, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...tooltipStyle() },
      xAxis: { type: 'value', ...axis },
      yAxis: {
        type: 'category',
        data: idx.map(i => cats[i]),
        ...axis,
        splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: big ? 13 : 11, interval: 0 },
      },
      series: [{
        name,
        type: 'bar',
        data: idx.map(i => seriesData[i]),
        barMaxWidth: big ? 24 : 18,
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: t.colors[0] },
              { offset: 1, color: t.colors[1] || t.colors[0] },
            ],
          },
        },
        label: {
          show: true, position: 'right', color: t.muted,
          fontSize: big ? 13 : 11, formatter: p => rankVal(p.value),
        },
      }],
    }
  }

  const isLine = kind === 'line' || kind === 'area'
  return {
    grid: { left: 4, right: 14, top: 16, bottom: 2, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: isLine ? 'line' : 'shadow' }, ...tooltipStyle() },
    xAxis: {
      type: 'category',
      data: cats,
      ...axis,
      splitLine: { show: false },
      axisLabel: { color: t.muted, fontSize: big ? 13 : 11, interval: 0, rotate: cats.length > 6 ? 32 : 0 },
    },
    yAxis: { type: 'value', ...axis },
    series: [{
      name,
      type: isLine ? 'line' : 'bar',
      data: seriesData,
      smooth: isLine,
      symbolSize: big ? 7 : 6,
      barMaxWidth: 28,
      itemStyle: { color: t.colors[0], borderRadius: isLine ? 0 : [4, 4, 0, 0] },
      lineStyle: { color: t.colors[0], width: 2 },
      areaStyle: kind === 'area'
        ? {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: t.colors[0] },
                { offset: 1, color: 'rgba(0,0,0,0)' },
              ],
            },
            opacity: t.dark ? 0.45 : 0.25,
          }
        : undefined,
    }],
  }
})

const html = computed(() => miniMarkdown(props.widget.text || ''))

function shortTime(s) {
  const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/)
  if (!m) return s
  const today = new Date()
  const same = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  return `${m[1]}-${m[2]}-${m[3]}` === same ? `${m[4]}:${m[5]}` : `${m[2]}-${m[3]} ${m[4]}:${m[5]}`
}
</script>

<style scoped>
.cw { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.cw-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 8px; margin-bottom: 10px;
}
.cw-title { font-size: var(--text-base); font-weight: 600; color: var(--text-primary); }
.cw-unit { font-size: var(--text-xs); color: var(--text-tertiary); }

.cw-error {
  display: flex; align-items: flex-start; gap: 6px;
  font-size: var(--text-sm); color: var(--danger);
  background: var(--danger-bg); border-radius: var(--radius-sm); padding: 8px 10px;
}

.cw-blank {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; min-height: 90px; color: var(--text-tertiary); font-size: var(--text-sm);
}

/* ---- 指标卡 ---- */
.cw-stat-label { font-size: var(--text-sm); color: var(--text-tertiary); font-weight: 500; }
.cw-stat-value {
  display: flex; align-items: baseline; gap: 5px; margin-top: 4px;
  font-family: var(--font-display); letter-spacing: -1px;
}
.sv-num {
  font-size: 30px; font-weight: 680; line-height: 1.15;
  color: var(--text-primary); font-variant-numeric: tabular-nums;
}
.sv-unit { font-size: var(--text-base); color: var(--text-tertiary); font-weight: 500; }
.cw-stat-value.d-up .sv-num { color: var(--primary); }
.cw-stat-value.d-down .sv-num { color: var(--info); }

.cw-stat-delta {
  display: flex; align-items: center; gap: 4px; margin-top: 7px; margin-bottom: 2px;
  font-size: var(--text-sm); font-weight: 600;
}
/* 不套用股票的涨红跌绿：这里是通用业务指标，「涨」不一定是好事。
   方向由箭头表达，颜色只做弱强调，避免误读。 */
.cw-stat-delta.d-up { color: var(--primary); }
.cw-stat-delta.d-down { color: var(--info); }
.cw-stat-delta.d-flat { color: var(--text-tertiary); }
.dd-cmp { color: var(--text-tertiary); font-weight: 400; margin-left: 2px; }
.cw-stat-sub { margin-top: 7px; margin-bottom: 2px; font-size: var(--text-xs); color: var(--text-tertiary); }

.cw-spark { display: flex; align-items: flex-end; gap: 2px; height: 24px; margin-top: auto; padding-top: 10px; }
.cw-spark i {
  flex: 1; min-width: 2px; background: var(--primary-bg-strong);
  border-radius: 2px 2px 0 0;
}

/* ---- KPI 卡（科技感指标） ---- */
.cw-kpi-label { font-size: var(--text-sm); color: var(--text-tertiary); font-weight: 500; }
.cw-kpi-value {
  display: flex; align-items: baseline; gap: 5px; margin-top: 4px;
  font-family: var(--font-display); letter-spacing: -1px;
}
.kv-num {
  font-size: 34px; font-weight: 700; line-height: 1.15;
  color: var(--text-primary); font-variant-numeric: tabular-nums;
  text-shadow: 0 0 18px var(--primary-glow);
}
.kv-unit { font-size: var(--text-base); color: var(--text-tertiary); font-weight: 500; }
.cw-kpi-value.d-up .kv-num { color: var(--primary); }
.cw-kpi-value.d-down .kv-num { color: var(--info); }
.cw-kpi-delta {
  display: flex; align-items: center; gap: 4px; margin-top: 6px;
  font-size: var(--text-sm); font-weight: 600;
}
.cw-kpi-delta.d-up { color: var(--primary); }
.cw-kpi-delta.d-down { color: var(--info); }
.cw-kpi-delta.d-flat { color: var(--text-tertiary); }
.cw-kpi-sub { margin-top: 6px; font-size: var(--text-xs); color: var(--text-tertiary); }
.cw-kpi-goal { margin-top: auto; padding-top: 10px; }
.kg-track {
  display: block; height: 6px; border-radius: var(--radius-full);
  background: var(--bg-sunken); overflow: hidden;
}
.kg-bar { display: block; height: 100%; border-radius: var(--radius-full); background: linear-gradient(90deg, var(--primary), var(--primary-light)); }
.kg-txt { display: block; margin-top: 5px; font-size: var(--text-xs); color: var(--text-tertiary); }

/* ---- 进度条卡 ---- */
.cw-progress { display: flex; flex-direction: column; gap: 10px; justify-content: center; flex: 1; min-height: 0; }
.cw-progress-goal .pg-main { display: flex; align-items: baseline; gap: 10px; }
.pg-num { font-size: 30px; font-weight: 700; color: var(--text-primary); font-family: var(--font-display); }
.pg-sub { font-size: var(--text-sm); color: var(--text-tertiary); }
.pg-track { height: 10px; border-radius: var(--radius-full); background: var(--bg-sunken); overflow: hidden; }
.pg-bar { display: block; height: 100%; border-radius: var(--radius-full); background: linear-gradient(90deg, var(--primary), var(--primary-light)); box-shadow: 0 0 10px var(--primary-glow); transition: width .6s var(--ease-out); }
.pg-stack-track { display: flex; height: 14px; border-radius: var(--radius-full); overflow: hidden; background: var(--bg-sunken); }
.pg-stack-seg { display: block; height: 100%; transition: width .6s var(--ease-out); }
.pg-legend { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 6px; }
.pg-leg-item { display: inline-flex; align-items: center; gap: 5px; font-size: var(--text-xs); color: var(--text-secondary); }
.pg-dot { width: 7px; height: 7px; border-radius: 50%; }
.pg-leg-item b { color: var(--text-primary); margin-left: 2px; }

/* ---- 状态板卡 ---- */
.cw-status { display: flex; flex-direction: column; gap: 6px; flex: 1; min-height: 0; overflow: auto; }
.st-row { display: grid; grid-template-columns: 16px 1fr 1.2fr auto; align-items: center; gap: 10px; padding: 5px 2px; }
.st-dot { width: 9px; height: 9px; border-radius: 50%; box-shadow: 0 0 6px currentColor; }
.st-name { font-size: var(--text-base); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-bar { height: 6px; border-radius: var(--radius-full); background: var(--bg-sunken); overflow: hidden; }
.st-bar i { display: block; height: 100%; border-radius: var(--radius-full); transition: width .6s var(--ease-out); }
.st-val { font-size: var(--text-sm); font-weight: 650; color: var(--text-primary); font-variant-numeric: tabular-nums; min-width: 3ch; text-align: right; }

/* 科技感分段色 */
.seg-0 { background: #6366f1; }
.seg-1 { background: #22d3ee; }
.seg-2 { background: #34d399; }
.seg-3 { background: #fbbf24; }
.seg-4 { background: #f472b6; }
.seg-5 { background: #a78bfa; }
.seg-6 { background: #2dd4bf; }
.seg-7 { background: #60a5fa; }

/* ---- 表格 / 列表 ---- */
.cw-table :deep(.el-table__cell) { padding: 6px 0; }
.cw-foot { margin-top: 8px; font-size: var(--text-xs); color: var(--text-tertiary); }
/* 卡片高度是用户自由拖出来的，内容高于卡片时在卡内滚动，
   不许溢出去压到别人的卡片上 */
.cw-table { flex: 1; min-height: 0; }
.cw-list { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: auto; }
.cw-li {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 8px 2px; border-bottom: 1px solid var(--border-light); cursor: pointer;
}
.cw-li:last-child { border-bottom: none; }
.cw-li:hover .cl-title { color: var(--primary); }
.cl-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.cl-title {
  font-size: var(--text-base); color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  transition: color var(--duration) var(--ease-out);
}
.cl-sub {
  font-size: var(--text-xs); color: var(--text-tertiary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 380px;
}
.cl-meta { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.cl-time { font-size: var(--text-xs); color: var(--text-tertiary); font-variant-numeric: tabular-nums; }

/* ---- 文本卡 ---- */
.cw-md { font-size: var(--text-base); color: var(--text-secondary); line-height: 1.7; flex: 1; min-height: 0; overflow: auto; }
.cw-md :deep(h3), .cw-md :deep(h4), .cw-md :deep(h5) {
  margin: 0 0 6px; color: var(--text-primary); font-size: var(--text-md); font-weight: 650;
}
.cw-md :deep(p) { margin: 0 0 6px; }
.cw-md :deep(ul) { margin: 0; padding-left: 18px; }
.cw-md :deep(li) { margin-bottom: 3px; }
.cw-md :deep(strong) { color: var(--text-primary); }
.cw-md :deep(code) {
  font-family: var(--font-mono); font-size: var(--text-xs);
  background: var(--bg-subtle); padding: 1px 5px; border-radius: var(--radius-xs);
}

/* ---- 排行榜 ---- */
.cw-rank { display: flex; flex-direction: column; gap: 2px; flex: 1; min-height: 0; overflow: auto; }
.rk-row {
  display: grid;
  grid-template-columns: 26px minmax(64px, 1.1fr) minmax(60px, 1.6fr) auto;
  align-items: center; gap: 8px;
  padding: 5px 2px;
  border-bottom: 1px solid var(--border-light);
}
.rk-row:last-child { border-bottom: none; }
.rk-medal {
  font-size: var(--text-base); text-align: center;
  color: var(--text-tertiary); font-variant-numeric: tabular-nums;
}
.rk-medal.rk-n { font-size: var(--text-xs); }
.rk-name {
  font-size: var(--text-base); color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rk-bar-track {
  height: 8px; border-radius: var(--radius-full);
  background: var(--bg-sunken); overflow: hidden;
}
.rk-bar {
  display: block; height: 100%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--primary), var(--primary-light));
  transition: width .6s var(--ease-out);
}
.rk-val {
  font-size: var(--text-base); font-weight: 650; color: var(--text-primary);
  font-variant-numeric: tabular-nums; min-width: 3ch; text-align: right;
}

/* ---- 全屏大屏模式 ----
   背景由大屏容器提供，卡片这里只负责「亮字 + 透明底」。
   字号全部加大：大屏是投在墙上扫一眼的，不是凑近读的。 */
.cw-screen .cw-title { font-size: 16px; letter-spacing: .5px; }
.cw-screen .cw-stat-label { font-size: 14px; }
.cw-screen .sv-num { font-size: 44px; }
.cw-screen .sv-unit { font-size: 16px; }
.cw-screen .cw-stat-sub { font-size: 12.5px; }
.cw-screen .cw-stat-delta { font-size: 14px; }
.cw-screen .rk-row { padding: 9px 2px; gap: 12px; }
.cw-screen .rk-medal { font-size: 18px; }
.cw-screen .rk-name { font-size: 15px; }
.cw-screen .rk-bar-track { height: 10px; }
.cw-screen .rk-val { font-size: 16px; }
.cw-screen .cw-li { padding: 11px 2px; }
.cw-screen .cl-title { font-size: 15px; }
.cw-screen .cw-blank { min-height: 140px; font-size: 15px; }
</style>
