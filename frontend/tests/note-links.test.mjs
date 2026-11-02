// 笔记「双链 + 关联记录」的纯函数断言
//
// 为什么这些逻辑要能被单测钉住：
//   双链是「关系网络」的骨架 —— 正向/反向列错一条、重复列一条，
//   用户看到的图谱就少一条边。现在这些判断写在 .vue 里，
//   改起来只能靠人肉点页面，好一通坏一通。
//
// 测法：把 NoteDetail.vue 里的纯函数块（普通 <script> 块，没有 Vue 依赖）
//   抽出来 eval —— 逻辑只有一份，测的就是页面上真跑的那份。
//   顺带用源码断言钉住两条「不能再犯」的规矩：
//     · 编辑器高度只由 CSS 变量驱动（不能给 textarea 写死 inline height）
//     · 双链解析只用 resolveWikilinkTarget（别再直接查标题索引）
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const NOTE_DETAIL = path.join(HERE, '../src/views/NoteDetail.vue')
const NOTE_EDITOR = path.join(HERE, '../src/components/NoteEditor.vue')

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  ' + detail : ''}`)
}
const has = (s, sub) => String(s).includes(sub)

const detailSrc = fs.readFileSync(NOTE_DETAIL, 'utf8')
const editorSrc = fs.readFileSync(NOTE_EDITOR, 'utf8')

// ---------- 抽出纯函数块 ----------
const block = detailSrc.match(/<script>\s*([\s\S]*?)<\/script>/)
assert('NoteDetail.vue 里有普通 <script> 块（纯函数放这里才能被单测）', !!block)
if (!block) {
  console.log('\n纯函数块缺失，无法继续验证')
  process.exit(1)
}
// export 关键字在 new Function 的函数体里是语法错误，先剥掉
const helpers = new Function(
  block[1].replace(/^\s*export\s+/gm, '') +
  '\nreturn { dedupeLinks, resolveWikilinkTarget, wikilinkExists, recordLabel }',
)()

const { dedupeLinks, resolveWikilinkTarget, wikilinkExists, recordLabel } = helpers

// ---------- dedupeLinks：同一目标只列一次 ----------
{
  const raw = [
    { target_record_id: 27, link_title: '数据模型设计' },
    { target_record_id: 27, link_title: '数据模型设计' },
    { target_record_id: 29, link_title: '关联与图谱' },
  ]
  const out = dedupeLinks(raw, 'target_record_id')
  assert('同一目标只保留一条', out.length === 2, JSON.stringify(out.map((o) => o.target_record_id)))
  assert('重复出现被记成次数', out[0].count === 2, 'count=' + out[0].count)
  assert('不同的目标都在', out.some((o) => o.target_record_id === 29))
  assert('没动原始数据', raw.length === 3, 'raw=' + raw.length)
  assert('空列表不炸', dedupeLinks([], 'target_record_id').length === 0)
  assert('空指针不炸', dedupeLinks(null, 'target_record_id').length === 0)
  assert('没有 id 的脏数据被丢掉', dedupeLinks([{ link_title: 'x' }], 'target_record_id').length === 0)
}

// ---------- resolveWikilinkTarget：先问后端的正链表 ----------
{
  const outgoing = [
    { target_record_id: 27, link_title: '数据模型设计' },
    { target_record_id: 35, link_title: '双向链接', placeholder: true },
  ]
  const titleIndex = { '数据模型设计': 27, '关联与图谱': 29 }
  assert('正链表里能解析', resolveWikilinkTarget('数据模型设计', outgoing, titleIndex) === 27)
  assert('占位笔记也能解析（它是真实存在的空壳笔记）',
    resolveWikilinkTarget('双向链接', outgoing, titleIndex) === 35)
  assert('回退到标题索引', resolveWikilinkTarget('关联与图谱', outgoing, titleIndex) === 29)
  assert('不区分大小写', resolveWikilinkTarget('  数据模型设计  ', outgoing, titleIndex) === 27)
  assert('正文里没有的标题返回 null',
    resolveWikilinkTarget('不存在的笔记', outgoing, titleIndex) === null)
  assert('空标题返回 null', resolveWikilinkTarget('', outgoing, titleIndex) === null)
  assert('null 也不炸', resolveWikilinkTarget(null, null, null) === null)
  // 改名之后：旧标题不在索引里，但正链表还指着那篇笔记 ——
  // 这时点旧双链应该跳过去，而不是报「没有这篇」
  const renamed = [{ target_record_id: 42, link_title: '旧标题' }]
  assert('改名后旧双链仍然能跳（靠正链表）',
    resolveWikilinkTarget('旧标题', renamed, {}) === 42)
}

