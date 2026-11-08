/**
 * 左侧导航栏的排版体检
 *
 * 为什么要有这个脚本：
 *   侧栏好不好看，眼睛一看就知道；但「一屏放不放得下」「对齐不对不对」
 *   靠眼睛看不出来 —— 得量。
 *   这台机器上侧栏有 23 个入口、4 个分组，
 *   排版松一点，800px 高的笔记本屏上就得往下滚半屏才够得着「系统设置」，
 *   看着就「挤」「乱」「丑」。
 *
 * 这里量的都是能判对错的东西：
 *   · 菜单内容高度 vs 可视高度（溢出多少像素）
 *   · **左对齐轴**：图标字形、分组标题、底部按钮图标、文字起始位置
 *     是不是在同一条竖线上（v1.5.3 就是栽在这儿：图标盒子 24px 套 16px 图标，
 *     图标被推到 25px，标题在 21px —— 同一列三个左轴）
 *   · 分组标题、菜单项、正文的对比度（WCAG AA：正文 ≥ 4.5:1）
 *   · 折叠态与展开态的宽度、图标方块尺寸
 *   · 底部边缘是「软渐隐」还是「硬切」
 *   · 侧栏与移动端抽屉是不是同一套（菜单项同高、品牌块同款）
 *
 * 用法：node scripts/kb-verify-nav-layout.cjs
 *      BASE=http://127.0.0.1:8082 node scripts/kb-verify-nav-layout.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

let failed = 0
function check(ok, label, extra = '') {
  console.log((ok ? '  ✓ ' : '  ✗ ') + label + (extra ? '  — ' + extra : ''))
  if (!ok) failed++
}

/* ---- WCAG 对比度 ---- */
function srgb(c) { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4) }
function lum(rgb) { return 0.2126 * srgb(rgb[0]) + 0.7152 * srgb(rgb[1]) + 0.0722 * srgb(rgb[2]) }
function parseColor(s) {
  const m = String(s).match(/rgba?\(([^)]+)\)/)
  if (!m) return null
  const p = m[1].split(/[ ,]+/).filter(Boolean).map(Number)
  return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
}
function composite(fg, bg) {
  const a = fg.a
  return { r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a) }
}
function contrast(fg, bg) {
  const a = lum([fg.r, fg.g, fg.b]), b = lum([bg.r, bg.g, bg.b])
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/**
 * 量侧栏的对齐轴。
 *
 * 「图标在哪」要看**字形**（svg），不是图标盒子：
 *   Element Plus 给菜单项的图标留了 24px 的盒子，
 *   16px 的图标被居中在盒子里 —— 量盒子会以为图标在 21px，
 *   实际字形在 25px，差了 4px，肉眼看就是「歪」。
 *
 * 「文字在哪」要用 Range 量：
 *   Element Plus 的菜单项文字是**裸文本节点**（没有 span），
 *   querySelector('span') 找不到它。
 */
async function measureAxes(page) {
  return page.evaluate(() => {
    const q = s => document.querySelector(s)
    const sb = q('.sidebar').getBoundingClientRect()
    const menu = q('.nav-menu')
    const items = [...menu.querySelectorAll('.el-menu-item')]
    const groups = [...menu.querySelectorAll('.nav-group-title')]

    const glyphXs = []
    const textXs = []
    const gaps = []
    for (const it of items) {
      const svg = it.querySelector('.el-icon svg') || it.querySelector('svg')
      if (svg) glyphXs.push(Math.round(svg.getBoundingClientRect().left - sb.left))
      const tn = [...it.childNodes].find(n => n.nodeType === 3 && n.textContent.trim())
      if (tn) {
        const r = document.createRange()
        r.setStart(tn, 0)
        r.setEnd(tn, 1)
        const cx = r.getBoundingClientRect().left - sb.left
        textXs.push(Math.round(cx))
        if (svg) gaps.push(Math.round(cx - svg.getBoundingClientRect().right))
      }
    }
    // 分组标题文字的左沿（标题是 div 里的裸文本，同样用 Range 量）
    const groupTextXs = []
    for (const g of groups) {
      const tn = [...g.childNodes].find(n => n.nodeType === 3 && n.textContent.trim())
      if (tn) {
        const r = document.createRange()
        r.setStart(tn, 0)
        r.setEnd(tn, 1)
        groupTextXs.push(Math.round(r.getBoundingClientRect().left - sb.left))
      }
    }
    // 底部按钮的图标左沿（它属于另一套 DOM，但必须跟导航项同轴）
    const footIconX = (() => {
      const i = q('.sidebar-footer .el-icon')
      return i ? Math.round(i.getBoundingClientRect().left - sb.left) : null
    })()
    return {
      glyphXs: [...new Set(glyphXs)].sort((a, b) => a - b),
      textXs: [...new Set(textXs)].sort((a, b) => a - b),
      groupTextXs: [...new Set(groupTextXs)].sort((a, b) => a - b),
      gaps: [...new Set(gaps)].sort((a, b) => a - b),
      footIconX,
      iconBoxW: (() => {
        const i = q('.nav-menu .el-menu-item .el-icon')
        return i ? Math.round(i.getBoundingClientRect().width) : null
      })(),
    }
  })
}

async function main() {
  const token = execFileSync('python3', [path.join(ROOT, 'scripts/kb-session-token.py')], { encoding: 'utf8' }).trim()
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await browser.setCookie({ name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' })

  console.log('▸ 展开态（1440×800 笔记本视口）')
  await page.setViewport({ width: 1440, height: 800 })
  await page.goto(BASE + '/#/', { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(2500)

  const m = await page.evaluate(() => {
    const q = s => document.querySelector(s)
    const cs = el => (el ? getComputedStyle(el) : null)
    const rect = el => (el ? el.getBoundingClientRect() : null)
    const menu = q('.nav-menu')
    const items = [...document.querySelectorAll('.nav-menu .el-menu-item')]
    const groups = [...document.querySelectorAll('.nav-group-title')]
    const active = q('.nav-menu .el-menu-item.is-active')
    const brand = q('.brand')
    const footer = q('.sidebar-footer')
    const icons = items.map(it => it.querySelector('.el-icon')).filter(Boolean)

    // 底部区：两个动作是不是排在同一行
    const acts = [...document.querySelectorAll('.footer-actions button')]
    const actBoxes = acts.map(b => {
      const r = b.getBoundingClientRect()
      const i = b.querySelector('.el-icon')
      return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top),
               left: Math.round(r.left - document.querySelector('.sidebar').getBoundingClientRect().left),
               iconLeft: i ? Math.round(i.getBoundingClientRect().left - document.querySelector('.sidebar').getBoundingClientRect().left) : null,
               text: (b.innerText || '').trim(), title: b.getAttribute('title') || '' }
    })

    // 侧栏专属令牌：改主题时只改这一处
    const sb = cs(q('.sidebar'))
    const navVars = {}
    ;['--nav-fg', '--nav-fg-muted', '--nav-fg-dim', '--nav-accent', '--nav-accent-grad',
      '--nav-surface', '--nav-hairline'].forEach(v => { navVars[v] = sb.getPropertyValue(v).trim() })

    // 「没有权限」的空态：规则必须真的在样式表里
    let emptyGroupRule = false
    for (const sheet of Array.from(document.styleSheets)) {
      let rules = []
      try { rules = Array.from(sheet.cssRules || []) } catch (e) { rules = [] }
      for (const r of rules) {
        if (r.selectorText && r.selectorText.indexOf('nav-group-empty') >= 0) { emptyGroupRule = true }
      }
    }

    const menuCs = cs(menu)
    return {
      sidebarW: Math.round(rect(q('.sidebar')).width),
      sidebarBg: cs(q('.sidebar')).backgroundColor,
      brandH: Math.round(rect(brand).height),
      brandSubColor: cs(q('.brand-sub')).color,
      footerH: Math.round(rect(footer).height),
      menuScrollH: menu.scrollHeight,
      menuClientH: menu.clientHeight,
      itemH: [...new Set(items.map(it => Math.round(rect(it).height)))],
      itemColor: cs(items[0]).color,
      itemRadius: cs(items[0]).borderRadius,
      groupColor: cs(groups[0]).color,
      groupSticky: cs(groups[0]).position,
      groupH: [...new Set(groups.map(g => Math.round(rect(g).height)))],
      iconXs: [...new Set(icons.map(i => Math.round(rect(i).x)))],
      iconColor: cs(items[0].querySelector('.el-icon')).color,
      activeBgImage: cs(active).backgroundImage,
      activeBgColor: cs(active).backgroundColor,
      activeColor: cs(active).color,
      hasMoreClass: menu.classList.contains('has-more-below'),
      maskImage: (menuCs.maskImage || menuCs.webkitMaskImage || 'none'),
      itemCount: items.length,
      groupCount: groups.length,
      actBoxes,
      navVars,
      emptyGroupRule,
      versionText: (q('.sys-version') || {}).textContent || '',
    }
  })

  const sb = parseColor(m.sidebarBg)
  const cr = (c) => {
    const fg = parseColor(c)
    if (!fg || !sb) return 0
    return contrast(fg.a < 1 ? composite(fg, sb) : fg, sb)
  }

  console.log('  侧栏 ' + m.sidebarW + 'px 宽，' + m.itemCount + ' 个入口 / ' + m.groupCount + ' 个分组')
  console.log('  品牌区 ' + m.brandH + 'px，底部区 ' + m.footerH + 'px，菜单项高 ' + JSON.stringify(m.itemH))
  console.log('  菜单内容 ' + m.menuScrollH + 'px / 可视 ' + m.menuClientH + 'px')

  check(m.groupSticky === 'sticky', '分组标题吸顶（滚到哪组知道是哪组）', m.groupSticky)
  check(m.itemH.length === 1 && m.itemH[0] <= 34, '菜单项高度统一且不挤', JSON.stringify(m.itemH))
  check(m.groupH.length === 1, '分组标题高度统一（吸顶时不会从下面露出半截）', JSON.stringify(m.groupH))
  check(m.footerH <= 100, '底部区不超过 100px（≈ 三个菜单项，别占掉导航的空间）', m.footerH + 'px')
  check(cr(m.itemColor) >= 4.5, '菜单项正文对比度 ≥ 4.5:1', cr(m.itemColor).toFixed(2) + ':1')
  check(cr(m.groupColor) >= 4.5, '分组标题对比度 ≥ 4.5:1', cr(m.groupColor).toFixed(2) + ':1')
  check(cr(m.brandSubColor) >= 4.5, '品牌副标题对比度 ≥ 4.5:1', cr(m.brandSubColor).toFixed(2) + ':1')
  check(cr(m.iconColor) >= 3, '图标对比度 ≥ 3:1（图形元素的底线）', cr(m.iconColor).toFixed(2) + ':1')
  check(cr(m.activeColor) >= 4.5, '当前项文字对比度 ≥ 4.5:1', cr(m.activeColor).toFixed(2) + ':1')
  // 当前项的底色：平涂的淡染（不是渐变，也不是「一层白」）
  check(m.activeBgImage.includes('gradient') || m.activeBgColor !== 'rgba(0, 0, 0, 0)',
    '当前项有底色（不是只靠字重区分）', m.activeBgColor)

  // ---- 对齐轴：这是 v1.5.3 真正翻车的地方 ----
  const ax = await measureAxes(page)
  console.log('  图标字形左沿 ' + JSON.stringify(ax.glyphXs) +
              ' / 标题左沿 ' + JSON.stringify(ax.groupTextXs) +
              ' / 文字左沿 ' + JSON.stringify(ax.textXs))
  check(ax.glyphXs.length === 1 && ax.glyphXs[0] === 21,
    '图标字形落在 21px 轴上（不是被 24px 的盒子推到 25px）', JSON.stringify(ax.glyphXs))
  check(ax.groupTextXs.length === 1 && ax.groupTextXs[0] === 21,
    '分组标题文字落在同一条 21px 轴上', JSON.stringify(ax.groupTextXs))
  check(ax.footIconX === 21, '底部按钮的图标也在同一条轴上', String(ax.footIconX))
  check(ax.textXs.length === 1 && ax.textXs[0] === 47,
    '菜单项文字落在 47px 轴上', JSON.stringify(ax.textXs))
  check(ax.gaps.length === 1 && ax.gaps[0] === 10,
    '图标与文字之间正好 10px（没有多出来的死区）', JSON.stringify(ax.gaps))
  check(ax.iconBoxW === 16,
    '图标盒子贴着图标本身（16px，不是 Element Plus 的 24px）', String(ax.iconBoxW))

  // ---- 底部区：两个动作并排、收起是纯图标、版本号在位 ----
  check(m.actBoxes.length >= 2, '底部区有两个动作（自定义导航 + 收起侧边栏）',
    '找到 ' + m.actBoxes.length + ' 个')
  if (m.actBoxes.length >= 2) {
    const [add, toggle] = m.actBoxes
    check(add.top === toggle.top, '两个动作排在同一行', add.top + ' / ' + toggle.top)
    check(toggle.w <= 40, '收起是纯图标按钮（不配一段重复的文字）',
      toggle.w + 'px · 「' + toggle.text + '」')
    // 两个按钮必须**同样规格**：一个带文字、一个是方形，并排就是大小不一
    check(add.w === toggle.w && add.h === toggle.h,
      '两个动作同样规格（不再一个宽一个方）',
      add.w + '×' + add.h + ' / ' + toggle.w + '×' + toggle.h)
    check(m.footerH <= 50, '底部只有一行（不超过 50px）', m.footerH + 'px')
  }
  check(/^v\d+\.\d+\.\d+/.test(m.versionText.trim()),
    '版本号在位（取自后端 /auth/status，不写死在构建里）', m.versionText.trim())
  const missingVars = Object.keys(m.navVars).filter(k => !m.navVars[k])
  check(missingVars.length === 0, '侧栏专属令牌（--nav-*）齐全', missingVars.join(','))
  check(m.emptyGroupRule, '「没有权限」的空分组有专门样式（不给它拖那条分组线）')

  const overflow = m.menuScrollH - m.menuClientH
  console.log('  溢出 ' + overflow + 'px —— 800px 高的屏上露不全是正常的，但要能滚、且看得出能滚')
  check(overflow < 200, '溢出压在 200px 内（v1.5.3 是 228px）', overflow + 'px')

  // ---- 底部边缘：软渐隐，不是硬切；滚到底就该干净停住 ----
  check(m.hasMoreClass && m.maskImage !== 'none',
    '下面还有内容时，底部用遮罩渐隐（软切口，不是硬切）',
    'mask=' + m.maskImage.slice(0, 46))
  const bottomState = await page.evaluate(async () => {
    const menu = document.querySelector('.nav-menu')
    menu.scrollTop = menu.scrollHeight
    await new Promise(r => setTimeout(r, 400))
    const cs = getComputedStyle(menu)
    const items = [...menu.querySelectorAll('.el-menu-item')]
    const last = items[items.length - 1]
    const mr = menu.getBoundingClientRect()
    const lr = last.getBoundingClientRect()
    return {
      hasMore: menu.classList.contains('has-more-below'),
      mask: (cs.maskImage || cs.webkitMaskImage || 'none'),
      lastBottom: Math.round(lr.bottom - mr.top),
      menuH: Math.round(mr.height),
      lastText: (last.innerText || '').trim(),
    }
  })
  check(!bottomState.hasMore && bottomState.mask === 'none',
    '滚到底后撤掉渐隐（别让人以为下面还有）',
    'hasMore=' + bottomState.hasMore + ' mask=' + bottomState.mask.slice(0, 30))
  check(bottomState.lastBottom <= bottomState.menuH,
    '滚到底时最后一项完整露出（没有被切）',
    bottomState.lastText + ' 底部 ' + bottomState.lastBottom + '/' + bottomState.menuH)
  await page.evaluate(() => { document.querySelector('.nav-menu').scrollTop = 0 })
  await sleep(300)

  // 吸顶标题的实际行为：滚到中间时，应该有一个标题正好贴在菜单顶边，
  // 并且它下面不该有内容从缝里穿过去。
  await page.evaluate(() => { document.querySelector('.nav-menu').scrollTop = 300 })
  await sleep(400)
  const sticky = await page.evaluate(() => {
    const menu = document.querySelector('.nav-menu')
    const menuTop = menu.getBoundingClientRect().top
    const titles = [...document.querySelectorAll('.nav-group-title')]
    const stuck = titles.filter(t => Math.abs(t.getBoundingClientRect().top - menuTop) < 2)
    // 吸住的那条带上方有没有漏出内容
    let peek = null
    if (stuck.length) {
      const r = stuck[stuck.length - 1].getBoundingClientRect()
      const probe = document.elementFromPoint(r.left + 30, menuTop + 1)
      peek = probe ? probe.className.toString().slice(0, 40) : null
    }
    return {
      stuckCount: stuck.length,
      stuckTitle: stuck.length ? stuck[stuck.length - 1].textContent.trim() : '',
      peek,
      titleBgs: [...new Set(titles.map(t => getComputedStyle(t).backgroundColor))],
      sidebarBg: getComputedStyle(document.querySelector('.sidebar')).backgroundColor,
    }
  })
  check(sticky.stuckCount >= 1, '滚动后有标题吸在菜单顶边', sticky.stuckTitle || '（没有）')
  check(!sticky.peek || !String(sticky.peek).includes('el-menu-item'),
    '吸顶标题上方没有内容穿缝露出', String(sticky.peek))
  check(sticky.titleBgs.every(b => b === sticky.sidebarBg),
    '吸顶标题底色与侧栏同色（不露方块）', sticky.titleBgs.join(',') + ' vs ' + sticky.sidebarBg)

  console.log('▸ 折叠态')
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.sidebar-footer button')].pop()
    if (b) b.click()
  })
  await sleep(1000)
  const c = await page.evaluate(() => {
    const q = s => document.querySelector(s)
    const rect = el => (el ? el.getBoundingClientRect() : null)
    const menu = q('.nav-menu')
    const item = q('.nav-menu .el-menu-item')
    const active = q('.nav-menu .el-menu-item.is-active')
    // 折叠态用短横线交代分组边界（原来那条线太淡，等于没有）
    const dividers = [...document.querySelectorAll('.nav-group-divider')]
      .map(d => {
        const r = d.getBoundingClientRect()
        return { w: Math.round(r.width), h: Math.round(r.height),
                 visible: getComputedStyle(d).display !== 'none' && r.width > 0 }
      })
    const acts = [...document.querySelectorAll('.footer-actions button')]
      .map(b => Math.round(b.getBoundingClientRect().width))
    // 折叠态图标要居中在 38px 的方块里
    const svg = item.querySelector('svg')
    const ir = rect(item), sr = rect(svg)
    return {
      w: Math.round(rect(q('.sidebar')).width),
      itemW: Math.round(ir.width),
      itemH: Math.round(ir.height),
      menuScrollH: menu.scrollHeight,
      menuClientH: menu.clientHeight,
      activeBg: getComputedStyle(active).backgroundImage,
      activeIconColor: getComputedStyle(active.querySelector('.el-icon')).color,
      dividers,
      actWidths: acts,
      iconOffset: sr ? Math.round(sr.left - ir.left) : null,
      iconSize: sr ? Math.round(sr.width) : null,
    }
  })
  console.log('  ' + c.w + 'px 宽，图标方块 ' + c.itemW + '×' + c.itemH)
  check(c.w === 64, '折叠宽度 64px', c.w + 'px')
  check(c.itemW === c.itemH, '折叠态图标方块是正方形', c.itemW + '×' + c.itemH)
  check(c.activeBg.includes('gradient'), '折叠态当前项整块点亮')
  check(c.menuScrollH > c.menuClientH, '折叠态内容超出时能滚（23 个入口必然超）')
  check(c.dividers.length >= 1 && c.dividers.every(d => d.visible),
    '折叠态用分隔线交代分组边界（不是把分组信息丢掉）',
    c.dividers.length + ' 条 · 宽 ' + (c.dividers[0] ? c.dividers[0].w + 'px' : '-'))
  check(c.actWidths.length >= 1 && c.actWidths.every(w => w <= 64),
    '折叠态底部动作也是图标方块（不超过侧栏宽度）', JSON.stringify(c.actWidths))
  check(c.iconOffset !== null &&
        Math.abs(c.iconOffset - (c.itemW - c.iconSize) / 2) <= 1,
    '折叠态图标在方块里居中', 'offset=' + c.iconOffset)

  // ---- 移动端抽屉：必须是同一套，不是「长得像」 ----
  console.log('▸ 移动端抽屉（390×844）')
  await page.setViewport({ width: 390, height: 844 })
  await sleep(1200)
  await page.evaluate(() => {
    const b = document.querySelector('.mobile-menu-btn')
    if (b) b.click()
  })
  await sleep(1500)
  const d = await page.evaluate(() => {
    const q = s => document.querySelector(s)
    const rect = el => (el ? el.getBoundingClientRect() : null)
    const drawer = q('.mobile-drawer')
    const brand = q('.mobile-drawer .brand')
    const items = [...document.querySelectorAll('.mobile-drawer .nav-menu .el-menu-item')]
    const groups = [...document.querySelectorAll('.mobile-drawer .nav-group-title')]
    const menu = q('.mobile-drawer .nav-menu')
    const svg = items[0] ? items[0].querySelector('svg') : null
    const dr = drawer ? rect(drawer) : null
    return {
      open: !!drawer,
      brandTitle: brand ? (brand.querySelector('.brand-title') || {}).innerText || '' : '',
      brandSub: brand ? (brand.querySelector('.brand-sub') || {}).innerText || '' : '',
      itemH: [...new Set(items.map(it => Math.round(rect(it).height)))],
      groupCount: groups.length,
      groupFont: groups[0] ? getComputedStyle(groups[0]).fontSize : '',
      // 量相对**菜单**的左沿，而不是相对抽屉外壳 ——
      // 抽屉外壳有 1px 边框，拿它当基准会凭空多出 1px
      iconGlyphX: svg && menu ? Math.round(svg.getBoundingClientRect().left - menu.getBoundingClientRect().left) : null,
      menuScrollW: menu ? menu.scrollWidth : null,
      menuClientW: menu ? menu.clientWidth : null,
      hasMore: menu ? menu.classList.contains('has-more-below') : null,
    }
  })
  check(d.open, '抽屉能打开')
  check(d.brandTitle.indexOf('知识工作台') >= 0, '抽屉里有品牌块（标题在）', d.brandTitle)
  // 抽屉里的副标题带 text-transform: uppercase（CSS 决定的），
  // innerText 拿回来是大写 —— 比内容时不能区分大小写
  check(d.brandSub.toLowerCase().indexOf('knowledge workbench') >= 0, '抽屉里有品牌副标题', d.brandSub)
  check(d.itemH.length === 1 && d.itemH[0] === 32,
    '抽屉里的菜单项与侧栏同高 32px（同一套设计）', JSON.stringify(d.itemH))
  check(d.groupCount >= 1, '抽屉里也分组（侧栏有的它也得有）', d.groupCount + ' 组')
  check(d.iconGlyphX === 21, '抽屉里的图标也在 21px 轴上（同一套设计）', String(d.iconGlyphX))
  check(d.menuScrollW <= d.menuClientW, '抽屉里没有横向滚动（内容没被裁掉）',
    d.menuScrollW + '/' + d.menuClientW)

  await browser.close()
  console.log(failed === 0 ? '\n全部通过 ✅' : '\n有 ' + failed + ' 项未通过 ❌')
  process.exit(failed === 0 ? 0 : 1)
}

main().catch(e => { console.error(e); process.exit(1) })
