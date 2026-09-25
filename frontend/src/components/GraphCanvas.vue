<template>
  <div class="gc">
    <!-- 工具条 -->
    <div class="gc-toolbar">
      <div class="gt-tools">
        <el-tooltip content="适应画布" placement="top">
          <button class="gt-btn" @click="fit"><el-icon><FullScreen /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="放大" placement="top">
          <button class="gt-btn" @click="zoom(1.25)"><el-icon><ZoomIn /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="缩小" placement="top">
          <button class="gt-btn" @click="zoom(0.8)"><el-icon><ZoomOut /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="重新计算布局" placement="top">
          <button class="gt-btn" :class="{ on: physicsOn }" @click="relayout">
            <el-icon><RefreshRight /></el-icon>
          </button>
        </el-tooltip>
        <span class="gt-sep" />
        <el-tooltip content="显示名称 / 仅图标" placement="top">
          <button class="gt-btn" :class="{ on: showLabels }" @click="toggleLabels">
            <el-icon><Postcard /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="显示关系名称" placement="top">
          <button class="gt-btn" :class="{ on: showEdgeLabels }" @click="toggleEdgeLabels">
            <el-icon><Memo /></el-icon>
          </button>
        </el-tooltip>
        <span class="gt-sep" />
        <el-tooltip content="全选图例 / 只留中心" placement="top">
          <button class="gt-btn" @click="toggleAllGroups"><el-icon><View /></el-icon></button>
        </el-tooltip>
      </div>
      <div class="gt-hint">
        <el-icon :size="12"><InfoFilled /></el-icon>
        滚轮缩放 · 拖拽平移 · 悬停高亮邻居 · 点击查看详情
      </div>
    </div>

    <div class="gc-body" :style="{ height }">
      <div ref="host" class="gc-canvas" />

      <div v-if="loading" class="gc-overlay">
        <el-icon class="is-loading" :size="22"><Loading /></el-icon>
        <span>正在计算图谱…</span>
      </div>

      <div v-else-if="!nodes.length" class="gc-overlay">
        <el-icon :size="34"><Connection /></el-icon>
        <div class="go-title">暂无关联数据</div>
        <div class="go-desc">{{ emptyHint }}</div>
      </div>

      <!-- 图例：可点选显隐 -->
      <div v-if="!loading && groups.length" class="gc-legend">
        <div class="gl-head">
          <span>图例</span>
          <span class="gl-count">{{ visibleNodeCount }} / {{ nodes.length }}</span>
        </div>
        <button v-for="g in groups" :key="g.key" class="gl-item"
                :class="{ off: hiddenGroups.has(g.key) }"
                @click="toggleGroup(g.key)">
          <span class="gl-swatch" :style="{ background: g.color, borderColor: g.color }" />
          <span class="gl-label" :title="g.key">{{ g.key }}</span>
          <span class="gl-num">{{ g.count }}</span>
        </button>
      </div>

      <!-- 边类型图例 -->
      <div v-if="!loading && viaGroups.length" class="gc-legend via">
        <div class="gl-head"><span>连线</span></div>
        <div v-for="v in viaGroups" :key="v.key" class="gl-item static">
          <span class="gl-line" :style="{ background: v.color }" />
          <span class="gl-label">{{ v.label }}</span>
          <span class="gl-num">{{ v.count }}</span>
        </div>
      </div>

      <div v-if="truncated" class="gc-trunc">
        <el-icon :size="12"><WarningFilled /></el-icon>节点过多，已按类型配额截断显示
      </div>
    </div>

    <!-- 节点详情 -->
    <el-drawer v-model="inspectorOpen" :size="drawerSize" :with-header="false"
               class="gc-drawer" append-to-body>
      <div v-if="active" class="gi">
        <header class="gi-head">
          <span class="gi-icon">{{ active.icon || '📦' }}</span>
          <div class="gi-title">
            <div class="gi-name">{{ active.label }}</div>
            <div class="gi-sub">{{ active.type_name || active.kind }} · {{ active.id }}</div>
          </div>
          <el-button text @click="inspectorOpen = false"><el-icon><Close /></el-icon></el-button>
        </header>

        <div class="gi-stats">
          <div class="gis"><span class="gis-v">{{ degreeOf(active.id) }}</span><span class="gis-l">条关联</span></div>
          <div class="gis"><span class="gis-v">{{ neighboursOf(active.id).length }}</span><span class="gis-l">个邻居</span></div>
          <div class="gis"><span class="gis-v">{{ groupOfRaw(active) }}</span><span class="gis-l">分组</span></div>
        </div>

        <div v-if="active.tags?.length" class="gi-tags">
          <el-tag v-for="t in active.tags" :key="t" size="small" effect="plain">#{{ t }}</el-tag>
        </div>

        <div class="gi-actions">
          <el-button type="primary" @click="emit('select', active)">
            <el-icon><View /></el-icon>打开详情
          </el-button>
          <el-button @click="emit('recenter', active)">
            <el-icon><Aim /></el-icon>以它为中心
          </el-button>
        </div>

        <div class="gi-section">
          <div class="gi-sec-title">相邻节点</div>
          <div v-if="neighboursOf(active.id).length" class="gi-nbrs">
            <button v-for="nb in neighboursOf(active.id)" :key="nb.node.id" class="gi-nbr"
                    @click="focus(nb.node)">
              <span class="gn-ico">{{ nb.node.icon || '📦' }}</span>
              <span class="gn-label">{{ nb.node.label }}</span>
              <span class="gn-rel">{{ nb.via }}</span>
            </button>
          </div>
          <div v-else class="gi-empty">这条节点还没有任何关联</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
