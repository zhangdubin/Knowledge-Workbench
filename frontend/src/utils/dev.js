/**
 * 软件开发模块的纯函数
 *
 * 为什么单独抽出来：
 *   模式/状态的文案、置信度的显示、方案 JSON 的容错解析、
 *   任务树的拼装 —— 这些是「算出来给人看的」逻辑，
 *   散在 .vue 里就只能靠手点页面验证，出错也没人拦。
 *   抽成纯函数之后可以直接用 node 跑断言，不用起浏览器。
 *
 * 口径与后端保持一致：后端 services/dev.py 里的常量是权威，
 * 这里只做展示层翻译，不自己另立一套。
 */

/* ============ 模式 ============ */

export const MODE_OFFLINE = 'offline'
export const MODE_ONLINE = 'online'

export const MODE_LABEL = {
  offline: '离线闭环',
  online: '在线协同',
}

export const MODE_DESC = {
  offline: '只用本机知识与本地模型，全程不发一个外网请求',
  online: '大模型 + GitHub 开源项目 + 网络知识 + 喂养的源码一起用',
}

export function modeLabel(mode) {
  return MODE_LABEL[mode] || mode || '未设置'
}

export function modeDesc(mode) {
  return MODE_DESC[mode] || ''
}

export function modeType(mode) {
  return mode === MODE_ONLINE ? 'success' : 'info'
}

/* ============ 状态 ============ */

export const PROJECT_STATUS = {
  draft: { label: '草稿', type: 'info' },
  planning: { label: '规划中', type: 'warning' },
  building: { label: '实现中', type: 'primary' },
  produced: { label: '已产出', type: 'success' },
  archived: { label: '归档', type: 'info' },
}

export const TASK_STATUS = {
  todo: { label: '待办', type: 'info' },
  doing: { label: '实现中', type: 'primary' },
  done: { label: '已完成', type: 'success' },
  blocked: { label: '被阻塞', type: 'danger' },
}

export const ARTIFACT_SOURCE = {
  model: { label: '模型生成', type: 'primary' },
  knowledge: { label: '知识库摘取', type: 'success' },
  manual: { label: '人工上传', type: 'info' },
}

export const CITATION_KIND = {
  gene: { label: '养料库基因', type: 'success' },
  doc: { label: '文档知识', type: 'info' },
  github: { label: '开源项目', type: 'primary' },
  web: { label: '网络知识', type: 'warning' },
}

export function statusInfo(map, key, fallback) {
  const hit = map[key]
  if (hit) return { label: hit.label, type: hit.type }
  return { label: fallback || key || '未知', type: 'info' }
}

export function projectStatus(status) {
  return statusInfo(PROJECT_STATUS, status)
}

export function taskStatus(status) {
  return statusInfo(TASK_STATUS, status)
}

export function artifactSource(source) {
  return statusInfo(ARTIFACT_SOURCE, source)
}

export function citationKind(kind) {
  return statusInfo(CITATION_KIND, kind)
}

/* ============ 数字与置信度 ============ */

/**
 * 置信度显示：0..1 转成百分比。
 * 空值显示「—」而不是 0% ——
 * 「没有置信度」和「置信度是 0」是两回事，不能混着显示。
 */
export function formatPercent(value, digits) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return (n * 100).toFixed(digits === undefined ? 0 : digits) + '%'
}

/**
 * 分数档位：按 0..1 给语义分档，用于配色。
 * 阈值跟养料库的评分分档同一口气：0.6 以下算弱，0.8 以上算强。
 */
export function scoreLevel(value) {
  const n = Number(value)
  if (value === null || value === undefined || Number.isNaN(n)) return 'unknown'
  if (n >= 0.8) return 'high'
  if (n >= 0.6) return 'mid'
  return 'low'
}

/* ============ 方案 JSON 的容错解析 ============ */

const FENCE = String.fromCharCode(96).repeat(3)

/**
 * 从模型回复里抠出 JSON。
 *
 * 模型经常把 JSON 包在代码块里，或者末尾多带一个逗号 ——
 * 直接 JSON.parse 会炸，炸了就等于「生成失败」，但其实内容是好的。
 * 这里做三层容错：剥代码块、抠第一对花括号、去尾逗号。
 */
export function parseJsonBlock(text) {
  if (!text) return null
  let s = String(text).trim()
  const fenced = s.match(new RegExp(FENCE + '[a-zA-Z]*\\n?([\\s\\S]*?)' + FENCE))
  if (fenced && fenced[1]) s = fenced[1].trim()
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start >= 0 && end > start) s = s.slice(start, end + 1)
  s = s.replace(/,\s*([}\]])/g, '$1')
  try {
    return JSON.parse(s)
  } catch (e) {
    return null
  }
}

/**
 * 方案对象的要点摘要（一行话）。
 * 模型返回的字段名不统一（有 summary / goal / idea），
 * 只认得几个常见键；都认不出就返回空串 ——
 * 宁可空着，也不要给用户看一句编出来的话。
 */
