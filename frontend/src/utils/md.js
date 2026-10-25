/**
 * 极简 Markdown → HTML
 *
 * 只服务驾驶舱的「文本卡」：一句话说明、几个要点、偶尔加粗。
 * 引入完整 Markdown 库不划算，而把用户输入直接 innerHTML 又必须防 XSS，
 * 所以这里先整体转义、再做少量替换 —— 转义在前，标签就一定是我们生成的。
 */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inline(s) {
  return s
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

export function miniMarkdown(src) {
  const lines = esc(src).split(/\r?\n/)
  const out = []
  let listOpen = false

  const closeList = () => { if (listOpen) { out.push('</ul>'); listOpen = false } }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) { closeList(); continue }

    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      closeList()
      const level = Math.min(h[1].length + 2, 5)   // 卡片内 h1 也只用 h3 大小
      out.push(`<h${level}>${inline(h[2])}</h${level}>`)
      continue
    }
    const li = line.match(/^\s*[-*·]\s+(.*)$/)
    if (li) {
      if (!listOpen) { out.push('<ul>'); listOpen = true }
      out.push(`<li>${inline(li[1])}</li>`)
      continue
    }
    closeList()
    out.push(`<p>${inline(line)}</p>`)
  }
  closeList()
  return out.join('')
}

/* ============================================================
   完整版 Markdown → HTML（给 AI 回答用）
   ------------------------------------------------------------
   和上面的 miniMarkdown 的区别：这个是「先解析块级、再逐块转义」，
   所以 `> 引用`、`| 表格 |`、缩进列表才认得出来；
   miniMarkdown 是「整段先转义」，两个字符 `>` 早就被转成 &gt; 了。

   安全性：所有文本一律经过 esc() 才进 HTML；标签全部由本函数生成，
   href 另外过一道 safeUrl()（挡掉 javascript: 之类的协议）。
   ============================================================ */

