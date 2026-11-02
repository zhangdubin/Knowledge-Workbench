/**
 * 打印功能验收
 *
 *   ① 知识库（Library.vue）—— 数据中心的文件列表
 *   ② 数据中心记录（Records.vue）
 *   ③ 笔记列表（Notes.vue）
 *   ④ 笔记详情（NoteDetail.vue）
 *   ⑤ 关联图谱（GraphView.vue）
 *   ⑥ 知识图谱（KnowledgeGraph.vue）
 *
 * 验的是什么（都是用户真正会踩到的点）：
 *   · 每页都有一个「打印」按钮（图标 + 文字，不能只有一个图标）
 *   · 切到 print 媒体后：侧边导航、顶栏、工具条、按钮都不该出现在纸上
 *   · 正文必须在（不然打出来是白纸）
 *   · 表格要有表头（el-table 的表头在另一个 table 里，
 *     不做处理的话只有第一页有表头）
 *   · 图谱页要给出节点清单（canvas 印不出来）
 *   · 点了打印按钮要真的调起 window.print（有内容时）
 *
 * 用法：
 *   node scripts/kb-verify-print.cjs
 *   BASE=http://127.0.0.1:5173 node scripts/kb-verify-print.cjs
 *
 * 跑之前要确认前端是**最新**的：
 *   · 用容器：cd frontend && npm run build && docker compose up -d frontend
 *   · 用开发服务器：cd frontend && npx vite --port 5173（BASE 指到 5173）
 * 前端没更新的话，每个页面都会报「没有打印按钮」——
 * 那不是代码坏了，是页面还是旧的。
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const API = process.env.API_BASE || 'http://127.0.0.1:8001'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

function sessionToken() {
  if (process.env.KB_TOKEN) return process.env.KB_TOKEN
  try {
    return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT }).trim()
  } catch (e) { return '' }
}

let fail = 0
const ok = (cond, tag, extra) => {
  if (cond) console.log('  ✓ ' + tag + (extra ? ' → ' + extra : ''))
  else { console.log('  ✗ ' + tag + (extra ? ' → ' + extra : '')); fail++ }
}

/** 元素在当前媒体下是不是真的看得见（不是只存在 DOM 里） */
const VISIBLE = (sel) => {
  const el = document.querySelector(sel)
  if (!el) return false
  const cs = getComputedStyle(el)
  if (cs.display === 'none' || cs.visibility === 'hidden') return false
  if (parseFloat(cs.opacity) === 0) return false
  const r = el.getBoundingClientRect()
  return r.width > 0 || r.height > 0
}

/** 取第一个匹配的元素：拿它的文字、类名、以及「打印媒体下还在不在」 */
const PROBE = (sel) => {
  const el = document.querySelector(sel)
  if (!el) return { found: false }
  const cs = getComputedStyle(el)
  const r = el.getBoundingClientRect()
  return {
    found: true,
    text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
    display: cs.display,
    visibility: cs.visibility,
    visible: cs.display !== 'none' && cs.visibility !== 'hidden'
      && (r.width > 0 || r.height > 0),
  }
}

async function apiGet(pathname) {
  const token = sessionToken()
  const res = await fetch(API + pathname, { headers: { cookie: 'kb_session=' + token } })
  if (!res.ok) return null
  return await res.json()
}

/** 找一个有记录的模型（记录页要能打开才有东西可打） */
async function pickTypeWithRecords() {
  const types = await apiGet('/api/entity-types')
  const list = Array.isArray(types) ? types : (types && types.items) || []
  for (const t of list) {
    const rec = await apiGet('/api/records/type/' + t.id + '?page_size=1')
    if (rec && (rec.items || []).length) return t
  }
  return list[0] || null
}

/** 找一篇笔记（笔记详情页要能打开才有东西可打） */
async function pickNote() {
  const nt = await apiGet('/api/entity-types/by-key/note')
  if (!nt || !nt.id) return null
  const rec = await apiGet('/api/records/type/' + nt.id + '?page_size=1')
  const item = rec && (rec.items || [])[0]
  return item || null
}

