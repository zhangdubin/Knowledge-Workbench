// 最终验证：删除 + AI + 预览 + 404
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

  const errors = []
  page.on('pageerror', err => errors.push(`PAGEERROR: ${err.message}`))
  page.on('console', async msg => {
    if (msg.type() === 'error') {
      try {
        const txt = await page.evaluate((a) => {
          try { return typeof a === 'string' ? a : a?.message || String(a) }
          catch { return null }
        }, msg.args()[0])
        if (!txt || /vis-data|hammerjs|deprecated/i.test(txt)) return
        errors.push(`CONSOLE: ${txt}`)
      } catch {}
    }
  })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400) {
      errors.push(`API ${r.status()} ${r.url()}`)
    }
  })

  // 1. 列表页删除完整流程
  console.log('=== 列表页删除完整流程 ===')
  await page.goto('http://127.0.0.1:8082/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  const before = await page.evaluate(() => document.querySelectorAll('.note-card').length)
  console.log('删除前:', before)

  await page.evaluate(() => {
    const card = document.querySelectorAll('.note-card')[0]
    const btn = card?.querySelector('.el-button--danger')
    if (btn) btn.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await new Promise(r => setTimeout(r, 1500))

  const hasBox = await page.evaluate(() => !!document.querySelector('.el-message-box'))
  console.log('确认弹窗出现:', hasBox)

  // 点确认
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-message-box .el-button')]
    const confirm = btns.find(b => b.textContent.includes('删除') && !b.textContent.includes('取消'))
    if (confirm) confirm.click()
  })
  await new Promise(r => setTimeout(r, 2500))

  const after = await page.evaluate(() => document.querySelectorAll('.note-card').length)
  console.log('删除后:', after, after < before ? '✅ 减少' : '❌ 没减少')

  // 2. AI 设置页
  console.log('\n=== AI 设置页 ===')
  await page.goto('http://127.0.0.1:8082/#/ai-settings', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))
  await page.screenshot({ path: '/tmp/v7-ai-settings.png' })

  // 3. NoteDetail AI 助手
  console.log('\n=== NoteDetail AI 助手 ===')
  await page.goto('http://127.0.0.1:8082/#/notes/14', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2500))
  // 点 AI 辅助按钮
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    const aiBtn = btns.find(b => b.textContent.includes('AI 辅助'))
    if (aiBtn) aiBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await new Promise(r => setTimeout(r, 1500))
  // 选择摘要
  const items = await page.evaluate(() => {
    const dropdown = [...document.querySelectorAll('.el-dropdown-menu .el-dropdown-item')]
    return dropdown.map(i => i.textContent.trim())
  })
  console.log('AI 菜单项:', items)
  if (items.length) {
    await page.evaluate(() => {
      const items = [...document.querySelectorAll('.el-dropdown-menu .el-dropdown-item')]
      const item = items.find(i => i.textContent.includes('摘要'))
      if (item) item.click()
    })
    await new Promise(r => setTimeout(r, 1500))
    await page.screenshot({ path: '/tmp/v7-ai-dialog.png' })
  }

  // 4. 404
  console.log('\n=== 404 ===')
  await page.goto('http://127.0.0.1:8082/#/no-such-page', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/v7-404.png' })
  const has404 = await page.evaluate(() => document.body.innerText.includes('404'))
  console.log('404 显示:', has404)

  console.log('\n=== 错误: ' + errors.length + ' ===')
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
})()