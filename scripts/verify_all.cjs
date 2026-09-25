const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const ROUTES = [
  '/', '/#/notes', '/#/notes/14', '/#/knowledge/graph',
  '/#/apps', '/#/apps/knowledge', '/#/types', '/#/graph', '/#/search',
]

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1400, height: 900 })

  const errors = []
  page.on('pageerror', err => errors.push(`PAGE ${err.message}`))
  page.on('console', async msg => {
    if (msg.type() === 'error') {
      try {
        const args = msg.args()
        if (!args.length) return
        // 把 args[0] 在页面里 stringify，拿到字符串
        const txt = await page.evaluate((a) => {
          try {
            if (typeof a === 'string') return a
            if (a?.message) return a.message
            if (a?.stack) return a.stack
            return String(a)
          } catch { return '<unstringifiable>' }
        }, args[0])
        if (/vis-data|hammerjs|deprecated/i.test(txt)) return
        errors.push(`CON ${txt}`)
      } catch (e) {
        errors.push(`CON ${msg.text()}`)
      }
    }
  })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400) {
      errors.push(`API ${r.status()} ${r.url()}`)
    }
  })

  for (const path of ROUTES) {
    process.stdout.write(`\n→ ${path}  `)
    try {
      await page.goto(`http://127.0.0.1:8082${path}`, { waitUntil: 'networkidle0', timeout: 25000 })
      await new Promise(r => setTimeout(r, 1800))
      const text = await page.evaluate(() => document.body.innerText.length)
      console.log(`OK · ${text} chars`)
    } catch (e) {
      console.log(`FAIL · ${e.message}`)
    }
  }

  console.log(`\n=== 真实错误: ${errors.length} ===`)
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
  process.exit(errors.length ? 1 : 0)
})()