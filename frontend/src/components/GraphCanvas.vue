<template>
  <div class="gc" :class="{ 'is-fs': isFullscreen }">
    <!-- 工具条 -->
    <div class="gc-toolbar">
      <div class="gt-tools">
        <el-tooltip :content="isFullscreen ? '退出全屏（Esc）' : '全屏显示'" placement="top">
          <button
            class="gt-btn"
            :class="{ on: isFullscreen }"
            aria-label="全屏显示"
            @click="toggleFullscreen"
          >
            <el-icon><Rank /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="适应画布" placement="top">
          <button class="gt-btn" aria-label="适应画布" @click="fit"><el-icon><FullScreen /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="放大" placement="top">
          <button class="gt-btn" aria-label="放大" @click="zoom(1.25)"><el-icon><ZoomIn /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="缩小" placement="top">
          <button class="gt-btn" aria-label="缩小" @click="zoom(0.8)"><el-icon><ZoomOut /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="重新计算布局" placement="top">
          <button class="gt-btn" :class="{ on: physicsOn }" aria-label="重新计算布局" @click="relayout">
            <el-icon><RefreshRight /></el-icon>
          </button>
        </el-tooltip>
        <span class="gt-sep" />
        <el-tooltip content="显示名称 / 仅图标" placement="top">
          <button class="gt-btn" :class="{ on: showLabels }" aria-label="显示名称" @click="toggleLabels">
            <el-icon><Postcard /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="显示关系名称（悬停连线也会临时显示）" placement="top">
          <button class="gt-btn" :class="{ on: showEdgeLabels }" aria-label="显示关系名称" @click="toggleEdgeLabels">
            <el-icon><Memo /></el-icon>
          </button>
        </el-tooltip>
        <span class="gt-sep" />
        <el-tooltip content="全选图例 / 只留中心" placement="top">
          <button class="gt-btn" aria-label="全选图例" @click="toggleAllGroups"><el-icon><View /></el-icon></button>
        </el-tooltip>
      </div>
      <div class="gt-hint">
        <el-icon :size="12"><InfoFilled /></el-icon>
        滚轮缩放 · 拖拽平移 · 悬停节点或连线看关系名 · 点击查看详情
      </div>
    </div>

    <div class="gc-body" :style="bodyStyle">
      <div ref="host" class="gc-canvas" />

      <!--
        关系名覆盖层
        ---------------------------------------------------------------------------
        为什么不用 canvas 里的边标签：vis 把边标签画在「边」那一层，
        节点画在更上面一层 —— 节点一多，边标签就会被节点盖住；
        而一次画几十个标签，彼此又会压在一起。
        改成用 HTML 单独画：想显示哪条就显示哪条，永远压在最上面，
        还能自己错开位置。
      -->
      <div v-if="edgeTips.length" class="gc-tips">
        <div
          v-for="t in edgeTips"
          :key="t.id"
          class="gct"
          :style="{ transform: `translate3d(${t.x}px, ${t.y}px, 0) translate(-50%, -50%)` }"
        >
          <span class="gct-chip" :style="{ background: t.color }" />
          <span class="gct-text">{{ t.text }}</span>
        </div>
      </div>

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
          <span
            class="gl-line"
            :class="{ dash: v.dash }"
            :style="{ background: v.dash ? 'transparent' : v.color, borderColor: v.color }"
          />
          <span class="gl-label">{{ v.label }}</span>
          <span class="gl-num">{{ v.count }}</span>
        </div>
      </div>

      <div v-if="truncated" class="gc-trunc">
        <el-icon :size="12"><WarningFilled /></el-icon>节点过多，已按类型配额截断显示
      </div>

      <!--
        图太大放不下时的提示
        为什么要有：手机上缩得太小字就认不出，缩到能认出的程度就必然放不下，
        得告诉用户「可以拖动」，否则会以为图缺了一块。
      -->
      <div v-if="zoomClamped" class="gc-zoom-hint">
        <el-icon :size="12"><InfoFilled /></el-icon>放大后更清晰，可拖动查看全图
      </div>

      <!--
        文字档位提示
        为什么藏字要说话：「字不见了」看起来像 bug，不像设计。
        说清楚「放大就能看见」，用户才知道怎么找回。
      -->
      <div v-if="tierHintText" class="gc-zoom-hint">
        <el-icon :size="12"><InfoFilled /></el-icon>{{ tierHintText }}
      </div>
    </div>

    <!-- 全屏时的退出条：浮层会盖住工具条，得有个明显的地方能退出来 -->
    <div v-if="isFullscreen" class="gc-fs-bar">
      <span class="gc-fs-title">{{ fsTitle }}</span>
      <button class="gc-fs-exit" @click="exitFullscreen">
        <el-icon><Close /></el-icon>退出全屏（Esc）
      </button>
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
import { DataSet, Network } from 'vis-network/standalone'
import { chartTheme, cssVar, isDark } from '../utils/theme'
import {
  viaMeta, minScaleFor,
  mix, lift, truncateLabel, textWidth,
  LABEL_TIER, labelTierFor, labelCharsForTier, fontSizeForTier, tierHint,
} from '../utils/graphStyle'
import { useGraphFullscreen } from '../composables/useGraphFullscreen'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  truncated: { type: Boolean, default: false },
  height: { type: String, default: '620px' },
  // 'type' 按数据模型着色（关联图谱），'tag' 按首个标签着色（知识图谱）
  colorBy: { type: String, default: 'type' },
  emptyHint: { type: String, default: '换个范围或先建立一些关联' },
  // 全屏时左上角显示的名字（哪个图谱，得说清楚）
  title: { type: String, default: '图谱' },
})
const emit = defineEmits(['select', 'recenter'])

