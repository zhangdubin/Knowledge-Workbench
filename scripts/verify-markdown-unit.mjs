/**
 * Markdown 渲染器单元验证（utils/md.js）
 *
 * 项目没装 vitest，而 md.js 是 ESM（frontend/package.json 没有 "type": "module"，
 * 直接 import 会被 Node 当成 CJS 而报错）。这里的做法是：读源码 → 去掉 `export `
 * → 用 new Function 求值拿到函数。改动 md.js 的导出形式时记得同步这里。
 *
 *   node scripts/verify-markdown-unit.mjs
 */
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SRC = fs.readFileSync(path.join(ROOT, 'frontend/src/utils/md.js'), 'utf8')
  .replace(/^export /gm, '')
const { renderMarkdown } = new Function(`${SRC}; return { renderMarkdown }`)()

let pass = 0
const fails = []
const ok = (cond, label, extra) => {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fails.push(label); console.log(`  ✗ ${label}${extra !== undefined ? ' → ' + extra : ''}`) }
}

// 用户反馈「不易读」的那条回答，原样搬进来当回归样本
const REPORTED = `系统里共有 **9 个数据模型**：

| 模型 | 应用 | 字段数 | 记录数 | 主要字段 |
|------|------|--------|--------|----------|
| 客户 | sales | 8 | 3 | 名称、联系人、电话、邮箱、级别、行业 |
| 商机 | sales | 8 | 2 | 商机名、客户、预期金额、阶段、负责人 |
| 订单 | sales | 7 | 0 | 订单号、客户、来源商机、金额、状态 |
| 笔记 | knowledge | 4 | 11 | 标题、内容、标签、父笔记（双链） |

如果想了解某个模型的详细字段定义，随时告诉我。`

console.log('\n== 表格（用户反馈的那条回答）==')
{
  const h = renderMarkdown(REPORTED)
  ok(h.includes('<div class="md-table-wrap">'), '表格包在可横向滚动的容器里')
  ok(h.includes('<table><thead><tr>'), '生成 thead')
  const ths = [...h.matchAll(/<th class="[^"]*">([^<]*)<\/th>/g)].map(m => m[1])
  ok(ths.join(',') === '模型,应用,字段数,记录数,主要字段', '5 个表头按序解析', ths.join(','))
  const rows = (h.match(/<tbody>([\s\S]*)<\/tbody>/) || [, ''])[1]
    .split('<tr>').filter(Boolean)
  ok(rows.length === 4, `4 行数据全部保留（首行没被当成分隔行吞掉）`, rows.length)
  ok(rows[0].includes('客户') && rows[0].includes('名称、联系人'), '第一行数据完整')
  ok((h.match(/class="num"/g) || []).length >= 8, '字段数/记录数两列标了 num（右对齐）')
  ok(!/<th class="[^"]*num[^"]*">(模型|应用|主要字段)<\/th>/.test(h), '文本列没有被误判成数字列')
  ok(h.includes('<strong>9 个数据模型</strong>'), '行内加粗生效')
  ok(!h.includes('|---'), '没有残留分隔行')
  ok(!h.includes('|'), '没有残留管道符')
}

console.log('\n== 列表 / 标题 / 引用 / 代码 ==')
{
  const h = renderMarkdown('# 大标题\n\n### 小标题\n\n- 一级\n  - 二级 `code`\n- **粗**\n\n1. 甲\n2. 乙\n\n> 引用一行\n\n```json\n{"a":1}\n```\n\n---\n\n段一\n段二')
  ok(h.includes('<h3>大标题</h3>'), 'h1 压到 h3（气泡里不需要巨无霸标题）')
  ok(h.includes('<h5>小标题</h5>'), 'h3 压到 h5')
  ok(h.includes('<li class="lvl-2">二级 <code>code</code></li>'), '缩进列表 → 二级 li + 行内代码')
  ok(h.includes('<ol><li>甲</li><li>乙</li></ol>'), '有序列表')
  ok(h.includes('<blockquote>引用一行</blockquote>'), '引用块')
  ok(h.includes('<pre class="md-pre" data-lang="json">'), '围栏代码块带语言标记')
  ok(h.includes('<hr>'), '分隔线')
  ok(h.includes('段一<br>段二'), '段落内软换行保留')
}

console.log('\n== 安全：先转义再解析 ==')
{
  const h = renderMarkdown('<img src=x onerror=alert(1)> 与 <script>alert(2)</script>')
  ok(!h.includes('<img') && !h.includes('<script'), 'HTML 标签被转义，不会执行')
  ok(h.includes('&lt;script&gt;'), '转义结果可见')

  const h2 = renderMarkdown('[点我](javascript:alert(1))')
  ok(!/href="javascript:/i.test(h2), 'javascript: 协议链接被挡掉')
  ok(!/<a /.test(h2), '危险链接干脆不生成 <a>，只留纯文本')
  ok(!/href="[^"]*"/i.test(renderMarkdown('[x](data:text/html,<svg onload=alert(1)>)')), 'data: 协议也进不了 href')
  const h3 = renderMarkdown('[官网](https://example.com/a?b=1)')
  ok(h3.includes('<a href="https://example.com/a?b=1"'), '正常 https 链接保留')

  const h4 = renderMarkdown('| a | b |\n|---|---|\n| "<b>x</b>" | 2 |')
  ok(!h4.includes('<b>x</b>') && h4.includes('&lt;b&gt;x&lt;/b&gt;'), '表格单元格里的 HTML 同样被转义')
}

console.log('\n== 边界 ==')
{
  ok(renderMarkdown('') === '', '空字符串安全')
  ok(renderMarkdown(null).includes('<p>') === false, 'null 不炸')
  const h = renderMarkdown('单行没有换行')
  ok(h === '<p>单行没有换行</p>', '单段裸文本')
  const h2 = renderMarkdown('| 只有表头 | 没有分隔 |\n不是表格')
  ok(!h2.includes('<table>'), '缺分隔行的伪表格不当表格渲染')
}

console.log(`\n==== 结果：${pass} 通过 / ${fails.length} 失败 ====`)
if (fails.length) { fails.forEach(f => console.log('  未通过：' + f)); process.exit(1) }
