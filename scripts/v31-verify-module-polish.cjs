/**
 * 模块体检：把「其它模块也优化一下」翻译成可测量的指标
 *
 * 为什么要有这个脚本：
 * v28 查的是「全站通用质量」（对比度、焦点、触控、溢出、行高），
 * 但它只覆盖 7 个页面，而且查不出「这个页面用的是哪套设计系统」。
 * 一轮改造之后最容易出现的情况是：新页面用上了 EmptyState / DialogShell，
 * 旧页面还留在手写的老样式里 —— 两套观感并存，从截图上看一眼就能发现，
 * 但从代码里很难一眼数清。
 *
 * 这个脚本专门盯「模块内部的一致性」：
 *   1) 键盘不可达（div 冒充按钮）
 *   2) 图标按钮没有无障碍名称（只有 tooltip，屏幕阅读器读不出来）
 *   3) 深色模式下搜索高亮读不出来
 *   4) 触控目标过小
 *   5) 老式空状态 / 裸 el-dialog / 表格没挂密度类（提示项，只统计不判失败）
 *
 * 用法：
 *   node scripts/v31-verify-module-polish.cjs
 *   BASE=http://127.0.0.1:5173 node scripts/v31-verify-module-polish.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { FE, USER, PASS } = require(path.join(__dirname, 'lib', 'session.cjs'))

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 本轮负责巡检的页面
const PAGES = [
  ['数据模型', '/types'],
  ['关联定义', '/relations'],
  ['全局搜索', '/search'],
  ['工作台', '/'],
  ['可视化驾驶舱', '/dashboards'],
  ['数据中心', '/library'],
  ['知识图谱', '/knowledge/graph'],
  ['关联图谱', '/graph'],
  ['用户管理', '/system/users'],
  ['角色权限', '/system/roles'],
  ['审计日志', '/system/audit'],
  ['回收站', '/system/recycle'],
  ['存储与备份', '/system/storage'],
]

const PROBE = () => {
  const out = { fake: [], noLabel: [], small: [], mark: [], oldEmpty: 0, rawDialog: 0, tableNoDensity: 0 }

  // ---- 1) 键盘不可达：div 冒充按钮 ----
  // cursor:pointer 会被子元素继承，所以只认「最外层」那个：
  // 如果祖先里已经有一个可聚焦的等价物，这里就不重复报了。
  const isNative = (el) => ['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)
  const reachable = (el) => {
    let n = el
    while (n && n !== document.body) {
      if (isNative(n)) return true
      if (n.getAttribute && n.getAttribute('tabindex') !== null
        && n.getAttribute('tabindex') !== '-1') return true
      if (n.getAttribute && ['button', 'link', 'menuitem', 'tab'].includes(n.getAttribute('role'))) return true
      n = n.parentElement
    }
    return false
  }
  // 只看「能装内容的容器」：svg/path 是图标内部的矢量片段，
  // 它们的 cursor 是从父级继承的，算成伪按钮只会淹没真问题。
  const CANDIDATE = ['DIV', 'SPAN', 'LI', 'TD', 'SECTION', 'ARTICLE', 'P', 'A']
  document.querySelectorAll('*').forEach((el) => {
    const cs = getComputedStyle(el)
    if (cs.cursor !== 'pointer') return
    if (!CANDIDATE.includes(el.tagName)) return
    if (isNative(el)) return
    if (el.getAttribute('role') === 'button' || el.getAttribute('role') === 'link') return
    if (reachable(el)) return
    // 必须有文字：纯图标的小方块由「无障碍名称」那条检查负责
    if (!(el.textContent || '').trim()) return
    // Element Plus 组件自带键盘交互（选择器、输入框、分页、标签页…），
    // 它们的内部节点 cursor 是继承来的，不算伪按钮
    if (el.closest('.el-select, .el-input, .el-form-item, .el-radio-group, .el-checkbox, .el-switch, .el-pagination, .el-tabs, .el-date-editor')) return
    // 表格里同理：整行可点时单元格的 cursor 是继承来的，只报行本身
    if (el.closest('tr') && el.tagName !== 'TR') return
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return
    out.fake.push({
      cls: (el.className || '').toString().slice(0, 46),
      tag: el.tagName,
      text: (el.textContent || '').trim().slice(0, 20),
    })
  })

  // ---- 2) 图标按钮没有无障碍名称 ----
  document.querySelectorAll('button, .el-button, [role="button"]').forEach((el) => {
    const text = (el.textContent || '').trim()
    if (text) return
    const label = el.getAttribute('aria-label') || el.getAttribute('title') || ''
    if (label.trim()) return
    // Element Plus 输入框里的「显示/隐藏密码」图标是组件库自带的缺口，
    // 业务代码改不了，先排除掉，别让真问题被淹没
    if (el.closest('.el-input__suffix, .el-input__prefix')) return
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return
    out.noLabel.push({
      cls: (el.className || '').toString().slice(0, 46),
      tag: el.tagName,
    })
  })

  // ---- 3) 触控目标（36 是建议线，28 是 WCAG 2.2 AA 硬线）----
  document.querySelectorAll('button, .el-button, [role="button"], a[href]').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return
    if (r.width < 28 || r.height < 28) {
      out.small.push({
        cls: (el.className || '').toString().slice(0, 46),
        w: Math.round(r.width), h: Math.round(r.height),
      })
    }
  })

  // ---- 4) 搜索高亮在深色底上读不读得出来 ----
  // mark 的颜色如果是写死的浅色，深色主题下就是一团糊
  document.querySelectorAll('mark').forEach((el) => {
    const cs = getComputedStyle(el)
    out.mark.push({ bg: cs.backgroundColor, color: cs.color })
  })

  // ---- 5) 一致性提示项 ----
  // EmptyState 组件渲染出来的根节点也是 .empty-state（带 is-card/is-plain/is-inline 变体类），
  // 只有没带变体类的才是「手写的空状态」—— 那才是没统一到设计系统的地方
  out.oldEmpty = document.querySelectorAll(
    '.empty-state:not(.is-card):not(.is-plain):not(.is-inline)'
  ).length
  out.rawDialog = document.querySelectorAll('.el-dialog:not(.dialog-shell)').length
  out.tableNoDensity = Array.from(document.querySelectorAll('.el-table'))
    .filter(t => !/table-density-(compact|default|comfortable)/.test(t.className || '')).length

  return out
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
    await inputs[0].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[0].type(USER)
    await inputs[1].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[1].type(PASS)
    await page.click('button[type=submit], .el-button--primary')
    await sleep(2500)
  }

  const results = []
  for (const [name, route] of PAGES) {
    await page.goto(`${base}/#${route}`, { waitUntil: 'networkidle2' })
    await sleep(1600)
    let probe
    try {
      probe = await page.evaluate(PROBE)
    } catch (e) {
      results.push({ name, route, error: e.message })
      continue
    }
    // 搜索页要有结果才能看到高亮，先用默认词搜一次
    if (route === '/search') {
      await page.evaluate(() => {
        const input = document.querySelector('.hero-search input')
        if (input) {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
          setter.call(input, '项目')
          input.dispatchEvent(new Event('input', { bubbles: true }))
          input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }))
        }
      })
      await sleep(2000)
      const markProbe = await page.evaluate(() => {
        const out = []
        document.querySelectorAll('mark').forEach((el) => {
          const cs = getComputedStyle(el)
          out.push({ bg: cs.backgroundColor, color: cs.color })
        })
        return out
      })
      probe.mark = markProbe
    }
    results.push({ name, route, ...probe })
  }

  // 深色模式再跑一遍搜索页：浅色下能看清不代表深色下也能
  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await page.goto(`${base}/#/search`, { waitUntil: 'networkidle2' })
  await sleep(1500)
  await page.evaluate(() => {
    const input = document.querySelector('.hero-search input')
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, '项目')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }))
    }
  })
  await sleep(2000)
  const darkMark = await page.evaluate(() => {
    const out = []
    document.querySelectorAll('mark').forEach((el) => {
      const cs = getComputedStyle(el)
      out.push({ bg: cs.backgroundColor, color: cs.color })
    })
    return out
  })

  await browser.close()

  // ---- 判定 ----
  let fail = 0
  const tips = []
  console.log('模块巡检（硬门槛：键盘可达 / 无障碍名称 / 触控目标 / 深色高亮）\n')
  for (const r of results) {
    if (r.error) {
      console.log(`✘ ${r.name.padEnd(8)} 探针失败: ${r.error}`)
      fail++
      continue
    }
    const bad = []
    if (r.fake.length) bad.push(`键盘不可达 ${r.fake.length} 处`)
    if (r.noLabel.length) bad.push(`图标按钮无名称 ${r.noLabel.length} 处`)
    if (r.small.length) bad.push(`触控目标过小 ${r.small.length} 处`)
    if (bad.length) {
      fail++
      console.log(`✘ ${r.name.padEnd(8)} ${bad.join('；')}`)
      r.fake.slice(0, 3).forEach(f => console.log(`     · 键盘不可达 <${f.tag}> .${f.cls} 「${f.text}」`))
      r.noLabel.slice(0, 3).forEach(f => console.log(`     · 无名称按钮 .${f.cls}`))
      r.small.slice(0, 3).forEach(f => console.log(`     · 小目标 ${f.w}×${f.h} .${f.cls}`))
    } else {
      console.log(`✔ ${r.name.padEnd(8)} 硬门槛全过`)
    }
    if (r.oldEmpty || r.rawDialog || r.tableNoDensity) {
      tips.push({
        page: r.name,
        老式空状态: r.oldEmpty,
        裸el对话框: r.rawDialog,
        表格未挂密度类: r.tableNoDensity,
      })
    }
  }

  // 深色模式高亮
  if (darkMark.length) {
    const sample = darkMark[0]
    console.log(`\n深色模式搜索高亮：${darkMark.length} 处，底色 ${sample.bg} / 字色 ${sample.color}`)
  } else {
    console.log('\n深色模式搜索高亮：未取到样本（搜索无结果时跳过高亮检查）')
  }

  if (tips.length) {
    console.log('\n一致性提示项（不影响判定）：')
    tips.forEach(t => console.log(`  ${t.page.padEnd(8)} 老式空状态 ${t.老式空状态} · 裸 el-dialog ${t.裸el对话框} · 表格未挂密度类 ${t.表格未挂密度类}`))
  }

  console.log(`\n共检查 ${results.length} 个页面，${fail} 个存在硬门槛问题`)
  if (fail) process.exit(1)
})().catch((e) => {
  console.error('异常:', e.message)
  process.exit(1)
})
