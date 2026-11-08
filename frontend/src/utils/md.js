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

/**
 * HTML 转义（对外公开）
 *
 * 任何「原文 → v-html」的路��都必须先过这一道。
 * 之前只有 md.js 内部用 escAll，SearchView 的关键词高亮就因为找不到
 * 可用的转义函数而直接把文件名拼进了 v-html —— 存成
 * `<img src=x onerror=...>` 的文件名在搜索结果里就能执行脚本。
 * 把它导出，就是为了让「要往 v-html 里塞字符串」这件事不再需要自己实现一遍。
 */
export const escapeHtml = escAll

/** 只放行 http/https/mailto/锚点/站内路径，其余（如 javascript:）一律废弃 */
function safeUrl(u) {
  const s = String(u || '').trim()
  // 协议相对 URL（//evil.com/x）长得像站内绝对路径，其实会把浏览器
  // 带到外站 —— 必须在放行 / 之前单独拦掉。
  if (s.startsWith('//')) return '#'
  if (/^(https?:\/\/|mailto:|#|\/)/i.test(s)) return s
  return '#'
}

/**
 * 把扁平的列表行还原成嵌套结构并渲染
 *
 * 缩进决定层级，标记符决定这一层渲染成 <ul> 还是 <ol>。
 * 同一层里标记符换了（先 `-` 后 `1.`）按 Markdown 常规行为开一个新列表。
 *
 * 深层列表项会带上 lvl-2 / lvl-3 class：主样式里用它区分项目符号形状
 * （圆点 / 方块），缩进本身由嵌套结构天然提供。
 */
/** 任务列表的勾选框（§8.3）：GitHub 风格的 - [ ] / - [x] / - [-] / - [?] */
const TASK_BOX = {
  ' ': '<span class="md-task-box" aria-hidden="true">☐</span>',
  x: '<span class="md-task-box is-done" aria-hidden="true">☑</span>',
  '-': '<span class="md-task-box is-doing" aria-hidden="true">◐</span>',
  '?': '<span class="md-task-box is-ask" aria-hidden="true">?</span>',
}

function renderTaskText(text) {
  const m = String(text).match(/^\[([ xX\-?])\]\s+(.*)$/)
  if (!m) return null
  const mark = m[1] === 'X' ? 'x' : m[1]
  return `${TASK_BOX[mark] || TASK_BOX[' ']}<span class="md-task-text">${m[2]}</span>`
}

function renderListTree(items) {
  // ---- 1) 按缩进建树 ----
  const root = { children: [] }
  const stack = [{ indent: -1, children: root.children }]
  for (const it of items) {
    while (stack.length > 1 && it.indent <= stack[stack.length - 1].indent) stack.pop()
    const node = { ...it, children: [] }
    stack[stack.length - 1].children.push(node)
    stack.push({ indent: it.indent, children: node.children })
  }
  // ---- 2) 渲染：同层按标记符分组 ----
  const renderLevel = (nodes, depth) => {
    let out = ''
    let i = 0
    while (i < nodes.length) {
      const ordered = nodes[i].ordered
      const group = []
      while (i < nodes.length && nodes[i].ordered === ordered) { group.push(nodes[i]); i++ }
      const tag = ordered ? 'ol' : 'ul'
      out += `<${tag}>` + group.map(n => {
        const task = renderTaskText(n.raw || '')
        const classes = []
        if (depth > 0) classes.push(`lvl-${Math.min(depth + 1, 3)}`)
        if (task !== null) classes.push('md-task')
        const cls = classes.length ? ` class="${classes.join(' ')}"` : ''
        const body = task === null ? n.text : task
        return `<li${cls}>${body}${n.children.length ? renderLevel(n.children, depth + 1) : ''}</li>`
      }).join('') + `</${tag}>`
    }
    return out
  }
  return renderLevel(root.children, 0)
}

/**
 * 关键词高亮：返回可直接交给 v-html 的 HTML
 *
 * 每一段都先转义再拼标签 —— 高亮的输入是「文件名 / 标题 / 摘要」，
 * 这些都来自用户上传或录入。早先的实现直接把原文 replace 成
 * '<mark>$1</mark>'，于是存成 `<img src=x onerror=...>` 的文件名
 * 一搜就执行脚本（存型 XSS）。
 *
 * 用「切分」而不是「replace + 捕获组」，是为了避开 replace 里
 * $1 / $& 被当成替换符的坑。
 */
export function highlightHtml(text, keyword) {
  const src = String(text ?? '')
  const needle = String(keyword ?? '').trim()
  if (!needle) return escapeHtml(src)
  const lowerSrc = src.toLowerCase()
  const lowerNeedle = needle.toLowerCase()
  let out = ''
  let pos = 0
  while (pos <= src.length) {
    const hit = lowerSrc.indexOf(lowerNeedle, pos)
    if (hit < 0) break
    out += escapeHtml(src.slice(pos, hit))
    out += `<mark>${escapeHtml(src.slice(hit, hit + needle.length))}</mark>`
    pos = hit + needle.length
  }
  out += escapeHtml(src.slice(pos))
  return out
}

/* ------------------------------------------------------------------
   行内 HTML 白名单
   ------------------------------------------------------------------
   规范里有两个东西**必须用 HTML 写**，Markdown 没有对应语法：
     §11 敏感信息遮盖：<span class="secret-toggle">… secret-mask … secret-value …</span>
     §8.2 折叠块：<details>/<summary>
   之前整个渲染器「先转义再解析」，这些标签会原样显示成一串源码 ——
   于是规范写得再对，知识库里看到的仍是一坨尖括号。

   所以这里先**摘出白名单内的标签**（内容照样转义），再整体转义其余部分。
   只认下面这几种固定形态：属性只认 class="secret-toggle|secret-mask|secret-value"
   和 tabindex，别的一概不认（不认就是纯文本，安全边界不会因为白名单变宽）。
   ------------------------------------------------------------------ */
const SECRET_SPAN_RE = new RegExp(
  '<span\\s+class="secret-toggle"[^>]*>\\s*' +
  '<span\\s+class="secret-mask">([\\s\\S]*?)</span>\\s*' +
  '<span\\s+class="secret-value">([\\s\\S]*?)</span>\\s*' +
  '</span>', 'g')

/** 行内：`代码` **粗** *斜* ~~删~~ [文字](链接) —— 外加白名单 HTML */
function inlineMd(s) {
  const stash = []
  const hold = (html) => {
    stash.push(html)
    return `\u0001${stash.length - 1}\u0001`
  }

  let t = String(s ?? '')

  // 白名单 HTML 先摘出来（里面的文字单独转义，标签由我们重建）
  t = t.replace(SECRET_SPAN_RE, (_m, mask, val) => hold(
    '<span class="secret-toggle" tabindex="0" title="悬停或点按查看">' +
    `<span class="secret-mask">${escAll(mask)}</span>` +
    `<span class="secret-value">${escAll(val)}</span></span>`))
  t = t.replace(/<kbd>([\s\S]*?)<\/kbd>/gi, (_m, x) => hold(`<kbd>${escAll(x)}</kbd>`))
  t = t.replace(/<mark>([\s\S]*?)<\/mark>/gi, (_m, x) => hold(`<mark>${escAll(x)}</mark>`))
  t = t.replace(/<br\s*\/?>/gi, () => hold('<br>'))

  t = escAll(t)
  t = t.replace(/`([^`]+)`/g, (_m, c) => hold(`<code>${c}</code>`))  // 代码里的 * 不当强调
  t = t
    .replace(/\[([^\]]*)\]\(([^()\s]+)\)/g,
      (_m, txt, href) => `<a href="${safeUrl(href)}" target="_blank" rel="noopener noreferrer">${txt}</a>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
  return t.replace(/\u0001(\d+)\u0001/g, (_m, i) => stash[+i])
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

/**
 * Obsidian callout 渲染（规范 §3）
 *
 * 语法：`> [!type] 标题`，type 后面 + / - 表示可折叠。
 * 已知类型给对应颜色；未知类型按 note 处理（别丢内容）。
 * 没用过的类型降级成普通 note 卡片，而不是原样吐出 `[!xxx]`。
 */
const CALLOUT_TYPES = [
  'info', 'tip', 'warning', 'danger', 'example', 'question',
  'success', 'failure', 'note', 'quote', 'abstract', 'todo',
]
const CALLOUT_TITLE = {
  info: '信息', tip: '技巧', warning: '注意', danger: '危险',
  example: '示例', question: '疑问', success: '成功', failure: '失败',
  note: '笔记', quote: '引用', abstract: '摘要', todo: '待办',
}
const CALLOUT_ICON = {
  info: 'ℹ️', tip: '💡', warning: '⚠️', danger: '🚨', example: '📖',
  question: '❓', success: '✅', failure: '❌', note: '📝', quote: '❝',
  abstract: '📋', todo: '☑️',
}

function renderCallout(buf, hOffset = 2) {
  const first = (buf[0] || '').trim()
  const m = first.match(/^\[!(\w+)\]([+-]?)\s*(.*)$/)
  if (!m) return null
  const type = m[1].toLowerCase()
  if (!CALLOUT_TYPES.includes(type)) return null
  const fold = m[2]
  const title = m[3].trim() || CALLOUT_TITLE[type] || ''
  const rest = buf.slice(1).join('\n')

  const cls = ['md-callout', `md-callout-${type}`]
  if (fold) cls.push('is-foldable', fold === '-' ? 'is-open' : 'is-collapsed')

  // 标题要转义（以前直接拼原文 —— 一个 `> [!note] <img onerror>` 就能执行脚本）
  const head = `<div class="md-callout-title"><span class="md-callout-ico">${CALLOUT_ICON[type] || '📝'}</span><span class="md-callout-name">${inlineMd(title)}</span></div>`
  // 正文按 Markdown 递归渲染：规范里 callout 里放的是列表/加粗/表格，
  // 直接把原文塞进去的话，用户看到的是 `- **创建**: ...` 这种裸记号
  const body = rest.trim()
    ? `<div class="md-callout-body">${renderMarkdown(rest, {
        headingOffset: Math.min(hOffset + 1, 4),
      })}</div>`
    : ''
  return `<div class="${cls.join(' ')}">${head}${body}</div>`
}

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
    if (/^\s*<details\b/i.test(l)) return true
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

    // ---- 引用 / Obsidian callout ----
    //
    // callout 是《笔记 UI 排版规范》§3 的核心记号：
    // `> [!info] 标题` 渲染成带色条的卡片，而不是普通引用块。
    // 不支持的话，规范里写的一堆 `> [!warning]` 到了页面上全变成灰引用块，
    // 层次感就没了。
    if (/^\s*>\s?/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?\s?/, ''))
        i++
      }
      const callout = renderCallout(buf, hOffset)
      out.push(callout || `<blockquote>${buf.map(inlineMd).join('<br>')}</blockquote>`)
      continue
    }

    // ---- 折叠块 <details>（§8.2）----
    //
    // Obsidian 用原生 HTML 做折叠块，里面通常是日志/长配置。
    // 不认它的话，整个块会被当成普通段落，`<details>` 原样显示。
    if (/^\s*<details\b/i.test(line)) {
      const buf = []
      let depth = 1
      i++
      while (i < lines.length) {
        const l = lines[i]
        if (/^\s*<details\b/i.test(l)) depth++
        if (/^\s*<\/details>/i.test(l)) {
          depth--
          if (depth === 0) { i++; break }
        }
        buf.push(l)
        i++
      }
      const inner = buf.join('\n')
      const m = inner.match(/<summary>([\s\S]*?)<\/summary>/i)
      const summary = m ? m[1].trim() : '展开'
      const rest = m ? inner.replace(m[0], '') : inner
      out.push(
        `<details class="md-details"><summary>${inlineMd(summary)}</summary>` +
        renderMarkdown(rest, { headingOffset: Math.min(hOffset + 1, 4) }) +
        '</details>')
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

    // ---- 列表（按缩进分层）----
    //
    // 早先的实现遇到「标记符类型变了」就 break，把嵌套列表拆成了
    // 兄弟列表（`-` 里套 `1.` 会断成两个并列列表）。标准 Markdown 允许
    // 不同层级用不同标记，所以这里改成按**缩进**建树，标记符只决定
    // 这一层渲染成 <ul> 还是 <ol>。
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const raw = []
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/)
        if (!m) break
        raw.push({
          indent: m[1].replace(/\t/g, '  ').length,
          ordered: /^\d+[.)]$/.test(m[2]),
          text: inlineMd(m[3]),
          raw: m[3],
        })
        i++
      }
      out.push(renderListTree(raw))
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