const host = ref(null)
const inspectorOpen = ref(false)
const active = ref(null)
const showLabels = ref(true)
// 边标签默认不显示：几十条边全挂着字，等于没有标签。
// 改成「悬停某条边 / 悬停某个节点时才显示相关边的关系名」。
const showEdgeLabels = ref(false)
const hoverEdgeId = ref(null)
const hoverNodeId = ref(null)
const hiddenGroups = ref(new Set())
const physicsOn = ref(false)
const windowWidth = ref(1440)
// 悬停时浮在画布上的关系名（HTML 覆盖层，永远压在最上面）
const edgeTips = ref([])
// 标签位置的指纹：没变就不动状态，避免平移画布时白白重渲染
const tipSignature = ref('')
// 缩放被下限卡住（也就是图太大、手机上看不全）
const zoomClamped = ref(false)
// 当前的「文字档位」：随缩放在 hidden/brief/full/large 之间跳
const labelTier = ref(LABEL_TIER.full)

const network = shallowRef(null)
// 图谱相关的清理动作（事件监听等）：组件卸载时统一撤掉
const graphCleanups = []
const nodesDS = shallowRef(null)
const edgesDS = shallowRef(null)
const built = shallowRef({ nodes: [], edges: [] })

const drawerSize = computed(() => (windowWidth.value < 760 ? '100%' : '360px'))

/** 画布区域的高度：全屏时铺满，普通时用页面传进来的高度 */
const bodyStyle = computed(() => ({ height: isFullscreen.value ? '100%' : props.height }))

/** 当前档位要给用户的一句提示（藏字/只显示图标时才说） */
const tierHintText = computed(() => tierHint(labelTier.value))

/** 全屏条上显示的名字 */
const fsTitle = computed(() => props.title)

/**
 * 按当前档位重算节点文字
 *
 * 为什么要单独一个函数、而不是在 zoom 回调里直接改：
 *   zoom 事件在滚轮缩放时每帧都触发，一次图可能有几百个节点 ——
 *   每帧都重写一遍节点数据会明显卡顿。
 *   所以只在**档位真的变了**时才重算（跨过阈值是低频事件）。
 */
function applyLabelTier(force = false) {
  const net = network.value
  if (!net || !nodesDS.value) return
  const tier = labelTierFor(net.getScale())
  if (!force && tier === labelTier.value) return
  labelTier.value = tier
  // 整批重算：节点数据里字号、名字是一起决定的，
  // 只改其中一半会出现「名字变了、字号没变」的半吊子状态
  const nodes = buildNodes()
  built.value = { ...built.value, nodes }
  nodesDS.value.update(nodes)
  // 边上的关系名也该跟着收：档位降下来时一屏挂几十个关系名反而看不清
  applyEdgeLabels()
}

/** 缩放事件的节流：滚轮缩放时每帧都来，只在下一帧处理一次 */
let tierRaf = 0
function scheduleTierCheck() {
  if (tierRaf) return
  tierRaf = requestAnimationFrame(() => {
    tierRaf = 0
    applyLabelTier()
  })
}

