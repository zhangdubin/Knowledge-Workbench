/**
 * 路由渲染冒烟测试：每个页面都得真的渲染出来
 *
 * 为什么需要这个脚本：
 * v0.5.0 开发中出现过一次「编译通过、构建通过、单元测试全绿，
 * 但整页白屏」的事故 —— Apps.vue 用了 `watch` 却忘了从 vue 导入。
 * 编译器不管这个，vite 构建也不管，单测更管不到（单测测的是纯函数）。
 * 只有真的把页面在浏览器里打开一次，才会炸出来。
 *
 * 断言三件事：
 *   1) 页面有实质内容（不是只有侧边栏外壳）
 *   2) 没有 JS 运行时错误
 *   3) 有标题（说明组件树挂上了）
 *
 * 用法：
 *   node scripts/v29-verify-routes-render.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { FE, USER, PASS } = require(path.join(__dirname, 'lib', 'session.cjs'))

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 需要 id 的路由用占位符，运行时替换
const ROUTES = [
  ['工作台', '/'],
  ['可视化驾驶舱', '/dashboards'],
  ['应用中心', '/apps'],
  ['数据模型', '/types'],
  ['记录列表', '/records/1'],
  ['关联定义', '/relations'],
  ['关联图谱', '/graph'],
  ['全局搜索', '/search'],
  ['知识库', '/notes'],
  ['知识图谱', '/knowledge/graph'],
  ['数据中心', '/library'],
  ['用户管理', '/system/users'],
  ['角色权限', '/system/roles'],
  ['审计日志', '/system/audit'],
  ['回收站', '/system/recycle'],
  ['存储与备份', '/system/storage'],
  ['系统设置', '/system/settings'],
  ['AI 设置', '/ai-settings'],
  ['使用指南', '/guide'],
]

// 页面外壳（侧栏 + 顶栏）本身就有这些字，出现它们说明内容区是空的
const SHELL_ONLY = '知识工作台 KNOWLEDGE WORKBENCH 收起侧边栏 快速搜索'

let checks = 0
const check = (cond, msg) => {
  checks++
  if (!cond) {
    console.log(`  ✗ ${msg}`)
    return false
  }
  return true
}

;(async () => {
  const base = process.env.BASE || FE
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000 })

  // 登录
  await page.goto(`${base}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1200)
  const inputs = await page.$$('input')
  if (inputs.length >= 2) {
    await inputs[0].click({ clickCount: 3 })
    await page.keyboard.press('Backspace')
    await inputs[0].type(USER)
    await inputs[1].click({ clickCount: 3 })
    await page.keyboard.press('Backspace')
    await inputs[1].type(PASS)
    await page.click('button[type=submit], .el-button--primary')
    await sleep(2500)
  }

  let failed = 0
  const problems = []

  for (const [name, route] of ROUTES) {
    const errors = []
    // console.error 的第一个参数可能是 Error 对象，直接 String() 会变成 "[object Object]"，
    // 必须把它在页面里求值成字符串才能看到真正的报错。
    // 求值是异步的，所以先同步占位再回填 —— 否则断言可能在回填前就跑完了。
    const onErr = (m) => {
      if (m.type() !== 'error') return
      const idx = errors.length
      errors.push(m.text().slice(0, 200))
      Promise.all(
        m.args().map((a) =>
          a
            .evaluate((x) => (x && x.stack) ? String(x.stack).slice(0, 400) : String(x).slice(0, 400))
            .catch(() => m.text().slice(0, 200))
        )
      ).then((parts) => {
        errors[idx] = parts.join(' | ').slice(0, 500)
      })
    }
    const onPageErr = (e) => errors.push('PAGEERROR: ' + String(e.stack || e.message || e).slice(0, 500))
    page.on('console', onErr)
    page.on('pageerror', onPageErr)

    await page.goto(`${base}/#${route}`, { waitUntil: 'networkidle2' })
    await sleep(1700)
    // 等 console.error 的异步求值回填完，再做断言
    await sleep(250)

    const info = await page.evaluate(() => {
      const main = document.querySelector('.page, .el-main, main') || document.body
      const text = (main.innerText || '').replace(/\s+/g, ' ').trim()
      return {
        len: text.length,
        text: text.slice(0, 160),
        h: document.querySelectorAll('h1, h2, .page-title, .el-page-header__title').length,
        // 视图根节点上有 el-alert / empty-state 也算渲染成功
        hasBody: !!main.querySelector('.toolbar, .el-table, .el-card, .app-grid, .entity-grid, .empty-state, .el-alert, .stat-grid, form, .notes-toolbar, .el-tabs'),
      }
    })

    page.off('console', onErr)
    page.off('pageerror', onPageErr)

    const ok =
      check(info.len > 20, `${name} 页面内容过少（${info.len} 字）：${info.text}`) &&
      check(errors.length === 0, `${name} 有运行时错误：${errors[0]}`) &&
      check(info.h > 0 || info.hasBody, `${name} 没有标题也没有主体结构`) &&
      check(info.len > 120 || !info.text.includes(SHELL_ONLY), `${name} 只渲染出了外壳`)

    if (ok) {
      console.log(`✔ ${name.padEnd(8)} 渲染正常（${info.len} 字）`)
    } else {
      failed++
      problems.push({ name, route, info, errors })
      console.log(`✘ ${name.padEnd(8)} ${route}`)
    }
  }

  await browser.close()

  console.log(`\n共检查 ${ROUTES.length} 个路由，${failed} 个有问题`)
  if (failed) {
    console.log('\n明细（JSON）：')
    console.log(JSON.stringify(problems, null, 2))
    process.exit(1)
  }
})().catch((e) => {
  console.error('异常:', e.message)
  process.exit(1)
})
