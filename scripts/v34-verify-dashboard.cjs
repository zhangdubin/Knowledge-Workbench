/**
 * 工作台视觉重做体检
 * ---------------------------------------------------------------------------
 * 查的不是「好不好看」，是用户能感知的结构问题：
 *   1. hero 是不是又变回「深色大块 + 下面一片白卡」
 *   2. 统计卡有没有主次（数字字号拉不开 = 还是四个一样）
 *   3. 快捷入口有没有主次（10 个一样大 = 用户不知道点哪个）
 *   4. 图标底板是不是语义色（一轮马卡龙就是没有语义）
 *   5. 两栏比例是不是失衡
 *   6. 卡片有没有层次（阴影只有一层 = 整屏平）
 *
 * 用法：BASE=http://localhost:5173 node scripts/v34-verify-dashboard.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const BASE = process.env.BASE || 'http://localhost:5173'

let failed = 0
let total = 0
function check(ok, label, detail = '') {
  total++
  if (!ok) failed++
  console.log(`  ${ok ? '✔' : '✘'} ${label}${detail ? `　${detail}` : ''}`)
}

// 全局强调色板（main.css 里的定义）
const ACCENTS = {
  blue: 'rgb(59, 111, 212)', teal: 'rgb(15, 139, 141)', green: 'rgb(47, 143, 78)',
  amber: 'rgb(179, 118, 15)', orange: 'rgb(201, 106, 30)', red: 'rgb(192, 74, 69)',
  violet: 'rgb(107, 75, 196)', pink: 'rgb(181, 64, 126)', slate: 'rgb(90, 100, 120)',
}

async function login(p) {
  await p.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1500)
  const ins = await p.$$('input')
  await ins[0].click({ clickCount: 3 }); await ins[0].press('Backspace'); await ins[0].type('admin', { delay: 5 })
  await ins[1].click({ clickCount: 3 }); await ins[1].press('Backspace'); await ins[1].type('Kb@2026admin', { delay: 5 })
  await p.evaluate(() => {
    const x = Array.from(document.querySelectorAll('button')).find((e) => (e.innerText || '').trim() === '登录')
    x && x.click()
  })
  for (let i = 0; i < 30; i++) {
    await sleep(400)
    if (!(await p.evaluate(() => location.hash.includes('/login')))) break
  }
}

async function main() {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new', args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 900 })
  await login(p)
  await p.goto(`${BASE}/#/`, { waitUntil: 'networkidle2' })
  await sleep(2600)
  await p.evaluate(() => {
    const x = Array.from(document.querySelectorAll('button')).find((e) => (e.innerText || '').trim() === '稍后')
    x && x.click()
  })
  await sleep(700)

  const d = await p.evaluate(() => {
    const px = (el) => parseFloat(getComputedStyle(el).fontSize)
    const box = (el) => { const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) } }
    const hero = document.querySelector('.hero')
    const stats = Array.from(document.querySelectorAll('.dash-stats .stat-card'))
    const quick = Array.from(document.querySelectorAll('.quick-item'))
    const minis = Array.from(document.querySelectorAll('.quick-mini'))
    const row = document.querySelector('.dashboard-row')
    const cards = row ? Array.from(row.children) : []
    return {
      hero: {
        ...box(hero),
        h1Size: px(hero.querySelector('h1')),
        color: getComputedStyle(hero).color,
        bg: getComputedStyle(hero).backgroundImage,
        shadow: getComputedStyle(hero).boxShadow,
      },
      stats: stats.map((c) => ({
        ...box(c),
        label: c.querySelector('.label').innerText.trim(),
        valueSize: px(c.querySelector('.value')),
        iconBg: getComputedStyle(c.querySelector('.icon')).backgroundColor,
        iconFg: getComputedStyle(c.querySelector('.icon')).color,
        shadow: getComputedStyle(c).boxShadow,
      })),
      quick: quick.map((q) => ({
        ...box(q),
        name: q.querySelector('.quick-name').innerText.trim(),
        iconFg: getComputedStyle(q.querySelector('.quick-icon')).color,
        iconBg: getComputedStyle(q.querySelector('.quick-icon')).backgroundColor,
      })),
      minis: minis.map((m) => ({ ...box(m), name: m.innerText.trim() })),
      row: row ? { cols: getComputedStyle(row).gridTemplateColumns.split(' ').map(parseFloat) } : null,
      cards: cards.map((c) => ({ ...box(c), title: c.querySelector('.card-title-text')?.innerText.trim() })),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    }
  })

  console.log(`\n工作台体检 · 1440×900\n`)

  // 1. hero 必须是浅色大卡片，不能又是深色块
  check(!/rgba\(20, 22, 31|#14161f|#1f2131/.test(d.hero.bg), 'hero 不是深色块', d.hero.bg.slice(0, 60))
  check(d.hero.color === 'rgb(23, 24, 29)', 'hero 文字是深色（浅底深字）', d.hero.color)
  check(d.hero.h1Size >= 32, 'hero 标题够大', `${d.hero.h1Size}px`)
  check(d.hero.shadow.split('px').length >= 4, 'hero 有两层阴影（有厚度）', d.hero.shadow.slice(0, 60))

  // 2. 统计卡主次
  const lead = d.stats.find((s) => s.label === '数据模型')
  const others = d.stats.filter((s) => s.label !== '数据模型')
  check(d.stats.length === 4, '统计卡还是 4 张', `${d.stats.length} 张`)
  check(lead && lead.valueSize >= 38, '主指标数字够大', `${lead && lead.valueSize}px`)
  check(others.every((s) => s.valueSize <= 30), '次要指标收着', others.map((s) => `${s.label} ${s.valueSize}px`).join(' / '))
  check(lead && others.every((s) => lead.w > s.w), '主指标卡片更宽', lead ? `${lead.w}px vs ${others.map((s) => s.w).join('/')}px` : '')
  check(lead && others.every((s) => lead.h >= s.h), '主指标卡片不矮于次要', lead ? `${lead.h}px` : '')

  // 3. 图标底板是语义色板里的颜色，且四张互不相同
  const fgList = d.stats.map((s) => s.iconFg)
  check(fgList.every((c) => Object.values(ACCENTS).includes(c)), '图标底板用的是 accent 色板', fgList.join(' '))
  check(new Set(fgList).size === 4, '四张统计卡颜色互不相同', `${new Set(fgList).size} 种`)

  // 4. 快捷入口主次
  check(d.quick.length === 3, '主入口 3 个（常用）', `${d.quick.length} 个`)
  check(d.quick.every((q) => q.h >= 64), '主入口是大块', d.quick.map((q) => `${q.name} ${q.w}×${q.h}`).join(' / '))
  check(d.minis.length === 7, '次入口 7 个（罕用）', `${d.minis.length} 个`)
  check(d.minis.every((m) => m.h <= 40), '次入口收成小标签', d.minis.map((m) => `${m.name} ${m.w}×${m.h}`).join(' / '))
  check(d.quick.every((q) => q.h > Math.max(...d.minis.map((m) => m.h))), '主入口明显大于次入口')
  const quickFg = d.quick.map((q) => q.iconFg)
  check(quickFg.every((c) => Object.values(ACCENTS).includes(c)), '主入口图标是 accent 色板', quickFg.join(' '))

  // 5. 两栏比例
  if (d.row) {
    const [a, b] = d.row.cols
    const ratio = a / b
    check(ratio > 0.9 && ratio < 1.35, '两栏比例均衡', `${Math.round(a)} / ${Math.round(b)}（${ratio.toFixed(2)}）`)
    const heights = d.cards.map((c) => c.h)
    check(Math.max(...heights) - Math.min(...heights) < 160, '两栏高度差不太大', heights.join(' / '))
  }

  // 6. 卡片阴影有层次
  check(d.stats.every((s) => s.shadow.split('px').length >= 4), '统计卡阴影不止一层', d.stats[0].shadow.slice(0, 60))

  // 7. 横向不溢出
  check(d.overflow === 0, '桌面端无横向溢出', `溢出 ${d.overflow}px`)

  // ---- 手机端 ----
  await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  await p.goto(`${BASE}/#/`, { waitUntil: 'networkidle2' })
  await sleep(2400)
  const m = await p.evaluate(() => {
    const box = (el) => { const r = el.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) } }
    return {
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      hero: box(document.querySelector('.hero')),
      stats: Array.from(document.querySelectorAll('.dash-stats .stat-card')).map(box),
      quick: Array.from(document.querySelectorAll('.quick-item')).map(box),
      minis: Array.from(document.querySelectorAll('.quick-mini')).map(box),
    }
  })
  console.log('\n  —— 390×844 ——')
  check(m.overflow === 0, '手机端无横向溢出', `溢出 ${m.overflow}px`)
  check(m.hero.w <= 366 && m.hero.h < 260, 'hero 在手机上没失控', `${m.hero.w}×${m.hero.h}`)
  check(m.stats.length === 4 && m.stats[0].w > 300, '主指标在手机上占满一行', `${m.stats[0].w}px`)
  check(m.stats.slice(1).every((s) => s.w <= 130 && s.h <= 80), '次要指标三个并排且够矮', m.stats.slice(1).map((s) => `${s.w}×${s.h}`).join(' / '))
  check(m.stats[0].h <= 120, '主指标在手机上不过高', `${m.stats[0].h}px`)
  check(m.quick.every((q) => q.w > 300), '主入口在手机上占满一行', m.quick.map((q) => q.w).join(' / '))
  check(m.minis.every((x) => x.h >= 28), '次入口在手机上够得着（≥28px）', m.minis.map((x) => x.h).join(' / '))

  await b.close()
  console.log(`\n共 ${total} 项断言，${failed} 项未通过`)
  process.exit(failed ? 1 : 0)
}
main().catch((e) => { console.error(e); process.exit(1) })
