/**
 * AI 回答「被截断」的前端回归测试
 *
 * 背景：用户反馈「AI 助理对话后回复的内容会被截断，没有回复全」。
 * 后端负责报出 truncated，前端负责：
 *   1. 明确告诉用户「回答被截断了」（不能让人对着半截内容猜）；
 *   2. 给一键续写入口，且续写要带上已有内容、不重复；
 *   3. 工具结果被截断时要有说明与「查看完整」的入口（不能静默 slice）。
 *
 * 这些逻辑抽在 utils/chatTruncation.js 里，所以这里能直接断言。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  TOOL_PREVIEW_CHARS,
  CONTINUATION_TAIL_CHARS,
  toolResultText,
  toolResultPreview,
  toolTruncationNote,
  toolDownloadFilename,
  continuationTail,
  continuationPrompt,
  buildContinueRequest,
  mergeContinuation,
  truncationNotice,
} from '../src/utils/chatTruncation.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (rel) => readFileSync(join(here, '..', rel), 'utf8')

let passed = 0
function t(name, fn) {
  fn()
  passed++
  console.log(`✅ ${name}`)
}

// ---------- 工具结果：不能静默截断 ----------
t('工具结果不超长时原样展示', () => {
  const p = toolResultPreview({ ok: true, rows: [1, 2, 3] })
  assert.equal(p.truncated, false)
  assert.ok(p.text.includes('"ok"'))
  assert.equal(p.total, p.text.length)
})

t('工具结果超长时标记为已截断并保留前缀', () => {
  const big = { rows: Array.from({ length: 500 }, (_, i) => `第${i}行` + 'x'.repeat(20)) }
  const p = toolResultPreview(big)
  assert.equal(p.truncated, true)
  assert.equal(p.text.length, TOOL_PREVIEW_CHARS)
  assert.ok(p.total > TOOL_PREVIEW_CHARS)
  assert.ok(p.text.startsWith('{'))
})

t('截断说明同时覆盖服务端截断与界面预览截断', () => {
  const note = toolTruncationNote(
    { result_truncated: true, result_chars: 99999 },
    { truncated: true, total: 99999 },
  )
  assert.ok(note.includes('99999'))
  assert.ok(note.includes('已截断'))
  assert.equal(toolTruncationNote({}, { truncated: false, total: 3 }), '')
})

t('工具结果下载文件名带工具名', () => {
  assert.equal(toolDownloadFilename('search_records'), 'ai-tool-search_records.json')
  assert.ok(toolDownloadFilename(null).endsWith('.json'))
})

t('工具结果为 null 时不炸', () => {
  assert.equal(toolResultText(null), '')
  const p = toolResultPreview(null)
  assert.equal(p.truncated, false)
})

// ---------- 续写：带上已有内容，且不重复 ----------
t('续写回灌保留已有内容的尾巴（断点不能丢）', () => {
  const tail = continuationTail('x'.repeat(5000) + '断点在这里')
  assert.ok(tail.endsWith('断点在这里'))
  assert.ok(tail.length <= CONTINUATION_TAIL_CHARS + 50)
  assert.ok(tail.includes('前文已省略'))
})

t('较短的回答整段回灌', () => {
  assert.equal(continuationTail('短短一段'), '短短一段')
  assert.equal(continuationTail(''), '')
})

t('续写指令明确要求不要重复', () => {
  const p = continuationPrompt()
  assert.ok(p.includes('继续写作'))
  assert.ok(p.includes('不要重复'))
  assert.ok(p.includes('接着'))
})

t('续写请求带上问题、历史与已有内容', () => {
  const req = buildContinueRequest({
    question: '介绍一下报销流程',
    history: [{ role: 'user', content: '上一个问题' }, null, { role: 'x' }],
    content: '已经写出来的半截答案',
  })
  assert.equal(req.question, '介绍一下报销流程')
  assert.equal(req.history.length, 1)
  assert.equal(req.history[0].content, '上一个问题')
  assert.ok(req.continuation.includes('已经写出来的半截答案'))
})

t('续写请求兼容直接传 continuation', () => {
  const req = buildContinueRequest({ question: 'q', continuation: '尾巴内容' })
  assert.ok(req.continuation.includes('尾巴内容'))
})

t('续写内容接在已有回答后面', () => {
  assert.equal(mergeContinuation('前半段', '后半段'), '前半段\n\n后半段')
  assert.equal(mergeContinuation('', '只有续写'), '只有续写')
  assert.equal(mergeContinuation('只有已有', ''), '只有已有')
})

// ---------- 底部提示 ----------
t('没被截断时不显示提示', () => {
  assert.equal(truncationNotice(false, 'stop'), null)
  assert.equal(truncationNotice(undefined, undefined), null)
})

t('被截断时给出明确的提示与续写动作', () => {
  const n = truncationNotice(true, 'length')
  assert.ok(n.text.includes('截断'))
  assert.ok(n.text.includes('length'))
  assert.equal(n.action, '继续写完')
  assert.ok(n.hint.includes('不会重复'))
})

// ---------- 组件接线（防止只写了工具函数却没接进界面） ----------
t('AgentChat 展示截断提示并提供续写按钮', () => {
  const src = read('src/components/AgentChat.vue')
  assert.ok(src.includes('m.truncated'), '没有渲染 truncated 状态')
  assert.ok(src.includes('continueAnswer'), '没有续写入口')
  assert.ok(src.includes('继续写完'), '没有续写按钮文案')
  assert.ok(src.includes('toolTruncationNote'), '工具结果没有截断说明')
  assert.ok(src.includes('下载 JSON'), '工具结果没有「查看完整/下载」入口')
  // 旧的静默截断写法要消失
  assert.ok(!src.includes('slice(0, 1500)'), '还在静默 slice 工具结果')
})

t('AIAssistantDialog 同样展示截断提示', () => {
  const src = read('src/components/AIAssistantDialog.vue')
  assert.ok(src.includes('truncated'), '没有渲染 truncated 状态')
  assert.ok(src.includes('continueAnswer'), '没有续写入口')
})

t('前端会请求后端的截断字段', () => {
  const src = read('src/api/index.js')
  assert.ok(src.includes('continuation'), '接口没有把续写内容传给后端')
})