/**
 * 全屏切换后：图必须重新量尺寸、重新对中
 *
 * 为什么不能只靠 resize 事件：
 *   全屏是**布局变了但 window 没变**，resize 事件根本不会触发。
 *   而且 vis-network 只在初始化时读一次容器尺寸 —— 不显式 setSize，
 *   画布还停在旧大小，只是被 CSS 拉大了（画面会糊、位置会偏）。
 */
function onFullscreenChange() {
  const net = network.value
  const el = host.value
  if (!net || !el) return
  net.setSize(`${el.clientWidth}px`, `${el.clientHeight}px`)
  // setSize 会按新旧画布的比例缩放视图 —— 必须重新对中，否则图会偏到一边
  net.fit({ animation: false })
  setTimeout(() => { applyMinScale(); applyLabelTier(true) }, 60)
}

const { isFullscreen, toggle: toggleFullscreen, exit: exitFullscreen } =
  useGraphFullscreen(onFullscreenChange)

/** 主题令牌：必须 touch isDark 才能让暗色切换重算 */
const theme = computed(() => {
  void isDark.value
  return chartTheme()
})

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
      const meta = viaMeta(key)
      return { key, count, label: meta.label, color: viaColor(meta), dash: meta.dash }
    })
})

/**
 * 连线颜色：固定色相 + 主题适配
 *
 * 暗色模式下把颜色往白里提一档，否则 #5b5fc7 这种深色在 #15171d 的底上
 * 只有 3.3:1，看久了很吃力。
 */
function viaColor(meta) {
  const t = theme.value
  const base = t.colors[meta.slot % t.colors.length]
  return t.dark ? lift(base, 0.3) : base
}

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

/**
 * 节点上画什么字
 *
 * 三个因素共同决定：
 *   1. 用户手动关了标签（showLabels）
 *   2. 当前缩放档位（labelTier）—— 缩得太小就一个字都不画
 *   3. 节点本身有没有图标
 *
 * 为什么「缩得太小」要一个字都不留：
 *   canvas 上的字是跟着缩放一起变小的 —— 缩到 0.4 倍，
 *   13px 的字只剩 5px，比一根头发粗不了多少，
 *   这种字不是「看不清」，是「看起来像噪点」，反而把图弄脏。
 */
function labelOf(n) {
  if (labelTier.value === LABEL_TIER.hidden) return ''
  if (!showLabels.value || labelTier.value === LABEL_TIER.brief) return n.icon || ''
  return `${n.icon || ''} ${n.label || ''}`.trim()
}

/**
 * 节点字号
 *
 * 窄屏字号要大一点：画布会被缩到 0.62 倍，
 * 13px 缩完只剩 8px，屏幕上根本认不出字
 */
function nodeFontSize(isCenter) {
  if (isCenter) return 16
  return windowWidth.value < 760 ? 15 : 13
}

