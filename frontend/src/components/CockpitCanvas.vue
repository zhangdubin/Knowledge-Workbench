<template>
  <div
    ref="rootEl"
    class="cv"
    :class="[`cv-${skin}`, { 'is-edit': edit, 'is-drag': !!drag, 'cv-locked': !scrollable }]"
    tabindex="0"
    @pointerdown="onRootPointerDown"
    @dblclick="onDblClick"
    @wheel="onWheel"
  >
    <div ref="scrollEl" class="cv-scroll">
      <div class="cv-space" :style="spaceStyle">
        <div ref="contentEl" class="cv-content" :style="contentStyle">
          <div v-if="edit" class="cv-grid" :style="gridStyle" />

          <!-- 对齐辅助线：只在拖动时出现，松手即消失 -->
          <div v-for="(g, i) in guides" :key="`g${i}`" class="cv-guide" :class="g.k" :style="g.style" />

          <div
            v-for="(w, i) in layout"
            :key="w.id"
            class="cv-card"
            :class="[`cv-t-${w.type}`, { sel: selected === i, moving: drag && drag.index === i }]"
            :style="cardStyle(w, i)"
            :data-wid="w.id"
            :data-idx="i"
            @pointerdown="onCardDown($event, i)"
          >
            <!-- 编辑态卡片工具条：整张卡都是拖拽区 -->
            <div v-if="edit" class="cv-bar">
              <span class="cb-grip" title="按住拖动"><el-icon :size="12"><Rank /></el-icon></span>
              <span class="cb-title">{{ w.title || '未命名卡片' }}</span>
              <span class="spacer" />
              <span class="cb-size">{{ Math.round(cur(w, i).w) }} × {{ Math.round(cur(w, i).h) }}</span>
              <button class="cb-btn" title="配置" @click.stop="emit('edit-widget', i)">
                <el-icon :size="13"><Setting /></el-icon>
              </button>
              <button class="cb-btn" title="置顶（叠放顺序）" @click.stop="emit('front', i)">
                <el-icon :size="13"><Top /></el-icon>
              </button>
              <button class="cb-btn danger" title="删除这张卡片" @click.stop="emit('remove', i)">
                <el-icon :size="13"><Delete /></el-icon>
              </button>
            </div>

            <div class="cv-body">
              <CockpitWidget
                :widget="computedFor(w)"
                :screen="skin === 'screen'"
                :screen-theme="screenTheme"
                :body-height="bodyHeight(w)"
                :table-height="tableHeight(w)"
                @open-row="row => emit('open-row', w, row)"
              />
            </div>

            <!-- 八向缩放手柄 -->
            <template v-if="edit">
              <span
                v-for="h in HANDLES"
                :key="h"
                class="cv-h"
                :class="`h-${h}`"
                :data-handle="h"
                @pointerdown.stop="onResizeDown($event, i, h)"
              />
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 画布工具条：缩放 / 吸附 / 自动整理 -->
    <div v-if="edit" class="cv-dock" @pointerdown.stop>
      <button class="dk" title="缩小" @click="zoomBy(-0.1)">−</button>
      <button class="dk val" title="点击恢复 100%" @click="setZoom(1)">{{ Math.round(zoom * 100) }}%</button>
      <button class="dk" title="放大" @click="zoomBy(0.1)">＋</button>
      <span class="dk-sep" />
      <button class="dk wide" title="缩放到刚好放下全部卡片" @click="fit('contain')">适应</button>
      <span class="dk-sep" />
      <button class="dk wide" :class="{ on: snap }" title="拖动时吸附网格与相邻卡片" @click="snap = !snap">
        吸附
      </button>
      <button class="dk wide" title="智能重排：大卡独行、小卡并行列" @click="tidy">智能整理</button>
      <button class="dk wide" title="紧凑排列：尽量把卡片插进上一行空隙" @click="compact">紧凑</button>
    </div>

    <div v-else-if="showMiniDock" class="cv-dock" @pointerdown.stop>
      <button class="dk" title="缩小" @click="zoomBy(-0.1)">−</button>
      <button class="dk val" title="点击恢复 100%" @click="setZoom(1)">{{ Math.round(zoom * 100) }}%</button>
      <button class="dk" title="放大" @click="zoomBy(0.1)">＋</button>
      <button class="dk wide" title="缩放到刚好放下全部卡片" @click="fit('contain')">适应</button>
    </div>

    <div v-if="edit" class="cv-tip">
      拖动卡片自由摆放 · 拖四边/四角缩放 · 点选后可方向键微调（Shift 加速）、Delete 删除 · 双击空白新建 · 空白处拖动平移
    </div>
  </div>
