/**
 * 图谱可读性验证（交互部分）
 * 覆盖：
 *   1. 悬停节点 → 浮出与它相连的关系名，且互不重叠
 *   2. 悬停连线 → 浮出这一条的关系名
 *   3. 打开「显示关系名称」→ 所有连线都带标签
 *   4. 标签底板不透明（画布上的节点底色不透明 → 线压不到文字）
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.KB_FRONTEND || 'http://localhost:5173'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'
const sleep = ms => new Promise(r => setTimeout(r, ms))

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ` — ${detail}` : ''}`)
}

/** 画布坐标 → 页面坐标 */
const NODE_PAGE_POS = id => {
  const net = window.__kbGraph
  const n = net.body.nodes[id]
  if (!n) return null
  const dom = net.canvasToDOM({ x: n.x, y: n.y })
  const rect = document.querySelector('.gc-canvas').getBoundingClientRect()
  return { x: rect.left + dom.x, y: rect.top + dom.y }
}

const EDGE_PAGE_POS = id => {
  const net = window.__kbGraph
  const e = net.body.edges[id]
  if (!e) return null
  const pt = e.edgeType.getPoint(0.5)
  const dom = net.canvasToDOM(pt)
  const rect = document.querySelector('.gc-canvas').getBoundingClientRect()
  return { x: rect.left + dom.x, y: rect.top + dom.y }
}

/** 覆盖层里的标签两两重叠数 */
const TIP_OVERLAP = () => {
  const items = [...document.querySelectorAll('.gct')].map(el => {
    const r = el.getBoundingClientRect()
    return { x: r.left, y: r.top, w: r.width, h: r.height, text: el.textContent.trim() }
  })
  let pairs = 0
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const ox = Math.min(items[i].x + items[i].w, items[j].x + items[j].w)
        - Math.max(items[i].x, items[j].x)
      const oy = Math.min(items[i].y + items[i].h, items[j].y + items[j].h)
        - Math.max(items[i].y, items[j].y)
      if (ox > 0 && oy > 0) pairs++
    }
  }
  return { count: items.length, pairs, items }
}

/** vis 里当前真正画出来的边标签 */
const VISIBLE_EDGE_LABELS = () => {
  const net = window.__kbGraph
  return Object.values(net.body.edges).filter(e => e.options.label).length
}


