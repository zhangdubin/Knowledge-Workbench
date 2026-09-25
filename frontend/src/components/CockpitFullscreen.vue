<template>
  <Teleport to="body">
    <div v-if="visible" class="fs-screen" :class="`fs-theme-${theme}`" ref="rootEl">
      <!-- 顶栏：驾驶舱名 + 实时时钟 + 控制 -->
      <header class="fs-header">
        <div class="fs-brand">
          <span class="fs-logo">◈</span>
          <h1 class="fs-title">{{ dash?.name || '驾驶舱' }}</h1>
          <span v-if="dash?.description" class="fs-desc">{{ dash.description }}</span>
        </div>
        <div class="fs-clock">
          <div class="fs-time">{{ clock.time }}</div>
          <div class="fs-date">{{ clock.date }} {{ clock.week }}</div>
        </div>
        <div class="fs-actions">
          <el-tooltip content="切换配色" placement="bottom">
            <button class="fs-btn" @click="cycleTheme"><span class="fs-btn-ico">🎨</span></button>
          </el-tooltip>
          <el-tooltip placement="bottom">
            <template #content>
              自动刷新：{{ autoRefresh ? `${autoRefresh}s 一刷` : '已关闭' }}
              <br />点击切换 30s / 60s / 关
            </template>
            <button class="fs-btn" :class="{ on: !!autoRefresh }" @click="cycleRefresh">
              <span class="fs-btn-ico">{{ autoRefresh ? '⟳' : '⏸' }}</span>
            </button>
          </el-tooltip>
          <el-tooltip content="立即刷新" placement="bottom">
            <button class="fs-btn" @click="reload(true)"><span class="fs-btn-ico">↻</span></button>
          </el-tooltip>
          <el-tooltip content="退出大屏 (Esc)" placement="bottom">
            <button class="fs-btn fs-exit" @click="close"><span class="fs-btn-ico">✕</span></button>
          </el-tooltip>
        </div>
        <!-- 刷新倒计时进度条：贴在顶栏底部一条细线，不抢注意力 -->
        <div v-if="autoRefresh" class="fs-countdown" :key="tickKey"
             :style="{ animationDuration: `${autoRefresh}s` }" />
      </header>

      <!-- 卡片区：与桌面驾驶舱同一份 layout（自由坐标），只是渲染风格不同。
           大屏按视口等比缩放到刚好放下，所以桌面上排的版投出来一样是完整的。 -->
      <div class="fs-canvas">
        <CockpitCanvas
          ref="canvasEl"
          :layout="screenLayout"
          :computed="computedMap"
          skin="screen"
          :screen-theme="theme"
          fit-mode="fill"
          :scrollable="false"
          @open-row="(w, row) => emit('open-row', w, row)"
        />
      </div>

      <div v-if="!loading && !screenLayout.length" class="fs-empty">
        这个驾驶舱还没有卡片，先去编辑布局添加几张吧
      </div>
      <div v-if="loading" class="fs-loading"><span class="fs-spin" /> 加载中…</div>

      <div class="fs-foot">
        数据更新于 {{ lastRefreshText }}
        <template v-if="autoRefresh"> · {{ autoRefresh }}s 后自动刷新</template>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
/**
 * 全屏高级感驾驶舱（大屏）
 *
 * 与桌面 DashboardView 的关系：**同一份 layout、同一个 CockpitWidget**，
 * 只是换了一层「投放皮肤」——深色渐变底、网格纹理、霓虹点缀、实时时钟、
 * 自动刷新。桌面改了卡片，大屏跟着变，不存在两套配置。
 *
 * 实现要点：
 * - 尽量用浏览器原生 Fullscreen API（真全屏、无地址栏）；
 *   拿不到（iframe 受限 / 用户拒绝）就退化为 100vw/100vh 的 fixed 覆盖层。
 * - 主题（配色）与自动刷新间隔存在驾驶舱的 settings 里（dashboard.settings 列），
 *   换了下次进来还是你调的样子。
 * - 根元素上重定义了一套 --text-* / --bg-* 令牌：卡片内部的样式全走令牌，
 *   这样浅色主题的浏览器里大屏也能保持深色高级感，不依赖全局暗色开关。
 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Api } from '../api'
import CockpitCanvas from './CockpitCanvas.vue'
import { compactLayout, contentSize, normalizeLayout, stretchLayout, tidyLayout } from '../utils/canvas'

const props = defineProps({
  modelValue: Boolean,
  /** 驾驶舱元信息（含 settings） */
  dash: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'open-row'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const THEMES = [
  { key: 'nebula', label: '星云蓝' },
  { key: 'aurora', label: '极光紫' },
  { key: 'abyss', label: '深渊青' },
]

