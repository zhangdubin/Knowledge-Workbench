// 验证：1) 旧配置升级 2) 完整 endpoint 直接 POST
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

  // 模拟用户的旧配置（不带 /chat/completions）
  await page.goto('http://127.0.0.1:8082/#/ai-settings', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.evaluate(async () => {
    await fetch('/api/ai/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'MiniMax_cn',
        base_url: 'https://api.minimax.cn/v1',  // 旧配置：没有 /chat/completions
        api_key: 'sk-invalid',
        model: 'MiniMax-M2.7-highspeed',
        enabled: true,
      }),
    })
  })

  // 重新加载页面，看是否自动补全
  await page.reload({ waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))

  const baseUrl = await page.evaluate(() => {
    const inputs = [...document.querySelectorAll('.el-input__inner')]
    const urlInput = inputs.find(i => i.value && i.value.includes('minimax'))
    return urlInput?.value
  })
  console.log('页面加载后的 base_url:', baseUrl)

  // 触发测试连接，看请求的实际 URL
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('测试连接'))
    if (btn) btn.click()
  })
  await new Promise(r => setTimeout(r, 3000))

  // 抓取测试结果中的 URL
  const testUrl = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.result-row')]
    const urlRow = rows.find(r => r.textContent.includes('请求 URL'))
    return urlRow?.innerText
  })
  console.log('测试请求 URL:', testUrl)

  await page.screenshot({ path: '/tmp/v10-no-autopath.png' })
  await browser.close()
})()