/**
 * 通用关系图谱画布
 *
 * 关联图谱与知识图谱曾各自维护一份 vis-network 代码，问题一致：
 * 颜色写死（暗色模式下节点文字看不见）、没有缩放/适应、点一下就跳走、
 * 关系类型与方向无从分辨。这里把「画图」这件事收敛成一个组件，
 * 页面只负责提供数据与响应用户意图。
 *
 * 对外只暴露三件事：nodes / edges 输入，select / recenter 两个意图事件。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { Network } from 'vis-network/standalone'
import { DataSet } from 'vis-data/standalone'
import { chartTheme, cssVar, isDark } from '../utils/theme'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  truncated: { type: Boolean, default: false },
  height: { type: String, default: '620px' },
  // 'type' 按数据模型着色（关联图谱），'tag' 按首个标签着色（知识图谱）
  colorBy: { type: String, default: 'type' },
  emptyHint: { type: String, default: '换个范围或先建立一些关联' },
})
const emit = defineEmits(['select', 'recenter'])

// 连线语义 → 颜色槽位：relation 用主色，其余各占一个固定槽，
// 保证同一语义在任何图里颜色一致
const VIA_META = {
  relation: { label: '关联关系', slot: 0, arrow: true, dash: false },
  reference: { label: '外键引用', slot: 2, arrow: true, dash: false },
  field: { label: '字段挂载', slot: 1, arrow: true, dash: false },
  wikilink: { label: '双向链接', slot: 3, arrow: false, dash: true },
}

const host = ref(null)
const inspectorOpen = ref(false)
const active = ref(null)
const showLabels = ref(true)
const showEdgeLabels = ref(true)
const hiddenGroups = ref(new Set())
const physicsOn = ref(false)
const windowWidth = ref(1440)

const network = shallowRef(null)
const nodesDS = shallowRef(null)
const edgesDS = shallowRef(null)
const built = shallowRef({ nodes: [], edges: [] })

const drawerSize = computed(() => (windowWidth.value < 760 ? '100%' : '360px'))

/** 主题令牌：必须 touch isDark 才能让暗色切换重算 */
const theme = computed(() => {
  void isDark.value
  return chartTheme()
})

function tint(hex, alpha) {
  const h = String(hex || '#888').replace('#', '')
  const n = h.length === 3 ? h.split('').map(c => c + c).join('') : h
  const r = parseInt(n.slice(0, 2), 16) || 0
  const g = parseInt(n.slice(2, 4), 16) || 0
  const b = parseInt(n.slice(4, 6), 16) || 0
  return `rgba(${r},${g},${b},${alpha})`
}

/** 稳定分组色：用字符串哈希而不是下标，增删分组时既有颜色不会整体错位 */
function hashOf(s) {
  let h = 0
  for (let i = 0; i < String(s).length; i++) h = (h * 31 + String(s).charCodeAt(i)) | 0
  return Math.abs(h)
}

function groupOfRaw(n) {
  if (props.colorBy === 'tag') return (n.tags && n.tags[0]) || '未分类'
  return n.type_name || n.type || n.kind || '其他'
}

