/**
 * AI 助理回答的 Markdown 排版验证（端到端，真实问答链路）
 *
 * 背景：AI 气泡原本是 white-space: pre-wrap 的纯文本，
 * 模型给的 Markdown 表格被原样吐出来 —— 管道符和空格糊成一团，几乎没法读。
 * 本次给 AI 回答接入 utils/md.js 的 renderMarkdown + 全局 .md-body 样式。
 *
 * 这里走真实链路：打开 AI 助理 → 提问 → 断言回答里的 Markdown 真的变成了
 * <table>/<ul>/<h*>/<pre>，且浅色与深色两套主题下文字都读得清。
 *
 *   KB_SESSION_TOKEN=xxx node scripts/verify-agent-markdown.cjs
 *
 * 渲染器本身的逐条断言在 verify-markdown-unit.mjs（不依赖网络与模型）。
 */
const { createRequire } = require('module')
const fs = require('fs')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = process.env.KB_SHOT_DIR || '/tmp/kb-agent-md'
const QUESTION = process.env.KB_Q || '用表格列出系统里所有数据模型：模型、应用、字段数、记录数'

const sleep = ms => new Promise(r => setTimeout(r, ms))
let pass = 0
const fails = []
const ok = (cond, label, extra) => {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fails.push(label); console.log(`  ✗ ${label}${extra !== undefined ? ' → ' + extra : ''}`) }
}

/** 相对亮度，用来判断「深字浅底 / 浅字深底」 */
const lum = s => {
  const m = String(s).match(/\d+(\.\d+)?/g)
  if (!m || m.length < 3) return null
  const [r, g, b] = m.slice(0, 3).map(Number)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255
}
/** 背景可能是 rgba(0,0,0,0)（透明），需要往上找到第一个不透明的底色 */
const probe = sel => {
  const el = document.querySelector(sel)
  if (!el) return null
  const cs = getComputedStyle(el)
  let bg = cs.backgroundColor, node = el
  while ((!bg || /rgba?\([^)]*,\s*0\s*\)/.test(bg)) && node.parentElement) {
    node = node.parentElement
    bg = getComputedStyle(node).backgroundColor
  }
  return { color: cs.color, bg, font: cs.fontSize }
}

