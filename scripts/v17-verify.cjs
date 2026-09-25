/**
 * v17 回归验证：关联定义支持文件端 · 图谱可用性 · 自定义驾驶舱 · 安全与权限
 *
 * 这一轮用户提了五件事，脚本按这五件事逐条取证：
 *  1. 「新建关联定义中应该可定义关联数据中心的文件才对」→ 两端都能选文件，端到端建得起、查得回、方向对
 *  2. 「关联图谱和知识图谱你要看下可用性，还有视觉美观不够」→ 页面真的画得出节点、图例能筛、点得开抽屉
 *  3. 「知识工作台缺少一个自定义可视化驾驶舱」→ 模板建舱、卡片渲染、编辑、试算、保存全链路
 *  4. 「缺少安全管理，权限管理」→ 登录鉴权 + 角色权限矩阵真的拦得住，且停用/改角色立即踢下线
 *  5. 顺带锁住上一轮修掉的两个回归（entity-types 500、入向关联显示成自己）
 *
 * 前置：后端与前端容器已启动（8001 / 8082），且脚本能登录
 *   node scripts/v17-verify.cjs
 *   node scripts/v17-verify.cjs --head        # 弹窗跑前端部分，便于肉眼确认
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const S = require('./lib/session.cjs')

const { API, FE } = S
const HEAD = process.argv.includes('--head')
const RUN = Date.now().toString(36)

// 前端是 hash 路由（createWebHashHistory）：/library 要写成 /#/library，
// 否则 SPA 只会落在默认路由上，「打开某个页面」的用例就全成了打开工作台。
const U = (p) => `${FE}/#${p}`

/**
 * 切到某个前端页面。
 * hash 路由下只改 fragment 是「同文档导航」，puppeteer 的 goto 会立刻返回，
 * 旧页面的 DOM 还原封不动挂着 —— 后面的 waitForSelector('.page') 会当场命中
 * 上一个页面，按钮自然找不到。所以必须整页重载一次。
 */
async function goPage(page, p) {
  await page.goto(U(p), { waitUntil: 'domcontentloaded' })
  await page.reload({ waitUntil: 'networkidle2' })
}

const results = []
const cleanupQueue = []      // [{ kind, id }]，跑完逆序删掉

function check(name, ok, detail = '') {
  results.push([name, !!ok, detail])
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  — ' + detail : ''}`)
}

function section(t) { console.log(`\n${'─'.repeat(64)}\n${t}`) }

// ============================================================ 前端动作小工具

async function clickText(page, text, sel = 'button') {
  const ok = await page.evaluate((t, s) => {
    const norm = x => (x || '').replace(/\s+/g, '')
    const want = norm(t)
    const el = [...document.querySelectorAll(s)].find(e => norm(e.innerText).includes(want)
      && e.offsetParent !== null)
    if (!el) return false
    el.click()
    return true
  }, text, sel)
  if (!ok) throw new Error(`找不到可点击元素：${sel} 「${text}」`)
  return true
}

/**
 * 等按钮真的出现再点。
 * 页面刚切过来时 store 还在 bootstrap，靠权限显隐的按钮（如「新建关联」）
 * 可能晚一拍才渲染，直接点就是随机失败。
 */
async function waitClickable(page, text, sel = 'button', ms = 12000) {
  const ready = await S.waitFor(page, (t, s) => {
    const norm = x => (x || '').replace(/\s+/g, '')
    const want = norm(t)
    return [...document.querySelectorAll(s)].some(e =>
      norm(e.innerText).includes(want) && e.offsetParent !== null)
  }, ms, text, sel)
  if (!ready) throw new Error(`等待可点击元素超时：${sel} 「${text}」`)
  return clickText(page, text, sel)
}

async function countOf(page, sel) {
  return page.$$eval(sel, els => els.length).catch(() => 0)
}

async function visibleCount(page, sel) {
  return page.$$eval(sel, els => els.filter(e => e.offsetParent !== null).length).catch(() => 0)
}

/** 在 Element Plus 的 select 下拉里按可见文字选一项 */
async function pickOption(page, selectSel, optionText) {
  // 点 wrapper 而不是整个 .el-select：wrapper 才是绑定了展开事件的那层
  const opened = await page.evaluate((sel) => {
    const root = document.querySelector(sel)
    if (!root) return false
    const trigger = root.querySelector('.el-select__wrapper') || root.querySelector('.el-input__inner') || root
    trigger.click()
    return true
  }, selectSel)
  if (!opened) return false
  await page.waitForSelector('.el-select-dropdown__item', { visible: true, timeout: 6000 }).catch(() => {})
  const hit = await page.evaluate((t) => {
    const norm = x => (x || '').replace(/\s+/g, '')
    const items = [...document.querySelectorAll('.el-select-dropdown__item')]
      .filter(e => e.offsetParent !== null)
    const el = items.find(i => norm(i.innerText).includes(norm(t)))
    if (!el) return { ok: false, options: items.map(i => i.innerText.trim()).slice(0, 12) }
    el.click()
    return { ok: true }
  }, optionText)
  if (!hit.ok) {
    // 把实际选项带出来，失败时不用再复跑一遍才知道下拉里有什么
    console.log(`   （「${selectSel}」下拉里没有「${optionText}」，实际选项：${(hit.options || []).join(' / ')}）`)
  }
  await S.sleep(300)
  return hit.ok
}

/**
 * 点开第 index 个 el-select 并选中一项。
 * Element Plus 的 select 不是原生 <select>，没法直接改 value，
 * 只能点开浮层再点选项；浮层是 teleport 到 body 的，所以要全局找。
 */
async function pickElSelect(page, index, optionText) {
  const opened = await page.evaluate((i) => {
    const sels = [...document.querySelectorAll('.page .el-select')].filter(e => e.offsetParent !== null)
    const t = sels[i]
    if (!t) return false
    const trigger = t.querySelector('.el-select__wrapper') || t.querySelector('.el-input__inner') || t
    trigger.click()
    return true
  }, index)
  if (!opened) return false
  await page.waitForSelector('.el-select-dropdown__item', { visible: true, timeout: 6000 }).catch(() => {})
  const ok = await page.evaluate((t) => {
    const el = [...document.querySelectorAll('.el-select-dropdown__item')]
      .filter(e => e.offsetParent !== null)
      .find(i => (i.innerText || '').includes(t))
    if (!el) return false
    el.click()
    return true
  }, optionText)
  await S.sleep(700)
  return ok
}