</template>

<script setup>
/**
 * 驾驶舱无限画布
 *
 * 布局模型就是一组绝对坐标（x/y/w/h，单位 px），画布本身不设边界：
 * 卡片可以拖到任何位置、叠放、随便缩放，右下方向会随内容自动扩展。
 *
 * 三个实现要点：
 *  1. 卡片用 transform 定位。拖动时每帧只改一个 transform（外加宽高），
 *     不触发重排，几十张卡也是满帧。
 *  2. 拖动过程写进 `live` 这个响应式对象而不是直接改 props —— 布局的
 *     真相在父组件手里，松手才通过 emit 提一次交；同时任何一次重渲染
 *     都会用 `live` 覆盖样式，不会把已经拖到一半的卡片弹回原位。
 *  3. 卡片内容的可用高度由 canvas.js 算成像素传下去。ECharts / el-table
 *     都需要确定高度，纯 CSS 撑满在 flex 里各浏览器差异太大。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import CockpitWidget from './CockpitWidget.vue'
import {
  BASE_WIDTH, GRID, HANDLES, MARGIN, MAX_H, MAX_W, bodyPx, clampBox, compactLayout, contentSize,
  minSize, snapBox, tidyLayout,
} from '../utils/canvas'

const props = defineProps({
  /** 卡片数组，每项含 id/type/title/x/y/w/h 与取数配置 */
  layout: { type: Array, default: () => [] },
  /** id → 后端算好的成品数据 */
  computed: { type: Object, default: () => ({}) },
  edit: { type: Boolean, default: false },
  /** desktop | screen：screen 是大屏皮肤 */
  skin: { type: String, default: 'desktop' },
  screenTheme: { type: String, default: 'nebula' },
  /** none | width | contain —— 打开时如何自适应 */
  fitMode: { type: String, default: 'none' },
  /** 大屏不允许滚动，整屏等比塞下 */
  scrollable: { type: Boolean, default: true },
})
const emit = defineEmits(['move', 'replace', 'edit-widget', 'remove', 'front', 'open-row', 'add-at', 'select'])

const rootEl = ref(null)
const scrollEl = ref(null)
const contentEl = ref(null)

const zoom = ref(1)
const snap = ref(true)
const selected = ref(-1)
const drag = ref(null)                 // { index, mode, handle, start:{cx,cy}, orig:{...} }
const live = ref(null)                 // 拖动中的实时几何（不落库）
const guideV = ref([])
const guideH = ref([])
const viewport = ref({ w: 1440, h: 900 })
let userZoomed = false                 // 用户手动缩放过就不再自动适应，免得抢操作
let ro = null

// ---------- 几何 ----------

/** 卡片当前几何：拖动中的那张用 live，其余用布局里的值 */
function cur(w, i) {
  return (live.value && live.value.index === i) ? live.value : w
}

const content = computed(() => {
  const items = props.layout.map((w, i) => (live.value && live.value.index === i ? { ...w, ...live.value } : w))
  // 大屏投放态：布局由 CockpitFullscreen 按视口宽度排好，评估候选时用的就是
  // margin=0，这里也必须归零 —— 否则内容比视口宽出 MARGIN，fit('fill'）被迫
  // 缩小一档，横向就铺不满了（#128）。留白只服务桌面编辑态的"继续放卡片"。
  return contentSize(items, { margin: props.skin === 'screen' ? 0 : MARGIN })
})

const spaceStyle = computed(() => ({
  width: `${Math.round(content.value.w * zoom.value)}px`,
  height: `${Math.round(content.value.h * zoom.value)}px`,
}))

