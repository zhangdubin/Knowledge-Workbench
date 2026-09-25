// 验证：取消自动补全、404 智能提示
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
  await new Promise(r => setTimeout(r, 2000))

  // 设用户的"不带 /chat/completions"的配置
  await page.evaluate(async () => {
    await fetch('/api/ai/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'MiniMax_cn',
        base_url: 'https://api.minimax.cn/v1',  // 不带 /chat/completions
        api_key: 'sk-test',
        model: 'MiniMax-M2.7-highspeed',
        enabled: true,
      }),
    })
  })
  await page.reload({ waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))

  // 看 base_url 字段值
  const url = await page.evaluate(() => {
    const input = [...document.querySelectorAll('.el-input__inner')]
      .find(i => i.value && i.value.includes('minimax'))
    return input?.value
  })
  console.log('页面显示的 base_url:', url)
  console.log('（应该是 https://api.minimax.cn/v1，不被自动补全）')

  await browser.close()
})()