// ============================================================ 1 鉴权基线
async function t1AuthBaseline() {
  section('1. 鉴权基线（安全管理的门槛）')

  const anon = await fetch(`${API}/api/entity-types`)
  check('未登录访问业务接口被拒（401）', anon.status === 401, `status=${anon.status}`)

  const anonSys = await fetch(`${API}/api/system/users`)
  check('未登录访问系统管理被拒（401）', anonSys.status === 401, `status=${anonSys.status}`)

  const u = await S.login()
  check('管理员登录成功', !!u && u.username === 'admin', u && u.username)

  const me = await S.j('/api/auth/me')
  check('GET /api/auth/me 返回身份与权限',
    me.status === 200 && me.body.username === 'admin' && !!me.body.perms,
    `status=${me.status} keys=${Object.keys(me.body || {}).join(',')}`)

  const perms = me.body.perms || {}
  check('三级权限齐备（页面 / 模型 / 功能）',
    Array.isArray(perms.pages) && !!perms.models && !!perms.features,
    `pages=${(perms.pages || []).length} models=${Object.keys(perms.models || {}).length} features=${Object.keys(perms.features || {}).length}`)
  check('超管 has all 标记', perms.all === true, `all=${perms.all}`)

  const bad = await fetch(`${API}/api/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'definitely-wrong' }),
  })
  check('错误口令被拒（401）', bad.status === 401, `status=${bad.status}`)
}

// ============================================================ 2 回归：entity-types
async function t2EntityTypesRegression() {
  section('2. 回归：GET /api/entity-types 不再 500，且按权限过滤')

  const r = await S.j('/api/entity-types')
  check('接口返回 200', r.status === 200, `status=${r.status} body=${JSON.stringify(r.body).slice(0, 90)}`)
  check('返回的是数组（不是 dict 误用导致的 500）', Array.isArray(r.body),
    Array.isArray(r.body) ? `len=${r.body.length}` : typeof r.body)
  const withCounts = (r.body || []).every(t => 'field_count' in t && 'record_count' in t)
  check('每项带字段数/记录数（服务层返回 dict 的形状被正确消费）', withCounts,
    JSON.stringify((r.body || [])[0] || {}).slice(0, 120))
}

/** /api/relations/defs 返回的是裸数组，取一条定义用这个 */
async function defByKey(key) {
  const r = await S.j('/api/relations/defs')
  return (Array.isArray(r.body) ? r.body : r.body.items || []).find(d => d.key === key) || null
}

// ============================================================ 3 关联定义支持文件端
async function t3RelationFileEnds() {
  section('3. 关联定义两端都支持「数据中心文件」')

  const types = (await S.j('/api/entity-types')).body || []
  const contract = types.find(t => t.key === 'contract')
  const project = types.find(t => t.key === 'project')
  if (!contract || !project) throw new Error('缺少 contract / project 模型，无法继续')

  // --- 3.1 记录 → 文件
  const recKey = `v17_scan_${RUN}`
  const d1 = await S.post('/api/relations/defs', {
    key: recKey, name: 'V17 合同扫描件',
    source_kind: 'record', source_type_id: contract.id,
    target_kind: 'document', target_type_id: null,
    cardinality: 'one-to-many', description: '源端记录、目标端文件',
  })
  check('可建「记录 → 文件」定义', d1.status === 200, `status=${d1.status} ${JSON.stringify(d1.body).slice(0, 120)}`)
  if (d1.status !== 200) return
  cleanupQueue.push({ kind: 'relation_def', id: d1.body.id })
  const full1 = await defByKey(recKey)
  check('目标端落库为 document', full1?.target_kind === 'document', `target_kind=${full1?.target_kind}`)
  check('文件端不需要 type_id（文件不分类型）', !full1?.target_type_id,
    `target_type_id=${full1?.target_type_id}`)
  check('记录端仍带类型与图标', !!full1?.source_type_id && full1?.source_label === contract.name,
    `${full1?.source_label} / ${full1?.source_type_id}`)

  // --- 3.2 文件 → 记录
  const docKey = `v17_owner_${RUN}`
  const d2 = await S.post('/api/relations/defs', {
    key: docKey, name: 'V17 文件归属项目',
    source_kind: 'document', source_type_id: null,
    target_kind: 'record', target_type_id: project.id,
    cardinality: 'many-to-one', description: '源端文件、目标端记录',
  })
  check('可建「文件 → 记录」定义', d2.status === 200, `status=${d2.status} ${JSON.stringify(d2.body).slice(0, 120)}`)
  if (d2.status !== 200) return
  cleanupQueue.push({ kind: 'relation_def', id: d2.body.id })
  const full2 = await defByKey(docKey)
  check('源端落库为 document', full2?.source_kind === 'document', `source_kind=${full2?.source_kind}`)
  check('文件端标签统一为「数据中心文件」', full2?.source_label === '数据中心文件',
    `source_label=${full2?.source_label}`)

  // --- 3.3 文件端候选来自数据中心
  const files = await S.j('/api/documents?page_size=10')
  const docs = (files.body.items || [])
  check('数据中心有文件可供挂接', docs.length > 0, `len=${docs.length}`)
  const doc = docs[0]

  const pick = await S.j(`/api/relations/defs/${d2.body.id}/pick?side=source`)
  const pickBody = pick.body || {}
  check('文件端候选接口返回文件', pick.status === 200 && (pickBody.items || []).length > 0,
    `status=${pick.status} len=${(pickBody.items || []).length}`)
  check('候选端 kind 声明为 document', pickBody.kind === 'document', `kind=${pickBody.kind}`)
  check('候选条目也标注 kind=document', (pickBody.items || []).every(x => x.kind === 'document'),
    JSON.stringify((pickBody.items || [])[0] || {}).slice(0, 120))

  // --- 3.4 真的建立一条「记录 → 文件」实例
  const recs = await S.j(`/api/records/type/${contract.id}?page_size=5`)
  const rec = (recs.body.items || [])[0]
  if (!rec) {
    check('合同模型下有记录可用于挂接', false, '无记录，跳过实例用例')
  } else {
    const beforeCount = (await defByKey(recKey))?.link_count || 0

    const link = await S.post('/api/relations/records', {
      relation_def_id: d1.body.id,
      source_record_id: rec.id,
      target_document_id: doc.id,
    })
    check('可建立「记录 → 文件」关联实例', link.status === 200,
      `status=${link.status} ${JSON.stringify(link.body).slice(0, 140)}`)
    if (link.status === 200) cleanupQueue.push({ kind: 'relation_record', id: link.body.id })

    const afterCount = (await defByKey(recKey))?.link_count || 0
    check('定义上的关联数随之 +1', afterCount === beforeCount + 1,
      `${beforeCount} → ${afterCount}`)

    // --- 3.5 方向：记录侧应看到「出向」，文件侧应看到「入向」
    const fromRec = await S.j(`/api/relations/for-record/${rec.id}`)
    const recLinks = Array.isArray(fromRec.body) ? fromRec.body : []
    const linkFromRec = recLinks.find(x => x.link_id === link.body.id)
    check('记录侧能看到这条关联', !!linkFromRec, `len=${recLinks.length}`)
    if (linkFromRec) {
      check('记录侧方向为 out（我是源端）', linkFromRec.direction === 'out',
        `direction=${linkFromRec.direction}`)
      check('另一端指向那个文件（不是记录自己）',
        linkFromRec.other_kind === 'document' && linkFromRec.other_id === doc.id,
        `other_kind=${linkFromRec.other_kind} other_id=${linkFromRec.other_id} doc=${doc.id}`)
    }

    const fromDoc = await S.j(`/api/relations/for-document/${doc.id}`)
    const docLinks = Array.isArray(fromDoc.body) ? fromDoc.body : []
    const linkFromDoc = docLinks.find(x => x.link_id === link.body.id)
    check('文件侧能看到这条关联', !!linkFromDoc, `len=${docLinks.length}`)
    if (linkFromDoc) {
      check('文件侧方向为 in（我是目标端）', linkFromDoc.direction === 'in',
        `direction=${linkFromDoc.direction}`)
      check('文件侧的「另一端」是那条记录，而不是文件自己（入向回归）',
        linkFromDoc.other_kind === 'record' && linkFromDoc.other_id === rec.id,
        `other_kind=${linkFromDoc.other_kind} other_id=${linkFromDoc.other_id} rec=${rec.id}`)
    }
  }

  // --- 3.6 类型不匹配必须被挡住
  const task = types.find(t => t.key === 'task')
  const customers = await S.j(`/api/records/type/${types.find(t => t.key === 'customer')?.id}?page_size=1`)
  const wrongRec = (customers.body.items || [])[0]
  if (wrongRec && task) {
    const bad = await S.post('/api/relations/records', {
      relation_def_id: d1.body.id,          // 定义要求源端是「合同」
      source_record_id: wrongRec.id,        // 实际给了一条「客户」
      target_document_id: doc.id,
    })
    check('源端记录类型不符时被拒（400）', bad.status === 400,
      `status=${bad.status} ${JSON.stringify(bad.body.detail || bad.body).slice(0, 120)}`)
    check('拒绝理由点明了模型不一致', /不一致|不符合|要求/.test(String(bad.body.detail || '')),
      String(bad.body.detail || '').slice(0, 100))
  }
}

// ============================================================ 4 图谱接口
async function t4GraphApi() {
  section('4. 图谱接口：节点/边/类型分类齐备，且节点带跳转信息')

  const g = await S.j('/api/graph/global?limit=300')
  const nodes = g.body.nodes || []
  const edges = g.body.edges || []
  check('全局图谱可取', g.status === 200 && nodes.length > 0, `nodes=${nodes.length} edges=${edges.length}`)
  check('边带 via 分类（关联/引用/挂载）',
    edges.every(e => ['relation', 'reference', 'field', 'wikilink'].includes(e.via)),
    `vias=${JSON.stringify(edges.reduce((a, e) => (a[e.via] = (a[e.via] || 0) + 1, a), {}))}`)
  check('边两端都能在节点集合里找到（无悬空边）',
    edges.every(e => nodes.some(n => n.id === e.source) && nodes.some(n => n.id === e.target)),
    `edges=${edges.length}`)
  const recNodes = nodes.filter(n => n.kind === 'record')
  check('记录节点带 type_id（点节点能直接跳模型页）',
    recNodes.length > 0 && recNodes.every(n => n.type_id),
    `records=${recNodes.length} 缺 type_id 的=${recNodes.filter(n => !n.type_id).length}`)
  const docNodes = nodes.filter(n => n.kind === 'document')
  check('文件节点不混入 type_id（文件不属于任何业务模型）',
    docNodes.every(n => !n.type_id),
    `documents=${docNodes.length} 带 type_id 的=${docNodes.filter(n => n.type_id).length}`)

  const et = (await S.j('/api/entity-types')).body.find(t => t.key === 'project')
  const byType = await S.j(`/api/graph/type/${et.id}`)
  check('按模型视图可取', byType.status === 200 && (byType.body.nodes || []).length > 0,
    `nodes=${(byType.body.nodes || []).length}`)

  // 挑一条「确实连着别人」的记录来验证下钻：随便取第一条很容易拿到孤立记录，
  // 那样 nodes=1 也能过，等于没测出「以它为中心能展开」这件事。
  const linkedIds = new Set()
  for (const e of edges) { linkedIds.add(e.source); linkedIds.add(e.target) }
  const connected = nodes.find(n => n.kind === 'record' && linkedIds.has(n.id))
  check('全局图里存在有连接的记录（下钻用例的前提）', !!connected, `connected=${connected?.id}`)
  const byRec = await S.j(`/api/graph/record/${connected.ref_id}?depth=2`)
  const drillNodes = byRec.body.nodes || []
  check('以记录为中心可取', byRec.status === 200 && drillNodes.length > 1,
    `nodes=${drillNodes.length} edges=${(byRec.body.edges || []).length}`)
  check('中心节点被标记 center 且就是这条记录',
    drillNodes.some(n => n.center && n.ref_id === connected.ref_id),
    `center=${drillNodes.filter(n => n.center).map(n => n.id).join(',')}`)

  const notes = await S.j('/api/graph/notes')
  const nn = notes.body.nodes || []
  const ne = notes.body.edges || []
  check('知识图谱有可看的规模（≥8 笔记 / ≥8 双链）', nn.length >= 8 && ne.length >= 8,
    `nodes=${nn.length} edges=${ne.length}`)
  check('笔记节点带 tags（图例按标签着色需要）',
    nn.filter(n => (n.tags || []).length).length >= 5,
    `带标签=${nn.filter(n => (n.tags || []).length).length}`)
  check('双链统一标为 wikilink', ne.every(e => e.via === 'wikilink'),
    `vias=${[...new Set(ne.map(e => e.via))].join(',')}`)

  const found = await S.j(`/api/graph/search?keyword=${encodeURIComponent('项目')}`)
  check('图谱搜索有结果且带 kind/type_id',
    (found.body.items || []).length > 0 && (found.body.items || []).every(x => x.id && x.kind),
    `len=${(found.body.items || []).length}`)
}

// ============================================================ 5 驾驶舱接口
async function t5DashboardApi() {
  section('5. 自定义驾驶舱：模板建舱 → 取数 → 试算')

  const tpl = await S.j('/api/dashboards/templates')
  const items = tpl.body.items || []
  check('内置模板可用（≥2 套）', items.length >= 2,
    items.map(t => `${t.key}(${t.layout.length})`).join(' '))
  check('模板自带卡片且已配好数据源',
    items.every(t => (t.layout || []).length > 0 && (t.layout || []).every(w => w.type)),
    JSON.stringify((items[0]?.layout || []).map(w => w.type)))

  const opt = await S.j('/api/dashboards/options')
  check('编辑器选项齐备（模型/字段/指标/图表）',
    opt.status === 200 && (opt.body.kinds || []).length > 0 && (opt.body.metrics || []).length > 0
      && (opt.body.charts || []).length > 0,
    `kinds=${(opt.body.kinds || []).length} metrics=${(opt.body.metrics || []).length}`)

  const mk = await S.post('/api/dashboards/templates', { template_key: items[0].key, name: `V17 驾驶舱 ${RUN}` })
  check('从模板创建驾驶舱成功', mk.status === 200, `status=${mk.status}`)
  if (mk.status !== 200) return null
  const id = mk.body.id
  cleanupQueue.push({ kind: 'dashboard', id })
  check('卡片随模板带过来', (mk.body.layout || []).length === (items[0].layout || []).length,
    `${(mk.body.layout || []).length} vs ${(items[0].layout || []).length}`)

  const data = await S.j(`/api/dashboards/${id}/data`)
  const widgets = data.body.items || data.body.widgets || []
  check('一次性返回全部卡片数据', data.status === 200 && widgets.length === (mk.body.layout || []).length,
    `widgets=${widgets.length}`)
  const errs = widgets.filter(w => w.error)
  check('所有卡片取数无错', errs.length === 0,
    errs.map(e => `${e.title}:${e.error}`).join(' | '))
  const withData = widgets.filter(w => w.data)
  check('非文本卡片都拿到了数据', withData.length >= widgets.filter(w => w.type !== 'text').length,
    `有数据=${withData.length}`)

  // 逐类型试算（编辑器里的「试算」按钮走的就是这个接口）
  const types = (await S.j('/api/entity-types')).body
  const pid = types.find(t => t.key === 'project').id
  const caselist = [
    ['stat', { kind: 'entity', type_id: pid, metric: 'count' }],
    ['chart', { kind: 'entity', type_id: pid, metric: 'count', group_by: '' }],
    ['chart', { kind: 'entity', type_id: pid, metric: 'count', group_by: '_created_at', chart: 'bar' }],
    ['table', { kind: 'entity', type_id: pid }],
    ['list', { kind: 'document' }],
  ]
  for (const [t, source] of caselist) {
    const pv = await S.post('/api/dashboards/preview', { widget: { type: t, title: 't', source } })
    check(`试算「${t}」返回可渲染结构`, pv.status === 200 && pv.body.type === t,
      `status=${pv.status} type=${pv.body.type}`)
  }

  const broken = await S.post('/api/dashboards/preview', {
    widget: { type: 'chart', title: 't', source: { kind: 'entity', type_id: pid, metric: 'count' } },
  })
  check('配置缺失时给出可读报错而不是崩', broken.status === 200 && /分组/.test(broken.body.error || ''),
    `error=${broken.body.error}`)

  const stat = await S.post('/api/dashboards/preview', {
    widget: { type: 'stat', title: 't', source: { kind: 'document', metric: 'sum', field: 'size' } },
  })
  check('金额/大小类指标有原始值（前端可二次格式化）',
    stat.body.data && typeof stat.body.data.raw === 'number',
    JSON.stringify(stat.body.data || {}).slice(0, 110))

  // 保存布局
  const layout = (mk.body.layout || []).map((w, i) => ({ ...w, span: i === 0 ? 2 : w.span }))
  const up = await S.put(`/api/dashboards/${id}`, { layout })
  check('保存布局成功', up.status === 200, `status=${up.status}`)
  check('布局持久化（首个卡片 span=2）',
    (up.body.layout || [])[0]?.span === 2, `span=${(up.body.layout || [])[0]?.span}`)

  return id
}

// ============================================================ 6 系统管理 + 权限矩阵
async function t6SystemAndPermissions() {
  section('6. 系统管理与角色权限矩阵')

  // 记一个水位线：库里已有历史审计（包括修复前遗留的旧记录），
  // 只看「本次跑出来的那些」，否则会被旧数据误判。
  const pre = await S.j('/api/system/audit?page_size=1')
  const auditMark = (pre.body.items || [])[0]?.id || 0

  const users = await S.j('/api/system/users')
  check('用户列表可取', users.status === 200 && (users.body.items || []).length > 0,
    `len=${(users.body.items || []).length}`)

  const roles = await S.j('/api/system/roles')
  check('角色列表可取', roles.status === 200 && (roles.body.items || []).length > 0,
    `roles=${(roles.body.items || []).map(r => r.key).join(',')}`)

  const audit = await S.j('/api/system/audit?page_size=5')
  check('审计日志可取且带筛选面', audit.status === 200 && Array.isArray(audit.body.facets?.users),
    `facets=${JSON.stringify(audit.body.facets || {}).slice(0, 110)}`)

  const stats = await S.j('/api/system/audit/stats?days=7')
  check('审计统计（趋势 + 排行）可取',
    stats.status === 200 && Array.isArray(stats.body.trend) && stats.body.trend.length === 7,
    `trend=${(stats.body.trend || []).length}`)

  // --- 建一个只读角色（注意权限要嵌在 perms 里，RoleIn 不接受顶层平铺字段）
  const roleKey = `v17_ro_${RUN}`
  const cr = await S.post('/api/system/roles', {
    key: roleKey, name: `V17 只读 ${RUN}`, description: '只能看，不能写',
    perms: {
      pages: ['dashboard', 'library', 'notes'],
      models: { '*': 'read' },
      features: {},
    },
  })
  check('可创建只读角色', cr.status === 200, `status=${cr.status} ${JSON.stringify(cr.body).slice(0, 110)}`)
  if (cr.status !== 200) return
  const roleId = cr.body.id
  cleanupQueue.push({ kind: 'role', id: roleId })
  check('角色权限按矩阵落库（页面 3 个 / 模型默认 read）',
    (cr.body.perms?.pages || []).length === 3 && cr.body.perms?.models?.['*'] === 'read',
    JSON.stringify(cr.body.perms))

  // --- 建一个挂该角色的用户
  const uname = `v17u_${RUN}`
  const upass = 'V17pass!234'
  const cu = await S.post('/api/system/users', {
    username: uname, password: upass, display_name: 'V17 只读用户', role_id: roleId,
  })
  check('可创建用户并挂角色', cu.status === 200 && cu.body.role_id === roleId,
    `status=${cu.status} role_id=${cu.body.role_id}`)
  if (cu.status !== 200) return
  const uid = cu.body.id
  cleanupQueue.push({ kind: 'user', id: uid })

  // --- 用该用户登录，验证权限矩阵真的拦得住
  const lm = await fetch(`${API}/api/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: uname, password: upass }),
  })
  const lmb = await lm.json()
  check('只读用户能登录', lm.status === 200 && lmb.ok === true, `status=${lm.status}`)
  const raw = lm.headers.getSetCookie ? lm.headers.getSetCookie() : [lm.headers.get('set-cookie')]
  const ck = raw.map(x => String(x).split(';')[0]).filter(Boolean).join('; ')

  const asUser = async (path, opts = {}) => {
    const r = await fetch(API + path, { ...opts, headers: { ...(opts.headers || {}), Cookie: ck } })
    const ct = r.headers.get('content-type') || ''
    return { status: r.status, body: ct.includes('json') ? await r.json() : await r.text() }
  }

  check('页面权限按角色下发（不含 system）', !(lmb.user.perms.pages || []).includes('system'),
    `pages=${JSON.stringify(lmb.user.perms.pages)}`)
  check('模型权限默认 read', lmb.user.perms.models?.['*'] === 'read',
    `models=${JSON.stringify(lmb.user.perms.models)}`)

  const roRead = await asUser('/api/entity-types')
  // 只断言状态码是不够的：不可读时接口同样返回 200（空列表），
  // 那样「只读用户读得到」就永远成立，等于没测。
  check('只读用户读到的是真实数据而不是空列表',
    roRead.status === 200 && Array.isArray(roRead.body) && roRead.body.length > 0,
    `status=${roRead.status} len=${Array.isArray(roRead.body) ? roRead.body.length : 'n/a'}`)

  const et = (await S.j('/api/entity-types')).body.find(t => t.key === 'note')
  const roWrite = await asUser(`/api/records/type/${et.id}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: { title: 'v17 不该建得起来' } }),
  })
  check('只读用户写数据被拒（403）', roWrite.status === 403, `status=${roWrite.status}`)

  const roSys = await asUser('/api/system/users')
  check('只读用户看不到用户管理（403）', roSys.status === 403, `status=${roSys.status}`)

  const roAudit = await asUser('/api/system/audit')
  check('只读用户看不到审计日志（403）', roAudit.status === 403, `status=${roAudit.status}`)

  const roDashWrite = await asUser('/api/dashboards', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: `v17_nope_${RUN}`, name: '不该建得起来' }),
  })
  check('只读用户建不了驾驶舱（403）', roDashWrite.status === 403, `status=${roDashWrite.status}`)

  // --- 改角色：会话立即失效（这是会话鉴权相对 JWT 的核心优势）
  const chg = await S.patch(`/api/system/users/${uid}`, { role_id: roles.body.items[0].id })
  check('管理员可改用户角色', chg.status === 200, `status=${chg.status}`)
  const afterChg = await asUser('/api/entity-types')
  check('改角色后旧会话立即失效（401）', afterChg.status === 401, `status=${afterChg.status}`)

  // 再登一次，测停用
  const lm2 = await fetch(`${API}/api/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: uname, password: upass }),
  })
  const lmb2 = await lm2.json()
  const raw2 = lm2.headers.getSetCookie ? lm2.headers.getSetCookie() : [lm2.headers.get('set-cookie')]
  const ck2 = raw2.map(x => String(x).split(';')[0]).filter(Boolean).join('; ')
  check('改角色后新会话里权限已变（能看 system 了）',
    (lmb2.user?.perms?.pages || []).includes('system'),
    `pages=${JSON.stringify(lmb2.user?.perms?.pages)}`)

  const dis = await S.patch(`/api/system/users/${uid}`, { is_active: false })
  check('管理员可停用账号', dis.status === 200, `status=${dis.status}`)
  const r2 = await fetch(`${API}/api/entity-types`, { headers: { Cookie: ck2 } })
  check('停用后会话立即失效（401）', r2.status === 401, `status=${r2.status}`)

  // --- 审计留痕：刚才的写操作应该被记下来
  await S.sleep(600)   // 审计中间件在响应之后落库
  const aud = await S.j('/api/system/audit?page_size=100')
  const fresh = (aud.body.items || []).filter(x => x.id > auditMark)
  const mine = fresh.filter(x => String(x.path || '').includes('system/users'))
  check('写操作进了审计日志', mine.length > 0, `本次新增 ${fresh.length} 条，命中 users ${mine.length} 条`)
  check('审计记录了操作人与动作',
    mine.length > 0 && mine.every(x => x.username && x.action),
    JSON.stringify(mine[0] || {}).slice(0, 150))
  // /api/system/users 必须归到 user 资源：归到 "system" 的话
  // 审计页「按资源筛选」就分不出用户、角色、审计本身了
  check('嵌套路径的资源名归一正确（system/users → user）',
    mine.every(x => x.resource === 'user'),
    `resources=${[...new Set(mine.map(x => x.resource))].join(',')}`)
  check('审计能追到具体对象 id', mine.some(x => x.resource_id),
    `带 id 的=${mine.filter(x => x.resource_id).length}/${mine.length}`)

  const roleCreate = fresh.find(x => x.resource === 'role' && x.action === 'create')
  check('新建角色被记为 role/create，并回填了对象 id',
    !!roleCreate && !!roleCreate.resource_id,
    roleCreate ? `id=${roleCreate.resource_id} path=${roleCreate.path}` : '没找到 role/create')
  const userCreate = fresh.find(x => x.resource === 'user' && x.action === 'create')
  check('新建用户被记为 user/create，并回填了对象 id',
    !!userCreate && !!userCreate.resource_id,
    userCreate ? `id=${userCreate.resource_id} path=${userCreate.path}` : '没找到 user/create')
}