const contentStyle = computed(() => ({
  width: `${content.value.w}px`,
  height: `${content.value.h}px`,
  transform: `scale(${zoom.value})`,
  transformOrigin: '0 0',
}))

const gridStyle = computed(() => ({
  width: `${content.value.w}px`,
  height: `${content.value.h}px`,
  backgroundSize: `${GRID * 4}px ${GRID * 4}px, ${GRID * 4}px ${GRID * 4}px, ${GRID}px ${GRID}px, ${GRID}px ${GRID}px`,
}))

function cardStyle(w, i) {
  const g = cur(w, i)
  return {
    transform: `translate3d(${Math.round(g.x)}px, ${Math.round(g.y)}px, 0)`,
    width: `${Math.round(g.w)}px`,
    height: `${Math.round(g.h)}px`,
    // 自由画布允许叠放：拖动中的置顶，选中的也抬起来 —— 否则被后一张卡
    // 压住时，连它自己的缩放手柄都点不到（手柄在卡片的下层）
    zIndex: drag.value && drag.value.index === i ? 9999 : (selected.value === i ? 9000 : i + 1),
  }
}

const guides = computed(() => [
  ...guideV.value.map(v => ({ k: 'v', style: { left: `${v}px` } })),
  ...guideH.value.map(v => ({ k: 'h', style: { top: `${v}px` } })),
])

function bodyHeight(w) {
  return `${bodyPx(w, props.edit)}px`
}

function tableHeight(w) {
  return Math.max(60, bodyPx(w, props.edit) - 26)
}

const showMiniDock = computed(() => {
  if (props.edit) return false
  if (props.skin === 'screen') return false      // 大屏是投出去给别人看的，不放控件
  return zoom.value !== 1 || content.value.w * zoom.value > viewport.value.w + 8
})

// ---------- 取数结果（带缓存，避免拖动时反复重算图表） ----------
const cache = new Map()
function computedFor(w) {
  const src = props.computed ? props.computed[w.id] : null
  const hit = cache.get(w.id)
  if (hit && hit.src === src && hit.w === w) return hit.out
  const out = src || { ...w, data: null, error: '' }
  cache.set(w.id, { src, w, out })
  return out
}

// ---------- 缩放 / 适应 / 平移 ----------

function setZoom(next, anchor) {
  const v = Math.min(2, Math.max(0.3, Math.round(next * 100) / 100))
  const el = scrollEl.value
  if (!el || !anchor) {
    zoom.value = v
    return
  }
  const rect = el.getBoundingClientRect()
  const ox = anchor.x - rect.left
  const oy = anchor.y - rect.top
  const cx = (el.scrollLeft + ox) / zoom.value
  const cy = (el.scrollTop + oy) / zoom.value
  zoom.value = v
  nextTick(() => {
    el.scrollLeft = cx * v - ox
    el.scrollTop = cy * v - oy
  })
}

function zoomBy(d) {
  userZoomed = true
  setZoom(zoom.value + d)
}

function fit(mode = props.fitMode) {
  const el = scrollEl.value
  if (!el || mode === 'none') return
  // fill（大屏）不留 8px 缓冲：画布锁定不可滚、目标就是横向铺满，
  // 留缝会让 zoom 落到 0.99、显示宽差几像素（#128）。其余模式保留缓冲。
  const availW = el.clientWidth - (mode === 'fill' ? 0 : 8)
  const availH = el.clientHeight - 8
  const sx = availW / content.value.w
  const sy = availH / content.value.h
  let next
  if (mode === 'width') {
    // 桌面浏览：尽量按原尺寸，只缩小不放大
    next = Math.min(1, sx)
  } else if (mode === 'fill') {
    // 大屏模式：contain 语义 —— 宽高都不能裁剪（底部截断比留边更糟，
    // 用户明确投诉过）。#128 的根因本就是 margin=0（内容虚胖 200px）
    // 而非 sy 约束：布局已按视口宽度排好、高度多半放得下时 sx 就是
    // 瓶颈、横向照样铺满；只有内容确实太高时才等比缩小保完整。
    next = Math.min(sx, sy, 1.8)
  } else {
    // contain：完全放进可视区，最多 1.6 倍
    next = Math.min(Math.min(sx, sy), 1.6)
  }
  // 千分位取整：fill 的铺满断言容不得百分位取整 —— 0.844 取成 0.84 就会
  // 在 1200px 的屏上留 6px 缝。dock 显示的是 round(zoom*100)%，不受影响。
  // fill（大屏投放）的底线是「绝不裁剪」：内容极端超比例时（如 4K 设计稿
  // 投到 720p）也要能继续缩小，通用下限 0.3 会破坏 contain 保证。
  const floor = mode === 'fill' ? 0.1 : 0.3
  zoom.value = Math.min(2, Math.max(floor, Math.round(next * 1000) / 1000))
  nextTick(() => { el.scrollLeft = 0; el.scrollTop = 0 })
}

