<template>
  <div class="dna-graph">
    <!-- ================= 工具条 ================= -->
    <div class="dg-bar">
      <div class="dg-bar-main">
        <el-input
          v-model="q"
          size="small"
          class="dg-search"
          placeholder="在图里找：文件名、章节、基因"
          clearable
        >
          <template #prefix><el-icon><Search /></el-icon></template>
          <template #suffix>
            <span v-if="q" class="dg-search-hit">{{ searchHit?.count || 0 }} 处命中</span>
          </template>
        </el-input>

        <div class="dg-grow" />

        <el-select v-model="geneLimit" size="small" class="dg-select" aria-label="基因显示数量">
          <el-option label="热门 12 条基因" :value="12" />
          <el-option label="热门 20 条基因" :value="20" />
          <el-option label="全部基因" :value="-1" />
          <el-option label="不显示基因" :value="0" />
        </el-select>

        <el-radio-group v-model="filter" size="small" aria-label="筛选链">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="knowledge">知识链</el-radio-button>
          <el-radio-button value="evidence">证据链</el-radio-button>
        </el-radio-group>

        <el-dropdown trigger="click" @command="setDensity">
          <el-button size="small" class="dg-density">
            <el-icon><Operation /></el-icon>{{ densityLabel }}
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="tight">紧凑 · 行距 20</el-dropdown-item>
              <el-dropdown-item command="normal">标准 · 行距 24</el-dropdown-item>
              <el-dropdown-item command="loose">宽松 · 行距 32</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <div class="dg-zoom">
          <el-button size="small" text title="放大" @click="zoomBy(0.8)">
            <el-icon><ZoomIn /></el-icon>
          </el-button>
          <el-button size="small" text title="缩小" @click="zoomBy(1.25)">
            <el-icon><ZoomOut /></el-icon>
          </el-button>
          <el-button size="small" text title="适应窗口" @click="resetView">
            <el-icon><FullScreen /></el-icon>
          </el-button>
        </div>

        <el-button size="small" @click="reshuffle">
          <el-icon><Refresh /></el-icon>重排
        </el-button>
      </div>

      <div class="dg-bar-sub">
        <!-- 节点类型 -->
        <div class="dg-group">
          <span class="dg-group-title">节点</span>
          <button
            v-for="l in legendItems"
            :key="l.key"
            type="button"
            class="lg-item lg-btn"
            :class="{ 'is-off': !l.on }"
            :title="l.on ? `隐藏${l.label}` : `显示${l.label}`"
            @click="toggleNodeKind(l.key)"
          >
            <span class="lg-glyph" :class="l.key" />{{ l.label }}<span class="lg-n">{{ l.count }}</span>
          </button>
        </div>

        <!-- 基因种类（按碱基色分四类） -->
        <div class="dg-group">
          <span class="dg-group-title">碱基</span>
          <button
            v-for="k in kindLegend"
            :key="k.key"
            class="lg-base"
            :class="{ 'is-off': !k.on }"
            :style="{ '--bc': k.color }"
            type="button"
            :title="k.on ? '点击隐藏这一类基因' : '点击显示这一类基因'"
            @click="toggleKind(k.key)"
          >
            {{ k.letter }}
          </button>
        </div>

        <!-- 连接类型：没有这个图例就分不清「骨架横档」和「碱基对」 -->
        <div class="dg-group dg-group-edges">
          <span class="dg-group-title">连接</span>
          <span v-for="e in edgeLegend" :key="e.key" class="dg-edge-item" :class="e.key">
            <i class="dg-edge-line" />{{ e.label }}<span class="lg-n">{{ e.count }}</span>
          </span>
        </div>

        <div class="dg-grow" />
        <div class="dg-stats">{{ statsText }}</div>
      </div>
    </div>

    <!-- ================= 双螺旋画布 ================= -->
    <div ref="viewport" class="dg-viewport">
      <div class="dg-stage" :style="stageStyle">
        <!-- 两条链的「骨架线」：跟着列位置走，不是写死百分比 -->
        <span v-if="showLeft" class="dg-rail dg-rail-l" :style="{ left: layout.xLeft + 'px' }" />
        <span v-if="showRight" class="dg-rail dg-rail-r" :style="{ left: layout.xRight + 'px' }" />

        <div ref="host" class="dg-canvas" :style="{ height: H + 'px' }" />

        <!-- 标题层：文字用 DOM 画，不跟节点挤在同一张 canvas 上 -->
        <div class="dg-overlay">
          <!-- 选中节点的光标环：canvas 上的节点只有几十像素，
               光靠底色变化在双链密集处还是认不出来，
               这里再叠一个会呼吸的环，位置跟着节点走 -->
          <span v-if="selMark" class="dg-sel-ring" :style="selMark.style" />
          <button
            v-for="lb in labels"
            :key="lb.id"
            :ref="el => setLbl(lb.id, el)"
            class="dg-lbl"
            :class="[lb.side, 'dg-lbl-' + lb.kind, { 'is-dim': lb.dim, 'is-sel': lb.sel, 'is-hit': lb.hit }]"
            type="button"
            :title="lb.title"
            @click.stop="selectById(lb.id)"
          >
            <span v-if="lb.code" class="dg-lbl-code" :style="{ color: lb.color }">{{ lb.code }}</span>
            <span class="dg-lbl-text">{{ lb.text }}</span>
          </button>
        </div>

        <div v-if="showLeft" class="dg-strand dg-strand-l" :style="{ left: layout.xLeft + 'px' }">
          <span class="dg-strand-dot" />知识链<span class="dg-strand-n">{{ layout.leftLen }}</span>
        </div>
        <div v-if="showRight" class="dg-strand dg-strand-r" :style="{ left: layout.xRight + 'px' }">
          <span class="dg-strand-dot" />证据链<span class="dg-strand-n">{{ layout.rightLen }}</span>
        </div>
      </div>
    </div>

    <!-- ================= 选中节点的详情 ================= -->
    <transition name="dg-slide">
      <div v-if="selected" class="dg-detail">
        <div class="dg-detail-head">
          <span class="dg-detail-kind" :style="detailKindStyle">{{ kindLabel(selected.kind) }}</span>
          <span class="dg-detail-title">{{ selected.label }}</span>
          <span class="dg-detail-acts">
            <el-button size="small" text title="复制标题" @click="copyTitle">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
            <el-button size="small" text title="关闭" @click="selected = null">
              <el-icon><Close /></el-icon>
            </el-button>
          </span>
        </div>
        <div v-if="detailMetaList.length" class="dg-detail-meta">
          <span v-for="m in detailMetaList" :key="m.k" class="dg-meta-item">
            <span class="dg-meta-k">{{ m.label }}</span>
            <span class="dg-meta-v">{{ m.value }}</span>
          </span>
        </div>
        <div v-if="selectedEdges.length" class="dg-detail-links">
          <span class="dg-links-label">连着 {{ selectedEdges.length }} 个：</span>
          <button
            v-for="e in selectedEdges.slice(0, 12)"
            :key="e.id"
            type="button"
            class="dg-link-chip"
            @click="jumpToEdge(e)"
          >
            <i class="dg-link-kind" :class="e.kind" />{{ edgeLabel(e) }}
          </button>
          <span v-if="selectedEdges.length > 12" class="dg-links-more">
            还有 {{ selectedEdges.length - 12 }} 个
          </span>
        </div>
      </div>
    </transition>

    <div v-if="!nodes.length" class="dg-empty">
      <el-icon class="dg-empty-icon"><DataLine /></el-icon>
      <div class="dg-empty-title">还没有可连起来的脉络</div>
      <div class="dg-empty-sub">文件与记录之间还没有建立关联 —— 先去养料库吸收一批资料吧</div>
    </div>
  </div>
</template>