function buildNodes() {
  const t = theme.value
  const centerFill = cssVar('--primary-dark', '#474bb0')
  const card = t.card
  const textStrong = cssVar('--text-primary', '#17181d')
  const maxChars = labelCharsForTier(labelTier.value, windowWidth.value)
  const tierFont = fontSizeForTier(labelTier.value, nodeFontSize(false))
  return props.nodes.map(n => {
    const c = colorOf(groupOfRaw(n))
    const isCenter = !!n.center
    const isDoc = n.kind === 'document'
    const dimText = t.dark ? 'rgba(236,238,242,0.26)' : 'rgba(23,24,29,0.26)'

    // 节点底色做成不透明的：半透明底挡不住线，线会从文字底下穿过去。
    // 底色是「类型色 + 卡片色」的浅色混合，类型靠边框颜色体现 ——
    // 底色太浓的话文字压上去对比度就不够了。
    const fill = isCenter ? centerFill : mix(card, c, t.dark ? 0.26 : 0.16)
    const stroke = isCenter ? centerFill : (t.dark ? lift(c, 0.3) : c)
    const text = isCenter ? '#ffffff' : textStrong

    return {
      id: n.id,
      label: truncateLabel(labelOf(n), maxChars),
      title: `${n.icon || ''} ${n.label}\n${n.type_name || ''}${n.tags?.length ? ' · ' + n.tags.map(x => '#' + x).join(' ') : ''}`,
      shape: 'box',
      shapeProperties: { borderRadius: isDoc ? 4 : 9 },
      borderDashes: isDoc ? [5, 3] : false,      // 文件端用虚线边框区分
      margin: isCenter
        ? { top: 12, bottom: 12, left: 17, right: 17 }
        : { top: 9, bottom: 9, left: 12, right: 12 },
      borderWidth: isCenter ? 3 : 2,
      color: {
        background: fill,
        border: stroke,
        highlight: { background: mix(card, c, t.dark ? 0.38 : 0.28), border: stroke },
        hover: { background: mix(card, c, t.dark ? 0.34 : 0.24), border: stroke },
      },
      font: {
        color: text,
        size: isCenter ? tierFont + 3 : tierFont,
        face: 'system-ui, -apple-system, "PingFang SC", sans-serif',
        // 标签底板用节点自己的底色，边线不会从字底下透出来
        background: fill,
        strokeWidth: 0,
      },
      shadow: t.dark
        ? { enabled: false }
        : { enabled: true, color: 'rgba(16,18,27,0.10)', size: 8, x: 0, y: 2 },
      // 悬停淡化用的预置变体：避免每次 hover 都解析颜色
      _on: {
        color: { background: fill, border: stroke },
        font: { color: text, size: isCenter ? tierFont + 3 : tierFont, background: fill },
        borderWidth: isCenter ? 3 : 2,
      },
      _off: {
        color: { background: mix(card, c, t.dark ? 0.1 : 0.07), border: mix(card, c, t.dark ? 0.12 : 0.1) },
        font: { color: dimText, size: isCenter ? tierFont + 3 : tierFont, background: 'transparent' },
        borderWidth: 1,
      },
    }
  })
}

