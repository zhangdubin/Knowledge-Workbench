/**
 * v15 诊断：按钮文字对比度 + 移动端适配
 *
 * 1) 对比度：抓取页面上所有可见按钮/链接的文字色与背景色，算 WCAG 对比度，
 *    标出 < 4.5（普通文字）或 < 3（大字/图标）的项。
 * 2) 移动端：390x844 视口下遍历关键页面，检测横向溢出（scrollWidth > clientWidth）
 *    以及超出视口右边界的元素，并截图。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')
const S = require('./lib/session.cjs')

const FE = 'http://127.0.0.1:8082'
const OUT = '/Volumes/Samsung/poc/知识库/kb-workbench/docs/screenshots/v15-audit'
fs.mkdirSync(OUT, { recursive: true })

const PAGES = [
  ['', 'dashboard'],
  ['library', 'library'],
  ['notes', 'notes'],
  ['apps', 'apps'],
  ['types', 'types'],
  ['relations', 'relations'],
  ['graph', 'graph'],
  ['knowledge/graph', 'kgraph'],
  ['search', 'search'],
  ['guide', 'guide'],
  ['ai-settings', 'ai'],
]

// ---- 浏览器内执行的对比度采集 ----
function collectContrast() {
  const parseRGB = (s) => {
    const m = (s || '').match(/rgba?\(([^)]+)\)/)
    if (!m) return null
    const p = m[1].split(',').map(x => parseFloat(x.trim()))
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
  }
  const lum = ({ r, g, b }) => {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  // 单个元素自身的有效背景：先看渐变（取色标均值），再看纯色
  const bgOf = (el) => {
    const st = getComputedStyle(el)
    const bi = st.backgroundImage
    if (bi && bi !== 'none') {
      const stops = (bi.match(/rgba?\([^)]+\)/g) || [])
        .map(parseRGB)
        .filter(c => c && c.a > 0.2)
      if (stops.length) {
        const s = stops.reduce((a, c) => ({ r: a.r + c.r, g: a.g + c.g, b: a.b + c.b }),
          { r: 0, g: 0, b: 0 })
        return { r: s.r / stops.length, g: s.g / stops.length, b: s.b / stops.length }
      }
    }
    const c = parseRGB(st.backgroundColor)
    return c && c.a > 0.5 ? c : null
  }
  // 逐级向上找到第一个不透明（或渐变）背景
  const effBg = (el) => {
    let n = el
    while (n && n !== document.documentElement) {
      const c = bgOf(n)
      if (c) return c
      n = n.parentElement
    }
    const c = parseRGB(getComputedStyle(document.body).backgroundColor)
    return c || { r: 255, g: 255, b: 255 }
  }
  const ratio = (a, b) => {
    const l1 = lum(a), l2 = lum(b)
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
  }

  const out = []
  const nodes = document.querySelectorAll(
    'button, .el-button, a.el-link, .el-tag, .nav-item, .tab, [class*="btn"]'
  )
  for (const el of nodes) {
    const r = el.getBoundingClientRect()
    if (r.width < 4 || r.height < 4) continue
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) < 0.15) continue
    const fg = parseRGB(st.color)
    if (!fg) continue
    const bg = effBg(el)
    // 文字与背景都半透明时难以精确判定，跳过纯透明背景
    const cr = ratio(fg, bg)
    const size = parseFloat(st.fontSize) || 14
    const bold = (parseInt(st.fontWeight, 10) || 400) >= 600
    const large = size >= 24 || (size >= 18.66 && bold)
    const need = large ? 3 : 4.5
    if (cr < need) {
      out.push({
        text: (el.innerText || '').trim().slice(0, 24) || el.className.toString().slice(0, 40),
        cls: el.className.toString().slice(0, 70),
        color: st.color,
        bg: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`,
        size: Math.round(size),
        ratio: Math.round(cr * 100) / 100,
        need,
      })
    }
  }
  return out
}

// ---- 浏览器内执行的溢出采集 ----
function collectOverflow() {
  const vw = document.documentElement.clientWidth
  const bad = []
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect()
    if (r.width < 8 || r.height < 8) continue
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || st.display === 'none') continue
    if (r.right > vw + 1.5) {
      bad.push({
        tag: el.tagName.toLowerCase(),
        cls: el.className.toString().slice(0, 60),
        right: Math.round(r.right),
        width: Math.round(r.width),
      })
    }
  }
  return {
    docScroll: document.documentElement.scrollWidth,
    vw,
    overflow: document.documentElement.scrollWidth - vw,
    offenders: bad.slice(0, 12),
  }
}

;(async () => {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })

  for (const mode of ['light', 'dark']) {
    const p = await b.newPage()
    await p.setViewport({ width: 1440, height: 950, deviceScaleFactor: 1 })
    await p.goto(FE, { waitUntil: 'networkidle0' })
    await p.evaluate(m => document.documentElement.classList.toggle('dark', m === 'dark'), mode)

    const seen = new Map()
    for (const [path, name] of PAGES) {
      await p.goto(FE + '/#' + path, { waitUntil: 'networkidle0' })
      await p.evaluate(m => document.documentElement.classList.toggle('dark', m === 'dark'), mode)
      await new Promise(r => setTimeout(r, 1300))
      const rows = await p.evaluate(collectContrast)
      for (const row of rows) {
        const key = row.cls + '|' + row.color + '|' + row.bg
        if (!seen.has(key)) seen.set(key, { ...row, pages: [] })
        seen.get(key).pages.push(name)
      }
    }
    console.log(`\n########## 对比度不足（${mode}）##########`)
    if (!seen.size) console.log('  ✅ 无')
    for (const v of [...seen.values()].sort((a, b) => a.ratio - b.ratio)) {
      console.log(`  ✗ ${v.ratio} (需≥${v.need}) 「${v.text}」 ${v.color} on ${v.bg} [${v.pages.join(',')}]`)
      console.log(`      class="${v.cls}"`)
    }
    await p.close()
  }

  // ---- 移动端 ----
  const p = await b.newPage()
  await p.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true })
  await p.goto(FE, { waitUntil: 'networkidle0' })

  const report = []
  for (const [path, name] of PAGES) {
    await p.goto(FE + '/#' + path, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1400))
    const o = await p.evaluate(collectOverflow)
    report.push({ name, ...o })
    await p.screenshot({ path: `${OUT}/m-${name}.png`, fullPage: false })
  }
  console.log('\n########## 移动端 390px 横向溢出 ##########')
  for (const r of report) {
    const flag = r.overflow > 1 ? '✗' : '✅'
    console.log(`  ${flag} ${r.name.padEnd(11)} overflow=${r.overflow}px (doc=${r.docScroll} vw=${r.vw})`)
    for (const o of r.offenders) console.log(`        -> <${o.tag} class="${o.cls}"> right=${o.right} w=${o.width}`)
  }

  await b.close()
})()