<script setup>
/**
 * 养料 DNA 的「DNA 双螺旋图谱」
 *
 * 视觉隐喻：把资料摊成一条测序轨道
 *   左链 = 知识链（基因 gene + 文件 document + 章节 section）—— 知识与骨架
 *   右链 = 证据链（记录 record）—— 挂在骨架上的东西
 *   中间的碱基对 = 跨链的边（encode / attach）
 *   同链的边（structure / relation）是这一侧的横档
 *
 * 布局为什么不用力导向（这是上一版最大的坑）：
 *   力导向的节点会飘 —— 实测被甩到 y=2300，而画布才 458 高，
 *   整张图在视口外，谁也点不中；而且每次刷新位置都不一样，读不出结构。
 *   现在自己算坐标：两列固定 x，节点按 y 序排好，物理引擎整个关掉。
 *   位置是确定的 → 可读、可点、可截图。
 *
 * ★ 排版事故的根因（2026-11 修复）：
 *   computeLayout() 写好了却**从来没被调用**。
 *   于是 layout 一直是初始值 { pos: {}, H: 460 }：
 *     - pos 为空 → 每个节点都落到 (0, 0) → 六十二个标签全叠在左上角
 *     - H 恒为 460 → 画布高度与节点数无关
 *   实测 62 个标签产生 966 对压字（全部 100% 重叠）。
 *   现在 draw() 每次都先算布局，并且按算出的高度同步画布尺寸。
 *
 * 基因会很多（上限 60 条），全画出来会把结构埋掉，
 * 所以默认只放「热门」的一批，其余用工具栏的开关调。
 *
 * 节点造型：
 *   基因 = 胶囊（带碱基编号 A-01，颜色按基因种类分四种碱基色）
 *   文件 = 胶囊（中性色，染色体）  章节 = 小方块  记录 = 圆形
 *
 * 配色全部来自设计令牌（明/暗两套都成立），不写死颜色。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { Network } from 'vis-network/standalone'
import { DataSet } from 'vis-data/standalone'
import { ElMessage } from 'element-plus'
import { cssVar, isDark } from '../utils/theme'

const props = defineProps({
  graph: { type: Object, default: () => ({ nodes: [], edges: [], stats: {} }) },
  // 定位：外部（比如染色体清单）说「看这个节点」，
  // 图会把它选并滚到视野中央
  focusId: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const host = ref(null)
const viewport = ref(null)
const filter = ref('all')
const selected = ref(null)
const seed = ref(0)
const hoverId = ref(null)
const geneLimit = ref(12)
const offKinds = ref(new Set())
const q = ref('')
const offNodeKinds = ref(new Set())
const density = ref('normal')

/** 密度档：只改行距，不改别的 */
const DENSITY = {
  tight: { min: 20, max: 26, label: '紧凑' },
  normal: { min: 24, max: 32, label: '标准' },
  loose: { min: 32, max: 42, label: '宽松' },
}
const densityLabel = computed(() => DENSITY[density.value]?.label || '标准')

function setDensity(k) {
  if (DENSITY[k]) density.value = k
}

/** 图例：带计数，点一下切换这一类节点的显示 */
const legendItems = computed(() => {
  const all = props.graph?.nodes || []
  const count = (k) => all.filter((n) => n.kind === k).length
  return [
    { key: 'gene', label: '基因', count: count('gene') },
    { key: 'document', label: '文件', count: count('document') },
    { key: 'section', label: '章节', count: count('section') },
    { key: 'record', label: '记录', count: count('record') },
    { key: 'library', label: '养料库', count: count('library') },
  ].filter((l) => l.count > 0)
    .map((l) => ({ ...l, on: !offNodeKinds.value.has(l.key) }))
})

function toggleNodeKind(kind) {
  const s = new Set(offNodeKinds.value)
  if (s.has(kind)) s.delete(kind)
  else s.add(kind)
  offNodeKinds.value = s
}

/** 连接类型图例：分不清「骨架横档」和「碱基对」，图就只是一堆线 */
const EDGE_KINDS = [
  { key: 'structure', label: '骨架' },
  { key: 'attach', label: '挂载' },
  { key: 'encode', label: '编码' },
  { key: 'relation', label: '关联' },
]
const edgeLegend = computed(() => {
  const edges = props.graph?.edges || []
  return EDGE_KINDS.map((k) => ({
    ...k,
    count: edges.filter((e) => e.kind === k.key).length,
  })).filter((e) => e.count > 0)
})

const statsText = computed(() => {
  const n = nodes.value.length
  const e = visibleEdges.value.length
  const total = (props.graph?.nodes || []).length
  if (!total) return '还没有数据'
  return `显示 ${n}/${total} 个节点 · ${e} 条连接`
})

let net = null
let nodesDS = null
let edgesDS = null
let ro = null
let rafId = 0

/* ------------------------------------------------------------------ *
 * 颜色工具：把设计令牌解析成能画到 canvas 上的具体色值
 * ------------------------------------------------------------------ */

// 解析 #rgb / #rrggbb / rgb() / rgba()
function parseColor(c) {
  if (!c) return { r: 128, g: 128, b: 128 }
  const s = String(c).trim()
  if (s[0] === '#') {
    let h = s.slice(1)
    if (h.length === 3) h = h.split('').map((x) => x + x).join('')
    if (h.length === 8) h = h.slice(0, 6)
    const n = parseInt(h, 16)
    if (Number.isNaN(n)) return { r: 128, g: 128, b: 128 }
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
  }
  const m = s.match(/rgba?\(([^)]+)\)/)
  if (m) {
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number)
    return { r: p[0] || 0, g: p[1] || 0, b: p[2] || 0 }
  }
  return { r: 128, g: 128, b: 128 }
}

// a 占 t 份，b 占 (1-t) 份
function mix(a, b, t) {
  const A = parseColor(a)
  const B = parseColor(b)
  const f = (x, y) => Math.max(0, Math.min(255, Math.round(x * t + y * (1 - t))))
  return `rgb(${f(A.r, B.r)}, ${f(A.g, B.g)}, ${f(A.b, B.b)})`
}

const BASES = ['A', 'T', 'G', 'C']
const BASE_VAR = { A: '--primary', T: '--accent-green', G: '--warning', C: '--accent-slate' }

/**
 * 四色碱基色板
 *
 * 为什么要在 JS 里再调一次色：
 *   accent 色板（绿 / 石板）没有暗色档 —— 浅色主题下够清楚，
 *   到了深色主题就是一团暗影。所以这里按主题把基色往正文色方向推：
 *   浅色下压深一点（提高白底对比度），深色下提亮（深底上跳出来）。
 */
const palette = computed(() => {
  const text = cssVar('--text-primary', '#17181d')
  const card = cssVar('--bg-card', '#ffffff')
  const out = {}
  for (const b of BASES) {
    const raw = cssVar(BASE_VAR[b], '#888888')
    out[b] = {
      raw,
      line: isDark.value ? mix(raw, text, 0.26) : mix(raw, text, 0.08),
      fill: isDark.value ? mix(card, raw, 0.20) : mix('#ffffff', raw, 0.86),
      soft: isDark.value ? mix(card, raw, 0.10) : mix('#ffffff', raw, 0.93),
      text: isDark.value ? mix(raw, text, 0.42) : mix(raw, text, 0.16),
    }
  }
  // 中性色：文件与章节走灰阶，把彩色让给基因
  const neutral = cssVar('--text-secondary', '#4b4f59')
  out.neutral = {
    raw: neutral,
    line: isDark.value ? mix(neutral, text, 0.18) : mix(neutral, text, 0.05),
    fill: isDark.value ? mix(card, neutral, 0.14) : mix('#ffffff', neutral, 0.92),
    soft: isDark.value ? mix(card, neutral, 0.07) : mix('#ffffff', neutral, 0.96),
    text: isDark.value ? mix(neutral, text, 0.35) : mix(neutral, text, 0.12),
  }
  const evi = cssVar('--accent-green', '#2f8f4e')
  out.evidence = {
    raw: evi,
    line: isDark.value ? mix(evi, text, 0.30) : mix(evi, text, 0.06),
    fill: isDark.value ? mix(card, evi, 0.20) : mix('#ffffff', evi, 0.86),
    soft: isDark.value ? mix(card, evi, 0.10) : mix('#ffffff', evi, 0.93),
    text: isDark.value ? mix(evi, text, 0.45) : mix(evi, text, 0.14),
  }
  return out
})

/* ------------------------------------------------------------------ *
 * 基因种类 → 碱基色
 * ------------------------------------------------------------------ */

const GENE_KINDS = [
  { key: 'method', letter: 'A', label: '方法' },
  { key: 'fact', letter: 'T', label: '事实' },
  { key: 'experience', letter: 'G', label: '经验' },
  { key: 'interface', letter: 'C', label: '接口' },
  { key: 'policy', letter: 'A', label: '规约' },
]
const GENE_KIND_MAP = Object.fromEntries(GENE_KINDS.map((k) => [k.key, k]))