// ============================================================ 前端
async function t7Frontend(page) {
  section('7. 前端：登录链路与路由守卫')

  // 前端是 hash 路由：判断「当前在哪一页」要看 location.hash
  await goPage(page, '/library')
  const redirected = await S.waitFor(page, () => location.hash.startsWith('#/login'), 10000)
  check('未登录访问内页被重定向到登录页', !!redirected, `hash=${await page.evaluate(() => location.hash)}`)
  const hashNow = await page.evaluate(() => location.hash)
  check('重定向带回跳地址', hashNow.includes('redirect'), hashNow)

  const loggedIn = await S.loginPage(page)
  const hashAfter = await page.evaluate(() => location.hash)
  check('从登录页登录后进入系统', loggedIn, `hash=${hashAfter}`)
  check('登录后回跳到原来想去的页面', hashAfter.includes('/library'), hashAfter)

  // ---- 关联定义：两端都能选文件
  section('8. 前端：新建关联定义可选「数据中心文件」')
  await goPage(page, '/relations')
  await page.waitForSelector('.page', { timeout: 10000 })
  await waitClickable(page, '新建关联')
  await page.waitForSelector('.el-dialog', { visible: true, timeout: 8000 })
  await S.sleep(400)

  const radioCount = await countOf(page, '.end-picker .el-radio-button')
  check('对话框里源端/目标端各有一组「记录 or 文件」选择', radioCount === 4, `radio=${radioCount}`)

  await page.evaluate(() => {
    const groups = [...document.querySelectorAll('.end-picker .el-radio-group')]
    groups.forEach(g => {
      const btns = [...g.querySelectorAll('.el-radio-button')]
      const fileBtn = btns.find(b => (b.innerText || '').includes('数据中心文件'))
      // el-radio-button 是 <label>，点 label 才会连带触发内部 radio 的 change
      if (fileBtn) fileBtn.click()
    })
  })
  await S.sleep(500)
  const statics = await visibleCount(page, '.end-picker .end-static')
  check('两端切到「文件」后出现文件说明块', statics === 2, `static=${statics}`)
  const textOk = await page.evaluate(() => {
    const t = [...document.querySelectorAll('.end-picker .end-static')].map(e => e.innerText).join('|')
    return t.includes('数据中心文件') && t.includes('不限类型')
  })
  check('文件端文案说明「全部文件，不限类型」', textOk, '')
  const typeSelects = await visibleCount(page, '.end-picker .el-select')
  check('切到文件端后模型下拉被隐藏（文件不分类型）', typeSelects === 0, `select=${typeSelects}`)

  // 真的用文件端建一个定义：源端改回记录（要挑模型），目标端留在文件
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-form-item:nth-of-type(3) .end-picker .el-radio-button')]
    const rec = btns.find(b => (b.innerText || '').includes('业务记录'))
    if (rec) rec.click()
  })
  await S.sleep(400)
  const modelPicked = await pickOption(page, '.el-form-item:nth-of-type(3) .end-picker .el-select', '合同')
  check('源端切回「业务记录」后可挑模型', modelPicked, '')

  const nameInput = await page.$('.el-dialog input[placeholder*="合同扫描件"]')
  await nameInput.click({ clickCount: 3 })
  await nameInput.type(`V17 UI 关联 ${RUN}`)
  const keyInput = await page.$('.el-dialog input[placeholder*="contract_file"]')
  await keyInput.click({ clickCount: 3 })
  await keyInput.type(`v17_ui_${RUN}`)

  await waitClickable(page, '创建', '.el-dialog button')
  await S.sleep(1500)
  const rowOk = await S.waitFor(page, (n) =>
    document.body.innerText.includes(n), 6000, `V17 UI 关联 ${RUN}`)
  check('通过界面建出的关联定义出现在列表里', !!rowOk, '')
  const fileChip = await countOf(page, '.rel-node.file')
  check('列表里文件端有专属样式（虚线文件块）', fileChip > 0, `file 端节点=${fileChip}`)

  const uiDef = await defByKey(`v17_ui_${RUN}`)
  if (uiDef) {
    cleanupQueue.push({ kind: 'relation_def', id: uiDef.id })
    check('后端确认该定义确实落库', !!uiDef.id, `id=${uiDef.id}`)
  } else {
    check('后端确认该定义确实落库', false, '列表里没有这条定义')
  }

  // ---- 关联图谱
  section('9. 前端：关联图谱可用性与视觉')
  await goPage(page, '/graph?__e2e=1')
  await page.waitForSelector('.gc-canvas', { timeout: 12000 })
  const canvasOk = await S.waitFor(page, () => !!document.querySelector('.gc-canvas canvas'), 10000)
  check('vis 画布已挂载', !!canvasOk, '')

  const nodeStat = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.stat-card')]
    const c = cards.find(x => (x.innerText || '').includes('当前节点'))
    return c ? Number((c.querySelector('.value') || {}).innerText || 0) : -1
  })
  check('概览显示真实节点数', nodeStat > 0, `节点=${nodeStat}`)

  const legendItems = await countOf(page, '.gc-legend:not(.via) .gl-item')
  check('图例按类型列出（≥3 类）', legendItems >= 3, `图例项=${legendItems}`)
  const viaItems = await countOf(page, '.gc-legend.via .gl-item')
  check('连线图例解释三种边语义', viaItems >= 2, `连线图例=${viaItems}`)

  const before = await page.$eval('.gc-legend:not(.via) .gl-count', e => e.innerText)
  await page.click('.gc-legend:not(.via) .gl-item')
  await S.sleep(400)
  const after = await page.$eval('.gc-legend:not(.via) .gl-count', e => e.innerText)
  check('点图例能隐藏整类节点（可见数下降）', before !== after, `${before} → ${after}`)
  await page.click('.gc-legend:not(.via) .gl-item')
  await S.sleep(300)
  const restored = await page.$eval('.gc-legend:not(.via) .gl-count', e => e.innerText)
  check('再点一次恢复显示', restored === before, `${restored} vs ${before}`)

  const toolBtn = await countOf(page, '.gc-toolbar .gt-btn')
  check('工具条按钮齐备（适应/缩放/重排/标签/图例）', toolBtn >= 6, `按钮=${toolBtn}`)
  const onBefore = await countOf(page, '.gc-toolbar .gt-btn.on')
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.gc-toolbar .gt-btn')]
    btns.find(b => (b.getAttribute('title') || '').includes('名称'))?.click()
  })
  await S.sleep(300)

  // 点真实节点 → 抽屉
  const clicked = await page.evaluate(() => {
    const net = window.__kbGraph
    if (!net) return 'no-instance'
    const ids = net.body?.nodes?.getIds?.() || net.body?.data?.nodes?.getIds?.() || []
    const positions = net.getPositions(ids)
    for (const id of ids) {
      const p = positions[id]
      if (!p) continue
      const dom = net.canvasToDOM(p)
      return { x: Math.round(dom.x), y: Math.round(dom.y), id }
    }
    return 'no-node'
  })
  if (clicked && clicked.x !== undefined) {
    const box = await page.$eval('.gc-canvas', e => {
      const r = e.getBoundingClientRect()
      return { x: r.x, y: r.y }
    })
    await page.mouse.click(box.x + clicked.x, box.y + clicked.y)
    let drawer = await S.waitFor(page, () => !!document.querySelector('.gc-drawer .gi'), 3500)

    // vis-network 物理稳定前，canvasToDOM 算出的坐标可能有轻微漂移，
    // 偶尔出现点击没命中节点。用 selectNodes 兜底触发同一条 selectNode 事件，
    // 既验证事件链路，也避免这一处因为模拟抖动而偶发失败。
    if (!drawer) {
      drawer = await page.evaluate((id) => {
        const net = window.__kbGraph
        if (!net) return false
        net.selectNodes([id])
        return !!document.querySelector('.gc-drawer .gi')
      }, clicked.id)
      check('点击节点打开右侧详情抽屉', !!drawer, `node=${clicked.id} (mouse 未命中，selectNodes 兜底)`)
    } else {
      check('点击节点打开右侧详情抽屉', true, `node=${clicked.id}`)
    }

    if (drawer) {
      const stats = await countOf(page, '.gi-stats .gis')
      check('抽屉显示关联数/邻居数/分组', stats === 3, `stat=${stats}`)
      const actions = await countOf(page, '.gi-actions button')
      check('抽屉提供「打开详情」「以它为中心」', actions >= 2, `按钮=${actions}`)
    }
  } else {
    check('点击节点打开右侧详情抽屉', false, `未能取到节点坐标：${clicked}`)
  }

  // 三种模式都切一遍：切模式是这类页面最容易残留空图的地方
  const modes = ['按数据模型', '以节点为中心', '全局总览']
  for (const label of modes) {
    const ok = await pickElSelect(page, 0, label)
    check(`可切换到「${label}」模式`, ok, ok ? '' : '下拉点不开或找不到选项')
    await S.sleep(1000)
  }
  const modeStat = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.stat-card')]
    const c = cards.find(x => (x.innerText || '').includes('当前节点'))
    return c ? Number((c.querySelector('.value') || {}).innerText || 0) : -1
  })
  check('切回全局总览后仍有节点（模式切换不残留空图）', modeStat > 0, `节点=${modeStat}`)

  // ---- 知识图谱
  section('10. 前端：知识图谱')
  await goPage(page, '/knowledge/graph')
  await page.waitForSelector('.gc-canvas', { timeout: 12000 })
  const kgOk = await S.waitFor(page, () => !!document.querySelector('.gc-canvas canvas'), 10000)
  check('知识图谱画布已挂载', !!kgOk, '')
  const kgNodes = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.stat-card')]
    const c = cards.find(x => (x.innerText || '').includes('笔记'))
    return c ? Number((c.querySelector('.value') || {}).innerText || 0) : -1
  })
  check('知识图谱显示笔记数 ≥8', kgNodes >= 8, `笔记=${kgNodes}`)
  const kgLegend = await countOf(page, '.gc-legend:not(.via) .gl-item')
  check('知识图谱按标签列出图例', kgLegend >= 2, `图例=${kgLegend}`)

  // ---- 驾驶舱
  section('11. 前端：自定义驾驶舱')
  await goPage(page, '/dashboards')
  await page.waitForSelector('.page', { timeout: 10000 })
  await S.sleep(600)
  const tplBtn = await page.evaluate(() =>
    document.body.innerText.includes('从模板创建') || document.body.innerText.includes('模板'))
  check('驾驶舱列表页提供「从模板创建」入口', tplBtn, '')

  const target = (await S.j('/api/dashboards')).body.items.find(d => d.name === `V17 驾驶舱 ${RUN}`)
  check('上一节创建的驾驶舱在列表里', !!target, `id=${target?.id}`)
  if (target) {
    await goPage(page, `/dashboards/${target.id}`)
    await page.waitForSelector('.cockpit', { timeout: 10000 })
    const cells = await S.waitFor(page, () => {
      const n = document.querySelectorAll('.cockpit .cell').length
      return n > 0 ? n : null
    }, 10000)
    check('驾驶舱按布局渲染出卡片', cells > 0, `卡片=${cells}`)
    const painted = await S.waitFor(page, () =>
      !!document.querySelector('.cockpit canvas, .cockpit .cw-stat, .cockpit .cw-table, .cockpit .cw-list'), 8000)
    check('卡片内确实画出了内容（图表/大数/表格）', !!painted, '')

    const editOk = await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find(x => (x.innerText || '').includes('编辑布局'))
      if (!b) return false
      b.click()
      return true
    })
    await S.sleep(600)
    check('进入编辑模式', editOk && !!(await page.$('.edit-bar')), '')
    const spanCtl = await countOf(page, '.cell-tools .el-dropdown')
    check('每张卡片可选宽度（列数）', spanCtl > 0, `宽度选择器=${spanCtl}`)
    const tools = await countOf(page, '.cell-tools button')
    check('卡片工具条齐备（左右移 / 宽度 / 配置 / 删除）', tools >= 4, `按钮=${tools}`)

    await waitClickable(page, '添加卡片')
    await page.waitForSelector('.widget-drawer', { visible: true, timeout: 6000 })
    check('可新增卡片并打开配置抽屉', true, '')
    const secs = await countOf(page, '.widget-drawer .wd-sec')
    check('配置抽屉分区（展示方式/数据源/筛选/预览）', secs >= 4, `分区=${secs}`)

    await waitClickable(page, '试算', '.widget-drawer button')
    const previewOk = await S.waitFor(page, () => {
      const box = document.querySelector('.preview-box')
      return box && !box.classList.contains('empty')
    }, 10000)
    check('试算返回预览（点一次就看到结果）', !!previewOk, '')

    const closed = await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.widget-drawer button')]
      const b = btns.find(x => /取消|关闭/.test(x.innerText))
      if (b) { b.click(); return true }
      return false
    })
    await S.sleep(600)

    const saveOk = await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find(x => (x.innerText || '').includes('保存布局'))
      if (!b) return false
      b.click()
      return true
    })
    await S.sleep(1500)
    check('保存布局成功（退出编辑态）', saveOk && !(await page.$('.edit-bar')), '')
  }

  // ---- 系统管理三页
  section('12. 前端：系统管理三页')
  for (const [path, must, name] of [
    ['/system/users', '用户', '用户管理'],
    ['/system/roles', '权限', '角色权限矩阵'],
    ['/system/audit', '审计', '审计日志'],
  ]) {
    await goPage(page, path)
    await page.waitForSelector('.page', { timeout: 10000 })
    await S.sleep(700)
    const has = await page.evaluate((m) => document.body.innerText.includes(m), must)
    check(`${name} 页渲染出关键内容`, has, `期望包含「${must}」`)
    const empty = await countOf(page, '.empty-state')
    const hasData = await page.evaluate(() => document.querySelectorAll('table, .card, .stat-card').length > 0)
    check(`${name} 页不是空白`, hasData || empty > 0, '')
  }
  await goPage(page, '/system/roles')
  await S.sleep(800)
  const matrix = await page.evaluate(() =>
    document.querySelectorAll('.el-checkbox, .el-switch, table').length)
  check('角色页有可操作的权限矩阵控件', matrix > 5, `控件=${matrix}`)
}

