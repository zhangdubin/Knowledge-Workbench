<template>
  <div class="dna-graph">
    <!-- 图例 + 筛选 + 操作 -->
    <div class="dg-toolbar">
      <div class="dg-legend">
        <span class="lg-item">
          <span class="lg-glyph gene" />基因<span class="lg-n">{{ counts.gene }}</span>
        </span>
        <span class="lg-item">
          <span class="lg-glyph doc" />文件<span class="lg-n">{{ counts.document }}</span>
        </span>
        <span class="lg-item">
          <span class="lg-glyph sec" />章节<span class="lg-n">{{ counts.section }}</span>
        </span>
        <span class="lg-item">
          <span class="lg-glyph rec" />记录<span class="lg-n">{{ counts.record }}</span>
        </span>
        <span v-if="counts.library" class="lg-item">
          <span class="lg-glyph lib" />养料库
        </span>
      </div>

      <!-- 基因种类：按碱基色分四类，点一下就能筛掉一类 -->
      <div class="dg-kinds">
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
        <span class="dg-kinds-label">基因种类</span>
      </div>

      <div class="dg-filters">
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
        <el-button size="small" @click="reshuffle">
          <el-icon><Refresh /></el-icon>重排
        </el-button>
        <el-button size="small" @click="resetView">
          <el-icon><FullScreen /></el-icon>适应
        </el-button>
      </div>
    </div>

    <!-- 双螺旋画布：两链固定坐标 + 碱基对曲线 -->
    <div ref="stage" class="dg-stage" :style="stageStyle">
      <!-- 两条链的「骨架线」：纯装饰，跟着列位置走 -->
      <span v-if="showLeft" class="dg-rail dg-rail-l" />
      <span v-if="showRight" class="dg-rail dg-rail-r" />

      <div ref="host" class="dg-canvas" :style="{ height: H + 'px' }" />

      <!-- 标题层：文字用 DOM 画，不跟节点挤在同一张 canvas 上 -->
      <div class="dg-overlay">
        <button
          v-for="lb in labels"
          :key="lb.id"
          :ref="el => setLbl(lb.id, el)"
          class="dg-lbl"
          :class="[lb.side, 'dg-lbl-' + lb.kind, { 'is-dim': lb.dim }]"
          type="button"
          :title="lb.title"
          @click.stop="selectById(lb.id)"
        >
          <span v-if="lb.code" class="dg-lbl-code" :style="{ color: lb.color }">{{ lb.code }}</span>
          <span class="dg-lbl-text">{{ lb.text }}</span>
        </button>
      </div>

      <div v-if="showLeft" class="dg-strand dg-strand-l">知识链</div>
      <div v-if="showRight" class="dg-strand dg-strand-r">证据链</div>
    </div>

    <!-- 选中节点的详情 -->
    <transition name="dg-slide">
      <div v-if="selected" class="dg-detail">
        <div class="dg-detail-head">
          <span class="dg-detail-kind" :style="detailKindStyle">{{ kindLabel(selected.kind) }}</span>
          <span class="dg-detail-title">{{ selected.label }}</span>
          <el-button size="small" text @click="selected = null">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
        <div class="dg-detail-meta">
          <span v-for="(v, k) in detailMeta" :key="k" class="dg-meta-item">
            {{ metaLabel(k) }}：{{ v }}
          </span>
        </div>
        <div v-if="selectedEdges.length" class="dg-detail-links">
          <span class="dg-links-label">连着 {{ selectedEdges.length }} 个：</span>
          <span v-for="e in selectedEdges.slice(0, 10)" :key="e.id" class="dg-link-chip">
            <i class="dg-link-kind" :class="e.kind" />{{ edgeLabel(e) }}
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
import { cssVar, isDark } from '../utils/theme'

const props = defineProps({
  graph: { type: Object, default: () => ({ nodes: [], edges: [], stats: {} }) },
})
const emit = defineEmits(['select'])

const host = ref(null)
const filter = ref('all')
const selected = ref(null)
const seed = ref(0)
const hoverId = ref(null)
const geneLimit = ref(12)
const offKinds = ref(new Set())

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
const BASE_NAME = { A: '腺嘌呤', T: '胸腺嘧啶', G: '鸟嘌呤', C: '胞嘧啶' }

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

const counts = computed(() => {
  const c = { document: 0, section: 0, record: 0, gene: 0, library: 0 }
  for (const n of props.graph?.nodes || []) {
    if (c[n.kind] !== undefined) c[n.kind]++
  }
  return c
})

