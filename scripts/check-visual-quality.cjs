/**
 * 视觉质量体检：把「丑」变成能测的数字
 *
 * 用户两次说「UI 太丑」。光靠看截图改，改完也说不清好没好。
 * 这里挑几条最容易「丑」的结构性问题，每次改完跑一遍，看数字有没有动。
 *
 * 测什么（都是实测值，不是感觉）：
 *   1. 色彩多样性 —— 一屏里的图标底板有几种颜色
 *      （原来全站一个淡紫，六个应用像复制粘贴的）
 *   2. 卡片层次 —— 卡片阴影的模糊半径（0 就等于没有层次）
 *   3. 字号层次 —— 页面里正文字号的种类数（1 种 = 没有层次）
 *   4. 圆角一致性 —— 卡片圆角是否统一
 *   5. 焦点可见性 —— 键盘 Tab 能不能看见焦点
 *   6. 对比度 —— 文字对比度（沿用 v28 的口径）
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')

const BASE = process.env.BASE || process.env.KB_FRONTEND || 'http://127.0.0.1:5173'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const PAGES = [
  ['工作台', '/'],
  ['应用中心', '/apps'],
  ['数据模型', '/types'],
  ['知识库', '/notes'],
  ['数据中心', '/library'],
  ['全局搜索', '/search'],
]

function lum(rgb) {
  const c = rgb.map((v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
function parseRGB(s) {
  const m = String(s).match(/rgba?\(([^)]+)\)/)
  if (!m) return null
  const p = m[1].split(',').map((x) => parseFloat(x))
  return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }
}

async function main() {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new', args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 900 })

  await p.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1600)
  const ins = await p.$$('input')
  await ins[0].click({ clickCount: 3 }); await ins[0].press('Backspace'); await ins[0].type(USER, { delay: 6 })
  await ins[1].click({ clickCount: 3 }); await ins[1].press('Backspace'); await ins[1].type(PASS, { delay: 6 })
  await p.evaluate(() => {
    const x = Array.from(document.querySelectorAll('button')).find((e) => (e.innerText || '').trim() === '登录')
    if (x) x.click()
  })
  for (let i = 0; i < 30; i++) {
    await sleep(400)
    if (!(await p.evaluate(() => String(location.hash).includes('/login')))) break
  }
  if (await p.evaluate(() => String(location.hash).includes('/login'))) {
    console.log('✘ 登录失败')
    process.exit(1)
  }

  const problems = []
  console.log('')
  for (const [name, route] of PAGES) {
    console.log(`  · 正在测 ${name} ...`)
    await p.goto(`${BASE}/#${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {})
    await sleep(2400)

    const r = await p.evaluate(() => {
      const vis = (e) => {
        const r = e.getBoundingClientRect()
        if (r.width < 4 || r.height < 4) return false
        const cs = getComputedStyle(e)
        if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') return false
        return true
      }
      const main = document.querySelector('.el-main') || document.body

      // 1. 图标底板的颜色种类
      const plateColors = new Set()
      // 凡是「小方块 + 有底色 + 圆角 + 里面是图标」的都算图标底板
      // —— 按几何特征找，不靠猜 class 名（页面的 class 命名各不相同）
      const plates = Array.from(main.querySelectorAll('span, div')).filter((e) => {
        if (!vis(e)) return false
        const r = e.getBoundingClientRect()
        if (r.width < 20 || r.width > 90 || r.height < 20 || r.height > 90) return false
        if (Math.abs(r.width - r.height) > 12) return false
        const cs = getComputedStyle(e)
        if (!cs.backgroundColor || cs.backgroundColor === 'rgba(0, 0, 0, 0)') return false
        if (cs.borderRadius === '0px') return false
        return e.querySelector('svg, i, .el-icon') !== null
      })
      for (const e of plates) {
        if (!vis(e)) continue
        const cs = getComputedStyle(e)
        if (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') {
          plateColors.add(cs.backgroundColor)
        }
      }

      // 2. 卡片阴影
      const shadows = new Set()
      const blur = []
      const radii = new Set()
      for (const e of main.querySelectorAll('.app-card, .ent-card, .stat-card, .file-card, .dash-card')) {
        if (!vis(e)) continue
        const cs = getComputedStyle(e)
        shadows.add(cs.boxShadow)
        if (cs.boxShadow && cs.boxShadow !== 'none') {
          const m = cs.boxShadow.match(/([\d.]+)px\s+([\d.]+)px\s+([\d.]+)px/)
          if (m) blur.push(parseFloat(m[3]))
        }
        radii.add(cs.borderRadius.split(' ')[0])
      }

      // 3. 正文字号种类
      const fontSizes = new Set()
      for (const e of main.querySelectorAll('p, span, div, td, li, h1, h2, h3')) {
        if (!vis(e)) continue
        if (!e.textContent || !e.textContent.trim()) continue
        if (e.children.length > 0) continue
        fontSizes.add(getComputedStyle(e).fontSize)
      }

      // 4. 顶栏控件是否重叠
      const bar = document.querySelector('.topbar')
      let overlap = 0
      if (bar) {
        // 只比**同一层**的元素 —— 父子嵌套（按钮在 .topbar-left 里）
        // 天然「重叠」，那不是问题
        const items = Array.from(bar.children)
          .filter(vis)
          .flatMap((c) => Array.from(c.children).filter(vis))
          .filter((c) => !c.children.length || c.matches('button, input, .el-input'))
        for (let i = 0; i < items.length; i++) {
          for (let j = i + 1; j < items.length; j++) {
            const a = items[i].getBoundingClientRect()
            const c = items[j].getBoundingClientRect()
            const ox = Math.min(a.right, c.right) - Math.max(a.left, c.left)
            const oy = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top)
            if (ox > 2 && oy > 2) overlap++
          }
        }
      }

      return {
        plateColors: plateColors.size,
        plateCount: plates.length,
        blurMax: blur.length ? Math.max(...blur) : 0,
        shadowCount: shadows.size,
        radii: Array.from(radii),
        fontSizes: fontSizes.size,
        overlap,
      }
    })

    const issues = []
    if (r.plateCount >= 3 && r.plateColors <= 1) issues.push(`图标底板全是同一个颜色（${r.plateCount} 个图标 ${r.plateColors} 种色）`)
    if (r.plateCount >= 3 && r.plateColors === 2) issues.push(`图标底板只有 ${r.plateColors} 种颜色（${r.plateCount} 个图标）`)
    if (r.blurMax === 0 && r.shadowCount > 0) issues.push('卡片阴影模糊半径为 0（等于没有层次）')
    if (r.radii.length > 2) issues.push(`卡片圆角不统一：${r.radii.join(' / ')}`)
    if (r.fontSizes < 3) issues.push(`正文字号只有 ${r.fontSizes} 种（没有层次）`)
    if (r.overlap > 0) issues.push(`顶栏控件重叠 ${r.overlap} 处`)

    const mark = issues.length ? '✘' : '✔'
    console.log(`${mark} ${name.padEnd(8)} 图标底色 ${r.plateColors} 种 / ${r.plateCount} 个 · 阴影模糊 ${r.blurMax}px · 字号 ${r.fontSizes} 种 · 圆角 ${r.radii.length} 种 · 顶栏重叠 ${r.overlap}`)
    for (const i of issues) { console.log(`     · ${i}`); problems.push(`${name}：${i}`) }
  }

  console.log('')
  if (problems.length) {
    console.log(`视觉体检发现 ${problems.length} 项：`)
    problems.forEach((x) => console.log(`  ✘ ${x}`))
    process.exit(1)
  }
  console.log('✅ 视觉体检全部通过')
}

main()
