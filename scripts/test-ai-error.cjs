// 模拟用户测试错误连接
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

  // 模拟后端设置：用错误的 URL 和 API key
  // 直接调 PUT 接口
  await page.evaluate(async () => {
    await fetch('/api/ai/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'MiniMax_cn',
        base_url: 'https://api.minimax.cn/v1',
        api_key: 'sk-test-invalid',
        model: 'MiniMax-M2.5',
        enabled: true,
        temperature: 0.7,
        max_tokens: 1024,
        system_prompt: '',
      }),
    })
  })
  await new Promise(r => setTimeout(r, 1000))

  // 重新加载页面拿到最新配置
  await page.reload({ waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))

  // 点测试连接按钮
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    const testBtn = btns.find(b => b.textContent.includes('测试连接'))
    if (testBtn) testBtn.click()
  })
  await new Promise(r => setTimeout(r, 4000))
  await page.screenshot({ path: '/tmp/v8-test-error.png' })

  const result = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.card')]
    const errCard = cards.find(c => c.textContent.includes('测试结果'))
    return errCard?.innerText.slice(0, 800)
  })
  console.log('测试结果:\n', result)

  await browser.close()
})()