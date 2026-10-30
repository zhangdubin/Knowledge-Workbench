/**
 * 图谱可读性测量（改前/改后共用同一个脚本）
 * 直接从 vis-network 的渲染结果里取真实坐标与真实文字尺寸，算：
 *  - 节点标签互相重叠的组数 / 对数
 *  - 边标签互相重叠的组数 / 对数
 *  - 连线穿过节点标签框的次数
 * 输出可比较的数字，不做主观描述。
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || process.env.KB_FRONTEND || 'http://localhost:5173'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'
const sleep = ms => new Promise(r => setTimeout(r, ms))
const TAG = process.env.TAG || 'before'

const ROUTES = [
  ['关联图谱', '/#/graph'],
  ['知识图谱', '/#/knowledge/graph'],
]
const SIZES = [[1600, 900], [390, 780]]


/** 像素级检查：节点文字区域里有没有被连线颜色污染的像素 */
const PIXEL_POLLUTION = () => {
  const net = window.__kbGraph
  const canvas = document.querySelector('.gc-canvas canvas')
  if (!canvas) return { error: 'no canvas' }
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  const parse = c => {
    const str = String(c || '')
    const m = str.match(/rgba?\(([^)]+)\)/)
    if (m) {
      const p = m[1].split(',').map(x => parseFloat(x))
      return [p[0], p[1], p[2]]
    }
    if (str.startsWith('#')) {
      const h = str.slice(1)
      const n = h.length === 3 ? h.split('').map(x => x + x).join('') : h
      return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)]
    }
    return null
  }
  const edgeRgb = [...new Set(Object.values(net.body.edges).map(e => e.options.color.color))]
    .map(parse).filter(Boolean)
  let polluted = 0
  let sampled = 0
  for (const n of Object.values(net.body.nodes)) {
    // 跳过隐藏节点，以及 vis 给弯曲边自动生成的辅助节点（edgeId:xxx，
    // 它们就落在连线中点上，采到的是线本身的像素）
    if (n.options.hidden || String(n.id).startsWith('edgeId:')) continue
    const dom = net.canvasToDOM({ x: n.x, y: n.y })
    // 只取盒子中间的文字区域，避开边框
    // 再往里收 3px，彻底避开节点自己的描边
    const w = Math.max(4, Math.round(n.shape.width * 0.6) - 6)
    const h = Math.max(3, Math.round(n.shape.height * 0.5) - 6)
    const x = Math.round(dom.x * dpr - (w * dpr) / 2)
    const y = Math.round(dom.y * dpr - (h * dpr) / 2)
    const pw = Math.round(w * dpr)
    const ph = Math.round(h * dpr)
    if (x < 0 || y < 0 || x + pw > canvas.width || y + ph > canvas.height) continue
    let data
    try { data = ctx.getImageData(x, y, pw, ph).data } catch (e) { continue }
    sampled++
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i + 1], b = data[i + 2]
      for (const [er, eg, eb] of edgeRgb) {
        // 容差要小：节点底色本身就是类型色的浅色混合，
        // 容差大了会把底色误判成「被连线污染」
        if (Math.abs(r - er) < 9 && Math.abs(g - eg) < 9 && Math.abs(b - eb) < 9) { polluted++; break }
      }
    }
  }
  return { pollutedPixels: polluted, sampledNodes: sampled, edgeColorCount: edgeRgb.length }
}