// ---------- wikilinkExists：判断口径必须和点击口径一致 ----------
{
  const outgoing = [{ target_record_id: 27, link_title: '数据模型设计' }]
  assert('存在的算存在', wikilinkExists('数据模型设计', outgoing, {}) === true)
  assert('不存在的算不存在', wikilinkExists('查无此篇', outgoing, {}) === false)
}

// ---------- recordLabel：各模型字段不统一 ----------
{
  assert('优先 name', recordLabel({ id: 1, data: { name: '客户A', title: 'T' } }) === '客户A')
  assert('其次 title', recordLabel({ id: 1, data: { title: '标题' } }) === '标题')
  assert('再次 code', recordLabel({ id: 1, data: { code: 'C-1' } }) === 'C-1')
  assert('最后用 id 兜底', recordLabel({ id: 9, data: {} }) === '#9')
  assert('空对象不炸', recordLabel(null) === '#0')
}

// ---------- 源码断言：页面上的用法不能走偏 ----------
{
  assert('正链按目标 id 去重', has(detailSrc, "dedupeLinks(await Api.getNoteOutgoing(noteId.value), 'target_record_id')"))
  assert('反链按来源 id 去重', has(detailSrc, "dedupeLinks(await Api.getNoteBacklinks(noteId.value), 'source_record_id')"))
  assert('点击双链走 resolveWikilinkTarget', has(detailSrc, 'resolveWikilinkTarget(a.dataset?.wikilink'))
  assert('弱化显示走 wikilinkExists', has(detailSrc, 'wikilinkExists(a.dataset?.wikilink'))
  assert('弱化与点击看的是同一份正链表', has(detailSrc, 'watch([renderedContent, titleIndex, outgoing]'))
  assert('笔记侧能主动关联业务记录', has(detailSrc, 'Api.linkKnowledge(rec.id, noteId.value)'))
  assert('笔记侧能取消关联', has(detailSrc, 'Api.unlinkKnowledge(r.record_id, noteId.value)'))
  assert('关联后立刻刷新列表', has(detailSrc, 'await loadRelatedRecords()'))
  assert('笔记模型被排除在候选之外（笔记之间走双链）',
    has(detailSrc, "filter((t) => t && t.key !== 'note')"))
}

// ---------- 源码断言：编辑器高度只由一个来源驱动 ----------
{
  assert('没有把计算出的高度写死进 textarea 的 inline style',
    !has(editorSrc, 'ta.style.height = `${next}px`'))
  assert('高度上限跟着可视区走（不是写死的 620）',
    has(editorSrc, 'window.innerHeight') && has(editorSrc, 'maxAutoHeight'))
  assert('textarea 与高亮层都靠 inset:0 填满容器',
    /\.composer-editor,\s*\n\.composer-overlay\s*\{[^}]*inset:\s*0/.test(editorSrc))
  assert('容器是弹性列（工具条不会把编辑区顶出框外）',
    /\.composer-body\s*\{[^}]*display:\s*flex/.test(editorSrc))
}

console.log(failed ? `\n❌ ${failed} 项未通过` : '\n✅ 全部通过')
if (failed) process.exit(1)