;(async () => {
  console.log('打印功能验收')
  console.log('前端：' + BASE)
  console.log('后端：' + API)

  const type = await pickTypeWithRecords()
  const note = await pickNote()
  if (!type) console.log('（没找到数据模型，记录页可能打不开）')
  if (!note) console.log('（没找到笔记，笔记详情页可能打不开）')

  const pages = [
    {
      name: '知识库（数据中心）',
      url: '/#/library',
      toolbar: '.toolbar',
      content: '.main-tabs',
      table: '.el-table',
      extraHidden: ['.upload-card'],
    },
    {
      name: '数据中心（记录）',
      url: type ? '/#/records/' + type.id : '/#/records/1',
      toolbar: '.toolbar',
      content: '.card',
      table: '.el-table',
    },
    {
      name: '笔记列表（知识库）',
      url: '/#/notes',
      toolbar: '.notes-toolbar',
      content: '.notes-main',
      table: null,
      extraHidden: ['.notes-groups'],
    },
    {
      name: '笔记详情',
      url: note ? '/#/notes/' + note.id : '/#/notes/1',
      toolbar: '.nd-topbar',
      content: '.nd-main',
      table: null,
    },
    {
      name: '关联图谱',
      url: '/#/graph',
      toolbar: '.page-header .actions',
      content: '.page',
      table: null,
      graph: true,
    },
    {
      name: '知识图谱',
      url: '/#/knowledge/graph',
      toolbar: '.page-header .actions',
      content: '.page',
      table: null,
      graph: true,
    },
  ]

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const errs = []
  page.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  page.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1440, height: 900 })

  let navSeq = 0
  let pagesWithButton = 0
  for (const p of pages) {
    console.log('')
    console.log('▶ ' + p.name)
    // 每次都带一个不同的查询参数：
    // 只改 hash 的话浏览器不会重新加载文档，第二次导航经常停在空白的
    // router-view 上（第一次正常、后面全空），验出来的是假失败。
    await page.goto(BASE + '/?__print=' + (++navSeq) + p.url, { waitUntil: 'domcontentloaded' })
    // 等「打印」按钮真的出现再验：
    // 图谱这类页面要等后端把整张图算出来，固定等 2 秒时快时慢，
    // 慢的时候页面还没渲染完，验出来的是「没这个按钮」—— 假失败。
    await page.waitForSelector('[data-print-trigger]', { timeout: 25000 }).catch(() => {})
    await sleep(1500)

    // ---------- 打印按钮 ----------
    const btn = await page.evaluate(() => {
      const el = document.querySelector('[data-print-trigger]')
      if (!el) return null
      const r = el.getBoundingClientRect()
      return {
        text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
        hasIcon: !!el.querySelector('.el-icon, svg, i'),
        visible: r.width > 0 || r.height > 0,
      }
    })
    ok(!!btn, '有「打印」按钮')
    if (btn) pagesWithButton++
    if (btn) {
      ok(btn.text.includes('打印'), '按钮上有「打印」两个字', JSON.stringify(btn.text))
      ok(btn.hasIcon, '按钮上有图标（不能只有文字，也不能只有图标）')
      ok(btn.visible, '屏幕模式下按钮可见')
    }

    // ---------- 切到打印媒体 ----------
    await page.emulateMediaType('print')
    await sleep(260)

    ok(!(await page.evaluate(VISIBLE, '.sidebar')), '打印时侧边导航不见了')
    ok(!(await page.evaluate(VISIBLE, '.topbar')), '打印时顶栏不见了')
    ok(!(await page.evaluate(VISIBLE, p.toolbar)), '打印时工具条不见了', p.toolbar)
    ok(!(await page.evaluate(VISIBLE, '[data-print-trigger]')), '打印时「打印」按钮本身不见了')
    for (const sel of (p.extraHidden || [])) {
      ok(!(await page.evaluate(VISIBLE, sel)), '打印时这块不该在纸上', sel)
    }

    const content = await page.evaluate(PROBE, p.content)
    ok(content.found && content.visible, '打印时正文还在', p.content)

    const bar = await page.evaluate(PROBE, '.print-title-bar')
    ok(bar.found && bar.visible, '打印时能看到页眉（页面名 + 打印时间）')

    // 表格：表头要留着
    if (p.table) {
      const head = await page.evaluate((sel) => {
        const t = document.querySelector(sel)
        if (!t) return { found: false }
        const ths = t.querySelectorAll('th')
        let visible = 0
        ths.forEach((th) => {
          const cs = getComputedStyle(th)
          const r = th.getBoundingClientRect()
          if (cs.display !== 'none' && cs.visibility !== 'hidden' && (r.width > 0 || r.height > 0)) visible++
        })
        return { found: true, thCount: ths.length, visibleTh: visible }
      }, p.table)
      ok(head.found && head.visibleTh > 0, '打印时表格有表头',
        head.found ? ('th ' + head.visibleTh + '/' + head.thCount + ' 可见') : '没找到表格')
    }

    // 图谱页：画布印不出来，得给节点清单
    if (p.graph) {
      const list = await page.evaluate(PROBE, '.print-block')
      ok(list.found && list.visible, '打印时给出节点清单（画布印不出来）')
      const canvas = await page.evaluate(VISIBLE, 'canvas')
      ok(!canvas, '打印时画布不上了纸（canvas 印出来是空白）')
    }

    // ---------- 点一下打印按钮 ----------
    await page.emulateMediaType(null)
    await sleep(120)
    await page.evaluate(() => {
      window.__printCalls = 0
      window.__printSnapshot = null
      window.print = () => {
        window.__printCalls++
        // 打印那一刻的 DOM：el-table 的表头有没有被搬进表体的 thead
        window.__printSnapshot = [...document.querySelectorAll('.el-table')].map((t) => ({
          theadInBody: !!t.querySelector('.el-table__body-wrapper table thead'),
        }))
      }
    })
    const clicked = await page.evaluate(() => {
      const el = document.querySelector('[data-print-trigger]')
      if (!el) return false
      el.click()
      return true
    })
    ok(clicked, '「打印」按钮点了不报错')
    await sleep(400)
    const called = await page.evaluate(() => window.__printCalls || 0)
    const snap = await page.evaluate(() => window.__printSnapshot || [])
    const rootEmpty = await page.evaluate(() => {
      const r = document.querySelector('[data-print-root]')
      return r ? r.getAttribute('data-print-empty') : null
    })
    if (rootEmpty === 'true') {
      ok(called === 0, '页面是空的 → 不打印（不给你一张白纸）')
    } else {
      ok(called === 1, '点了打印真的调起 window.print', 'calls=' + called)
      if (snap.length) {
        ok(snap.every(s => s.theadInBody), '打印那一刻表格表头被搬进了表体（每页都能重复表头）',
          JSON.stringify(snap))
      }
      // 打印时间只有真要打印的那一刻才算数：
      // 页面挂载时算好的时间会骗人（用户可能开着页面看了一下午）
      const stamp = await page.evaluate(() => {
        const el = document.querySelector('[data-print-time]')
        return el ? (el.textContent || '').trim() : ''
      })
      ok(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(stamp), '打印时才填打印时间', stamp)
    }
  }

  console.log('')
  if (pagesWithButton === 0) {
    // 一个页面都没有按钮 —— 十有八九是前端没重新构建，
    // 而不是「打印功能没做」。说清楚，别让人白查。
    console.log('✗ 六个页面一个「打印」按钮都没有 —— 多半是前端还是旧构建：')
    console.log('   cd frontend && npm run build && docker compose up -d frontend')
    console.log('   或用开发服务器：cd frontend && npx vite --port 5173，再 BASE=http://127.0.0.1:5173 跑本脚本')
    fail++
  }
  if (errs.length) {
    console.log('页面报错：')
    errs.slice(0, 10).forEach(e => console.log('  ' + e))
  }
  await browser.close()

  if (fail) {
    console.log('✗ ' + fail + ' 项不通过')
    process.exit(1)
  }
  console.log('✓ 打印功能全部检查通过')
})().catch((e) => {
  console.error('✗ 验证脚本自身出错：' + (e && e.stack ? e.stack : e))
  process.exit(1)
})
