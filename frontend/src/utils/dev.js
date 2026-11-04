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
 *
 * ⚠️ 这里曾经有一个「假的 50% 兜底」：total 未知时返回 percent=50。
 * 后果是 —— 后端把作业包在 { job: ... } 里，前端忘了取 .job，
 * total 就永远是 undefined，于是进度条**永远停在 50%、文案永远是「进行中」**，
 * 作业其实早就 failed 了，页面从头到尾不报错。
 *
 * 所以规矩是：
 *   · total 未知 → 不给百分比，走**不确定态**（indeterminate），文案说「进行中…」；
 *   · total 已知 → 一律按 processed/total 算，不许拍脑袋；
 *   · failed → 终态，把 error 与 how_to_fix 交给界面显示，不能装作还在跑。
 */
export function jobProgress(job) {
  if (!job) {
    return { percent: 0, text: '排队中', done: false, failed: false, indeterminate: false }
  }
  const total = Number(job.total || 0)
  const processed = Number(job.processed || 0)
  const status = job.status || 'created'
  if (status === 'failed') {
    return {
      percent: 100,
      text: job.error || '失败',
      done: true,
      failed: true,
      indeterminate: false,
    }
  }
  if (status === 'done' || status === 'completed') {
    return { percent: 100, text: '已完成', done: true, failed: false, indeterminate: false }
  }
  if (!total) {
    // 不知道总量就不给百分比 —— 给一个假的 50% 比不给更害人
    return {
      percent: 0,
      text: job.current || '进行中…',
      done: false,
      failed: false,
      indeterminate: true,
    }
  }
  const percent = Math.min(99, Math.round((processed / total) * 100))
  return {
    percent: percent,
    text: job.current || (processed + '/' + total),
    done: false,
    failed: false,
    indeterminate: false,
  }
}

/* ============ 四阶段流水线 ============ */

/**
 * 四个阶段的顺序与名字。
 *
 * 顺序是**产品决定的**，不是后端返回什么就按什么排 ——
 * 「需求理解 → 需求补全 → 需求转化 → 项目生成」有严格的先后依赖，
 * 界面上必须按这个顺序呈现，用户才知道自己现在在哪一步。
 */
export const STAGE_KEYS = ['clarify', 'specify', 'design', 'implement']

export const STAGE_META = {
  clarify: {
    key: 'clarify',
    title: '需求理解',
    short: '理解',
    subtitle: '让模型先真正读懂需求，并提出必须由人回答的问题',
    action: '开始理解需求',
    rerun: '重新理解',
    deliverable: '需求理解摘要 + 澄清问题清单',
  },
  specify: {
    key: 'specify',
    title: '需求补全',
    short: '补全',
    subtitle: '把需求写成可验收的规格：用户故事、验收标准、数据模型与边界',
    action: '生成需求规格',
    rerun: '重新生成规格',
    deliverable: '需求规格（用户故事 / 验收标准 / 非功能需求 / 数据模型 / 边界 / 不做范围）',
  },
  design: {
    key: 'design',
    title: '需求转化',
    short: '转化',
    subtitle: '把规格变成设计：架构、模块、数据表、接口清单与任务拆解',
    action: '生成设计',
    rerun: '重新生成设计',
    deliverable: '架构设计 + 模块划分 + 数据表 + 接口清单 + 任务拆解',
  },
  implement: {
    key: 'implement',
    title: '项目生成',
    short: '生成',
    subtitle: '产出真正能跑的项目文件：源码、配置、README、测试与启动脚本',
    action: '生成项目',
    rerun: '重新生成项目',
    deliverable: '可运行的项目文件（源码 / 依赖 / README / 测试 / 启动脚本）',
  },
}

export function stageMeta(key) {
  return STAGE_META[key] || { key: key || '', title: key || '未知阶段', short: '', subtitle: '', action: '运行', rerun: '重新运行', deliverable: '' }
}

/**
 * 阶段状态。契约里定了五种，前端按这五种渲染，不自己发明。
 * pending（没做）/ running（正在跑）/ needs_input（等用户输入）/
 * done（做完了）/ failed（失败了，error 里说原因）。
 */
