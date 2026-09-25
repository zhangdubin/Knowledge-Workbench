/**
 * 验证脚本共用的「会话 + 请求」助手
 *
 * v17 之后后端默认开启登录鉴权，所有 /api 调用（除 /api/auth/*）都需要 cookie。
 * 早先各验证脚本各自裸调 fetch，一开鉴权就全线 401 —— 与其在每个脚本里
 * 复制粘贴一遍登录取 cookie，不如集中在这里，改一处全体生效。
 *
 * 用法：
 *   const S = require('./lib/session.cjs')
 *   await S.login()                      // 登录取 cookie（幂等，只登一次）
 *   const r = await S.j('/api/entity-types')   // r = { status, body }
 *   await S.loginPage(page)              // Puppeteer：走登录页真实登录
 */
const API = process.env.KB_API || 'http://localhost:8001'
const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'

let cookie = ''          // 'kb_session=xxx'，登录后填充
let user = null

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

/** 从 Set-Cookie 头里剥出 name=value，仅保留本次会话需要的部分 */
function pickCookie(setCookies) {
  return setCookies
    .map(sc => String(sc).split(';')[0].trim())
    .filter(Boolean)
    .join('; ')
}

async function login() {
  if (cookie) return user
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok || !body.ok) {
    throw new Error(`登录失败：HTTP ${r.status} ${JSON.stringify(body).slice(0, 200)}`)
  }
  const raw = r.headers.getSetCookie ? r.headers.getSetCookie() : [r.headers.get('set-cookie')]
  cookie = pickCookie(raw)
  if (!cookie) throw new Error('登录成功但响应没有下发 cookie（鉴权通道异常）')
  user = body.user
  if (user && user.must_change_password) {
    throw new Error('管理员仍处于「必须改口令」状态，请先用新口令登录或改密')
  }
  return user
}

/** 统一的请求入口：自动带上会话 cookie，并把响应解析成 {status, body} */
async function j(path, opts = {}) {
  if (!cookie) await login()
  const headers = { ...(opts.headers || {}) }
  if (cookie) headers.Cookie = cookie
  const r = await fetch(API + path, { ...opts, headers })
  const ct = r.headers.get('content-type') || ''
  const body = ct.includes('json') ? await r.json() : await r.text()
  return { status: r.status, body }
}

async function post(path, payload) {
  return j(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

async function put(path, payload) {
  return j(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

async function patch(path, payload) {
  return j(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

async function del(path) {
  return j(path, { method: 'DELETE' })
}

/**
 * Puppeteer：走真实登录页登录。
 * 直接塞 cookie 会跳过「登录页 → 守卫 → 跳转」这条真实链路，
 * 而这条链路的正确性恰恰是权限这一轮最该被验证的东西。
 *
 * 注意前端用的是 hash 路由（createWebHashHistory），所以「当前在哪一页」
 * 要看 location.hash，不能看 pathname —— pathname 永远是 nginx 返回
 * index.html 的那个路径。
 */
async function loginPage(page, { user: u = USER, pass: p = PASS, navigate = true } = {}) {
  // 已经在登录页就别再跳一次：`/#/login` 会把守卫带过来的 ?redirect= 冲掉，
  // 登完只能回到首页，「登录后回跳原页面」这条也就测不出来了。
  const onLogin = await page.evaluate(() => location.hash.startsWith('#/login')).catch(() => false)
  if (!onLogin && navigate) await page.goto(`${FE}/#/login`, { waitUntil: 'networkidle2' })
  const userSel = 'input[autocomplete="username"]'
  const passSel = 'input[autocomplete="current-password"]'
  await page.waitForSelector(userSel, { timeout: 15000 })
  await page.$eval(userSel, el => { el.value = '' })
  await page.type(userSel, u)
  await page.$eval(passSel, el => { el.value = '' })
  await page.type(passSel, p)
  await page.click('button.submit')
  // 等守卫放行：hash 不再是 /login 即视为通过
  const t0 = Date.now()
  while (Date.now() - t0 < 15000) {
    const h = await page.evaluate(() => location.hash)
    if (!h.includes('/login')) return true
    await sleep(200)
  }
  return false
}

/**
 * 轮询等一个前端结果落地（固定 sleep 只能碰运气）。
 * 多出来的参数会一并传给页面里的判断函数，省得为了带个参数去拼字符串。
 */
async function waitFor(page, fn, ms = 8000, ...args) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    const v = await page.evaluate(fn, ...args)
    if (v) return v
    await sleep(150)
  }
  return null
}

function cookies() { return cookie }

module.exports = { API, FE, USER, PASS, login, j, post, put, patch, del, loginPage, waitFor, sleep, cookies }
