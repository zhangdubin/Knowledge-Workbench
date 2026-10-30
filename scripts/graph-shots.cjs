/**
 * 图谱页面自检截图 + 基本体检
 * 出图：桌面 1600 / 手机 390，浅色 + 暗色
 * 体检：画布可见、无横向溢出、节点字号在缩放后仍然够大、图例存在
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || process.env.KB_FRONTEND || 'http://localhost:5173'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'
const sleep = ms => new Promise(r => setTimeout(r, ms))

const ROUTES = [
  ['rel', '/#/graph'],
  ['note', '/#/knowledge/graph'],
]
const SIZES = [[1600, 900], [390, 780]]

const PROBE = () => {
  const net = window.__kbGraph
  const canvas = document.querySelector('.gc-canvas canvas')
  const host = document.querySelector('.gc-canvas')
  const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
  const nodes = net ? Object.values(net.body.nodes).filter(n => !n.options.hidden && !String(n.id).startsWith('edgeId:')) : []
  const fontSize = nodes[0]?.options?.font?.size || 0
  const scale = net ? net.getScale() : 0
  return {
    canvas: canvas ? { w: canvas.clientWidth, h: canvas.clientHeight } : null,
    hostVisible: host ? host.getBoundingClientRect().height > 100 : false,
    horizontalOverflow: overflow,
    nodeCount: nodes.length,
    nodeFontPx: fontSize,
    onScreenFontPx: Math.round(fontSize * scale * 10) / 10,
    scale: Math.round(scale * 100) / 100,
    legends: document.querySelectorAll('.gc-legend').length,
    viaLegendVisible: !!document.querySelector('.gc-legend.via') &&
      getComputedStyle(document.querySelector('.gc-legend.via')).display !== 'none',
  }
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 900 })
  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1000)
  const inputs = await page.$$('input')
  await inputs[0].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[0].type(USER)
  await inputs[1].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[1].type(PASS)
  await page.click('button[type=submit], .el-button--primary')
  await sleep(2500)

  for (const dark of [false, true]) {
    await page.evaluate(d => {
      document.documentElement.classList.toggle('dark', d)
      localStorage.setItem('kb-theme', d ? 'dark' : 'light')
    }, dark)
    for (const [name, route] of ROUTES) {
      for (const [w, h] of SIZES) {
        await page.setViewport({ width: w, height: h })
        await page.goto(`${BASE}${route}?__e2e=1`, { waitUntil: 'networkidle2' })
        await page.waitForFunction(() => window.__kbGraph && Object.keys(window.__kbGraph.body.nodes || {}).length > 0, { timeout: 20000 }).catch(() => {})
        await sleep(4000)
        let probe
        try { probe = await page.evaluate(PROBE) } catch (e) { probe = { error: e.message } }
        console.log(`${name}@${w} ${dark ? 'dark ' : 'light'} → ${JSON.stringify(probe)}`)
        await page.screenshot({ path: `/tmp/gshot-${name}-${w}-${dark ? 'dark' : 'light'}.png` })
      }
    }
  }
  await browser.close()
})()
