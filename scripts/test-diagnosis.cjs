// 验证 1004 错误诊断显示
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

  // 设置无效的 MiniMax_cn 配置
  await page.evaluate(async () => {
    await fetch('/api/ai/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'MiniMax_cn',
        base_url: 'https://api.minimax.cn/v1',
        api_key: 'sk-invalid-key-12345',
        model: 'MiniMax-M2.7-highspeed',
        enabled: true,
      }),
    })
  })
  await page.reload({ waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))

  // 测试连接
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('测试连接'))
    if (btn) btn.click()
  })
  await new Promise(r => setTimeout(r, 4000))
  await page.screenshot({ path: '/tmp/v9-diagnosis.png' })

  // 看诊断提示
  const diag = await page.evaluate(() => {
    const alert = document.querySelector('.el-alert')
    return alert?.innerText
  })
  console.log('诊断提示:\n', diag)

  await browser.close()
})()