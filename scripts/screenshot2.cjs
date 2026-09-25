// 重新截图（JSON 试验场）
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
  await page.goto('http://127.0.0.1:8082/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 3000))
  // 打开 JSON 试验场
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('button')]
    const btn = buttons.find(b => b.textContent.includes('JSON 试验场'))
    if (btn) btn.click()
  })
  await new Promise(r => setTimeout(r, 2500))
  // 看 viewer 渲染内容
  const info = await page.evaluate(() => {
    const tree = document.querySelector('.json-viewer')
    if (!tree) return 'no .json-viewer'
    return {
      html: tree.innerHTML.slice(0, 1500),
      text: tree.innerText.slice(0, 500),
    }
  })
  console.log('=== viewer HTML ===')
  console.log(info.html || info)
  console.log('=== viewer TEXT ===')
  console.log(info.text || '')
  await page.screenshot({ path: '/tmp/kb-json-playground.png', fullPage: false })
  await browser.close()
})()