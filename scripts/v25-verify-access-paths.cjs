/**
 * v24 回归验证：聚合入口的读权限收口
 *
 * 背景：上一轮把「记录接口」和「文件接口」的权限门禁补齐了，但这三条
 * 「一次性返回一批东西」的聚合入口漏在门外：
 *
 *   1. GET /api/search              → 记录命中不按模型权限裁剪，
 *                                      合同金额、客户名直接摊在搜索结果里
 *   2. GET /api/graph/*              → 图谱节点不按模型权限裁剪，
 *                                      只能看笔记的人能看到全库记录的标签
 *   3. GET /api/relations/*          → 关联列表不校验本体与对端，
 *                                      能拿到「对端记录标题 + 文件预览链接」
 *   4. GET /api/documents            → 列表与单文件两套口径，
 *                                      「列表里看得见、点进去 403」
 *
 * 这一轮要锁住的是：
 *   - 搜索 / 图谱 / 关联 三条聚合路径都不再泄露读不到的记录
 *   - 文件列表与单文件接口用同一条判定（列表里能看见的，点进去一定能打开）
 *   - 管理员一切照旧
 *
 * 前置：后端容器已启动（8001），管理员口令已知。
 *   node scripts/v24-verify-access-paths.cjs
 *   KB_PASS='你的管理员口令' node scripts/v24-verify-access-paths.cjs
 *
 * 脚本自建临时角色与临时账号，跑完自动删除，不留残留。
 */
const S = require('./lib/session.cjs')
const { API } = S

const results = []
const cleanup = []   // [{ kind, id }]，跑完逆序删掉

function check(name, got, want) {
  const ok = got === want
  results.push({ name, ok, got, want })
  console.log(`${ok ? '✅' : '❌'}${name}${ok ? '' : `  （实际 ${got}，期望 ${want}）`}`)
}

function checkTrue(name, cond, detail = '') {
  check(name, !!cond, true)
  if (!cond && detail) console.log(`      ${detail}`)
}

/** 用指定账号登录，返回该会话的 cookie */
async function loginAs(user, pass) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: user, password: pass }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok || !body.ok) throw new Error(`登录 ${user} 失败：HTTP ${r.status}`)
  const raw = r.headers.getSetCookie ? r.headers.getSetCookie() : [r.headers.get('set-cookie')]
  const cookie = raw.map(sc => String(sc).split(';')[0].trim()).filter(Boolean).join('; ')
  if (!cookie) throw new Error(`登录 ${user} 成功但没拿到 cookie`)
  return cookie
}

/** 带指定会话发请求，只关心状态码 */
async function status(cookie, path, method = 'GET') {
  const r = await fetch(API + path, { method, headers: { Cookie: cookie } })
  await r.arrayBuffer().catch(() => {})   // 读完响应体，别把连接挂住
  return r.status
}

/** 带指定会话发请求并解析 JSON */
async function json(cookie, path) {
  const r = await fetch(API + path, { headers: { Cookie: cookie } })
  return { status: r.status, body: await r.json().catch(() => ({})) }
}

const PAGES_ALL = [
  'dashboard', 'dashboards', 'library', 'notes', 'apps', 'types', 'records',
  'relations', 'graph', 'knowledge_graph', 'search', 'guide', 'ai', 'system',
]

