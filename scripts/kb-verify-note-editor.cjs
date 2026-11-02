#!/usr/bin/env node
/**
 * 笔记编辑器 · 浏览器级验收（长笔记不能溢出编辑框）
 *
 * 用户报的现象：新建笔记粘一段长文，字的**下半截掉到框外面**，
 * 而且高亮层和文字框对不齐（双链高亮错位）。
 *
 * 根因（前端侧）：
 *   autoGrow 同时干了两件事 —— 设 CSS 变量 --composer-body-h，
 *   又给 textarea 写 inline style.height。
 *   textarea 是 position:absolute; inset:0，inline height 会盖掉 inset 的 bottom，
 *   于是文字框比容器高出一截；高亮覆盖层没跟着高 → 两层永远差几 px。
 *   另外上限写死 620px，长笔记最多只能显示 620px，剩下的够不着。
 *
 * 修完之后的硬指标（这里逐条断言）：
 *   1. textarea 的底边**不超出** .composer-body 的底边（字不掉到框外）；
 *   2. 高亮覆盖层与 textarea 高度差 = 0（逐像素一致）；
 *   3. 内容超出时**在框内滚动**（scrollHeight > clientHeight，且能滚到底）；
 *   4. 编辑区高度不超过「可视区高度 - 120」（不是写死的魔数）；
 *   5. quick（列表页内联新建）与 full（详情页整页编辑）两种模式都要过。
 *
 * 用法：
 *   node scripts/kb-verify-note-editor.cjs
 *   KB_FRONTEND=http://127.0.0.1:5174 node scripts/kb-verify-note-editor.cjs
 *
 * 前端要跑**新代码**：
 *   docker compose build frontend && docker compose up -d frontend
 *   或本地起 dev：cd frontend && npx vite --port 5174
 *
 * 退出码 0 = 全部通过；非 0 = 有问题（清单打印在最后）。
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const FRONTEND = (process.env.KB_FRONTEND || 'http://127.0.0.1:8082').replace(/\/+$/, '')
const API = (process.env.KB_API || 'http://127.0.0.1:8001').replace(/\/+$/, '')
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

const ERRORS = []
let CHECKS = 0
function check(name, cond, detail) {
  CHECKS++
  const good = typeof cond === 'function' ? !!cond() : !!cond
  console.log(`  ${good ? '✓' : '✗'} ${name}${good ? '' : '  ← ' + (detail || '')}`)
  if (!good) ERRORS.push(name + (detail ? '：' + detail : ''))
  return good
}

function sessionToken() {
  return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
    { encoding: 'utf8', cwd: ROOT }).trim()
}

async function api(pathname) {
  const res = await fetch(API + pathname, {
    headers: { 'Cookie': 'kb_session=' + sessionToken() },
  })
  const ct = res.headers.get('content-type') || ''
  const body = ct.includes('json') ? await res.json() : await res.text()
  return { status: res.status, body }
}

/** 造一段足够长的正文：200 行，每行都有内容 */
function longText(lines) {
  const out = []
  for (let i = 1; i <= (lines || 200); i++) {
    out.push(`第 ${i} 行：这是一段用于验证编辑器高度的长文本，内容要足够长才能把编辑框撑开。`)
  }
  return out.join('\n')
}

/**
 * 在页面里把正文灌进 textarea 并触发 input 事件。
 * 用真实事件而不是直接改 value —— 组件的 autoGrow 挂在 @input 上。
 */
async function fillBody(page, text) {
  await page.evaluate((t) => {
    const ta = document.querySelector('.composer-editor')
    if (!ta) throw new Error('找不到 .composer-editor')
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, t)
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  }, text)
  await sleep(400)
}

/** 量一次编辑框的几何关系 */
async function measure(page) {
  return await page.evaluate(() => {
    const body = document.querySelector('.composer-body')
    const ta = document.querySelector('.composer-editor')
    const ov = document.querySelector('.composer-overlay')
    if (!body || !ta) return null
    const b = body.getBoundingClientRect()
    const t = ta.getBoundingClientRect()
    const o = ov ? ov.getBoundingClientRect() : null
    return {
      bodyTop: b.top, bodyBottom: b.bottom, bodyH: b.height,
      taTop: t.top, taBottom: t.bottom, taH: t.height,
      ovH: o ? o.height : null,
      scrollH: ta.scrollHeight, clientH: ta.clientHeight,
      inlineH: ta.style.height || '',
      viewportH: window.innerHeight,
    }
  })
}