function measure() {
  const el = scrollEl.value
  if (el) viewport.value = { w: el.clientWidth, h: el.clientHeight }
  if (!userZoomed && props.fitMode !== 'none') fit()
}

function onWheel(e) {
  if (!(e.ctrlKey || e.metaKey)) return          // 普通滚轮＝滚动，不拦
  e.preventDefault()
  userZoomed = true
  setZoom(zoom.value + (e.deltaY < 0 ? 0.08 : -0.08), { x: e.clientX, y: e.clientY })
}

function tidy() {
  const next = tidyLayout(props.layout, { width: Math.max(BASE_WIDTH, viewport.value.w), fill: true, smart: true })
  emit('replace', next)
  ElMessage.success('已智能重排')
}

function compact() {
  const next = compactLayout(props.layout, { width: Math.max(BASE_WIDTH, viewport.value.w) })
  emit('replace', next)
  ElMessage.success('已紧凑排列')
}

// ---------- 拖动：移动 / 缩放 / 平移画布 ----------

function othersOf(index) {
  return props.layout.filter((_, j) => j !== index)
}

function onCardDown(e, i) {
  if (!props.edit || e.button !== 0) return
  if (e.target.closest('.cb-btn')) return
  select(i)
  beginDrag(e, i, 'move', '')
}

function onResizeDown(e, i, handle) {
  if (!props.edit || e.button !== 0) return
  select(i)
  beginDrag(e, i, 'resize', handle)
}

function select(i) {
  if (selected.value !== i) {
    selected.value = i
    emit('select', i)
  }
}

function beginDrag(e, i, mode, handle) {
  const w = props.layout[i]
  const rect = contentEl.value.getBoundingClientRect()
  drag.value = {
    index: i, mode, handle,
    start: { cx: (e.clientX - rect.left) / zoom.value, cy: (e.clientY - rect.top) / zoom.value },
    orig: { x: Number(w.x) || 0, y: Number(w.y) || 0, w: Number(w.w) || 200, h: Number(w.h) || 140 },
  }
  live.value = { index: i, ...drag.value.orig }
  e.preventDefault()
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerUp)
}

function pointerContent(e) {
  const rect = contentEl.value.getBoundingClientRect()
  return { cx: (e.clientX - rect.left) / zoom.value, cy: (e.clientY - rect.top) / zoom.value }
}

