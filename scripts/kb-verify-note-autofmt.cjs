#!/usr/bin/env node
/**
 * 新建笔记 · 自动排版 · 浏览器级验收
 *
 * 要验的不是「函数算得对」（那是 scripts/verify-note-format.py 的事），
 * 而是**整条路走通**：在列表页敲一段散乱正文 → 点保存 → 出来的笔记
 * 已经按《笔记 UI 排版规范》排好，而且**知识库自己的渲染器认得这些记号**。
 *
 * 断言的硬指标：
 *   1. 新建条上有「自动排版」开关，且默认是开的；
 *   2. 存下来的正文里有 front-matter / H1 语义 emoji / 摘要或元信息卡；
 *   3. 正文里的凭证变成 secret-toggle，且页面上渲染成**药丸**而不是源码；
 *   4. 命令行围栏成 ```bash，页面上是代码块；
 *   5. 列表摘要里**看不到明文口令**（遮盖不能只在详情页生效）；
 *   6. callout 正文里的 `- **创建**: …` 渲染成列表 + 粗体（不是裸星号）。
 *
 * 用法：
 *   node scripts/kb-verify-note-autofmt.cjs
 *   KB_FRONTEND=http://127.0.0.1:8082 KB_API=http://127.0.0.1:8001 node scripts/kb-verify-note-autofmt.cjs
 *
 * 前端必须是**新构建**（docker compose build frontend && docker compose up -d）。
 * 退出码 0 = 全过。
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

async function api(method, pathname, body, token) {
  const res = await fetch(API + pathname, {
    method,
    headers: { 'Cookie': 'kb_session=' + (token || sessionToken()), 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const ct = res.headers.get('content-type') || ''
  return { status: res.status, body: ct.includes('json') ? await res.json() : await res.text() }
}

/** 一段「人在现场随手记」的正文：没 front-matter、没章节、口令明文、命令裸着 */
const RAW = [
  '已成功登录 18001 的 session',
  '数据库 密码: YunHai@2026',
  '$ nmap -sV -p 18001 120.224.7.251',
  '$ curl -s http://120.224.7.251:18001/admin/login',
].join('\n')

