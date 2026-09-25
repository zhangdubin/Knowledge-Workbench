/**
 * 自由画布几何工具的单元验证
 *
 * 直接 import 前端的 utils/canvas.js —— 它是纯函数模块，不依赖 Vue，
 * 所以能在 node 里跑，不用起浏览器。
 *
 * 跑法：node scripts/verify-canvas-unit.mjs
 */
import {
  DEFAULT_SIZE, MIN_SIZE, clampBox, compactLayout, contentSize, findFreeSlot,
  normalizeLayout, shelfPack, snapBox, stretchLayout, tidyLayout, bodyPx,
} from '../frontend/src/utils/canvas.js'

let pass = 0
let fail = 0
function ok(cond, msg) {
  if (cond) { pass++; console.log('  ✓ ' + msg) }
  else { fail++; console.log('  ✗ ' + msg) }
}

console.log('\n== 1. 老 span 布局归一化 ==')
{
  const legacy = [
    { id: 'w1', type: 'stat', span: 1 },
    { id: 'w2', type: 'stat', span: 1 },
    { id: 'w3', type: 'stat', span: 1 },
    { id: 'w4', type: 'stat', span: 1 },
    { id: 'w5', type: 'chart', span: 2 },
    { id: 'w6', type: 'list', span: 2 },
  ]
  const out = normalizeLayout(legacy)
  ok(out.length === 6, '卡片数量不变')
  ok(out.every(w => Number.isFinite(w.x) && Number.isFinite(w.y) && w.w > 0 && w.h > 0),
    '每张卡都拿到了 x/y/w/h')
  ok(out.every(w => w.span === undefined), '老字段 span 被清掉，不再双轨')
  ok(out.slice(0, 4).every(w => w.y === 0), '4 张宽 1 的卡排在第一行')
  ok(new Set(out.slice(0, 4).map(w => w.x)).size === 4, '第一行 4 张左右不重叠')
  ok(out[4].y > 0 && out[5].y > 0, '放不下的卡片换到第二行')
  ok(out[4].w > out[0].w, 'span=2 的卡片比 span=1 宽')
  // 两行之间不能压在一起
  const row1Bottom = Math.max(...out.slice(0, 4).map(w => w.y + w.h))
  ok(out[4].y >= row1Bottom, '第二行在第一行下方，无重叠')
}

console.log('\n== 2. 已有坐标的布局不被重排 ==')
{
  const free = [
    { id: 'a', type: 'stat', x: 500, y: 300, w: 300, h: 130 },
    { id: 'b', type: 'chart', x: 40, y: 12, w: 620, h: 380 },
  ]
  const out = normalizeLayout(free)
  ok(out[0].x === 500 && out[0].y === 300, '位置原样保留（不"帮我"重排）')
  ok(out[1].x === 40 && out[1].y === 12, '第二张也一样')
}

console.log('\n== 3. 尺寸钳制 ==')
{
  const tiny = clampBox({ x: -5, y: -9, w: 10, h: 10 }, 'chart')
  ok(tiny.w === MIN_SIZE.chart.w && tiny.h === MIN_SIZE.chart.h, '小于最小尺寸被抬起')
  const huge = clampBox({ x: 0, y: 0, w: 99999, h: 99999 }, 'stat')
  ok(huge.w === 4000 && huge.h === 2400, '超过上限被压回')
  ok(tiny.x === -5 && tiny.y === -9, '负坐标交给调用方处理，不在这里偷偷改')
}

console.log('\n== 4. 货架排布 ==')
{
  const items = [
    { w: 400, h: 100 }, { w: 400, h: 100 }, { w: 400, h: 100 },
    { w: 900, h: 300 },
  ]
  const out = shelfPack(items, 1000, 20)
  ok(out[0].y === 0 && out[1].y === 0, '前两张同一行')
  ok(out[2].y === 120, '第三张换行且 y = 行高 + 间距')
  ok(out[3].y === 240, '900 宽放不进第二行，换到第三行')
  ok(out.every(o => o.x + o.w <= 1000), '没有任何卡片超出目标宽度')
}

