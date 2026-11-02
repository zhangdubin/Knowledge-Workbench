// 评分展示的翻译层断言
// 覆盖 utils/dnaScore.js：
//   fmtScore / scoreTone / pct —— 分数怎么显示、怎么分档
//   buildScoreGroups        —— 后端分项字典怎么变成页面上的两栏
//   scoreHistory            —— 履历（复用成功/失败、纠正次数）
//   scoreVerdict            —— 一句话结论
//
// 为什么单测它：评分是「让人信」的界面。
// 分档写反了、缺项没兜住，页面上就会把一条坏知识显示成好的 ——
// 光看截图发现不了。
import {
  fmtScore, scoreTone, pct, outcomeLabel,
  buildScoreGroups, scoreHistory, scoreVerdict,
} from '../src/utils/dnaScore.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log((ok ? '✅' : '❌') + ' ' + name + (detail ? '  ' + detail : ''))
}

// ---------- 分数显示 ----------
{
  assert('两位小数', fmtScore(0.4213) === '0.42', fmtScore(0.4213))
  assert('整数也带两位', fmtScore(1) === '1.00', fmtScore(1))
  assert('空值显示为破折号', fmtScore(null) === '—', fmtScore(null))
  assert('非数字显示为破折号', fmtScore('abc') === '—')
}

// ---------- 分档 ----------
{
  assert('0.85 算好', scoreTone(0.85) === 'score-good')
  assert('0.50 算中等', scoreTone(0.5) === 'score-mid')
  assert('0.20 算差', scoreTone(0.2) === 'score-low')
  assert('没有分数不冒充好坏', scoreTone(undefined) === 'score-none')
}

// ---------- 百分比 ----------
{
  assert('0.5 → 50%', pct(0.5) === '50%', pct(0.5))
  assert('0 → 0%', pct(0) === '0%')
  assert('空值不装成 0%', pct(null) === '—')
}

// ---------- 复用结果 ----------
{
  assert('成功', outcomeLabel('success') === '成功')
  assert('失败', outcomeLabel('fail') === '失败')
  assert('未知值原样返回', outcomeLabel('xxx') === 'xxx')
}

// ---------- 分项翻译 ----------
{
  const payload = {
    expressiveness: 0.72,
    confidence: 0.61,
    express_parts: {
      specificity: { key: 'specificity', label: '具体度', score: 0.8, weight: 0.25, detail: '有具体锚点' },
      actionability: { key: 'actionability', label: '可执行性', score: 0.6, weight: 0.3, detail: '四要素缺一' },
    },
    confidence_parts: {
      authority: { key: 'authority', label: '来源权威度', score: 0.9, weight: 0.25, detail: '源码实证' },
    },
    evidence: {
      confidence: { penalties: [
        { key: 'correction', label: '人工纠正', amount: 0.12, detail: '被纠正 1 次' },
      ] },
    },
  }
  const groups = buildScoreGroups(payload)
  assert('翻成两栏', groups.length === 2, '实际 ' + groups.length)
  assert('第一栏是表达度', groups[0].key === 'expressiveness')
  assert('第二栏是置信度', groups[1].key === 'confidence')
  assert('表达度分项都带依据', groups[0].parts.every((p) => !!p.detail))
  assert('分项权重带出来了', groups[0].parts[0].weight === 0.25)
  assert('扣分项带出来了', groups[1].penalties.length === 1)
  assert('扣分项有金额', groups[1].penalties[0].amount === 0.12)
  assert('空载荷不炸', buildScoreGroups(null).length === 0)
  assert('缺分项也不炸', buildScoreGroups({ expressiveness: 0.5 }).length === 2)
}

// ---------- 履历 ----------
{
  const h = scoreHistory({ use_success: 3, use_fail: 1, corrections: 2, distinct_sources: 4 })
  assert('复用成功次数', h.use_success === 3)
  assert('复用失败次数', h.use_fail === 1)
  assert('纠正次数', h.corrections === 2)
  assert('来源数', h.distinct_sources === 4)
  assert('没评分时来源数按 1 算', scoreHistory(null).distinct_sources === 1)
}

// ---------- 一句话结论 ----------
{
  assert('没评分 → 不下结论', scoreVerdict(null).tone === 'score-none')
  assert('纠正过 → 优先让人去核对',
    scoreVerdict({ expressiveness: 0.9, confidence: 0.9, corrections: 1 })
      .text.includes('核对'))
  assert('表达度低 → 说太含糊',
    scoreVerdict({ expressiveness: 0.2, confidence: 0.9 }).tone === 'score-low')
  assert('置信度低 → 说出处不够硬',
    scoreVerdict({ expressiveness: 0.8, confidence: 0.3 }).tone === 'score-mid')
  assert('又清楚又可信 → 可以直接用',
    scoreVerdict({ expressiveness: 0.8, confidence: 0.8 }).tone === 'score-good')
}

console.log(failed ? `\n❌ ${failed} 项断言失败` : '\n✅ 全部断言通过')
if (failed) process.exit(1)