async function main() {
  const token = sessionToken()
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1500, height: 950 })
  const consoleErrors = []
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message))

  let noteId = null
  try {
    await page.goto(FRONTEND + '/#/notes', { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1200)

    // ---- 1. 打开新建条 ----
    const opened = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find(b => /新建笔记|新建第一篇/.test(b.innerText))
      if (btn) { btn.click(); return true }
      return false
    })
    check('点开「新建笔记」', opened)

    // ---- 2. 自动排版开关默认开 ----
    const switchState = await page.evaluate(() => {
      const wrap = document.querySelector('.notes-composer-autofmt')
      if (!wrap) return { found: false }
      const input = wrap.querySelector('input[type="checkbox"]')
      return {
        found: true,
        checked: input ? input.checked : null,
        text: wrap.innerText.trim(),
        label: wrap.getAttribute('title') || '',
      }
    })
    check('新建条上有「自动排版」开关', switchState.found, JSON.stringify(switchState))
    check('开关默认是开的', switchState.checked === true, String(switchState.checked))

    // ---- 3. 填标题与正文，保存 ----
    await page.evaluate((raw) => {
      const title = document.querySelector('.composer-title')
      const ta = document.querySelector('.composer-editor')
      const set = (el, v) => {
        const proto = el.tagName === 'TEXTAREA'
          ? window.HTMLTextAreaElement.prototype
          : window.HTMLInputElement.prototype
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v)
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }
      set(title, '登录记录（排版自测）')
      set(ta, raw)
    }, RAW)
    await sleep(300)
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find(b => /保存笔记|^(保存|创建)$/.test(b.innerText.trim()))
      if (btn) btn.click()
    })
    await sleep(2500)

    // 保存后会跳到详情页
    const url = page.url()
    check('保存后进入详情页', /#\/notes\/\d+/.test(url), url)
    noteId = Number((url.match(/#\/notes\/(\d+)/) || [])[1] || 0) || null

    if (!noteId) {
      // 退一步：从列表接口里找刚建的那篇
      const list = await api('GET', '/api/records/type/1?page_size=5')
      void list
    }

    // ---- 4. 库里存的是排版后的正文 ----
    const rec = noteId ? await api('GET', `/api/records/${noteId}`) : { body: {} }
    const content = (rec.body?.data?.content) || ''
    check('正文里有 front-matter', content.startsWith('---'), content.slice(0, 60))
    check('H1 带语义 emoji', /^# [^\s]+ 登录记录/m.test(content), content.slice(0, 300))
    check('补了元信息卡或摘要', /\[!info\] 元信息|\[!abstract\]/.test(content), content.slice(0, 400))
    check('凭证变成 secret-toggle', content.includes('secret-toggle'), content.slice(0, 600))
    check('命令行围栏成 bash', content.includes('```bash'), content.slice(0, 800))

    // ---- 5. 页面渲染：认得这些记号 ----
    await page.goto(FRONTEND + '/#/notes/' + noteId, { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1500)
    const dom = await page.evaluate(() => {
      const body = document.querySelector('.note-body')
      if (!body) return { found: false }
      const secret = body.querySelector('.secret-toggle')
      const mask = body.querySelector('.secret-toggle .secret-mask')
      const value = body.querySelector('.secret-toggle .secret-value')
      const pre = body.querySelector('pre.md-pre')
      const callout = body.querySelector('.md-callout')
      const style = secret ? getComputedStyle(secret.querySelector('.secret-value')) : null
      const maskStyle = mask ? getComputedStyle(mask) : null
      return {
        found: true,
        hasSecret: !!secret,
        maskText: mask ? mask.textContent : '',
        valueDisplay: style ? style.display : '',
        maskDisplay: maskStyle ? maskStyle.display : '',
        hasPre: !!pre,
        hasCallout: !!callout,
        // 裸源码不该出现在正文里
        rawTags: (body.innerHTML.match(/&lt;span class="secret-toggle"/g) || []).length,
        rawStars: body.innerText.includes('**'),
        text: body.innerText.slice(0, 400),
      }
    })
    check('详情页渲染出 secret-toggle 元素', dom.found && dom.hasSecret, JSON.stringify(dom).slice(0, 300))
    check('遮罩默认可见、明文默认隐藏',
      dom.maskDisplay !== 'none' && dom.valueDisplay === 'none',
      `mask=${dom.maskDisplay} value=${dom.valueDisplay}`)
    check('页面上不出现 secret-toggle 源码', dom.rawTags === 0, String(dom.rawTags))
    check('命令渲染成代码块', dom.hasPre, String(dom.hasPre))
    check('callout 渲染成卡片', dom.hasCallout, String(dom.hasCallout))
    check('callout 里的粗体不是裸星号', !dom.rawStars, dom.text)

    // ---- 5.5 详情页「排版」入口：已经排好的笔记应该是「无需改动」 ----
    const openedDlg = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find(b => /^\s*排版\s*$/.test(b.innerText.trim()))
      if (btn) { btn.click(); return true }
      return false
    })
    check('详情页有「排版」入口', openedDlg)
    await sleep(1800)
    const dlg = await page.evaluate(() => {
      const box = document.querySelector('.el-dialog, .dialog-shell')
      if (!box) return { found: false }
      const text = box.innerText
      const applyBtn = Array.from(box.querySelectorAll('button'))
        .find(b => /应用|无需改动/.test(b.innerText))
      return {
        found: true,
        clean: /已经很规范|无需改动/.test(text),
        hasTab: /改了什么|排完之后/.test(text),
        applyDisabled: applyBtn ? applyBtn.disabled || applyBtn.classList.contains('is-disabled') : null,
        snippet: text.replace(/\s+/g, ' ').slice(0, 160),
      }
    })
    check('排版弹窗打开了', dlg.found, JSON.stringify(dlg))
    check('弹窗里有「改了什么 / 排完之后」两栏', dlg.hasTab, dlg.snippet)
    check('已经排好的笔记显示「无需改动」且按钮禁用', dlg.clean && dlg.applyDisabled === true,
      `clean=${dlg.clean} disabled=${dlg.applyDisabled}`)
    await page.evaluate(() => {
      const box = document.querySelector('.el-dialog, .dialog-shell')
      const btn = box && Array.from(box.querySelectorAll('button')).find(b => b.innerText.trim() === '取消')
      if (btn) btn.click()
    })
    await sleep(500)

    // ---- 6. 列表摘要不泄露明文 ----
    await page.goto(FRONTEND + '/#/notes', { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1500)
    const snippet = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll('.note-row'))
      const row = rows.find(r => /登录记录（排版自测）/.test(r.innerText))
      return row ? row.querySelector('.note-row-snippet')?.innerText || '' : ''
    })
    check('列表里找到这篇笔记', !!snippet)
    check('列表摘要不含明文口令', !snippet.includes('YunHai@2026'), snippet)

    check('浏览器无 JS 报错', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
  } finally {
    if (noteId) {
      await api('DELETE', `/api/records/${noteId}`)
      console.log(`  （已把自测笔记 #${noteId} 移进回收站）`)
    }
    await browser.close()
  }

  console.log()
  if (ERRORS.length) {
    console.log(`❌ ${ERRORS.length}/${CHECKS} 项失败：`)
    ERRORS.forEach(e => console.log('   · ' + e))
    process.exit(1)
  }
  console.log(`✅ ${CHECKS} 项全部通过`)
}

main().catch(e => { console.error(e); process.exit(1) })
