// 验证数据中心 + JSON 试验场
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const ROUTES = [
  { path: '/#/library', name: '数据中心' },
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
        const txt = await page.evaluate((a) => {
          try {
            if (typeof a === 'string') return a
            if (a?.message) return a.message
            if (a?.stack) return a.stack
            return String(a)
          } catch { return null }
        }, args[0])
        if (!txt || /vis-data|hammerjs|deprecated/i.test(txt)) return
        errors.push(`CON ${txt}`)
      } catch {}
    }
  })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400) {
      errors.push(`API ${r.status()} ${r.url()}`)
    }
  })

  for (const r of ROUTES) {
    console.log(`\n→ ${r.name}: ${r.path}`)
    try {
      await page.goto(`http://127.0.0.1:8082${r.path}`, { waitUntil: 'networkidle0', timeout: 25000 })
      await new Promise(resolve => setTimeout(resolve, 3000))
      const text = await page.evaluate(() => document.body.innerText.slice(0, 500))
      console.log(`   preview: ${text.replace(/\n+/g, ' | ').slice(0, 300)}`)
    } catch (e) {
      console.log(`   ❌ ${e.message}`)
    }
  }

  // 截图
  await page.goto('http://127.0.0.1:8082/#/library', { waitUntil: 'networkidle0' })
  await new Promise(resolve => setTimeout(resolve, 2500))
  await page.screenshot({ path: '/tmp/kb-library.png' })
  console.log('\n→ 截图：/tmp/kb-library.png')

  // 打开 JSON 试验场
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('button')]
    const btn = buttons.find(b => b.textContent.includes('JSON 试验场'))
    if (btn) btn.click()
  })
  await new Promise(resolve => setTimeout(resolve, 1500))
  await page.screenshot({ path: '/tmp/kb-json-playground.png' })
  console.log('→ 截图：/tmp/kb-json-playground.png')

  console.log(`\n=== 错误汇总: ${errors.length} ===`)
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
  process.exit(errors.length ? 1 : 0)
})()