// 检索请求的「去重 + 取消 + 提示」逻辑断言
// 覆盖 utils/searchRequest.js：
//   createSearchRequest  —— 同一个词不重复发、换词取消上一个、旧结果不许盖新结果
//   buildSearchNotice   —— 后端的「降级 / 截断」说明转成人话
//
// 这段逻辑全是时序，光看页面验不出来：
// 「旧结果有没有被盖掉」「取消有没有真的取消」都得单测钉住。
import { createSearchRequest, buildSearchNotice } from '../src/utils/searchRequest.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log((ok ? '✅' : '❌') + ' ' + name + (detail ? '  ' + detail : ''))
}

// ---------- 去重：同一个词不重复发 ----------
{
  const req = createSearchRequest()
  const a = req.begin('知识库')
  const b = req.begin('知识库')
  assert('同一个词重复提交 → 标记为重复（不再发第二次请求）', b.duplicated === true)
  assert('重复提交拿到的还是同一个请求序号', b.seq === a.seq)
  assert('重复提交不产生新的 AbortController', b.controller === a.controller)
}

// ---------- 换词：取消上一个 ----------
{
  const req = createSearchRequest()
  const a = req.begin('知识库')
  let aborted = false
  a.controller.signal.addEventListener('abort', () => { aborted = true })
  const b = req.begin('投标')
  assert('换了词 → 上一个请求被取消', aborted === true)
  assert('换了词 → 不是重复', b.duplicated === false)
  assert('换了词 → 序号递增', b.seq > a.seq)
}

// ---------- 旧结果不许盖新结果 ----------
{
  const req = createSearchRequest()
  const a = req.begin('知识库')
  const b = req.begin('投标')
  assert('旧请求的序号不再是「当前」', req.isCurrent(a.seq) === false)
  assert('最新请求的序号是「当前」', req.isCurrent(b.seq) === true)
}

// ---------- end 之后不算当前（防止旧请求把 loading 关掉） ----------
{
  const req = createSearchRequest()
  const a = req.begin('知识库')
  req.end(a.seq)
  const b = req.begin('投标')
  assert('end 之后再换词 → 新请求仍然是当前', req.isCurrent(b.seq) === true)
  assert('end 之后的旧序号不是当前', req.isCurrent(a.seq) === false)
}

// ---------- buildSearchNotice ----------
{
  assert('没有返回体 → 空提示', buildSearchNotice(null) === '')
  assert('正常结果 → 空提示', buildSearchNotice({ records: [], documents: [] }) === '')

  const deg = buildSearchNotice({
    degraded: true, degraded_reason: '语义通道超时，已降级为关键词检索',
  })
  assert('降级 → 说出原因', deg === '语义通道超时，已降级为关键词检索', deg)

  const tru = buildSearchNotice({
    truncated: true, truncated_reason: '关键词命中超过 150 条，已按相关度取前 50 条',
  })
  assert('截断 → 说出取了多少条', tru.includes('前 50 条'), tru)

  const both = buildSearchNotice({
    degraded: true, degraded_reason: '语义通道超时',
    truncated: true, truncated_reason: '命中过多，已截断',
  })
  assert('降级 + 截断 → 两句都说', both.split('；').length === 2, both)

  assert('降级但没给原因 → 有兜底文案',
    buildSearchNotice({ degraded: true }).length > 0)
  assert('截断但没给原因 → 有兜底文案',
    buildSearchNotice({ truncated: true }).length > 0)
}

if (failed) {
  console.error('\n❌ 检索请求逻辑测试失败：' + failed + ' 项')
  process.exit(1)
}
console.log('\n✅ 检索请求逻辑测试全部通过')