function onPointerMove(e) {
  if (!drag.value) return
  const { index, mode, handle, start, orig } = drag.value
  const p = pointerContent(e)
  const dx = p.cx - start.cx
  const dy = p.cy - start.cy

  if (mode === 'move') {
    const box = { x: orig.x + dx, y: orig.y + dy, w: orig.w, h: orig.h }
    if (snap.value) {
      const s = snapBox(box, othersOf(index), { threshold: 6 / zoom.value })
      live.value = { index, x: s.x, y: s.y, w: orig.w, h: orig.h }
      guideV.value = s.vLines
      guideH.value = s.hLines
    } else {
      live.value = { index, x: Math.round(box.x), y: Math.round(box.y), w: orig.w, h: orig.h }
      guideV.value = []
      guideH.value = []
    }
  } else {
    const type = props.layout[index]?.type
    const min = minSize(type)
    const east = handle.includes('e')
    const west = handle.includes('w')
    const south = handle.includes('s')
    const north = handle.includes('n')

    let w2 = orig.w + (east ? dx : 0) - (west ? dx : 0)
    let h2 = orig.h + (south ? dy : 0) - (north ? dy : 0)
    let x = orig.x + (west ? dx : 0)
    let y = orig.y + (north ? dy : 0)

    if (w2 < min.w) { if (west) x -= min.w - w2; w2 = min.w }
    if (h2 < min.h) { if (north) y -= min.h - h2; h2 = min.h }
    w2 = Math.min(MAX_W, w2)
    h2 = Math.min(MAX_H, h2)
    if (snap.value) {
      w2 = Math.round(w2 / GRID) * GRID
      h2 = Math.round(h2 / GRID) * GRID
      if (west) x = Math.round(x / GRID) * GRID
      if (north) y = Math.round(y / GRID) * GRID
    }
    live.value = { index, x, y, w: w2, h: h2 }
  }

  autoScroll(e)
}

/** 拖到视口边缘自动滚动画布，不然大布局里拖不远 */
function autoScroll(e) {
  const el = scrollEl.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const pad = 56
  const step = 14
  if (e.clientX > r.right - pad) el.scrollLeft += step
  else if (e.clientX < r.left + pad) el.scrollLeft -= step
  if (e.clientY > r.bottom - pad) el.scrollTop += step
  else if (e.clientY < r.top + pad) el.scrollTop -= step
}

function onPointerUp() {
  if (drag.value && live.value) {
    const i = drag.value.index
    const box = clampBox(live.value, props.layout[i]?.type)
    const w = props.layout[i]
    if (box.x !== w.x || box.y !== w.y || box.w !== w.w || box.h !== w.h) {
      emit('move', i, box)
    }
  }
  endDrag()
}

function endDrag() {
  drag.value = null
  live.value = null
  guideV.value = []
  guideH.value = []
  detach()
}

function detach() {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
}

// 空白处拖动 = 平移画布；点一下空白 = 取消选中
let pan = null
function onRootPointerDown(e) {
  if (e.target.closest('.cv-card') || e.target.closest('.cv-dock')) return
  if (!props.edit) return
  if (e.button !== 0) return
  selected.value = -1
  const el = scrollEl.value
  pan = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop }
  rootEl.value?.classList.add('panning')
  window.addEventListener('pointermove', onPanMove)
  window.addEventListener('pointerup', onPanUp)
}

function onPanMove(e) {
  if (!pan) return
  const el = scrollEl.value
  el.scrollLeft = pan.left - (e.clientX - pan.x)
  el.scrollTop = pan.top - (e.clientY - pan.y)
}

function onPanUp() {
  pan = null
  rootEl.value?.classList.remove('panning')
  window.removeEventListener('pointermove', onPanMove)
  window.removeEventListener('pointerup', onPanUp)
}

/** 双击空白：就地在鼠标处新建卡片 */
function onDblClick(e) {
  if (!props.edit) return
  if (e.target.closest('.cv-card') || e.target.closest('.cv-dock')) return
  const rect = contentEl.value.getBoundingClientRect()
  emit('add-at', {
    x: Math.max(0, Math.round((e.clientX - rect.left) / zoom.value)),
    y: Math.max(0, Math.round((e.clientY - rect.top) / zoom.value)),
  })
}

// ---------- 键盘 ----------

/** 焦点在输入框里时不能抢键（配置抽屉是独立浮层，也在 window 上冒泡） */
function isTyping(el) {
  if (!el) return false
  const tag = String(el.tagName || '').toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable === true
}

