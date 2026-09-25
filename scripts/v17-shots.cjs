/**
 * v17 截图：这一轮新增/重做的界面，明暗两套主题各抓一遍
 *
 *   1. 登录页（安全管理的入口）
 *   2. 关联定义列表 + 新建对话框（两端可选「数据中心文件」）
 *   3. 关联图谱：全局总览 / 节点详情抽屉
 *   4. 知识图谱：按标签着色
 *   5. 可视化驾驶舱：列表 / 渲染态 / 编辑态 + 配置抽屉
 *   6. 系统管理：用户 / 角色权限矩阵 / 审计日志
 *
 * 顺带断言控制台与接口没有异常。
 *   node scripts/v17-shots.cjs
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')
const S = require('./lib/session.cjs')

const OUT = '/Volumes/Samsung/poc/知识库/kb-workbench/docs/screenshots/v17'
fs.mkdirSync(OUT, { recursive: true })

const errs = []
let shot = 0

async function snap(p, name, mode) {
  shot += 1
  const file = `${OUT}/${String(shot).padStart(2, '0')}-${name}-${mode}.png`
  await p.screenshot({ path: file })
  console.log(`  📸 ${file.replace(OUT + '/', '')}`)
}

async function setTheme(p, mode) {
  await p.evaluate(m => document.documentElement.classList.toggle('dark', m === 'dark'), mode)
  await S.sleep(450)
}

/** 带 ?__e2e=1 进图谱页：需要 network 实例才能算出节点坐标，点开详情抽屉 */
async function openGraphNode(p) {
  const pos = await p.evaluate(() => {
    const net = window.__kbGraph
    if (!net) return null
    const ids = net.body?.data?.nodes?.getIds?.() || net.body?.nodes?.getIds?.() || []
    for (const id of ids) {
      const pt = net.getPositions([id])[id]
      if (!pt) continue
      const dom = net.canvasToDOM(pt)
      return { x: Math.round(dom.x), y: Math.round(dom.y) }
    }
    return null
  })
  if (!pos) return false
  const box = await p.$eval('.gc-canvas', e => {
    const r = e.getBoundingClientRect()
    return { x: r.x, y: r.y }
  })
  await p.mouse.click(box.x + pos.x, box.y + pos.y)
  return !!(await S.waitFor(p, () => !!document.querySelector('.gc-drawer .gi'), 6000))
}