const PROBE = () => {
  const net = window.__kbGraph
  if (!net) return { error: 'no network' }

  // ---- 节点框：vis 画出来的真实尺寸 ----
  const nodeBoxes = Object.values(net.body.nodes)
    .filter(n => !n.options.hidden)
    .map(n => ({
      id: n.id,
      label: n.options.label || '',
      x: n.x, y: n.y,
      w: n.shape.width, h: n.shape.height,
    }))

  // ---- 边标签：真实落点 + 真实文字尺寸 ----
  const edgeLabels = Object.values(net.body.edges)
    .filter(e => !e.options.hidden && e.options.label)
    .map(e => {
      const size = e.labelModule.getSize()
      const pt = e.edgeType.getPoint(0.5)
      return {
        id: e.id, text: e.options.label,
        x: pt.x, y: pt.y,
        w: size.width, h: size.height,
      }
    })

  const overlapArea = (a, b) => {
    const ox = Math.min(a.x + a.w / 2, b.x + b.w / 2) - Math.max(a.x - a.w / 2, b.x - b.w / 2)
    const oy = Math.min(a.y + a.h / 2, b.y + b.h / 2) - Math.max(a.y - a.h / 2, b.y - b.h / 2)
    return ox > 0 && oy > 0 ? Math.round(ox * oy) : 0
  }

  // 重叠分组（连通分量）：互相压在一起的一堆算一组
  const groups = (items) => {
    const parent = items.map((_, i) => i)
    const find = i => (parent[i] === i ? i : (parent[i] = find(parent[i])))
    const union = (a, b) => { a = find(a); b = find(b); if (a !== b) parent[b] = a }
    let pairs = 0
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        if (overlapArea(items[i], items[j]) > 0) { pairs++; union(i, j) }
      }
    }
    return { pairs, groups: new Set(items.map((_, i) => find(i))).size }
  }

  // ---- 连线穿过节点标签框 ----
  const crossings = []
  const allEdges = Object.values(net.body.edges).filter(e => !e.options.hidden)
  for (const e of allEdges) {
    const a = e.from, b = e.to
    if (!a || !b) continue
    for (const box of nodeBoxes) {
      if (box.id === a.id || box.id === b.id) continue
      const dx = b.x - a.x, dy = b.y - a.y
      const len2 = dx * dx + dy * dy
      let t = len2 ? ((box.x - a.x) * dx + (box.y - a.y) * dy) / len2 : 0
      t = Math.max(0, Math.min(1, t))
      const px = a.x + t * dx, py = a.y + t * dy
      const outX = Math.max(0, Math.abs(box.x - px) - box.w / 2)
      const outY = Math.max(0, Math.abs(box.y - py) - box.h / 2)
      const d = Math.hypot(outX, outY)
      if (d < 4) crossings.push({ edge: e.id, node: box.id, d: Math.round(d) })
    }
  }

  const nodeOv = groups(nodeBoxes)
  const edgeOv = groups(edgeLabels)
  const allEdgesCount = allEdges.length

  // 边标签压住节点标签：两者重叠也算「读不了」
  let edgeLabelOnNode = 0
  for (const el of edgeLabels) {
    for (const nb of nodeBoxes) {
      if (overlapArea(el, nb) > 0) { edgeLabelOnNode++; break }
    }
  }

  // 并行边：同一对节点之间有多条连线时，它们的标签会落在同一个点上
  const pairCount = {}
  for (const e of allEdges) {
    const k = [e.fromId, e.toId].sort().join('|')
    pairCount[k] = (pairCount[k] || 0) + 1
  }
  const parallelEdges = Object.values(pairCount).filter(v => v > 1).length

  // 节点之间的最小间距（画布单位）
  let minGap = Infinity
  for (let i = 0; i < nodeBoxes.length; i++) {
    for (let j = i + 1; j < nodeBoxes.length; j++) {
      const d = Math.hypot(nodeBoxes[i].x - nodeBoxes[j].x, nodeBoxes[i].y - nodeBoxes[j].y)
      if (d < minGap) minGap = d
    }
  }

  const maxNodeLabelW = Math.round(Math.max(0, ...nodeBoxes.map(n => n.w)))
  const maxEdgeLabelW = Math.round(Math.max(0, ...edgeLabels.map(e => e.w)))

  return {
    nodes: nodeBoxes.length,
    edges: allEdgesCount,
    visibleEdgeLabels: edgeLabels.length,
    nodeOverlapPairs: nodeOv.pairs,
    nodeOverlapGroups: nodeOv.groups,
    edgeLabelOverlapPairs: edgeOv.pairs,
    edgeLabelOverlapGroups: edgeOv.groups,
    edgeLabelsOnNodeLabels: edgeLabelOnNode,
    parallelEdgePairs: parallelEdges,
    linesCrossingNodeLabels: crossings.length,
    crossingDetail: crossings.slice(0, 5),
    minNodeGap: Math.round(minGap),
    maxNodeLabelWidth: maxNodeLabelW,
    maxEdgeLabelWidth: maxEdgeLabelW,
    scale: Math.round(net.getScale() * 100) / 100,
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

  const out = {}
  for (const [name, route] of ROUTES) {
    for (const [w, h] of SIZES) {
      await page.setViewport({ width: w, height: h })
      await page.goto(`${BASE}${route}?__e2e=1`, { waitUntil: 'networkidle2' })
      // 等图谱真正画出来（网络实例 + 节点）再量
      await page.waitForFunction(
        () => window.__kbGraph && Object.keys(window.__kbGraph.body.nodes || {}).length > 0,
        { timeout: 20000 },
      ).catch(() => {})
      await sleep(3000)
      let probe
      try { probe = await page.evaluate(PROBE) } catch (e) { probe = { error: e.message } }
      const key = `${name}@${w}`
      out[key] = probe
      // SIMULATE_OLD=1：把节点底色改回改动前的半透明样式，
      // 用同一套像素指标量出「改动前连线压在文字上」的像素数，做前后对照
      if (process.env.SIMULATE_OLD === '1') {
        await page.evaluate(() => {
          const net = window.__kbGraph
          const items = net.body.data.nodes.get()
            .filter(n => !String(n.id).startsWith('edgeId:'))
            .map(n => {
              const border = n.color.border
              const h = String(border).replace('#', '')
              const num = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16)
              const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255
              return {
                id: n.id,
                color: {
                  ...n.color,
                  background: `rgba(${r},${g},${b},0.13)`,
                  highlight: { ...n.color.highlight, background: `rgba(${r},${g},${b},0.2)` },
                  hover: { ...n.color.hover, background: `rgba(${r},${g},${b},0.2)` },
                },
                font: { ...n.font, background: 'transparent' },
              }
            })
          net.body.data.nodes.update(items)
        })
        await sleep(600)
      }
      let pixels = {}
      try { pixels = await page.evaluate(PIXEL_POLLUTION) } catch (e) { pixels = { error: e.message } }
      out[key].pixels = pixels
      console.log(`\n=== ${key} ===`)
      console.log(JSON.stringify({ ...probe, pixels }))
      await page.screenshot({ path: `/tmp/graph-${TAG}-${name === '关联图谱' ? 'rel' : 'note'}-${w}.png` })
    }
  }
  require('fs').writeFileSync(`/tmp/graph-measure-${TAG}.json`, JSON.stringify(out, null, 2))
  await browser.close()
})()
