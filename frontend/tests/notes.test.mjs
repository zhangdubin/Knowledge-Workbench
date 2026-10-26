// 笔记界面重做相关的纯函数断言
// 覆盖 utils/notes.js：标题兜底、首行提标题、标签解析/去重、
// Markdown 剥离、相对时间、双链解析与正文渲染
import {
  stripMarkdown, collapseWhitespace, firstLineTitle, noteTitle, noteSnippet,
  normalizeTags, parseTags, matchTags, relativeTime,
  extractWikilinks, extractHashtags, renderNoteHtml,
} from '../src/utils/notes.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'}${name}${detail ? '  ' + detail : ''}`)
}
const has = (s, sub) => String(s).includes(sub)

// ---------- stripMarkdown：列表摘要必须是纯文本 ----------
{
  const src = '## 标题\n\n这是 **粗体** 和 `代码`，还有 [链接](http://x.com) 与 [[某笔记]]。'
  const out = stripMarkdown(src)
  assert('去掉标题井号', !has(out, '#'), out)
  assert('去掉粗体星号', has(out, '粗体') && !has(out, '**'), out)
  assert('行内代码只留文字', has(out, '代码') && !has(out, '`'), out)
  assert('链接只留锚文本', has(out, '链接') && !has(out, 'http'), out)
  assert('双链只留标题', has(out, '某笔记') && !has(out, '[['), out)
}

// ---------- stripMarkdown：表格 / 列表 / 引用 ----------
{
  assert('表格分隔行被清掉', !has(stripMarkdown('| a | b |\n|---|---|\n| 1 | 2 |'), '---'))
  const li = stripMarkdown('- 项一\n- 项二')
  assert('列表符号被清掉', !has(li, '- 项') && has(li, '项一') && has(li, '项二'), JSON.stringify(li))
  assert('引用符号被清掉', !has(stripMarkdown('> 引用内容'), '>'))
}

// ---------- collapseWhitespace ----------
{
  assert('多行折叠成单行', collapseWhitespace('a\n\n  b   c ') === 'a b c')
}

// ---------- firstLineTitle：Obsidian 的「首行即标题」 ----------
{
  assert('取第一行', firstLineTitle('我的笔记标题\n第二行') === '我的笔记标题')
  assert('跳过空行', firstLineTitle('\n\n真正的标题') === '真正的标题')
  assert('剥掉标题井号', firstLineTitle('## 带井号的标题') === '带井号的标题')
  assert('剥掉 Markdown 标记', firstLineTitle('**加粗的标题**') === '加粗的标题')
  assert('跳过 frontmatter', firstLineTitle('---\ntitle: A\n---\n正文首行') === '正文首行', firstLineTitle('---\ntitle: A\n---\n正文首行'))
  assert('空内容返回空串', firstLineTitle('') === '' && firstLineTitle('   \n  ') === '')
}

// ---------- noteTitle：显式标题 > 首行 > 未命名 ----------
{
  assert('显式标题优先', noteTitle({ data: { title: '显式标题', content: '正文首行' } }) === '显式标题')
  assert('没标题时用首行', noteTitle({ data: { title: '', content: '正文首行' } }) === '正文首行')
  assert('都没有时兜底带 id', noteTitle({ data: { title: '', content: '' } }, 42) === '未命名笔记 #42')
  assert('都没有时兜底不带 id', noteTitle({ data: {} }) === '未命名笔记')
}

// ---------- noteSnippet ----------
{
  assert('空内容返回空串', noteSnippet('') === '')
  const long = 'x'.repeat(300)
  const s = noteSnippet(long, 50)
  assert('超长截断并加省略号', s.length === 51 && s.endsWith('…'), String(s.length))
  assert('摘要不含 Markdown 标记', !has(noteSnippet('## 标题\n内容'), '#'))
}

// ---------- normalizeTags：去 #、去空白、大小写不敏感去重 ----------
{
  assert('去前缀井号', JSON.stringify(normalizeTags(['#设计', ' 架构 '])) === '["设计","架构"]')
  assert('大小写不敏感去重', normalizeTags(['Design', 'design', 'Design']).length === 1)
  assert('丢掉空标签', normalizeTags(['', '  ', 'ok']).length === 1)
  assert('非数组输入不炸', JSON.stringify(normalizeTags(null)) === '[]')
}

// ---------- parseTags：逗号 / 中文逗号 / 顿号分隔 ----------
{
  assert('逗号分隔', JSON.stringify(parseTags('架构,设计')) === '["架构","设计"]')
  assert('中文逗号与顿号', JSON.stringify(parseTags('架构，设计、测试')) === '["架构","设计","测试"]')
  assert('输入自带井号也能解析', JSON.stringify(parseTags('#架构')) === '["架构"]')
}

// ---------- matchTags：# 候选 ----------
{
  const all = ['架构', '设计', 'Design']
  assert('空查询返回全部候选', matchTags('', all).length === 3)
  assert('井号前缀被忽略', matchTags('#架', all)[0] === '架构')
  assert('按包含匹配', matchTags('de', all)[0] === 'Design')
  assert('大小写不敏感', matchTags('DESIGN', all)[0] === 'Design')
  assert('候选去重', matchTags('', ['a', 'A']).length === 1)
  assert('结果有上限', matchTags('', Array.from({ length: 50 }, (_, i) => 't' + i), 8).length === 8)
}

// ---------- relativeTime ----------
{
  const now = new Date('2026-10-26T12:00:00').getTime()
  assert('一分钟内是「刚刚」', relativeTime(new Date(now - 30 * 1000), now) === '刚刚')
  assert('分钟级', relativeTime(new Date(now - 5 * 60000), now) === '5 分钟前')
  assert('小时级', relativeTime(new Date(now - 3 * 3600000), now) === '3 小时前')
  assert('昨天带时刻', relativeTime(new Date(now - 26 * 3600000), now).startsWith('昨天'))
  assert('一周内是天数', relativeTime(new Date(now - 3 * 86400000), now) === '3 天前')
  assert('非法时间返回空串', relativeTime('not-a-date', now) === '')
  assert('空值返回空串', relativeTime('', now) === '')
}

// ---------- extractWikilinks ----------
{
  const out = extractWikilinks('看 [[架构]] 和 [[设计]]，还有 [[架构]] 与 [[别名|真名]]')
  assert('双链去重且保序', JSON.stringify(out) === '["架构","设计","别名"]', JSON.stringify(out))
}

// ---------- extractHashtags ----------
{
  const out = extractHashtags('正文 #架构 #设计/评审 结束')
  assert('识别行内标签', JSON.stringify(out) === '["架构","设计/评审"]', JSON.stringify(out))
  assert('不把 C# 当标签', extractHashtags('C# 和 F#').length === 0)
}

// ---------- renderNoteHtml：双链渲染 + 安全 ----------
{
  const html = renderNoteHtml('看 [[架构]] 这个')
  assert('双链变成锚点', has(html, 'class="note-wikilink"'))
  assert('锚点带 data-wikilink', has(html, 'data-wikilink="架构"'))
  assert('正文文字保留', has(html, '看'))

  const code = renderNoteHtml('```\n[[不是链接]]\n```')
  assert('代码块里的方括号不变成链接', !has(code, 'note-wikilink'), code)

  const xss = renderNoteHtml('<img src=x onerror=alert(1)>')
  assert('HTML 被转义', !has(xss, '<img') && has(xss, '&lt;img'))
}

console.log(failed ? `\n❌ ${failed} 项失败` : '\n✅ 全部通过')
process.exit(failed ? 1 : 0)
