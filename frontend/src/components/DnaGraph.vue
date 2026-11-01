<template>
  <div class="dna-graph">
    <!-- 图例 + 筛选 + 操作 -->
    <div class="dg-toolbar">
      <div class="dg-legend">
        <span class="lg-item">
          <span class="lg-dot doc" />文件<span class="lg-n">{{ counts.document }}</span>
        </span>
        <span class="lg-item">
          <span class="lg-dot sec" />章节<span class="lg-n">{{ counts.section }}</span>
        </span>
        <span class="lg-item">
          <span class="lg-dot rec" />记录<span class="lg-n">{{ counts.record }}</span>
        </span>
      </div>

      <div class="dg-filters">
        <el-radio-group v-model="filter" size="small" aria-label="筛选节点类型">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="document">文件</el-radio-button>
          <el-radio-button value="record">记录</el-radio-button>
        </el-radio-group>
        <el-button size="small" @click="reheat">
          <el-icon><Refresh /></el-icon>重排
        </el-button>
        <el-button size="small" @click="fit">
          <el-icon><FullScreen /></el-icon>适应
        </el-button>
      </div>
    </div>

    <div ref="host" class="dg-canvas" />

    <!-- 选中节点的详情 -->
    <transition name="dg-slide">
      <div v-if="selected" class="dg-detail">
        <div class="dg-detail-head">
          <span class="dg-detail-kind">{{ kindLabel(selected.kind) }}</span>
          <span class="dg-detail-title">{{ selected.label }}</span>
          <el-button size="small" text @click="selected = null">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
        <div class="dg-detail-meta">
          <span v-for="(v, k) in selected.meta || {}" :key="k" class="dg-meta-item">
            {{ metaLabel(k) }}：{{ v }}
          </span>
        </div>
        <div v-if="selectedEdges.length" class="dg-detail-links">
          <span class="dg-links-label">连着 {{ selectedEdges.length }} 个：</span>
          <span v-for="e in selectedEdges.slice(0, 8)" :key="e.id" class="dg-link-chip">
            {{ e.label }}
          </span>
        </div>
      </div>
    </transition>

    <div v-if="!nodes.length" class="dg-empty">
      还没有可连起来的脉络 —— 文件与记录之间还没有建立关联
    </div>
  </div>
</template>