const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const escAll = s => String(s ?? '').replace(/[&<>"']/g, c => ESC_MAP[c])

/** 只放行 http/https/mailto/锚点/站内路径，其余（如 javascript:）一律废弃 */
function safeUrl(u) {
  const s = String(u || '').trim()
  if (/^(https?:\/\/|mailto:|#|\/)/i.test(s)) return s
  return '#'
}

/** 行内：`代码` **粗** *斜* ~~删~~ [文字](链接) */
function inlineMd(s) {
  const codes = []
  let t = escAll(s).replace(/`([^`]+)`/g, (_m, c) => {
    codes.push(c)
    return `\u0001${codes.length - 1}\u0001`          // 先占位，免得代码里的 * 被当成强调
  })
  t = t
    .replace(/\[([^\]]*)\]\(([^()\s]+)\)/g,
      (_m, txt, href) => `<a href="${safeUrl(href)}" target="_blank" rel="noopener noreferrer">${txt}</a>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
  return t.replace(/\u0001(\d+)\u0001/g, (_m, i) => `<code>${codes[+i]}</code>`)
}

/** 拆表格行：| a | b | → ['a','b']，并还原转义的 \| */
function splitRow(row) {
  const s = row.trim().replace(/\\\|/g, '\u0002').replace(/^\|/, '').replace(/\|$/, '')
  return s.split('|').map(c => c.replace(/\u0002/g, '|').trim())
}

function isTableSep(row) {
  if (!row || row.indexOf('|') === -1) return false
  const cells = splitRow(row)
  return cells.length > 0 && cells.every(c => /^:?-{1,}:?$/.test(c))
}

/** 全是数字/金额/百分比 → 该列右对齐，读数更顺 */
const NUMERIC = /^[¥$€]?\s*[-+]?\d[\d,._]*\s*(%|元|万元|亿|万|次|条|个|天|人)?$/

function renderTable(rows) {
  const head = splitRow(rows[0])
  const align = splitRow(rows[1]).map(c =>
    /^:-+:$/.test(c) ? 'center' : /^-+:$/.test(c) ? 'right' : /^:-+$/.test(c) ? 'left' : '')
  const body = rows.slice(2).map(splitRow)
  const cols = head.length

  // 整列都是数字（且不是第一列）→ 右对齐
  const numeric = head.map((_h, ci) => ci > 0 && body.length > 0 &&
    body.every(r => !r[ci] || NUMERIC.test(r[ci])))
  const cls = ci => [
    align[ci] === 'right' || numeric[ci] ? 'num' : '',
    align[ci] === 'center' ? 'ctr' : '',
  ].filter(Boolean).join(' ')

  const th = head.map((c, ci) => `<th class="${cls(ci)}">${inlineMd(c)}</th>`).join('')
  const trs = body.map(r => '<tr>' +
    Array.from({ length: cols }, (_x, ci) => `<td class="${cls(ci)}">${inlineMd(r[ci] ?? '')}</td>`).join('') +
    '</tr>').join('')

  // 外层 div 负责横向滚动：窄屏宁可滑，也不把中文挤成一列一个字
  return `<div class="md-table-wrap"><table><thead><tr>${th}</tr></thead>` +
    (trs ? `<tbody>${trs}</tbody>` : '') + '</table></div>'
}

/* ============================================================
   YAML frontmatter（文档属性）
   ------------------------------------------------------------
   Obsidian 风格的 .md 开头常有一段 --- 包起来的 YAML：
   title / tags / created / status 等。不处理的话它会被当成
   正文 —— 两个 --- 变成两条分隔线，中间是一坨裸 YAML，很难读。

   这里只解析最常见的两种形态：key: value，和 key: 后面跟
   一串 "- item" 列表项（渲染成小标签）。认不出来的行原样保留，
   绝不丢内容。
   ============================================================ */

/** 拆出 frontmatter：返回 { raw, body }，不是 frontmatter 则返回 null */
export function splitFrontmatter(src) {
  const lines = String(src ?? '').replace(/\r\n?/g, '\n').split('\n')
  if (lines[0]?.trim() !== '---') return null
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === '---') {
      const block = lines.slice(1, i)
      // 块里有空行 → 多半不是 frontmatter，而是正文里的分隔线碰巧在开头
      if (!block.some(l => l.trim()) || block.some(l => !l.trim())) return null
      return { raw: block.join('\n'), body: lines.slice(i + 1).join('\n') }
    }
    // 别的分隔线写法（*** / ___）出现，说明这压根不是 frontmatter
    if (/^\s*(\*\*\*|___)\s*$/.test(lines[i])) return null
  }
  return null
}

/** frontmatter → 属性表 HTML */
function renderFrontmatter(raw) {
  const rows = []
  let cur = null
  for (const line of raw.split('\n')) {
    const item = line.match(/^\s*-\s+(.*)$/)
    if (item && cur) { cur.list.push(item[1].trim()); continue }
    const kv = line.match(/^([^\s:#][^:#]*)\s*:\s*(.*)$/)
    if (kv) {
      cur = { key: kv[1].trim(), value: kv[2].trim(), list: [] }
      rows.push(cur)
      continue
    }
    // 认不出的行：挂到上一个键后面，别丢
    if (line.trim() && cur) cur.value = (cur.value ? cur.value + ' ' : '') + line.trim()
  }
  if (!rows.length) return ''

  const body = rows.map(r => {
    const val = r.list.length
      ? r.list.map(x => `<span class="md-fm-chip">${escAll(x)}</span>`).join('')
      : `<span class="md-fm-val">${inlineMd(r.value)}</span>`
    return `<div class="md-fm-row"><span class="md-fm-key">${escAll(r.key)}</span>${val}</div>`
  }).join('')

  return `<div class="md-frontmatter">${body}</div>`
}

export function renderMarkdown(src, opts = {}) {
  // 标题层级的下压量。AI 气泡里 h1 太占地方，默认压到 h3 起（+2）；
  // 文档正文要保留原始层级，调用方传 headingOffset: 0，
  // 这样「# 一级标题 / ## 二级标题」在长文里仍能一眼分清主次。
  const hOffset = opts.headingOffset ?? 2

  // 文档正文（opts.frontmatter）才拆 frontmatter；
  // AI 回答保持原样，免得把「---」误判成属性块。
  let source = String(src ?? '')
  let fmHtml = ''
  if (opts.frontmatter) {
    const fm = splitFrontmatter(source)
    // 解析不出属性行就别拆 —— 否则那一段原文会被凭空吞掉
    if (fm) {
      const html = renderFrontmatter(fm.raw)
      if (html) { source = fm.body; fmHtml = html }
    }
  }

  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const out = []
  let i = 0

  /** 这一段是不是「新块的开头」——用于打断正在收集的段落 */
  const startsBlock = n => {
    const l = lines[n]
    if (l === undefined || !l.trim()) return true
    if (/^\s*```/.test(l)) return true
    if (/^#{1,6}\s/.test(l)) return true
    if (/^\s*>\s?/.test(l)) return true
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(l)) return true
    if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) return true
    if (l.indexOf('|') !== -1 && isTableSep(lines[n + 1] ?? '')) return true
    return false
  }

  while (i < lines.length) {
    const line = lines[i].replace(/\s+$/, '')

    if (!line.trim()) { i++; continue }

    // ---- 围栏代码块 ----
    if (/^\s*```/.test(line)) {
      const lang = line.replace(/^\s*```/, '').trim()
      const buf = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++ }
      i++                                                  // 跳过收尾的 ```
      out.push(`<pre class="md-pre"${lang ? ` data-lang="${escAll(lang)}"` : ''}><code>${escAll(buf.join('\n'))}</code></pre>`)
      continue
    }

    // ---- 标题（AI 气泡里 h1/h2 压到 h3 起；文档正文按 headingOffset 原样保留）----
    const h = line.match(/^(#{1,6})\s+(.+)$/)
    if (h) {
      const lv = Math.min(Math.max(h[1].length + hOffset, 1), 6)
      out.push(`<h${lv}>${inlineMd(h[2])}</h${lv}>`)
      i++
      continue
    }

    // ---- 分隔线 ----
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) { out.push('<hr>'); i++; continue }

    // ---- 引用 ----
    if (/^\s*>\s?/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''))
        i++
      }
      out.push(`<blockquote>${buf.map(inlineMd).join('<br>')}</blockquote>`)
      continue
    }

    // ---- 表格 ----
    if (line.indexOf('|') !== -1 && isTableSep(lines[i + 1] ?? '')) {
      const rows = [line, lines[i + 1]]                     // rows[0]=表头 rows[1]=分隔行
      i += 2
      while (i < lines.length && lines[i].trim() && lines[i].indexOf('|') !== -1) {
        rows.push(lines[i].replace(/\s+$/, ''))
        i++
      }
      out.push(renderTable(rows))
      continue
    }

    // ---- 列表（缩进 ≥ 2 空格算第二层，用 class 缩进，不折腾嵌套标签）----
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s/.test(line)
      const tag = ordered ? 'ol' : 'ul'
      const items = []
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/)
        if (!m) break
        if (/^\s*\d+[.)]\s/.test(lines[i]) !== ordered && items.length) break
        const lv = m[1].replace(/\t/g, '  ').length >= 2 ? 2 : 1
        items.push(`<li${lv > 1 ? ' class="lvl-2"' : ''}>${inlineMd(m[3])}</li>`)
        i++
      }
      out.push(`<${tag}>${items.join('')}</${tag}>`)
      continue
    }

    // ---- 段落（软换行保留，符合中文书写习惯）----
    const buf = [line]
    i++
    while (i < lines.length && !startsBlock(i)) { buf.push(lines[i].replace(/\s+$/, '')); i++ }
    out.push(`<p>${buf.map(inlineMd).join('<br>')}</p>`)
  }

  return fmHtml + out.join('')
}
