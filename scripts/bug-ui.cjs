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

  // 测试 1: 列表页删除按钮
  console.log('=== 列表页删除按钮 ===')
  await page.goto('http://127.0.0.1:8082/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))

  const before = await page.evaluate(() => document.querySelectorAll('.note-card').length)
  console.log('删除前笔记数:', before)

  const deleteClicked = await page.evaluate(() => {
    const cards = document.querySelectorAll('.note-card')
    if (!cards.length) return 'no cards'
    const card = cards[0]
    const delBtn = card.querySelector('.el-button--danger')
    if (!delBtn) return 'no danger button'
    delBtn.click()
    return 'clicked'
  })
  console.log('点击删除按钮:', deleteClicked)
  await new Promise(r => setTimeout(r, 1500))
  await page.screenshot({ path: '/tmp/bug-after-delete-click.png' })

  const dialogVisible = await page.evaluate(() => {
    const dlg = document.querySelector('.el-message-box')
    if (!dlg) return 'no dialog'
    return {
      visible: getComputedStyle(dlg).display !== 'none',
      title: dlg.querySelector('.el-message-box__title')?.textContent,
      text: dlg.querySelector('.el-message-box__content')?.textContent?.slice(0, 200),
      buttons: [...dlg.querySelectorAll('.el-button')].map(b => b.textContent.trim()),
    }
  })
  console.log('弹窗状态:', JSON.stringify(dialogVisible))

  if (dialogVisible && dialogVisible.buttons) {
    await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.el-message-box .el-button')]
      const confirm = btns.find(b => b.textContent.includes('删除') && !b.textContent.includes('取消'))
      if (confirm) confirm.click()
    })
    await new Promise(r => setTimeout(r, 2500))
  }

  const after = await page.evaluate(() => document.querySelectorAll('.note-card').length)
  console.log('删除后笔记数:', after)

  // 测试 2: 附件预览按钮
  console.log('\n=== 附件预览按钮 ===')
  await page.goto('http://127.0.0.1:8082/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))

  const previewClicked = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-table button')]
    const previewBtn = btns.find(b => b.textContent.trim() === '预览')
    if (!previewBtn) return 'no preview button'
    previewBtn.click()
    return 'clicked preview'
  })
  console.log('点击预览按钮:', previewClicked)
  await new Promise(r => setTimeout(r, 2500))
  await page.screenshot({ path: '/tmp/bug-after-preview-click.png' })

  const previewDialog = await page.evaluate(() => {
    const dialogs = document.querySelectorAll('.el-dialog')
    const visible = [...dialogs].find(d => getComputedStyle(d).display !== 'none')
    if (!visible) return 'no visible dialog'
    return {
      title: visible.querySelector('.el-dialog__title')?.textContent,
      bodyText: visible.querySelector('.el-dialog__body')?.innerText.slice(0, 400),
      hasImage: !!visible.querySelector('img'),
      hasIframe: !!visible.querySelector('iframe'),
      hasTextarea: !!visible.querySelector('textarea'),
    }
  })
  console.log('预览对话框:', JSON.stringify(previewDialog))

  console.log('\n=== 错误: ' + errors.length + ' ===')
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
})()