console.log('\n== 5. 画布内容尺寸 ==')
{
  const size = contentSize([{ x: 0, y: 0, w: 300, h: 200 }])
  ok(size.w === 1180 && size.h === 620, '空/小布局给保底尺寸')
  const big = contentSize([{ x: 1500, y: 900, w: 400, h: 300 }])
  ok(big.w === 2100 && big.h === 1400, '大布局按最大边界 + 留白扩展（1500+400+200）')
}

console.log('\n== 6. 新卡片落点 ==')
{
  const layout = [
    { x: 0, y: 0, w: 400, h: 200 },
    { x: 400, y: 0, w: 400, h: 200 },
  ]
  const slot = findFreeSlot(layout, { w: 300, h: 150 })
  // 右侧要越过最后一张卡的右边缘 + 间距（16-1 的容差），再对齐到 8px 网格
  ok(slot.y === 0 && slot.x >= 800, `优先填到同一行的右侧空地（x=${slot.x}）`)
  ok(slot.x >= 815 || layout.every(c => c.x + c.w + 15 <= slot.x), '落点与已有卡片留足间距')
  const slot2 = findFreeSlot([{ x: 0, y: 0, w: 1400, h: 300 }], { w: 400, h: 160 })
  ok(slot2.y >= 300, '一行占满后落到下方')
}

console.log('\n== 7. 吸附与对齐辅助线 ==')
{
  const others = [{ x: 400, y: 0, w: 300, h: 200 }]
  // 左边缘差 4px 对齐 → 应被吸到 400，并给出一条竖线
  const near = snapBox({ x: 396, y: 300, w: 300, h: 120 }, others, { threshold: 6 })
  ok(near.x === 400, '左边缘吸附到相邻卡片左边缘')
  ok(near.vLines.length === 1 && near.vLines[0] === 400, '返回竖辅助线位置')
  // 无相邻卡片时回落到网格
  const grid = snapBox({ x: 101, y: 55, w: 300, h: 120 }, [], { threshold: 6, gridSize: 8 })
  ok(grid.x === 104 && grid.y === 56, '没有可对齐目标时吸到 8px 网格')
  // 关掉吸附
  const off = snapBox({ x: 101, y: 55, w: 300, h: 120 }, [], { grid: false })
  ok(off.x === 101 && off.y === 55, '吸附关闭时位置不变')
  // 中线对齐：宽 200 的卡中心 552 ≈ 相邻卡中心 550，两条边都不重合，
  // 只有「中线对齐」这一条能救它
  const mid = snapBox({ x: 452, y: 500, w: 200, h: 120 }, others, { threshold: 6 })
  ok(mid.x === 450 && mid.vLines[0] === 550, '中线对齐（552 → 450，中心 550）')
  // 右边缘贴相邻卡左边缘
  const right = snapBox({ x: 96, y: 500, w: 300, h: 120 }, others, { threshold: 8 })
  ok(right.x === 100, '右边缘对齐到相邻卡左边缘（396 → 400）')
}

