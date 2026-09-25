// 验证 MiniMax_cn 默认 base_url 是 .cn
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
  await page.goto('http://127.0.0.1:8082/#/ai-settings', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))

  // 选 MiniMax（中国）
  await page.evaluate(() => {
    const inputs = [...document.querySelectorAll('.el-select')]
    const providerSelect = inputs.find(s => s.textContent.includes('MiniMax'))
    if (providerSelect) providerSelect.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  })
  await new Promise(r => setTimeout(r, 800))
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    const item = items.find(i => i.textContent.includes('中国'))
    if (item) item.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await new Promise(r => setTimeout(r, 1000))

  // 看表单字段
  const fields = await page.evaluate(() => {
    const inputs = [...document.querySelectorAll('.el-input__inner, .el-select__placeholder, .el-select__selected-item, .el-textarea__inner')]
    return inputs.map(i => ({
      tag: i.tagName,
      value: i.value || i.textContent.trim().slice(0, 80),
    }))
  })
  console.log('字段:')
  fields.forEach(f => console.log(`  ${f.tag}: ${f.value}`))

  await page.screenshot({ path: '/tmp/v8-cn-fix.png' })
  await browser.close()
})()