<script setup>
/**
 * 养料 DNA 的「关联脉络图」
 *
 * 画的是这批资料的三层结构：
 *   文件（document） —— 资料本体
 *   章节（section）  —— 文件里的标题骨架（OpenKB 的 PageIndex 思路）
 *   记录（record）   —— 挂在文件上的业务记录与知识库笔记
 *
 * 边的三种语义各有一种画法：
 *   structure 文件 → 它的章节（骨架，实线浅灰）
 *   attach    文件 → 挂载它的记录（实线主色）
 *   relation  记录 → 记录（虚线绿色）
 *
 * 节点样式全部跟主题走（明/暗都要成立），不写死颜色。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Network } from 'vis-network/standalone'
import { DataSet } from 'vis-data/standalone'
import { chartTheme, cssVar, isDark } from '../utils/theme'

const props = defineProps({
  graph: { type: Object, default: () => ({ nodes: [], edges: [], stats: {} }) },
})
const emit = defineEmits(['select'])

const host = ref(null)
const filter = ref('all')
const selected = ref(null)
let net = null
let nodesDS = null
let edgesDS = null

const counts = computed(() => {
  const c = { document: 0, section: 0, record: 0 }
  for (const n of props.graph?.nodes || []) {
    if (c[n.kind] !== undefined) c[n.kind]++
  }
  return c
})

const nodes = computed(() => {
  const all = props.graph?.nodes || []
  if (filter.value === 'all') return all
  if (filter.value === 'document') {
    // 「文件」视图把章节也带上：章节是文件的骨架，
    // 只剩孤零零的文件节点，图就没有脉络可言了
    return all.filter(n => n.kind === 'document' || n.kind === 'section')
  }
  return all.filter(n => n.kind === 'record')
})

const visibleEdges = computed(() => {
  const ids = new Set(nodes.value.map(n => n.id))
  return (props.graph?.edges || []).filter(e => ids.has(e.source) && ids.has(e.target))
})

const selectedEdges = computed(() => {
  if (!selected.value) return []
  return visibleEdges.value.filter(e => e.source === selected.value.id || e.target === selected.value.id)
})

function kindLabel(kind) {
  return { document: '文件', section: '章节', record: '记录' }[kind] || kind
}

function metaLabel(k) {
  return {
    type: '类型', words: '字数', chunks: '块数', entity_type: '模型',
    document_id: '所属文件', level: '层级', ext: '扩展名',
  }[k] || k
}

const KIND_COLOR = {
  document: () => cssVar('--primary', '#5b5fc7'),
  section: () => cssVar('--accent-slate', '#5a6478'),
  record: () => cssVar('--accent-green', '#2f8f4e'),
}

const EDGE_COLOR = {
  structure: () => cssVar('--border-strong', '#d1d5dd'),
  attach: () => cssVar('--primary', '#5b5fc7'),
  relation: () => cssVar('--accent-green', '#2f8f4e'),
}

function buildNodes() {
  const t = chartTheme()
  const textStrong = cssVar('--text-primary', '#17181d')
  return nodes.value.map(n => {
    const c = KIND_COLOR[n.kind]?.() || t.primary
    const isDoc = n.kind === 'document'
    const isSec = n.kind === 'section'
    return {
      id: n.id,
      label: truncate(n.label || '', isSec ? 14 : 18),
      title: `${n.label}\n${metaText(n)}`,
      shape: isSec ? 'box' : 'dot',
      size: isDoc ? 26 : 14,
      borderWidth: isDoc ? 2 : 1,
      color: {
        background: isDoc ? c : (isSec ? t.card : c),
        border: c,
        highlight: { background: c, border: c },
        hover: { background: c, border: c },
      },
      font: {
        color: isSec ? textStrong : '#ffffff',
        size: isDoc ? 12 : 11,
        face: 'system-ui, -apple-system, "PingFang SC", sans-serif',
        background: isSec ? t.card : 'transparent',
      },
      margin: isSec ? { top: 5, bottom: 5, left: 8, right: 8 } : undefined,
      shapeProperties: { borderRadius: 6 },
    }
  })
}

function buildEdges() {
  const t = chartTheme()
  return visibleEdges.value.map(e => {
    const c = EDGE_COLOR[e.kind]?.() || t.line
    return {
      id: e.id,
      from: e.source,
      to: e.target,
      label: e.kind === 'structure' ? '' : (e.label || ''),
      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      color: { color: c, highlight: c, hover: c, opacity: e.kind === 'structure' ? 0.55 : 0.9 },
      width: e.kind === 'structure' ? 1 : 1.6,
      dashes: e.kind === 'relation' ? [5, 4] : false,
      smooth: { enabled: true, type: 'dynamic', roundness: 0.2 },
      font: {
        color: t.text, size: 10, align: 'middle',
        background: t.card, strokeWidth: 4, strokeColor: t.card,
      },
    }
  })
}

function metaText(n) {
  const m = n.meta || {}
  const parts = []
  if (m.type) parts.push(m.type)
  if (m.words) parts.push(`${m.words} 字`)
  if (m.chunks) parts.push(`${m.chunks} 块`)
  if (m.entity_type) parts.push(m.entity_type)
  return parts.join(' · ')
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

function draw() {
  if (!net) return
  const ns = buildNodes()
  const es = buildEdges()
  nodesDS.clear()
  edgesDS.clear()
  nodesDS.add(ns)
  edgesDS.add(es)
  net.setOptions({ physics: { enabled: true } })
  // 先粗调一次，等物理稳定后再调一次：
  // 只在开头 fit 的话，力学稳定过程中节点还会继续往外扩 ——
  // 实测节点被甩到 y=2300（画布才 458 高），整张图在视口外，谁也点不到。
  setTimeout(() => {
    try { net.fit({ animation: { duration: 320 } }) } catch (e) { /* 节点为空时 fit 会抛 */ }
  }, 120)
}