console.log('\n== 8. 自动整理 + 宽度填充 ==')
{
  const items = [
    { id: 'a', type: 'stat' }, { id: 'b', type: 'stat' },
    { id: 'c', type: 'stat' }, { id: 'd', type: 'stat' },
    { id: 'e', type: 'chart' }, { id: 'f', type: 'list' },
  ]
  const out = normalizeLayout(items, { width: 1800, fill: true })
  ok(out.length === 6, '6 张卡')
  ok(out[0].w > 348, 'fill=true 时单卡宽度被拉伸')
  const row1w = out[0].w + out[1].w + out[2].w + out[3].w + 3 * 16
  ok(row1w === 1800, `第一行恰好铺满 1800（实际 ${row1w}）`)
  const row2w = out[4].w + out[5].w + 16
  ok(row2w === 1800, `第二行也铺满 1800（实际 ${row2w}）`)

  const placed = [
    { id: 'r1', type: 'stat', x: 0, y: 0, w: 348, h: 132 },
    { id: 'r2', type: 'stat', x: 364, y: 0, w: 348, h: 132 },
    { id: 'r3', type: 'stat', x: 728, y: 0, w: 348, h: 132 },
    { id: 'r4', type: 'stat', x: 1092, y: 0, w: 348, h: 132 },
  ]
  const stretched = stretchLayout(placed, 1800)
  const total = stretched.reduce((s, it, i, arr) => s + it.w + (i < arr.length - 1 ? 16 : 0), 0)
  ok(stretched[0].x === 0 && total === 1800, '旧坐标布局自适应拉伸后铺满容器')
  ok(stretched.every(it => it.w >= placed[0].w), '拉伸不会小于原尺寸')

  // 智能整理：大卡优先独行，小卡尽量并排行
  const mixed = [
    { id: 's1', type: 'stat', x: 0, y: 0, w: 348, h: 132 },
    { id: 's2', type: 'stat', x: 400, y: 0, w: 348, h: 132 },
    { id: 'c1', type: 'chart', x: 0, y: 200, w: 700, h: 320 },
    { id: 's3', type: 'stat', x: 0, y: 600, w: 348, h: 132 },
    { id: 's4', type: 'stat', x: 400, y: 600, w: 348, h: 132 },
  ]
  const smart = tidyLayout(mixed, { width: 1800, fill: true, smart: true })
  ok(smart.find(w => w.id === 'c1').y === 0, '智能整理把最大的 chart 放到第一行')
  ok(smart.filter(w => w.y === 0).length === 1, '第一行只有 chart 一张大卡片')
  ok(smart.filter(w => w.type === 'stat' && w.y > 0).length === 4, '四张小卡排在下面行')

  // 紧凑排列：小卡能插进上一行右侧空位
  const loose = [
    { id: 'a', type: 'stat', x: 0, y: 0, w: 400, h: 200 },
    { id: 'b', type: 'stat', x: 0, y: 216, w: 400, h: 200 },
    { id: 'c', type: 'stat', x: 0, y: 432, w: 400, h: 200 },
  ]
  const compact = compactLayout(loose, { width: 1400 })
  ok(compact[1].y === 0 && compact[1].x === 416, '第二张被插到第一行右侧')
  ok(compact[2].y === 0 && compact[2].x === 832, '第三张继续插到第一行')
}

console.log('\n== 9. 卡片内容高度 ==')
{
  const chart = { type: 'chart', h: 320 }
  ok(bodyPx(chart, false) === 320 - 32 - 26, '视图态：扣掉内边距与标题行')
  ok(bodyPx(chart, true) < bodyPx(chart, false), '编辑态还要扣掉卡片工具条')
  ok(bodyPx({ type: 'stat', h: 132 }, false) === 132 - 32, '指标卡没有标题行')
  ok(bodyPx({ type: 'chart', h: 10 }, false) === 72, '极矮的卡片也留 72px 保底')
}

console.log('\n== 11. 默认尺寸表完整 ==')
{
  for (const t of ['stat', 'chart', 'gauge', 'rank', 'progress', 'status', 'kpi', 'table', 'list', 'text']) {
    ok(DEFAULT_SIZE[t] && MIN_SIZE[t] && MIN_SIZE[t].w < DEFAULT_SIZE[t].w,
      `${t}: 默认尺寸 ${DEFAULT_SIZE[t].w}×${DEFAULT_SIZE[t].h}，最小 ${MIN_SIZE[t].w}×${MIN_SIZE[t].h}`)
  }
}

console.log(`\n结果：${pass} 通过 / ${fail} 失败`)
process.exit(fail ? 1 : 0)