const layout = ref([])
const screenLayout = ref([])
const computedMap = ref({})
const loading = ref(false)
const theme = ref('nebula')
const autoRefresh = ref(30)
const rootEl = ref(null)
const canvasEl = ref(null)
const clock = reactive({ time: '--:--:--', date: '', week: '' })
const lastRefresh = ref(null)
const tickKey = ref(0)
let resizeRo = null

let clockTimer = null
let refreshTimer = null

const lastRefreshText = computed(() => {
  if (!lastRefresh.value) return '—'
  const d = new Date(lastRefresh.value)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
})

function startClock() {
  const tick = () => {
    const d = new Date()
    clock.time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
    clock.date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    clock.week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  }
  tick()
  clockTimer = setInterval(tick, 1000)
}

async function reload(manual = false) {
  if (!props.dash?.id) return
  loading.value = true
  try {
    const r = await Api.dashboardData(props.dash.id)
    computedMap.value = Object.fromEntries((r.widgets || []).map(w => [w.id, w]))
    // 老驾驶舱的 span 布局在这里也要换算，否则大屏上会全挤在左上角
    layout.value = normalizeLayout(props.dash.layout || [])
    rebuildScreenLayout()
    lastRefresh.value = Date.now()
    tickKey.value++                     // 重启倒计时动画
    if (manual) restartTimer()
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

/** 大屏布局策略：
 *  - 用户在自由画布上手工排过的布局（带 x/y）：**原样保留**，只做安全的
 *    行拉伸（stretchLayout 只动"看起来像货架"的行）。重排会毁掉用户的
 *    排版心血，曾导致「大屏和编辑器长得不一样」的投诉。
 *  - 老 span 布局（没有坐标）：按视口宽度重排，左右必须铺满，
 *    纵向尽量完整，放不下时回退更紧凑的策略。
 *  纵向超出视口不裁剪 —— 由 CockpitCanvas.fit('fill') 的 contain 缩放兜底。 */
function rebuildScreenLayout() {
  if (!layout.value.length) {
    screenLayout.value = []
    return
  }
  // 用 window.innerWidth/Height 而不是 rootEl.clientWidth：
  // rootEl 在 requestFullscreen 前后尺寸可能抖动，innerWidth 更稳
  const viewW = Math.max(1180, window.innerWidth - 64)
  const viewH = Math.max(540, window.innerHeight - 140)

  // 手工排过的自由布局：判断要用**原始** dash.layout（layout.value 已被
  // normalizeLayout 补过坐标，那时全都有 x/y，无法区分来源）
  const raw = props.dash?.layout || []
  const placed = raw.length > 0 && raw.every(w =>
    Number.isFinite(Number(w?.x)) && Number.isFinite(Number(w?.y)))
  if (placed) {
    screenLayout.value = stretchLayout(layout.value, viewW)
    return
  }

  const strategies = [
    // 大屏要左右铺满、纵向完整：先尝试最紧凑的普通货架排布
    { name: 'tidy', fn: () => tidyLayout(layout.value, { width: viewW, fill: true, smart: false }) },
    { name: 'compact', fn: () => stretchLayout(compactLayout(layout.value, { width: viewW }), viewW) },
    // 实在放不下再尝试智能（大卡独行）排布
    { name: 'smart', fn: () => tidyLayout(layout.value, { width: viewW, fill: true, smart: true }) },
  ]
  const candidates = strategies.map(s => {
    const c = s.fn()
    const size = contentSize(c, { margin: 0 })
    return { ...s, layout: c, size }
  })
  // 优先选能纵向完整显示且横向铺满的策略（宽高比大的优先）。
  // 宽度必须卡上界：超宽候选（自由布局残行宽于视口）宽高比最大、总赢，
  // 结果整体缩小、卡片视觉变小，还留取整缝（#128）。
  const fits = candidates.filter(c => c.size.h <= viewH
    && c.size.w >= viewW * 0.92 && c.size.w <= viewW + 8)
  let chosen
  if (fits.length) {
    chosen = fits.reduce((a, b) => ((a.size.w / a.size.h) > (b.size.w / b.size.h) ? a : b))
  } else {
    // 都放不下：选纵向最接近且横向最宽的；ratio 或宽度相同时保留排在前面的策略
    chosen = candidates.reduce((a, b) => {
      const ra = Math.max(1, a.size.h / viewH)
      const rb = Math.max(1, b.size.h / viewH)
      if (Math.abs(ra - rb) > 0.05) return ra < rb ? a : b
      return a.size.w >= b.size.w ? a : b
    })
  }
  screenLayout.value = chosen.layout
}

function restartTimer() {
  clearInterval(refreshTimer)
  refreshTimer = null
  if (autoRefresh.value > 0) {
    refreshTimer = setInterval(() => reload(), autoRefresh.value * 1000)
  }
}

function cycleTheme() {
  const i = THEMES.findIndex(t => t.key === theme.value)
  theme.value = THEMES[(i + 1) % THEMES.length].key
  persistSettings()
}

function cycleRefresh() {
  // 30s → 60s → 5min → 关
  const seq = [30, 60, 300, 0]
  const i = seq.indexOf(autoRefresh.value)
  autoRefresh.value = seq[(i + 1) % seq.length]
  restartTimer()
  persistSettings()
}

async function persistSettings() {
  if (!props.dash?.id) return
  const next = { ...(props.dash.settings || {}), theme: theme.value, auto_refresh: autoRefresh.value }
  // 同步内存里的 settings：不写这一步，关掉再开大屏仍会读到打开前的旧值
  props.dash.settings = next
  try {
    // settings 是显示偏好；写权限由后端校验，普通用户保存失败静默跳过
    await Api.updateDashboard(props.dash.id, { settings: next })
  } catch { /* 大屏设置保存失败不致命，下次再存 */ }
}

async function open() {
  const s = props.dash?.settings || {}
  theme.value = THEMES.some(t => t.key === s.theme) ? s.theme : 'nebula'
  autoRefresh.value = Number.isFinite(s.auto_refresh) ? s.auto_refresh : 30
  await reload()
  startClock()
  restartTimer()
  window.addEventListener('keydown', onKey)
  // 大屏容器尺寸变化时重新按视口宽度排布，保证左右始终铺满；防抖避免全屏切换时抖动
  if (typeof ResizeObserver !== 'undefined' && rootEl.value) {
    let t = null
    resizeRo = new ResizeObserver(() => {
      clearTimeout(t)
      t = setTimeout(() => rebuildScreenLayout(), 120)
    })
    resizeRo.observe(rootEl.value)
  }
  // 原生全屏失败不致命：fixed 覆盖层本身就是兜底
  try { await rootEl.value?.requestFullscreen?.() } catch { /* 用户拒绝或环境不支持 */ }
  // requestFullscreen 后有些浏览器尺寸不会立即反映，延迟再排一次
  setTimeout(() => rebuildScreenLayout(), 250)
}

function close() {
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
  visible.value = false
}

function onKey(e) {
  if (e.key === 'Escape') close()
}

function cleanup() {
  clearInterval(clockTimer)
  clearInterval(refreshTimer)
  clockTimer = refreshTimer = null
  window.removeEventListener('keydown', onKey)
  resizeRo?.disconnect()
  resizeRo = null
}

watch(visible, v => { if (v) open(); else cleanup() })
onBeforeUnmount(() => {
  cleanup()
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
})
</script>

<style scoped>
/* ============ 主题：底色 / 点缀色由 data 令牌驱动 ============ */
.fs-screen {
  position: fixed; inset: 0; z-index: 3000;
  display: flex; flex-direction: column;
  overflow: auto;
  font-family: var(--font-display);
  color: #e8ecf4;
  /* 本地重定义令牌：大屏内所有子组件（含 el-table）跟随这套深色系，
     不依赖全局暗色开关 —— 白天浅色主题下打开也照样成立 */
  --text-primary: #e8ecf4;
  --text-secondary: #aab4c6;
  --text-tertiary: #7f8aa0;
  --bg-card: rgba(16, 24, 40, 0.55);
  --bg-subtle: rgba(148, 163, 184, 0.08);
  --bg-sunken: rgba(148, 163, 184, 0.12);
  --border: rgba(148, 163, 184, 0.18);
  --border-light: rgba(148, 163, 184, 0.12);
  --primary: #22d3ee;
  --primary-light: #67e8f9;
  --primary-bg: rgba(34, 211, 238, 0.12);
  --primary-bg-strong: rgba(34, 211, 238, 0.28);
  background:
    radial-gradient(1200px 600px at 15% -10%, rgba(34, 211, 238, 0.13), transparent 55%),
    radial-gradient(1100px 550px at 85% 110%, rgba(99, 102, 241, 0.15), transparent 55%),
    linear-gradient(180deg, #060a14 0%, #0a1020 55%, #060a14 100%);
}
.fs-theme-aurora {
  --primary: #a78bfa; --primary-light: #c4b5fd;
  --primary-bg: rgba(167, 139, 250, 0.12); --primary-bg-strong: rgba(167, 139, 250, 0.30);
  background:
    radial-gradient(1200px 600px at 12% -10%, rgba(167, 139, 250, 0.16), transparent 55%),
    radial-gradient(1100px 550px at 88% 108%, rgba(236, 72, 153, 0.10), transparent 55%),
    linear-gradient(180deg, #0a0614 0%, #120a22 55%, #0a0614 100%);
}
.fs-theme-abyss {
  --primary: #2dd4bf; --primary-light: #5eead4;
  --primary-bg: rgba(45, 212, 191, 0.12); --primary-bg-strong: rgba(45, 212, 191, 0.30);
  background:
    radial-gradient(1200px 600px at 15% -10%, rgba(45, 212, 191, 0.14), transparent 55%),
    radial-gradient(1100px 550px at 85% 110%, rgba(56, 189, 248, 0.12), transparent 55%),
    linear-gradient(180deg, #04100e 0%, #07161a 55%, #04100e 100%);
}
/* 网格纹理：两层 1px 线叠加出 44px 网眼，透明度压到 4% 只提供「质感」 */
.fs-screen::before {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.05) 1px, transparent 1px);
  background-size: 44px 44px;
  -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 85%);
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 85%);
}

/* ============ 顶栏 ============ */
.fs-header {
  position: relative; flex-shrink: 0;
  display: flex; align-items: center; gap: 28px;
  padding: 18px 32px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(6, 10, 20, 0.35);
  backdrop-filter: blur(6px);
}
.fs-brand { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.fs-logo {
  color: var(--primary); font-size: 22px;
  filter: drop-shadow(0 0 8px var(--primary-bg-strong));
}
.fs-title {
  margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 2px;
  color: #fff; white-space: nowrap;
}
.fs-desc {
  font-size: 13px; color: var(--text-tertiary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.fs-clock { margin-left: auto; text-align: right; font-variant-numeric: tabular-nums; }
.fs-time {
  font-size: 30px; font-weight: 700; letter-spacing: 3px;
  color: var(--primary);
  text-shadow: 0 0 18px var(--primary-bg-strong);
}
.fs-date { font-size: 12.5px; color: var(--text-tertiary); letter-spacing: 1px; }

.fs-actions { display: flex; gap: 8px; }
.fs-btn {
  width: 34px; height: 34px; border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(148, 163, 184, 0.08); color: var(--text-secondary);
  cursor: pointer; font-size: 15px;
  transition: all .2s;
}
.fs-btn:hover { color: #fff; border-color: var(--primary); box-shadow: 0 0 12px var(--primary-bg); }
.fs-btn.on { color: var(--primary); border-color: var(--primary); }
.fs-btn-ico { font-size: 15px; line-height: 1; }

/* 倒计时进度线 */
.fs-countdown {
  position: absolute; left: 0; bottom: -1px; height: 2px; width: 100%;
  background: linear-gradient(90deg, var(--primary), transparent);
  transform-origin: left;
  animation: fs-count linear forwards;
}
@keyframes fs-count {
  from { transform: scaleX(1); }
  to { transform: scaleX(0); }
}

/* ============ 卡片区 ============
   自由画布由 CockpitCanvas 负责（skin="screen" 时它自带玻璃质感卡片、
   透明表格等大屏皮肤），这里只需要给它一块铺满的容器。 */
.fs-canvas {
  position: relative;
  flex: 1;
  min-height: 0;
  padding: 22px 32px;
  display: flex;
}
.fs-canvas > * { flex: 1; min-width: 0; }

.fs-empty, .fs-loading {
  position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center; gap: 10px;
  color: var(--text-tertiary); font-size: 16px; letter-spacing: 1px;
}
.fs-spin {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid var(--primary-bg-strong); border-top-color: var(--primary);
  animation: fs-rot .8s linear infinite;
}
@keyframes fs-rot { to { transform: rotate(360deg); } }

.fs-foot {
  flex-shrink: 0; padding: 10px 32px 14px;
  font-size: 12px; color: var(--text-tertiary); letter-spacing: 1px;
  border-top: 1px solid rgba(148, 163, 184, 0.10);
}

@media (max-width: 760px) {
  .fs-header { padding: 12px 16px; gap: 12px; flex-wrap: wrap; }
  .fs-title { font-size: 18px; letter-spacing: 1px; }
  .fs-time { font-size: 22px; }
  .fs-canvas { padding: 14px 16px; }
}
</style>
