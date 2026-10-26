/**
 * v18 回归验证：页面权限在接口层真的生效
 *
 * 背景：以前「数据中心」与「知识库」只是菜单里的两个入口，后端读接口
 * 只要求登录。于是「只给知识库」的角色换个 URL 就能把文件全读走 ——
 * 菜单挡住的是界面，不是数据。
 *
 * 这一轮要锁住的是：
 *   1. 只给知识库的角色 → 数据中心的读接口一律 403（含附件接口这个绕过口）
 *   2. 只给数据中心的角色 → 知识库的读接口一律 403
 *   3. 挂在记录上的文件跟随那条记录的模型权限（不能一刀切 403 误伤记录页）
 *   4. 全局搜索不把文件命中泄露给没有数据中心权限的人
 *   5. 管理员一切照旧
 *
 * 前置：后端与前端容器已启动（8001 / 8082），且管理员口令已知。
 *   node scripts/v18-verify-permissions.cjs
 *   KB_PASS='你的管理员口令' node scripts/v18-verify-permissions.cjs
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
  console.log(`${ok ? '✅' : '❌'} ${name}${ok ? '' : `  （实际 ${got}，期望 ${want}）`}`)
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
  // ---------- 准备：先找一个「独立文件」和一个「挂在记录上的文件」 ----------
  await S.login()
  const list = await S.j('/api/documents?page=1&page_size=200')
  const docs = (list.body.items || []).filter(d => !d.deleted_at)
  const standalone = docs.find(d => !(d.links || []).length)
  const attached = docs.find(d => (d.links || []).length)
  if (!standalone) throw new Error('库里没有独立的文件，跳过本轮验证')
  console.log(`独立文件：#${standalone.id} ${standalone.filename}`)
  console.log(attached
    ? `记录附件：#${attached.id} ${attached.filename}`
    : '记录附件：库里没有（相关断言会跳过）')

  // ---------- 建临时角色与账号 ----------
  async function makeRole(key, name, pages, models, features) {
    const r = await S.post('/api/system/roles', {
      key, name, description: 'v18 临时验证角色',
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
  const notesRoleId = await makeRole(
    `v18_notes_${STAMP}`, 'v18 只给知识库',
    PAGES_ALL.filter(p => p !== 'library'),
    { '*': 'read' },
    { ai: true },
  )
  const filesRoleId = await makeRole(
    `v18_files_${STAMP}`, 'v18 只给数据中心',
    PAGES_ALL.filter(p => p !== 'notes'),
    {},
    { ai: true, file_write: true },
  )
  const notesUser = `v18_notes_${STAMP}`
  const filesUser = `v18_files_${STAMP}`
  const PASS = 'V18Tmp!2026'
  await makeUser(notesUser, PASS, notesRoleId)
  await makeUser(filesUser, PASS, filesRoleId)

  // ---------- A. 只给知识库 ----------
  console.log('\n=== A. 只给知识库的角色 ===')
  {
    const c = await loginAs(notesUser, PASS)
    check('文档列表 /api/documents', await status(c, '/api/documents'), 403)
    check('文档检索 /api/documents/search', await status(c, '/api/documents/search?q=x'), 403)
    check('文档统计 /api/documents/stats', await status(c, '/api/documents/stats'), 403)
    check('文件原文 /api/documents/:id/raw',
      await status(c, `/api/documents/${standalone.id}/raw`), 403)
    check('文件下载 /api/documents/:id/download',
      await status(c, `/api/documents/${standalone.id}/download`), 403)
    check('文件抽取 /api/documents/:id/content',
      await status(c, `/api/documents/${standalone.id}/content`), 403)
    // 附件接口是绕过口：它按 id 直接查 document，能取到任何文件
    check('绕过口 /api/attachments/:id/preview',
      await status(c, `/api/attachments/${standalone.id}/preview`), 403)
    check('绕过口 /api/attachments/:id/download',
      await status(c, `/api/attachments/${standalone.id}/download`), 403)
    check('绕过口 /api/attachments/:id/extract',
      await status(c, `/api/attachments/${standalone.id}/extract`), 403)
    check('附件总表 /api/attachments/all', await status(c, '/api/attachments/all'), 403)

    const s = await json(c, '/api/search?q=a')
    check('全局搜索不返回文件命中', (s.body.documents || []).length, 0)

    if (attached) {
      // 关键：记录附件跟记录本身的模型权限走，不能被数据中心页面权限误伤
      check('记录附件跟随记录模型权限（不该被误伤）',
        await status(c, `/api/documents/${attached.id}/raw`), 200)
    }
  }

  // ---------- B. 只给数据中心 ----------
  console.log('\n=== B. 只给数据中心的角色 ===')
  {
    const c = await loginAs(filesUser, PASS)
    check('文档列表 /api/documents', await status(c, '/api/documents'), 200)
    check('文件原文 /api/documents/:id/raw',
      await status(c, `/api/documents/${standalone.id}/raw`), 200)
    check('文件抽取 /api/documents/:id/content',
      await status(c, `/api/documents/${standalone.id}/content`), 200)
    check('笔记双链 /api/notes/:id/backlinks', await status(c, '/api/notes/1/backlinks'), 403)
    check('笔记图谱 /api/graph/notes', await status(c, '/api/graph/notes'), 403)
    check('知识关联 /api/knowledge/note-type', await status(c, '/api/knowledge/note-type'), 403)
    if (attached) {
      check('记录附件跟随记录模型权限（模型不可读应被拒）',
        await status(c, `/api/documents/${attached.id}/raw`), 403)
    }
  }

  // ---------- C. 管理员一切照旧 ----------
  console.log('\n=== C. 管理员 ===')
  {
    const c = S.cookies()
    check('文档列表 /api/documents', await status(c, '/api/documents'), 200)
    check('文件原文 /api/documents/:id/raw',
      await status(c, `/api/documents/${standalone.id}/raw`), 200)
    check('绕过口 /api/attachments/:id/preview',
      await status(c, `/api/attachments/${standalone.id}/preview`), 200)
    check('笔记双链 /api/notes/:id/backlinks', await status(c, '/api/notes/1/backlinks'), 200)
    check('知识关联 /api/knowledge/note-type', await status(c, '/api/knowledge/note-type'), 200)
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
      process.exitCode = 1
    } else {
      console.log('✅ 全部通过')
    }
  })