function geneKindOf(n) {
  return n?.meta?.gene_kind || ''
}

function baseOfGene(n) {
  const k = GENE_KIND_MAP[geneKindOf(n)]
  if (k) return k.letter
  // 未知种类：按哈希落到四色里，别崩也别全一样
  let h = 0
  const s = String(n?.id || '')
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return BASES[h % BASES.length]
}

const kindLegend = computed(() => {
  const P = palette.value
  const seen = new Map()
  for (const n of props.graph?.nodes || []) {
    if (n.kind !== 'gene') continue
    const k = geneKindOf(n)
    if (!k) continue
    seen.set(k, (seen.get(k) || 0) + 1)
  }
  return GENE_KINDS.filter((k) => seen.has(k.key)).map((k) => ({
    key: k.key,
    letter: k.letter,
    label: `${k.label} ${seen.get(k.key)}`,
    count: seen.get(k.key),
    color: P[k.letter].line,
    on: !offKinds.value.has(k.key),
  }))
})

function toggleKind(key) {
  const s = new Set(offKinds.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  offKinds.value = s
}

/* ------------------------------------------------------------------ *
 * 数据准备
 * ------------------------------------------------------------------ */

const showLeft = computed(() => filter.value !== 'evidence')
const showRight = computed(() => filter.value !== 'knowledge')

/**
 * 基因：先按种类筛，再按「表达度 + 置信度」取热门的一批
 *
 * 注意还要看图例开关（offNodeKinds）：
 *   之前这里只看种类筛选，图例里把「基因」关掉之后，
 *   visibleGenes 仍然有值 → 会被摊进左链 → 白占行、把别的行挤走。
 */
const visibleGenes = computed(() => {
  if (geneLimit.value === 0) return []
  if (offNodeKinds.value.has('gene')) return []
  const all = (props.graph?.nodes || []).filter((n) => n.kind === 'gene')
  const kept = all.filter((n) => !offKinds.value.has(geneKindOf(n)))
  const sorted = kept.slice().sort((a, b) => {
    const u = (b.meta?.usage || 0) - (a.meta?.usage || 0)
    if (u) return u
    const c = (b.meta?.confidence || 0) - (a.meta?.confidence || 0)
    if (c) return c
    return String(a.id).localeCompare(String(b.id))
  })
  return geneLimit.value > 0 ? sorted.slice(0, geneLimit.value) : sorted
})

const geneIds = computed(() => new Set(visibleGenes.value.map((n) => n.id)))

/** 搜索命中：节点名里有词的，外加它的一跳邻居（不然命中了也看不出关系） */
const searchHit = computed(() => {
  const kw = (q.value || '').trim().toLowerCase()
  if (!kw) return null
  const all = props.graph?.nodes || []
  const hit = new Set()
  for (const n of all) {
    const hay = `${n.label || ''} ${n.meta?.source_title || ''} ${n.meta?.gene_kind || ''}`.toLowerCase()
    if (hay.includes(kw)) hit.add(n.id)
  }
  if (!hit.size) return { ids: new Set(), count: 0 }
  // 带上邻居，保留上下文
  const keep = new Set(hit)
  for (const e of props.graph?.edges || []) {
    if (hit.has(e.source)) keep.add(e.target)
    if (hit.has(e.target)) keep.add(e.source)
  }
  return { ids: keep, count: hit.size, direct: hit }
})

const nodes = computed(() => {
  const all = props.graph?.nodes || []
  let out
  if (filter.value === 'all') {
    out = all.filter((n) => n.kind !== 'gene' || geneIds.value.has(n.id))
  } else if (filter.value === 'knowledge') {
    out = all.filter(
      (n) => n.kind === 'gene' || n.kind === 'document' || n.kind === 'section' || n.kind === 'library'
    ).filter((n) => n.kind !== 'gene' || geneIds.value.has(n.id))
  } else {
    out = all.filter((n) => n.kind === 'record')
  }
  // 图例关掉的类别不画
  out = out.filter((n) => !offNodeKinds.value.has(n.kind))
  // 搜索：只留命中节点与它的一跳邻居
  if (searchHit.value) out = out.filter((n) => searchHit.value.ids.has(n.id))
  return out
})

const visibleEdges = computed(() => {
  const ids = new Set(nodes.value.map((n) => n.id))
  return (props.graph?.edges || []).filter((e) => ids.has(e.source) && ids.has(e.target))
})

const selectedEdges = computed(() => {
  if (!selected.value) return []
  return visibleEdges.value.filter(
    (e) => e.source === selected.value.id || e.target === selected.value.id)
})

function kindLabel(kind) {
  return {
    document: '文件', section: '章节', record: '记录',
    gene: '基因', library: '养料库',
  }[kind] || '节点'
}

function metaLabel(k) {
  return {
    type: '类型', words: '字数', chunks: '块数', entity_type: '模型',
    document_id: '所属文件', level: '层级', ext: '扩展名',
    gene_kind: '种类', source_kind: '来源形态', source_title: '出处',
    usage: '表达度', confidence: '置信度', destroyed: '原文',
    note: '说明',
  }[k] || k
}

function edgeLabel(e) {
  const other = e.source === selected.value?.id ? e.target : e.source
  const n = (props.graph?.nodes || []).find((x) => x.id === other)
  const tag = { structure: '骨架', attach: '挂载', relation: '关联', encode: '编码' }[e.kind] || '关系'
  return `${tag}${e.label ? ' · ' + e.label : ''}${n?.label ? ' → ' + n.label : ''}`
}

/** 详情里的元数据：键值对形式，便于排版 */
const detailMetaList = computed(() => {
  const m = { ...(selected.value?.meta || {}) }
  if (selected.value?.kind === 'gene') {
    if (m.gene_kind) m.gene_kind = GENE_KIND_MAP[m.gene_kind]?.label || m.gene_kind
    if (m.destroyed) m.destroyed = '已销毁（蒸馏自源码）'
  }
  return Object.entries(m)
    .filter(([k, v]) => v !== '' && v !== null && v !== undefined)
    .map(([k, v]) => ({ k, label: metaLabel(k), value: String(v) }))
})

const detailKindStyle = computed(() => {
  const n = selected.value
  let p = palette.value.neutral
  if (n?.kind === 'gene') p = palette.value[baseOfGene(n)]
  else if (n?.kind === 'record') p = palette.value.evidence
  else if (n?.kind === 'library') p = palette.value.A
  return { '--ac-fg': p.text, '--ac-bg': p.fill, '--ac-line': p.line }
})

function copyTitle() {
  const t = selected.value?.label || ''
  if (!t) return
  try {
    navigator.clipboard?.writeText(t)
    ElMessage.success('已复制标题')
  } catch (e) {
    ElMessage.warning('复制失败，请手动选中')
  }
}

/** 点关联芯片 → 跳到另一端节点 */
function jumpToEdge(e) {
  const other = e.source === selected.value?.id ? e.target : e.source
  if (other) selectById(other)
}

/* ------------------------------------------------------------------ *
 * 布局：两列固定坐标（不碰物理引擎）
 * ------------------------------------------------------------------ */

const PAD_TOP = 52        // 顶部留白：给「知识链 / 证据链」两个链头
const PAD_BOTTOM = 28
const TARGET_H = 940      // 图区目标高度；行多的时候自动收窄行距
// 行距下限 20px：标签行高约 15px（12px 字号 × 1.25），
// 行距 20px 时相邻标签还留 5px 缝，不会压字；
// 再密就真的叠上去了（实测 20px 是压字与浪费空间之间的分界）。
const MIN_PITCH = 20
const MAX_PITCH = 32

const layout = ref({
  pos: {}, W: 900, H: 460, leftLen: 1, rightLen: 1,
  xLeft: 0, xRight: 0, pitch: MIN_PITCH, lblMaxL: 250, lblMaxR: 260,
})

/**
 * 每个节点的「排版元数据」（碱基色 / 编号）
 *
 * 为什么单独放一份，而不是直接写在节点对象上：
 *   节点对象来自 props.graph，是响应式的。在里面写字段会触发
 *   watch(..., {deep:true}) → 重画 → 又写字段 → 无限递归
 *   （浏览器报「Maximum recursive updates exceeded」）。
 *   所以这里只读节点、不改节点，排版信息另存一份。
 */
const nodeMeta = shallowRef({})
const metaOf = (id) => nodeMeta.value[id] || { base: 'A', code: '' }

function computeLayout() {
  const W = Math.max(560, host.value?.clientWidth || 900)
  const list = nodes.value
  const edges = visibleEdges.value
  const byId = new Map(list.map((n) => [n.id, n]))

  const docs = list.filter((n) => n.kind === 'document')
  const recs = list.filter((n) => n.kind === 'record')
  const libs = list.filter((n) => n.kind === 'library')

  const push = (map, k, v) => {
    if (!map.has(k)) map.set(k, [])
    const arr = map.get(k)
    if (!arr.includes(v)) arr.push(v)
  }

  // ---- 边归类（不假设方向，契约里 attach / encode 方向是固定的） ----
  const secOfDoc = new Map()     // documentId -> [sectionId]
  const secParent = new Map()    // sectionId -> documentId
  const relAdj = new Map()       // recordId -> [recordId]
  const docRecs = new Map()      // documentId -> [recordId]
  const recDocs = new Map()      // recordId -> [documentId]
  const genesOf = new Map()      // targetId -> [geneId]   （encode 边）
  const geneTarget = new Map()   // geneId -> targetId

  for (const e of edges) {
    const s = byId.get(e.source)
    const t = byId.get(e.target)
    if (!s || !t) continue
    if (e.kind === 'structure') {
      const doc = s.kind === 'document' ? s : (t.kind === 'document' ? t : null)
      const sec = s.kind === 'section' ? s : (t.kind === 'section' ? t : null)
      if (doc && sec) {
        secParent.set(sec.id, doc.id)
        push(secOfDoc, doc.id, sec.id)
      }
    } else if (e.kind === 'attach') {
      const doc = s.kind === 'document' ? s : (t.kind === 'document' ? t : null)
      const rec = s.kind === 'record' ? s : (t.kind === 'record' ? t : null)
      if (doc && rec) {
        push(docRecs, doc.id, rec.id)
        push(recDocs, rec.id, doc.id)
      }
    } else if (e.kind === 'relation') {
      if (s.kind === 'record' && t.kind === 'record') {
        push(relAdj, s.id, t.id)
        push(relAdj, t.id, s.id)
      }
    } else if (e.kind === 'encode') {
      const gene = s.kind === 'gene' ? s : (t.kind === 'gene' ? t : null)
      const src = s.kind === 'gene' ? t : s
      if (gene && src) {
        push(genesOf, src.id, gene.id)
        geneTarget.set(gene.id, src.id)
      }
    }
  }

  // ---- 左链的文件顺序 ----
  let docOrder = docs.slice().sort((a, b) => {
    const w = (b.meta?.words || 0) - (a.meta?.words || 0)
    if (w) return w
    return String(a.id).localeCompare(String(b.id), 'zh')
  })
  if (seed.value % 2 === 1) docOrder = docOrder.slice().reverse()

  // ---- 右链：记录。先用关系子图做一次 DFS，让互相关联的记录挨着 ----
  const deg = (id) => (relAdj.get(id) || []).length
  const recSeed = recs.slice().sort(
    (a, b) => deg(b.id) - deg(a.id) || String(a.id).localeCompare(String(b.id)))
  const visited = new Set()
  let recOrder = []
  const startAt = seed.value % Math.max(1, recSeed.length)
  const rotated = recSeed.slice(startAt).concat(recSeed.slice(0, startAt))
  for (const r of rotated) {
    if (visited.has(r.id)) continue
    const queue = [r.id]
    while (queue.length) {
      const id = queue.shift()
      if (visited.has(id)) continue
      visited.add(id)
      recOrder.push(byId.get(id))
      for (const nb of relAdj.get(id) || []) if (!visited.has(nb)) queue.push(nb)
    }
  }
  for (const r of recs) if (!visited.has(r.id)) recOrder.push(r)

  // ---- 重心法微调：让「挂载关系」的两端在 y 上尽量对齐 ----
  // 用归一化位置（0~1）而不是行号，两条链长度不同时对齐才不会歪。
  for (let it = 0; it < 10; it++) {
    const docU = new Map(docOrder.map((d, i) => [d.id, i / Math.max(1, docOrder.length)]))
    const recU = new Map(recOrder.map((r, i) => [r.id, i / Math.max(1, recOrder.length)]))
    const rScore = new Map()
    for (const r of recOrder) {
      const a = (recDocs.get(r.id) || []).map((id) => docU.get(id)).filter((v) => v !== undefined)
      const b = (relAdj.get(r.id) || []).map((id) => recU.get(id)).filter((v) => v !== undefined)
      const parts = []
      if (a.length) parts.push([0.68, a.reduce((x, y) => x + y, 0) / a.length])
      if (b.length) parts.push([0.32, b.reduce((x, y) => x + y, 0) / b.length])
      rScore.set(
        r.id,
        parts.length
          ? parts.reduce((s, p) => s + p[0] * p[1], 0) / parts.reduce((s, p) => s + p[0], 0)
          : recU.get(r.id)
      )
    }
    recOrder = recOrder.slice().sort(
      (a, b) => (rScore.get(a.id) - rScore.get(b.id)) || String(a.id).localeCompare(String(b.id)))

    const recU2 = new Map(recOrder.map((r, i) => [r.id, i / Math.max(1, recOrder.length)]))
    const dScore = new Map()
    for (const d of docOrder) {
      const a = (docRecs.get(d.id) || []).map((id) => recU2.get(id)).filter((v) => v !== undefined)
      dScore.set(d.id, a.length ? a.reduce((x, y) => x + y, 0) / a.length : docU.get(d.id))
    }
    docOrder = docOrder.slice().sort(
      (a, b) => (dScore.get(a.id) - dScore.get(b.id)) || String(a.id).localeCompare(String(b.id)))
  }

  // ---- 摊平成左链的行：养料库 → （每份文件：它的基因 → 文件 → 章节） ----
  // 基因紧挨着它的出处，encode 边就成了短短一档，不会把结构压住。
  const leftRows = []
  const libGenes = []
  for (const lib of libs) {
    for (const gid of genesOf.get(lib.id) || []) libGenes.push(gid)
  }
  const usedGenes = new Set()
  const takeGenes = (targetId) => {
    const out = []
    for (const gid of genesOf.get(targetId) || []) {
      if (usedGenes.has(gid)) continue
      usedGenes.add(gid)
      out.push(gid)
    }
    return out
  }

  for (const gid of libGenes) {
    const g = byId.get(gid)
    if (g) leftRows.push(g)
  }
  for (const lib of libs) leftRows.push(lib)

  for (const d of docOrder) {
    for (const gid of takeGenes(d.id)) {
      const g = byId.get(gid)
      if (g) leftRows.push(g)
    }
    leftRows.push(d)
    for (const sid of secOfDoc.get(d.id) || []) {
      const s = byId.get(sid)
      if (s) leftRows.push(s)
    }
  }
  // 出处是记录、或没有出处的基因：也要留在左链（知识在左、出处在右，
  // encode 边跨过去就是碱基对），插到与出处高度相近的位置。
  const orphans = []
  for (const g of visibleGenes.value) {
    if (usedGenes.has(g.id)) continue
    usedGenes.add(g.id)
    orphans.push(g)
  }
  const recIndexOf = new Map(recOrder.map((r, i) => [r.id, i]))
  orphans.sort((a, b) => {
    const ia = recIndexOf.get(geneTarget.get(a.id)) ?? 99999
    const ib = recIndexOf.get(geneTarget.get(b.id)) ?? 99999
    return ia - ib
  })
  for (const g of orphans) {
    const ri = recIndexOf.get(geneTarget.get(g.id))
    const targetU = ri === undefined ? 1 : (ri + 0.5) / Math.max(1, recOrder.length)
    let at = leftRows.length
    for (let i = 0; i < leftRows.length; i++) {
      if ((i + 0.5) / Math.max(1, leftRows.length) >= targetU) { at = i; break }
    }
    leftRows.splice(at, 0, g)
  }
  // 没挂到任何文件下的章节也补进去
  const inLeft = new Set(leftRows.map((n) => n.id))
  for (const n of list) {
    if (n.kind === 'section' && !inLeft.has(n.id)) {
      leftRows.push(n)
      inLeft.add(n.id)
    }
  }

  // ---- 编号（碱基编号） ----
  // 只写进 meta（普通对象），不碰响应式的节点本身 —— 详见 nodeMeta 的注释
  const meta = {}
  const kindSeq = {}
  let docNo = 0
  for (const n of leftRows) {
    if (n.kind === 'gene') {
      const b = baseOfGene(n)
      kindSeq[b] = (kindSeq[b] || 0) + 1
      meta[n.id] = { base: b, code: `${b}-${String(kindSeq[b]).padStart(2, '0')}` }
    } else if (n.kind === 'document') {
      meta[n.id] = { base: 'N', code: `D-${String(++docNo).padStart(2, '0')}` }
    } else if (n.kind === 'section') {
      meta[n.id] = { base: 'N', code: '' }
    } else if (n.kind === 'library') {
      meta[n.id] = { base: 'L', code: '库' }
    }
  }
  for (const r of recOrder) {
    meta[r.id] = { base: 'E', code: '' }
  }
  // 章节继承所属文件的颜色：看颜色就知道这段骨架挂在哪份文件下面
  for (const [secId, docId] of secParent) {
    if (meta[secId] && meta[docId]) meta[secId].base = meta[docId].base
  }
  nodeMeta.value = meta

  const rightRows = recOrder

  // ---- 坐标 ----
  const leftLen = Math.max(leftRows.length, 1)
  const rightLen = Math.max(rightRows.length, 1)
  const rows = Math.max(leftLen, rightLen)
  const dens = DENSITY[density.value] || DENSITY.normal
  const pitch = Math.max(dens.min, Math.min(dens.max, (TARGET_H - PAD_TOP - PAD_BOTTOM) / rows))
  const span = rows * pitch
  const H = PAD_TOP + PAD_BOTTOM + span

  // 列位置：两链时左右分开；只看一条链时把它放在偏左 32% 处 ——
  // 标题都是往右排的（证据链）或往左排的（知识链），
  // 放在 42% 会让一大半画布空着，标签被挤在中间一小条里。
  const both = showLeft.value && showRight.value
  const xSingle = W * 0.32
  const xLeft = both ? W * 0.30 : xSingle
  const xRight = both ? W * 0.70 : xSingle

  const pos = {}
  leftRows.forEach((n, i) => {
    pos[n.id] = { x: xLeft, y: PAD_TOP + (i + 0.5) * (span / leftLen) }
  })
  rightRows.forEach((n, i) => {
    pos[n.id] = { x: xRight, y: PAD_TOP + (i + 0.5) * (span / rightLen) }
  })

  layout.value = {
    pos, W, H, leftLen, rightLen, xLeft, xRight, pitch,
    // 标题层的可用宽度：左边的往左排，右边的往右排，都不许出界
    lblMaxL: Math.max(56, Math.min(250, xLeft - 44)),
    lblMaxR: Math.max(56, Math.min(260, W - xRight - 28)),
  }
  return layout.value
}

const stageStyle = computed(() => ({
  '--lbl-max-l': (layout.value.lblMaxL || 250) + 'px',
  '--lbl-max-r': (layout.value.lblMaxR || 260) + 'px',
  height: (layout.value.H || 460) + 'px',
}))

/* ------------------------------------------------------------------ *
 * 悬停高亮：亮起整条链 + 相连的对侧节点，其余淡出
 * ------------------------------------------------------------------ */

function chainOf(n) {
  return n && n.kind === 'record' ? 'r' : 'l'
}

const hiSet = computed(() => {
  const out = new Set()
  const id = hoverId.value
  if (!id) return out
  const list = nodes.value
  const byId = new Map(list.map((n) => [n.id, n]))
  const side = chainOf(byId.get(id))
  for (const n of list) if (chainOf(n) === side) out.add(n.id)
  for (const e of visibleEdges.value) {
    if (out.has(e.source) && chainOf(byId.get(e.target)) !== side) out.add(e.target)
    if (out.has(e.target) && chainOf(byId.get(e.source)) !== side) out.add(e.source)
  }
  return out
})

/**
 * 把颜色往背景里压
 *
 * k 是「还剩多少原色」：
 *  - 悬停时压到 0.16 —— 鼠标扫过的那条链要跳出来，其余的赶紧让位
 *  - 选中时压到 0.42 —— 被点名的那一个要跳出来，
 *    但双链图的价值就在于看它跟谁配对，
 *    其余节点压太狠会连上下文一起压没了
 */
function dimmed(color, k = 0.16) {
  const card = cssVar('--bg-card', '#ffffff')
  return mix(card, color, k)
}

/* ------------------------------------------------------------------ *
 * 画到 vis-network 上
 * ------------------------------------------------------------------ */

function buildNodes() {
  const P = palette.value
  const hi = hiSet.value
  const dim = hoverId.value && hi.size > 0
  const pos = layout.value.pos
  // 选中的节点要**在图上看得见**。
  // 以前选中只让右侧弹详情框，图上的节点一点变化都没有 ——
  // 「双螺旋定位」跳过去之后，用户根本不知道自己在看哪一个。
  const selId = selected.value?.id || ''
  const isSelId = (id) => !!selId && id === selId

  return nodes.value.map((n) => {
    const p = pos[n.id] || { x: 0, y: 0 }
    const isSel = !!selId && n.id === selId
    const isGene = n.kind === 'gene'
    const isDoc = n.kind === 'document'
    const isSec = n.kind === 'section'
    const isRec = n.kind === 'record'
    const isLib = n.kind === 'library'
    // 选中一个节点时，其它的退到背景里 —— 只把选中项点亮就够了
    const faded = (dim && !hi.has(n.id)) || (isSelId(n.id) === false && !!selId)

    const m = metaOf(n.id)
    const base = isGene ? P[m.base || 'A']
      : isRec ? P.evidence
        : isLib ? P.A
          : P.neutral

    let color
    let font
    let shape = 'dot'
    let size = 13
    let borderWidth = 1.5
    let margin

    if (isGene) {
      // 基因 = 胶囊（圆角矩形），里面写碱基编号
      shape = 'box'
      margin = { top: 4, bottom: 4, left: 11, right: 11 }
      font = {
        face: 'SF Mono, ui-monospace, Menlo, Consolas, monospace',
        size: 10,
        color: base.text,
        bold: true,
      }
      color = {
        background: base.fill,
        border: base.line,
        highlight: { background: base.line, border: base.text },
        hover: { background: base.fill, border: base.text },
      }
      borderWidth = 1.5
    } else if (isLib) {
      // 养料库 = 一个更宽的根节点
      shape = 'box'
      margin = { top: 6, bottom: 6, left: 14, right: 14 }
      font = { size: 11, color: base.text, bold: true }
      color = {
        background: base.fill,
        border: base.line,
        highlight: { background: base.line, border: base.text },
        hover: { background: base.fill, border: base.text },
      }
      borderWidth = 1.8
    } else if (isDoc) {
      // 文件 = 胶囊（中性色：染色体）
      shape = 'box'
      margin = { top: 4, bottom: 4, left: 11, right: 11 }
      font = {
        face: 'SF Mono, ui-monospace, Menlo, Consolas, monospace',
        size: 10,
        color: base.text,
        bold: true,
      }
      color = {
        background: base.fill,
        border: base.line,
        highlight: { background: base.line, border: base.text },
        hover: { background: base.fill, border: base.text },
      }
      borderWidth = 1.4
    } else if (isSec) {
      // 章节 = 小方块
      shape = 'square'
      size = 9
      borderWidth = 1.2
      font = { size: 1, color: 'transparent' }
      color = {
        background: base.soft,
        border: base.line,
        highlight: { background: base.line, border: base.line },
        hover: { background: base.line, border: base.line },
      }
    } else {
      // 记录 = 圆形
      shape = 'dot'
      size = 13
      borderWidth = 1.6
      font = { size: 1, color: 'transparent' }
      color = {
        background: base.line,
        border: base.line,
        highlight: { background: base.text, border: base.text },
        hover: { background: base.text, border: base.text },
      }
    }

    if (isSel) {
      // 选中态：底色换成实心、边框加粗、描一圈高亮色 ——
      // 双链图上节点挨得很近，光换底色不够，得有「被点名」的重量差
      const accent = cssVar('--primary', '#5b5fc7')
      const text = base.text
      color = {
        background: accent,
        border: accent,
        highlight: { background: accent, border: text },
        hover: { background: accent, border: text },
      }
      if (font) font = { ...font, color: '#ffffff', bold: true }
      borderWidth = 3
    } else if (faded) {
      // 选中引起的变淡比悬停轻 —— 上下文还得看得见
      const k = selId ? 0.42 : 0.16
      color = {
        background: dimmed(color.background, k),
        border: dimmed(color.border, k),
        highlight: color.highlight,
        hover: color.hover,
      }
    }

    return {
      id: n.id,
      label: m.code || '',
      title: `${n.label}\n${metaText(n)}`,
      shape,
      size,
      margin,
      x: p.x,
      y: p.y,
      fixed: { x: true, y: true },
      borderWidth,
      color,
      font: faded ? { ...font, color: dimmed(font.color || '#888888', selId ? 0.42 : 0.16) } : font,
      shapeProperties: { borderRadius: 11 },
      widthConstraint: { maximum: 96 },
    }
  })
}

function buildEdges() {
  const P = palette.value
  const hi = hiSet.value
  const dim = hoverId.value && hi.size > 0
  const pos = layout.value.pos
  const line = cssVar('--border-strong', '#d1d5dd')
  const primary = cssVar('--primary', '#5b5fc7')

  return visibleEdges.value.map((e) => {
    const sp = pos[e.source]
    const tp = pos[e.target]
    const cross = sp && tp && Math.abs(sp.x - tp.x) > 40
    // 同链的边统一「从上往下」画：贝塞尔的弯向才一致，不会一会儿左一会儿右
    let from = e.source
    let to = e.target
    if (!cross && sp && tp && sp.y > tp.y) {
      from = e.target
      to = e.source
    }

    let c = line
    let width = 1
    let dashes = false
    let roundness = 0.18

    if (e.kind === 'encode') {
      // 基因 → 出处：跨链的是碱基对，同链的是短横档
      c = cross ? primary : mix(line, P.A.line, 0.45)
      width = cross ? 1.4 : 1.1
      roundness = cross ? 0.42 : 0.14
    } else if (e.kind === 'attach') {
      // 碱基对：文件 → 记录，跨链的连续贝塞尔
      c = primary
      width = 1.5
      roundness = 0.42
    } else if (e.kind === 'relation') {
      c = P.evidence.line
      width = 1.1
      dashes = [5, 4]
      roundness = 0.16
    } else {
      // structure：文件 → 章节，同链短横档
      c = mix(line, P.neutral.line, 0.5)
      width = 1
      roundness = 0.16
    }

    const smooth = cross
      ? { enabled: true, type: 'continuous', roundness }
      : { enabled: true, type: 'curvedCW', roundness }

    const touched = hi.has(e.source) && hi.has(e.target)
    if (dim && !touched) {
      c = dimmed(c)
      width = Math.max(0.6, width * 0.6)
    }

    return {
      id: e.id,
      from,
      to,
      label: '',
      arrows: { to: { enabled: false } },
      color: { color: c, highlight: c, hover: c, opacity: 1 },
      width,
      dashes,
      smooth,
      selectionWidth: 0,
      hoverWidth: 0,
      font: { size: 1, color: 'transparent' },
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
  if (m.level) parts.push(`第 ${m.level} 级`)
  if (m.gene_kind) parts.push(GENE_KIND_MAP[m.gene_kind]?.label || m.gene_kind)
  if (m.source_title) parts.push(`出自《${m.source_title}》`)
  if (m.usage) parts.push(`用过 ${m.usage} 次`)
  if (m.note) parts.push(m.note)
  return parts.join(' · ')
}

/* ------------------------------------------------------------------ *
 * 标题层（DOM）
 * ------------------------------------------------------------------ */

const lblEls = new Map()
function setLbl(id, el) {
  if (el) lblEls.set(id, el)
  else lblEls.delete(id)
}

const labels = computed(() => {
  const P = palette.value
  const hi = hiSet.value
  const dim = hoverId.value && hi.size > 0
  const selId = selected.value?.id || ''
  const hits = searchHit.value?.direct || null
  const list = []
  for (const n of nodes.value) {
    const side = chainOf(n) === 'r' ? 'r' : 'l'
    let color = P.neutral.text
    if (n.kind === 'gene') color = P[metaOf(n.id).base || 'A'].text
    else if (n.kind === 'record') color = P.evidence.text
    else if (n.kind === 'library') color = P.A.text
    list.push({
      id: n.id,
      side,
      kind: n.kind,
      code: n.kind === 'record' || n.kind === 'section' ? '' : (metaOf(n.id).code || ''),
      color,
      text: n.label || '',
      title: `${n.label}\n${metaText(n)}`,
      dim: (dim && !hi.has(n.id)) || (!!selId && n.id !== selId),
      sel: n.id === selId,
      hit: !!hits && hits.has(n.id),
    })
  }
  return list
})

/** 选中节点在画布上的位置（给脉冲环用） */
const selMark = ref(null)

function updateSelMark() {
  const id = selected.value?.id
  if (!id || !net) { selMark.value = null; return }
  const nd = net.body?.nodes?.[id]
  if (!nd) { selMark.value = null; return }
  const p = net.canvasToDOM({ x: nd.x, y: nd.y })
  selMark.value = {
    id,
    style: {
      '--x': `${p.x.toFixed(1)}px`,
      '--y': `${p.y.toFixed(1)}px`,
    },
  }
}

function syncLabels() {
  if (!net) return
  const bodyNodes = net.body?.nodes || {}
  for (const [id, el] of lblEls) {
    const nd = bodyNodes[id]
    if (!nd || !el) continue
    const p = net.canvasToDOM({ x: nd.x, y: nd.y })
    el.style.setProperty('--x', `${p.x.toFixed(1)}px`)
    el.style.setProperty('--y', `${p.y.toFixed(1)}px`)
  }
  updateSelMark()
}

function scheduleSync() {
  if (rafId) return
  rafId = requestAnimationFrame(() => {
    rafId = 0
    syncLabels()
  })
}

/* ------------------------------------------------------------------ *
 * 绘制
 * ------------------------------------------------------------------ */

/**
 * 把画布尺寸同步到布局算出来的高度
 *
 * 为什么必须显式调 setSize：
 *   vis-network 只在初始化时读一次容器尺寸。
 *   节点变多 → 布局算出的 H 变了 → 容器高度变了，
 *   但 vis 的画布还是老高度 → 下面的节点被裁掉看不见。
 */
function syncCanvasSize() {
  if (!net) return
  const w = host.value?.clientWidth || layout.value.W
  const h = layout.value.H
  if (!w || !h) return
  try {
    net.setSize(`${w}px`, `${h}px`)
  } catch (e) { /* 容器还没挂上 */ }
}

/**
 * 重画图（节点样式 / 连线）
 *
 * 注意：这里**默认不碰视口**。
 * 以前 draw() 顺手把视图拉回中心，于是「鼠标扫过一个节点」、
 * 「点一下选中」都会把用户已经平移好的视角弹回原处 ——
 * 一张能拖能缩放的图，老是自动跳回去等于不能拖。
 * 需要复位视角的地方显式传 recenter = true。
 *
 * recenter 什么时候必须为 true：容器尺寸变了。
 *   vis-network 的 setSize 会**按新旧画布的比例缩放视图**，
 *   好让「看起来还是那么大」—— 于是相邻标签的间距也跟着按比例变窄
 *   （实测 1256 → 936 宽时，行距 24px 被压成 18px），
 *   而且 moveTo 的锚点还是旧中心，标签整体偏出画布。
 *   所以尺寸变化后必须重新对中。
 */
function draw(recenter = false) {
  if (!net) return
  // ★ 先算布局：以前这一步压根没做，所有节点都落在 (0,0)
  computeLayout()
  const ns = buildNodes()
  const es = buildEdges()
  nodesDS.clear()
  edgesDS.clear()
  nodesDS.add(ns)
  edgesDS.add(es)
  // 容器高度是绑定在 layout 上的，DOM 要等下一帧才更新，
  // 所以 setSize 必须放到 nextTick 里，否则量到的还是旧高度。
  nextTick(() => {
    syncCanvasSize()
    if (recenter) resetView()
    scheduleSync()
  })
}

function resetView() {
  if (!net) return
  const lay = layout.value
  try {
    net.moveTo({ position: { x: lay.W / 2, y: lay.H / 2 }, scale: 1 })
  } catch (e) { /* 没有节点 */ }
  scheduleSync()
}

function zoomBy(k) {
  if (!net) return
  try {
    const scale = net.getScale() * k
    net.moveTo({ scale: Math.max(0.25, Math.min(2.5, scale)) })
  } catch (e) { /* 视口挪不动也不该报错 */ }
  scheduleSync()
}

function reshuffle() {
  seed.value += 1
  // 位置全变了，视角要跟着重新对中
  draw(true)
}

function selectById(id) {
  const n = (props.graph?.nodes || []).find((x) => x.id === id)
  if (!n) return
  selected.value = n
  emit('select', n)
  // 重画：选中态是画在节点上的，不重画图上就看不到变化
  draw()
  nextTick(scheduleSync)
}

onMounted(() => {
  nodesDS = new DataSet([])
  edgesDS = new DataSet([])
  net = new Network(host.value, { nodes: nodesDS, edges: edgesDS }, {
    layout: { improvedLayout: false, hierarchical: { enabled: false } },
    // 物理引擎整个关掉：位置由我们自己算，节点不会再飘到画布外
    physics: { enabled: false },
    interaction: {
      hover: true,
      dragNodes: false,     // 节点位置固定，拖节点没有意义
      dragView: true,       // 背景可以拖动平移
      zoomView: true,
      selectable: true,
      tooltipDelay: 160,
      hideEdgesOnDrag: false,
    },
    nodes: { chosen: true },
    edges: { selectionWidth: 0, hoverWidth: 0 },
  })

  net.on('hoverNode', (p) => {
    const id = p.node ?? p.nodes?.[0]
    if (id !== hoverId.value) {
      hoverId.value = id ?? null
      draw()
    }
  })
  net.on('blurNode', () => {
    if (hoverId.value) {
      hoverId.value = null
      draw()
    }
  })
  net.on('click', (p) => {
    // vis 的 click 事件给的是 nodes 数组，node 字段只有
    // selectNode / hoverNode 才有 —— 只看 p.node 会永远点不中。
    const id = p.node ?? p.nodes?.[0]
    if (!id) {
      selected.value = null
      draw()
      nextTick(scheduleSync)
      return
    }
    selectById(id)
  })
  net.on('doubleClick', (p) => {
    const id = p.node ?? p.nodes?.[0]
    if (!id) return
    const n = (props.graph?.nodes || []).find((x) => x.id === id)
    // 双击文件节点 → 直接跳到数据中心看这个文件
    if (n?.kind === 'document') {
      window.location.hash = `/library?doc=${n.ref_id}`
    }
  })
  net.on('afterDrawing', scheduleSync)
  net.on('zoom', scheduleSync)
  net.on('drag', scheduleSync)

  // 容器尺寸变了要重排：列位置是按宽度算的百分比，宽度变了列就偏了。
  // 而且必须 recenter —— vis 的 setSize 会按比例缩放视图，
  // 不重新对中就会看到行距被压窄、标签整体偏出画布。
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => {
      if (!net) return
      const w = host.value?.clientWidth || 0
      if (!w) return
      draw(true)
    })
    ro.observe(host.value)
  }

  // 开发期把 network 实例挂出去：自动化测试要拿到节点的真实坐标，
  // 才能点得准（坐标是算出来的，不是猜的）。
  if (import.meta.env.DEV) window.__dnaNet = net
  draw(true)
})

watch([nodes, visibleEdges, isDark], () => {
  // 数据换了（初次加载、筛选、暗色切换）——视角要重新对中一次
  draw(true)
}, { deep: true })
watch(seed, () => {
  draw(true)
})
watch(density, () => {
  draw(true)
})

// 外部定位（比如染色体清单里点「在双螺旋里看」）：
// 选中它并把它移到视野中央。
// 找不到就不动 —— 图还没加载完时不要把用户的选择吃掉。
watch(() => props.focusId, async (id) => {
  if (!id) return
  await nextTick()
  const n = (props.graph?.nodes || []).find((x) => x.id === id)
  if (!n) return
  selected.value = n
  emit('select', n)
  draw()
  await nextTick()
  if (!net) return
  // 视口中心移到该节点
  try {
    const pos = net.getPositions([id])
    const p = pos[id]
    if (p) {
      const scale = net.getScale()
      net.moveTo({ x: p.x * scale - (host.value?.clientWidth || 0) / 2,
                   y: p.y * scale - (host.value?.clientHeight || 0) / 2 })
    }
  } catch (e) { /* 视口挪不动也不该报错 */ }
  // 视口挪过之后要再同步一次：标题层和高亮环都靠 DOM 坐标定位，
  // 位置是按「画布坐标 → 屏幕坐标」换算的，视口一变就得重算。
  scheduleSync()
}, { immediate: false })

onBeforeUnmount(() => {
  try { ro?.disconnect() } catch (e) { /* 已经断开 */ }
  try { net?.destroy() } catch (e) { /* 已经销毁了 */ }
  net = null
})

/* ------------------------------------------------------------------ *
 * 对外暴露的尺寸（父组件用来对齐页头装饰）
 * ------------------------------------------------------------------ */
const H = computed(() => layout.value.H)
</script>

<style scoped>
.dna-graph {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ---------- 工具条 ---------- */
.dg-bar {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-xs);
}
.dg-bar-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.dg-grow { flex: 1 1 auto; min-width: 0; }
.dg-search { width: 268px; }
.dg-search-hit {
  font-size: 11px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  padding-right: 2px;
}
.dg-select { width: 132px; }
.dg-zoom {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 4px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}
.dg-zoom .el-button { padding: 5px 7px; }
.dg-density { min-width: 92px; }

.dg-bar-sub {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  padding-top: 9px;
  border-top: 1px dashed var(--border-light);
}
.dg-group {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}
.dg-group-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.6px;
  color: var(--text-tertiary);
}
.dg-group-edges { gap: 12px; }
.dg-edge-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-secondary);
}
.dg-edge-line {
  width: 16px;
  height: 0;
  border-top: 1.6px solid var(--border-strong);
  display: inline-block;
}
.dg-edge-item.encode .dg-edge-line { border-top-color: var(--primary); border-top-width: 2px; }
.dg-edge-item.attach .dg-edge-line { border-top-color: var(--primary); border-top-width: 2.4px; }
.dg-edge-item.relation .dg-edge-line {
  border-top-color: var(--accent-green);
  border-top-style: dashed;
}
.dg-stats {
  font-size: 11.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.dg-legend { display: flex; gap: 13px; flex-wrap: wrap; align-items: center; }
.lg-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
}
.lg-btn {
  border: 0;
  background: none;
  padding: 2px 4px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font: inherit;
  transition: opacity 0.15s var(--ease-out), background 0.15s var(--ease-out);
}
.lg-btn:hover { background: var(--bg-subtle); }
.lg-btn.is-off { opacity: 0.35; }
.lg-glyph { width: 10px; height: 10px; display: inline-block; }
.lg-glyph.gene {
  width: 13px;
  height: 9px;
  border-radius: 5px;
  border: 1.4px solid var(--primary);
  background: var(--primary-bg);
}
.lg-glyph.doc {
  width: 13px;
  height: 9px;
  border-radius: 5px;
  border: 1.4px solid var(--border-strong);
  background: var(--bg-subtle);
}
.lg-glyph.sec {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  border: 1.2px solid var(--border-strong);
  background: var(--bg-subtle);
}
.lg-glyph.rec {
  border-radius: 50%;
  background: var(--accent-green);
}
.lg-glyph.lib {
  width: 13px;
  height: 9px;
  border-radius: 5px;
  border: 1.4px solid var(--primary);
  background: var(--primary-200);
}
.lg-n { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }

.dg-kinds {
  display: flex;
  align-items: center;
  gap: 4px;
}
.lg-base {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1px solid transparent;
  background: var(--bc, var(--primary));
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  cursor: pointer;
  padding: 0;
  transition: opacity 0.15s var(--ease-out), transform 0.15s var(--ease-out);
}
.lg-base:hover { transform: translateY(-1px); }
.lg-base.is-off { opacity: 0.25; }

/* ---------- 画布 ---------- */
.dg-viewport {
  /* 图区固定高度 + 内部滚动：
     图有几十行时把整页撑到几千像素，谁都找不到中段。
     视口自己滚，图内还能拖拽缩放。 */
  max-height: 74vh;
  min-height: 420px;
  overflow: auto;
  border-radius: var(--radius-md);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  overscroll-behavior: contain;
}
.dg-stage {
  position: relative;
  border-radius: var(--radius-md);
  background:
    radial-gradient(circle at 1px 1px, var(--border-light) 1px, transparent 0) 0 0 / 24px 24px,
    linear-gradient(180deg, var(--bg-card) 0%, var(--bg-subtle) 100%);
  /* 窄屏也保持两列结构：宁可横向滚动，也不要把双螺旋压成一列 */
  min-width: 660px;
}
.dg-canvas {
  width: 100%;
  position: relative;
  z-index: 1;
}
.dg-rail {
  position: absolute;
  top: 42px;
  bottom: 18px;
  width: 2px;
  border-radius: 2px;
  z-index: 0;
  background-image: linear-gradient(to bottom, var(--primary-200) 0 6px, transparent 6px 12px);
  opacity: 0.7;
  transform: translateX(-1px);
}
.dg-rail-l { }
.dg-rail-r {
  background-image: linear-gradient(to bottom, var(--accent-slate) 0 6px, transparent 6px 12px);
  opacity: 0.35;
}

