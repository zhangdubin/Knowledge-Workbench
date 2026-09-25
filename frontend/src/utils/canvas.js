/**
 * 自由画布（无限画布）几何工具
 *
 * 驾驶舱的布局从「CSS Grid + 每卡选 1~4 列宽」升级成了「绝对定位 + 拖拽 /
 * 八向缩放」。这里放的全是纯函数：尺寸表、旧布局归一化、空位查找、吸附
 * 与对齐辅助线计算。组件只负责指针事件与 DOM，算法都在这里，便于单测。
 *
 * 坐标语义：单位是 CSS 像素，原点在画布左上角，画布向右下无限延伸。
 * 卡片用 `transform: translate3d(x, y, 0)` 定位（不是 left/top）——
 * 拖动时只改 transform，不触发重排，几十张卡也不掉帧。
 */

export const GRID = 8                    // 吸附网格步长
export const GAP = 16                    // 新卡片/自动整理时的间距
export const BASE_WIDTH = 1440           // 旧 span 布局的换算基准宽度
export const LEGACY_COLS = 4
export const MAX_W = 4000
export const MAX_H = 2400
export const MARGIN = 200                // 画布右下留白：总有地方可以继续放卡片
export const MIN_CANVAS_W = 1180
export const MIN_CANVAS_H = 620

/** 旧布局：1 列宽度 */
const LEGACY_COL_W = (BASE_WIDTH - (LEGACY_COLS - 1) * GAP) / LEGACY_COLS

/** 各类型卡片的默认尺寸：一眼能看全内容，又不会一屏只放得下三张 */
export const DEFAULT_SIZE = {
  stat: { w: 348, h: 132 },
  gauge: { w: 348, h: 248 },
  chart: { w: 700, h: 320 },
  rank: { w: 460, h: 300 },
  progress: { w: 460, h: 180 },
  status: { w: 460, h: 240 },
  kpi: { w: 348, h: 180 },
  table: { w: 940, h: 320 },
  list: { w: 460, h: 300 },
  text: { w: 460, h: 168 },
}

/** 最小尺寸：小于这个尺寸内容就没法看了，缩放到此为止 */
export const MIN_SIZE = {
  stat: { w: 180, h: 104 },
  gauge: { w: 220, h: 190 },
  chart: { w: 300, h: 220 },
  rank: { w: 260, h: 170 },
  progress: { w: 260, h: 120 },
  status: { w: 260, h: 160 },
  kpi: { w: 220, h: 120 },
  table: { w: 320, h: 170 },
  list: { w: 240, h: 160 },
  text: { w: 180, h: 104 },
}

/** 预设尺寸（配置抽屉里的「小/中/大/宽/高」按钮） */
export const SIZE_PRESETS = [
  { key: 'sm', label: '小', scale: 0.7 },
  { key: 'md', label: '中', scale: 1 },
  { key: 'lg', label: '大', scale: 1.45 },
  { key: 'wide', label: '宽扁', w: 1.8, h: 0.75 },
  { key: 'tall', label: '窄高', w: 0.7, h: 1.7 },
]

/** 旧版「高度」预设 → 额外高度 */
const HEIGHT_STEP = { '': 0, lg: 80, xl: 160 }

export function defaultSize(type) {
  return { ...(DEFAULT_SIZE[type] || DEFAULT_SIZE.stat) }
}

export function minSize(type) {
  return { ...(MIN_SIZE[type] || MIN_SIZE.stat) }
}