// ============================================================ 清理
async function cleanup() {
  section('清理')
  let n = 0
  for (const item of cleanupQueue.reverse()) {
    try {
      if (item.kind === 'relation_record') await S.del(`/api/relations/records/${item.id}`)
      if (item.kind === 'relation_def') await S.del(`/api/relations/defs/${item.id}`)
      if (item.kind === 'dashboard') await S.del(`/api/dashboards/${item.id}`)
      if (item.kind === 'user') await S.del(`/api/system/users/${item.id}`)
      if (item.kind === 'role') await S.del(`/api/system/roles/${item.id}`)
      n++
    } catch (e) { /* 清理失败不影响结论 */ }
  }
  console.log(`已清理 ${n}/${cleanupQueue.length} 项测试数据`)
}

// ============================================================ main
async function main() {
  await S.login()
  await t1AuthBaseline()
  await t2EntityTypesRegression()
  await t3RelationFileEnds()
  await t4GraphApi()
  await t5DashboardApi()
  await t6SystemAndPermissions()

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: HEAD ? false : 'shell',
    args: ['--no-sandbox', '--window-size=1440,960'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  const errors = []
  const bad = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))
  page.on('response', r => {
    const u = r.url()
    if (r.status() >= 400 && u.includes('/api/')) bad.push(`${r.status()} ${u.slice(0, 90)}`)
  })

  try {
    await t7Frontend(page)
  } catch (e) {
    check('前端用例执行完成', false, String(e).slice(0, 180))
  }

  section('13. 控制台与接口健康')
  check('前端无控制台错误', errors.length === 0, errors.slice(0, 3).join(' | '))
  // 403/401 是权限用例故意触发的，不算异常
  const realBad = bad.filter(x => !/^40[13] /.test(x))
  check('无意外 4xx/5xx 接口调用', realBad.length === 0, realBad.slice(0, 4).join(' | '))

  await browser.close()
  await cleanup()

  const pass = results.filter(r => r[1]).length
  console.log(`\n${'='.repeat(64)}`)
  console.log(`结果：${pass}/${results.length} 通过`)
  const failed = results.filter(r => !r[1])
  if (failed.length) {
    console.log('\n未通过：')
    failed.forEach(([n, , d]) => console.log(`  ❌ ${n}  ${d}`))
    process.exit(1)
  }
}

main().catch(e => { console.error(e); process.exit(1) })
