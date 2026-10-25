// Markdown 渲染断言：数据中心预览 .md 的排版基础
// 覆盖 utils/md.js 的两个对外能力：renderMarkdown / splitFrontmatter
import { renderMarkdown, splitFrontmatter } from '../src/utils/md.js'

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

console.log(failed ? `\n❌ ${failed} 项失败` : '\n✅ 全部通过')
process.exit(failed ? 1 : 0)
