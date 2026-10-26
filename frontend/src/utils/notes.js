/**
 * 笔记相关的纯函数集合
 * ---------------------------------------------------------------------------
 * 这里刻意不碰 Vue、不碰 API：能算的都算成纯函数，
 * 一来可以在 tests/notes.test.mjs 里直接断言（不需要起浏览器），
 * 二来 Notes.vue / NoteDetail.vue / NoteEditor.vue 共用同一套规则，
 * 不会出现「列表里标题和详情页标题不一样」的割裂感。
 *
 * 参照的是 Obsidian 的行为：
 *   - 没有标题时用正文首行兜底（新建文件时文件名就是首行）
 *   - 列表里展示的是「剥掉 Markdown 标记后的纯文本」
 *   - 标签大小写不敏感去重
 */

import { renderMarkdown } from './md.js'

const HTML_ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

/** HTML 转义（渲染 [[双链]] 锚点时用） */
export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => HTML_ESCAPE[c])
}

/**
 * 剥掉 Markdown 标记，只留可读文本。
 * 列表摘要、搜索高亮、无障碍朗读都用它。
 */
export function stripMarkdown(src) {
  let s = String(src ?? '')

  // YAML frontmatter（Obsidian 的文件属性）：整体丢掉，别糊在摘要里
  s = s.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
  // 代码围栏：留内容、去掉 ``` 标记
  s = s.replace(/```[^\n]*\n?/g, '')
  // 上传附件时机器写入的元数据残留（老版 cleanSnippet 就在处理这个）
  s = s.replace(/upload\s*\[[\s\S]*?\]/g, ' ')
  s = s.replace(/attachment_id\s*\d+/g, ' ')

  // 图片 → alt 文本；链接 → 锚文本
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  // 双链：[[标题|别名]] → 别名；[[标题]] → 标题
  s = s.replace(/\[\[([^\[\]|]+)\|([^\[\]]+)\]\]/g, '$2')
  s = s.replace(/\[\[([^\[\]]+)\]\]/g, '$1')

  // 行内代码、强调
  s = s.replace(/`([^`]+)`/g, '$1')
  s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '$1')
  s = s.replace(/\*\*([^*]+)\*\*/g, '$1')
  s = s.replace(/(^|[^\w*])\*([^*\n]+)\*(?=[^\w*]|$)/g, '$1$2')
  s = s.replace(/~~([^~]+)~~/g, '$1')

  // 块级前缀：标题、引用、列表、分隔线
  s = s.replace(/^\s{0,3}#{1,6}\s+/gm, '')
  s = s.replace(/^\s{0,3}>\s?/gm, '')
  s = s.replace(/^\s{0,3}[-*+]\s+/gm, '')
  s = s.replace(/^\s{0,3}\d+[.)]\s+/gm, '')
  s = s.replace(/^\s{0,3}([-*_])(\s*\1){2,}\s*$/gm, ' ')
  // 表格分隔行（|---|---|）本身没有信息量
  s = s.replace(/^\s*\|?[\s:|-]*\|[\s:|-]*$/gm, ' ')

  // 行内 HTML 标签
  s = s.replace(/<\/?[a-zA-Z][^>]*>/g, ' ')
  return s
}

/** 折叠空白：摘要必须是单行 */
export function collapseWhitespace(s) {
  return String(s ?? '').replace(/\s+/g, ' ').trim()
}

/**
 * 取正文首行作为标题（Obsidian：新建文件时文件名取自第一行）。
 * 会跳过 frontmatter 和空行；没有可用内容时返回空串。
 */
export function firstLineTitle(content) {
  const lines = String(content ?? '').replace(/\r\n?/g, '\n').split('\n')
  let start = 0
  if (lines[0]?.trim() === '---') {
    for (let i = 1; i < lines.length; i++) {
      if (lines[i].trim() === '---') { start = i + 1; break }
      if (/^\s*(\*\*\*|___)\s*$/.test(lines[i])) { start = 0; break }
    }
  }
  for (let i = start; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue
    if (/^```/.test(line)) continue
    const t = collapseWhitespace(stripMarkdown(line))
    if (t) return t
  }
  return ''
}

/**
 * 笔记的显示标题：显式标题 > 正文首行 > 「未命名笔记 #id」。
 * 列表和详情页必须用同一个函数，否则标题会前后不一致。
 */
export function noteTitle(note, id) {
  const explicit = collapseWhitespace(note?.data?.title || '')
  if (explicit) return explicit
  const derived = firstLineTitle(note?.data?.content || '')
  if (derived) return derived
  const suffix = id ?? note?.id
  return suffix != null ? `未命名笔记 #${suffix}` : '未命名笔记'
}

/** 列表摘要：剥 Markdown + 折叠成单行 + 截断 */
export function noteSnippet(content, max = 140) {
  const t = collapseWhitespace(stripMarkdown(content || ''))
  if (!t) return ''
  return t.length > max ? t.slice(0, max).trimEnd() + '…' : t
}

/**
 * 标签规范化：去空白、去前缀 #、按大小写不敏感去重（保留首次出现的写法）。
 */
export function normalizeTags(tags) {
  const out = []
  const seen = new Set()
  for (const raw of Array.isArray(tags) ? tags : []) {
    const t = String(raw ?? '').trim().replace(/^#+/, '').trim()
    if (!t) continue
    const key = t.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(t)
  }
  return out
}

/** 把「架构, 设计」这样的输入串解析成标签数组 */
export function parseTags(input) {
  return normalizeTags(String(input ?? '').split(/[,，;；、\n]/))
}

/**
 * 标签候选：输入 # 时给全部，输入文字时按包含匹配。
 * 大小写不敏感，结果去重并保留原始写法。
 */
export function matchTags(query, all, limit = 8) {
  const uniq = []
  const seen = new Set()
  for (const raw of Array.isArray(all) ? all : []) {
    const t = String(raw ?? '').trim().replace(/^#+/, '').trim()
    if (!t) continue
    const key = t.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    uniq.push(t)
  }
  const q = String(query ?? '').trim().replace(/^#+/, '').toLowerCase()
  if (!q) return uniq.slice(0, limit)
  return uniq.filter(t => t.toLowerCase().includes(q)).slice(0, limit)
}

/**
 * 相对时间（Obsidian 的 "12 minutes ago"）：
 * 刚刚 / N 分钟前 / N 小时前 / 昨天 HH:MM / N 天前 / M 月 D 日 / YYYY-MM-DD
 */
export function relativeTime(t, now = Date.now()) {
  if (!t) return ''
  const d = new Date(t)
  if (isNaN(d.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  const diff = now - d.getTime()
  if (diff < 0) return '刚刚'
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hour = Math.floor(min / 60)
  if (hour < 24) return `${hour} 小时前`
  const day = Math.floor(hour / 24)
  if (day === 1) return `昨天 ${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (day < 7) return `${day} 天前`
  if (new Date(now).getFullYear() === d.getFullYear()) return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 正文里引用的双链标题（去重、保序） */
export function extractWikilinks(content) {
  const out = []
  const re = /\[\[([^\[\]\n]+?)\]\]/g
  let m
  while ((m = re.exec(String(content ?? '')))) {
    const t = m[1].split('|')[0].trim()
    if (t && !out.includes(t)) out.push(t)
  }
  return out
}

/**
 * 正文里的行内标签（Obsidian 的 #tag 写法）。
 * 只认「前面是空白或括号」的 #，免得把 C# / issue#12 这类当成标签。
 */
export function extractHashtags(content) {
  const out = []
  const re = /(^|[\s(（])#([A-Za-z0-9_\u4e00-\u9fa5][A-Za-z0-9_\u4e00-\u9fa5/-]*)/g
  let m
  while ((m = re.exec(String(content ?? '')))) {
    const t = m[2].trim()
    if (t && !out.some(x => x.toLowerCase() === t.toLowerCase())) out.push(t)
  }
  return out
}

/**
 * 笔记正文 → HTML。
 * 复用 utils/md.js 的渲染（转义、表格、代码块都在那边），这里只补一件事：
 * 把 [[标题]] 变成可点击的双链锚点。
 *
 * 代码块里的 [[x]] 不做链接化 —— Obsidian 也不会把代码里的方括号当双链。
 */
export function renderNoteHtml(content) {
  const html = renderMarkdown(content || '', { headingOffset: 0, frontmatter: true })
  // 拆出代码块，奇数段是代码块本身（不处理），偶数段才做双链替换
  const parts = html.split(/(<pre class="md-pre">[\s\S]*?<\/pre>)/g)
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part
      return part.replace(/\[\[([^\[\]\n]+?)\]\]/g, (_m, inner) => {
        const text = inner.trim()
        return `<a class="note-wikilink" href="#" data-wikilink="${inner}" title="跳转到「${text}」">${inner}</a>`
      })
    })
    .join('')
}