;(async () => {
  await S.login()   // 后端要登录，顺手把 cookie 也带进浏览器

  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 980, deviceScaleFactor: 2 })

  p.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  p.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  p.on('response', r => {
    if (r.status() >= 400 && r.url().includes('/api/')) errs.push(`[http ${r.status()}] ${r.url()}`)
  })

  // 借一个驾驶舱来截图；没有就现建一个，拍完删掉
  const list = await S.j('/api/dashboards')
  let dashId = (list.body.items || [])[0]?.id
  let tempDash = null
  if (!dashId) {
    const mk = await S.post('/api/dashboards/templates', { template_key: 'overview', name: '截图用驾驶舱' })
    dashId = mk.body.id
    tempDash = dashId
  }

  // ---------- 1) 登录页（此时还没登录，正好抓真实状态） ----------
  for (const mode of ['light', 'dark']) {
    await p.goto(`${S.FE}/#/login`, { waitUntil: 'networkidle2' })
    await p.evaluate(() => { localStorage.getItem('kb-theme') })
    await setTheme(p, mode)
    await S.sleep(900)
    await snap(p, 'login', mode)
  }

  const ok = await S.loginPage(p)
  if (!ok) console.log('  （登录未通过，后续页面可能停在登录页）')

  for (const mode of ['light', 'dark']) {
    // ---------- 2) 关联定义 ----------
    await p.goto(`${S.FE}/#/relations`, { waitUntil: 'domcontentloaded' })
    await p.reload({ waitUntil: 'networkidle2' })
    await setTheme(p, mode)
    await S.sleep(900)
    await snap(p, 'relations-list', mode)

    const opened = await p.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(x => x.innerText.includes('新建关联'))
      if (!btn) return false
      btn.click()
      return true
    })
    if (opened) {
      await p.waitForSelector('.el-dialog', { visible: true, timeout: 8000 }).catch(() => {})
      // 目标端切到「数据中心文件」，把「可定义文件端」这件事直接拍出来
      await p.evaluate(() => {
        const groups = [...document.querySelectorAll('.end-picker .el-radio-group')]
        const g = groups[1]
        if (!g) return
        const fileBtn = [...g.querySelectorAll('.el-radio-button')]
          .find(x => x.innerText.includes('数据中心文件'))
        fileBtn && fileBtn.click()
      })
      await S.sleep(600)
      await snap(p, 'relations-dialog-file-end', mode)
      await p.evaluate(() => {
        const btn = [...document.querySelectorAll('.el-dialog button')].find(x => x.innerText.includes('取消'))
        btn && btn.click()
      })
      await S.sleep(600)
    }

    // ---------- 3) 关联图谱 ----------
    await p.goto(`${S.FE}/#/graph?__e2e=1`, { waitUntil: 'domcontentloaded' })
    await p.reload({ waitUntil: 'networkidle2' })
    await setTheme(p, mode)
    await S.sleep(2600)          // 等物理布局稳定
    await snap(p, 'graph-global', mode)

    if (await openGraphNode(p)) {
      await S.sleep(700)
      await snap(p, 'graph-inspector', mode)
      await p.keyboard.press('Escape')
      await S.sleep(600)
    } else {
      console.log('  （没能点中节点，跳过抽屉截图）')
    }

    // ---------- 4) 知识图谱 ----------
    await p.goto(`${S.FE}/#/knowledge/graph`, { waitUntil: 'domcontentloaded' })
    await p.reload({ waitUntil: 'networkidle2' })
    await setTheme(p, mode)
    await S.sleep(2600)
    await snap(p, 'knowledge-graph', mode)

    // ---------- 5) 驾驶舱 ----------
    await p.goto(`${S.FE}/#/dashboards`, { waitUntil: 'domcontentloaded' })
    await p.reload({ waitUntil: 'networkidle2' })
    await setTheme(p, mode)
    await S.sleep(1100)
    await snap(p, 'cockpit-list', mode)

    await p.goto(`${S.FE}/#/dashboards/${dashId}`, { waitUntil: 'domcontentloaded' })
    await p.reload({ waitUntil: 'networkidle2' })
    await setTheme(p, mode)
    await S.sleep(2200)          // 等图表画完
    await snap(p, 'cockpit-view', mode)

    // 编辑态 + 配置抽屉（含试算预览）
    const editOn = await p.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(x => x.innerText.includes('编辑布局'))
      if (!btn) return false
      btn.click()
      return true
    })
    if (editOn) {
      await S.sleep(700)
      await snap(p, 'cockpit-edit', mode)
      await p.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find(x => x.innerText.includes('添加卡片'))
        btn && btn.click()
      })
      await p.waitForSelector('.widget-drawer', { visible: true, timeout: 6000 }).catch(() => {})
      await S.sleep(700)
      await p.evaluate(() => {
        const btn = [...document.querySelectorAll('.widget-drawer button')].find(x => x.innerText.includes('试算'))
        btn && btn.click()
      })
      await S.waitFor(p, () => {
        const box = document.querySelector('.preview-box')
        return box && !box.classList.contains('empty')
      }, 9000)
      await S.sleep(500)
      await snap(p, 'cockpit-widget-drawer', mode)
      await p.evaluate(() => {
        const btn = [...document.querySelectorAll('.widget-drawer button')].find(x => /取消|关闭/.test(x.innerText))
        btn && btn.click()
      })
      await S.sleep(600)
      await p.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find(x => x.innerText.includes('取消'))
        btn && btn.click()
      })
      await S.sleep(600)
    }

    // ---------- 6) 系统管理 ----------
    for (const [path, name] of [
      ['/system/users', 'sys-users'],
      ['/system/roles', 'sys-roles'],
      ['/system/audit', 'sys-audit'],
    ]) {
      await p.goto(`${S.FE}/#${path}`, { waitUntil: 'domcontentloaded' })
      await p.reload({ waitUntil: 'networkidle2' })
      await setTheme(p, mode)
      await S.sleep(1600)
      await snap(p, name, mode)
    }
  }

  await b.close()

  if (tempDash) await S.del(`/api/dashboards/${tempDash}`)

  console.log(`\n共 ${shot} 张，输出目录：${OUT}`)
  if (errs.length) {
    console.log(`\n⚠️ 发现 ${errs.length} 条异常：`)
    errs.slice(0, 8).forEach(e => console.log('  ' + e))
    process.exit(1)
  }
  console.log('控制台与接口均无异常')
})().catch(e => { console.error(e); process.exit(1) })