const showLeft = computed(() => filter.value !== 'evidence')
const showRight = computed(() => filter.value !== 'knowledge')

/** 基因：先按种类筛，再按「表达度 + 置信度」取热门的一批 */
const visibleGenes = computed(() => {
  if (geneLimit.value === 0) return []
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

const nodes = computed(() => {
  const all = props.graph?.nodes || []
  if (filter.value === 'all') {
    return all.filter((n) => n.kind !== 'gene' || geneIds.value.has(n.id))
  }
  if (filter.value === 'knowledge') {
    return all.filter(
      (n) => n.kind === 'gene' || n.kind === 'document' || n.kind === 'section' || n.kind === 'library'
    ).filter((n) => n.kind !== 'gene' || geneIds.value.has(n.id))
  }
  return all.filter((n) => n.kind === 'record')
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

const detailMeta = computed(() => {
  const m = { ...(selected.value?.meta || {}) }
  if (selected.value?.kind === 'gene') {
    if (m.gene_kind) m.gene_kind = GENE_KIND_MAP[m.gene_kind]?.label || m.gene_kind
    if (m.destroyed) m.destroyed = '已销毁（蒸馏自源码）'
  }
  return m
})

const detailKindStyle = computed(() => {
  const n = selected.value
  let p = palette.value.neutral
  if (n?.kind === 'gene') p = palette.value[baseOfGene(n)]
  else if (n?.kind === 'record') p = palette.value.evidence
  else if (n?.kind === 'library') p = palette.value.A
  return { '--ac-fg': p.text, '--ac-bg': p.fill, '--ac-line': p.line }
})

/* ------------------------------------------------------------------ *
 * 布局：两列固定坐标（不碰物理引擎）
 * ------------------------------------------------------------------ */

const PAD_TOP = 50        // 顶部留白：给「知识链 / 证据链」两个链头
const PAD_BOTTOM = 26
const TARGET_H = 940      // 图区目标高度；行多的时候自动收窄行距
const MIN_PITCH = 20
const MAX_PITCH = 28

const layout = ref({ pos: {}, W: 900, H: 460, leftLen: 1, rightLen: 1, xLeft: 0, xRight: 0 })

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
  const W = Math.max(320, host.value?.clientWidth || 900)
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
  for (const n of list) {
    if (n.kind === 'section' && !leftRows.includes(n)) leftRows.push(n)
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
  const pitch = Math.max(MIN_PITCH, Math.min(MAX_PITCH, (TARGET_H - PAD_TOP - PAD_BOTTOM) / rows))
  const span = Math.max(leftLen, rightLen) * pitch
  const H = PAD_TOP + PAD_BOTTOM + span

  const both = showLeft.value && showRight.value
  const xLeft = both ? W * 0.30 : W * 0.42
  const xRight = both ? W * 0.70 : W * 0.42

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
    lblMaxL: Math.max(64, Math.min(250, xLeft - 46)),
    lblMaxR: Math.max(64, Math.min(260, W - xRight - 30)),
  }
  return layout.value
}

const stageStyle = computed(() => ({
  '--lbl-max-l': (layout.value.lblMaxL || 250) + 'px',
  '--lbl-max-r': (layout.value.lblMaxR || 260) + 'px',
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

function dimmed(color) {
  const card = cssVar('--bg-card', '#ffffff')
  return mix(card, color, 0.16)
}

/* ------------------------------------------------------------------ *
 * 画到 vis-network 上
 * ------------------------------------------------------------------ */

function buildNodes() {
  const P = palette.value
  const hi = hiSet.value
  const dim = hoverId.value && hi.size > 0
  const pos = layout.value.pos

  return nodes.value.map((n) => {
    const p = pos[n.id] || { x: 0, y: 0 }
    const isGene = n.kind === 'gene'
    const isDoc = n.kind === 'document'
    const isSec = n.kind === 'section'
    const isRec = n.kind === 'record'
    const isLib = n.kind === 'library'
    const faded = dim && !hi.has(n.id)

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

    if (faded) {
      color = {
        background: dimmed(color.background),
        border: dimmed(color.border),
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
      font: faded ? { ...font, color: dimmed(font.color || '#888888') } : font,
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
      dim: dim && !hi.has(n.id),
    })
  }
  return list
})

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

function draw() {
  if (!net) return
  const lay = computeLayout()
  const ns = buildNodes()
  const es = buildEdges()
  nodesDS.clear()
  edgesDS.clear()
  nodesDS.add(ns)
  edgesDS.add(es)
  // 视图复位：把画布坐标 1:1 对上 DOM 坐标（平移量归零），
  // 这样标题层可以直接用节点坐标定位，永远对得齐。
  requestAnimationFrame(() => {
    try {
      net.moveTo({ position: { x: lay.W / 2, y: lay.H / 2 }, scale: 1 })
    } catch (e) { /* 还没有节点时 moveTo 会抛 */ }
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

function reshuffle() {
  seed.value += 1
  draw()
}

function selectById(id) {
  const n = (props.graph?.nodes || []).find((x) => x.id === id)
  if (!n) return
  selected.value = n
  emit('select', n)
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
    if (!id) { selected.value = null; return }
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

  // 容器尺寸变了要重排：列位置是按宽度算的百分比，宽度变了列就偏了
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => {
      if (!net) return
      const w = host.value?.clientWidth || 0
      if (!w) return
      net.setSize(`${w}px`, `${layout.value.H}px`)
      draw()
    })
    ro.observe(host.value)
  }

  // 开发期把 network 实例挂出去：自动化测试要拿到节点的真实坐标，
  // 才能点得准（坐标是算出来的，不是猜的）。
  if (import.meta.env.DEV) window.__dnaNet = net
  draw()
  nextTick(scheduleSync)
})

watch([nodes, visibleEdges, isDark], draw, { deep: true })
watch(seed, draw)

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
.dg-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 0 2px 12px;
}
.dg-legend { display: flex; gap: 13px; flex-wrap: wrap; align-items: center; }
.lg-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
}
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
.dg-kinds-label {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: 3px;
}
.lg-base {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1px solid transparent;
  background: var(--bc, var(--primary));
  color: #fff;
  font-size: 10px;
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

.dg-filters { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.dg-select { width: 132px; }

/* ---------- 画布 ---------- */
.dg-stage {
  position: relative;
  border-radius: 12px;
  background:
    radial-gradient(circle at 1px 1px, var(--border-light) 1px, transparent 0) 0 0 / 24px 24px;
  border: 1px solid var(--border-light);
  overflow: hidden;
}
.dg-canvas {
  width: 100%;
  position: relative;
  z-index: 1;
}
.dg-rail {
  position: absolute;
  top: 40px;
  bottom: 18px;
  width: 2px;
  border-radius: 2px;
  z-index: 0;
  background-image: linear-gradient(to bottom, var(--primary-200) 0 6px, transparent 6px 12px);
  opacity: 0.7;
}
.dg-rail-l { left: 30%; }
.dg-rail-r {
  left: 70%;
  background-image: linear-gradient(to bottom, var(--accent-slate) 0 6px, transparent 6px 12px);
  opacity: 0.35;
}

/* ---------- 链头 ---------- */
.dg-strand {
  position: absolute;
  top: 14px;
  z-index: 2;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1.4px;
  color: var(--text-tertiary);
  pointer-events: none;
}
.dg-strand-l { left: 30%; transform: translateX(-50%); }
.dg-strand-r { left: 70%; transform: translateX(-50%); }

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
  padding: 1px 0;
  border: 0;
  background: none;
  font: inherit;
  color: var(--text-secondary);
  cursor: pointer;
  pointer-events: auto;
  white-space: nowrap;
  overflow: hidden;
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
.dg-lbl-code {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.4px;
  flex-shrink: 0;
}
.dg-lbl-text {
  font-size: 12px;
  line-height: 1.35;
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
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}
.dg-detail-head { display: flex; align-items: center; gap: 8px; }
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
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 7px;
  font-size: 12px;
  color: var(--text-tertiary);
}
.dg-detail-links { margin-top: 8px; font-size: 12px; color: var(--text-tertiary); }
.dg-links-label { margin-right: 6px; }
.dg-link-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin: 2px 4px 0 0;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.dg-empty {
  padding: 26px 0;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

.dg-slide-enter-active, .dg-slide-leave-active { transition: opacity .18s ease, transform .18s ease; }
.dg-slide-enter-from, .dg-slide-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 768px) {
  .dg-filters { margin-left: 0; width: 100%; }
  .dg-select { width: 118px; }
  .dg-lbl-text { font-size: 11px; }
  .dg-lbl.l { transform: translate3d(var(--x), var(--y), 0) translate(calc(-100% - 26px), -50%); }
  .dg-lbl.r { transform: translate3d(var(--x), var(--y), 0) translate(16px, -50%); }
  .dg-rail-l { left: 28%; }
  .dg-rail-r { left: 72%; }
  .dg-strand-l { left: 28%; }
  .dg-strand-r { left: 72%; }
}
</style>