function buildEdges(validIds) {
  const t = theme.value
  const card = t.card
  const textStrong = cssVar('--text-primary', '#17181d')
  // 同一对节点之间的多条边要错开：给不同的弯曲度，曲线与标签自然分开
  const pairSeen = new Map()
  return props.edges
    .filter(e => validIds.has(e.source) && validIds.has(e.target))
    .map(e => {
      const meta = viaMeta(e.via)
      const c = viaColor(meta)
      const dim = mix(c, card, t.dark ? 0.22 : 0.18)
      const arrow = { enabled: meta.arrow, scaleFactor: 0.6 }
      const pairKey = [e.source, e.target].sort().join('|')
      const idx = pairSeen.get(pairKey) || 0
      pairSeen.set(pairKey, idx + 1)
      return {
        id: e.id,
        from: e.source,
        to: e.target,
        // 默认不画标签：靠 hover 触发（见 applyEdgeLabels）
        label: '',
        arrows: { to: arrow, from: { enabled: false }, middle: { enabled: false } },
        color: {
          color: c,
          highlight: c,
          hover: c,
        },
        width: e.via === 'wikilink' ? 1.8 : 1.6,
        // 双向链接没有方向，用虚线；外键引用用连续曲线减少交叠
        dashes: meta.dash ? [6, 5] : false,
        smooth: {
          enabled: true,
          type: e.via === 'reference' ? 'continuous' : 'dynamic',
          roundness: 0.15 + idx * 0.4,
        },
        font: {
          color: textStrong,
          size: 11,
          align: 'middle',
          // 底板 + 同色描边：标签压在线上面，不会和线混成一团
          background: card,
          strokeWidth: 5,
          strokeColor: card,
        },
        _from: e.source,
        _to: e.target,
        _on: { color: { color: c, opacity: 1 }, width: e.via === 'wikilink' ? 2.2 : 2 },
        _off: { color: { color: dim, opacity: 1 }, width: 1, font: { color: 'rgba(0,0,0,0)' } },
        _label: e.relation || '',
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
  startTipTimer()
  net.fit({ animation: false })
  // fit 之后的缩放可能落在「字该藏」的区间，先把档位对齐
  applyLabelTier(true)
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
  stopTipTimer()
  net.fit({ animation: { duration: 380, easingFunction: 'easeInOutQuad' } })
  // fit 是带动画的，等它跑完再把缩放拉回可读区间
  setTimeout(() => { applyMinScale(); scheduleTipRefresh() }, 430)
}

/** 物理布局期间标签要跟着节点走，慢速跟一次就够了 */
let tipTimer = 0
function startTipTimer() {
  if (tipTimer) return
  tipTimer = setInterval(() => { if (physicsOn.value) updateEdgeTips() }, 220)
}
function stopTipTimer() {
  if (tipTimer) { clearInterval(tipTimer); tipTimer = 0 }
}

/**
 * 缩放的下限
 *
 * 为什么要卡下限：手机上把整张图 fit 进 390px 宽，缩放只有 0.28，
 * 13px 的节点名缩成 3.6px —— 什么字都认不出。
 * 「看得全」和「看得清」必须选一个，这里选「看得清」：
 * 缩到能读为止，剩下的交给拖动和「以它为中心」。
 */
function minScale() {
  return minScaleFor(windowWidth.value)
}

function applyMinScale() {
  const net = network.value
  if (!net) return
  const min = minScale()
  if (net.getScale() < min) {
    net.moveTo({ scale: min, animation: { duration: 320, easingFunction: 'easeInOutQuad' } })
    zoomClamped.value = true
  } else {
    zoomClamped.value = false
  }
  // 缩放被拉回来了，文字档位也得跟着重算（可能从 hidden 回到 brief/full）
  applyLabelTier(true)
}

function createNetwork() {
  const options = {
    layout: { improvedLayout: true },
    physics: {
      enabled: true,
      // 斥力更大、弹簧更松：节点之间要留出能读标签的空隙，
      // 挤成一坨的图再漂亮也没法看
      barnesHut: {
        gravitationalConstant: -11000,
        springLength: 240,
        springConstant: 0.018,
        damping: 0.55,
        avoidOverlap: 0.85,
      },
      stabilization: { iterations: 420, fit: true },
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
  // 缩放变了 → 文字档位可能要跟着变（缩太小就把名字藏起来）
  //
  // 为什么两个事件都要挂：
  //   vis 的 'zoom' 事件只在「鼠标滚轮 / 键盘快捷键」缩放时才发，
  //   代码调用 moveTo({scale})（工具条的放大缩小按钮、fit）**不发**。
  //   只挂 'zoom' 的话，点按钮放大缩小就不会跟着调文字。
  //   'afterDrawing' 每次重绘都发，缩放必然引起重绘 —— 补上这一路才完整。
  net.on('zoom', scheduleTierCheck)
  net.on('afterDrawing', scheduleTierCheck)
  net.on('stabilizationIterationsDone', onStabilized)
  net.on('hoverNode', p => {
    // vis 的 hoverNode 事件里是 node（单个 id），不是 nodes 数组
    hoverNodeId.value = p.node ?? p.nodes?.[0] ?? null
    highlight(hoverNodeId.value)
    applyEdgeLabels()
  })
  net.on('blurNode', () => {
    hoverNodeId.value = null
    highlight(null)
    applyEdgeLabels()
  })
  net.on('hoverEdge', p => {
    hoverEdgeId.value = p.edge ?? null
    applyEdgeLabels()
  })
  net.on('blurEdge', () => {
    hoverEdgeId.value = null
    applyEdgeLabels()
  })
  net.on('drag', () => scheduleTipRefresh())
  net.on('zoom', () => scheduleTipRefresh())
  net.on('selectNode', p => {
    const raw = rawById.value[p.node ?? p.nodes?.[0]]
    if (raw) { active.value = raw; inspectorOpen.value = true }
  })
  net.on('dragEnd', () => { /* 拖动后不重排，交给用户 */ })
  // 指针离开画布时把悬停状态清掉：
  // 否则关系名会一直浮在图上，鼠标都已经不在图里了
  // 监听器要留着句柄：匿名函数卸载时没法移除，
  // 组件销毁后监听还在 → 指针再进出这块区域就会去操作已经销毁的 network。
  const onMouseLeave = () => {
    hoverNodeId.value = null
    hoverEdgeId.value = null
    highlight(null)
    applyEdgeLabels()
  }
  host.value?.addEventListener('mouseleave', onMouseLeave)
  graphCleanups.push(() => host.value?.removeEventListener('mouseleave', onMouseLeave))
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
    }
  }))
  applyEdgeLabels()
}

/**
 * 决定每条边要不要显示关系名
 *
 * 为什么默认不显示：一张图几十条边，全挂着标签就等于没有标签 ——
 * 标签互相压住，谁也读不出来。改成按需：
 *   · 悬停某条边 → 只显示这一条
 *   · 悬停某个节点 → 显示与它相连的边（这时最需要知道「这条线是什么关系」）
 *   · 工具条里打开「显示关系名称」→ 全部显示
 *
 * 为什么不用 canvas 自带的边标签：vis 把边标签画在「边」那一层，
 * 节点画在更上面一层 —— 节点一多，边标签就被节点盖住；
 * 而且 vis 不允许把标签清空（空字符串会被当成非法值，旧标签留着），
 * 开开关就没法关。统一改成 HTML 覆盖层画：想显示哪条就显示哪条，
 * 永远压在最上面，还能自己错开位置。
 */
function applyEdgeLabels() {
  updateEdgeTips()
}

// 一次最多浮出多少个关系名：再多 DOM 会拖慢动画，
// 而且一屏全是标签本来也读不了
const TIP_MAX = 160

/**
 * 计算该浮出哪些关系名，并摆到不会互相压住的位置
 *
 * 错开方式：按画布位置排好序，再逐个往下推 —— 后一个跟已摆好的重叠就往下挪，
 * 直到不重叠为止。这样同一对节点之间的多条边，标签会排成一列而不是叠在一起。
 */
function updateEdgeTips() {
  const net = network.value
  if (!net) { edgeTips.value = []; return }
  // 档位降到「字都藏了」时，关系名也不画：
  // 名字在这个缩放下根本看不清，画一堆标签只是把图弄脏
  if (labelTier.value === LABEL_TIER.hidden) {
    edgeTips.value = []
    tipSignature.value = ''
    return
  }
  const hoverE = hoverEdgeId.value
  const hoverN = hoverNodeId.value
  const all = showEdgeLabels.value

  let wanted
  if (all) {
    wanted = built.value.edges.filter(e => e._label)
  } else if (hoverE) {
    wanted = built.value.edges.filter(e => e.id === hoverE && e._label)
  } else if (hoverN) {
    wanted = built.value.edges.filter(e => (e._from === hoverN || e._to === hoverN) && e._label)
  } else {
    edgeTips.value = []
    tipSignature.value = ''
    return
  }
  if (!wanted.length) {
    edgeTips.value = []
    tipSignature.value = ''
    return
  }
  const truncated = wanted.length > TIP_MAX
  if (truncated) wanted = wanted.slice(0, TIP_MAX)

  const placed = []
  const tips = []
  for (const e of wanted) {
    const inst = net.body.edges[e.id]
    if (!inst) continue
    const pt = inst.edgeType.getPoint(0.5)
    const dom = net.canvasToDOM(pt)
    const w = textWidth(e._label, 12) + 26
    const h = 22
    let y = dom.y - h / 2
    const x = dom.x - w / 2
    // 往下推，避开已经摆好的标签
    let guard = 0
    while (guard++ < 24 && placed.some(p => Math.abs(p.y - y) < h && Math.abs(p.x - x) < (p.w + w) / 2)) {
      y += h + 3
    }
    placed.push({ x, y, w, h })
    tips.push({ id: e.id, text: e._label, x, y, color: e.color?.color || '#888' })
  }

  // 位置没变就别动 Vue 的状态，避免拖动画布时白白重渲染
  const sig = tips.map(t => `${t.id}:${Math.round(t.x)}:${Math.round(t.y)}`).join('|')
  if (sig === tipSignature.value) return
  tipSignature.value = sig
  edgeTips.value = tips
}

/** 视图变了（平移/缩放/布局变化）标签要跟着动 */
function scheduleTipRefresh() {
  if (tipRaf) return
  tipRaf = requestAnimationFrame(() => {
    tipRaf = 0
    updateEdgeTips()
  })
}

// ---------- 工具条动作 ----------

function fit() {
  network.value?.fit({ animation: { duration: 380, easingFunction: 'easeInOutQuad' } })
  // fit 之后把缩放拉回可读区间，否则手机上整张图缩成一团小点
  setTimeout(applyMinScale, 420)
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
  // 档位决定「留几个字」，所以整批重算而不是只换 label 字段
  applyLabelTier(true)
}

function toggleEdgeLabels() {
  showEdgeLabels.value = !showEdgeLabels.value
  applyEdgeLabels()
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
  stopTipTimer()
  // 撤掉画布上的事件监听
  while (graphCleanups.length) {
    try { graphCleanups.pop()() } catch { /* 清理失败不影响卸载 */ }
  }
  // 别把已销毁的 network 留在 window 上：
  // 验收脚本会读它，拿到的却是上一张图的「尸体」，测出来的东西全是错的
  if (window.__kbGraph === network.value) window.__kbGraph = null
  network.value?.destroy()
  network.value = null
})