export function planOutline(plan) {
  if (!plan || typeof plan !== 'object') return ''
  const keys = ['summary', 'goal', 'idea', 'description', 'outline', 'title']
  for (const k of keys) {
    const v = plan[k]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return ''
}

/**
 * 方案里的任务清单。
 * 兼容两种形状：{tasks: [...]} 与直接是一个数组。
 */
export function planTasks(plan) {
  if (Array.isArray(plan)) return plan
  if (plan && Array.isArray(plan.tasks)) return plan.tasks
  return []
}

/* ============ 任务树 ============ */

/**
 * 把任务按 depends_on 拼成树。
 *
 * 依赖关系本来就可能是「多父」（一个任务依赖两件事），
 * 硬拼成树会丢依赖。这里给的是「谁依赖我」的反向视图：
 * 父节点 = 被依赖的事，子节点 = 依赖它的活。
 * 目的是让人一眼看出「这件事卡住了谁」。
 */
export function buildTaskTree(tasks) {
  const list = Array.isArray(tasks) ? tasks : []
  const byId = new Map()
  list.forEach((t) => byId.set(t.id, Object.assign({}, t, { children: [], blockers: [] })))
  const roots = []
  byId.forEach((node) => {
    const deps = Array.isArray(node.depends_on) ? node.depends_on : []
    let attached = false
    deps.forEach((depId) => {
      const parent = byId.get(depId)
      if (parent && parent !== node) {
        parent.children.push(node)
        node.blockers.push(depId)
        attached = true
      }
    })
    if (!attached) roots.push(node)
  })
  return roots
}

/** 拍平成一维（带深度），用于「按顺序生成」这类线性操作 */
export function flattenTaskTree(nodes, depth, out) {
  const level = depth || 0
  const acc = out || []
  ;(nodes || []).forEach((n) => {
    acc.push(Object.assign({}, n, { depth: level }))
    flattenTaskTree(n.children, level + 1, acc)
  })
  return acc
}

/**
 * 生成顺序：先做没有依赖的，再做依赖已完成的。
 * 依赖成环（互相依赖）时退化成原顺序，不能死循环。
 */
export function sortTasksForGeneration(tasks) {
  const list = Array.isArray(tasks) ? tasks.slice() : []
  const done = new Set()
  const out = []
  const pending = new Set(list.map((t) => t.id))
  let guard = 0
  while (pending.size && guard++ < 1000) {
    const ready = list.filter((t) =>
      pending.has(t.id) &&
      (t.depends_on || []).every((d) => done.has(d) || !pending.has(d)))
    if (!ready.length) break
    ready.forEach((t) => {
      out.push(t)
      done.add(t.id)
      pending.delete(t.id)
    })
  }
  // 剩下的多半是依赖成环的：按原顺序补上，别把用户的任务弄丢了
  list.forEach((t) => { if (pending.has(t.id)) out.push(t) })
  return out
}

/* ============ 引用 ============ */

/**
 * 引用按来源分组。
 * 一次生成往往同时引了基因、文档、网络知识，
 * 混在一起看不出「这条结论到底靠什么撑起来」。
 */
export function groupCitations(citations) {
  const list = Array.isArray(citations) ? citations : []
  const groups = new Map()
  list.forEach((c) => {
    const kind = c.kind || 'other'
    if (!groups.has(kind)) {
      groups.set(kind, { kind: kind, label: citationKind(kind).label, items: [] })
    }
    groups.get(kind).items.push(c)
  })
  return Array.from(groups.values())
}

/* ============ 安全体检 ============ */

export const WARNING_SEVERITY = {
  block: { label: '必须处理', type: 'danger' },
  warn: { label: '需要注意', type: 'warning' },
  info: { label: '提示', type: 'info' },
}

export function warningSeverity(w) {
  const sev = (w && w.severity) || 'warn'
  return statusInfo(WARNING_SEVERITY, sev, '提示')
}

/**
 * 一句话说明体检结果，带上行号 ——
 * 用户得知道去哪儿改，不然「有告警」等于没说。
 */
export function describeWarning(w) {
  if (!w) return ''
  const line = w.line ? ('第 ' + w.line + ' 行') : ''
  return [w.rule || '', line, w.message || ''].filter(Boolean).join(' · ')
}

/* ============ 后台作业 ============ */

/**
 * 作业进度：百分比 + 一句话状态。
 * 后端作业有 created/running/done/failed 几种状态，
 * 这里统一成「跑完了没有、跑到哪儿了」。
 */
export function jobProgress(job) {
  if (!job) return { percent: 0, text: '排队中', done: false, failed: false }
  const total = Number(job.total || 0)
  const processed = Number(job.processed || 0)
  const status = job.status || 'created'
  if (status === 'failed') {
    return { percent: 100, text: job.error || '失败', done: true, failed: true }
  }
  if (status === 'done' || status === 'completed') {
    return { percent: 100, text: '已完成', done: true, failed: false }
  }
  if (!total) {
    return { percent: 50, text: job.current || '进行中', done: false, failed: false }
  }
  const percent = Math.min(99, Math.round((processed / total) * 100))
  return {
    percent: percent,
    text: job.current || (processed + '/' + total),
    done: false,
    failed: false,
  }
}

/* ============ 产出物 ============ */

/**
 * 产出物概览：几个文件、多少字、有没有告警、有没有入库。
 * 卡片上就显示这一行。
 */
export function summarizeArtifacts(artifacts) {
  const list = Array.isArray(artifacts) ? artifacts : []
  let bytes = 0
  let warned = 0
  let imported = 0
  list.forEach((a) => {
    bytes += Number(a.size || 0)
    if ((a.warnings || []).length) warned += 1
    if (a.document_id) imported += 1
  })
  let text = list.length + ' 个文件 · ' + formatBytes(bytes)
  if (warned) text += ' · ' + warned + ' 个有告警'
  if (imported) text += ' · ' + imported + ' 个已入库'
  return { count: list.length, bytes: bytes, warned: warned, imported: imported, text: text }
}

/**
 * 字节数显示。
 * 产出物都是代码文件，一般不大，但日志类文件可能上兆。
 */
export function formatBytes(n) {
  const num = Number(n || 0)
  if (!num) return '0 B'
  if (num < 1024) return num + ' B'
  if (num < 1024 * 1024) return (num / 1024).toFixed(1) + ' KB'
  return (num / 1024 / 1024).toFixed(1) + ' MB'
}
