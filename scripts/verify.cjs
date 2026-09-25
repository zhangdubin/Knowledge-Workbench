// 用 puppeteer-core 验证前端 SPA
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')

const puppeteer = require_('puppeteer-core')

const ROUTES = [
  { path: '/#/apps', name: '应用中心' },
  { path: '/#/types', name: '数据模型' },
  { path: '/#/graph', name: '关联图谱' },
  { path: '/#/records/1', name: '项目管理 - 列表' },
  { path: '/#/records/3', name: '客户管理 - 列表' },
]

async function main() {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1400, height: 900 })

  const errors = []
  page.on('pageerror', err => errors.push(`pageerror: ${err.message}`))
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`)
  })
  page.on('response', resp => {
    if (resp.url().includes('/api/') && resp.status() >= 400) {
      errors.push(`API ${resp.status()} ${resp.url()}`)
    }
  })

  for (const r of ROUTES) {
    console.log(`\n→ ${r.name}: ${r.path}`)
    await page.goto(`http://127.0.0.1:8082${r.path}`, { waitUntil: 'networkidle0', timeout: 20000 })
    await new Promise(resolve => setTimeout(resolve, 1500))
    const title = await page.title()
    const text = await page.evaluate(() => document.body.innerText.slice(0, 200))
    console.log(`   title: ${title}`)
    console.log(`   preview: ${text.replace(/\n+/g, ' | ').slice(0, 200)}`)
  }

  console.log(`\n=== 错误汇总 (${errors.length}) ===`)
  errors.forEach(e => console.log(`  ❌ ${e}`))

  await browser.close()
  process.exit(errors.length ? 1 : 0)
}

main().catch(e => { console.error(e); process.exit(2) })