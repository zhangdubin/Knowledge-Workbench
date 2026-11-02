// 软件开发工作台 · 四阶段流水线的纯函数断言
//
// 重点守住三件事：
//   1) 作业解包（后端返回 {job:...}，忘了取 .job 就是「进度永远 50%」那个 bug）；
//   2) 进度条不许再出现假的 50%：总量未知就走不确定态；
//   3) 阶段状态、闸门、摘要、文件树、doctor 文案都能落到人话上。
import {
  unwrapJob, jobProgress, jobHowToFix,
  STAGE_KEYS, stageMeta, stageStatus, stageSummary, stageGate, gateReason,
  clarifyQuestions, specifySections, designSections,
  buildFileTree, doctorMissingText, doctorSummary,
} from '../src/utils/dev.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log((ok ? '✅' : '❌') + ' ' + name + (detail ? '  ' + detail : ''))
}

// ---------- 作业解包 ----------
{
  // 后端 GET /api/dev/jobs/{id} 返回的是 { job: {...} }
  assert('包装对象能解包', unwrapJob({ job: { id: 7 } }).id === 7)
  assert('没有包装也能用', unwrapJob({ id: 7 }).id === 7)
  assert('空值解包成 null', unwrapJob(null) === null)
  assert('解包后拿得到 total', unwrapJob({ job: { total: 5 } }).total === 5)
}

// ---------- 进度条：不许再有假的 50% ----------
{
  assert('空作业是排队中', jobProgress(null).percent === 0)
  assert('空作业不是确定态', jobProgress(null).indeterminate === false)

  // 总量未知：不给百分比，走不确定态
  const unknown = jobProgress({ status: 'running', processed: 2 })
  assert('总量未知时百分比是 0', unknown.percent === 0, 'percent=' + unknown.percent)
  assert('总量未知时是不确定态', unknown.indeterminate === true)
  assert('总量未知时文案是「进行中…」', unknown.text === '进行中…', 'text=' + unknown.text)
  assert('总量未知时不是失败', unknown.failed === false)

  const withCurrent = jobProgress({ status: 'running', current: '调用模型生成需求规格' })
  assert('有 current 就显示 current', withCurrent.text === '调用模型生成需求规格')

  // 总量已知：按比例算
  const half = jobProgress({ status: 'running', total: 10, processed: 5 })
  assert('进度按比例算', half.percent === 50)
  assert('总量已知时是确定态', half.indeterminate === false)
  assert('没跑完不算完成', half.done === false)
  const over = jobProgress({ status: 'running', total: 10, processed: 10 })
  assert('没完成时封顶 99', over.percent === 99)

  // 终态
  const failed = jobProgress({ status: 'failed', error: '模型没有返回可解析的方案 JSON' })
  assert('失败是终态', failed.failed === true && failed.done === true)
  assert('失败时显示后端的错误', failed.text.includes('模型没有返回可解析的方案 JSON'))
  assert('失败时不是不确定态', failed.indeterminate === false)
  const done = jobProgress({ status: 'done' })
  assert('完成是终态', done.done === true && done.percent === 100)
}

// ---------- 失败时给用户的处置建议 ----------
{
  assert('数组形式的 how_to_fix', jobHowToFix({ how_to_fix: ['a', 'b'] }).length === 2)
  assert('字符串形式的 how_to_fix', jobHowToFix({ how_to_fix: '换个大模型' })[0] === '换个大模型')
  assert('没有就空数组', jobHowToFix({}).length === 0)
  assert('空作业不炸', jobHowToFix(null).length === 0)
}

// ---------- 阶段元信息 ----------
{
  assert('四个阶段', STAGE_KEYS.join(',') === 'clarify,specify,design,implement')
  assert('阶段有中文名', stageMeta('clarify').title === '需求理解')
  assert('未知阶段不炸', stageMeta('xxx').title === 'xxx')
  assert('阶段状态有五种', ['pending', 'running', 'needs_input', 'done', 'failed']
    .every((s) => !!stageStatus(s).label))
  assert('未知状态有兜底', stageStatus('weird').label === '未开始')
}