const pal = computed(() => theme.value.colors)

function colorOf(key) {
  return pal.value[hashOf(key) % pal.value.length]
}

const groups = computed(() => {
  const map = new Map()
  for (const n of props.nodes) {
    const k = groupOfRaw(n)
    map.set(k, (map.get(k) || 0) + 1)
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => ({ key, count, color: colorOf(key) }))
})

const visibleNodeCount = computed(() => props.nodes.length
  - props.nodes.filter(n => hiddenGroups.value.has(groupOfRaw(n))).length)

const viaGroups = computed(() => {
  const t = theme.value
  const map = new Map()
  for (const e of props.edges) map.set(e.via || 'relation', (map.get(e.via || 'relation') || 0) + 1)
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => {
      const meta = VIA_META[key] || VIA_META.relation
      return { key, count, label: meta.label, color: t.colors[meta.slot % t.colors.length] }
    })
})

// ---------- 邻接 ----------

const adjacency = computed(() => {
  const m = new Map()
  const add = (a, b, label) => {
    if (!m.has(a)) m.set(a, [])
    m.get(a).push({ other: b, via: label })
  }
  for (const e of props.edges) {
    add(e.source, e.target, e.relation || '关联')
    add(e.target, e.source, e.relation || '关联')
  }
  return m
})

const rawById = computed(() => Object.fromEntries(props.nodes.map(n => [n.id, n])))

function neighboursOf(id) {
  const ns = adjacency.value.get(id) || []
  return ns
    .filter(x => rawById.value[x.other])
    .map(x => ({ node: rawById.value[x.other], via: x.via }))
}

function degreeOf(id) {
  return (adjacency.value.get(id) || []).length
}

// ---------- 构建 vis 数据 ----------

function labelOf(n) {
  if (!showLabels.value) return n.icon || ''
  return `${n.icon || ''} ${n.label || ''}`.trim()
}

function buildNodes() {
  const t = theme.value
  const centerFill = cssVar('--primary-dark', '#474bb0')
  return props.nodes.map(n => {
    const c = colorOf(groupOfRaw(n))
    const isCenter = !!n.center
    const isDoc = n.kind === 'document'
    const dimText = t.dark ? 'rgba(236,238,242,0.26)' : 'rgba(23,24,29,0.26)'
    const dimFill = tint(c, t.dark ? 0.06 : 0.05)

    return {
      id: n.id,
      label: labelOf(n),
      title: `${n.icon || ''} ${n.label}\n${n.type_name || ''}${n.tags?.length ? ' · ' + n.tags.map(x => '#' + x).join(' ') : ''}`,
      shape: 'box',
      shapeProperties: { borderRadius: isDoc ? 4 : 9 },
      borderDashes: isDoc ? [5, 3] : false,      // 文件端用虚线边框区分
      margin: isCenter
        ? { top: 12, bottom: 12, left: 17, right: 17 }
        : { top: 9, bottom: 9, left: 12, right: 12 },
      borderWidth: isCenter ? 3 : 2,
      color: {
        background: isCenter ? centerFill : tint(c, t.dark ? 0.22 : 0.13),
        border: isCenter ? centerFill : c,
        highlight: { background: isCenter ? centerFill : tint(c, 0.3), border: c },
        hover: { background: isCenter ? centerFill : tint(c, 0.2), border: c },
      },
      font: {
        color: isCenter ? '#ffffff' : t.text,
        size: isCenter ? 15 : 13,
        face: 'system-ui, -apple-system, "PingFang SC", sans-serif',
      },
      shadow: t.dark
        ? { enabled: false }
        : { enabled: true, color: 'rgba(16,18,27,0.10)', size: 8, x: 0, y: 2 },
      // 悬停淡化用的预置变体：避免每次 hover 都解析颜色
      _on: {
        color: { background: isCenter ? centerFill : tint(c, 0.2), border: c },
        font: { color: isCenter ? '#ffffff' : t.text, size: isCenter ? 15 : 13 },
        borderWidth: isCenter ? 3 : 2,
      },
      _off: {
        color: { background: dimFill, border: dimFill },
        font: { color: dimText, size: isCenter ? 15 : 12 },
        borderWidth: 1,
      },
    }
  })
}

