// 项目文件预览 · 懒加载正文的回归断言
//
// 背景（这个 bug 的来龙去脉）：
//   后端的列表接口 GET /api/dev/projects/{id} **刻意不带正文**
//   （一个项目几十个文件、单个几 KB 到几十 KB，全塞进去列表接口就重了），
//   而预览区原来渲染的是 `current?.content || '（这个文件没有内容）'`，
//   pick() 又只把列表里的那一项赋给 current —— 从不去单条接口取正文。
//   于是 current.content 恒为 undefined，
//   几百行的源码在界面上永远显示「（这个文件没有内容）」，
//   用户只会得出「模型没生成」的结论，
//   而内容其实好好地躺在库里 —— 是**显示链路断了**，不是没生成。
//
// 这里守住三件事：
//   1) 「没取到」与「文件确实是空的」必须分开说（原来用一个 || 判成了一件事）；
//   2) 取失败要如实显示后端的错误，不能再拿「没有内容」冒充；
//   3) 慢请求回来时不能把上一个文件的正文盖到当前文件上（竞态）。
import {
  PREVIEW_IDLE, PREVIEW_LOADING, PREVIEW_READY, PREVIEW_EMPTY, PREVIEW_ERROR,
  unwrapArtifactContent, previewView, previewErrorText,
  hasArtifactContent, contentSizeMatches, byteLength,
  nextRequestSeq, isStaleSeq,
} from '../src/utils/dev.js'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p) => readFileSync(join(ROOT, p), 'utf8')

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log((ok ? '✅' : '❌') + ' ' + name + (detail ? '  ' + detail : ''))
}

/* ---------- 取正文：三态，不能只有「有/无」 ---------- */
{
  // 取到了
  const got = unwrapArtifactContent({ artifact: { id: 11, content: 'print(1)\n' } })
  assert('取到正文时状态是 ready', got.status === PREVIEW_READY, 'status=' + got.status)
  assert('取到的正文原样带出来', got.content === 'print(1)\n')

  // 文件本来就是空的（字段在，但正文是空串）
  const empty = unwrapArtifactContent({ artifact: { id: 12, content: '' } })
  assert('空文件是 empty 不是 error', empty.status === PREVIEW_EMPTY, 'status=' + empty.status)
  assert('空文件的正文是空串', empty.content === '')

  // 列的 content 是 NULL：也是空文件
  const nulled = unwrapArtifactContent({ artifact: { id: 13, content: null } })
  assert('content 为 null 也算空文件', nulled.status === PREVIEW_EMPTY)

  // ⚠️ 关键回归：字段根本不存在 = **没取到**，绝不能当成空文件
  const missing = unwrapArtifactContent({ artifact: { id: 14 } })
  assert('没有 content 字段是 error 而不是 empty',
    missing.status === PREVIEW_ERROR, 'status=' + missing.status)
  assert('没有 content 字段时正文为空', missing.content === '')

  // 整个返回都不对
  assert('空返回是 error', unwrapArtifactContent(null).status === PREVIEW_ERROR)
  assert('没有 artifact 的返回是 error',
    unwrapArtifactContent({}).status === PREVIEW_ERROR)
}

/* ---------- 预览区显示什么 ---------- */
{
  const loading = previewView(PREVIEW_LOADING, '', '')
  assert('加载中是一个独立状态', loading.kind === PREVIEW_LOADING)
  assert('加载中说的是在读', loading.title.includes('读取'))

  const ready = previewView(PREVIEW_READY, 'def main():\n    pass\n', '')
  assert('取到了就显示正文', ready.content === 'def main():\n    pass\n')
  assert('取到了就没有多余的提示', ready.title === '')

  const empty = previewView(PREVIEW_EMPTY, '', '')
  assert('空文件是独立状态', empty.kind === PREVIEW_EMPTY)
  assert('空文件说清「确实是空的」', empty.title.includes('确实是空的'))
  assert('空文件不再用「没有内容」这种说法', !empty.title.includes('没有内容'))

  const error = previewView(PREVIEW_ERROR, '', '产出物不存在')
  assert('取失败是独立状态', error.kind === PREVIEW_ERROR)
  assert('取失败原样透出后端的错误', error.detail === '产出物不存在')
  assert('取失败不再冒充「没有内容」',
    !error.detail.includes('没有内容') && !error.title.includes('没有内容'))

  const idle = previewView(PREVIEW_IDLE, '', '')
  assert('没选文件是 idle', idle.kind === PREVIEW_IDLE)
  assert('idle 也会说清下一步做什么', idle.title.includes('选一个文件'))
}