async function main() {
  if (!TOKEN) { console.error('缺少 KB_SESSION_TOKEN'); process.exit(1) }
  fs.mkdirSync(OUT, { recursive: true })

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1500, height: 980, deviceScaleFactor: 2 })
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(`console: ${m.text()}`) })
  page.on('pageerror', e => errors.push(`pageerror: ${e}`))
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })

  console.log('\n== 1. 打开 AI 助理抽屉 ==')
  await page.goto(`${FE}/`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('button[title^="AI 助理"]', { timeout: 15000 })
  await page.click('button[title^="AI 助理"]')
  await page.waitForSelector('.agent-input textarea', { visible: true, timeout: 10000 })
  ok(true, '抽屉已打开')

  console.log(`\n== 2. 提问：${QUESTION} ==`)
  await page.type('.agent-input textarea', QUESTION)
  await page.click('.agent-input button')
  await page.waitForFunction(
    () => !!document.querySelector('.agent-list .msg.assistant .md-body'),
    { timeout: 150000, polling: 500 },
  )
  // 等模型把话说完：内容连续 3 秒不再变化
  let last = '', stableSince = Date.now()
  while (Date.now() - stableSince < 3000) {
    const now = await page.evaluate(() =>
      (document.querySelector('.agent-list .msg.assistant .md-body') || {}).innerText || '')
    if (now !== last) { last = now; stableSince = Date.now() }
    await sleep(400)
  }

  console.log('\n== 3. 断言：Markdown 真的被渲染成标签 ==')
  const info = await page.evaluate(() => {
    const root = document.querySelector('.agent-list .msg.assistant .md-body')
    const wrap = root?.querySelector('.md-table-wrap')
    const t = wrap?.querySelector('table')
    return {
      hasRoot: !!root,
      html: root ? root.innerHTML : '',
      text: root ? root.innerText : '',
      tags: root ? {
        h: root.querySelectorAll('h3,h4,h5,h6').length,
        ul: root.querySelectorAll('ul').length,
        ol: root.querySelectorAll('ol').length,
        li: root.querySelectorAll('li').length,
        table: root.querySelectorAll('table').length,
        pre: root.querySelectorAll('pre').length,
        blockquote: root.querySelectorAll('blockquote').length,
        strong: root.querySelectorAll('strong').length,
        code: root.querySelectorAll('code').length,
      } : {},
      cols: t ? [...t.querySelectorAll('thead th')].map(x => x.textContent.trim()) : [],
      rows: t ? [...t.querySelectorAll('tbody tr')].map(tr =>
        [...tr.querySelectorAll('td')].map(td => td.textContent.trim())) : [],
      aligns: t ? [...(t.querySelector('tbody tr')?.querySelectorAll('td') || [])]
        .map(td => getComputedStyle(td).textAlign) : [],
      scroll: wrap ? { sw: wrap.scrollWidth, cw: wrap.clientWidth } : null,
      light: {
        body: null,
        cell: t ? { color: getComputedStyle(t.querySelector('tbody td')).color,
                    bg: getComputedStyle(t.querySelector('tbody td')).backgroundColor } : null,
        th: t ? { bg: getComputedStyle(t.querySelector('thead th')).backgroundColor } : null,
      },
    }
  })

  ok(info.hasRoot, 'AI 回答挂在 .md-body 上（不再是裸 pre-wrap 文本）')
  ok(/\|\s*-{3,}|^\s*\*\*/m.test(info.text) === false,
    '页面上看不到 |---|---| / ** 这类原始 Markdown 记号')
  const renderedAny = info.tags.h + info.tags.ul + info.tags.ol + info.tags.li + info.tags.table
  ok(renderedAny > 0, `生成了真实标签：h=${info.tags.h} ul=${info.tags.ul} ol=${info.tags.ol} li=${info.tags.li} table=${info.tags.table}`)
  ok(info.tags.table >= 1, '表格类回答被渲染成 <table>')
  if (info.tags.table) {
    ok(info.cols.length >= 3, `表头解析出 ${info.cols.length} 列：${info.cols.join(' | ')}`)
    ok(info.rows.length >= 5, `渲染出 ${info.rows.length} 行数据`)
    ok(info.rows.every(r => r.length === info.cols.length), '每行列数与表头一致')
    ok(info.rows.some(r => r.join('').includes('客户')), '第一行数据没被当成分隔行吞掉')
    ok(info.aligns.filter(a => a === 'right').length >= 1, `数字列右对齐：${JSON.stringify(info.aligns)}`)
    info.rows.slice(0, 3).forEach(r => console.log('    ·', r.join(' | ')))
    console.log(`    表格宽 ${info.scroll.sw}px / 可视 ${info.scroll.cw}px（溢出时容器内横向滚动）`)
  } else {
    console.log('    （本条回答模型未用表格，跳过表格断言）')
  }

  const readability = async tag => {
    const r = await page.evaluate(`(${probe.toString()})('.agent-list .msg.assistant .md-body')`)
    const t = lum(r.color), b = lum(r.bg)
    ok(t !== null && b !== null && Math.abs(t - b) > 0.25,
      `${tag}：正文对比清晰（字 ${r.color} / 底 ${r.bg}，${t > b ? '浅字深底' : '深字浅底'}）`,
      `${t} vs ${b}`)
    return r
  }

  console.log('\n== 4. 浅色主题 ==')
  await page.screenshot({ path: `${OUT}/agent-md-light.png` })
  console.log(`  截图 ${OUT}/agent-md-light.png`)
  await readability('浅色')

  console.log('\n== 5. 深色主题 ==')
  // 抽屉自带遮罩，真实鼠标点击会被挡住 —— 直接派发 click 给按钮本身
  const found = await page.evaluate(() => {
    const btn = document.querySelector('button[title="切换主题"]')
    if (btn) btn.click()
    return !!btn
  })
  ok(found, '找到主题切换按钮')
  await sleep(900)
  const isDark = await page.evaluate(() => document.documentElement.classList.contains('dark'))
  ok(isDark, '深色主题已启用')
  await page.screenshot({ path: `${OUT}/agent-md-dark.png` })
  console.log(`  截图 ${OUT}/agent-md-dark.png`)
  await readability('深色')
  if (info.tags.table) {
    const darkBg = await page.evaluate(`
      (() => { const t = document.querySelector('.agent-list .msg.assistant .md-body table')
        return { th: getComputedStyle(t.querySelector('thead th')).backgroundColor,
                 cell: getComputedStyle(t.querySelector('tbody td')).backgroundColor,
                 border: getComputedStyle(t.querySelector('thead th')).borderBottomColor } })()`)
    const same = lum(darkBg.th) === lum(darkBg.cell)
    ok(!same, `深色下表头/数据行仍有底色区分（表头 ${darkBg.th} / 行 ${darkBg.cell}）`)
    ok(lum(darkBg.border) !== null, `深色下单元格边框可见（${darkBg.border}）`)
  }
  // 还原主题，别把用户的界面留在深色
  await page.evaluate(() => document.querySelector('button[title="切换主题"]')?.click())
  await sleep(400)

  ok(errors.length === 0, '无控制台报错', errors.slice(0, 3).join(' ; '))

  console.log('\n---- 渲染后的 HTML（截断 900 字）----')
  console.log(info.html.slice(0, 900))
  await browser.close()

  console.log(`\n==== 结果：${pass} 通过 / ${fails.length} 失败 ====`)
  if (fails.length) { fails.forEach(f => console.log('  未通过：' + f)); process.exit(1) }
}

main().catch(e => { console.error(e); process.exit(1) })