export const STAGE_STATUS = {
  pending: { label: '未开始', type: 'info' },
  running: { label: '进行中', type: 'primary' },
  needs_input: { label: '待你回答', type: 'warning' },
  done: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

export function stageStatus(status) {
  return statusInfo(STAGE_STATUS, status, '未开始')
}

/**
 * 阶段的一行人话摘要（左栏导航上显示）。
 *
 * 为什么要专门写这个：后端给的是结构化产出（stories / modules / risks…），
 * 直接甩给用户看等于没摘要。这里按阶段挑最能说明问题的一两样，
 * 拼成一句话；挑不出来就说「已完成 / 还没产出」，不编。
 */
export function stageSummary(stage) {
  if (!stage) return ''
  const status = stage.status || 'pending'
  if (status === 'failed') return stage.error || '这一步失败了'
  if (status === 'needs_input') {
    const n = clarifyQuestions(stage.data).length
    return n ? ('有 ' + n + ' 个问题等你回答') : '等你补充信息'
  }
  if (status === 'running') return '正在' + stageMeta(stage.key).short + '…'
  if (status !== 'done') return '还没开始'
  const data = stage.data || {}
  switch (stage.key) {
    case 'clarify': {
      const q = clarifyQuestions(data).length
      if (q) return ('提出了 ' + q + ' 个澄清问题')
      return '需求已经够清楚，无需澄清'
    }
    case 'specify': {
      const n = (data.stories || []).length
      return n ? (n + ' 条用户故事 · ' + (data.nonfunctional || []).length + ' 条非功能需求') : '规格已生成'
    }
    case 'design': {
      const m = (data.modules || []).length
      const t = (data.data_tables || []).length
      return (m ? m + ' 个模块' : '') + (t ? (m ? ' · ' : '') + t + ' 张表' : '') || '设计已生成'
    }
    case 'implement': {
      const n = (data.files || data.artifacts || []).length
      return n ? (n + ' 个项目文件') : '项目文件已生成'
    }
    default: {
      const text = planOutline(data)
      return text ? text.slice(0, 60) : '已完成'
    }
  }
}

/**
 * 澄清问题清单（契约：clarify.data.questions）。
 *
 * 每题带 id / question / why / options / allow_free。
 * questions 为空是**合法状态**（模型认为需求已经够清楚）——
 * 界面上要据此说「无需澄清」，不能当成出错。
 */
export function clarifyQuestions(data) {
  if (!data) return []
  const list = Array.isArray(data.questions) ? data.questions : []
  return list
    .filter((q) => q && (q.question || q.text))
    .map((q) => ({
      id: String(q.id || q.key || q.qid || ''),
      question: String(q.question || q.text || ''),
      why: String(q.why || q.reason || ''),
      options: Array.isArray(q.options) ? q.options.map(String) : [],
      allow_free: q.allow_free !== false,
      answer: String(q.answer || ''),
    }))
}

/** 需求规格的分区（契约：specify.data） */
export function specifySections(data) {
  const d = data || {}
  return [
    { key: 'stories', title: '用户故事与验收标准', type: 'stories', items: d.stories || [] },
    { key: 'nonfunctional', title: '非功能需求', type: 'list', items: d.nonfunctional || [] },
    { key: 'data_model', title: '数据模型', type: 'entities', items: d.data_model || [] },
    { key: 'edge_cases', title: '边界与异常', type: 'list', items: d.edge_cases || [] },
    { key: 'out_of_scope', title: '明确不做', type: 'list', items: d.out_of_scope || [] },
  ].filter((s) => s.items && s.items.length)
}

/** 设计分区（契约：design.data） */
export function designSections(data) {
  const d = data || {}
  return [
    { key: 'architecture', title: '整体架构', type: 'text', items: d.architecture || '' },
    { key: 'modules', title: '模块划分', type: 'modules', items: d.modules || [] },
    { key: 'data_tables', title: '数据表', type: 'tables', items: d.data_tables || [] },
    { key: 'apis', title: '接口清单', type: 'apis', items: d.apis || [] },
    { key: 'risks', title: '风险与取舍', type: 'list', items: d.risks || [] },
  ].filter((s) => s.items && s.items.length)
}

/**
 * 闸门：某个阶段现在能不能跑。
 *
 * 契约里 gates 形如 { can_specify, can_design, can_implement }。
 * 前端只负责**显示**能不能跑、为什么不能跑 ——
 * 真正的判定在后端（前端看不到状态机的全部真相）。
 */
export function stageGate(stageKey, gates) {
  const map = {
    clarify: 'can_clarify',
    specify: 'can_specify',
    design: 'can_design',
    implement: 'can_implement',
  }
  const key = map[stageKey]
  if (!key || !gates) return { ok: true, reason: '' }
  if (gates[key] === undefined) return { ok: true, reason: '' }
  if (gates[key]) return { ok: true, reason: '' }
  return { ok: false, reason: gateReason(stageKey) }
}

/**
 * 闸门拦下来时，给一句「为什么不能跑」。
 * 依据契约的状态机：上一阶段没完成就不许进下一阶段。
 */
export function gateReason(stageKey) {
  switch (stageKey) {
    case 'clarify':
      return '需求理解还没跑过，先点上面的「开始理解需求」。'
    case 'specify':
      return '需求理解还没完成（可能还有澄清问题没回答），先回答完再生成规格。'
    case 'design':
      return '需求规格还没产出，先完成「需求补全」。'
    case 'implement':
      return '设计还没产出，先完成「需求转化」。'
    default:
      return '上一阶段还没完成。'
  }
}

/**
 * 作业包装对象解包。
 *
 * 后端所有返回 { job: ... } 的接口都得先取 .job ——
 * 忘了取的后果很隐蔽：job.total 变成 undefined，
 * 进度条于是永远停在 50%（这个 bug 已经坑过一次）。
 * 这里统一收口，忘了 unpackJob 的地方一眼能看出来。
 */
export function unwrapJob(res) {
  if (!res) return null
  if (res.job) return res.job
  return res
}

/**
 * 作业失败时给用户看的处置建议。
 * 后端可能给数组，也可能给一句话；两种都认。
 */
export function jobHowToFix(job) {
  if (!job) return []
  const raw = job.how_to_fix || job.howToFix || job.detail
  if (!raw) return []
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean)
  if (typeof raw === 'string') return raw ? [raw] : []
  return []
}

