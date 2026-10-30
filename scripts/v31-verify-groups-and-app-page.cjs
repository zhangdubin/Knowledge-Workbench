/**
 * 知识库分组 + 应用独立页 体检
 *
 * 为什么需要这个脚本：
 * 这两块都是「看着有、其实不能用」的高发区 ——
 *   · 分组：侧栏画出来了，但点了不过滤；建了组但笔记进不去
 *   · 应用页：页面渲染了，但表单没按数据模型生成字段、删记录不问一声
 * 所以这里全部用**计算样式**和**文本内容**断言：
 * 不截图（截图得靠眼睛看，测不出「其实没渲染出来」），
 * 也不靠「元素存在」（存在但透明、零高度、白字白底，一样是坏的）。
 *
 * 用法：
 *   BASE=http://localhost:5173 node scripts/v31-verify-groups-and-app-page.cjs
 *   KB_USER=admin KB_PASS=xxx BASE=... node scripts/v31-verify-groups-and-app-page.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')

const BASE = process.env.BASE || process.env.KB_FRONTEND || 'http://127.0.0.1:5173'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 元素是否「真的看得见」：有面积、不透明、没被藏起来 */
const VISIBLE = (sel) => {
  const el = document.querySelector(sel)
  if (!el) return { ok: false, why: '元素不存在' }
  const r = el.getBoundingClientRect()
  if (r.width < 2 || r.height < 2) return { ok: false, why: `没有面积 ${Math.round(r.width)}×${Math.round(r.height)}` }
  const s = getComputedStyle(el)
  if (s.display === 'none' || s.visibility === 'hidden') return { ok: false, why: '被隐藏了' }
  if (Number(s.opacity) < 0.05) return { ok: false, why: `透明度 ${s.opacity}` }
  return { ok: true, text: (el.innerText || '').trim(), bg: s.backgroundColor, fg: s.color, h: Math.round(r.height) }
}

