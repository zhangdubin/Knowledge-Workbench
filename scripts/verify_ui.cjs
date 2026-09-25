// UI 优化 + JSON 视图验证
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const SHOTS = [
  { path: '/', name: 'dashboard' },
  { path: '/#/notes', name: 'notes' },
  { path: '/#/notes/14', name: 'note-detail' },
  { path: '/#/library', name: 'library' },
  { path: '/#/apps', name: 'apps' },
]

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

  for (const s of SHOTS) {
    console.log(`\n→ ${s.name}: ${s.path}`)
    try {
      await page.goto(`http://127.0.0.1:8082${s.path}`, { waitUntil: 'networkidle0', timeout: 25000 })
      await new Promise(resolve => setTimeout(resolve, 2500))
      const chars = await page.evaluate(() => document.body.innerText.length)
      console.log(`   OK · ${chars} chars`)
      await page.screenshot({ path: `/tmp/ui-${s.name}.png` })
      console.log(`   saved /tmp/ui-${s.name}.png`)
    } catch (e) {
      console.log(`   FAIL · ${e.message}`)
    }
  }

  // NoteDetail 的 JSON 视图
  console.log('\n→ 切换 NoteDetail 到 JSON 视图...')
  await page.goto('http://127.0.0.1:8082/#/notes/14', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.el-tabs__item')]
    const t = tabs.find(t => t.textContent.includes('JSON'))
    if (t) t.click()
  })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/ui-note-json.png' })
  console.log('   saved /tmp/ui-note-json.png')

  console.log(`\n=== 错误: ${errors.length} ===`)
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
  process.exit(errors.length ? 1 : 0)
})()