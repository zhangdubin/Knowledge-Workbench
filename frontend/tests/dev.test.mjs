// 软件开发模块的纯函数断言
// 覆盖 utils/dev.js：模式/状态文案、置信度、方案 JSON 容错解析、
// 任务树、生成顺序、引用分组、作业进度、产出物概览
import {
  MODE_LABEL, PROJECT_STATUS, TASK_STATUS, ARTIFACT_SOURCE, CITATION_KIND,
  modeLabel, modeDesc, modeType, projectStatus, taskStatus,
  artifactSource, citationKind, statusInfo,
  formatPercent, scoreLevel,
  parseJsonBlock, planOutline, planTasks,
  buildTaskTree, flattenTaskTree, sortTasksForGeneration,
  groupCitations, warningSeverity, describeWarning,
  jobProgress, summarizeArtifacts, formatBytes,
} from '../src/utils/dev.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log((ok ? '✅' : '❌') + ' ' + name + (detail ? '  ' + detail : ''))
}

// ---------- 模式与状态文案 ----------
{
  assert('离线模式有中文名', modeLabel('offline') === MODE_LABEL.offline)
  assert('在线模式有中文名', modeLabel('online') === MODE_LABEL.online)
  assert('未知模式原样返回', modeLabel('mystery') === 'mystery')
  assert('空模式有兜底文案', modeLabel('') === '未设置')
  assert('离线有说明文字', modeDesc('offline').includes('不发'))
  assert('在线模式标成成功色', modeType('online') === 'success')
  assert('离线模式标成中性色', modeType('offline') === 'info')
  assert('项目状态取得到', projectStatus('building').label === PROJECT_STATUS.building.label)
  assert('未知任务状态不炸', taskStatus('nope').label === 'nope')
  assert('产出物来源有区分', artifactSource('manual').label !== artifactSource('model').label)
  assert('引用种类有区分', citationKind('gene').label !== citationKind('web').label)
  assert('未知键回落到给定兜底', statusInfo({}, 'x', '兜底').label === '兜底')
  // 任务状态键名跟后端一致：todo 而不是 pending
  assert('任务状态键是 todo', !!TASK_STATUS.todo)
  assert('任务状态键是 doing', !!TASK_STATUS.doing)
  assert('任务状态键是 blocked', !!TASK_STATUS.blocked)
}

// ---------- 置信度与分数档位 ----------
{
  assert('0.78 显示成 78%', formatPercent(0.78) === '78%')
  assert('空值显示破折号', formatPercent(null) === '—')
  assert('undefined 显示破折号', formatPercent(undefined) === '—')
  assert('非数字显示破折号', formatPercent('abc') === '—')
  assert('保留一位小数', formatPercent(0.626, 1) === '62.6%')
  assert('0 跟空值不一样', formatPercent(0) === '0%')
  assert('高分档', scoreLevel(0.9) === 'high')
  assert('中分档', scoreLevel(0.7) === 'mid')
  assert('低分档', scoreLevel(0.2) === 'low')
  assert('空值是未知档', scoreLevel(null) === 'unknown')
}

// ---------- 方案 JSON 的容错解析 ----------
{
  assert('裸 JSON 能解', parseJsonBlock('{"a":1}').a === 1)
  // 模型经常把 JSON 包在代码块里，解不出来就等于白生成
  const fence = String.fromCharCode(96).repeat(3)
  assert('剥代码块后能解',
    parseJsonBlock(fence + 'json\n{"a":2}\n' + fence).a === 2)
  assert('带前后废话也能抠出来',
    parseJsonBlock('好的，这是方案：{"a":3} 希望有用').a === 3)
  assert('尾逗号能容错', parseJsonBlock('{"a":4,}').a === 4)
  assert('不是 JSON 返回 null', parseJsonBlock('完全不是 JSON') === null)
  assert('空文本返回 null', parseJsonBlock('') === null)
  assert('空值返回 null', parseJsonBlock(null) === null)
  // 方案摘要：认不出就返回空串，不能编一句出来
  assert('摘要有内容', planOutline({ summary: '做个对账工具' }) === '做个对账工具')
  assert('认不出时返回空', planOutline({ foo: 'bar' }) === '')
  assert('空方案返回空', planOutline(null) === '')
  assert('任务清单兼容数组', planTasks([{ title: 'a' }]).length === 1)
  assert('任务清单兼容对象', planTasks({ tasks: [{ title: 'a' }] }).length === 1)
  assert('没有任务给空数组', planTasks({}).length === 0)
}

