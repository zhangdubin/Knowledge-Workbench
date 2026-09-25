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

  page.on('requestfailed', req => console.log('REQ FAILED:', req.url(), req.failure()?.errorText))

  await page.goto('http://127.0.0.1:8082/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))

  // 直接在浏览器里 fetch 附件
  const result = await page.evaluate(async () => {
    // 找一个附件 URL
    const links = [...document.querySelectorAll('.el-table a.filename')]
    const url = links[0]?.href
    if (!url) return { error: 'no link found' }
    try {
      const resp = await fetch(url)
      const text = await resp.text()
      return {
        status: resp.status,
        ok: resp.ok,
        url,
        length: text.length,
        preview: text.slice(0, 200),
      }
    } catch (e) {
      return { error: e.message, url }
    }
  })
  console.log('附件 fetch 测试:', JSON.stringify(result, null, 2))

  // 点击预览按钮
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-table button')]
    const previewBtn = btns.find(b => b.textContent.trim() === '预览')
    if (previewBtn) previewBtn.click()
  })
  await new Promise(r => setTimeout(r, 2500))

  const dialogContent = await page.evaluate(() => {
    const dialogs = [...document.querySelectorAll('.el-dialog')]
    const visible = dialogs.find(d => getComputedStyle(d).display !== 'none')
    if (!visible) return null
    const ta = visible.querySelector('textarea')
    return {
      title: visible.querySelector('.el-dialog__title')?.textContent,
      textareaValue: ta?.value?.slice(0, 200),
      textareaLen: ta?.value?.length,
      loading: !!visible.querySelector('.el-loading-mask'),
    }
  })
  console.log('预览对话框内容:', JSON.stringify(dialogContent, null, 2))

  await page.screenshot({ path: '/tmp/preview-debug.png' })
  await browser.close()
})()