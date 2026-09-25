// 验证笔记相关新页面
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const ROUTES = [
  { path: '/#/notes', name: '知识库列表' },
  { path: '/#/notes/14', name: '笔记详情（知识工作台设计）' },
  { path: '/#/knowledge/graph', name: '知识图谱' },
  { path: '/#/apps', name: '应用中心（含新建按钮）' },
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
    try {
      await page.goto(`http://127.0.0.1:8082${r.path}`, { waitUntil: 'networkidle0', timeout: 25000 })
      await new Promise(resolve => setTimeout(resolve, 2500))
      const title = await page.title()
      const text = await page.evaluate(() => document.body.innerText.slice(0, 300))
      console.log(`   title: ${title}`)
      console.log(`   preview: ${text.replace(/\n+/g, ' | ').slice(0, 250)}`)
    } catch (e) {
      console.log(`   ❌ ${e.message}`)
      errors.push(e.message)
    }
  }

  // 截图笔记详情页
  console.log('\n→ 截图笔记详情...')
  await page.goto('http://127.0.0.1:8082/#/notes/14', { waitUntil: 'networkidle0' })
  await new Promise(resolve => setTimeout(resolve, 2000))
  await page.screenshot({ path: '/tmp/note-detail.png', fullPage: false })
  console.log('   saved /tmp/note-detail.png')

  // 截图知识图谱
  console.log('\n→ 截图知识图谱...')
  await page.goto('http://127.0.0.1:8082/#/knowledge/graph', { waitUntil: 'networkidle0' })
  await new Promise(resolve => setTimeout(resolve, 3000))
  await page.screenshot({ path: '/tmp/knowledge-graph.png', fullPage: false })
  console.log('   saved /tmp/knowledge-graph.png')

  console.log(`\n=== 错误汇总 (${errors.length}) ===`)
  errors.forEach(e => console.log(`  ❌ ${e}`))

  await browser.close()
  process.exit(errors.length ? 1 : 0)
}

main().catch(e => { console.error(e); process.exit(2) })