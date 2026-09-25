// 验证 UI 改进：菜单可读性 + 笔记删除 + 附件预览
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  const errors = []
  page.on('pageerror', err => errors.push(`PAGE ${err.message}`))
  page.on('console', async msg => {
    if (msg.type() === 'error') {
      try {
        const args = msg.args()
        if (!args.length) return
        const txt = await page.evaluate((a) => {
          try {
            if (typeof a === 'string') return a
            if (a?.message) return a.message
            if (a?.stack) return a.stack
            return String(a)
          } catch { return null }
        }, args[0])
        if (!txt || /vis-data|hammerjs|deprecated/i.test(txt)) return
        errors.push(`CON ${txt}`)
      } catch {}
    }
  })

  // 1. 笔记库列表（验证菜单 + 删除按钮）
  console.log('→ 笔记库列表')
  await page.goto('http://127.0.0.1:8082/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/ui2-notes.png' })

  // 2. 笔记详情（验证删除按钮）
  console.log('→ 笔记详情（含删除按钮）')
  await page.goto('http://127.0.0.1:8082/#/notes/14', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/ui2-note-detail.png' })

  // 3. 数据中心（验证附件预览）
  console.log('→ 数据中心（含预览按钮）')
  await page.goto('http://127.0.0.1:8082/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/ui2-library.png' })

  // 4. 上传一个测试文件 + 触发预览
  console.log('→ 测试文本预览')
  // 先在浏览器里 fetch 一个 API 直接创建一个 text 附件
  // 简化：通过 evaluate 调用 upload API
  const preview = await page.evaluate(async () => {
    // 上传一个文本文件
    const noteType = await fetch('/api/entity-types/by-key/note').then(r => r.json())
    const rec = await fetch('/api/records/type/' + noteType.id, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: { title: '_preview_test', content: 'preview', tags: ['_test'] } }),
    }).then(r => r.json())

    // 上传文件
    const fd = new FormData()
    fd.append('record_id', rec.id)
    fd.append('field_key', 'attachment')
    fd.append('file', new Blob(['Hello Preview\n这是预览测试内容\nLine 3\n中文测试'], { type: 'text/plain' }), 'preview-test.txt')
    const att = await fetch('/api/attachments/upload', { method: 'POST', body: fd }).then(r => r.json())
    return att.id
  })
  console.log('   uploaded attachment id:', preview)

  // 刷新 library 列表
  await page.reload({ waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 2000))

  // 点击预览按钮（最新附件的预览按钮）
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('button')]
    const previewBtn = buttons.find(b => b.textContent.trim() === '预览')
    if (previewBtn) previewBtn.click()
  })
  await new Promise(r => setTimeout(r, 2000))
  await page.screenshot({ path: '/tmp/ui2-preview-text.png' })
  console.log('   saved /tmp/ui2-preview-text.png')

  console.log(`\n=== 错误: ${errors.length} ===`)
  errors.forEach(e => console.log('  ❌', e))
  await browser.close()
  process.exit(errors.length ? 1 : 0)
})()