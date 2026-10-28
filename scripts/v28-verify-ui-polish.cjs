/**
 * UI 体检：把「简陋」翻译成可测量的指标
 *
 * 为什么需要这个脚本：
 * 「界面简陋」是个主观描述，改完很难说清到底有没有改好。
 * 这里把它拆成几条能自动判定的规则 —— 触控目标够不够大、文字对比度够不够、
 * 焦点看不看得见、有没有横向溢出、弹窗按钮是不是右对齐。
 * 每次改动后跑一遍，指标掉了就是真的退步了，比凭感觉靠谱。
 *
 * 用法：
 *   node scripts/v28-verify-ui-polish.cjs
 *   BASE=http://127.0.0.1:8082 node scripts/v28-verify-ui-polish.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { FE, USER, PASS } = require(path.join(__dirname, 'lib', 'session.cjs'))

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 受检页面。选的是「用户天天看」的几个：列表页、卡片页、表单页、设置页
const PAGES = [
  ['工作台', '/'],
  ['应用中心', '/apps'],
  ['数据模型', '/types'],
  ['记录', '/records/1'],
  ['知识库', '/notes'],
  ['数据中心', '/library'],
  ['系统设置', '/system/settings'],
]

// 在页面里跑的检查。全部返回可断言的数值，不返回主观描述。
const PROBE = () => {
  const out = {}

  // ---- 1. 触控目标：可点击元素的实际命中区域 ----
  // 图标按钮最容易做成 20px 的小点，点不准是「简陋」最直接的体感
  const sels = 'button, .el-button, [role="button"], a.el-dropdown-link, .tile-menu-btn'
  const small = []
  document.querySelectorAll(sels).forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return // 不可见
    if (r.width < 28 || r.height < 28) {
      small.push({
        cls: (el.className || '').toString().slice(0, 40),
        w: Math.round(r.width),
        h: Math.round(r.height),
        text: (el.textContent || '').trim().slice(0, 16),
      })
    }
  })
  out.smallTargets = small.slice(0, 12)
  out.smallTargetCount = small.length

  // ---- 2. 横向溢出：内容比视口宽就是「排版崩了」 ----
  out.hOverflow = Math.max(
    0,
    document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )

  // ---- 3. 文字对比度 ----
  const lum = (rgb) => {
    const [r, g, b] = rgb.map((v) => {
      const s = v / 255
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const parse = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || '')
    if (!m) return null
    const p = m[1].split(',').map((x) => parseFloat(x))
    return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }
  }
  // 渐变里的所有颜色。背景是渐变时，backgroundColor 是 transparent，
  // 只读 backgroundColor 会一路往上找到白底，把「深色渐变上的白字」误判成 1:1
  const gradientColors = (img) => {
    if (!img || img === 'none') return []
    const out = []
    const re = /rgba?\(([^)]+)\)/g
    let m
    while ((m = re.exec(img))) {
      const p = m[1].split(',').map((x) => parseFloat(x))
      if (p.length >= 3) out.push({ rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 })
    }
    return out
  }
  // 元素的有效背景：自身有不透明底色就用它；自身有渐变就用渐变颜色的平均亮度
  const bgOf = (el) => {
    const cs = getComputedStyle(el)
    const c = parse(cs.backgroundColor)
    if (c && c.a > 0.5) return c.rgb
    const grads = gradientColors(cs.backgroundImage).filter((g) => g.a > 0.5)
    if (grads.length) {
      const avg = [0, 1, 2].map((i) =>
        grads.reduce((s, g) => s + g.rgb[i], 0) / grads.length)
      return avg
    }
    let n = el.parentElement
    while (n && n !== document.documentElement) {
      const ncs = getComputedStyle(n)
      const nc = parse(ncs.backgroundColor)
      if (nc && nc.a > 0.5) return nc.rgb
      const ng = gradientColors(ncs.backgroundImage).filter((g) => g.a > 0.5)
      if (ng.length) {
        return [0, 1, 2].map((i) => ng.reduce((s, g) => s + g.rgb[i], 0) / ng.length)
      }
      n = n.parentElement
    }
    return [255, 255, 255]
  }

  // 祖先链找不到底色时，用几何扫描补一次：
  // 有些控件的"选中底"是绝对定位的兄弟节点（Element Plus 的分段滑块就是），
  // 它不是祖先，只按祖先链算会把「白字压深色滑块」误判成白字压白底。
  // elementsFromPoint 会忽略 pointer-events:none 的滑块，所以只能自己扫。
  const paintedUnder = (el) => {
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return null
    const cx = r.left + r.width / 2
    const cy = r.top + r.height / 2
    const all = document.querySelectorAll('*')
    let best = null
    for (const cand of all) {
      if (cand === el || cand.contains(el)) continue
      const cs = getComputedStyle(cand)
      if (cs.position !== 'absolute' && cs.position !== 'fixed') continue
      if (cs.display === 'none' || cs.visibility === 'hidden') continue
      const bc = parse(cs.backgroundColor)
      if (!bc || bc.a <= 0.5) continue
      const cr = cand.getBoundingClientRect()
      if (cx < cr.left || cx > cr.right || cy < cr.top || cy > cr.bottom) continue
      // 画在越靠后的越优先
      best = bc.rgb
    }
    return best
  }
  const lowContrast = []
  // 禁用的控件不参与对比度判定。
  // WCAG 1.4.3 明确豁免「失效的用户界面组件」—— 禁用按钮就该看起来是失效的，
  // 把它按正常文字的 4.5:1 去卡，等于逼着禁用态也做得跟可用态一样醒目。
  const isDisabled = (el) => {
    if (el.disabled === true) return true
    if (el.getAttribute('aria-disabled') === 'true') return true
    if (el.classList && el.classList.contains('is-disabled')) return true
    let n = el.parentElement
    while (n && n !== document.body) {
      if (n.classList && n.classList.contains('is-disabled')) return true
      if (n.getAttribute && n.getAttribute('aria-disabled') === 'true') return true
      n = n.parentElement
    }
    return false
  }
  document.querySelectorAll('p, span, div, label, td, th, li, a, button, h1, h2, h3, h4').forEach((el) => {
    // 只看直接含文字的元素
    const txt = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join('')
    if (txt.length < 2) return
    const cs = getComputedStyle(el)
    if (cs.visibility === 'hidden' || cs.display === 'none') return
    if (isDisabled(el)) return
    const fg = parse(cs.color)
    if (!fg || fg.a < 0.5) return
    let bg = bgOf(el)
    const l1 = lum(fg.rgb)
    const l2 = lum(bg)
    let ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
    // 大号粗体字（≥18.66px 粗体 或 ≥24px）的门槛是 3:1，其余 4.5:1
    const size = parseFloat(cs.fontSize)
    const bold = parseInt(cs.fontWeight, 10) >= 700
    const min = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5
    // 祖先链算出来不达标时，再用几何扫描确认一次「底下实际画的是什么」
    if (ratio < min) {
      const under = paintedUnder(el)
      if (under) {
        const u2 = lum(under)
        const r2 = (Math.max(l1, u2) + 0.05) / (Math.min(l1, u2) + 0.05)
        if (r2 > ratio) ratio = r2
      }
    }
    if (ratio < min) {
      lowContrast.push({
        text: txt.slice(0, 20),
        ratio: Math.round(ratio * 100) / 100,
        need: min,
        size: Math.round(size),
        color: cs.color,
      })
    }
  })
  out.lowContrast = lowContrast.slice(0, 12)
  out.lowContrastCount = lowContrast.length

  // ---- 4. 焦点可见性：键盘用户能不能看见自己在哪 ----
  const btn = document.querySelector('button, .el-button, a[href], input')
  let focusRing = false
  let focusInfo = 'no-focusable'
  if (btn) {
    btn.focus()
    const cs = getComputedStyle(btn)
    const hasOutline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0
    const hasShadow = cs.boxShadow && cs.boxShadow !== 'none'
    focusRing = hasOutline || hasShadow
    focusInfo = `outline=${cs.outline} shadow=${cs.boxShadow.slice(0, 40)}`
    btn.blur()
  }
  out.focusRing = focusRing
  out.focusInfo = focusInfo

  // ---- 5. 正文字号与行高下限 ----
  let minFont = 999
  let minLine = 999
  document.querySelectorAll('p, td, li, .el-form-item__label, .el-table__cell').forEach((el) => {
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden') return
    const txt = (el.textContent || '').trim()
    if (!txt) return
    minFont = Math.min(minFont, parseFloat(cs.fontSize) || 99)
    const lh = parseFloat(cs.lineHeight)
    if (lh) minLine = Math.min(minLine, lh / (parseFloat(cs.fontSize) || 1))
  })
  out.minFont = minFont === 999 ? null : Math.round(minFont)
  out.minLineHeight = minLine === 999 ? null : Math.round(minLine * 100) / 100

  // ---- 6. 结构件：工具条 / 搜索入口 / 空状态 ----
  out.hasToolbar = !!document.querySelector('.toolbar, .kb-toolbar, [class*="toolbar"]')
  out.hasSearch = !!document.querySelector('input[type="search"], .el-input__inner, input[placeholder*="搜索"]')
  out.hasEmptyState = !!document.querySelector('.empty-state, .empty, [class*="empty"]')

  // ---- 7. 交互元素是否都是原生可聚焦的 ----
  // 用 div 冒充按钮是「不好用」的常见来源：鼠标能点，键盘却到不了
  // 但要排除「可点元素内部的子节点」—— 它们继承 pointer 光标，
  // 却不是独立的点击目标（整张卡片才是）。把它们算成伪按钮是误报。
  const inClickable = (el) => {
    let n = el.parentElement
    while (n && n !== document.body) {
      if (n.tagName === 'BUTTON' || n.tagName === 'A') return true
      const role = n.getAttribute && n.getAttribute('role')
      if (role === 'button' || role === 'link') return true
      n = n.parentElement
    }
    return false
  }
  let fakeButtons = 0
  document.querySelectorAll('[class*="btn"], [class*="card"], [class*="tile"]').forEach((el) => {
    const cs = getComputedStyle(el)
    if (cs.cursor !== 'pointer') return
    if (el.tagName === 'BUTTON' || el.tagName === 'A') return
    if (el.getAttribute('tabindex') === '-1') return
    if (el.getAttribute('role') === 'button' || el.getAttribute('role') === 'link') return
    if (inClickable(el)) return
    fakeButtons++
  })
  out.fakeButtons = fakeButtons

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
    await inputs[0].click({ clickCount: 3 })
    await page.keyboard.press('Backspace')
    await inputs[0].type(USER)
    await inputs[1].click({ clickCount: 3 })
    await page.keyboard.press('Backspace')
    await inputs[1].type(PASS)
    await page.click('button[type=submit], .el-button--primary')
    await sleep(2500)
  }

  // 登录必须真的成功。
  //
  // 为什么要加这一段：脚本原本登录完就直接往下跑，
  // 账号口令一旦失效（改过密码、库被重建、账号被删），
  // 登录会失败并被弹回 #/login —— 而后面每一页「打开」的都是登录页，
  // 于是所有检查都落在同一张页面上，「7/7 无问题」是**假绿**。
  // 踩过一次才发现，所以这里必须硬失败：测不到东西就别报通过。
  const loggedIn = await page.evaluate(() => !String(location.hash).includes('/login'))
  if (!loggedIn) {
    console.log('✘ 登录失败（还停在登录页）—— 下面的检查全都会落在登录页上，结果没有意义')
    console.log(`   账号: ${USER}`)
    console.log('   用 KB_USER / KB_PASS 覆盖，或先跑 scripts/reset-admin-password.sh 重置口令')
    await browser.close()
    process.exit(1)
  }

  const results = []
  for (const [name, route] of PAGES) {
    await page.goto(`${base}/#${route}`, { waitUntil: 'networkidle2' })
    await sleep(1800)
    let probe
    try {
      probe = await page.evaluate(PROBE)
    } catch (e) {
      results.push({ name, route, error: e.message })
      continue
    }
    results.push({ name, route, ...probe })
  }
  await browser.close()

  // ---- 判定 ----
  let fail = 0
  const problems = []
  for (const r of results) {
    if (r.error) {
      console.log(`✘ ${r.name} 探针失败: ${r.error}`)
      fail++
      continue
    }
    const bad = []
    if (r.hOverflow > 2) bad.push(`横向溢出 ${r.hOverflow}px`)
    if (r.smallTargetCount > 0) bad.push(`触控目标过小 ${r.smallTargetCount} 处`)
    if (r.lowContrastCount > 0) bad.push(`对比度不足 ${r.lowContrastCount} 处`)
    if (!r.focusRing) bad.push('焦点不可见')
    if (r.minFont && r.minFont < 12) bad.push(`正文字号 ${r.minFont}px 过小`)
    if (r.minLineHeight && r.minLineHeight < 1.35) bad.push(`行高 ${r.minLineHeight} 过密`)
    if (r.fakeButtons > 0) bad.push(`伪按钮 ${r.fakeButtons} 个`)

    if (bad.length) {
      fail++
      problems.push({ page: r.name, bad, detail: r })
      console.log(`✘ ${r.name.padEnd(8)} ${bad.join('；')}`)
      if (r.smallTargets.length) {
        r.smallTargets.slice(0, 3).forEach((t) =>
          console.log(`     · 小目标 ${t.w}×${t.h} 「${t.text}」 .${t.cls}`))
      }
      if (r.lowContrast.length) {
        r.lowContrast.slice(0, 3).forEach((t) =>
          console.log(`     · 对比度 ${t.ratio}:1 (需 ${t.need}) ${t.size}px 「${t.text}」 ${t.color}`))
      }
    } else {
      console.log(`✔ ${r.name.padEnd(8)} 无问题（对比度、焦点、触控、溢出、行高均达标）`)
    }
  }

  console.log(`\n共检查 ${PAGES.length} 个页面，${fail} 个存在问题`)
  if (fail) {
    console.log('\n明细（JSON）：')
    console.log(JSON.stringify(problems, null, 2))
    process.exit(1)
  }
})().catch((e) => {
  console.error('异常:', e.message)
  process.exit(1)
})
