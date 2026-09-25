// v10 全量验证：所有路由零错误 + AI 降级链路 + 402 诊断
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const BASE = 'http://127.0.0.1:8082'
const ROUTES = [
  ['#/', '工作台'],
  ['#/apps', '应用中心'],
  ['#/notes', '知识库'],
  ['#/library', '数据中心'],
  ['#/types', '数据模型'],
  ['#/graph', '关联图谱'],
  ['#/knowledge/graph', '知识图谱'],
  ['#/search', '全局搜索'],
  ['#/ai-settings', 'AI 设置'],
  ['#/no-such-page', '404'],
]

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell', args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  const errors = []
  page.on('pageerror', e => errors.push(`[页面崩溃] ${e.message}`))
  page.on('console', async msg => {
    if (msg.type() !== 'error') return
    try {
      const t = await page.evaluate(a => {
        try { return typeof a === 'string' ? a : a?.message || String(a) } catch { return null }
      }, msg.args()[0])
      if (!t || /vis-data|hammerjs|deprecated|ResizeObserver/i.test(t)) return
      errors.push(`[控制台] ${t}`)
    } catch {}
  })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400) errors.push(`[接口 ${r.status()}] ${r.url()}`)
  })

  console.log('====== 1. 路由遍历 ======')
  for (const [hash, name] of ROUTES) {
    const before = errors.length
    await page.goto(BASE + '/' + hash, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1200))
    const info = await page.evaluate(() => {
      const el = document.querySelector('h1, .page-title, .pt-title')
      return { title: el?.textContent?.trim() || '', len: document.body.innerText.length }
    })
    const ok = errors.length === before && info.len > 120
    console.log(`${ok ? '✅' : '❌'} ${name.padEnd(8)} 标题="${info.title}" 内容长度=${info.len}`)
  }

  console.log('\n====== 2. AI 设置页 · 402 诊断 ======')
  await page.goto(BASE + '/#/ai-settings', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1500))
  // 触发"测试连接"
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('测试连接'))
    if (b) b.click()
  })
  await new Promise(r => setTimeout(r, 6000))
  const diag = await page.evaluate(() => {
    const alert = document.querySelector('.el-alert__title')
    const rows = [...document.querySelectorAll('.result-label')].map(r => r.textContent.trim())
    const tag = document.querySelector('.el-tag')
    return { alert: alert?.textContent?.trim() || '', rows, tag: tag?.textContent?.trim() || '' }
  })
  console.log('结果标签:', diag.tag)
  console.log('诊断标题:', diag.alert || '(无)')
  console.log('结果字段:', diag.rows.join(' / '))
  await page.screenshot({ path: '/tmp/v10-ai.png', fullPage: true })

  console.log('\n====== 3. 错误汇总 ======')
  if (!errors.length) console.log('✅ 零错误')
  else { console.log(`❌ 共 ${errors.length} 条：`); errors.forEach(e => console.log('   ', e)) }

  await browser.close()
  process.exit(errors.length ? 1 : 0)
})()
