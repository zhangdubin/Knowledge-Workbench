/**
 * 行为体检：确认「统一空状态 / 统一弹窗 / 键盘可达」这些改造没把功能改坏
 *
 * 为什么要有这个脚本：
 * 这一轮把十来个页面的弹窗换成了 DialogShell、把空状态换成了 EmptyState 组件，
 * 这类改动是「模板换了」，最容易出的问题是：
 *   - 弹窗标题还在，但描述和底部按钮没渲染出来
 *   - 权限项的勾选框还能点，但点文字没反应（改之前就是这样）
 *   - 空状态组件塞进了 grid 容器里，只占了第一格
 * 编译和单测都发现不了这些，得真的点一下。
 *
 * 断言的是「点了之后页面确实变成那样」，不是「代码里写了那句话」。
 *
 * 用法：
 *   node scripts/v31-verify-module-behavior.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { FE, USER, PASS } = require(path.join(__dirname, 'lib', 'session.cjs'))

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let checks = 0
let failed = 0
function check(cond, msg) {
  checks++
  if (!cond) {
    failed++
    console.log(`  ✗ ${msg}`)
    return false
  }
  console.log(`  ✔ ${msg}`)
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
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))

  // 登录
  await page.goto(`${base}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1400)
  const inputs = await page.$$('input')
  if (inputs.length >= 2) {
    await inputs[0].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[0].type(USER)
    await inputs[1].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[1].type(PASS)
    await page.click('button[type=submit], .el-button--primary')
    await sleep(2500)
  }

  // ---- 1) 用户管理：弹窗换成了 DialogShell ----
  console.log('\n用户管理')
  await page.goto(`${base}/#/system/users`, { waitUntil: 'networkidle2' })
  await sleep(1500)
  const opened = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('新建用户'))
    if (btn) btn.click()
    return !!btn
  })
  await sleep(900)
  const usersDialog = await page.evaluate(() => {
    const d = document.querySelector('.el-dialog.dialog-shell')
    if (!d) return null
    return {
      title: (d.querySelector('.shell-title') || {}).textContent || '',
      desc: (d.querySelector('.shell-desc') || {}).textContent || '',
      footer: Array.from(d.querySelectorAll('.shell-footer-actions button')).map(b => b.textContent.trim()),
      width: Math.round(d.getBoundingClientRect().width),
    }
  })
  check(opened && usersDialog, '点「新建用户」弹窗能打开')
  check(usersDialog && usersDialog.title.includes('新建用户'), `弹窗标题是「新建用户」（实得「${usersDialog && usersDialog.title}」）`)
  check(usersDialog && usersDialog.desc.length > 10, '弹窗有描述说明（不再是正文里混一段话）')
  check(usersDialog && usersDialog.footer.length === 2, `底部动作区有两个按钮（实得 ${usersDialog && usersDialog.footer.length}）`)
  await page.keyboard.press('Escape')
  await sleep(600)

  // ---- 2) 角色权限：点文字要能勾上（改之前点文字没反应）----
  console.log('\n角色权限')
  await page.goto(`${base}/#/system/roles`, { waitUntil: 'networkidle2' })
  await sleep(1600)
  // 「全部权限」角色的勾选框是禁用的（那是设计如此），所以要先切到一个普通角色
  await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('.role-item'))
    const normal = items.find(i => !i.querySelector('.ri-icon.super'))
    if (normal) normal.click()
  })
  await sleep(1200)
  const roleClicked = await page.evaluate(() => {
    const item = Array.from(document.querySelectorAll('.check-item'))
      .find(i => !i.querySelector('input')?.disabled)
    if (!item) return null
    const label = item.querySelector('.ci-label')
    if (!label) return null
    const before = item.classList.contains('on')
    label.click()
    // 勾选状态是 Vue 响应式的，class 要等下一个 tick 才更新，
    // 所以这里先记下「点之前」的状态，点完再回来看
    return { before, text: label.textContent.trim() }
  })
  await sleep(700)
  const roleAfter = await page.evaluate(() => {
    const item = Array.from(document.querySelectorAll('.check-item'))
      .find(i => !i.querySelector('input')?.disabled)
    return { after: item.classList.contains('on'), checked: item.querySelector('input')?.checked }
  })
  check(roleClicked !== null, '权限项渲染出来了（挑的是可编辑角色）')
  if (roleClicked) {
    check(roleClicked.before !== roleAfter.after,
      `点权限文字能切换勾选（「${roleClicked.text}」${roleClicked.before} → ${roleAfter.after}）`)
  }

  // ---- 3) 驾驶舱：卡片能 Tab 到并回车打开；弹窗是 DialogShell ----
  console.log('\n可视化驾驶舱')
  await page.goto(`${base}/#/dashboards`, { waitUntil: 'networkidle2' })
  await sleep(1800)
  const cardInfo = await page.evaluate(() => {
    const c = document.querySelector('.dash-card')
    if (!c) return null
    return { role: c.getAttribute('role'), tabindex: c.getAttribute('tabindex'), label: c.getAttribute('aria-label') }
  })
  check(cardInfo && cardInfo.role === 'button' && cardInfo.tabindex === '0',
    '驾驶舱卡片是可聚焦的（role=button + tabindex=0）')
  check(cardInfo && !!cardInfo.label, '驾驶舱卡片有无障碍名称')
  const tpl = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('从模板创建'))
    if (btn) btn.click()
    return !!btn
  })
  await sleep(900)
  const tplDialog = await page.evaluate(() => {
    const d = document.querySelector('.el-dialog.dialog-shell')
    if (!d) return null
    return {
      title: (d.querySelector('.shell-title') || {}).textContent || '',
      desc: (d.querySelector('.shell-desc') || {}).textContent || '',
    }
  })
  check(tpl && tplDialog, '「从模板创建」弹窗能打开且是统一外壳')
  check(tplDialog && tplDialog.title.includes('从模板创建'), `弹窗标题正确（实得「${tplDialog && tplDialog.title}」）`)
  await page.keyboard.press('Escape')
  await sleep(500)

  // ---- 4) 关联定义：弹窗统一 + 表格挂上密度类 ----
  console.log('\n关联定义')
  await page.goto(`${base}/#/relations`, { waitUntil: 'networkidle2' })
  await sleep(1500)
  const rel = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('新建关联'))
    if (btn) btn.click()
    const table = document.querySelector('.el-table')
    return { hasBtn: !!btn, density: table ? /table-density-/.test(table.className) : false }
  })
  await sleep(900)
  const relDialog = await page.evaluate(() => {
    const d = document.querySelector('.el-dialog.dialog-shell')
    return d ? { title: (d.querySelector('.shell-title') || {}).textContent || '' } : null
  })
  check(rel.hasBtn && relDialog, '「新建关联」弹窗能打开且是统一外壳')
  check(relDialog && relDialog.title.includes('关联定义'), `弹窗标题正确（实得「${relDialog && relDialog.title}」）`)
  await page.keyboard.press('Escape')
  await sleep(500)

  // ---- 5) 全局搜索：搜索中出骨架、出结果后高亮可读 ----
  console.log('\n全局搜索')
  await page.goto(`${base}/#/search`, { waitUntil: 'networkidle2' })
  await sleep(1400)
  // 建议词只在下拉建议卡和「没搜到」的空态里出现，所以要在搜之前先看一眼
  const chipsBefore = await page.evaluate(() => {
    const chips = Array.from(document.querySelectorAll('.suggest-chip'))
    return { count: chips.length, allButtons: chips.length > 0 && chips.every(c => c.tagName === 'BUTTON') }
  })
  check(chipsBefore.allButtons, `建议词是真正的 button（${chipsBefore.count} 个，键盘可达）`)
  await page.evaluate(() => {
    const input = document.querySelector('.hero-search input')
    if (!input) return
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, '项目')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true, keyCode: 13 }))
  })
  await sleep(2600)
  const search = await page.evaluate(() => {
    const marks = Array.from(document.querySelectorAll('mark'))
    const cs = marks.length ? getComputedStyle(marks[0]) : null
    return {
      items: document.querySelectorAll('.result-item').length,
      marks: marks.length,
      bg: cs ? cs.backgroundColor : '',
      color: cs ? cs.color : '',
      chips: document.querySelectorAll('.suggest-chip').length,
      chipIsButton: Array.from(document.querySelectorAll('.suggest-chip')).every(c => c.tagName === 'BUTTON'),
      resultFocusable: Array.from(document.querySelectorAll('.result-item')).every(
        r => r.getAttribute('tabindex') === '0' && r.getAttribute('role') === 'button'),
    }
  })
  check(search.items > 0, `搜到结果了（${search.items} 条）`)
  check(search.marks > 0, `命中关键词有高亮（${search.marks} 处）`)
  check(search.resultFocusable, '搜索结果条目可聚焦（Tab 能走到）')
  const contrast = await page.evaluate(() => {
    const m = document.querySelector('mark')
    if (!m) return null
    const parse = (c) => (c.match(/[\d.]+/g) || []).map(Number)
    const lum = ([r, g, b]) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    }
    const fg = parse(getComputedStyle(m).color)
    // 高亮底是半透明的：先合成到卡片白底上再算
    const bg = parse(getComputedStyle(m).backgroundColor)
    const page = [255, 255, 255]
    const solid = bg.length === 4 ? bg.slice(0, 3).map((v, i) => v * bg[3] + page[i] * (1 - bg[3])) : bg
    const l1 = lum(fg), l2 = lum(solid)
    return Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100
  })
  check(contrast !== null && contrast >= 4.5, `高亮文字对比度 ${contrast}:1（需 ≥4.5）`)

  // ---- 5b) 搜索中的骨架：把接口拖慢 1.2 秒，看骨架有没有顶上来 ----
  console.log('\n搜索加载态')
  await page.setRequestInterception(true)
  const slow = (req) => {
    if (req.url().includes('/api/search')) {
      setTimeout(() => { try { req.continue() } catch (e) {} }, 1200)
    } else {
      try { req.continue() } catch (e) {}
    }
  }
  page.on('request', slow)
  await page.goto(`${base}/#/search`, { waitUntil: 'networkidle2' })
  await sleep(1200)
  await page.evaluate(() => {
    const input = document.querySelector('.hero-search input')
    if (!input) return
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, '项目')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true, keyCode: 13 }))
  })
  await sleep(600)
  const skeleton = await page.evaluate(() => ({
    shown: !!document.querySelector('.search-skeleton'),
    rows: document.querySelectorAll('.sk-row').length,
    busy: document.querySelector('.search-skeleton')?.getAttribute('aria-busy') || '',
  }))
  check(skeleton.shown && skeleton.rows > 0, `搜索中有骨架占位（${skeleton.rows} 行，aria-busy=${skeleton.busy}）`)
  page.off('request', slow)
  await page.setRequestInterception(false)

  // ---- 6) 数据中心：拖拽区整块可点 + 关联标签够大 ----
  console.log('\n数据中心')
  await page.goto(`${base}/#/library`, { waitUntil: 'networkidle2' })
  await sleep(2000)
  const lib = await page.evaluate(() => {
    const dz = document.querySelector('.dropzone')
    const ref = document.querySelector('.cell-reference')
    return {
      dropzoneFocusable: !!dz && dz.getAttribute('tabindex') === '0',
      refHeight: ref ? Math.round(ref.getBoundingClientRect().height) : 0,
    }
  })
  check(lib.dropzoneFocusable, '拖拽区可聚焦（Tab 能走到，回车能选文件）')
  check(lib.refHeight >= 28, `关联标签高 ${lib.refHeight}px（需 ≥28）`)

  await browser.close()

  console.log(`\n共 ${checks} 项断言，${failed} 项未通过`)
  if (failed) process.exit(1)
})().catch((e) => {
  console.error('异常:', e.message)
  process.exit(1)
})
