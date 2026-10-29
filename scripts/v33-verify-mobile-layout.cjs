/**
 * 手机版（390×844）排版体检
 * ---------------------------------------------------------------------------
 * 检查的是「手机用户真的能感觉到」的问题，不是像素洁癖：
 *   1. 顶栏控件互相压住（搜索框盖住页面标题）
 *   2. 页面横向溢出（内容比屏幕宽）
 *   3. 弹窗/抽屉在手机上不是全屏
 *   4. 统计卡占掉半屏，下面的内容被顶没
 *   5. 悬停才出现的按钮在触摸设备上点不到
 *
 * 用法：BASE=http://localhost:5173 KB_USER=admin KB_PASS=xxx node scripts/v33-verify-mobile-layout.cjs
 * 截图：SHOTS=1 时把每页截图写到 /tmp/mobile-<页面>.png
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const { USER, PASS } = require('../scripts/lib/session.cjs')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const BASE = process.env.BASE || 'http://localhost:5173'
const W = Number(process.env.W || 390)
const H = Number(process.env.H || 844)

const PAGES = [
  ['知识库', '/#/notes', 'notes'],
  ['应用中心', '/#/apps', 'apps'],
  ['数据模型', '/#/types', 'types'],
  ['知识图谱', '/#/knowledge/graph', 'graph'],
  ['关联图谱', '/#/graph', 'graph2'],
  ['数据中心', '/#/library', 'library'],
  ['全局搜索', '/#/search', 'search'],
  ['工作台', '/#/', 'dashboard'],
  ['用户管理', '/#/system/users', 'users'],
  ['角色权限', '/#/system/roles', 'roles'],
  ['审计日志', '/#/system/audit', 'audit'],
  ['回收站', '/#/system/recycle', 'recycle'],
]

let failed = 0
let total = 0
function check(ok, label, detail = '') {
  total++
  if (!ok) failed++
  console.log(`  ${ok ? '✔' : '✘'} ${label}${detail ? `　${detail}` : ''}`)
}

async function main() {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: W, height: H, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })

  await p.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1500)
  const ins = await p.$$('input')
  await ins[0].click({ clickCount: 3 }); await ins[0].press('Backspace'); await ins[0].type(USER, { delay: 5 })
  await ins[1].click({ clickCount: 3 }); await ins[1].press('Backspace'); await ins[1].type(PASS, { delay: 5 })
  await p.evaluate(() => {
    const x = Array.from(document.querySelectorAll('button')).find((e) => (e.innerText || '').trim() === '登录')
    x && x.click()
  })
  for (let i = 0; i < 30; i++) {
    await sleep(400)
    if (!(await p.evaluate(() => location.hash.includes('/login')))) break
  }
  const loggedIn = !(await p.evaluate(() => location.hash.includes('/login')))
  check(loggedIn, '登录成功', `${USER}`)
  if (!loggedIn) { await b.close(); process.exit(1) }

  console.log(`\n视口 ${W}×${H}\n`)

  for (const [name, route, slug] of PAGES) {
    await p.goto(`${BASE}${route}`, { waitUntil: 'networkidle2' })
    await sleep(2200)
    if (process.env.SHOTS === '1') {
      await p.screenshot({ path: `/tmp/mobile-${slug}.png`, fullPage: false })
    }

    const r = await p.evaluate(() => {
      const vw = document.documentElement.clientWidth
      const out = { overflow: document.documentElement.scrollWidth - vw, overlaps: [], statH: 0, hoverOnly: [] }

      // 顶栏：所有可见控件两两求交
      const bar = document.querySelector('.topbar')
      if (bar) {
        const items = Array.from(bar.querySelectorAll('button, input, .user-chip, .page-title, .search-input'))
          .map((el) => {
            const q = el.getBoundingClientRect()
            return { label: (el.getAttribute('aria-label') || el.className || el.tagName).toString().slice(0, 24), l: q.left, r: q.right, t: q.top, b: q.bottom, w: q.width, h: q.height }
          })
          .filter((x) => x.w > 0 && x.h > 0)
        for (let i = 0; i < items.length; i++) {
          for (let j = i + 1; j < items.length; j++) {
            const a = items[i], c = items[j]
            const ox = Math.min(a.r, c.r) - Math.max(a.l, c.l)
            const oy = Math.min(a.b, c.b) - Math.max(a.t, c.t)
            if (ox > 1 && oy > 1) out.overlaps.push(`${a.label}×${c.label}(${Math.round(ox)}px)`)
          }
        }
      }

      // 统计卡高度：超过视口的 1/4 就算占太多
      const sg = document.querySelector('.stat-grid')
      if (sg) out.statH = Math.round(sg.getBoundingClientRect().height)

      // 悬停才出现的操作按钮（触摸设备上点不到）
      for (const sel of ['.ft-actions', '.dc-actions', '.note-row-del', '.ng-side-more']) {
        const el = document.querySelector(sel)
        if (el) {
          const cs = getComputedStyle(el)
          if (parseFloat(cs.opacity) < 0.2 && cs.visibility !== 'hidden') out.hoverOnly.push(sel)
        }
      }
      return out
    })

    const bad = r.overlaps.length
    check(bad === 0, `${name}：顶栏无重叠`, bad ? r.overlaps.join(' ') : '')
    check(r.overflow === 0, `${name}：页面无横向溢出`, `溢出 ${r.overflow}px`)
    if (r.statH) check(r.statH <= H * 0.25, `${name}：统计卡不占半屏`, `${r.statH}px（上限 ${Math.round(H * 0.25)}px）`)
    check(r.hoverOnly.length === 0, `${name}：操作按钮不靠 hover 才出现`, r.hoverOnly.join(' '))
  }

  // ---- 弹窗：手机上必须整屏 ----
  console.log('\n弹窗 / 抽屉')
  await p.goto(`${BASE}/#/system/users`, { waitUntil: 'networkidle2' })
  await sleep(2000)
  await p.evaluate(() => {
    const x = Array.from(document.querySelectorAll('button')).find((e) => (e.innerText || '').includes('新建用户'))
    x && x.click()
  })
  await sleep(1200)
  const dlg = await p.evaluate(() => {
    const d = document.querySelector('.el-dialog')
    if (!d) return null
    const r = d.getBoundingClientRect()
    const foot = d.querySelector('.el-dialog__footer')
    return {
      w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top),
      vw: document.documentElement.clientWidth, vh: window.innerHeight,
      footerBottom: foot ? Math.round(foot.getBoundingClientRect().bottom) : null,
      bodyScroll: d.querySelector('.el-dialog__body') ? getComputedStyle(d.querySelector('.el-dialog__body')).overflowY : '',
    }
  })
  check(!!dlg, '弹窗能打开')
  if (dlg) {
    check(dlg.w >= dlg.vw - 1 && dlg.h >= dlg.vh - 2, '弹窗在手机上整屏', `${dlg.w}×${dlg.h}（视口 ${dlg.vw}×${dlg.vh}）`)
    check(dlg.x <= 1 && dlg.y <= 1, '弹窗贴左上（不是浮在页面中间）', `x=${dlg.x} y=${dlg.y}`)
    check(dlg.footerBottom !== null && dlg.footerBottom >= dlg.vh - 24, '弹窗底部动作区贴着屏幕底部', `bottom=${dlg.footerBottom}`)
    check(dlg.bodyScroll === 'auto' || dlg.bodyScroll === 'scroll', '正文区可滚动', dlg.bodyScroll)
  }
  await p.keyboard.press('Escape')
  await sleep(600)

  // ---- 抽屉：手机上必须整屏（导航抽屉 260px、AI 助理除外）----
  await p.goto(`${BASE}/#/records/1`, { waitUntil: 'networkidle2' })
  await sleep(2400)
  const drawer = await p.evaluate(() => {
    const d = Array.from(document.querySelectorAll('.el-drawer'))
      .find((x) => !x.classList.contains('mobile-drawer') && !x.classList.contains('agent-drawer'))
    if (!d) return null
    return { computedW: getComputedStyle(d).width, inline: d.getAttribute('style') || '', cls: d.className }
  })
  check(!!drawer && drawer.computedW === '100%', '业务抽屉在手机上整屏', drawer ? `计算宽 ${drawer.computedW}（内联 ${drawer.inline}）` : '没找到抽屉')

  // ---- 知识库页头：动作区要和标题对齐 ----
  console.log('\n知识库页头')
  await p.goto(`${BASE}/#/notes`, { waitUntil: 'networkidle2' })
  await sleep(2200)
  const head = await p.evaluate(() => {
    const t = document.querySelector('.notes-head-title')
    const a = document.querySelector('.notes-head-actions')
    const s = document.querySelector('.notes-search')
    const tr = document.querySelector('.notes-toolbar-right')
    if (!t || !a) return null
    const tr_ = t.getBoundingClientRect(), ar = a.getBoundingClientRect()
    const sr = s ? s.getBoundingClientRect() : null
    const rr = tr ? tr.getBoundingClientRect() : null
    return {
      titleX: Math.round(tr_.left), actionsX: Math.round(ar.left),
      actionsRight: Math.round(ar.right),
      cardRight: Math.round(ar.right + parseFloat(getComputedStyle(a).marginRight || 0)),
      searchY: sr ? Math.round(sr.top) : null, searchW: sr ? Math.round(sr.width) : null,
      rightY: rr ? Math.round(rr.top) : null,
      parentW: Math.round(a.parentElement.getBoundingClientRect().width),
    }
  })
  check(!!head, '找到知识库页头')
  if (head) {
    check(Math.abs(head.titleX - head.actionsX) <= 2, '动作区左边缘与标题对齐', `标题 x=${head.titleX} / 动作 x=${head.actionsX}`)
    check(head.searchY === null || head.rightY === null || head.searchY !== head.rightY, '搜索框与视图切换不在同一行', `搜索 y=${head.searchY} / 视图 y=${head.rightY}`)
  }

  await b.close()
  console.log(`\n共 ${total} 项断言，${failed} 项未通过`)
  process.exit(failed ? 1 : 0)
}
main().catch((e) => { console.error(e); process.exit(1) })