function buildEdges(validIds) {
  const t = theme.value
  return props.edges
    .filter(e => validIds.has(e.source) && validIds.has(e.target))
    .map(e => {
      const meta = VIA_META[e.via] || VIA_META.relation
      const c = t.colors[meta.slot % t.colors.length]
      const dim = tint(c, t.dark ? 0.08 : 0.06)
      const arrow = { enabled: meta.arrow, scaleFactor: 0.55 }
      return {
        id: e.id,
        from: e.source,
        to: e.target,
        label: showEdgeLabels.value ? (e.relation || '') : '',
        arrows: { to: arrow, from: { enabled: false }, middle: { enabled: false } },
        color: {
          color: tint(c, 0.75),
          highlight: c,
          hover: c,
        },
        width: e.via === 'wikilink' ? 1.5 : 1.2,
        // 双向链接没有方向，用虚线；外键引用用连续曲线减少交叠
        dashes: meta.dash ? [5, 4] : false,
        smooth: { enabled: true, type: e.via === 'reference' ? 'continuous' : 'dynamic', roundness: 0.4 },
        font: {
          color: t.muted, size: 10, align: 'middle',
          strokeWidth: 3, strokeColor: t.card,
          background: t.card,
        },
        _from: e.source,
        _to: e.target,
        _on: { color: { color: c, opacity: 1 }, width: e.via === 'wikilink' ? 1.8 : 1.5 },
        _off: { color: { color: dim, opacity: 1 }, width: 1, font: { color: 'rgba(0,0,0,0)' } },
        _label: showEdgeLabels.value ? (e.relation || '') : '',
      }
    })
}

// ---------- 渲染 ----------

async function draw() {
  const net = network.value
  if (!net) return
  const raw = { nodes: buildNodes(), edges: [] }
  const ids = new Set(raw.nodes.map(n => n.id))
  raw.edges = buildEdges(ids)
  built.value = raw

  nodesDS.value.clear()
  edgesDS.value.clear()
  nodesDS.value.add(raw.nodes)
  edgesDS.value.add(raw.edges)
  applyVisibility()

  // 每次换数据都重算布局：沿用旧坐标会让新图挤成一团
  net.setOptions({ physics: { enabled: true } })
  physicsOn.value = true
  net.fit({ animation: false })
}

function applyVisibility() {
  if (!nodesDS.value) return
  const hidden = hiddenGroups.value
  nodesDS.value.update(props.nodes.map(n => ({
    id: n.id, hidden: hidden.has(groupOfRaw(n)),
  })))
  const ids = new Set(props.nodes.filter(n => !hidden.has(groupOfRaw(n))).map(n => n.id))
  edgesDS.value.update(props.edges.map(e => ({
    id: e.id, hidden: !ids.has(e.source) || !ids.has(e.target),
  })))
}

function onStabilized() {
  const net = network.value
  if (!net) return
  // 布局稳定后关掉物理：否则拖完一个节点整张图会一直抖
  net.setOptions({ physics: { enabled: false } })
  physicsOn.value = false
  net.fit({ animation: { duration: 380, easingFunction: 'easeInOutQuad' } })
}

function createNetwork() {
  const options = {
    layout: { improvedLayout: true },
    physics: {
      enabled: true,
      barnesHut: { gravitationalConstant: -5200, springLength: 190, springConstant: 0.045, damping: 0.42 },
      stabilization: { iterations: 320, fit: true },
    },
    interaction: {
      hover: true,
      dragNodes: true,
      dragView: true,
      zoomView: true,
      tooltipDelay: 180,
      navigationButtons: false,
      multiselect: false,
    },
    nodes: { chosen: true },
    edges: { selectionWidth: 1, hoverWidth: 0.4 },
  }
  const net = new Network(host.value, { nodes: nodesDS.value, edges: edgesDS.value }, options)
  net.on('stabilizationIterationsDone', onStabilized)
  net.on('hoverNode', p => highlight(p.node))
  net.on('blurNode', () => highlight(null))
  net.on('selectNode', p => {
    const raw = rawById.value[p.nodes[0]]
    if (raw) { active.value = raw; inspectorOpen.value = true }
  })
  net.on('dragEnd', () => { /* 拖动后不重排，交给用户 */ })
  return net
}

