/**
 * 软件开发流水线 · 前端纯函数单测
 *
 * 守住三件事：
 *   1) 阶段顺序与状态是契约定的，不许前端自己发明：
 *      clarify → specify → design → implement，五个状态不多不少；
 *   2) 闸门只负责显示，真正的判定在后端 —— 但「为什么不能跑」
 *      必须说清是上一阶段没完成，不能只写「不可用」；
 *   3) 进度条不许再有假的 50%：
 *      总量未知就不给百分比（走不确定态），
 *      总量已知一律按 processed/total 算。
 *      这一条当年坑过一次（后端返回 {job:…}，前端忘了取 .job，
 *      total 变 undefined，进度条永远停在 50%），必须钉死。
 */
import assert from 'node:assert/strict'
import {
  STAGE_KEYS, STAGE_STATUS, stageMeta, stageStatus, stageSummary,
  stageGate, gateReason, unwrapJob, jobProgress, jobHowToFix,
  clarifyQuestions,
} from '../src/utils/dev.js'

let passed = 0
function t(name, fn) {
  fn()
  passed++
  console.log('  ✓ ' + name)
}

console.log('dev · 四阶段流水线（契约层）')

// ---------- 阶段顺序：契约 §1 定的，产品决定 ----------
t('四个阶段的顺序固定为 需求理解 → 需求补全 → 需求转化 → 项目生成', () => {
  assert.deepEqual(STAGE_KEYS, ['clarify', 'specify', 'design', 'implement'])
})

t('每个阶段都有名字、动作与交付物（不许留空给用户看）', () => {
  for (const key of STAGE_KEYS) {
    const m = stageMeta(key)
    assert.ok(m.title && m.short && m.action && m.deliverable,
      '阶段 ' + key + ' 的元信息不全：' + JSON.stringify(m))
    assert.equal(m.key, key)
  }
})

t('未知阶段不炸，给个占位（后端加了新阶段也不会把界面搞崩）', () => {
  const m = stageMeta('release')
  assert.equal(m.key, 'release')
  assert.ok(m.title.length > 0)
  assert.equal(stageMeta(undefined).title, '未知阶段')
})

// ---------- 状态机：五种状态，契约 §2 ----------
t('阶段状态正好五种，一个不多一个不少', () => {
  assert.deepEqual(
    Object.keys(STAGE_STATUS).sort(),
    ['done', 'failed', 'needs_input', 'pending', 'running'])
})

t('五种状态都有中文标签与配色类型', () => {
  for (const [k, v] of Object.entries(STAGE_STATUS)) {
    assert.ok(v.label && v.type, '状态 ' + k + ' 缺 label/type')
  }
})

t('未知状态按「未开始」显示，不抛异常', () => {
  assert.equal(stageStatus('weird').label, '未开始')
  assert.equal(stageStatus(undefined).label, '未开始')
  assert.equal(stageStatus('done').label, '已完成')
  assert.equal(stageStatus('failed').type, 'danger')
})

// ---------- 闸门 ----------
t('闸门没放行时要说清是上一阶段没完成', () => {
  const gates = { can_specify: false, can_design: false, can_implement: false }
  const g = stageGate('specify', gates)
  assert.equal(g.ok, false)
  assert.ok(g.reason.length > 0)
  assert.ok(g.reason.includes('需求理解'), '理由里要点名上一阶段：' + g.reason)
})

t('四个阶段的闸门理由都非空，且互不相同', () => {
  const reasons = STAGE_KEYS.map((k) => gateReason(k))
  for (const r of reasons) assert.ok(r && r.length > 0)
  assert.equal(new Set(reasons).size, STAGE_KEYS.length)
})

t('闸门放行时不啰嗦', () => {
  const gates = { can_specify: true, can_design: true, can_implement: true }
  for (const k of ['specify', 'design', 'implement']) {
    const g = stageGate(k, gates)
    assert.equal(g.ok, true)
    assert.equal(g.reason, '')
  }
})

t('后端没给这个闸门键时先不拦（判定在后端，前端不自己发明规则）', () => {
  assert.equal(stageGate('specify', {}).ok, true)
  assert.equal(stageGate('specify', undefined).ok, true)
  assert.equal(stageGate('clarify', { can_clarify: false }).ok, false)
})

// ---------- 状态机推进：产出说什么 ----------
t('clarify 有待答问题时说清有几个', () => {
  const s = {
    key: 'clarify',
    status: 'needs_input',
    data: { questions: [{ id: 'q1', question: '工单从哪来？', options: ['人工'] }] },
  }
  assert.ok(stageSummary(s).includes('1'))
})

t('clarify 没问题时明确说「无需澄清」（空问题是合法状态，不是出错）', () => {
  const s = { key: 'clarify', status: 'done', data: { questions: [] } }
  assert.ok(stageSummary(s).includes('无需澄清'))
})

