const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const PAGES = [
  ['', 'dashboard'], ['apps', 'apps'], ['notes', 'notes'], ['library', 'library'],
  ['types', 'types'], ['graph', 'graph'], ['knowledge/graph', 'kgraph'],
  ['search', 'search'], ['ai-settings', 'ai'],
]
;(async () => {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell', args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 950, deviceScaleFactor: 2 })
  for (const [path, name] of PAGES) {
    await p.goto('http://127.0.0.1:8082/#' + path, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1800))
    await p.screenshot({ path: `/tmp/shots/${name}.png` })
    console.log('shot', name)
  }
  await b.close()
})()