// ---------- 阶段摘要（要是一句人话） ----------
{
  assert('没开始时摘要说还没开始', stageSummary({ key: 'clarify', status: 'pending' }) === '还没开始')
  assert('失败时摘要是失败原因',
    stageSummary({ key: 'design', status: 'failed', error: '解析失败' }) === '解析失败')
  assert('完成时摘要说需求够清楚',
    stageSummary({ key: 'clarify', status: 'done', data: { questions: [] } }) === '需求已经够清楚，无需澄清')
  assert('完成时摘要有问题数',
    stageSummary({
      key: 'clarify',
      status: 'done',
      data: { questions: [{ id: 'q1', question: '从哪来？' }, { id: 'q2', question: '到哪去？' }] },
    }).includes('提出了 2 个澄清问题'))
  assert('规格阶段摘要给故事数',
    stageSummary({ key: 'specify', status: 'done', data: { stories: [{ id: 'S1' }], nonfunctional: ['a'] } })
      .includes('1 条用户故事'))
}

// ---------- 澄清问题 ----------
{
  const qs = clarifyQuestions({
    questions: [
      { id: 'q1', question: '工单从哪来？', why: '决定要不要做导入', options: ['人工录入', '外部推送'], allow_free: true },
      { id: 'q2', text: '缺字段时怎么办？' },
    ],
  })
  assert('两道题', qs.length === 2)
  assert('候选项在', qs[0].options.length === 2)
  assert('为什么问也在', qs[0].why.includes('导入'))
  assert('text 也当问题', qs[1].question.includes('缺字段'))
  assert('没给 allow_free 默认允许自由填', qs[1].allow_free === true)
  assert('questions 为空是合法的', clarifyQuestions({ questions: [] }).length === 0)
  assert('没有 data 不炸', clarifyQuestions(null).length === 0)
}

// ---------- 规格与设计的分区 ----------
{
  const spec = specifySections({
    stories: [{ id: 'S1' }],
    nonfunctional: ['性能'],
    edge_cases: [],
  })
  assert('只留有内容的分区', spec.length === 2)
  assert('分区标题是人话', spec[0].title.includes('用户故事'))
  const design = designSections({ architecture: '单体', modules: [{ name: 'm' }], risks: [] })
  assert('架构在最前', design[0].key === 'architecture')
  assert('空分区被过滤', design.length === 2)
}

// ---------- 闸门 ----------
{
  assert('没给 gates 就放行', stageGate('specify', {}).ok === true)
  assert('gates 说不行就不行', stageGate('specify', { can_specify: false }).ok === false)
  assert('闸门理由说清是哪一步', stageGate('specify', { can_specify: false }).reason.includes('需求理解'))
  assert('闸门理由要说怎么办', gateReason('design').includes('需求规格'))
  assert('gates 说行就放行', stageGate('specify', { can_specify: true }).ok === true)
}

// ---------- 文件树 ----------
{
  const tree = buildFileTree([
    { id: 1, path: 'backend/app/main.py', size: 120 },
    { id: 2, path: 'backend/app/config.py', size: 60 },
    { id: 3, path: 'README.md', size: 900 },
  ])
  assert('顶层两个（目录 + 文件）', tree.length === 2)
  const dir = tree.find((n) => n.type === 'dir')
  // backend/app/main.py 是三级路径：backend → app → main.py
  assert('目录下还有一层', dir.children.length === 1)
  const sub = dir.children[0]
  assert('子目录里两个文件', sub.children.length === 2)
  const main = sub.children.find((c) => c.file && c.file.id === 1)
  assert('文件带原始行', !!main)
  assert('文件路径是完整相对路径', main && main.path === 'backend/app/main.py')
  assert('目录排在文件前面', tree[0].type === 'dir')
  assert('空文件列表不炸', buildFileTree(null).length === 0)
  assert('没有 path 的条目被忽略', buildFileTree([{ id: 9 }]).length === 0)
}

// ---------- doctor 文案（人话，不是机器名） ----------
{
  assert('missing 翻译成人话', doctorMissingText(['model_endpoint'])[0].includes('模型端点'))
  assert('没见过的键原样返回', doctorMissingText(['xxx']) [0] === 'xxx')
  assert('空 missing 不炸', doctorMissingText(null).length === 0)
  const sum = doctorSummary({ mode: 'offline', missing: ['model_endpoint'] })
  assert('离线用不了时说清怎么走', sum.includes('在线协同'))
  const okSum = doctorSummary({ mode: 'online', missing: [] })
  assert('在线且不缺时说可用', okSum.includes('可用'))
}

console.log('')
if (failed) {
  console.log('❌ ' + failed + ' 项未通过')
  process.exit(1)
}
console.log('✅ 软件开发工作台流水线纯函数断言全部通过')