t('阶段失败时摘要里能看到失败原因', () => {
  const s = { key: 'specify', status: 'failed', error: '模型没吐出 JSON' }
  assert.equal(stageSummary(s), '模型没吐出 JSON')
})

t('没开始的阶段说「还没开始」，不编产出', () => {
  assert.equal(stageSummary({ key: 'design', status: 'pending' }), '还没开始')
})

t('澄清问题按契约字段归一（id/question/options/allow_free）', () => {
  const qs = clarifyQuestions({
    questions: [{ id: 'q1', question: '工单从哪来？', options: ['人工', '推送'] }],
  })
  assert.equal(qs.length, 1)
  assert.equal(qs[0].id, 'q1')
  assert.deepEqual(qs[0].options, ['人工', '推送'])
  assert.equal(qs[0].allow_free, true)
  assert.deepEqual(clarifyQuestions(null), [])
})

// ---------- 作业解包 ----------
t('后端返回 {job:…} 时要取 .job（忘了取就是「进度永远 50%」那个坑）', () => {
  assert.equal(unwrapJob({ job: { id: 7, total: 3 } }).id, 7)
  assert.equal(unwrapJob({ job: { id: 7, total: 3 } }).total, 3)
  assert.equal(unwrapJob({ id: 7 }).id, 7)
  assert.equal(unwrapJob(null), null)
})

// ---------- 进度百分比：绝不许有假的 50% ----------
t('总量未知时走不确定态，百分比不是 50', () => {
  const p = jobProgress({ status: 'running', processed: 0, total: 0 })
  assert.equal(p.indeterminate, true)
  assert.notEqual(p.percent, 50)
  assert.equal(p.done, false)
  assert.equal(p.failed, false)
})

t('总量未知就算 processed 很大也不给百分比', () => {
  const p = jobProgress({ status: 'running', processed: 12, total: 0 })
  assert.equal(p.indeterminate, true)
  assert.notEqual(p.percent, 50)
})

t('总量已知时按 processed/total 算', () => {
  assert.equal(jobProgress({ status: 'running', total: 4, processed: 1 }).percent, 25)
  assert.equal(jobProgress({ status: 'running', total: 4, processed: 3 }).percent, 75)
  assert.equal(jobProgress({ status: 'running', total: 4, processed: 0 }).percent, 0)
})

t('跑着的作业最多显示 99%（100% 只留给真正完成）', () => {
  const p = jobProgress({ status: 'running', total: 4, processed: 4 })
  assert.equal(p.percent, 99)
  assert.equal(p.done, false)
})

t('没有作业时是排队中，不是 50%', () => {
  const p = jobProgress(null)
  assert.notEqual(p.percent, 50)
  assert.equal(p.indeterminate, false)
  assert.equal(p.done, false)
})

t('作业失败是终态：显示 error、能拿到处置建议', () => {
  const p = jobProgress({
    status: 'failed',
    total: 3,
    processed: 1,
    error: '模型没有返回可解析的方案 JSON',
    how_to_fix: ['把 max_tokens 调到 8192', '重跑这一步'],
  })
  assert.equal(p.failed, true)
  assert.equal(p.done, true)
  assert.ok(p.text.includes('模型没有返回'))
  const fix = jobHowToFix({
    status: 'failed',
    error: 'x',
    how_to_fix: ['把 max_tokens 调到 8192'],
  })
  assert.equal(fix.length, 1)
  assert.ok(fix[0].includes('8192'))
})

t('how_to_fix 也认字符串与 detail 两种形状', () => {
  assert.deepEqual(jobHowToFix({ how_to_fix: '调大 max_tokens' }), ['调大 max_tokens'])
  assert.deepEqual(jobHowToFix({ detail: ['看日志'] }), ['看日志'])
  assert.deepEqual(jobHowToFix({}), [])
  assert.deepEqual(jobHowToFix(null), [])
})

t('任何一种作业形状都不会凭空冒出 50%（这是当年那个 bug 的形状）', () => {
  const shapes = [
    null,
    {},
    { status: 'running' },
    { status: 'running', processed: 0 },
    { status: 'running', processed: 3, total: 0 },
    { status: 'created' },
    { status: 'running', processed: 2, total: 4 },
    { status: 'queued', total: undefined },
  ]
  for (const s of shapes) {
    const p = jobProgress(s)
    const total = Number((s && s.total) || 0)
    const processed = Number((s && s.processed) || 0)
    const real = total > 0 ? Math.min(99, Math.round((processed / total) * 100)) : null
    if (real === null) {
      assert.notEqual(p.percent, 50, '形状 ' + JSON.stringify(s) + ' 冒出了 50%')
    } else {
      assert.equal(p.percent, real)
    }
  }
})

console.log('\n通过 ' + passed + ' 项')
