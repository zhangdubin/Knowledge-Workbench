// 截图所有关键页面
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
  await page.setViewport({ width: 1400, height: 900 })

  const SHOTS = [
    { path: '/', name: '01-dashboard' },
    { path: '/#/notes', name: '02-notes-list' },
    { path: '/#/notes/14', name: '03-note-detail' },
    { path: '/#/knowledge/graph', name: '04-knowledge-graph' },
    { path: '/#/apps', name: '05-apps-with-create' },
  ]
  for (const s of SHOTS) {
    await page.goto(`http://127.0.0.1:8082${s.path}`, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 2500))
    await page.screenshot({ path: `/tmp/kb-${s.name}.png` })
    console.log(`saved /tmp/kb-${s.name}.png`)
  }
  await browser.close()
})()