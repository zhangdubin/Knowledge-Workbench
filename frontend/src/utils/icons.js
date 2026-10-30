// 统一的图标映射：把后端返回的 entity_type.key / app.key 映射为 Element Plus 图标组件名。
// 全局已注册所有 Element Plus 图标，因此这里返回字符串名即可在 <component :is="..."> 使用。

export const ENTITY_ICON_MAP = {
  // 知识
  note: 'Notebook',
  reading_note: 'EditPen',
  article: 'Memo',
  // 项目
  project: 'Folder',
  task: 'List',
  milestone: 'Flag',
  risk: 'WarningFilled',
  // 销售
  customer: 'User',
  opportunity: 'TrendCharts',
  order: 'Box',
  followup: 'ChatDotRound',
  // 合同 / 财务
  contract: 'Files',
  payment: 'Money',
  vendor: 'OfficeBuilding',
  invoice: 'Tickets',
  // 库存
  product: 'Goods',
  warehouse: 'OfficeBuilding',
  stock_move: 'Sort',
  supplier: 'Van',
  // 文献
  paper: 'Reading',
  author: 'Avatar',
  // 支持
  ticket: 'Service',
  // 人事
  department: 'OfficeBuilding',
  employee: 'UserFilled',
  job: 'Briefcase',
  candidate: 'Avatar',
  // 资产
  asset: 'Monitor',
  borrow: 'Sort',
  maintenance: 'Tools',
  // 其他
  contact: 'User',
  file: 'Document',
}

export const APP_ICON_MAP = {
  knowledge: 'Notebook',
  project: 'Management',
  sales: 'TrendCharts',
  crm: 'User',
  contract: 'Files',
  library: 'Coin',
  finance: 'Money',
  hr: 'Avatar',
  inventory: 'Box',
  research: 'Reading',
  support: 'Service',
  asset: 'Monitor',
  default: 'Grid',
}

/**
 * 模板生成的模型 key 会带应用前缀（如 hr_employee）。
 * 先精确匹配，再按后缀匹配去前缀。
 */
function lookup(map, key, fallback) {
  if (!key) return fallback
  if (map[key]) return map[key]
  for (const k of Object.keys(map)) {
    if (key.endsWith('_' + k)) return map[k]
  }
  return fallback
}

export function entityIcon(key) {
  return lookup(ENTITY_ICON_MAP, key, 'Folder')
}

/**
 * 应用的强调色
 *
 * 为什么按 key 分配而不是让用户自己选：
 * - 应用卡片的图标底板原来全是同一个淡紫方块，一屏六个应用长得一模一样，
 *   像同一个东西复制了六遍 —— 这是「整个界面很平、很丑」的最大来源。
 * - 按 key 固定分配，每个应用有稳定的颜色，用户扫一眼就能认出是哪个应用。
 * - 颜色取自全局强调色板（accent-*），浅色/深色两套都由 main.css 负责。
 */
const APP_ACCENTS = {
  knowledge: 'violet',
  project: 'blue',
  sales: 'teal',
  crm: 'green',
  contract: 'amber',
  library: 'orange',
  finance: 'red',
  hr: 'pink',
  inventory: 'slate',
  research: 'green',
  support: 'amber',
  asset: 'slate',
  default: 'blue',
}

/** 应用用哪个强调色（没登记过的按 key 哈希稳定分配一个） */
export function appAccent(key) {
  const k = String(key || '')
  if (APP_ACCENTS[k]) return APP_ACCENTS[k]
  // 没登记过的：按 key 的字符和取模，保证同一个 key 每次都是同一个颜色
  let sum = 0
  for (let i = 0; i < k.length; i++) sum = (sum + k.charCodeAt(i) * (i + 1)) % 997
  const pool = ['blue', 'teal', 'green', 'amber', 'orange', 'red', 'violet', 'pink']
  return pool[sum % pool.length]
}

export function appIcon(key) {
  return lookup(APP_ICON_MAP, key, 'Grid')
}

// 应用图标可选集合（新建/编辑应用时使用）
export const APP_ICON_CHOICES = [
  'Grid', 'Management', 'Notebook', 'Coin', 'Files', 'User', 'ShoppingCart',
  'Box', 'Money', 'TrendCharts', 'DataAnalysis', 'Connection', 'Tickets',
  'Goods', 'Avatar', 'Histogram', 'Briefcase', 'SetUp', 'Reading', 'Service',
  'Monitor', 'OfficeBuilding', 'Van', 'Tools', 'Flag', 'Collection', 'Folder',
  'Document', 'Memo', 'EditPen', 'Star', 'Compass', 'Aim',
]

// 数据模型图标可选集合
export const ENTITY_ICON_CHOICES = APP_ICON_CHOICES

export function isKnownIcon(name, list) {
  return list.includes(name)
}