// ---------- 任务树 ----------
{
  const tasks = [
    { id: 1, title: '搭骨架', depends_on: [] },
    { id: 2, title: '比对逻辑', depends_on: [1] },
    { id: 3, title: '出报告', depends_on: [2] },
  ]
  const roots = buildTaskTree(tasks)
  assert('只有一个根', roots.length === 1)
  assert('根是第一个任务', roots[0].id === 1)
  assert('子节点挂上了', roots[0].children[0].id === 2)
  const flat = flattenTaskTree(roots)
  assert('拍平后有三个', flat.length === 3)
  assert('深度逐级递增', flat[0].depth === 0 && flat[1].depth === 1 && flat[2].depth === 2)

  // 顺序：无依赖的先做
  const order = sortTasksForGeneration([
    { id: 3, depends_on: [2] },
    { id: 2, depends_on: [1] },
    { id: 1, depends_on: [] },
  ])
  assert('生成顺序按依赖排', order.map((t) => t.id).join(',') === '1,2,3')

  // 依赖成环不能死循环，也不能把任务弄丢
  const cyclic = sortTasksForGeneration([
    { id: 1, depends_on: [2] },
    { id: 2, depends_on: [1] },
  ])
  assert('依赖成环不丢任务', cyclic.length === 2)

  // 依赖指向不存在的任务时，当成无依赖
  const ghost = buildTaskTree([{ id: 9, depends_on: [999] }])
  assert('悬空依赖不炸', ghost.length === 1)
  assert('空任务列表返回空', buildTaskTree([]).length === 0)
  assert('非数组不炸', buildTaskTree(null).length === 0)
}

// ---------- 引用分组 ----------
{
  const groups = groupCitations([
    { id: 1, kind: 'gene', title: '基因A' },
    { id: 2, kind: 'doc', title: '文档B' },
    { id: 3, kind: 'gene', title: '基因C' },
  ])
  assert('分成两组', groups.length === 2)
  const geneGroup = groups.find((g) => g.kind === 'gene')
  assert('基因组有两条', geneGroup.items.length === 2)
  assert('组有中文标签', geneGroup.label === CITATION_KIND.gene.label)
  assert('空引用返回空数组', groupCitations([]).length === 0)
  assert('非数组不炸', groupCitations(null).length === 0)
}

// ---------- 安全体检文案 ----------
{
  assert('阻断级是危险色', warningSeverity({ severity: 'block' }).type === 'danger')
  assert('告警级是警告色', warningSeverity({ severity: 'warn' }).type === 'warning')
  assert('没给级别默认告警', warningSeverity({}).type === 'warning')
  assert('文案带行号', describeWarning({ rule: '硬编码密钥', line: 3, message: '换掉' }).includes('第 3 行'))
  assert('空告警不炸', describeWarning(null) === '')
}

// ---------- 作业进度 ----------
{
  assert('排队中', jobProgress(null).percent === 0)
  assert('失败是终态', jobProgress({ status: 'failed', error: '炸了' }).failed === true)
  assert('完成是终态', jobProgress({ status: 'done' }).done === true)
  const half = jobProgress({ status: 'running', total: 10, processed: 5 })
  assert('进度按比例算', half.percent === 50)
  assert('没跑完不算完成', half.done === false)
  const over = jobProgress({ status: 'running', total: 10, processed: 10 })
  assert('没完成时封顶 99', over.percent === 99)
}

// ---------- 产出物概览 ----------
{
  const arts = [
    { id: 1, size: 100, warnings: [], document_id: 3 },
    { id: 2, size: 2048, warnings: [{ severity: 'warn' }], document_id: null },
  ]
  const sum = summarizeArtifacts(arts)
  assert('统计两个文件', sum.count === 2)
  assert('统计字节数', sum.bytes === 2148)
  assert('统计有告警的', sum.warned === 1)
  assert('统计已入库的', sum.imported === 1)
  assert('概览文案带文件数', sum.text.includes('2 个文件'))
  assert('空产出物不炸', summarizeArtifacts(null).count === 0)
  assert('字节格式化', formatBytes(0) === '0 B')
  assert('字节格式化 KB', formatBytes(2048) === '2.0 KB')
  assert('字节格式化 MB', formatBytes(3 * 1024 * 1024) === '3.0 MB')
}

console.log('')
if (failed) {
  console.log('❌ ' + failed + ' 项未通过')
  process.exit(1)
}
console.log('✅ 软件开发模块纯函数断言全部通过')
