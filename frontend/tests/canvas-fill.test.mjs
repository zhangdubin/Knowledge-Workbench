// #128 断言验证：大屏横向铺满
// 数学链复刻 CockpitFullscreen.rebuildScreenLayout → CockpitCanvas.content/fit('fill')
import { contentSize, tidyLayout, stretchLayout, compactLayout, normalizeLayout, DEFAULT_SIZE } from '../src/utils/canvas.js'
const GAP = 16
let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  ' + detail : ''}`)
}

// 造一组典型卡片（上次诊断的驾驶舱类似规模：3 stat + 2 chart + 1 table + 2 rank）
function fakeLayout() {
  const mk = (type, i) => ({ id: `w${i}`, type, title: `卡${i}`, ...DEFAULT_SIZE[type] })
  return [mk('stat', 1), mk('stat', 2), mk('stat', 3), mk('chart', 4), mk('chart', 5), mk('table', 6), mk('rank', 7), mk('rank', 8)]
}

for (const innerW of [1280, 1536, 1600, 1920, 2560]) {
  // —— 策略层（CockpitFullscreen.rebuildScreenLayout 同款逻辑）——
  const viewW = Math.max(1180, innerW - 64)
  const viewH = Math.max(540, innerW * 0.6 - 140)  // 高度对断言无影响，取个比例
  const src = normalizeLayout(fakeLayout())
  const strategies = [
    () => tidyLayout(src, { width: viewW, fill: true, smart: false }),
    () => stretchLayout(compactLayout(src, { width: viewW }), viewW),
    () => tidyLayout(src, { width: viewW, fill: true, smart: true }),
  ]
  const candidates = strategies.map(fn => { const c = fn(); return { c, size: contentSize(c, { margin: 0 }) } })
  const fits = candidates.filter(c => c.size.h <= viewH && c.size.w >= viewW * 0.92)
  const chosen = fits.length
    ? fits.reduce((a, b) => ((a.size.w / a.size.h) > (b.size.w / b.size.h) ? a : b))
    : candidates.reduce((a, b) => (a.size.w >= b.size.w ? a : b))
  const layout = chosen.c

  // —— 画布层（新逻辑：fill = contain，绝不裁剪）——
  const content = contentSize(layout, { margin: 0 })          // screen 皮肤 margin=0
  const clientW = innerW - 64                                  // .cv 实际宽（fs-canvas padding 32×2）
  const availW = clientW                                       // fill 模式不再留 8px 缓冲
  const availH = viewH + 140 - 8
  const sx = availW / content.w
  const sy = availH / content.h
  const zoom = Math.min(2, Math.max(0.1, Math.round(Math.min(sx, sy, 1.8) * 1000) / 1000))
  const shownW = content.w * zoom
  const shownH = content.h * zoom

  // —— 旧逻辑（回归对照：margin 200 + availW-8）——
  const oldContent = contentSize(layout)                       // 默认 MARGIN=200
  const oldSx = (clientW - 8) / oldContent.w
  const oldSy = availH / oldContent.h
  const oldZoom = Math.min(2, Math.max(0.3, Math.round(Math.min(oldSx, oldSy, 1.8) * 1000) / 1000))
  const oldShownW = oldContent.w * oldZoom

  // 硬断言：纵向绝不截断（底部卡片被 hidden 裁掉比留边严重得多）
  assert(`innerW=${innerW}: 不截断 (shownH ${Math.round(shownH)} <= avail ${Math.round(availH)})`,
    shownH <= availH + 2,
    `zoom=${zoom} content=${content.w}x${content.h}`)
  // 条件断言：内容高度放得下时（sy 不构成瓶颈），横向必须铺满
  if (sy >= Math.min(sx, 1.8)) {
    assert(`innerW=${innerW}: 高度放得下时横向铺满 (shown ${Math.round(shownW)} / avail ${availW})`,
      Math.abs(shownW - availW) <= 2)
  }
  assert(`innerW=${innerW}: 旧逻辑复现缺陷 (shown ${Math.round(oldShownW)} < ${availW})`,
    oldShownW < availW - 4, `oldZoom=${oldZoom}`)
}

// 边界：内容宽被 MIN_CANVAS_W=1180 托底 + 视口更宽时，fill 仍应放大铺满
{
  const viewW = 1180
  const layout = tidyLayout(normalizeLayout([{ id: 'a', type: 'stat', ...DEFAULT_SIZE.stat }, { id: 'b', type: 'stat', ...DEFAULT_SIZE.stat }]), { width: viewW, fill: true })
  const content = contentSize(layout, { margin: 0 })
  const availW = 1536
  const zoom = Math.min(2, Math.max(0.3, Math.round(Math.min(availW / content.w, 1.8) * 1000) / 1000))
  assert('窄布局在宽视口下放大铺满', content.w * zoom >= availW - 2, `content.w=${content.w} zoom=${zoom}`)
}