async function main() {
  // ---------- 准备：找一条「别的模型」的记录 + 一个独立文件 ----------
  await S.login()
  const typeRes = await S.j('/api/entity-types')
  const typeArr = Array.isArray(typeRes.body) ? typeRes.body : (typeRes.body.items || [])
  // 找一个「确实有记录、且不是笔记」的模型当对照组
  let nonNote = null
  let rec = null
  for (const t of typeArr) {
    if (t.key === 'note') continue
    const r = await S.j(`/api/records/type/${t.id}?page=1&page_size=5`)
    const arr = Array.isArray(r.body) ? r.body : (r.body.items || [])
    if (arr.length) { nonNote = t; rec = arr[0]; break }
  }
  if (!nonNote) throw new Error('库里找不到有记录的非笔记模型，跳过本轮验证')
  console.log(`对照模型：${nonNote.key}（${nonNote.name}）`)
  console.log(`对照记录：#${rec.id}`)

  const docsRes = await S.j('/api/documents?page=1&page_size=200')
  const docs = (docsRes.body.items || []).filter(d => !d.deleted_at)
  const standalone = docs.find(d => !(d.links || []).length)
  console.log(`独立文件：#${standalone ? standalone.id : '（无）'} ${standalone ? standalone.filename : ''}`)

  // ---------- 建临时角色与账号 ----------
  async function makeRole(key, name, pages, models, features) {
    const r = await S.post('/api/system/roles', {
      key, name, description: 'v24 临时验证角色',
      perms: { all: false, pages, models, features },
    })
    if (r.status !== 200) throw new Error(`建角色失败：${JSON.stringify(r.body).slice(0, 200)}`)
    cleanup.push({ kind: 'role', id: r.body.id })
    return r.body.id
  }
  async function makeUser(username, password, roleId) {
    const r = await S.post('/api/system/users', {
      username, password, display_name: username, role_id: roleId, is_active: true,
    })
    if (r.status !== 200) throw new Error(`建用户失败：${JSON.stringify(r.body).slice(0, 200)}`)
    cleanup.push({ kind: 'user', id: r.body.id })
    return r.body.id
  }

  const STAMP = Date.now().toString(36).slice(-6)
  // 只给知识库 + 只给 note 模型读权限：其它模型一概读不到
  const kbRoleId = await makeRole(
    `v24_kb_${STAMP}`, 'v24 只给知识库',
    PAGES_ALL.filter(p => p !== 'library'),
    { note: 'read' },
    {},
  )
  // 只给数据中心、但没有任何模型读权限
  const libRoleId = await makeRole(
    `v24_lib_${STAMP}`, 'v24 只给数据中心',
    PAGES_ALL.filter(p => p !== 'notes'),
    {},
    {},
  )
  const kbUser = `v24_kb_${STAMP}`
  const libUser = `v24_lib_${STAMP}`
  const PASS = 'V24Tmp!2026'
  await makeUser(kbUser, PASS, kbRoleId)
  await makeUser(libUser, PASS, libRoleId)

  // ================================================================
  console.log('\n=== A. 只给知识库：搜索 / 图谱 不泄露别的模型 ===')
  {
    const c = await loginAs(kbUser, PASS)

    // --- 搜索：记录命中必须按模型权限裁剪 ---
    const s = await json(c, `/api/search?keyword=${encodeURIComponent('a')}`)
    const hitKeys = (s.body.records || []).map(r => r.entity_type_key)
    checkTrue('搜索：记录命中不包含无权限的模型',
      !hitKeys.includes(nonNote.key), `命中了 ${hitKeys.join(',')}`)

    // --- 图谱：节点必须按模型权限裁剪 ---
    const g = await json(c, '/api/graph/global?limit=50')
    const nodeTypes = (g.body.nodes || []).filter(n => n.kind === 'record').map(n => n.type)
    checkTrue('全局图谱：记录节点不含无权限的模型',
      !nodeTypes.includes(nonNote.key), `出现了 ${nodeTypes.join(',')}`)

    const gt = await json(c, `/api/graph/type/${nonNote.id}`)
    check('类型图谱：整个模型不可读时返回空节点',
      (gt.body.nodes || []).filter(n => n.kind === 'record').length, 0)
    check('类型图谱：整个模型不可读时不返回文件节点',
      (gt.body.nodes || []).filter(n => n.kind === 'document').length, 0)

    const gr = await json(c, `/api/graph/record/${rec.id}`)
    check('记录图谱：读不到的记录不返回节点',
      (gr.body.nodes || []).filter(n => n.kind === 'record').length, 0)

    const gs = await json(c, `/api/graph/search?keyword=a`)
    check('图谱搜索：读不到的模型不出现在结果里',
      (gs.body.items || []).filter(i => i.kind === 'record' && i.type_name === nonNote.name).length,
      0)

    // --- 关联：本体与对端都要校验 ---
    const rf = await status(c, `/api/relations/for-record/${rec.id}`)
    check('关联列表：读不到的记录 → 403', rf, 403)
    const ff = await status(c, `/api/relations/files-of-record/${rec.id}`)
    check('挂载文件列表：读不到的记录 → 403', ff, 403)
  }

  console.log('\n=== B. 只给数据中心：文件列表与单文件同一口径 ===')
  {
    const c = await loginAs(libUser, PASS)
    const dl = await json(c, '/api/documents?page=1&page_size=200')
    const items = dl.body.items || []
    check('文件列表可访问', dl.status, 200)
    // 列表里出现的每一个文件，点进去都必须能打开（口径一致）
    let mismatched = []
    for (const d of items) {
      const st = await status(c, `/api/documents/${d.id}/raw`)
      if (st !== 200) mismatched.push(`#${d.id}=${st}`)
    }
    checkTrue('文件列表里的每一条点进去都能打开（口径一致）',
      mismatched.length === 0, mismatched.join(' '))
    // 读不到的关联记录不能出现在 links 里
    const leaked = items.filter(d => (d.links || []).some(l => l.entity_type_key === nonNote.key))
    checkTrue('文件列表不泄露读不到的关联记录标题',
      leaked.length === 0, `文件 ${leaked.map(d => '#' + d.id).join(',')}`)

    if (standalone) {
      check('独立文件可读（归数据中心页面管）',
        await status(c, `/api/documents/${standalone.id}/raw`), 200)
    }
  }

  console.log('\n=== C. 管理员一切照旧 ===')
  {
    const c = S.cookies()
    const s = await json(c, `/api/search?keyword=a`)
    checkTrue('管理员：搜索仍能返回记录',
      (s.body.records || []).length > 0)
    const g = await json(c, '/api/graph/global?limit=50')
    checkTrue('管理员：全局图谱仍有节点',
      (g.body.nodes || []).length > 0)
    const gt = await json(c, `/api/graph/type/${nonNote.id}`)
    checkTrue('管理员：类型图谱仍有记录节点',
      (gt.body.nodes || []).filter(n => n.kind === 'record').length > 0)
    const rf = await status(c, `/api/relations/for-record/${rec.id}`)
    check('管理员：关联列表仍可访问', rf, 200)
    const dl = await json(c, '/api/documents?page=1&page_size=200')
    check('管理员：文件列表仍可访问', dl.status, 200)
  }
}

async function cleanupAll() {
  for (const item of cleanup.reverse()) {
    try {
      if (item.kind === 'user') await S.del(`/api/system/users/${item.id}`)
      else await S.del(`/api/system/roles/${item.id}`)
    } catch (e) {
      console.log(`⚠️ 清理 ${item.kind}#${item.id} 失败：${e.message}`)
    }
  }
}

main()
  .catch(e => { console.error('❌ 验证脚本异常：', e.message); process.exitCode = 1 })
  .finally(async () => {
    await cleanupAll()
    const bad = results.filter(r => !r.ok)
    console.log(`\n共 ${results.length} 项，${results.length - bad.length} 项通过`)
    if (bad.length) {
      console.log('❌ 失败项：')
      for (const r of bad) console.log(`   ${r.name}  实际 ${r.got} / 期望 ${r.want}`)
    }
    process.exit(bad.length ? 1 : 0)
  })
