/**
 * 左侧导航栏的排版体检
 *
 * 为什么要有这个脚本：
 *   侧栏好不好看，眼睛一看就知道；但「一屏放不放得下」「对比度够不够」
 *   靠眼睛看不出来 —— 得量。
 *   这台机器上侧栏有 23 个入口、4 个分组，
 *   排版松一点，800px 高的笔记本屏上就得往下滚半屏才够得着「系统设置」，
 *   看着就「挤」「乱」「丑」。
 *
 * 这里量的都是能判对错的东西：
 *   · 菜单内容高度 vs 可视高度（溢出多少像素）
 *   · 图标与文字的左对齐轴是否一致
 *   · 分组标题、菜单项、正文的对比度（WCAG AA：正文 ≥ 4.5:1）
 *   · 折叠态与展开态的宽度、图标方块尺寸
 *
 * 用法：node scripts/kb-verify-nav-layout.cjs
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
      iconColor: cs(icons[0]).color,
      activeBgImage: cs(active).backgroundImage,
      activeColor: cs(active).color,
      hasFade: (() => {
        // 注意：要显式传第二个参数取伪元素 —— getComputedStyle(el) 拿到的是元素本身，
        // 取 ::after 得写成 getComputedStyle(el, '::after')。
        const a = getComputedStyle(menu, '::after')
        return a.content !== 'none' && a.position === 'sticky' && a.height !== '0px'
      })(),
      itemCount: items.length,
      groupCount: groups.length,
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
  check(m.hasFade, '菜单底部有渐隐（被截断的一行看起来是「下面还有」）')
  check(m.itemH.length === 1 && m.itemH[0] <= 34, '菜单项高度统一且收紧', JSON.stringify(m.itemH))
  check(m.iconXs.length === 1, '所有图标在同一条左对齐轴上', 'x=' + JSON.stringify(m.iconXs))
  check(m.footerH <= 100, '底部区不超过 100px（≈ 三个菜单项，别占掉导航的空间）', m.footerH + 'px')
  check(cr(m.itemColor) >= 4.5, '菜单项正文对比度 ≥ 4.5:1', cr(m.itemColor).toFixed(2) + ':1')
  check(cr(m.groupColor) >= 4.5, '分组标题对比度 ≥ 4.5:1', cr(m.groupColor).toFixed(2) + ':1')
  check(cr(m.brandSubColor) >= 4.5, '品牌副标题对比度 ≥ 4.5:1', cr(m.brandSubColor).toFixed(2) + ':1')
  check(cr(m.iconColor) >= 3, '图标对比度 ≥ 3:1（图形元素的底线）', cr(m.iconColor).toFixed(2) + ':1')
  check(cr(m.activeColor) >= 4.5, '当前项文字对比度 ≥ 4.5:1', cr(m.activeColor).toFixed(2) + ':1')
  check(m.activeBgImage.includes('gradient'), '当前项有底色（不是只靠字重区分）')

  const overflow = m.menuScrollH - m.menuClientH
  console.log('  溢出 ' + overflow + 'px —— 800px 高的屏上露不全是正常的，但要能滚、且看得出能滚')
  check(overflow < 400, '溢出控制在 400px 内（原来是 376+）', overflow + 'px')

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
    const rect = el => el.getBoundingClientRect()
    const menu = q('.nav-menu')
    const item = q('.nav-menu .el-menu-item')
    const active = q('.nav-menu .el-menu-item.is-active')
    return {
      w: Math.round(rect(q('.sidebar')).width),
      itemW: Math.round(rect(item).width),
      itemH: Math.round(rect(item).height),
      menuScrollH: menu.scrollHeight,
      menuClientH: menu.clientHeight,
      activeBg: getComputedStyle(active).backgroundImage,
      activeIconColor: getComputedStyle(active.querySelector('.el-icon')).color,
    }
  })
  console.log('  ' + c.w + 'px 宽，图标方块 ' + c.itemW + '×' + c.itemH)
  check(c.w === 64, '折叠宽度 64px', c.w + 'px')
  check(c.itemW === c.itemH, '折叠态图标方块是正方形', c.itemW + '×' + c.itemH)
  check(c.activeBg.includes('gradient'), '折叠态当前项整块点亮')
  check(c.menuScrollH > c.menuClientH, '折叠态内容超出时能滚（23 个入口必然超）')

  await browser.close()
  console.log(failed === 0 ? '\n全部通过 ✅' : '\n有 ' + failed + ' 项未通过 ❌')
  process.exit(failed === 0 ? 0 : 1)
}

main().catch(e => { console.error(e); process.exit(1) })