function num(v, fallback = 0) {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

/** 把宽高收进 [最小, 最大] 区间并取整 */
export function clampBox(box, type) {
  const min = minSize(type)
  return {
    x: Math.round(num(box.x)),
    y: Math.round(num(box.y)),
    w: Math.round(Math.min(MAX_W, Math.max(min.w, num(box.w, min.w)))),
    h: Math.round(Math.min(MAX_H, Math.max(min.h, num(box.h, min.h)))),
  }
}

/** 老布局（span / height 预设）换算成像素尺寸 */
function legacySize(w) {
  const d = defaultSize(w.type)
  const span = Math.min(Math.max(num(w.span, 1), 1), LEGACY_COLS)
  return {
    w: Math.round(span * LEGACY_COL_W + (span - 1) * GAP),
    h: Math.round(d.h + (HEIGHT_STEP[w.height || ''] || 0)),
  }
}

/** 货架式排布：从左到右铺，放不下就换行。保留传入顺序。
 *  若 fill=true，每一行会按比例拉伸卡片宽度，刚好铺满 targetWidth（最后一行也铺）。
 */
export function shelfPack(items, width = BASE_WIDTH, gap = GAP, { fill = false } = {}) {
  const out = []
  let x = 0
  let y = 0
  let rowH = 0
  let rowStart = 0
  for (const it of items) {
    if (x > 0 && x + it.w > width) {
      if (fill) fillRow(out, rowStart, width, gap)
      x = 0
      y += rowH + gap
      rowH = 0
      rowStart = out.length
    }
    out.push({ ...it, x, y })
    x += it.w + gap
    rowH = Math.max(rowH, it.h)
  }
  if (fill && rowStart < out.length) fillRow(out, rowStart, width, gap)
  return out
}

/** 把 layout 数组里 [start, end] 这一行按比例拉宽，铺满 width（保持 gap 不变） */
function fillRow(layout, start, width, gap) {
  const row = layout.slice(start)
  if (!row.length) return
  const n = row.length
  const totalW = row.reduce((s, it) => s + it.w, 0)
  const rowW = totalW + (n - 1) * gap
  if (rowW >= width - 1) return            // 已经满或超出，不处理
  const extra = width - rowW
  const scale = (totalW + extra) / totalW  // ≥ 1
  let x = 0
  for (let i = 0; i < n; i++) {
    const it = row[i]
    it.w = Math.round(it.w * scale)
    it.x = Math.round(x)
    x += it.w + gap
  }
}

/** 对已经存在的坐标布局做「宽度自适应拉伸」：把每一行从左到右铺的卡片
 * 按比例拉宽到 targetWidth。用于后端模板残留的旧 1440 宽度布局。
 * 只处理「看起来像自动货架」的行：第一个卡片 x≈0，且同一行 y 相差很小。
 */
export function stretchLayout(layout, width = BASE_WIDTH, gap = GAP) {
  const items = (layout || []).map(w => ({ ...w }))
  if (!items.length) return items
  // 按 y 分组（容忍 4px）
  const rows = []
  let cur = null
  for (const it of items.slice().sort((a, b) => num(a.y) - num(b.y))) {
    if (!cur || Math.abs(num(it.y) - num(cur.y)) > 4) {
      cur = { y: num(it.y), items: [] }
      rows.push(cur)
    }
    cur.items.push(it)
  }
  for (const row of rows) {
    row.items.sort((a, b) => num(a.x) - num(b.x))
    const first = row.items[0]
    if (num(first.x) > 4) continue          // 不是从左边缘开始的行，不动
    const n = row.items.length
    const totalW = row.items.reduce((s, it) => s + num(it.w), 0)
    const rowW = totalW + (n - 1) * gap
    if (rowW >= width - 1) continue
    const extra = width - rowW
    const scale = (totalW + extra) / totalW
    let x = 0
    for (let i = 0; i < n; i++) {
      const it = row.items[i]
      it.w = Math.round(num(it.w) * scale)
      it.x = Math.round(x)
      x += it.w + gap
    }
  }
  return items
}

/**
 * 归一化布局：任何来源（老 span 布局、后端模板、手工 JSON）都能变成
 * 带 x/y/w/h 的自由画布布局。已经坐标齐全的保持原样，不重排。
 */
export function normalizeLayout(layout, { width = BASE_WIDTH, fill = true } = {}) {
  const items = (layout || []).map(w => ({ ...w }))
  if (!items.length) return []

  const placed = items.every(w => Number.isFinite(Number(w.x)) && Number.isFinite(Number(w.y)))
  if (placed) {
    // 已经自由摆放：只做尺寸钳制，位置不动（避免用户精心排的版被"修正"）
    return items.map(w => ({ ...w, ...clampBox(w, w.type), span: undefined }))
  }

  const sized = items.map(w => {
    const fallback = legacySize(w)
    return {
      ...w,
      ...clampBox({
        x: 0, y: 0,
        w: Number.isFinite(Number(w.w)) ? w.w : fallback.w,
        h: Number.isFinite(Number(w.h)) ? w.h : fallback.h,
      }, w.type),
      span: undefined,
    }
  })
  return shelfPack(sized, width, GAP, { fill })
}

/** 画布内容尺寸：所有卡片的最大边界 + 留白 */
export function contentSize(layout, { margin = MARGIN } = {}) {
  let w = MIN_CANVAS_W
  let h = MIN_CANVAS_H
  for (const it of layout || []) {
    w = Math.max(w, num(it.x) + num(it.w) + margin)
    h = Math.max(h, num(it.y) + num(it.h) + margin)
  }
  return { w: Math.round(w), h: Math.round(h) }
}

function overlaps(a, b, gap = 0) {
  return !(a.x + a.w + gap <= b.x || b.x + b.w + gap <= a.x ||
           a.y + a.h + gap <= b.y || b.y + b.h + gap <= a.y)
}

/**
 * 给新卡片找位置：优先放到最上面一行的空隙里，找不到就放到所有卡片下方。
 * 用网格步长扫描，卡片量级（几十张）下开销可以忽略。
 */
export function findFreeSlot(layout, size, { width = BASE_WIDTH, gap = GAP } = {}) {
  const items = (layout || []).map(w => ({
    x: num(w.x), y: num(w.y), w: num(w.w), h: num(w.h),
  }))
  const box = { x: 0, y: 0, w: size.w, h: size.h }
  const maxY = items.reduce((m, it) => Math.max(m, it.y + it.h), 0)

  for (let y = 0; y <= maxY + gap; y += GRID) {
    for (let x = 0; x + size.w <= width; x += GRID) {
      const probe = { ...box, x, y }
      if (!items.some(it => overlaps(probe, it, gap - 1))) return { x, y }
    }
  }
  // 兜底：整行铺满了，放到最下面
  return { x: 0, y: maxY + gap }
}

/** 自动整理：按当前坐标的阅读顺序（先上后下、先左后右）重新排布 */
export function tidyLayout(layout, { width = BASE_WIDTH, gap = GAP, fill = true, smart = false } = {}) {
  let ordered
  if (smart) {
    // 智能模式：大卡（宽屏过半或很高）独占一行并按宽度铺满，
    // 小卡按原始阅读顺序排在下方，尽量并排行且每行铺满
    const items = (layout || []).map(w => ({ ...w }))
    const big = items.filter(w => num(w.w) >= width * 0.55 || num(w.h) >= 280)
    const small = items.filter(w => num(w.w) < width * 0.55 && num(w.h) < 280)
    big.sort((a, b) => (num(b.w) * num(b.h)) - (num(a.w) * num(a.h)))
    small.sort((a, b) => {
      const dy = num(a.y) - num(b.y)
      if (Math.abs(dy) > Math.max(num(a.h), num(b.h)) * 0.5) return dy
      return num(a.x) - num(b.x)
    })
    // 大卡每一张独占一行并横向填满
    let y = 0
    const bigRows = big.map(w => {
      const row = { ...w, x: 0, y }
      if (fill && num(row.w) < width) row.w = width
      y += num(row.h) + gap
      return row
    })
    const packed = shelfPack(small.map(w => ({ ...w })), width, gap, { fill })
    for (const w of packed) w.y += y
    return [...bigRows, ...packed]
  } else {
    // 普通整理：在保留大致阅读顺序（先上后下）的前提下，
    // 同行内把大卡往前放，让 shelfPack 尽可能排成更少行、更紧凑
    ordered = [...(layout || [])].sort((a, b) => {
      const dy = num(a.y) - num(b.y)
      if (Math.abs(dy) > Math.max(num(a.h), num(b.h)) * 0.5) return dy
      if (dy !== 0) return dy
      const ax = num(a.x), bx = num(b.x)
      // 同一行（y 接近）时，面积大的放前面，shelfPack 才能少留空隙
      if (Math.abs(ax - bx) <= 80) {
        return (num(b.w) * num(b.h)) - (num(a.w) * num(a.h))
      }
      return ax - bx
    })
  }
  return shelfPack(ordered.map(w => ({ ...w })), width, gap, { fill })
}

/** 紧凑整理：消除行间空隙，把高度相近的卡片插进上一行右侧空位（ masonry 式） */
export function compactLayout(layout, { width = BASE_WIDTH, gap = GAP } = {}) {
  // 注意 clampBox 只返回几何 {x,y,w,h}：必须先展开原卡片保留 id/type/source
  // 等全部字段，再用几何覆盖。曾因只保留几何导致大屏卡片全部丢失数据、
  // 「紧凑」按钮保存后抹掉整份配置（#128 关联缺陷）。
  const items = (layout || []).map(w => ({ ...w, ...clampBox(w, w.type) }))
  if (!items.length) return items
  // 按当前阅读顺序从上到下排列
  items.sort((a, b) => {
    const dy = num(a.y) - num(b.y)
    if (Math.abs(dy) > Math.max(num(a.h), num(b.h)) * 0.5) return dy
    return num(a.x) - num(b.x)
  })
  const rows = []
  for (const it of items) {
    let placed = false
    for (let ri = rows.length - 1; ri >= 0; ri--) {
      const row = rows[ri]
      const last = row[row.length - 1]
      const right = num(last.x) + num(last.w) + gap + num(it.w)
      if (right <= width && num(it.h) <= num(last.h) + 8) {
        it.x = num(last.x) + num(last.w) + gap
        it.y = num(last.y)
        row.push(it)
        placed = true
        break
      }
    }
    if (!placed) {
      const y = rows.reduce((m, r) => Math.max(m, num(r[0].y) + Math.max(...r.map(x => num(x.h)))), 0)
      it.x = 0
      it.y = rows.length ? y + gap : 0
      rows.push([it])
    }
  }
  return items
}

/**
 * 拖拽吸附：算出对齐后的位置与需要画的辅助线。
 * 竖向比左 / 中 / 右三条边，横向比上 / 中 / 下三条边，另外画布原点也算一条。
 */
export function snapBox(box, others, opts = {}) {
  const threshold = opts.threshold ?? 6
  const useGrid = opts.grid !== false
  const grid = opts.gridSize ?? GRID

  const vTargets = [0]
  const hTargets = [0]
  for (const o of others) {
    vTargets.push(num(o.x), num(o.x) + num(o.w) / 2, num(o.x) + num(o.w))
    hTargets.push(num(o.y), num(o.y) + num(o.h) / 2, num(o.y) + num(o.h))
  }

  const vEdges = [box.x, box.x + box.w / 2, box.x + box.w]
  const hEdges = [box.y, box.y + box.h / 2, box.y + box.h]

  let bestX = null
  let bestY = null
  let vLine = null
  let hLine = null

  for (const t of vTargets) {
    for (const e of vEdges) {
      const d = t - e
      if (Math.abs(d) <= threshold && (bestX === null || Math.abs(d) < Math.abs(bestX))) {
        bestX = d
        vLine = t
      }
    }
  }
  for (const t of hTargets) {
    for (const e of hEdges) {
      const d = t - e
      if (Math.abs(d) <= threshold && (bestY === null || Math.abs(d) < Math.abs(bestY))) {
        bestY = d
        hLine = t
      }
    }
  }

  let x = box.x
  let y = box.y
  if (bestX !== null) x += bestX
  else if (useGrid) x = Math.round(x / grid) * grid
  if (bestY !== null) y += bestY
  else if (useGrid) y = Math.round(y / grid) * grid

  return {
    x, y,
    vLines: bestX !== null ? [vLine] : [],
    hLines: bestY !== null ? [hLine] : [],
  }
}

/**
 * 卡片内容可用高度（像素）
 *
 * ECharts 和 el-table 都需要一个确定的像素高度才肯正常绘制，纯 CSS 撑满
 * 在 flex 里受实现差异影响，所以这里直接把可用高度算出来传给子组件。
 */
export function bodyPx(w, edit) {
  const type = w?.type
  const total = num(w?.h, 200)
  const pad = 32                       // 卡片内边距（上下各 16）
  const bar = edit ? 44 : 0            // 编辑态顶部的卡片工具条
  const head = (type === 'stat' || type === 'gauge') ? 0 : 26   // 标题行
  return Math.max(72, Math.round(total - pad - bar - head))
}

/** 内容区定位：编辑态要避开工具条 */
export const HANDLES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
