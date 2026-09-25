// 系统性问题盘点
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

  const ROUTES = [
    '/', '/#/apps', '/#/apps/project', '/#/types',
    '/#/types/1/edit', '/#/types/new',
    '/#/records/1', '/#/records/3', '/#/graph',
    '/#/knowledge/graph', '/#/search',
    '/#/notes', '/#/notes/14', '/#/library',
  ]

  const findings = []
  for (const path of ROUTES) {
    try {
      const resp = await page.goto(`http://127.0.0.1:8082${path}`, { waitUntil: 'networkidle0', timeout: 20000 })
      await new Promise(r => setTimeout(r, 1500))
      const info = await page.evaluate(() => {
        const issues = []
        // 1. 检测截断：长文本溢出容器
        const tables = document.querySelectorAll('.el-table')
        tables.forEach(t => {
          const overflow = t.scrollWidth > t.clientWidth + 10
          if (overflow) issues.push('表格横向溢出')
        })
        // 2. 检测空状态
        const empties = document.querySelectorAll('.empty')
        if (empties.length > 1) issues.push(`多个空状态 (${empties.length})`)
        // 3. 检测极小的卡片
        document.querySelectorAll('.card, .stat-card, .app-card').forEach(c => {
          if (c.clientHeight < 30 && c.clientWidth > 100) issues.push('卡片高度异常')
        })
        // 4. 检查暗色主题（documentElement 有无 dark class）
        const isDark = document.documentElement.classList.contains('dark')
        // 5. 检测 title
        const title = document.title
        const text = document.body.innerText
        return {
          title,
          isDark,
          textLen: text.length,
          issues,
          route: location.hash || location.pathname,
        }
      })
      console.log(`\n${path}  → ${info.title} (${info.textLen} chars)`)
      if (info.issues.length) {
        console.log(`   ⚠️  ${info.issues.join(', ')}`)
        findings.push({ path, issues: info.issues })
      }
      await page.screenshot({ path: `/tmp/audit-${path.replace(/[/#]/g, '_') || 'home'}.png` })
    } catch (e) {
      console.log(`${path} → FAIL: ${e.message}`)
    }
  }

  console.log('\n=== 总问题清单 ===')
  console.log(JSON.stringify(findings, null, 2))
  await browser.close()
})()