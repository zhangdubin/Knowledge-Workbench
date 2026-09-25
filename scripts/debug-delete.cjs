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

  page.on('pageerror', err => console.log('PAGEERROR:', err.message))
  page.on('console', msg => console.log(`[${msg.type()}]`, msg.text()))

  await page.goto('http://127.0.0.1:8082/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 3000))

  // 触发原生 click 事件
  const result = await page.evaluate(() => {
    const card = document.querySelectorAll('.note-card')[0]
    const btn = card?.querySelector('.el-button--danger')
    if (!btn) return 'no btn'
    // 检查 button 是不是被禁用
    return {
      btnText: btn.textContent.trim(),
      isDisabled: btn.disabled || btn.classList.contains('is-disabled'),
      btnHTML: btn.outerHTML.slice(0, 300),
    }
  })
  console.log('按钮信息:', JSON.stringify(result, null, 2))

  // 触发 click
  await page.evaluate(() => {
    const card = document.querySelectorAll('.note-card')[0]
    const btn = card?.querySelector('.el-button--danger')
    if (btn) {
      // 触发原生 click
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    }
  })
  await new Promise(r => setTimeout(r, 2000))

  // 看是否有 message-box 出现（包括挂载到 body 的）
  const dialog = await page.evaluate(() => {
    return {
      bodyChildren: [...document.body.children].map(c => c.className || c.tagName).filter(c => c.includes('message') || c.includes('overlay')),
      hasMessageBox: !!document.querySelector('.el-message-box'),
      bodyHasOverlay: !!document.querySelector('.el-overlay'),
    }
  })
  console.log('弹窗查询:', JSON.stringify(dialog, null, 2))

  await page.screenshot({ path: '/tmp/debug-delete.png' })

  await browser.close()
})()