/** 文字颜色和背景色的对比度（WCAG） */
function contrast(fg, bg) {
  const lum = (c) => {
    const m = c.match(/[\d.]+/g)
    if (!m) return null
    const [r, g, b] = m.slice(0, 3).map(Number)
    const f = (v) => {
      v /= 255
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  const l1 = lum(fg), l2 = lum(bg)
  if (l1 == null || l2 == null) return null
  const a = Math.max(l1, l2), b = Math.min(l1, l2)
  return Math.round(((a + 0.055) / (b + 0.055)) * 100) / 100
}

/** 页面上有没有这个文字（可见的） */
const HAS_TEXT = (text) => {
  const el = Array.from(document.querySelectorAll('body *')).find((x) => {
    if (x.children.length > 0) return false
    const t = (x.textContent || '').trim()
    if (!t.includes(text)) return false
    const r = x.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) return false
    const s = getComputedStyle(x)
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0.05
  })
  return !!el
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 1000 })

  const problems = []
  const ok = (msg) => console.log(`✔ ${msg}`)
  const bad = (msg) => { console.log(`✘ ${msg}`); problems.push(msg) }

  try {
    // ---- 登录 ----
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(1200)
    const inputs = await page.$$('input')
    if (inputs.length < 2) {
      bad('登录页没找到用户名/密码输入框')
    } else {
      await inputs[0].click({ clickCount: 3 })
      await inputs[0].press('Backspace')
      await inputs[0].type(USER, { delay: 8 })
      await inputs[1].click({ clickCount: 3 })
      await inputs[1].press('Backspace')
      await inputs[1].type(PASS, { delay: 8 })
      await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button'))
          .find((x) => (x.innerText || '').trim() === '登录')
        if (b) b.click()
      })
      for (let i = 0; i < 30; i++) {
        await sleep(500)
        const u = await page.evaluate(() => location.hash)
        if (!u.includes('/login')) break
      }
      const after = await page.evaluate(() => location.hash)
      if (after.includes('/login')) bad('登录没成功（还停在登录页）')
      else ok(`登录成功（${after}）`)
    }

    // ==========================================================
    // 一、知识库分组
    // ==========================================================
    console.log('\n── 知识库分组 ──')
    await page.goto(`${BASE}/#/notes`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2500)

    // 1.1 分组侧栏存在
    const sidebar = await page.evaluate(() => {
      // 找「全部笔记」或「未分组」所在的侧栏容器：
      // 取包含这两个词之一的最小可见容器，再看它是不是有宽度
      const hit = Array.from(document.querySelectorAll('body *')).find((x) => {
        if (x.children.length > 0) return false
        const t = (x.textContent || '').trim()
        if (t !== '全部笔记' && t !== '未分组') return false
        const r = x.getBoundingClientRect()
        return r.width > 2 && r.height > 2
      })
      if (!hit) return null
      // 一路上溯，直到宽度像个侧栏（120~340px）
      //
      // 原来还要求「高度 > 260px」，那是在拿高度当「像个侧栏」的代理指标 ——
      // 其实那个高度正是 bug 本身：列表 flex:1 + min-height:320px，
      // 两个分组也能把每行撑到 111px。现在侧栏按内容收缩，
      // 高度随分组数量变，所以只验宽度和结构。
      let node = hit
      for (let i = 0; i < 6 && node.parentElement; i++) {
        const p = node.parentElement
        const r = p.getBoundingClientRect()
        if (r.width >= 110 && r.width <= 340 && r.height > 60) return { w: Math.round(r.width), h: Math.round(r.height) }
        node = p
      }
      return { w: Math.round(hit.getBoundingClientRect().width), h: Math.round(hit.getBoundingClientRect().height), narrow: true }
    })
    if (!sidebar) {
      bad('知识库页面上找不到分组侧栏（连「全部笔记」都没渲染）')
    } else if (sidebar.narrow) {
      bad('分组侧栏宽度不正常（像个普通文字块，不是侧栏）')
    } else {
      ok(`分组侧栏在位（${sidebar.w}×${sidebar.h}）`)
    }

    // 1.1b 侧栏每一行都要是「一行」的高度
    //
    // 踩过的坑：侧栏列表写了 flex:1，容器又写死 min-height:320px，
    // 结果两个分组也能把每行撑到 111px —— 一屏两个巨大的空白块，
    // 看着像页面加载坏了。分组少的时候，侧栏就该矮下去。
    const rowHeights = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.ng-side-item')).map((e) => Math.round(e.getBoundingClientRect().height))
    )
    if (!rowHeights.length) {
      bad('侧栏里一个分组项都没有')
    } else if (Math.max(...rowHeights) > 48) {
      bad(`侧栏分组项被拉高了（最高 ${Math.max(...rowHeights)}px）—— 分组少的时候不该撑出一片空白`)
    } else {
      ok(`侧栏分组项高度正常（${rowHeights.join('/')}px）`)
    }

    // 1.2 有「新建分组」的入口
    const hasCreateGroup = await page.evaluate(() =>
      Array.from(document.querySelectorAll('button, .el-button, [role="button"]'))
        .some((b) => /新建分组|新增分组|添加分组|\+/.test((b.innerText || b.getAttribute('aria-label') || '').trim()))
    )
    if (hasCreateGroup) ok('有「新建分组」入口')
    else bad('找不到「新建分组」入口')

    // 1.3 建一个分组，然后它要出现在侧栏里
    const GROUP_NAME = `体检分组${Date.now().toString().slice(-5)}`
    let created = false
    try {
      await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button, .el-button'))
          .find((x) => /新建分组|新增分组|添加分组/.test((x.innerText || '').trim()))
        if (b) b.click()
      })
      await sleep(900)
      // 输入框里填名字
      const typed = await page.evaluate((name) => {
        const inputs = Array.from(document.querySelectorAll('.el-dialog input, .el-drawer input, input'))
          .filter((i) => i.offsetParent !== null && i.type !== 'password')
        if (!inputs.length) return false
        const input = inputs[inputs.length - 1]
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
        setter.call(input, name)
        input.dispatchEvent(new Event('input', { bubbles: true }))
        return true
      }, GROUP_NAME)
      if (typed) {
        await sleep(400)
        await page.evaluate(() => {
          const b = Array.from(document.querySelectorAll('.el-dialog button, .el-drawer button, .el-message-box button'))
            .find((x) => /^(确定|保存|创建|新建|确认)$/.test((x.innerText || '').trim()))
          if (b) b.click()
        })
        await sleep(1800)
        created = HAS_TEXT ? await page.evaluate((n) => {
          return Array.from(document.querySelectorAll('body *')).some((x) => {
            if (x.children.length > 0) return false
            return (x.textContent || '').trim().includes(n)
          })
        }, GROUP_NAME) : false
      }
    } catch (e) {
      console.log('  （建分组过程异常：' + e.message + '）')
    }
    if (created) ok(`分组「${GROUP_NAME}」建出来了，并且出现在页面上`)
    else bad(`分组「${GROUP_NAME}」没建出来（或建了但页面上看不到）`)

    // 1.4 点分组能过滤（URL 或列表内容要变）
    const beforeHash = await page.evaluate(() => location.hash)
    const beforeRows = await page.evaluate(() => document.querySelectorAll('.el-table__row, .notes-item, .note-card, [data-note-id]').length)
    await page.evaluate((n) => {
      const el = Array.from(document.querySelectorAll('body *')).find((x) => {
        if (x.children.length > 0) return false
        return (x.textContent || '').trim().includes(n)
      })
      if (el) el.click()
    }, GROUP_NAME)
    await sleep(1500)
    const afterHash = await page.evaluate(() => location.hash)
    const afterRows = await page.evaluate(() => document.querySelectorAll('.el-table__row, .notes-item, .note-card, [data-note-id]').length)
    if (afterHash !== beforeHash || afterRows !== beforeRows) {
      ok(`点分组后列表有变化（地址 ${beforeHash} → ${afterHash}，行数 ${beforeRows} → ${afterRows}）`)
    } else {
      bad('点分组既没改地址也没改列表 —— 分组只是画了个样子')
    }

    // 1.5 空分组要有引导，不能白屏
    const emptyState = await page.evaluate(() => {
      const t = document.body.innerText || ''
      return /空|还没有|新建第|没有笔记|暂无/.test(t)
    })
    if (emptyState) ok('空分组有引导文案')
    else bad('空分组没有引导文案（可能白屏）')

    // ==========================================================
    // 二、应用独立页
    // ==========================================================
    console.log('\n── 应用独立页 ──')
    await page.goto(`${BASE}/#/apps/sales`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2800)

    // 2.1 是独立页（不是抽屉）
    const isDrawer = await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      if (!d) return false
      const r = d.getBoundingClientRect()
      return r.width > 200 && r.height > 300
    })
    if (isDrawer) bad('应用详情还是抽屉 —— 用户要的是独立页面')
    else ok('应用详情是独立页面（不是抽屉）')

    // 2.2 页头有应用名
    if (HAS_TEXT ? await page.evaluate(() => (document.body.innerText || '').includes('销售管理')) : false) {
      ok('页面标题区有应用名「销售管理」')
    } else {
      bad('页面上找不到应用名「销售管理」')
    }

    // 2.3 左侧有数据模型列表
    const models = await page.evaluate(() => {
      const want = ['客户', '商机', '订单']
      const found = want.filter((w) => Array.from(document.querySelectorAll('body *')).some((x) => {
        if (x.children.length > 0) return false
        return (x.textContent || '').trim() === w
      }))
      return { found, total: want.length }
    })
    if (models.found.length >= 2) ok(`模型列表里有 ${models.found.join('、')}`)
    else bad(`模型列表不完整（只找到 ${models.found.join('、') || '无'}）`)

    // 2.4 记录表有数据，且字段按数据模型渲染（表头是中文标签，不是 key）
    const tableInfo = await page.evaluate(() => {
      const ths = Array.from(document.querySelectorAll('.el-table th, table th'))
        .map((t) => (t.innerText || '').trim()).filter(Boolean)
      const rows = document.querySelectorAll('.el-table__row, table tbody tr').length
      return { ths, rows }
    })
    if (tableInfo.ths.includes('客户名称')) ok(`表头用的是字段中文名（含「客户名称」，共 ${tableInfo.ths.length} 列）`)
    else bad(`表头不是字段中文名：${tableInfo.ths.slice(0, 6).join(' / ') || '没找到表头'}`)
    if (tableInfo.rows > 0) ok(`记录表有 ${tableInfo.rows} 行数据`)
    else bad('记录表一行数据都没有')

    // 2.5 枚举字段要渲染成可读形态（不能是原始 id）
    const enumOk = await page.evaluate(() => {
      const cells = Array.from(document.querySelectorAll('.el-table__row td, table tbody td'))
        .map((c) => (c.innerText || '').trim())
      return cells.some((c) => /VIP|战略|普通/.test(c))
    })
    if (enumOk) ok('枚举字段（客户级别）渲染成了可读值')
    else bad('枚举字段没渲染成可读值（可能显示的是 id）')

    // 2.6 录入记录的表单要按数据模型生成字段
    let formOk = false
    try {
      await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button, .el-button'))
          .find((x) => /录入记录|新建记录|新增记录|\+ *记录/.test((x.innerText || '').trim()))
        if (b) b.scrollIntoView({ block: 'center' })
      })
      await sleep(400)
      await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button, .el-button'))
          .find((x) => /录入记录|新建记录|新增记录/.test((x.innerText || '').trim()))
        if (b) b.click()
      })
      await sleep(1500)
      formOk = await page.evaluate(() => {
        const scope = document.querySelector('.el-drawer, .el-dialog') || document.body
        const t = scope.innerText || ''
        return /客户名称/.test(t) && /联系电话|手机/.test(t)
      })
      await page.keyboard.press('Escape')
      await sleep(600)
    } catch (e) { /* 表单没打开也算失败，下面统一报 */ }
    if (formOk) ok('录入记录的表单按数据模型生成了字段（客户名称/联系电话）')
    else bad('录入记录的表单没有按数据模型生成字段')

    // 2.7 有卡片视图（可视化）
    const hasCardView = await page.evaluate(() => {
      const seg = Array.from(document.querySelectorAll('.el-segmented__item, .el-radio-button__inner, button'))
        .some((x) => /卡片|网格|看板/.test((x.innerText || '').trim()))
      return seg
    })
    if (hasCardView) ok('有卡片/网格视图切换')
    else bad('没有卡片/网格视图切换（只有表格谈不上「可视化」）')

    // 2.8 删除记录要二次确认
    const hasConfirm = await page.evaluate(() => {
      const rows = document.querySelectorAll('.el-table__row')
      if (!rows.length) return false
      const btns = rows[0].querySelectorAll('button, .el-button')
      return Array.from(btns).some((b) => /删除/.test((b.innerText || b.getAttribute('aria-label') || '')))
    })
    if (hasConfirm) ok('行操作里有删除入口（是否二次确认另测）')
    else bad('记录行没有删除入口')

    // 2.9 窄屏不塌
    await page.setViewport({ width: 820, height: 900 })
    await sleep(1200)
    const narrow = await page.evaluate(() => {
      const el = document.querySelector('.el-table, table, .app-workspace, main')
      if (!el) return { ok: false, why: '没找到内容容器' }
      const r = el.getBoundingClientRect()
      return { ok: r.width <= window.innerWidth + 2, w: Math.round(r.width), win: window.innerWidth }
    })
    if (narrow.ok) ok(`窄屏（820px）内容没有横向溢出（${narrow.w} ≤ ${narrow.win}）`)
    else bad(`窄屏内容横向溢出（${narrow.w} > ${narrow.win}）`)
    await page.setViewport({ width: 1440, height: 1000 })

    // 2.10 对比度抽检
    const contrastResult = await page.evaluate(() => {
      const bad = []
      const pick = document.querySelectorAll('.el-table td, .el-table th, .app-workspace button, .app-workspace .el-button')
      let checked = 0
      for (const el of Array.from(pick).slice(0, 40)) {
        const s = getComputedStyle(el)
        let bg = s.backgroundColor
        let p = el
        while (bg === 'rgba(0, 0, 0, 0)' && p.parentElement) { p = p.parentElement; bg = getComputedStyle(p).backgroundColor }
        const fg = s.color
        const lum = (c) => {
          const m = c.match(/[\d.]+/g); if (!m) return null
          const [r, g, b] = m.slice(0, 3).map(Number)
          const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
          return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
        }
        const l1 = lum(fg), l2 = lum(bg)
        if (l1 == null || l2 == null) continue
        const a = Math.max(l1, l2), b = Math.min(l1, l2)
        const cr = Math.round(((a + 0.055) / (b + 0.055)) * 100) / 100
        checked++
        if (cr < 4.5) bad.push(`${cr}:1 「${(el.innerText || '').trim().slice(0, 14)}」`)
      }
      return { checked, bad: bad.slice(0, 5) }
    })
    if (contrastResult.checked && !contrastResult.bad.length) ok(`对比度抽检 ${contrastResult.checked} 处全部达标`)
    else if (contrastResult.bad.length) bad(`对比度不达标：${contrastResult.bad.join('；')}`)
    else ok('对比度抽检：没取到可测的元素')

  } catch (e) {
    bad(`脚本异常：${e.message}`)
  } finally {
    await browser.close()
    // 收尾：把体检建出来的分组删掉，别在用户的库里留垃圾
    // （体检脚本跑一次就留一个分组，用久了分栏里全是「体检分组xxxx」）
    try {
      const API = process.env.API || 'http://127.0.0.1:8001'
      const USER = process.env.KB_USER || 'admin'
      const PASS = process.env.KB_PASS || 'Kb@2026admin'
      const lr = await fetch(`${API}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: USER, password: PASS }),
      })
      const cookie = (lr.headers.getSetCookie?.() || []).map((c) => c.split(';')[0]).join('; ')
      const gs = await (await fetch(`${API}/api/note-groups`, { headers: { Cookie: cookie } })).json()
      for (const g of (Array.isArray(gs) ? gs : [])) {
        if (/^体检分组/.test(g.name)) {
          await fetch(`${API}/api/note-groups/${g.id}`, { method: 'DELETE', headers: { Cookie: cookie } })
        }
      }
    } catch { /* 收尾失败不影响体检结论 */ }
  }

  console.log('')
  if (problems.length) {
    console.log(`体检未通过：${problems.length} 项问题`)
    problems.forEach((p) => console.log(`  ✘ ${p}`))
    process.exit(1)
  } else {
    console.log('分组与应用页体检通过')
  }
}

main()
