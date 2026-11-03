// ============================================================
// 全站页面冒烟：逐个路由打开，看有没有报错、有没有白屏
//
// 为什么要有这个：
//   Element Plus 从「整包注册」改成「按需引入」之后，
//   只要有一个组件漏了引入，那个位置就是空的 ——
//   页面不报错、控制台也不一定有提示（组件解析失败是 warning）。
//   main.js 里把 Vue 的 warning 升级成了 error，就是为了这个脚本能抓到。
//
// 用法：node scripts/kb-verify-pages.cjs
// ============================================================
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const fs = require('fs')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = 'http://127.0.0.1:8082/'
const TOKEN = fs.readFileSync('/tmp/kb-tok.txt', 'utf8').trim()

// 需要登录才能进的页面（hash 路由，直接拼在 # 后面）
const ROUTES = [
  ['/', '首页'],
  ['#/dna', 'DNA 图谱'],
  ['#/dna-library', '养料库'],
  ['#/notes', '笔记'],
  ['#/graph', '关联图谱'],
  ['#/knowledge/graph', '知识图谱'],
  ['#/records/1', '记录'],
  ['#/relations', '关联'],
  ['#/types', '实体类型'],
  ['#/types/new', '新建类型'],
  ['#/library', '资料库'],
  ['#/search', '搜索'],
  ['#/guide', '使用指南'],
  ['#/apps', '应用'],
  ['#/dashboards', '仪表盘'],
  ['#/ai-settings', 'AI 设置'],
  ['#/dev', '开发工作台'],
  ['#/dev/settings', '开发设置'],
  ['#/system/users', '用户'],
  ['#/system/roles', '角色'],
  ['#/system/nav', '导航'],
  ['#/system/audit', '审计'],
  ['#/system/recycle', '回收站'],
  ['#/system/settings', '系统设置'],
  ['#/system/storage', '存储'],
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000 })
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })

  let pass = 0
  let fail = 0
  const bad = []

  for (const [hash, name] of ROUTES) {
    const errs = []
    const onErr = (e) => errs.push(String(e.message || e).slice(0, 200))
    const onConsole = (m) => {
      if (m.type() === 'error') errs.push(m.text().slice(0, 200))
    }
    page.on('pageerror', onErr)
    page.on('console', onConsole)
    await page.goto(BASE + hash, { waitUntil: 'networkidle2', timeout: 45000 })
    await sleep(2600)
    const info = await page.evaluate(() => {
      const app = document.querySelector('#app')
      const txt = (document.body.innerText || '').trim()
      // 组件解析失败在 Vue 里是 warning，被 main.js 升级成了 console.error
      const unresolved = Array.from(document.querySelectorAll('*')).filter((el) =>
        el.tagName.startsWith('EL-') && !el.className && !el.getAttribute('class')
      ).length
      return {
        textLen: txt.length,
        appChildren: app ? app.children.length : 0,
        head: txt.replace(/\s+/g, ' ').slice(0, 60),
        unresolved,
      }
    })
    page.off('pageerror', onErr)
    page.off('console', onConsole)

    const problems = []
    if (errs.length) problems.push('报错: ' + errs.slice(0, 2).join(' | '))
    if (info.textLen < 40) problems.push('页面几乎是空的（' + info.textLen + ' 字）')
    if (info.appChildren === 0) problems.push('应用没渲染出来')
    if (problems.length) {
      fail++
      bad.push(name + '（' + hash + '）：' + problems.join('；'))
      console.log('  ✗ ' + name + '（' + hash + '）—— ' + problems.join('；'))
    } else {
      pass++
      console.log('  ✓ ' + name + '（' + hash + '）')
    }
  }

  await browser.close()
  console.log('\n共 ' + (pass + fail) + ' 项检查，失败 ' + fail + ' 项')
  if (fail) {
    console.log('失败项：')
    bad.forEach((b) => console.log('  - ' + b))
    process.exit(1)
  }
}

main().catch((e) => { console.error('ERR', e); process.exit(1) })