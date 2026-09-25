const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')

const PAGES = [
  ['', '01-dashboard'],
  ['notes', '02-notes'],
  ['library', '03-library'],
  ['apps', '04-apps'],
  ['types', '05-types'],
  ['relations', '06-relations'],
  ['graph', '07-graph'],
  ['knowledge/graph', '08-kgraph'],
  ['search', '09-search'],
  ['guide', '10-guide'],
  ['ai-settings', '11-ai'],
]

const OUT = '/Volumes/Samsung/poc/知识库/kb-workbench/docs/screenshots/v13'
fs.mkdirSync(OUT, { recursive: true })

;(async () => {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 950, deviceScaleFactor: 2 })

  const errs = []
  p.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  p.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  p.on('response', r => {
    const s = r.status()
    if (s >= 400) errs.push(`[http ${s}] ${r.url()}`)
  })

  for (const mode of ['light', 'dark']) {
    for (const [path, name] of PAGES) {
      await p.goto('http://127.0.0.1:8082/#' + path, { waitUntil: 'networkidle0' })
      await p.evaluate(m => {
        document.documentElement.classList.toggle('dark', m === 'dark')
      }, mode)
      await new Promise(r => setTimeout(r, 1600))
      await p.screenshot({ path: `${OUT}/${name}-${mode}.png` })
    }
    console.log('done', mode)
  }

  // 侧边栏专项：确认无数字徽标
  await p.goto('http://127.0.0.1:8082/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1200))
  const badges = await p.$$eval('.nav-badge', els => els.length)
  console.log('nav-badge count =', badges)

  await b.close()
  console.log('--- errors ---')
  console.log(errs.length ? [...new Set(errs)].join('\n') : 'none')
})()