/** 挂在 window 上：点过卡片之后焦点常落在 body，挂在画布根节点收不到按键 */
function onKeydown(e) {
  if (!props.edit || selected.value < 0) return
  if (isTyping(e.target)) return
  const i = selected.value
  const w = props.layout[i]
  if (!w) return
  const step = e.shiftKey ? GRID : 1

  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault()
    emit('remove', i)
    selected.value = -1
    return
  }
  const map = {
    ArrowLeft: [-step, 0], ArrowRight: [step, 0],
    ArrowUp: [0, -step], ArrowDown: [0, step],
  }
  const d = map[e.key]
  if (!d) return
  e.preventDefault()
  emit('move', i, {
    x: Math.max(0, (Number(w.x) || 0) + d[0]),
    y: Math.max(0, (Number(w.y) || 0) + d[1]),
    w: w.w, h: w.h,
  })
}

// ---------- 生命周期 ----------

watch(() => props.fitMode, () => { userZoomed = false; measure() })
watch(() => props.edit, v => { if (!v) selected.value = -1 })
watch(() => props.layout.length, () => { if (!userZoomed) measure() })

onMounted(() => {
  measure()
  window.addEventListener('keydown', onKeydown)
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => measure())
    if (scrollEl.value) ro.observe(scrollEl.value)
  }
})
onBeforeUnmount(() => {
  detach(); onPanUp(); ro?.disconnect()
  window.removeEventListener('keydown', onKeydown)
})

defineExpose({ fit, setZoom, zoom })
</script>

<style scoped>
.cv {
  position: relative;
  height: 100%;
  min-height: 0;
  outline: none;
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  overflow: hidden;
}
.cv.is-edit { cursor: grab; user-select: none; }
.cv.panning { cursor: grabbing; }
.cv.cv-locked { cursor: default; }

.cv-scroll {
  position: absolute; inset: 0;
  overflow: auto;
  overscroll-behavior: contain;
}
.cv.cv-locked .cv-scroll { overflow: hidden; }
/* 大屏：内容居中投放 */
.cv-screen .cv-scroll {
  display: flex; align-items: center; justify-content: center;
}

.cv-space { position: relative; }
.cv-content { position: relative; }

/* 编辑态的网格底：粗线每 32px（对齐吸附步长的高亮），细线每 8px */
.cv-grid {
  position: absolute; top: 0; left: 0;
  pointer-events: none;
  background-image:
    linear-gradient(var(--grid-line-strong) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line-strong) 1px, transparent 1px),
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
}

/* 对齐辅助线 */
.cv-guide { position: absolute; pointer-events: none; background: var(--primary); opacity: .85; z-index: 9000; }
.cv-guide.v { top: 0; width: 1px; height: 100%; }
.cv-guide.h { left: 0; height: 1px; width: 100%; }

/* ---------- 卡片 ---------- */
.cv-card {
  position: absolute; top: 0; left: 0;
  display: flex; flex-direction: column;
  padding: 16px;
  box-sizing: border-box;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
  will-change: transform;
  transition: border-color var(--duration) var(--ease-out),
              box-shadow var(--duration) var(--ease-out);
}
.cv-card-body, .cv-body { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column; }
.cv-body { overflow: hidden; }

/* 编辑态：卡片内容不接受指针事件，整张卡都是拖拽面，
   顺带避免拖动时误触表格行跳转 */
.cv.is-edit .cv-body { pointer-events: none; user-select: none; }
.cv.is-edit .cv-card { cursor: grab; }
.cv-card.moving { z-index: 9999; cursor: grabbing; box-shadow: 0 12px 32px rgba(0, 0, 0, .18); }
.cv.is-edit .cv-card:hover { border-color: var(--border-strong); }
.cv.is-edit .cv-card.sel { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-ring); }

.cv-bar {
  display: flex; align-items: center; gap: 6px;
  height: 24px; margin: -4px 0 10px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--border);
  font-size: var(--text-xs);
}
.cb-grip { color: var(--text-disabled); display: inline-flex; cursor: grab; }
.cb-title {
  font-weight: 600; color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 42%;
}
.cv-bar .spacer { flex: 1; min-width: 4px; }
.cb-size {
  color: var(--text-tertiary); font-variant-numeric: tabular-nums;
  font-family: var(--font-mono); font-size: 11px;
}
.cb-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; padding: 0;
  border: none; border-radius: var(--radius-xs);
  background: transparent; color: var(--text-tertiary); cursor: pointer;
  transition: all var(--duration) var(--ease-out);
}
.cb-btn:hover { background: var(--bg-sunken); color: var(--primary); }
.cb-btn.danger:hover { background: var(--danger-bg); color: var(--danger); }

