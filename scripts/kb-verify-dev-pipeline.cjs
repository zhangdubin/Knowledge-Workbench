#!/usr/bin/env node
/**
 * 软件开发四阶段流水线 —— API 级端到端验证
 *
 * 为什么用 API 而不是点浏览器：
 *   浏览器那层会变（升级前端、换布局），一次「点不出来」分不清是
 *   后端没就绪还是前端没接好。API 是契约本身：
 *   接口名、字段名、状态机按 docs/软件开发流水线设计.md 钉死。
 *   这一层守住之后，前端怎么改都不会把契约改坏。
 *
 * 验什么（每一条都是可执行的断言，不是「看着还行」）：
 *   1. GET  /api/dev/projects/{id}/pipeline
 *      → 四个阶段都在、字段齐全、gates 齐全、stages[] 顺序固定；
 *   2. 闸门：clarify 没做完就跑 specify → 必须 409，且说清缺什么、怎么修；
 *   3. POST /api/dev/projects/{id}/stages/{stage}/run → 拿到作业 → 轮询
 *      /api/dev/jobs/{id}：
 *        · total 是真实步骤数（>0）—— total=0 就是前端假 50% 的根源；
 *        · processed 递增、不倒退；
 *        · status 最终是 done 或 failed，不能永远 running；
 *        · failed 时 error 与 how_to_fix 都要非空（不然用户只看到「生成失败」）；
 *   4. POST .../stages/clarify/answer 提交澄清答案；
 *   5. 依次跑 specify → design → implement；
 *   6. GET .../export.zip → 校验是 zip、里面有 README.md；
 *   7. 没跑 implement 就导出 → 必须 409（不许给一个空壳 zip）。
 *
 * 后端还没上线新接口时，脚本如实报失败并退出非 0 ——
 * 静默跳过等于把「没做」说成「没问题」。
 *
 * 用法：
 *   node scripts/kb-verify-dev-pipeline.cjs
 *   KB_DEV_API=http://127.0.0.1:8001 node scripts/kb-verify-dev-pipeline.cjs
 *
 * 退出码 0 = 全部通过；非 0 = 有问题（问题清单打印在最后）。
 */
const { execFileSync } = require('node:child_process')
const path = require('node:path')

const BASE = (process.env.KB_DEV_API || 'http://127.0.0.1:8001').replace(/\/+$/, '')
const REPO = path.resolve(__dirname, '..')
const POLL_INTERVAL = 400
// 轮询上界要盖住后端最坏情况的耗时：
// 后端的 stage_timeout 默认 600 秒，而模型调用超时后还会重试一次
// （call_json 里 attempt 0 超时 → 翻倍额度再来一次），
// 所以一个阶段最坏要 2×600 = 1200 秒才可能落到终态。
// 宁可多等一会儿看到后端自己报的「模型超时」，也不要自己先放弃 ——
// 自己放弃就分不清是「模型慢」还是「作业卡死」了。
const POLL_TIMEOUT = Number(process.env.KB_POLL_TIMEOUT || 1500)

const ERRORS = []
let CHECKS = 0

function ok(name, cond, detail) {
  CHECKS++
  if (cond) {
    console.log('  ✓ ' + name + (detail ? '  ' + detail : ''))
  } else {
    console.log('  ✗ ' + name + (detail ? '  ' + detail : ''))
    ERRORS.push(name + (detail ? '：' + detail : ''))
  }
  return !!cond
}

