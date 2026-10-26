// Markdown 渲染断言：数据中心预览 .md 的排版基础
// 覆盖 utils/md.js 的两个对外能力：renderMarkdown / splitFrontmatter
import { renderMarkdown, splitFrontmatter, escapeHtml, highlightHtml } from '../src/utils/md.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  ' + detail : ''}`)
}
const has = (html, s) => html.includes(s)

// ---------- 标题层级 ----------
{
  const src = '# 一级\n\n## 二级\n\n### 三级'
  const chat = renderMarkdown(src)                            // AI 气泡：标题压到 h3 起
  const doc = renderMarkdown(src, { headingOffset: 0 })       // 文档：保留原层级
  assert('chat 变体把 h1 压成 h3', has(chat, '<h3>一级</h3>'))
  assert('doc 变体保留 h1', has(doc, '<h1>一级</h1>'))
  assert('doc 变体保留 h2', has(doc, '<h2>二级</h2>'))
  assert('doc 变体保留 h3', has(doc, '<h3>三级</h3>'))
}

// ---------- 块级元素 ----------
{
  const src = '> 引用\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- 项1\n- 项2\n\n```js\ncode()\n```'
  const html = renderMarkdown(src, { headingOffset: 0 })
  assert('渲染 blockquote', has(html, '<blockquote>引用</blockquote>'))
  assert('渲染表格', has(html, '<table>') && has(html, '<th'))
  assert('表格有横向滚动容器', has(html, 'md-table-wrap'))
  assert('渲染列表', has(html, '<ul><li>项1</li><li>项2</li></ul>'))
  assert('渲染代码块', has(html, '<pre class="md-pre"'))
}

// ---------- XSS：所有文本必须转义 ----------
{
  const html = renderMarkdown('<img src=x onerror=alert(1)>', { headingOffset: 0 })
  assert('不生成真实 img 标签', !has(html, '<img'))
  assert('尖括号被转义', has(html, '&lt;img'))
  const link = renderMarkdown('[点我](javascript:alert)', { headingOffset: 0 })
  assert('javascript: 协议被拦', !has(link, 'href="javascript:'))
  assert('危险链接降级为 #', has(link, 'href="#"'))
  const link2 = renderMarkdown('[点我](javascript:alert(1))', { headingOffset: 0 })
  assert('含括号的 js 链接不生成 a 标签', !has(link2, '<a '))
}

// ---------- frontmatter ----------
{
  const src = '---\ntitle: A\ntags:\n  - x\n  - y\ncreated: 2026-01-01\n---\n\n# 正文'
  const fm = splitFrontmatter(src)
  assert('识别出 frontmatter', !!fm)
  assert('frontmatter 正文被剥离', fm.body.trim() === '# 正文')

  const html = renderMarkdown(src, { headingOffset: 0, frontmatter: true })
  assert('渲染 frontmatter 容器', has(html, 'md-frontmatter'))
  assert('渲染 title 属性', has(html, 'md-fm-key">title'))
  assert('列表渲染成标签', has(html, 'md-fm-chip">x') && has(html, 'md-fm-chip">y'))
  assert('frontmatter 不再裸在正文里', !has(html, '<p>title: A'))
  assert('正文正常渲染', has(html, '<h1>正文</h1>'))
}

// ---------- frontmatter 误判防护 ----------
{
  const cases = [
    ['无 frontmatter', '# H\n\ntext', false],
    ['开头是分隔线', '---\n\ntext\n\n---\n\nmore', false],
    ['开头分隔线无闭合', '---\n\n# H\n\ntext', false],
    ['空 frontmatter', '---\n---\n\n# H', false],
    ['块内含空行', '---\ntitle: A\n\nother: B\n---\n\n# H', false],
  ]
  for (const [name, src, expect] of cases) {
    assert(`${name} → 不当作 frontmatter`, splitFrontmatter(src) === null === !expect)
  }
}

// ---------- frontmatter 内容不许被吞 ----------
{
  const src = '---\njust a line\n---\n\n# H'
  const html = renderMarkdown(src, { headingOffset: 0, frontmatter: true })
  assert('无法解析的行不丢内容', has(html, 'just a line'))
}

// ---------- chat 变体不拆 frontmatter ----------
{
  const src = '---\ntitle: A\n---\n\ntext'
  const html = renderMarkdown(src)
  assert('chat 变体不拆 frontmatter', !has(html, 'md-frontmatter'))
}

// ---------- 嵌套列表：按缩进分层，标记符换了也不该断 ----------
{
  // 无序里套有序：早先的实现遇到标记符变化就 break，
  // 会拆成 `<ul>…</ul><ol>…</ol>` 两个并列列表
  const src = '- 一级 A\n  1. 二级 1\n  2. 二级 2\n- 一级 B'
  const html = renderMarkdown(src, { headingOffset: 0 })
  assert('嵌套列表：ol 嵌在 ul 的 li 里',
    has(html, '<ul><li>一级 A<ol>') && has(html, '</ol></li>'))
  assert('嵌套列表：二级项带 lvl-2', has(html, 'class="lvl-2"'))
  assert('嵌套列表：末项没被拆出去', has(html, '<li>一级 B</li>'))

  // 有序里套无序
  const src2 = '1. 一级 A\n   - 二级 X\n2. 一级 B'
  const html2 = renderMarkdown(src2, { headingOffset: 0 })
  assert('嵌套列表：ul 嵌在 ol 的 li 里',
    has(html2, '<ol><li>一级 A<ul>') && has(html2, '</ul></li>'))
  assert('嵌套列表：有序里的无序项带 lvl-2', has(html2, 'class="lvl-2"'))

  // 同层换标记符 → 开新列表（Markdown 常规行为）
  const src3 = '- 甲\n1. 乙'
  const html3 = renderMarkdown(src3, { headingOffset: 0 })
  assert('同层换标记符开新列表',
    has(html3, '<ul><li>甲</li></ul><ol><li>乙</li></ol>'))

  // 三层
  const src4 = '- L1\n  - L2\n    - L3'
  const html4 = renderMarkdown(src4, { headingOffset: 0 })
  assert('三层嵌套出现 lvl-3', has(html4, 'class="lvl-3"'))
}

// ---------- 协议相对 URL 必须被拒 ----------
{
  const html = renderMarkdown('[点我](//evil.example.com/x)', { headingOffset: 0 })
  assert('协议相对 URL 被拒（不跳外站）', !has(html, 'href="//evil.example.com/x"'))
  assert('协议相对 URL 退化成 #', has(html, 'href="#"'))

  const html2 = renderMarkdown('[站内](/docs/1)', { headingOffset: 0 })
  assert('站内绝对路径仍然放行', has(html2, 'href="/docs/1"'))

  const html3 = renderMarkdown('[外链](https://example.com/a)', { headingOffset: 0 })
  assert('http(s) 仍然放行', has(html3, 'href="https://example.com/a"'))
}

// ---------- 搜索结果高亮：必须转义（P1-4 存型 XSS）----------
{
  const evil = '<img src=x onerror="window.__XSS_FIRED__=1">'
  const html = highlightHtml(evil, 'img')
  assert('高亮：原始标签被转义', !has(html, '<img'))
  assert('高亮：命中段包在 mark 里', has(html, '<mark>img</mark>'))
  assert('高亮：onerror 不会变成真属性', !has(html, 'onerror="window'))

  // 普通高亮
  const html2 = highlightHtml('zebra 手册', 'zebra')
  assert('高亮：命中段被 mark 包住', has(html2, '<mark>zebra</mark>'))
  assert('高亮：其余部分原样', has(html2, '手册'))

  // 关键词里的 $ 不会被当成替换符
  const html3 = highlightHtml('价格 $100', '$1')
  assert('高亮：$1 不被当替换符', has(html3, '<mark>$1</mark>'))

  // 没有关键词 → 全部转义
  const html4 = highlightHtml(evil, '')
  assert('高亮：无关键词时仍转义', !has(html4, '<img'))
}

// ---------- escapeHtml 本身 ----------
{
  assert('escapeHtml 转义尖括号', escapeHtml('<b>') === '&lt;b&gt;')
  assert('escapeHtml 转义引号', escapeHtml('"x"') === '&quot;x&quot;')
  assert('escapeHtml 处理 null', escapeHtml(null) === '')
}

console.log(failed ? `\n❌ ${failed} 项失败` : '\n✅ 全部通过')
process.exit(failed ? 1 : 0)
