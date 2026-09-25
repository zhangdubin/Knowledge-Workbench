/**
 * 移动端审计：390px 视口逐页检测横向溢出 + 弹窗是否超出界面
 *
 * 背景：用户反馈手机端「弹窗超界面」「工作台竖着罗列不实用」。
 * 本脚本断言两件事：
 *   1. 每个关键页面 documentElement.scrollWidth == clientWidth（无横向滚动）
 *   2. 典型弹窗（固定 px 宽的 el-dialog）在 390px 视口里完整可见
 *
 * 需要免鉴权运行（KB_AUTH_ENABLED=false），否则页面会被守卫弹回登录页。
 *   用法：node mobile-audit.cjs
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')
const path = require('path')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const SHOT_DIR = path.join(__dirname, '..', 'docs', 'screenshots', 'mobile-audit')
fs.mkdirSync(SHOT_DIR, { recursive: true })

const PAGES = [
  { hash: '#/', name: '01-workbench' },
  { hash: '#/notes', name: '02-notes' },
  { hash: '#/library', name: '03-library' },
  { hash: '#/types', name: '04-entity-types' },
  { hash: '#/apps', name: '05-apps' },
  { hash: '#/relations', name: '06-relations' },
  { hash: '#/search?kw=x', name: '07-search' },
  { hash: '#/dashboards', name: '08-dashboards' },
  { hash: '#/system/users', name: '09-users' },
  { hash: '#/system/storage', name: '10-storage' },
  { hash: '#/guide', name: '11-guide' },
]

const sleep = ms => new Promise(r => setTimeout(r, ms))

// 页面级溢出扫描：找出所有右缘超出视口的可见元素
const SCAN = () => {
  const vw = document.documentElement.clientWidth
  const out = []
  const all = document.querySelectorAll('*')
  for (const el of all) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) continue
    const st = getComputedStyle(el)
    if (st.display === 'none' || st.visibility === 'hidden') continue
    if (r.right > vw + 2 || r.left < -2) {
      // 在横向可滚动容器内的元素不算页面溢出
      let p = el.parentElement, scrollable = false
      while (p) {
        const ps = getComputedStyle(p)
        if (/(auto|scroll)/.test(ps.overflowX)) { scrollable = true; break }
        p = p.parentElement
      }
      if (!scrollable) {
        out.push({
          tag: el.tagName.toLowerCase(),
          cls: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').slice(0, 60),
          right: Math.round(r.right), left: Math.round(r.left), vw,
        })
        if (out.length >= 6) break
      }
    }
  }
  return {
    scrollW: document.documentElement.scrollWidth,
    clientW: vw,
    offenders: out,
  }
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })

  let failed = 0
  const report = []

  for (const p of PAGES) {
    await page.goto(`${FE}/${p.hash}`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(600)   // 等图表/动画安定
    const r = await page.evaluate(SCAN)
    const overflowPx = r.scrollW - r.clientW
    const ok = overflowPx <= 1 && r.offenders.length === 0
    if (!ok) failed++
    report.push({ page: p.name, ok, overflowPx, offenders: r.offenders })
    console.log(`${ok ? '✅' : '❌'} ${p.name}  scrollW=${r.scrollW}/${r.clientW}${r.offenders.length ? '  offenders=' + JSON.stringify(r.offenders) : ''}`)
    await page.screenshot({ path: path.join(SHOT_DIR, `${p.name}.png`) })
  }

  // ---- 弹窗实测：dashboards 页的「新建空白驾驶舱」（width=520px 的 el-dialog） ----
  await page.goto(`${FE}/#/dashboards`, { waitUntil: 'networkidle2' })
  await sleep(400)
  const clicked = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    const b = btns.find(x => x.textContent.includes('空白'))
    if (b) { b.click(); return true }
    return false
  })
  if (clicked) {
    await sleep(800)
    const d = await page.evaluate(() => {
      const el = document.querySelector('.el-dialog')
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), vw: innerWidth, vh: innerHeight }
    })
    if (!d) {
      failed++
      console.log('❌ dialog 未打开')
    } else {
      const ok = d.left >= 0 && d.right <= d.vw && d.top >= 0 && d.bottom <= d.vh
      if (!ok) failed++
      console.log(`${ok ? '✅' : '❌'} dialog-fit  rect=${JSON.stringify(d)}`)
      await page.screenshot({ path: path.join(SHOT_DIR, '12-dialog.png') })
    }
  } else {
    failed++
    console.log('❌ 没找到「空白驾驶舱」按钮')
  }

  await browser.close()
  console.log(failed ? `\n${failed} 项失败` : '\n全部通过 ✅')
  process.exit(failed ? 1 : 0)
})().catch(e => { console.error('FATAL', e); process.exit(1) })
