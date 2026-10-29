/**
 * 图谱配色的纯计算
 *
 * 为什么单独抽出来：混色、截断、缩放下限这几件事都要能单独验证，
 * 而且组件里混着大量 vis 的回调，逻辑混在一起就没法测了。
 * 这里只放纯函数，不依赖 Vue，也不碰 DOM。
 */

/**
 * 连线语义 → 颜色槽位 / 线型
 *
 * 为什么不用调色板下标：知识图谱里所有边都是同一种语义，
 * 全撞成同一个颜色就等于没有颜色可分。
 * 这里给每种语义一个固定色相，颜色只表达「这条线是什么关系」。
 */
export const VIA_META = {
  relation: { label: '关联关系', slot: 0, arrow: true, dash: false },
  reference: { label: '外键引用', slot: 1, arrow: true, dash: false },
  field: { label: '字段挂载', slot: 2, arrow: true, dash: false },
  wikilink: { label: '双向链接', slot: 5, arrow: false, dash: true },
}

/** 取连线的语义定义；未知语义按关联关系处理 */
export function viaMeta(via) {
  return VIA_META[via] || VIA_META.relation
}

/** 节点标签最多显示几个字（窄屏留短一点，免得盒子挤成一坨） */
export const LABEL_MAX_CHARS = { wide: 14, narrow: 8 }

/** 当前视口宽度下，标签最多留几个字 */
export function labelBudget(windowWidth) {
  return windowWidth < 760 ? LABEL_MAX_CHARS.narrow : LABEL_MAX_CHARS.wide
}

/**
 * 缩放下限
 *
 * 为什么要卡下限：手机上把整张图 fit 进 390px 宽，缩放只有 0.28，
 * 13px 的节点名缩成 3.6px —— 什么字都认不出。
 * 「看得全」和「看得清」必须选一个，这里选「看得清」。
 */
export function minScaleFor(windowWidth) {
  return windowWidth < 760 ? 0.62 : 0.45
}

/** 十六进制 → rgb 三元组 */
export function hex2rgb(hex) {
  const s = String(hex || '#888').replace('#', '')
  const n = s.length === 3 ? s.split('').map(c => c + c).join('') : s
  return [
    parseInt(n.slice(0, 2), 16) || 0,
    parseInt(n.slice(2, 4), 16) || 0,
    parseInt(n.slice(4, 6), 16) || 0,
  ]
}

/**
 * 两种颜色按比例混出一个不透明的颜色
 *
 * 为什么需要：节点底色原来是 rgba(类型色, 0.13) —— 半透明。
 * 半透明的底色挡不住线，于是连线会从文字下面穿过去，看着像被划掉了。
 * 混成不透明的浅色底，线就永远压不到文字上。
 *
 * @param {string} a 主色
 * @param {string} b 混入色
 * @param {number} ratio b 的占比（0~1）
 */
export function mix(a, b, ratio) {
  const A = hex2rgb(a)
  const B = hex2rgb(b)
  const c = i => Math.round(A[i] * (1 - ratio) + B[i] * ratio)
  return `rgb(${c(0)}, ${c(1)}, ${c(2)})`
}

/** 把颜色往白里提一档（暗色模式下用，否则类型色在深底上不够亮） */
export function lift(hex, amount) {
  return mix(hex, '#ffffff', amount)
}

/**
 * 标签截断：太长就砍掉加省略号，完整名留在 title 里
 *
 * 为什么截断：模型里有一条 25 字的记录名，原样画出来盒子有 233px 宽，
 * 在手机上缩放后直接糊成一片。
 */
export function truncateLabel(text, max) {
  const str = String(text || '')
  if (!max || max < 2) return str
  if (str.length <= max) return str
  return `${str.slice(0, max - 1)}…`
}

/** 估算一段文字的像素宽度：中文按字号，英文按 0.55 字号 */
export function textWidth(str, size) {
  let w = 0
  for (const ch of String(str || '')) {
    w += /[⺀-鿿＀-￯]/.test(ch) ? size : size * 0.55
  }
  return w
}