/* 八向手柄：默认只露边角，选中后全亮 */
.cv-h {
  position: absolute; width: 12px; height: 12px;
  opacity: 0; transition: opacity .15s;
  z-index: 5;
}
.cv-card:hover .cv-h, .cv-card.sel .cv-h { opacity: 1; }
.cv-h::after {
  content: ''; position: absolute; inset: 3px;
  background: var(--bg-card); border: 1.5px solid var(--primary); border-radius: 2px;
}
.cv-card.sel .cv-h::after { background: var(--primary); }
.h-n  { top: -6px;  left: 50%; margin-left: -6px; cursor: ns-resize; }
.h-s  { bottom: -6px; left: 50%; margin-left: -6px; cursor: ns-resize; }
.h-w  { left: -6px;  top: 50%; margin-top: -6px; cursor: ew-resize; }
.h-e  { right: -6px; top: 50%; margin-top: -6px; cursor: ew-resize; }
.h-nw { top: -6px; left: -6px; cursor: nwse-resize; }
.h-ne { top: -6px; right: -6px; cursor: nesw-resize; }
.h-sw { bottom: -6px; left: -6px; cursor: nesw-resize; }
.h-se { bottom: -6px; right: -6px; cursor: nwse-resize; }
/* 四条边只留中点一小段，避免贴边误触 */
.h-n::after, .h-s::after { left: 50%; margin-left: -4px; width: 20px; right: auto; inset-block: 3px; }
.h-w::after, .h-e::after { top: 50%; margin-top: -4px; height: 20px; bottom: auto; inset-inline: 3px; }

/* ---------- 工具条 ---------- */
.cv-dock {
  position: absolute; right: 14px; bottom: 14px; z-index: 9500;
  display: flex; align-items: center; gap: 4px;
  padding: 5px 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
}
.dk {
  min-width: 30px; height: 28px; padding: 0 8px;
  border: 1px solid transparent; border-radius: var(--radius-sm);
  background: transparent; color: var(--text-secondary);
  font-family: inherit; font-size: var(--text-sm); cursor: pointer;
  transition: all var(--duration) var(--ease-out);
}
.dk:hover { background: var(--bg-sunken); color: var(--primary); }
.dk.val { font-variant-numeric: tabular-nums; min-width: 52px; }
.dk.wide { font-size: var(--text-xs); }
.dk.on { color: var(--primary); background: var(--primary-bg); border-color: var(--primary-200); }
.dk-sep { width: 1px; height: 18px; background: var(--border); margin: 0 3px; }

.cv-tip {
  position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%);
  max-width: 62%;
  padding: 6px 12px; border-radius: 999px;
  background: var(--bg-card); border: 1px solid var(--border);
  font-size: var(--text-xs); color: var(--text-tertiary);
  pointer-events: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* ---------- 大屏皮肤 ---------- */
.cv-screen {
  border: none; border-radius: 0; background: transparent;
}
.cv-screen .cv-card {
  background: var(--bg-card);
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 14px;
  padding: 16px;                    /* 桌面/大屏统一 16，与 bodyPx 的 32px 内边距一致 */
  backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 8px 28px rgba(0, 0, 0, 0.35);
}
.cv-screen .cv-card::before {
  content: ''; position: absolute; top: 0; left: 18px; right: 18px; height: 1px;
  background: linear-gradient(90deg, transparent, var(--primary-bg-strong), transparent);
}
.cv-screen .cv-card :deep(.el-table) {
  background: transparent;
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-header-text-color: var(--text-tertiary);
  --el-table-text-color: var(--text-secondary);
  --el-table-border-color: rgba(148, 163, 184, 0.14);
  --el-table-row-hover-bg-color: rgba(148, 163, 184, 0.08);
  font-size: 14px;
}
.cv-screen .cv-card :deep(.el-table__empty-block) { background: transparent; }
</style>
