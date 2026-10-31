/**
 * 编辑器实时高亮
 *
 * 为什么单独写一个（不直接用 renderMarkdown）：
 * 编辑区的「高亮层」是盖在 textarea 上面的**透明**层 ——
 * 它的每一个字都要跟 textarea 里的字**逐字对齐**。
 * 而 renderMarkdown 产出的是块级 HTML（<h1>、<pre>、<ul>…），
 * 行高、内外边距一有出入就错位，光标和文字就对不上了。
 *
 * 所以这里做的是「**行内**高亮」：输出仍然是纯文本的行，
 * 只把标题、代码块、列表符号、双链这些**用 span 包起来**，
 * 字号行高与 textarea 完全一致（CSS 里两者共用同一套排版规则）。
 *
 * 规范依据：《笔记 UI 排版规范》§1 标题层级 / §6 代码块 / §3.1 callout
 */

/** 一行是不是代码块围栏的开始 */
const FENCE = /^\s*(```|~~~)(.*)$/

/** 行内代码 `xxx` */
const INLINE_CODE = /(`[^`\n]+`)/g

/** 双链 [[xxx]] */
const WIKILINK = /(\[\[[^\[\]\n]+?\]\])/g

/** 强调 **粗体** / *斜体* */
const EMPHASIS = /(\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_)/g

/** 标题 # ## ### */
const HEADING = /^(#{1,6})\s+/

/** 任务列表 - [ ] / - [x] */
const TASK = /^(\s*[-*+]\s+\[([ xX~\-/])\]\s*)/

/** 引用 / callout */
const CALLOUT = /^(\s*>\s*(\[![^\]]+\][+-]?)?)/

/** 无序列表符号 */
const BULLET = /^(\s*)([-*+])\s+/

/** 行内链接 */
const LINK = /(\[[^\]\n]*\]\([^)\n]*\))/

/**
 * 给一段纯文本生成高亮 HTML
 *
 * @param {string} text 原始文本（未经转义）
 * @param {Function} escapeHtml 转义函数
 * @returns {string} 高亮后的 HTML（行与行之间用 \n 分隔，交给 CSS 排版）
 */
export function highlightEditorText(text, escapeHtml) {
  const esc = escapeHtml || ((s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])))
  const lines = String(text || '').split('\n')
  const out = []
  let inCode = false

  for (const raw of lines) {
    // ---- 代码块围栏 ----
    const fence = FENCE.exec(raw)
    if (fence) {
      inCode = !inCode
      const lang = fence[2].trim()
      out.push(
        `<span class="ed-fence">${esc(fence[1])}${lang ? `<span class="ed-lang">${esc(lang)}</span>` : ''}</span>`
      )
      continue
    }

    // ---- 代码块内部：整行当代码 ----
    if (inCode) {
      out.push(`<span class="ed-code-line">${esc(raw)}</span>`)
      continue
    }

    // ---- 普通行：行内标记 ----
    let line = esc(raw)

    // 行内代码要先占住，避免里面的 * _ 被当强调
    const stash = []
    line = line.replace(INLINE_CODE, (m) => {
      stash.push(`<span class="ed-inline-code">${m}</span>`)
      return `\u0000${stash.length - 1}\u0000`
    })
    line = line.replace(WIKILINK, (m) => `<span class="ed-wikilink">${m}</span>`)
    line = line.replace(EMPHASIS, (m) => `<span class="ed-em">${m}</span>`)
    line = line.replace(LINK, (m) => `<span class="ed-link">${m}</span>`)
    // 还原行内代码
    line = line.replace(/\u0000(\d+)\u0000/g, (_m, i) => stash[Number(i)])

    // 行首标记（要在转义之后处理，所以单独用 raw 判断）
    if (HEADING.test(raw)) {
      const m = HEADING.exec(raw)
      line = line.replace(/^(\s*)(#{1,6})(\s+)/, (_m, sp, hashes, tail) =>
        `${sp}<span class="ed-h ed-h${hashes.length}">${hashes}</span>${tail}`)
    } else if (CALLOUT.test(raw)) {
      const m = CALLOUT.exec(raw)
      // callout 标记本身要**替换掉**，不能只是加一段 ——
      // 否则原文的 [!warning] 还在，变成「[!warning][!warning]」
      const tag = m[2] ? `<span class="ed-callout-tag">${esc(m[2])}</span>` : ''
      // ⚠️ 匹配要打在**转义后**的字符串上：'>' 已经变成 '&gt;'
      // （之前拿 raw 的正则去改转义后的行，callout 永远匹配不上）
      line = line.replace(/^(\s*&gt;\s*)(?:\[[^\]]+\][+-]?)?/, '$1' + tag)
    } else if (TASK.test(raw)) {
      const m = TASK.exec(raw)
      const done = /[xX]/.test(m[2])
      const sym = { ' ': '☐', x: '☑', X: '☑', '~': '◐', '-': '◐', '/': '◐' }[m[2]] || '☐'
      line = line.replace(/^(\s*[-*+]\s+\[)([ xX~\-/])(\]\s*)/,
        `$1<span class="ed-task${done ? ' is-done' : ''}">${sym}</span>$3`)
    } else if (BULLET.test(raw)) {
      const m = BULLET.exec(raw)
      line = line.replace(/^(\s*)([-*+])(\s+)/,
        '$1<span class="ed-bullet">\u2022</span>$3')
    }

    out.push(line)
  }

  return out.join('\n')
}