// 数据变 → 重画；主题变 → 重画（颜色已经写进 vis 的 item 里，不会自己更新）
watch(() => [props.nodes, props.edges], draw, { deep: false })
watch(isDark, draw)
watch(() => props.colorBy, () => { hiddenGroups.value = new Set(); draw() })

// 视口宽度变了：标签截断长度要跟着变（窄屏留短一点），
// 顺便把缩放拉回可读区间 —— 旋转手机后 fit 出来的缩放往往又太小了
watch(windowWidth, () => {
  // 档位里的字数预算跟视口宽度有关，整批重算
  applyLabelTier(true)
  setTimeout(applyMinScale, 120)
})

defineExpose({ fit, zoom, relayout })
</script>

<style scoped>
.gc { position: relative; }

/* ---------- 全屏 ---------- */
/*
 * 铺满视口的浮层，而不是浏览器的 Fullscreen API：
 *   API 在 iframe 里可能被拒、会把浏览器 UI 一起换掉（触屏上出不来）。
 *   浮层方案在任何环境都成立，而且工具条、图例都还在。
 */
.gc.is-fs {
  position: fixed;
  inset: 0;
  /* 1999：正好在 Element Plus 弹层基线（2000）之下。
     节点详情抽屉是 append-to-body 的，z-index 由 Element Plus 统一发号，
     浮层压得太高会把抽屉盖住 —— 全屏里点节点却看不见详情，最难排查。 */
  z-index: 1999;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  padding: 12px;
  box-sizing: border-box;
}
.gc.is-fs .gc-toolbar {
  flex: 0 0 auto;
  margin-bottom: 10px;
}
.gc.is-fs .gc-body {
  flex: 1 1 auto;
  min-height: 0;
}
.gc-fs-bar {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 6;
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 5px 6px 5px 12px;
  box-shadow: var(--shadow-sm);
}
.gc-fs-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.gc-fs-exit {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  padding: 5px 10px;
  font-size: var(--text-xs);
  cursor: pointer;
}
.gc-fs-exit:hover { background: var(--primary-bg); color: var(--primary); }

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
  /* 视口相对高度之下再保个下限：窗口很矮时画布不能塌成一条缝 */
  min-height: 320px;
}
.gc-canvas { width: 100%; height: 100%; }