function reheat() {
  if (!net) return
  net.setOptions({ physics: { enabled: true, barnesHut: { gravitationalConstant: -4200 } } })
  net.stabilize(180)
}

function fit() {
  try { net?.fit({ animation: { duration: 320 } }) } catch (e) { /* 没有节点 */ }
}

onMounted(() => {
  nodesDS = new DataSet([])
  edgesDS = new DataSet([])
  net = new Network(host.value, { nodes: nodesDS, edges: edgesDS }, {
    layout: { improvedLayout: true },
    physics: {
      enabled: true,
      barnesHut: {
        // 斥力要克制：画布只有 460 高，48 个节点挤在里面，
        // 斥力一大就被甩到视口外（点不到，也看不清脉络）。
        gravitationalConstant: -4200,
        springLength: 120,
        springConstant: 0.035,
        damping: 0.75,
        avoidOverlap: 0.9,
      },
      stabilization: { iterations: 600, fit: true },
    },
    interaction: { hover: true, dragNodes: true, zoomView: true, tooltipDelay: 160 },
    nodes: { chosen: true },
    edges: { selectionWidth: 1.5, hoverWidth: 0.4 },
  })
  net.on('stabilizationIterationsDone', () => {
    // 物理稳定后再自适应一次 —— 这一步是「点得到节点」的关键
    try { net.fit({ animation: { duration: 260 } }) } catch (e) { /* 没有节点 */ }
  })
  net.on('click', (p) => {
    // vis 的 click 事件给的是 nodes 数组，node 字段只有
    // selectNode / hoverNode 才有 —— 只看 p.node 会永远点不中。
    const id = p.node ?? p.nodes?.[0]
    if (!id) { selected.value = null; return }
    const n = (props.graph?.nodes || []).find(x => x.id === id)
    if (n) {
      selected.value = n
      emit('select', n)
    }
  })
  net.on('doubleClick', (p) => {
    const id = p.node ?? p.nodes?.[0]
    if (!id) return
    const n = (props.graph?.nodes || []).find(x => x.id === id)
    // 双击文件节点 → 直接跳到数据中心看这个文件
    if (n?.kind === 'document') {
      window.location.hash = `/library?doc=${n.ref_id}`
    }
  })
  // 开发期把 network 实例挂出去：自动化测试要拿到节点的真实坐标，
  // 才能点得准（物理布局的节点位置是算出来的，不是猜的）。
  if (import.meta.env.DEV) window.__dnaNet = net
  draw()
})

watch([nodes, visibleEdges], draw, { deep: true })
watch(isDark, draw)

onBeforeUnmount(() => {
  try { net?.destroy() } catch (e) { /* 已经销毁了 */ }
  net = null
})
</script>

<style scoped>
.dg-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 0 4px 10px;
}
.dg-legend { display: flex; gap: 14px; flex-wrap: wrap; }
.lg-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
}
.lg-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}
.lg-dot.doc { background: var(--primary); }
.lg-dot.sec { background: var(--accent-slate); border-radius: 2px; }
.lg-dot.rec { background: var(--accent-green); }
.lg-n { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.dg-filters { margin-left: auto; display: flex; align-items: center; gap: 8px; }

.dg-canvas {
  height: 460px;
  width: 100%;
  border-radius: 10px;
  background:
    radial-gradient(circle at 1px 1px, var(--border-light) 1px, transparent 0) 0 0 / 22px 22px;
  border: 1px solid var(--border-light);
  overflow: hidden;
}

.dg-detail {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-subtle);
}
.dg-detail-head { display: flex; align-items: center; gap: 8px; }
.dg-detail-kind {
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-100);
  border-radius: 5px;
  padding: 1px 6px;
}
.dg-detail-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dg-detail-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}
.dg-detail-links { margin-top: 6px; font-size: 12px; color: var(--text-tertiary); }
.dg-links-label { margin-right: 6px; }
.dg-link-chip {
  display: inline-block;
  margin: 2px 4px 0 0;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
}

.dg-empty {
  height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

.dg-slide-enter-active, .dg-slide-leave-active { transition: opacity .18s ease, transform .18s ease; }
.dg-slide-enter-from, .dg-slide-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
