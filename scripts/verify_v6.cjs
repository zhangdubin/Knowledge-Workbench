// 验证这一轮优化
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  const errors = []
  page.on('pageerror', err => errors.push(`PAGE ${err.message}`))
  page.on('console', async msg => {
    if (msg.type() === 'error') {
      try {
        const args = msg.args()
        if (!args.length) return
        const txt = await page.evaluate((a) => {
          try { return typeof a === 'string' ? a : a?.message || String(a) }
          catch { return null }
        }, args[0])
        if (!txt || /vis-data|hammerjs|deprecated/i.test(txt)) return
        errors.push(`CON ${txt}`)
      } catch {}
    }
  })

  const SHOTS = [
    { path: '/', name: '01-dashboard' },
    { path: '/#/apps', name: '02-apps' },
    { path: '/#/apps/project', name: '03-app-detail' },
    { path: '/#/types', name: '04-types' },
    { path: '/#/types/1/edit', name: '05-type-editor' },
    { path: '/#/records/1', name: '06-records' },
    { path: '/#/search', name: '07-search' },
    { path: '/#/knowledge/graph', name: '08-knowledge-graph' },
    { path: '/#/graph', name: '09-graph' },
  ]

  for (const s of SHOTS) {
    console.log(`\n→ ${s.name}: ${s.path}`)
    try {
      await page.goto(`http://127.0.0.1:8082${s.path}`, { waitUntil: 'networkidle0', timeout: 20000 })
      await new Promise(r => setTimeout(r, 2000))
      await page.screenshot({ path: `/tmp/v6-${s.name}.png` })
      console.log('   saved')
    } catch (e) {
      console.log('   FAIL', e.message)
    }
  }

  console.log(`\n=== 错误: ${errors.length} ===`)
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
  process.exit(errors.length ? 1 : 0)
})()