// compactLayout 必须保留卡片业务字段（id/type/title/source）——
// 曾因只保留几何导致大屏卡片全部「保存后显示数据」、编辑器「紧凑」保存后抹掉配置
{
  const src = [
    { id: 'w1', type: 'list', title: '最近更新', x: 0, y: 0, w: 1520, h: 300, source: { kind: 'document', metric: 'count' } },
    { id: 'w2', type: 'chart', title: '分布', x: 0, y: 316, w: 700, h: 320, source: { kind: 'entity', type_id: 3 } },
    { id: 'w3', type: 'stat', title: '总数', x: 716, y: 316, w: 348, h: 132, source: { kind: 'entity', metric: 'count' } },
  ]
  const out = compactLayout(src, { width: 1180 })
  for (const w of out) {
    assert(`compactLayout 保留字段（${w.id || '???'}）`,
      w.id && w.type && w.title && w.source,
      JSON.stringify(Object.keys(w)))
  }
  // stretchLayout(()) 组合（大屏 compact 候选）同样必须保留
  const out2 = stretchLayout(compactLayout(src, { width: 1180 }), 1180)
  for (const w of out2) {
    assert(`compact+stretch 保留字段（${w.id || '???'}）`,
      w.id && w.type && w.title && w.source)
  }
}

// 大屏对手工排过的自由布局必须原样保留（只 stretch 货架行），不得重排 ——
// 曾把用户手排的布局用 tidy/compact 洗掉，导致「大屏和编辑器长得不一样」
{
  const placed = [
    { id: 'w1', type: 'list', title: '最近更新', x: 0, y: 0, w: 1000, h: 300, source: {} },
    { id: 'w2', type: 'chart', title: '分布', x: 1016, y: 0, w: 500, h: 300, source: {} },
    { id: 'w3', type: 'stat', title: '总数', x: 0, y: 316, w: 400, h: 132, source: {} },
  ]
  const viewW = 1472
  const out = stretchLayout(placed.map(w => ({ ...w })), viewW)
  // 相对位置与卡片顺序必须保持：w2 仍在 w1 右侧，w3 仍在第二行
  const p = Object.fromEntries(out.map(w => [w.id, w]))
  assert('手排布局原样保留：卡片不重排', out.map(w => w.id).join() === 'w1,w2,w3')
  assert('手排布局原样保留：同行不缩放', Math.abs(p.w2.x - 1016) <= 4, `w2.x=${p.w2.x}`)
  assert('手排布局原样保留：字段齐全', out.every(w => w.id && w.type && w.title && w.source))
  // 单行铺满场景：第一行从 x=0 开始且宽度不足时按比例拉满
  const row = [placed[0]]
  const stretched = stretchLayout(row.map(w => ({ ...w })), viewW)
  assert('货架行拉伸到视口宽', stretched[0].w >= viewW - 8, `w=${stretched[0].w}`)
}

// 老span布局（无坐标）仍走策略重排：normalizeLayout 补坐标后按视口铺满
{
  const legacy = [
    { id: 'a', type: 'stat', span: 1, source: {} },
    { id: 'b', type: 'chart', span: 2, source: {} },
    { id: 'c', type: 'rank', span: 1, source: {} },
  ]
  const norm = normalizeLayout(legacy, { width: 1472, fill: true })
  assert('老布局补坐标', norm.every(w => Number.isFinite(w.x) && Number.isFinite(w.y)))
  assert('老布局保留字段', norm.every(w => w.id && w.type && w.source))
}

// 极端分辨率适配：内容远超视口 3.3 倍时（如 4K 设计稿投到 720p），
// 缩放必须能突破 0.3 的通用下限继续缩小 —— contain「绝不裁剪」优先于下限
{
  const availW = 1216, availH = 620                  // 720p 全屏的可用区
  const content = { w: 3600, h: 2100 }               // 4K 设计稿
  const sx = availW / content.w
  const sy = availH / content.h
  const zoom = Math.min(2, Math.max(0.1, Math.round(Math.min(sx, sy, 1.8) * 1000) / 1000))
  assert('极端缩放：zoom 突破 0.3 下限', zoom < 0.3, `zoom=${zoom}`)
  assert('极端缩放：纵向不截断', content.h * zoom <= availH + 2, `shownH=${Math.round(content.h * zoom)}`)
  assert('极端缩放：横向不截断', content.w * zoom <= availW + 2, `shownW=${Math.round(content.w * zoom)}`)
  // 反例：若沿用 0.3 下限，底部必被裁 —— 这正是本次修的洞
  const oldZoom = Math.max(0.3, Math.round(Math.min(sx, sy) * 1000) / 1000)
  assert('反例复现：0.3 下限导致截断', content.h * oldZoom > availH + 2, `oldShownH=${Math.round(content.h * oldZoom)}`)
}

console.log(failed ? `\n${failed} 个断言失败` : '\n全部断言通过 ✅')
process.exit(failed ? 1 : 0)
