/**
 * 语义 → 强调色 的映射
 *
 * 为什么要有这个文件：
 * 全站以前只有「主色淡紫」一个颜色，模型卡片、文件卡片、关系两端的图标底板
 * 全是同一个淡紫方块，一屏十来个方块长得一模一样 —— 看不出「这是什么」。
 *
 * 这里把「是什么」翻译成颜色，颜色取自 main.css 的强调色板
 * （--accent-blue / teal / green / amber / orange / red / violet / pink / slate）：
 * - 同一个东西在哪都是同一个颜色（模型卡、表格里的图标、关系两端一致）
 * - 相邻色相刻意拉开，一屏并排时能分辨
 * - 不用随机色：颜色必须能背下来，看到颜色就知道是什么
 */

/* ============ 数据模型字段类型 → 颜色 ============ */
/**
 * 文字类用中性色（不抢注意力），真正有含义的类型才给彩色：
 * 数字=teal、日期=green、枚举=amber、开关=violet、附件=orange、图片=pink、关联=blue
 */
const FIELD_TYPE_ACCENT = {
  text: 'slate',
  textarea: 'slate',
  richtext: 'slate',
  number: 'teal',
  date: 'green',
  datetime: 'green',
  select: 'amber',
  multiselect: 'amber',
  boolean: 'violet',
  file: 'orange',
  image: 'pink',
  reference: 'blue',
}

export function fieldTypeAccent(type) {
  return FIELD_TYPE_ACCENT[type] || 'slate'
}

/* ============ 文件 MIME → 颜色 ============ */
/**
 * 跟人看到文件类型的直觉对齐：
 * PDF 红、表格绿、文档蓝、演示橙、压缩包琥珀、视频紫、音频粉、图片青、其余灰。
 */
export function fileAccent(mime, filename = '') {
  const m = String(mime || '').toLowerCase()
  const n = String(filename || '').toLowerCase()
  if (m.startsWith('image/')) return 'teal'
  if (m.includes('pdf') || n.endsWith('.pdf')) return 'red'
  if (m.includes('spreadsheet') || m.includes('excel') || m.includes('csv')) return 'green'
  if (n.endsWith('.csv') || n.endsWith('.xlsx') || n.endsWith('.xls')) return 'green'
  if (m.includes('presentation') || m.includes('powerpoint')) return 'orange'
  if (n.endsWith('.pptx') || n.endsWith('.ppt')) return 'orange'
  if (m.includes('zip') || m.includes('compressed') || m.includes('rar') || m.includes('7z')) return 'amber'
  if (n.endsWith('.zip') || n.endsWith('.rar') || n.endsWith('.7z')) return 'amber'
  if (m.includes('video')) return 'violet'
  if (m.includes('audio')) return 'pink'
  if (m.includes('word') || m.includes('document') || m.includes('markdown') || m.includes('text')) return 'blue'
  if (n.endsWith('.docx') || n.endsWith('.doc') || n.endsWith('.md') || n.endsWith('.txt')) return 'blue'
  return 'slate'
}

/* ============ 关系 ============ */
/** 关系的源端与目标端必须能一眼分开 —— 蓝=源、青=目标 */
export const REL_SOURCE_ACCENT = 'blue'
export const REL_TARGET_ACCENT = 'teal'

/** 基数 → 颜色：一对一是弱关系（灰），多对多最复杂（紫） */
const CARDINALITY_ACCENT = {
  'many-to-many': 'violet',
  'one-to-many': 'teal',
  'many-to-one': 'blue',
  'one-to-one': 'slate',
}

export function cardinalityAccent(cardinality) {
  return CARDINALITY_ACCENT[cardinality] || 'slate'
}
