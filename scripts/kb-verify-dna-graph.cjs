// ============================================================
// DNA 双螺旋图谱的可读性验收
//
// 为什么单独写这个脚本：
//   这张图的问题不是「功能坏了」，而是「读不动」——
//   画布 1256×1280、视口只有 900 高，一屏看不全；
//   右链 50 个节点平铺成一面墙，行距 24px；
//   54 个基因默认只画 12 个；
//   点一下节点，连它自己的出处都一起变暗。
//   这些都不报错，回归测试抓不到，只能把「读起来是什么样」写成断言。
//
// 用法：node scripts/kb-verify-dna-graph.cjs
// ============================================================
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const fs = require('fs')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const URL = 'http://127.0.0.1:8082/#/dna'
const TOKEN = fs.readFileSync('/tmp/kb-tok.txt', 'utf8').trim()

let pass = 0
let fail = 0
const fails = []
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  ✓ ' + name) }
  else { fail++; fails.push(name + (detail ? '（' + detail + '）' : '')); console.log('  ✗ ' + name + (detail ? '（' + detail + '）' : '')) }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000 })
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })
  const errs = []
  page.on('pageerror', (e) => errs.push(e.message))
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text().slice(0, 160)) })

  await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(9000)

  console.log('\n▶ 默认视图（聚焦）')
  const m = await page.evaluate(() => {
    const labels = Array.from(document.querySelectorAll('.dg-lbl'))
    const canvas = document.querySelector('.dg-canvas canvas')
    const cr = canvas ? canvas.getBoundingClientRect() : { width: 0, height: 0 }
    const boxes = labels.map((e) => {
      const r = e.getBoundingClientRect()
      return { x: r.x, y: r.y, w: r.width, h: r.height, cls: e.className }
    })
    let overlaps = 0
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j]
        const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)
        const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)
        if (ox > 1 && oy > 1) overlaps++
      }
    }
    const stats = (document.querySelector('.dg-stats') || {}).textContent || ''
    const scopeBtns = Array.from(document.querySelectorAll('.dg-bar .el-radio-button')).map((b) => b.innerText.trim())
    return {
      labels: labels.length,
      genes: labels.filter((e) => e.className.includes('dg-lbl-gene')).length,
      evidence: labels.filter((e) => !e.className.includes('dg-lbl-gene')).length,
      canvasH: Math.round(cr.height),
      canvasW: Math.round(cr.width),
      overlaps,
      stats: stats.trim(),
      scopeBtns,
    }
  })
  ok('默认是聚焦模式（工具条有「聚焦 / 全链」）', m.scopeBtns.includes('聚焦') && m.scopeBtns.includes('全链'))
  ok('一屏能看完（画布高 ≤ 900）', m.canvasH <= 900, '画布高 ' + m.canvasH)
  ok('标签总数比改版前少（≤ 40）', m.labels <= 40, m.labels + ' 个')
  ok('右链不再是一面墙（证据节点 ≤ 24）', m.evidence <= 24, m.evidence + ' 个')
  ok('左右两链长度不再悬殊（差 ≤ 12）', Math.abs(m.genes - m.evidence) <= 12, '基因 ' + m.genes + ' / 证据 ' + m.evidence)
  ok('标签没有互相压字', m.overlaps === 0, m.overlaps + ' 处重叠')
  ok('统计行说明了基因显示了多少', /基因 \d+\/\d+/.test(m.stats), m.stats)

  console.log('\n▶ 选中一个基因：它的出处必须还亮着')
  const sel = await page.evaluate(async () => {
    const g = document.querySelector('.dg-lbl-gene')
    const gname = g.querySelector('.dg-lbl-text').textContent.trim()
    g.click()
    await new Promise((r) => setTimeout(r, 1000))
    const bright = Array.from(document.querySelectorAll('.dg-lbl:not(.is-dim)'))
      .map((e) => e.querySelector('.dg-lbl-text').textContent.trim())
    const detail = document.querySelector('.dg-detail')
    return { gname, bright, dimmed: document.querySelectorAll('.dg-lbl.is-dim').length,
      detail: detail ? detail.innerText.replace(/\n+/g, ' | ') : '' }
  })
  ok('选中的基因自己是亮的', sel.bright.includes(sel.gname))
  ok('它的出处也还亮着（不再被一起暗掉）', sel.bright.length >= 2, '亮的只有 ' + sel.bright.length + ' 个：' + sel.bright.join(' / '))
  ok('详情面板说得出它的出处', /出处/.test(sel.detail))

  console.log('\n▶ 折叠：文件徽章能展开章节')
  const badge = await page.evaluate(async () => {
    const b = document.querySelector('.dg-lbl-badge')
    if (!b) return { has: false }
    const before = document.querySelectorAll('.dg-lbl').length
    b.click()
    await new Promise((r) => setTimeout(r, 1500))
    return { has: true, before, after: document.querySelectorAll('.dg-lbl').length,
      sections: document.querySelectorAll('.dg-lbl-section').length }
  })
  ok('文件上有徽章（写明下面还有几个）', badge.has)
  ok('点徽章能展开出章节', !badge.has || badge.after > badge.before, badge.before + ' → ' + badge.after)

  console.log('\n▶ 搜索能搜到当前没显示的基因')
  const search = await page.evaluate(async () => {
    const input = document.querySelector('.dg-search input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, '部署')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await new Promise((r) => setTimeout(r, 1500))
    const hit = document.querySelector('.dg-search-hit')
    const n = document.querySelectorAll('.dg-lbl').length
    setter.call(input, '')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await new Promise((r) => setTimeout(r, 1000))
    return { hit: hit ? hit.textContent.trim() : '', n }
  })
  ok('搜得到东西', /\d+ 处命中/.test(search.hit), search.hit)
  ok('搜出来的结果不是空的', search.n > 0, search.n + ' 个标签')

  console.log('\n▶ 全链模式还能用')
  const all = await page.evaluate(async () => {
    const btn = Array.from(document.querySelectorAll('.dg-bar .el-radio-button')).find((b) => b.innerText.trim() === '全链')
    btn.click()
    await new Promise((r) => setTimeout(r, 2200))
    const c = document.querySelector('.dg-canvas canvas').getBoundingClientRect()
    const n = document.querySelectorAll('.dg-lbl').length
    const stats = (document.querySelector('.dg-stats') || {}).textContent || ''
    const back = Array.from(document.querySelectorAll('.dg-bar .el-radio-button')).find((b) => b.innerText.trim() === '聚焦')
    back.click()
    await new Promise((r) => setTimeout(r, 1500))
    return { n, h: Math.round(c.height), stats: stats.trim() }
  })
  ok('全链模式把全部证据摊开（≥ 50 个标签）', all.n >= 50, all.n + ' 个')

  console.log('\n▶ 页面没有报错')
  ok('没有 JS 报错', errs.length === 0, errs.slice(0, 2).join(' / '))

  await browser.close()

  console.log('\n共 ' + (pass + fail) + ' 项检查，失败 ' + fail + ' 项')
  if (fail) {
    console.log('失败项：')
    fails.forEach((f) => console.log('  - ' + f))
    process.exit(1)
  }
  // 成功路径也必须显式退出：
  //   browser.close() 之后 puppeteer 的连接套接字还挂着句柄，
  //   node 不会自己结束 —— 脚本会把「断言全过」打印出来，
  //   然后**永远不退出**（实测挂住 4 分多钟，被 SIGTERM 杀掉，exit=143）。
  //   在 CI/回归跑批里，一个不退出的脚本会被当成「还在跑」，
  //   把整批验证卡住 —— 断言全过也没用。
  process.exit(0)
}

main().catch((e) => { console.error('ERR', e); process.exit(1) })