function highlight(centerId) {
  if (!nodesDS.value) return
  const nb = new Set(centerId ? neighboursOf(centerId).map(x => x.node.id) : [])
  nodesDS.value.update(built.value.nodes.map(n => {
    const on = !centerId || n.id === centerId || nb.has(n.id)
    return { id: n.id, ...(on ? n._on : n._off) }
  }))
  edgesDS.value.update(built.value.edges.map(e => {
    const on = !centerId || e._from === centerId || e._to === centerId
    return {
      id: e.id,
      ...(on ? e._on : e._off),
      label: on ? e._label : '',
    }
  }))
}

// ---------- 工具条动作 ----------

function fit() {
  network.value?.fit({ animation: { duration: 380, easingFunction: 'easeInOutQuad' } })
}
function zoom(factor) {
  const net = network.value
  if (!net) return
  net.moveTo({ scale: net.getScale() * factor, animation: { duration: 200, easingFunction: 'easeInOutQuad' } })
}
function relayout() {
  const net = network.value
  if (!net) return
  net.setOptions({ physics: { enabled: true } })
  physicsOn.value = true
  net.stabilize(220)
}

function toggleLabels() {
  showLabels.value = !showLabels.value
  nodesDS.value.update(built.value.nodes.map(n => ({ id: n.id, label: labelOf(rawById.value[n.id] || {}) })))
}

function toggleEdgeLabels() {
  showEdgeLabels.value = !showEdgeLabels.value
  edgesDS.value.update(built.value.edges.map(e => ({
    id: e.id, label: showEdgeLabels.value ? e._label : '',
  })))
}

function toggleGroup(key) {
  const s = new Set(hiddenGroups.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  hiddenGroups.value = s
  applyVisibility()
}

function toggleAllGroups() {
  hiddenGroups.value = hiddenGroups.value.size
    ? new Set()
    : new Set(groups.value.map(g => g.key))
  applyVisibility()
}

function focus(raw) {
  active.value = raw
  if (network.value) {
    const pos = network.value.getPositions([raw.id])[raw.id]
    if (pos) {
      network.value.moveTo({ position: pos, scale: Math.max(network.value.getScale(), 1), animation: { duration: 420 } })
    }
  }
}

function measure() { windowWidth.value = window.innerWidth }

onMounted(() => {
  measure()
  window.addEventListener('resize', measure)
  nodesDS.value = new DataSet([])
  edgesDS.value = new DataSet([])
  network.value = createNetwork()
  draw()
  // E2E 钩子：只有显式带上 ?__e2e=1 才把实例挂到 window。
  // 自动化脚本必须能算出节点的真实屏幕坐标才点得中它，否则只能在画布上盲点，
  // 命中与否全看运气。留这个开关比让测试脚本绕路更可靠，正常访问不受影响。
  // 注意前端是 hash 路由，参数落在 location.hash 里，看 search 是看不到的。
  if (window.location.href.includes('__e2e=1')) window.__kbGraph = network.value
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', measure)
  network.value?.destroy()
  network.value = null
})

// 数据变 → 重画；主题变 → 重画（颜色已经写进 vis 的 item 里，不会自己更新）
watch(() => [props.nodes, props.edges], draw, { deep: false })
watch(isDark, draw)
watch(() => props.colorBy, () => { hiddenGroups.value = new Set(); draw() })

defineExpose({ fit, zoom, relayout })
</script>

<style scoped>
.gc { position: relative; }

.gc-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; margin-bottom: 10px;
}
.gt-tools {
  display: flex; align-items: center; gap: 3px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 4px; box-shadow: var(--shadow-xs);
}
.gt-btn {
  width: 30px; height: 30px; border: none; background: transparent;
  border-radius: var(--radius-sm); cursor: pointer; color: var(--text-tertiary);
  display: inline-flex; align-items: center; justify-content: center;
  transition: background var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}
.gt-btn:hover { background: var(--bg-subtle); color: var(--primary); }
.gt-btn.on { background: var(--primary-bg); color: var(--primary); }
.gt-sep { width: 1px; height: 18px; background: var(--border); margin: 0 4px; }
.gt-hint {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: var(--text-xs); color: var(--text-tertiary);
}

.gc-body {
  position: relative; width: 100%;
  background: var(--bg-subtle); border: 1px solid var(--border);
  border-radius: var(--radius-md); overflow: hidden;
}
.gc-canvas { width: 100%; height: 100%; }

.gc-overlay {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 9px;
  background: var(--bg-subtle); color: var(--text-tertiary); text-align: center;
  padding: 24px;
}
.gc-overlay .el-icon { color: var(--text-disabled); }
.go-title { font-size: var(--text-lg); font-weight: 650; color: var(--text-secondary); }
.go-desc { font-size: var(--text-sm); max-width: 380px; line-height: 1.7; }