/**
 * 项目文件树（契约：implement 的产物是 dev_artifact 行，
 * path = 项目内相对路径）。
 *
 * 这里把扁平的路径列表拼成目录树。
 * 平铺的文件列表在几十个文件时根本没法看，
 * 而「一个能跑的项目」动辄几十个文件。
 */
export function buildFileTree(files) {
  const list = Array.isArray(files) ? files : []
  const root = { name: '', path: '', type: 'dir', children: [], file: null }
  const dirs = new Map([['', root]])
  list.forEach((f) => {
    const path = String(f.path || f.filename || '')
    if (!path) return
    const parts = path.split('/').filter(Boolean)
    let parent = root
    let acc = ''
    parts.forEach((part, i) => {
      acc = acc ? acc + '/' + part : part
      const isFile = i === parts.length - 1
      if (isFile) {
        parent.children.push({
          name: part,
          path: acc,
          type: 'file',
          children: [],
          file: f,
        })
      } else {
        let dir = dirs.get(acc)
        if (!dir) {
          dir = { name: part, path: acc, type: 'dir', children: [], file: null }
          dirs.set(acc, dir)
          parent.children.push(dir)
        }
        parent = dir
      }
    })
  })
  const sort = (node) => {
    node.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    node.children.forEach(sort)
  }
  sort(root)
  return root.children
}

/* ============ 体检（doctor） ============ */

/**
 * 把 doctor 给的 missing 键翻译成人话。
 *
 * 为什么非要翻译：后端给的是 "model_endpoint" 这样的机器名，
 * 直接甩给用户等于什么都没说。这里的目标是让用户看完就知道
 * 「缺什么、为什么现在用不了、点了那个按钮之后会怎样」。
 */
const DOCTOR_MISSING_TEXT = {
  model_endpoint: '没有可用的模型端点（本地模型没配，模块也认不了系统里已配好的云端大模型）',
  model: '模型不可用',
  local_model: '本地模型端点没配',
  local_endpoint: '本地模型端点没配',
  github: 'GitHub 仓库没配（只有在线协同模式用得上）',
  'github.repos': 'GitHub 仓库没配（只有在线协同模式用得上）',
  web_search: '网络搜索没配',
  'web_search.endpoint': '网络搜索服务没配（不配就只用本地知识与 GitHub）',
  repo: '开源项目仓库没配',
}

export function doctorMissingText(missing) {
  const list = Array.isArray(missing) ? missing : (missing ? [missing] : [])
  return list.map((k) => DOCTOR_MISSING_TEXT[k] || String(k))
}

/**
 * 可选增强的中文名。
 *
 * 后端给的 label 已经是人话了，这里只是兜底：
 * 万一某个 key 后端没给 label，前端也不至于把 "github.repos" 甩到界面上。
 */
const DOCTOR_OPTIONAL_TEXT = {
  'github.repos': 'GitHub 开源项目取材（能直接读真实仓库，少走弯路）',
  github: 'GitHub 开源项目取材（能直接读真实仓库，少走弯路）',
  'web_search.endpoint': '网络知识检索（能顺手查最新的框架文档与业界做法）',
  web_search: '网络知识检索（能顺手查最新的框架文档与业界做法）',
}

