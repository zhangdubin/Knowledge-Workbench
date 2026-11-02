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

/* ==================================================================== *
 * 缩放 → 文字显示档位
 *
 * 为什么需要这一层：
 *   文字在图上是「随缩放变化」的东西，而缩放是用户随时在拖的。
 *   缩得太小时字会小到认不出（画布上的字跟着缩放一起变小），
 *   或者压在一起（DOM 的字不跟着缩放，节点变小了就互相压）。
 *   两种症状的解法一样：**按缩放分级，该藏就藏、该放大就放大**。
 *
 * 为什么做成纯函数：
 *   阈值是「看起来对不对」的经验值，必须能单独验 ——
 *   不然每次改图都得靠肉眼在浏览器里缩放试。
 * ==================================================================== */

/** 文字档位：从「什么都不显示」到「放大加粗」 */
export const LABEL_TIER = {
  hidden: 'hidden',   // 缩得太小：一个字都认不出，索性全藏
  brief: 'brief',     // 缩得较小：只留图标，别的一律不画
  full: 'full',       // 正常：图标 + 名称
  large: 'large',     // 放得很大：名称放大，看得省力
}

/**
 * 档位阈值（可被调用方覆盖，方便不同图谱微调）
 *
 * hiddenBelow 必须 ≤ minScaleFor()（宽屏 0.45）：
 *   缩放下限的意义是「宁可看不清全图，也要看得清字」。
 *   如果藏字阈值比下限还高，就会出现「被下限卡住的画面一个字都没有」——
 *   那不是取舍，是 bug。两处数值要一起改。
 */
export const ZOOM_RULES = {
  hiddenBelow: 0.45,  // < 0.45 → hidden（13px 的字只剩 5.8px，那不是字，是噪点）
  briefBelow: 0.8,    // < 0.8  → brief（只留图标，名字还认不出来）
  largeFrom: 1.55,    // >= 1.55 → large
}

/**
 * 当前缩放对应哪个文字档位
 *
 * @param {number} scale 画布缩放比（1 = 原始大小）
 * @param {object} rules 阈值覆盖
 * @returns {string} LABEL_TIER 里的一个值
 */
export function labelTierFor(scale, rules = ZOOM_RULES) {
  const s = Number(scale)
  if (!Number.isFinite(s) || s <= 0) return LABEL_TIER.hidden
  if (s < rules.hiddenBelow) return LABEL_TIER.hidden
  if (s < rules.briefBelow) return LABEL_TIER.brief
  if (s >= rules.largeFrom) return LABEL_TIER.large
  return LABEL_TIER.full
}

/**
 * 这个档位下，节点名最多留几个字
 *
 * 为什么要分级截断而不是一刀切：
 *   「brief」档留给的是「知道这里有个节点、但还没细看」的场景，
 *   名字给太长反而压字；给 2 个字刚好能区分。
 */
export function labelCharsForTier(tier, windowWidth = 1440) {
  const narrow = windowWidth < 760
  switch (tier) {
    case LABEL_TIER.hidden: return 0
    case LABEL_TIER.brief: return narrow ? 1 : 2
    case LABEL_TIER.large: return narrow ? 18 : 40
    case LABEL_TIER.full:
    default: return labelBudget(windowWidth)
  }
}

/**
 * 这个档位下的节点字号
 *
 * canvas 上的字会跟着缩放一起变大变小，
 * 所以「large」档把字号调小一点，放大后的字才不会大得离谱。
 */
export function fontSizeForTier(tier, baseSize = 13) {
  switch (tier) {
    case LABEL_TIER.hidden: return baseSize
    case LABEL_TIER.brief: return baseSize
    case LABEL_TIER.large: return Math.round(baseSize * 0.9)
    case LABEL_TIER.full:
    default: return baseSize
  }
}

/**
 * DOM 文字（不跟画布缩放）该放大多少倍
 *
 * 为什么 DOM 文字要单独处理：
 *   canvas 上的字跟着缩放走，DOM 上的字不会 ——
 *   放大时节点变大了、字还是那么大，看着像「字变小了」；
 *   缩小时节点变小了、字不变，一堆字压在一起。
 *   所以让字按缩放同比放大（并配合「太小时整层藏掉」）。
 */
export function domLabelScaleFor(scale) {
  const s = Number(scale)
  if (!Number.isFinite(s) || s <= 0) return 1
  // 夹在 0.7~1.8 之间：太小会把字缩得看不清，太大会撑破布局
  return Math.min(1.8, Math.max(0.7, s))
}

/**
 * 这一档要不要给用户一句提示
 *
 * 为什么藏字要说话：
 *   「字不见了」看起来像 bug，不像设计。
 *   说一句「缩得太小，名称已隐藏，放大可显示」，用户才知道怎么找回。
 */
export function tierHint(tier) {
  if (tier === LABEL_TIER.hidden) return '缩得太小，名称已隐藏 —— 放大即可显示'
  if (tier === LABEL_TIER.brief) return '当前只显示图标 —— 放大可看到完整名称'
  return ''
}

