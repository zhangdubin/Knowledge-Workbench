const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell', args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  const shots = [
    ['', 'home'],
    ['/#/apps', 'apps'],
    ['/#/types', 'types'],
    ['/#/notes', 'notes'],
    ['/#/apps/project', 'app-detail'],
  ]
  for (const [path, name] of shots) {
    await page.goto('http://127.0.0.1:8082' + path, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 2000))
    await page.screenshot({ path: '/tmp/v6-' + name + '.png' })
    console.log(name, 'done')
  }
  await browser.close()
})()