/**
 * 把 doctor 的 optional 列表翻译成能直接渲染的 [{label, how_to_fix}]。
 *
 * 为什么要单独一个函数、而不是在页面里 map：
 *   「可选增强」和「真正缺的东西」是两回事 ——
 *   缺的是**不开工就做不了**（模型端点、知识库），
 *   可选的是**配了更好**（GitHub 仓库、网络搜索）。
 *   之前后端把后两者也放进 missing，于是页面一片告警色，
 *   用户以为模块坏了，其实照样能生成项目。
 */
export function doctorOptionalText(optional) {
  const list = Array.isArray(optional) ? optional : (optional ? [optional] : [])
  return list.map((o) => {
    if (typeof o === 'string') {
      return { key: o, label: DOCTOR_OPTIONAL_TEXT[o] || String(o), how_to_fix: '' }
    }
    const key = (o && o.key) || ''
    return {
      key,
      label: (o && o.label) || DOCTOR_OPTIONAL_TEXT[key] || String(key),
      how_to_fix: (o && o.how_to_fix) || '',
    }
  })
}

/**
 * 「其实是增强、不是阻断」的键。
 *
 * 为什么前端也要认这一份：后端的新契约把这几项挪进了 optional，
 * 但旧后端（还没升级的那台）把它们留在 missing 里 ——
 * 如果前端只信后端，模块就会在旧后端上继续显示成「还差这些才能开工」，
 * 而用户明明能开工。这是「兼容性兜底」，后端升级后这段逻辑自动什么都不做。
 */
const DOCTOR_OPTIONAL_KEYS = ['github.repos', 'web_search.endpoint', 'github', 'web_search']

/**
 * 把 doctor 拆成「阻断项」和「可选增强」两份。
 *
 * 返回：
 *   blocking: [{key, text, how_to_fix}] —— 不配就真的做不了
 *   optional: [{key, label, how_to_fix}] —— 配了更好，不配照样开工
 *
 * how_to_fix 与 missing 是**一一对应**的（后端契约如此），
 * 所以这里按下标配对，拆开之后每条阻断项仍带着自己的修法。
 */
export function doctorSplit(doctor) {
  const missing = Array.isArray(doctor && doctor.missing) ? doctor.missing : []
  const fixes = Array.isArray(doctor && doctor.how_to_fix) ? doctor.how_to_fix : []
  const blocking = []
  const optional = doctorOptionalText(doctor && doctor.optional)
  const seen = new Set(optional.map((o) => o.key))
  missing.forEach((k, i) => {
    if (DOCTOR_OPTIONAL_KEYS.includes(k)) {
      // 旧后端：增强项混在 missing 里 → 挪进 optional，别当成阻断项
      if (!seen.has(k)) {
        seen.add(k)
        optional.push({
          key: k,
          label: DOCTOR_OPTIONAL_TEXT[k] || String(k),
          how_to_fix: fixes[i] || '',
        })
      }
      return
    }
    blocking.push({
      key: k,
      text: DOCTOR_MISSING_TEXT[k] || String(k),
      how_to_fix: fixes[i] || '',
    })
  })
  return { blocking, optional }
}

/**
 * doctor 的一句话结论。
 *
 * 口径：只有**阻断项**（missing）才影响「能不能开工」。
 *   阻断项为空 → 结论是「可以开工」，哪怕可选增强一个都没配；
 *   阻断项非空 → 才说「还差这些才能开工」，并把修法说清楚。
 * 可选增强最多在附注里提一句，绝不能混进「还差这些」里。
 *
 * 离线模式下没配本地模型 → 说清「可以切在线协同」，别只说「不可用」。
 */
export function doctorSummary(doctor) {
  if (!doctor) return ''
  const mode = doctor.mode || ''
  const { blocking, optional } = doctorSplit(doctor)
  if (!blocking.length) {
    const base = mode === 'online'
      ? '在线协同模式：核心能力可用，可以开工。'
      : '离线闭环模式：本地模型已就绪，可以开工。'
    const note = optional.length
      ? '还可以配这些增强（不配也能开工，配了更好）：' + optional.map((o) => o.label).join('、')
      : ''
    return [base, note].filter(Boolean).join(' ')
  }
  const head = '还差这些才能开工：'
  const tail = mode === 'offline'
    ? '系统里已经配好的云端大模型在在线协同模式下可直接用。'
    : ''
  return [head + blocking.map((b) => b.text).join('；'), tail].filter(Boolean).join(' ')
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