/* ---------- 链头 ---------- */
.dg-strand {
  position: absolute;
  top: 12px;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-xs);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.8px;
  color: var(--text-secondary);
  pointer-events: none;
  transform: translateX(-50%);
  white-space: nowrap;
}
.dg-strand-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
}
.dg-strand-r .dg-strand-dot { background: var(--accent-green); }
.dg-strand-n {
  font-size: 10px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  padding-left: 2px;
}

/* ---------- 标题层 ---------- */
.dg-overlay {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}
.dg-lbl {
  position: absolute;
  left: 0;
  top: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  line-height: 1.25;
  color: var(--text-secondary);
  cursor: pointer;
  pointer-events: auto;
  white-space: nowrap;
  overflow: hidden;
  /* 全局 button { min-height: 28px }（触控目标下限）会把每个标签撑到 28px，
     行距 20px → 相邻标签压字 8px。
     图里的标签是密集排布的文字行，不是触控按钮 ——
     真正的点击目标是画布上的节点圆点，所以这里解除高度下限。 */
  min-height: 0;
  min-width: 0;
  transition: opacity 0.16s var(--ease-out), color 0.16s var(--ease-out);
}
.dg-lbl.l {
  transform: translate3d(var(--x), var(--y), 0) translate(calc(-100% - 38px), -50%);
  flex-direction: row-reverse;
  max-width: var(--lbl-max-l, 250px);
}
.dg-lbl.r {
  transform: translate3d(var(--x), var(--y), 0) translate(22px, -50%);
  max-width: var(--lbl-max-r, 260px);
}
/* 选中的标签：加粗 + 一条主色底线，跟图上的实心节点对上 */
.dg-lbl.is-sel {
  color: var(--text-primary);
  font-weight: 600;
}
.dg-lbl.is-sel .dg-lbl-text {
  text-decoration: underline;
  text-decoration-color: var(--primary);
  text-decoration-thickness: 2px;
  text-underline-offset: 3px;
}
.dg-lbl.is-sel .dg-lbl-code {
  color: var(--primary) !important;
}
/* 搜索命中的标签：垫一层底色，从一堆灰字里一眼挑出来 */
.dg-lbl.is-hit .dg-lbl-text {
  background: var(--highlight-bg);
  color: var(--highlight-color);
  border-radius: 4px;
  padding: 0 4px;
  margin: 0 -4px;
}