.gc-legend {
  position: absolute; left: 12px; bottom: 12px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow-sm);
  padding: 10px 12px; max-width: 230px; max-height: 46%;
  overflow: auto;
}
.gc-legend.via { left: auto; right: 12px; }
.gl-head {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  font-size: var(--text-xs); font-weight: 600; color: var(--text-primary);
  text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 7px;
}
.gl-count { color: var(--text-tertiary); font-weight: 500; letter-spacing: 0; text-transform: none; }
.gl-item {
  display: flex; align-items: center; gap: 7px; width: 100%;
  padding: 4px 5px; border: none; background: transparent; cursor: pointer;
  border-radius: var(--radius-xs); font-family: inherit; text-align: left;
  transition: background var(--duration) var(--ease-out);
}
.gl-item:hover { background: var(--bg-subtle); }
.gl-item.static { cursor: default; }
.gl-item.static:hover { background: transparent; }
.gl-item.off { opacity: 0.42; }
.gl-swatch {
  width: 12px; height: 12px; border-radius: 4px; flex-shrink: 0;
  border: 2px solid; background: transparent;
}
.gl-item.off .gl-swatch { background: var(--bg-sunken) !important; }
.gl-line { width: 16px; height: 2.5px; border-radius: 2px; flex-shrink: 0; }
.gl-label {
  flex: 1; min-width: 0; font-size: var(--text-xs); color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gl-item.off .gl-label { text-decoration: line-through; }
.gl-num {
  font-size: var(--text-xs); color: var(--text-tertiary);
  font-variant-numeric: tabular-nums; flex-shrink: 0;
}

.gc-trunc {
  position: absolute; top: 12px; left: 12px;
  display: inline-flex; align-items: center; gap: 5px;
  background: var(--warning-bg); color: var(--warning);
  border-radius: var(--radius-full); padding: 4px 11px;
  font-size: var(--text-xs); font-weight: 600;
}

/* ---------- 节点详情 ---------- */
.gi { display: flex; flex-direction: column; height: 100%; }
.gi-head {
  display: flex; align-items: center; gap: 11px;
  padding: 16px 18px; border-bottom: 1px solid var(--border);
}
.gi-icon { font-size: 24px; line-height: 1; flex-shrink: 0; }
.gi-title { flex: 1; min-width: 0; }
.gi-name {
  font-size: var(--text-md); font-weight: 650; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gi-sub { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 2px; }

.gi-stats { display: flex; gap: 10px; padding: 14px 18px 0; }
.gis {
  flex: 1; text-align: center; padding: 10px 6px;
  background: var(--bg-subtle); border-radius: var(--radius-sm);
  display: flex; flex-direction: column; gap: 2px;
}
.gis-v {
  font-size: var(--text-lg); font-weight: 680; color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gis-l { font-size: var(--text-xs); color: var(--text-tertiary); }

.gi-tags { display: flex; gap: 6px; flex-wrap: wrap; padding: 12px 18px 0; }
.gi-actions { display: flex; gap: 8px; padding: 14px 18px; }

.gi-section { flex: 1; overflow: auto; padding: 0 18px 18px; }
.gi-sec-title {
  font-size: var(--text-sm); font-weight: 600; color: var(--text-secondary);
  margin-bottom: 9px;
}
.gi-nbrs { display: flex; flex-direction: column; gap: 6px; }
.gi-nbr {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  padding: 8px 11px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); cursor: pointer; font-family: inherit;
  transition: all var(--duration) var(--ease-out);
}
.gi-nbr:hover { border-color: var(--primary); background: var(--primary-bg); }
.gn-ico { font-size: 13px; line-height: 1; flex-shrink: 0; }
.gn-label {
  flex: 1; min-width: 0; font-size: var(--text-sm); color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gn-rel { font-size: var(--text-xs); color: var(--text-tertiary); flex-shrink: 0; }
.gi-empty {
  padding: 24px; text-align: center; font-size: var(--text-sm);
  color: var(--text-tertiary); border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
}

@media (max-width: 768px) {
  .gt-hint { display: none; }
  .gc-legend { max-width: 160px; max-height: 34%; }
  .gc-legend.via { display: none; }
}
</style>