/* ---------- 取失败时的错误文案 ---------- */
{
  // axios 形状：后端的 detail 在 response.data.detail
  const err = { response: { status: 404, data: { detail: '产出物不存在' } } }
  assert('取后端给的错误原文', previewErrorText(err, '兜底') === '产出物不存在')
  assert('错误文案里没有「没有内容」',
    !previewErrorText(err, '兜底').includes('没有内容'))

  const plain = new Error('Network Error')
  assert('普通异常取 message', previewErrorText(plain, '兜底') === 'Network Error')
  assert('什么都没有时用兜底', previewErrorText(null, '兜底') === '兜底')
  assert('兜底也没有时不返回空串', previewErrorText(null, '') !== '')
}

/* ---------- 列表接口本来就不带正文 ---------- */
{
  // 列表里的一项：没有 content 字段
  assert('列表项不算有正文', hasArtifactContent({ id: 1, path: 'a.py' }) === false)
  assert('带正文的算有正文', hasArtifactContent({ id: 1, content: 'x' }) === true)
  assert('空正文不算有正文', hasArtifactContent({ id: 1, content: '' }) === false)
  assert('空对象不算有正文', hasArtifactContent(null) === false)
}

/* ---------- 正文有没有过期（用 size 对账） ---------- */
{
  assert('字节数按 UTF-8 算', byteLength('中') === 3, 'got=' + byteLength('中'))
  assert('字节数按 UTF-8 算（多字）', byteLength('中文a') === 7)

  assert('尺寸对得上', contentSizeMatches('abc', 3) === true)
  assert('中文字节数对得上', contentSizeMatches('中文', 6) === true)
  assert('尺寸对不上就是过期了', contentSizeMatches('abc', 4) === false)
  assert('后端没给尺寸就不比对', contentSizeMatches('abc', 0) === true)
  assert('后端没给尺寸也不比对（null）', contentSizeMatches('abc', null) === true)
}

/* ---------- 竞态：慢请求不能盖掉新文件 ---------- */
{
  const seq1 = nextRequestSeq(0)
  const seq2 = nextRequestSeq(seq1)
  assert('序号递增', seq2 > seq1, seq1 + ' → ' + seq2)
  assert('最新序号的响应不算过期', isStaleSeq(seq2, seq2) === false)
  assert('迟到的响应算过期（要丢掉）', isStaleSeq(seq1, seq2) === true)

  // 模拟：先点 A（慢），再点 B（快）；A 后回来 → 必须被丢掉
  let shown = 'B 的正文'
  const applyResponse = (seq, latest, text) => {
    if (isStaleSeq(seq, latest)) return
    shown = text
  }
  applyResponse(seq1, seq2, 'A 的正文')
  assert('慢请求回来后当前内容没被覆盖', shown === 'B 的正文', 'shown=' + shown)
  applyResponse(seq2, seq2, 'B 的正文')
  assert('最新请求的内容正常写进界面', shown === 'B 的正文')
}

/* ---------- 源码守护：别把懒加载改回「从列表里读 content」 ---------- */
{
  // 扫源码前先去掉注释：
  // 注释里本来就该写清楚「原来是 current?.content || '（这个文件没有内容）'」，
  // 那是根因说明，不是活代码，不能因为它就误判。
  const stripComments = (src) => src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
  const src = stripComments(read('src/views/dev/DevStageImplement.vue'))
  assert('预览区不再直接读 current.content',
    !/current\?\.content/.test(src), '出现了 current?.content')
  assert('预览区会调单条接口取正文', /DevApi\.artifact\(/.test(src))
  assert('旧的误导文案不在源码里了', !src.includes('（这个文件没有内容）'), '还留着老文案')
  assert('组件里区分了「取失败」状态', /PREVIEW_ERROR/.test(src))
  assert('组件里防了竞态（请求序号）', /nextRequestSeq/.test(src) && /isStaleSeq/.test(src))
}

console.log('')
if (failed) {
  console.log('❌ ' + failed + ' 项未通过')
  process.exit(1)
}
console.log('✅ 项目文件预览（懒加载正文）断言全部通过')