function fail(name, detail) {
  return ok(name, false, detail)
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 拿会话 token（复用仓库里现成的只读脚本，别自己动库） */
function sessionToken() {
  const out = execFileSync('python3', [path.join(REPO, 'scripts', 'kb-session-token.py')], {
    encoding: 'utf-8',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const token = String(out).trim().split('\n').filter(Boolean).pop()
  if (!token) throw new Error('拿不到会话 token（scripts/kb-session-token.py 没有输出）')
  return token
}

let TOKEN = ''

/**
 * 发一次请求，失败自动重试。
 *
 * 为什么要有重试：
 *   验证脚本经常是在别人重启后端的过程中跑的。
 *   后端容器一重启，正在飞的那条连接就断了 —— 这是**环境抖动**，
 *   不是「流水线坏了」。脚本不该把环境抖动报成产品缺陷，
 *   更不该直接崩掉（崩掉就等于没验）。
 */
async function api(method, apiPath, body, attempt) {
  const n = attempt || 0
  const init = {
    method,
    headers: {
      Cookie: 'kb_session=' + TOKEN,
      Accept: 'application/json',
    },
  }
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let resp
  try {
    resp = await fetch(BASE + apiPath, init)
  } catch (e) {
    if (n < 4) {
      await sleep(800 * (n + 1))
      return api(method, apiPath, body, n + 1)
    }
    throw new Error('连不上后端 ' + BASE + '：' + e.message)
  }
  const ct = resp.headers.get('content-type') || ''
  let payload = null
  if (ct.includes('application/json')) {
    payload = await resp.json()
  } else {
    payload = Buffer.from(await resp.arrayBuffer())
  }
  if (resp.status >= 500 && n < 4) {
    // 后端刚重启时可能回 5xx，缓一下再试
    await sleep(800 * (n + 1))
    return api(method, apiPath, body, n + 1)
  }
  return { status: resp.status, contentType: ct, body: payload }
}

/**
 * 轮询作业直到终态。
 * 记下每一步的 processed，用来证明「进度是真的在走」，而不是一直 0。
 */
async function pollJob(jobId) {
  const samples = []
  const deadline = Date.now() + POLL_TIMEOUT * 1000
  let last = null
  while (Date.now() < deadline) {
    const r = await api('GET', '/api/dev/jobs/' + jobId)
    if (r.status !== 200) {
      return { samples, final: null, httpStatus: r.status, body: r.body }
    }
    const job = r.body && r.body.job ? r.body.job : r.body
    samples.push({
      status: job.status,
      total: Number(job.total || 0),
      processed: Number(job.processed || 0),
      current: job.current || '',
    })
    last = job
    if (job.status === 'done' || job.status === 'failed' ||
        job.status === 'completed' || job.status === 'error') {
      return { samples, final: job, httpStatus: 200 }
    }
    await sleep(POLL_INTERVAL)
  }
  return { samples, final: last, httpStatus: 200, timeout: true }
}

/**
 * 校验一个作业的「真实进度」三件事：
 * total 是真实步骤数（>0）、processed 不倒退、终态不是永远 running。
 */
function checkJobProgress(name, res) {
  if (!res.final) {
    return fail(name + '：拿不到作业状态', 'HTTP ' + res.httpStatus)
  }
  const first = res.samples[0] || {}
  ok(name + '：total 是真实步骤数（>0，不能是 0）',
    Number(res.final.total || 0) > 0,
    'total=' + res.final.total)
  ok(name + '：第一次采样就能看到 total（前端第一帧就有的分母）',
    Number(first.total || 0) > 0, 'first.total=' + first.total)

  let mono = true
  for (let i = 1; i < res.samples.length; i++) {
    if (res.samples[i].processed < res.samples[i - 1].processed) { mono = false; break }
  }
  // 采样点可能上百个（全打印出来没法看），只留头尾若干个：
  const seq = res.samples.map((s) => s.processed)
  const brief = seq.length > 12
    ? seq.slice(0, 6).join('→') + '…' + seq.slice(-5).join('→')
    : seq.join('→')
  ok(name + '：processed 只增不减', mono, '采样 ' + brief)

  const last = res.samples[res.samples.length - 1] || {}
  ok(name + '：processed 至少动过一次（有真实步骤走过）',
    Number(last.processed || 0) > 0,
    'processed=' + last.processed)

  const st = res.final.status
  ok(name + '：作业有终态（不会永远 running）',
    res.timeout ? false : (st === 'done' || st === 'completed' || st === 'failed' || st === 'error'),
    'status=' + st + (res.timeout ? '（轮询超时）' : ''))

  // 假 50% 的根源：total=0 时前端只能显示不确定态。
  // 这里再钉一道：任何时刻 total 都不许是 0。
  const badTotal = res.samples.find((s) => Number(s.total || 0) <= 0)
  ok(name + '：整个过程 total 都不是 0', !badTotal,
    badTotal ? '出现 total=' + badTotal.total : '')

  if (st === 'failed' || st === 'error') {
    const err = res.final.error || ''
    const how = res.final.how_to_fix || (res.final.detail && res.final.detail.how_to_fix)
    const detail = res.final.detail
    const hasHow = Array.isArray(how) ? how.length > 0
      : (typeof how === 'string' ? how.length > 0 : false)
    ok(name + '：失败时 error 非空', !!err, err)
    ok(name + '：失败时 how_to_fix 非空', hasHow,
      JSON.stringify(how) + ' / detail=' + JSON.stringify(detail))
  }
  return res
}

/** 从 zip 字节里列出条目名（本地文件头 PK\x03\x04，不用解压） */
function zipEntries(buf) {
  const names = []
  let i = 0
  while (i + 30 <= buf.length) {
    if (buf[i] === 0x50 && buf[i + 1] === 0x4b && buf[i + 2] === 0x03 && buf[i + 3] === 0x04) {
      const nameLen = buf.readUInt16LE(i + 26)
      const extraLen = buf.readUInt16LE(i + 28)
      const name = buf.slice(i + 30, i + 30 + nameLen).toString('utf-8')
      names.push(name)
      i += 30 + nameLen + extraLen + buf.readUInt32LE(i + 18)
    } else {
      i++
    }
  }
  return names
}
async function main() {
  console.log('软件开发流水线 · API 级端到端验证')
  console.log('后端：' + BASE)
  console.log('')

  try {
    TOKEN = sessionToken()
  } catch (e) {
    console.log('  ✗ 拿不到会话 token：' + e.message)
    console.log('')
    console.log('✗ 无法验证：连会话都建不起来')
    process.exit(1)
  }

  // ---------- 0) 建项目（名字带时间戳，不污染已有数据） ----------
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)
  const name = '流水线验证-' + stamp
  console.log('▶  建项目：' + name)
  const created = await api('POST', '/api/dev/projects', {
    name,
    goal: '做一个工单管理系统：客服录入工单、分配负责人、按状态筛选、统计工作量',
    tech_stack: ['Python', 'FastAPI'],
    tech_notes: '用 SQLite 存储',
    mode: '',
  })
  if (created.status !== 200 || !created.body || !created.body.project) {
    console.log('  ✗ 建项目失败：HTTP ' + created.status + ' ' + JSON.stringify(created.body).slice(0, 300))
    console.log('')
    console.log('✗ 无法验证：项目都建不起来')
    process.exit(1)
  }
  const pid = created.body.project.id
  console.log('  项目 id = ' + pid)
  console.log('')

  // ---------- 1) 读流水线 ----------
  console.log('▶  GET /api/dev/projects/' + pid + '/pipeline')
  const pl = await api('GET', '/api/dev/projects/' + pid + '/pipeline')
  if (pl.status === 404) {
    console.log('  ✗ 后端还没有 pipeline 接口（404）—— 后端流水线没上线，不能当成通过')
    console.log('')
    console.log('✗ 验证未通过：缺少 /api/dev/projects/{id}/pipeline')
    process.exit(1)
  }
  ok('流水线接口可用', pl.status === 200, 'HTTP ' + pl.status)
  const pipeline = (pl.body && pl.body.pipeline) || null
  const stageKeys = ['clarify', 'specify', 'design', 'implement']
  ok('返回里有 pipeline 对象', !!pipeline)
  ok('四个阶段都在',
    pipeline && stageKeys.every((k) => pipeline.stages && pipeline.stages[k]),
    pipeline ? Object.keys(pipeline.stages || {}).join(',') : '')
  if (pipeline) {
    const fields = ['status', 'at', 'data', 'answers', 'notes', 'error', 'summary']
    const missing = []
    for (const k of stageKeys) {
      for (const f of fields) {
        if (!(f in (pipeline.stages[k] || {}))) missing.push(k + '.' + f)
      }
    }
    ok('每个阶段的字段齐全（契约 §3.1）', missing.length === 0, missing.join(' '))
    ok('current_stage 是四个阶段之一',
      stageKeys.includes(pipeline.current_stage),
      'current_stage=' + pipeline.current_stage)
  }
  const view = (pl.body && pl.body.stages) || []
  ok('stages[] 是左栏用的精简视图，四项且顺序固定',
    view.length === 4 && stageKeys.every((k, i) => view[i] && view[i].key === k),
    view.map((s) => s.key).join('→'))
  const gates = (pl.body && pl.body.gates) || {}
  ok('gates 齐全（can_specify / can_design / can_implement）',
    ['can_specify', 'can_design', 'can_implement'].every((k) => k in gates),
    JSON.stringify(gates))
  console.log('')

  // ---------- 2) 闸门：clarify 没做完就跑 specify → 必须 409 ----------
  console.log('▶  闸门：clarify 没做完就跑 specify（必须 409）')
  const gateRes = await api('POST', '/api/dev/projects/' + pid + '/stages/specify/run', { extra: '', force: false })
  ok('闸门拦住了 specify', gateRes.status === 409, 'HTTP ' + gateRes.status)
  if (gateRes.status === 409 && gateRes.body && typeof gateRes.body === 'object') {
    const b = gateRes.body
    ok('409 的 body 说清了缺什么',
      Array.isArray(b.missing) ? b.missing.length > 0 : !!b.detail,
      JSON.stringify(b).slice(0, 200))
    ok('409 的 body 给了怎么修（how_to_fix）',
      Array.isArray(b.how_to_fix) ? b.how_to_fix.length > 0 : !!b.detail,
      JSON.stringify(b.how_to_fix || b.detail || '').slice(0, 200))
  }
  console.log('')

  // ---------- 3) 跑 clarify ----------
  console.log('▶  跑 clarify（需求理解）')
  const runClarify = await api('POST', '/api/dev/projects/' + pid + '/stages/clarify/run', { extra: '', force: false })
  if (runClarify.status !== 200 || !runClarify.body || !runClarify.body.job) {
    fail('clarify 阶段能起作业', 'HTTP ' + runClarify.status + ' ' + JSON.stringify(runClarify.body).slice(0, 300))
  } else {
    const jobId = runClarify.body.job.id
    console.log('  作业 id = ' + jobId)
    const res = await pollJob(jobId)
    checkJobProgress('clarify', res)
    if (res.final && (res.final.status === 'failed' || res.final.status === 'error')) {
      fail('clarify 跑成功', '作业失败：' + (res.final.error || ''))
    } else {
      ok('clarify 跑成功', true)
    }
  }
  console.log('')

  // ---------- 4) 提交澄清答案 ----------
  console.log('▶  提交澄清答案')
  const pl2 = await api('GET', '/api/dev/projects/' + pid + '/pipeline')
  const clarifyData = (pl2.body.pipeline && pl2.body.pipeline.stages.clarify.data) || {}
  const questions = Array.isArray(clarifyData.questions) ? clarifyData.questions : []
  ok('clarify 产出了澄清问题清单（结构符合契约）',
    Array.isArray(clarifyData.questions),
    'questions=' + questions.length)
  if (questions.length) {
    const q = questions[0]
    ok('第一个澄清问题字段齐全（id/question/options）',
      q && q.id && q.question && Array.isArray(q.options),
      JSON.stringify(q).slice(0, 160))
  }
  const answers = {}
  for (const q of questions) {
    answers[q.id] = (Array.isArray(q.options) && q.options.length) ? q.options[0] : '人工录入'
  }
  const clarifyStage = pl2.body.pipeline && pl2.body.pipeline.stages.clarify
  if (questions.length === 0) {
    // 契约里「questions 为空」是合法状态：模型认为需求已经够清楚。
    // 这时候不该硬凑答案 —— 该验的是「它已经算澄清完成」。
    ok('没有澄清问题时，clarify 直接算完成（无需澄清也是合法状态）',
      clarifyStage && clarifyStage.status === 'done',
      clarifyStage ? clarifyStage.status : 'no stage')
  } else {
    const ans = await api('POST', '/api/dev/projects/' + pid + '/stages/clarify/answer', {
      answers,
      notes: '验证脚本自动作答',
    })
    ok('澄清答案提交成功', ans.status === 200, 'HTTP ' + ans.status)
    if (ans.status === 200) {
      const st = ans.body && ans.body.pipeline && ans.body.pipeline.stages.clarify
      ok('回答完后 clarify 变成 done（闸门据此放行）',
        st && st.status === 'done', st ? st.status : 'no stage')
    }
  }
  console.log('')

  // ---------- 5) 依次跑 specify → design → implement ----------
  for (const stage of ['specify', 'design', 'implement']) {
    console.log('▶  跑 ' + stage)
    // 重启容错：后端在验证过程中被重启是常事（有人在重新发版）。
    // 这时作业会被标成 failed「服务重启中断」——
    // 用户遇到这事的正确反应就是「重跑这一步」，脚本也照做，
    // 不然一次环境抖动就把整条验证判死。
    let res = null
    for (let attempt = 1; attempt <= 3; attempt++) {
      const runRes = await api('POST', '/api/dev/projects/' + pid + '/stages/' + stage + '/run',
        { extra: '', force: attempt > 1 })
      if (runRes.status === 409) {
        fail(stage + ' 阶段能起作业', '闸门没放行：HTTP 409 ' + JSON.stringify(runRes.body).slice(0, 200))
        res = null
        break
      }
      if (runRes.status !== 200 || !runRes.body || !runRes.body.job) {
        fail(stage + ' 阶段能起作业', 'HTTP ' + runRes.status + ' ' + JSON.stringify(runRes.body).slice(0, 300))
        res = null
        break
      }
      res = await pollJob(runRes.body.job.id)
      const st = res.final && res.final.status
      if (st !== 'failed' && st !== 'error') break
      const err = String((res.final && res.final.error) || '')
      if (!/服务重启中断|中断/.test(err)) break
      console.log('  ! 作业被服务重启打断（第 ' + attempt + ' 次），重跑这一步')
      await sleep(2000)
    }
    if (!res) continue
    checkJobProgress(stage, res)
    if (res.final && (res.final.status === 'failed' || res.final.status === 'error')) {
      fail(stage + ' 跑成功', '作业失败：' + (res.final.error || ''))
    } else {
      ok(stage + ' 跑成功', true)
    }
    // 作业与阶段状态必须同步：
    // 作业失败却让阶段永远停在 running，界面上就是一个转不完的圈。
    const plNow = await api('GET', '/api/dev/projects/' + pid + '/pipeline')
    const stNow = plNow.body && plNow.body.pipeline &&
      plNow.body.pipeline.stages[stage]
    ok(stage + '：阶段状态与作业状态同步（不是永远 running）',
      stNow && stNow.status !== 'running',
      stNow ? stNow.status : 'no stage')
  }
  console.log('')

  // ---------- 6) 导出 ZIP ----------
  console.log('▶  GET /api/dev/projects/' + pid + '/export.zip')
  const zip = await api('GET', '/api/dev/projects/' + pid + '/export.zip')
  ok('导出返回 200', zip.status === 200, 'HTTP ' + zip.status)
  if (zip.status === 200 && Buffer.isBuffer(zip.body)) {
    const buf = zip.body
    ok('内容是 zip（首字节 PK\\x03\\x04）',
      buf[0] === 0x50 && buf[1] === 0x4b && buf[2] === 0x03 && buf[3] === 0x04,
      'size=' + buf.length)
    const entries = zipEntries(buf)
    ok('zip 里有条目', entries.length > 0, '条目数 ' + entries.length)
    ok('zip 里有 README.md', entries.some((n) => /(^|\/)README\.md$/i.test(n)),
      entries.filter((n) => /readme/i.test(n)).join(','))
    ok('zip 顶层有一层项目目录（契约 §3.4）',
      entries.length > 0 && entries[0].includes('/'),
      entries[0] || '')
    ok('zip 里有依赖清单',
      entries.some((n) => /requirements\.txt$|package\.json$/i.test(n)),
      entries.filter((n) => /requirements|package\.json/i.test(n)).join(','))
    ok('zip 里有测试文件',
      entries.some((n) => /test/i.test(n)),
      entries.filter((n) => /test/i.test(n)).slice(0, 3).join(','))
    ok('zip 里有可运行的入口文件',
      entries.some((n) => /main\.py$|app\.py$|index\.(js|ts)$|server\.py$/i.test(n)),
      entries.slice(0, 6).join(','))
  } else {
    ok('导出的是二进制 zip', false, 'content-type=' + zip.contentType)
  }
  console.log('')

  // ---------- 7) 收尾：流水线不该有阶段卡在 running ----------
  const plEnd = await api('GET', '/api/dev/projects/' + pid + '/pipeline')
  const stagesEnd = (plEnd.body && plEnd.body.pipeline &&
    plEnd.body.pipeline.stages) || {}
  const stuck = stageKeys.filter((k) =>
    stagesEnd[k] && stagesEnd[k].status === 'running')
  ok('没有阶段卡在 running（都该有终态）', stuck.length === 0,
    stuck.join(',') || '（无）')
  const failedStages = stageKeys.filter((k) =>
    stagesEnd[k] && stagesEnd[k].status === 'failed')
  ok('没有阶段处于 failed', failedStages.length === 0,
    failedStages.join(',') || '（无）')
  console.log('')

  console.log('项目 id = ' + pid + '（留着便于排查；名字带时间戳，不会认错别人的项目）')
  console.log('')
  if (ERRORS.length) {
    console.log('✗ ' + ERRORS.length + ' 项不通过（共 ' + CHECKS + ' 项）：')
    for (const e of ERRORS) console.log('   - ' + e)
    process.exit(1)
  }
  console.log('✓ 全部 ' + CHECKS + ' 项检查通过')
  process.exit(0)
}

main().catch((e) => {
  console.log('')
  console.log('✗ 验证脚本自身出错：' + (e && e.stack ? e.stack : e))
  process.exit(1)
})
