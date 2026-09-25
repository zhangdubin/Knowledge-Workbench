// 验证删除修复 + AI 集成
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
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(`CONSOLE: ${msg.text()}`)
  })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400) {
      errors.push(`API ${r.status()} ${r.url()}`)
    }
  })

  // 1. 列表页删除
  console.log('=== 测试删除 ===')
  await page.goto('http://127.0.0.1:8082/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  const before = await page.evaluate(() => document.querySelectorAll('.note-card').length)
  console.log('删除前:', before)

  // 点第一个笔记的删除按钮
  await page.evaluate(() => {
    const card = document.querySelectorAll('.note-card')[0]
    const btn = card?.querySelector('.el-button--danger')
    if (btn) btn.click()
  })
  await new Promise(r => setTimeout(r, 1500))

  const dialogVisible = await page.evaluate(() => {
    const dlg = document.querySelector('.el-message-box')
    if (!dlg) return 'no dialog'
    return {
      visible: getComputedStyle(dlg).display !== 'none',
      text: dlg.querySelector('.el-message-box__content')?.textContent?.slice(0, 100),
      buttons: [...dlg.querySelectorAll('.el-button')].map(b => b.textContent.trim()),
    }
  })
  console.log('弹窗:', JSON.stringify(dialogVisible))

  if (typeof dialogVisible === 'object' && dialogVisible.buttons) {
    await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.el-message-box .el-button')]
      const confirm = btns.find(b => b.textContent.includes('删除') && !b.textContent.includes('取消'))
      if (confirm) confirm.click()
    })
    await new Promise(r => setTimeout(r, 2000))
  }

  const after = await page.evaluate(() => document.querySelectorAll('.note-card').length)
  console.log('删除后:', after, '(应该减少)')

  // 2. AI 设置页
  console.log('\n=== 测试 AI 设置页 ===')
  await page.goto('http://127.0.0.1:8082/#/ai-settings', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/v7-ai-settings.png' })

  // 3. AI 助手弹窗（NoteDetail）
  console.log('\n=== 测试 NoteDetail AI 助手 ===')
  await page.goto('http://127.0.0.1:8082/#/notes/14', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    const aiBtn = btns.find(b => b.textContent.includes('AI 辅助'))
    if (aiBtn) aiBtn.click()
  })
  await new Promise(r => setTimeout(r, 1500))
  // 选"生成摘要"
  const dropdownItems = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.el-dropdown-menu .el-dropdown-item')]
    return items.map(i => i.textContent.trim())
  })
  console.log('AI 下拉菜单:', dropdownItems)
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.el-dropdown-menu .el-dropdown-item')]
    const sumItem = items.find(i => i.textContent.includes('摘要'))
    if (sumItem) sumItem.click()
  })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/v7-ai-summarize.png' })

  // 4. 404 页
  console.log('\n=== 测试 404 ===')
  await page.goto('http://127.0.0.1:8082/#/nonexistent-page', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/v7-404.png' })

  console.log('\n=== 错误: ' + errors.length + ' ===')
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
})()