/* ---------- 悬停时浮出的关系名 ---------- */
.gc-tips {
  position: absolute; inset: 0;
  pointer-events: none;   /* 不能挡住画布上的悬停 */
}
.gct {
  position: absolute; left: 0; top: 0;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px 3px 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  box-shadow: var(--shadow-sm);
  font-size: var(--text-xs); line-height: 1.35;
  color: var(--text-primary);
  white-space: nowrap;
  will-change: transform;
}
.gct-chip {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.gct-text { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }

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
  padding: 10px 12px; max-width: 230px;
  /* 图例不能被画布底边裁掉：留出 12px 的余量，
     并且给一个下限高度，让它自己滚动而不是被 overflow:hidden 切掉 */
  max-height: calc(100% - 24px);
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
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
/* 虚线关系（图例里要跟实线区分开） */
.gl-line.dash {
  height: 0; border-top: 2px dashed;
  border-top-style: dashed; background: transparent !important;
}
.gl-label {
  flex: 1; min-width: 0; font-size: var(--text-xs); color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gl-item.off .gl-label { text-decoration: line-through; }
.gl-num {
  font-size: var(--text-xs); color: var(--text-tertiary);
  font-variant-numeric: tabular-nums; flex-shrink: 0;
}

.gc-zoom-hint {
  position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%);
  display: inline-flex; align-items: center; gap: 5px;
  background: var(--bg-card); color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-full); padding: 4px 11px;
  font-size: var(--text-xs); white-space: nowrap;
  box-shadow: var(--shadow-xs);
  pointer-events: none;
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
  .gc-legend { max-width: 150px; max-height: 32%; }
  /* 手机上也保留连线图例：颜色是「这条线是什么关系」的唯一线索，
     直接隐藏等于让用户只能靠猜 */
  .gc-legend.via { max-width: 132px; max-height: 24%; }
  .gl-line { width: 12px; }
}
</style>