/** 统一的断言：一次量测结果要同时满足这几条 */
function assertGeometry(label, m) {
  if (!m) { check(label + '：量到几何数据', false, '找不到 .composer-body / .composer-editor'); return false }
  const overflow = m.taBottom - m.bodyBottom
  check(label + '：文字框底边不超出编辑框底边', overflow <= 0.5,
    `超出 ${overflow.toFixed(1)}px（框底 ${m.bodyBottom.toFixed(1)} / 文字框底 ${m.taBottom.toFixed(1)}）`)
  check(label + '：高亮层与文字框高度一致',
    m.ovH === null || Math.abs(m.ovH - m.taH) <= 0.5,
    `overlay ${m.ovH} vs textarea ${m.taH}`)
  check(label + '：文字框没有 inline height（高度只由 CSS 变量驱动）',
    !m.inlineH, `inline height = ${JSON.stringify(m.inlineH)}`)
  check(label + '：长内容在框内可滚（scrollHeight > clientHeight）',
    m.scrollH > m.clientH + 1, `scrollHeight ${m.scrollH} / clientHeight ${m.clientH}`)
  check(label + '：编辑区高度不超过可视区高度 - 120',
    m.bodyH <= m.viewportH - 120 + 1, `body ${m.bodyH} / viewport ${m.viewportH}`)
  return true
}

/** 能不能滚到底（内容没被切掉） */
async function canScrollToEnd(page) {
  return await page.evaluate(async () => {
    const ta = document.querySelector('.composer-editor')
    if (!ta) return { reached: false, synced: false }
    ta.scrollTop = ta.scrollHeight
    // scroll 事件是异步派发的：组件在 @scroll 里同步高亮层，
    // 这里必须等事件跑完再比，否则测的是「还没同步」的状态
    await new Promise(r => setTimeout(r, 120))
    const reached = ta.scrollTop + ta.clientHeight >= ta.scrollHeight - 1
    const ov = document.querySelector('.composer-overlay')
    const synced = !ov || Math.abs(ov.scrollTop - ta.scrollTop) <= 1
    return { reached, synced, scrollTop: ta.scrollTop }
  })
}

async function main() {
  console.log('\n▶  准备浏览器')
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1600, height: 950 })
  const consoleErrors = []
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message))

  // ---------- 1. quick 模式：列表页内联新建 ----------
  console.log('\n▶  quick 模式（知识库列表页内联新建）')
  await page.goto(FRONTEND + '/#/notes', { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(1500)
  const opened = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(
      b => /新建笔记/.test(b.innerText))
    if (btn) { btn.click(); return true }
    return false
  })
  check('点开「新建笔记」', opened)
  await sleep(800)
  check('quick 模式编辑器已出现', await page.evaluate(() => !!document.querySelector('.composer-editor')))
  await fillBody(page, longText(200))
  const qm = await measure(page)
  assertGeometry('quick', qm)
  const qs = await canScrollToEnd(page)
  check('quick：能滚到内容末尾（没被切掉）', qs.reached, JSON.stringify(qs))
  check('quick：高亮层与文字框滚动同步', qs.synced, JSON.stringify(qs))
  // 删掉内容后要缩回起始高度：
  // 量内容高度时如果没归零，scrollHeight 会被容器高度顶住，框就永远缩不回去
  await fillBody(page, '')
  await sleep(300)
  const shrunk = await measure(page)
  check('quick：内容删光后编辑区缩回起始高度', shrunk && shrunk.bodyH <= 200,
    'bodyH=' + (shrunk && shrunk.bodyH))

  // ---------- 2. full 模式：详情页整页编辑 ----------
  console.log('\n▶  full 模式（笔记详情页整页编辑）')
  // 记录接口要的是模型 id，不是 key —— 先把 note 模型的 id 换出来
  const typeRes = await api('/api/entity-types/by-key/note')
  const noteTypeId = typeRes.body && typeRes.body.id
  let noteId = null
  if (noteTypeId) {
    const notesRes = await api('/api/records/type/' + noteTypeId + '?page=1&page_size=1')
    const items = (notesRes.body && notesRes.body.items) || []
    if (items.length) noteId = items[0].id
  }
  check('取到一篇已有笔记用于验证 full 模式', !!noteId, 'typeId=' + noteTypeId)
  if (noteId) {
    await page.goto(FRONTEND + '/#/notes/' + noteId, { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1500)
    const editClicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(
        b => /^编辑$/.test(b.innerText.trim()))
      if (btn) { btn.click(); return true }
      return false
    })
    check('点开「编辑」进入 full 模式', editClicked)
    await sleep(900)
    check('full 模式编辑器已出现', await page.evaluate(() => !!document.querySelector('.composer-editor')))
    await fillBody(page, longText(200))
    const fm = await measure(page)
    assertGeometry('full', fm)
    const fs = await canScrollToEnd(page)
    check('full：能滚到内容末尾（没被切掉）', fs.reached, JSON.stringify(fs))
    check('full：高亮层与文字框滚动同步', fs.synced, JSON.stringify(fs))
    await fillBody(page, '')
    await sleep(300)
    const shrunk = await measure(page)
    check('full：内容删光后编辑区缩回起始高度', shrunk && shrunk.bodyH <= 440,
      'bodyH=' + (shrunk && shrunk.bodyH))
  }

  check('全程没有 JS 报错', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))

  await browser.close()
  console.log('\n' + (ERRORS.length ? '✗ ' + ERRORS.length + ' 项未通过' : '✓ 全部 ' + CHECKS + ' 项检查通过'))
  if (ERRORS.length) {
    ERRORS.forEach(e => console.log('  · ' + e))
    process.exit(1)
  }
}

main().catch(e => { console.error(e); process.exit(1) })