/* 选中节点的光标环：会呼吸的一圈，位置跟着节点走 */
.dg-sel-ring {
  position: absolute;
  left: 0;
  top: 0;
  width: 46px;
  height: 46px;
  margin: -23px 0 0 -23px;
  border-radius: 50%;
  border: 2px solid var(--primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent);
  transform: translate3d(var(--x), var(--y), 0);
  pointer-events: none;
  animation: dg-sel-pulse 1.6s var(--ease-out) infinite;
}
@keyframes dg-sel-pulse {
  0%   { transform: translate3d(var(--x), var(--y), 0) scale(0.72); opacity: 0.95; }
  70%  { transform: translate3d(var(--x), var(--y), 0) scale(1.18); opacity: 0; }
  100% { transform: translate3d(var(--x), var(--y), 0) scale(1.18); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .dg-sel-ring { animation: none; opacity: 0.85; }
}

.dg-lbl-code {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.4px;
  flex-shrink: 0;
}
.dg-lbl-text {
  font-size: 12px;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dg-lbl-gene .dg-lbl-text { color: var(--text-primary); font-weight: 600; }
.dg-lbl-document .dg-lbl-text { color: var(--text-primary); font-weight: 600; }
.dg-lbl-section .dg-lbl-text { color: var(--text-tertiary); font-size: 11px; }
.dg-lbl-record .dg-lbl-text { color: var(--text-secondary); }
.dg-lbl-library .dg-lbl-text { color: var(--text-primary); font-weight: 600; }
.dg-lbl:hover .dg-lbl-text { color: var(--primary); }
.dg-lbl.is-dim { opacity: 0.28; }

/* ---------- 详情 ---------- */
.dg-detail {
  padding: 13px 15px;
  border-radius: var(--radius-md);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  box-shadow: var(--shadow-xs);
}
.dg-detail-head {
  display: flex;
  align-items: center;
  gap: 9px;
}
.dg-detail-kind {
  font-size: 11px;
  font-weight: 600;
  color: var(--ac-fg, var(--primary));
  background: var(--ac-bg, var(--primary-bg));
  border: 1px solid var(--ac-line, var(--primary-100));
  border-radius: 5px;
  padding: 1px 7px;
  flex-shrink: 0;
}
.dg-detail-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dg-detail-acts { display: inline-flex; gap: 2px; flex-shrink: 0; }
.dg-detail-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.dg-meta-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  font-size: 12px;
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  max-width: 100%;
}
.dg-meta-k { color: var(--text-tertiary); flex-shrink: 0; }
.dg-meta-v {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dg-detail-links {
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px dashed var(--border-light);
  font-size: 12px;
  color: var(--text-tertiary);
}
.dg-links-label { margin-right: 6px; }
.dg-link-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin: 2px 4px 0 0;
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: border-color 0.15s var(--ease-out), color 0.15s var(--ease-out);
}
.dg-link-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.dg-link-kind {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  background: var(--border-strong);
  flex-shrink: 0;
}
.dg-link-kind.structure { background: var(--border-strong); }
.dg-link-kind.attach { background: var(--primary); }
.dg-link-kind.relation { background: var(--accent-green); }
.dg-link-kind.encode { background: var(--primary-200); }
.dg-links-more {
  margin-left: 6px;
  color: var(--text-disabled);
}

/* ---------- 空状态 ---------- */
.dg-empty {
  padding: 34px 0;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}
.dg-empty-icon {
  font-size: 26px;
  color: var(--border-strong);
  margin-bottom: 8px;
}
.dg-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}
.dg-empty-sub {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.dg-slide-enter-active, .dg-slide-leave-active { transition: opacity .18s ease, transform .18s ease; }
.dg-slide-enter-from, .dg-slide-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 768px) {
  .dg-search { width: 100%; }
  .dg-bar-main { gap: 8px; }
  .dg-select { width: 118px; }
  .dg-lbl-text { font-size: 11px; }
  .dg-lbl.l { transform: translate3d(var(--x), var(--y), 0) translate(calc(-100% - 30px), -50%); }
  .dg-lbl.r { transform: translate3d(var(--x), var(--y), 0) translate(16px, -50%); }
  .dg-viewport { max-height: 68vh; }
}
</style>