/** 把鼠标移到画布里一个既没有节点也没有连线的空白点 */
async function moveToBlank(page) {
  const pts = await page.evaluate(() => {
    const net = window.__kbGraph
    const rect = document.querySelector('.gc-canvas').getBoundingClientRect()
    const out = []
    for (const fx of [0.02, 0.95, 0.5, 0.15, 0.85]) {
      for (const fy of [0.03, 0.97, 0.5, 0.2, 0.8]) {
        const x = rect.left + rect.width * fx
        const y = rect.top + rect.height * fy
        const el = document.elementFromPoint(x, y)
        if (el && el.tagName === 'CANVAS') out.push({ x, y })
      }
    }
    return out
  })
  for (const p of pts) {
    await page.mouse.move(p.x, p.y)
    await sleep(120)
    const hovering = await page.evaluate(() => ({
      n: Object.values(window.__kbGraph.body.nodes).filter(x => x.hover).length,
      e: Object.values(window.__kbGraph.body.edges).filter(x => x.hover).length,
    }))
    if (!hovering.n && !hovering.e) return
  }
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 900 })

  await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2' })
  await sleep(1000)
  const inputs = await page.$$('input')
  await inputs[0].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[0].type(USER)
  await inputs[1].click({ clickCount: 3 }); await page.keyboard.press('Backspace'); await inputs[1].type(PASS)
  await page.click('button[type=submit], .el-button--primary')
  await sleep(2500)

  await page.goto(`${BASE}/#/knowledge/graph?__e2e=1`, { waitUntil: 'networkidle2' })
  await page.waitForFunction(() => window.__kbGraph && Object.keys(window.__kbGraph.body.nodes || {}).length > 0, { timeout: 20000 })
  await sleep(3500)

  // ---- 1. 默认不画任何边标签 ----
  const defaultLabels = await page.evaluate(VISIBLE_EDGE_LABELS)
  const defaultTips = await page.evaluate(TIP_OVERLAP)
  check('默认不显示边标签', defaultLabels === 0 && defaultTips.count === 0,
    `canvas 边标签 ${defaultLabels} 个 / 浮层 ${defaultTips.count} 个`)

  // ---- 2. 悬停节点 → 浮出相邻关系名 ----
  const nodeId = await page.evaluate(() => {
    const net = window.__kbGraph
    // 选度数最高的节点：它能一次浮出多条关系名，最容易压在一起
    const deg = {}
    for (const e of Object.values(net.body.edges)) {
      deg[e.fromId] = (deg[e.fromId] || 0) + 1
      deg[e.toId] = (deg[e.toId] || 0) + 1
    }
    const list = Object.keys(deg).sort((a, b) => deg[b] - deg[a])
    // 挑一个没被图例盖住的节点
    const rect = document.querySelector('.gc-canvas').getBoundingClientRect()
    for (const id of list) {
      const n = net.body.nodes[id]
      const dom = net.canvasToDOM({ x: n.x, y: n.y })
      const el = document.elementFromPoint(rect.left + dom.x, rect.top + dom.y)
      if (el && el.tagName === 'CANVAS') return id
    }
    return list[0]
  })
  const np = await page.evaluate(NODE_PAGE_POS, nodeId)
  await page.mouse.move(np.x, np.y)
  await sleep(700)
  const tipAfterNode = await page.evaluate(TIP_OVERLAP)
  check('悬停节点浮出关系名', tipAfterNode.count > 0, `浮出 ${tipAfterNode.count} 条`)
  check('浮出的关系名互不重叠', tipAfterNode.pairs === 0, `重叠对 ${tipAfterNode.pairs}`)
  check('浮出的关系名有文字', tipAfterNode.items.every(i => i.text.length > 0), JSON.stringify(tipAfterNode.items.map(i => i.text)))

  // ---- 3. 悬停连线 → 只浮出这一条 ----
  // 找一条「中间点没被节点盖住、也在画布内」的连线
  const edgeId = await page.evaluate(() => {
    const net = window.__kbGraph
    const rect = document.querySelector('.gc-canvas').getBoundingClientRect()
    for (const [id, e] of Object.entries(net.body.edges)) {
      const pt = e.edgeType.getPoint(0.5)
      const dom = net.canvasToDOM(pt)
      const x = rect.left + dom.x, y = rect.top + dom.y
      if (x < rect.left + 6 || y < rect.top + 6 || x > rect.right - 6 || y > rect.bottom - 6) continue
      if (net.getNodeAt({ x: dom.x, y: dom.y })) continue      // 被节点盖住就换一条
      const el = document.elementFromPoint(x, y)
      if (!el || el.tagName !== 'CANVAS') continue
      return id
    }
    return null
  })
  if (!edgeId) { check('悬停连线浮出该线关系名', false, '找不到可悬停的连线'); }
  const ep = await page.evaluate(EDGE_PAGE_POS, edgeId)
  await moveToBlank(page)
  await sleep(400)
  await page.mouse.move(ep.x, ep.y)
  await sleep(700)
  const tipAfterEdge = await page.evaluate(TIP_OVERLAP)
  check('悬停连线浮出该线关系名', tipAfterEdge.count === 1, `浮出 ${tipAfterEdge.count} 条：${tipAfterEdge.items.map(i => i.text).join('|')}`)

  // ---- 4. 打开「显示关系名称」→ 全部边都有标签 ----
  await moveToBlank(page)
  await sleep(300)
  const toggled = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.gt-btn')].find(b => b.getAttribute('aria-label') === '显示关系名称')
    if (!btn) return false
    btn.click()
    return true
  })
  await sleep(800)
  const totalEdges = await page.evaluate(() => Object.keys(window.__kbGraph.body.edges).length)
  const allTips = await page.evaluate(TIP_OVERLAP)
  check('工具条能打开全部关系名', toggled && allTips.count === totalEdges,
    `${allTips.count}/${totalEdges} 条边带标签`)
  check('全部显示时标签仍不重叠', allTips.pairs === 0, `重叠对 ${allTips.pairs}`)

  // ---- 5. 关掉后恢复默认 ----
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.gt-btn')].find(b => b.getAttribute('aria-label') === '显示关系名称')
    btn?.click()
  })
  await sleep(600)
  const afterOff = await page.evaluate(TIP_OVERLAP)
  const afterOffCanvas = await page.evaluate(VISIBLE_EDGE_LABELS)
  const leftover = await page.evaluate(() => ({
    tips: [...document.querySelectorAll('.gct')].map(e => e.textContent.trim()),
    hoveredNodes: Object.values(window.__kbGraph.body.nodes).filter(n => n.hover).map(n => n.id),
    hoveredEdges: Object.values(window.__kbGraph.body.edges).filter(e => e.hover).map(e => e.id),
  }))
  check('再点一次能关掉关系名', afterOff.count === 0 && afterOffCanvas === 0,
    `浮层 ${afterOff.count} 条 ${JSON.stringify(leftover)} / canvas ${afterOffCanvas} 条`)

  // ---- 6. 节点底色不透明（线压不到文字上）----
  const opacity = await page.evaluate(() => {
    const net = window.__kbGraph
    const n = Object.values(net.body.nodes)[0]
    const bg = n.options.color.background
    const m = String(bg).match(/rgba?\(([^)]+)\)/)
    if (!m) return { bg, alpha: 1 }
    const parts = m[1].split(',').map(s => parseFloat(s))
    return { bg, alpha: parts.length > 3 ? parts[3] : 1 }
  })
  check('节点底色不透明', opacity.alpha === 1, `背景 ${opacity.bg}`)

  const failed = results.filter(r => !r.ok)
  console.log(`\n通过 ${results.length - failed.length}/${results.length}`)
  await browser.close()
  process.exit(failed.length ? 1 : 0)
})()
