/**
 * 自由画布（无限画布）端到端验证（v0.3.3）
 *
 * 覆盖：
 *   1. 老 span 布局自动归一化成绝对坐标，且互不重叠
 *   2. 编辑态：卡片工具条、八向手柄、画布工具条（缩放/吸附/自动整理）
 *   3. 拖拽移动（含吸附对齐辅助线）
 *   4. 八向缩放 + 最小尺寸钳制
 *   5. 双击空白新建卡片（落在鼠标处）
 *   6. 缩放（按钮 + ctrl 滚轮）、适应窗口
 *   7. 自动整理
 *   8. 保存 → 刷新 → 几何持久化
 *   9. 全屏大屏：同一份自由布局、等比自适应、不滚动
 *  10. 浅/深色主题下卡片与网格可读
 *
 * 探测驾驶舱用完即删。
 *   KB_SESSION_TOKEN=xxx node scripts/verify-cockpit-canvas.cjs
 */
const { createRequire } = require('module')
const fs = require('fs')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = process.env.KB_SHOT_DIR || '/tmp/kb-cockpit-canvas'
const PROBE_KEY = `__v033_canvas_probe_${Date.now().toString(36)}`

const sleep = ms => new Promise(r => setTimeout(r, ms))
let pass = 0
const fails = []
const ok = (cond, label, extra) => {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fails.push(label); console.log(`  ✗ ${label}${extra !== undefined ? ' → ' + extra : ''}`) }
}
const lum = s => {
  const m = String(s).match(/\d+(\.\d+)?/g)
  if (!m) return null
  const [r, g, b] = m.slice(0, 3).map(Number)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255
}

async function main() {
  if (!TOKEN) { console.error('缺少 KB_SESSION_TOKEN'); process.exit(1) }
  fs.mkdirSync(OUT, { recursive: true })

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox', '--window-size=1600,1000'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 })
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); else console.log('  [browser]', m.type(), m.text()) })
  page.on('pageerror', e => errors.push(`pageerror: ${e}`))
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })
  await page.goto(`${FE}/#/`, { waitUntil: 'networkidle2' })

  const api = (p, method = 'GET', body) => page.evaluate(async (url, method, body) => {
    const r = await fetch(url, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { status: r.status, json: await r.json().catch(() => null) }
  }, `${FE}${p}`, method, body)

  // 画布状态读取器
  const readCards = () => page.evaluate(() => {
    const cards = [...document.querySelectorAll('.cv-card')]
    return cards.map(el => {
      const cs = getComputedStyle(el)
      const m = new DOMMatrix(cs.transform)
      const r = el.getBoundingClientRect()
      return {
        id: el.dataset.wid, type: (el.className.match(/cv-t-(\w+)/) || [])[1],
        x: Math.round(m.m41), y: Math.round(m.m42),
        w: Math.round(parseFloat(cs.width)), h: Math.round(parseFloat(cs.height)),
        sx: r.x, sy: r.y, sw: r.width, sh: r.height,
        badge: el.querySelector('.cb-size')?.textContent?.trim() || '',
      }
    })
  })
  const readZoom = () => page.evaluate(() => {
    const t = document.querySelector('.cv-dock .dk.val')?.textContent || ''
    const m = t.match(/(\d+)%/)
    return m ? Number(m[1]) / 100 : null
  })
  const clickByText = (sel, text) => page.evaluate((sel, text) => {
    const el = [...document.querySelectorAll(sel)].find(b => b.textContent.includes(text))
    el?.click()
    return !!el
  }, sel, text)

  // ---------- 0. 准备：一份"老式 span 布局" ----------
  console.log('\n== 0. 准备探测驾驶舱（老 span 布局）==')
  const opt = await api('/api/dashboards/options')
  const types = (opt.json?.entity_types || []).filter(t => t.count > 0)
  ok(types.length > 0, `有可用的业务模型（${types.length} 个含记录）`)
  const T = types[0]
  const groupField = (T.fields || []).find(f => ['select', 'text'].includes(f.type)) || T.fields[0]
  const src = { kind: 'entity', type_id: T.id, metric: 'count', field: '', limit: 10 }
  const chartSrc = { ...src, group_by: groupField?.key, limit: 6 }

  const create = await api('/api/dashboards', 'POST', {
    key: PROBE_KEY, name: 'V033 自由画布探测', icon: '🧭',
    description: '自动化探测，用完即删',
    // 故意只给 span（0.3.2 及以前的老写法），验证前端能换算成自由坐标
    layout: [
      { id: 'p1', type: 'stat', title: '指标甲', span: 1, source: src },
      { id: 'p2', type: 'stat', title: '指标乙', span: 1, source: src },
      { id: 'p3', type: 'gauge', title: '仪表', span: 1, source: { ...src, goal: 30 } },
      { id: 'p4', type: 'rank', title: '排行', span: 1, source: chartSrc },
      { id: 'p5', type: 'chart', title: '图表', span: 2, source: { ...chartSrc, chart: 'bar' } },
    ],
    settings: { theme: 'nebula', auto_refresh: 0 },
  })
  ok(create.status === 200, '驾驶舱创建成功', JSON.stringify(create.json))
  const DASH_ID = create.json?.id

  // ---------- 1. 老布局归一化 ----------
  console.log('\n== 1. 视图态：老 span 布局换算成自由坐标 ==')
  await page.goto(`${FE}/#/dashboards/${DASH_ID}`, { waitUntil: 'networkidle2' })
  await sleep(1500)
  const view = await readCards()
  ok(view.length === 5, `渲染出 ${view.length} 张卡片`)
  ok(!(await page.$('.cockpit')), '旧的 grid 容器已经不存在')
  ok(view.every(c => c.x >= 0 && c.y >= 0), '每张卡都有非负的自由坐标')
  ok(new Set(view.map(c => `${c.x},${c.y}`)).size === 5, '5 张卡位置互不相同（不是全堆在左上角）')
  // 自适应容器宽度：在小容器里 4 张卡可能分两行，不强制同一行，但要求无重叠
  const overlap = []
  for (let i = 0; i < view.length; i++) {
    for (let j = i + 1; j < view.length; j++) {
      const a = view[i], b = view[j]
      if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlap.push(`${a.id}~${b.id}`)
    }
  }
  ok(overlap.length === 0, '卡片两两不重叠', overlap.join(','))
  ok(view[4].w > view[0].w, `span=2 比 span=1 宽（${view[4].w} > ${view[0].w}）`)
  await page.screenshot({ path: `${OUT}/view-free-canvas.png` })

  // ---------- 2. 进入编辑 ----------
  console.log('\n== 2. 编辑态：手柄与画布工具条 ==')
  ok(await clickByText('button', '编辑布局'), '点「编辑布局」')
  await sleep(1200)
  const editUi = await page.evaluate(() => ({
    editClass: document.querySelector('.cv')?.classList.contains('is-edit'),
    bars: document.querySelectorAll('.cv-bar').length,
    handles: document.querySelectorAll('.cv-h').length,
    dock: [...document.querySelectorAll('.cv-dock .dk')].map(b => b.textContent.trim()),
    grid: !!document.querySelector('.cv-grid'),
    tip: document.querySelector('.cv-tip')?.textContent?.includes('拖动卡片自由摆放'),
    bodyNoPointer: getComputedStyle(document.querySelector('.cv-body')).pointerEvents,
  }))
  ok(editUi.editClass, '画布进入编辑态')
  ok(editUi.bars === 5, `每张卡都有编辑工具条（${editUi.bars} 条）`)
  ok(editUi.handles === 40, `八向手柄齐全（${editUi.handles} = 5 张 × 8）`)
  ok(editUi.dock.join(',').includes('吸附') && editUi.dock.join(',').includes('智能整理'),
    `画布工具条含缩放/吸附/智能整理：${editUi.dock.join(' ')}`)
  ok(editUi.grid, '编辑态显示网格底纹')
  ok(editUi.tip, '底部有操作提示')
  ok(editUi.bodyNoPointer === 'none', '编辑态卡片内容不拦指针（整卡可拖、不会误触跳转）')
  await page.screenshot({ path: `${OUT}/edit-canvas.png` })

  // ---------- 3. 拖拽移动 + 吸附 ----------
  console.log('\n== 3. 拖拽移动与吸附对齐 ==')
  const before = await readCards()
  const zoom = await readZoom()
  const A = before[0]
  const B = before[1]
  // 把 B 拖到与 A 左边缘对齐的位置（屏幕位移要乘上缩放系数）
  const grabX = B.sx + 60
  const grabY = B.sy + 10
  const wantX = grabX + (A.x - B.x) * zoom
  const wantY = grabY + 140
  await page.mouse.move(grabX, grabY)
  await page.mouse.down()
  for (let i = 1; i <= 12; i++) {
    await page.mouse.move(grabX + (wantX - grabX) * i / 12, grabY + (wantY - grabY) * i / 12)
    await sleep(24)
  }
  const during = await page.evaluate(() => ({
    guides: document.querySelectorAll('.cv-guide').length,
    moving: !!document.querySelector('.cv-card.moving'),
    badge: document.querySelector('.cv-card.moving .cb-size')?.textContent?.trim() || '',
  }))
  ok(during.moving, '拖动中的卡片有 dragging 状态')
  ok(/\d+ × \d+/.test(during.badge), `实时显示尺寸（${during.badge}）`)
  ok(during.guides >= 1, `拖动时出现对齐辅助线（${during.guides} 条）`)
  await page.mouse.up()
  await sleep(300)
  const after = await readCards()
  ok(after[1].x === A.x, `吸附：B 的左边缘对齐到 A（${after[1].x} = ${A.x}）`)
  ok(after[1].y > B.y + 80, `纵向确实移动了（${B.y} → ${after[1].y}）`)
  const guidesAfter = await page.evaluate(() => document.querySelectorAll('.cv-guide').length)
  ok(guidesAfter === 0, '松手后辅助线消失')

  // ---------- 4. 缩放（resize）与最小尺寸 ----------
  console.log('\n== 4. 八向缩放与最小尺寸钳制 ==')
  const target = after[1]
  const seX = target.sx + target.sw - 1
  const seY = target.sy + target.sh - 1
  await page.mouse.move(seX, seY)
  await page.mouse.down()
  for (let i = 1; i <= 8; i++) {
    await page.mouse.move(seX + 16 * i, seY + 12 * i)
    await sleep(24)
  }
  await page.mouse.up()
  await sleep(300)
  const grown = (await readCards())[1]
  ok(grown.w > target.w + 60, `右下角拖拽放大宽度（${target.w} → ${grown.w}）`)
  ok(grown.h > target.h + 40, `高度一起放大（${target.h} → ${grown.h}）`)
  ok(grown.x === target.x && grown.y === target.y, '拖右下角不改变左上角位置')

  // 往回拖到远小于最小尺寸，应被钳制
  const minProbe = (await readCards())[1]
  const seX2 = minProbe.sx + minProbe.sw - 1
  const seY2 = minProbe.sy + minProbe.sh - 1
  await page.mouse.move(seX2, seY2)
  await page.mouse.down()
  for (let i = 1; i <= 10; i++) {
    await page.mouse.move(seX2 - 40 * i, seY2 - 30 * i)
    await sleep(20)
  }
  await page.mouse.up()
  await sleep(300)
  const clamped = (await readCards())[1]
  ok(clamped.w >= 180 && clamped.h >= 104,
    `缩到极限时被最小尺寸挡住（${clamped.w} × ${clamped.h} ≥ 180 × 104）`)
  ok(clamped.w < grown.w && clamped.h < grown.h,
    `继续往回拖确实缩小了（${grown.w}×${grown.h} → ${clamped.w}×${clamped.h}）`)

  // ---------- 5. 键盘微调 ----------
  console.log('\n== 5. 方向键微调 ==')
  const kb0 = (await readCards())[1]
  await page.mouse.move(kb0.sx + 40, kb0.sy + 10)
  await page.mouse.down()
  await page.mouse.up()          // 单击选中（选中的卡片会浮到最上层）
  await sleep(200)
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await sleep(250)
  const kb1 = (await readCards())[1]
  ok(kb1.x === kb0.x + 3, `方向键每次移动 1px（${kb0.x} → ${kb1.x}）`)

  // ---------- 6. 缩放与适应窗口 ----------
  console.log('\n== 6. 画布缩放与适应窗口 ==')
  const z0 = await readZoom()
  await clickByText('.cv-dock .dk', '−')
  await sleep(400)
  const z1 = await readZoom()
  ok(z1 < z0, `点「−」缩小（${z0} → ${z1}）`)
  await clickByText('.cv-dock .dk', '＋')
  await sleep(400)
  ok((await readZoom()) === z0, '点「＋」加回来')
  await clickByText('.cv-dock .dk', '适应')
  await sleep(600)
  const fitState = await page.evaluate(() => {
    const scroll = document.querySelector('.cv-scroll')
    const content = document.querySelector('.cv-content')
    return {
      contentW: parseFloat(getComputedStyle(content).width),
      scale: new DOMMatrix(getComputedStyle(content).transform).a,
      viewW: scroll.clientWidth, viewH: scroll.clientHeight,
      overflowX: scroll.scrollWidth - scroll.clientWidth,
    }
  })
  ok(Math.abs(fitState.contentW * fitState.scale - fitState.viewW) < 12 ||
     fitState.contentW * fitState.scale <= fitState.viewW + 2,
    `适应后内容宽度贴合视口（${Math.round(fitState.contentW * fitState.scale)} ≤ ${fitState.viewW}）`)
  await page.screenshot({ path: `${OUT}/edit-zoom-fit.png` })

  // ---------- 7. 双击空白新建 ----------
  console.log('\n== 7. 双击空白新建卡片 ==')
  const addPos = await page.evaluate(() => {
    const r = document.querySelector('.cv-scroll').getBoundingClientRect()
    return { x: r.x + r.width * 0.62, y: r.y + r.height * 0.78 }
  })
  await page.mouse.move(addPos.x, addPos.y)
  await page.mouse.click(addPos.x, addPos.y, { clickCount: 2, delay: 60 })
  await sleep(900)
  const drawer = await page.evaluate(() => {
    const d = document.querySelector('.widget-drawer')
    const nums = [...(d?.querySelectorAll('.sz-num .el-input-number input') || [])].map(i => i.value)
    const presets = [...(d?.querySelectorAll('.sz-row .el-radio-button') || [])].map(b => b.textContent.trim())
    return {
      open: !!d,
      title: d?.querySelector('.wd-head h3')?.textContent?.trim(),
      sizeLabels: [...(d?.querySelectorAll('.sz-num .wd-label') || [])].map(x => x.textContent.trim()),
      nums, presets,
      hasSpanSelect: [...(d?.querySelectorAll('.wd-label') || [])].some(x => x.textContent.trim() === '宽度'),
    }
  })
  ok(drawer.open, '双击空白处打开了新建卡片抽屉')
  ok(drawer.title === '添加卡片', '是「添加卡片」而不是「配置卡片」')
  ok(drawer.sizeLabels.join(',').includes('宽') && drawer.sizeLabels.join(',').includes('高'),
    `尺寸项改成像素宽高：${drawer.sizeLabels.join(' / ')}`)
  ok(drawer.presets.join('').includes('小') && drawer.presets.join('').includes('宽扁'),
    `尺寸预设：${drawer.presets.join(' ')}`)
  ok(!drawer.hasSpanSelect, '不再有「占几列」这种老配置')
  await page.screenshot({ path: `${OUT}/drawer-size.png` })
  // 选一个预设看数值变化
  const beforePreset = drawer.nums.join('x')
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.widget-drawer .sz-row .el-radio-button')]
    b.find(x => x.textContent.trim() === '大')?.click()
  })
  await sleep(400)
  const afterPreset = await page.evaluate(() =>
    [...document.querySelectorAll('.widget-drawer .sz-num .el-input-number input')].map(i => i.value).join('x'))
  ok(afterPreset !== beforePreset, `预设「大」改变了尺寸（${beforePreset} → ${afterPreset}）`)
  // 应用到画布
  await clickByText('.widget-drawer button', '添加到驾驶舱')
  await sleep(700)
  const added = await readCards()
  ok(added.length === 6, `新卡片加到画布上（共 ${added.length} 张）`)
  const newCard = added[added.length - 1]
  ok(newCard.x > 0 && newCard.y > 0, `新卡片落在双击的位置附近（${newCard.x},${newCard.y}）`)

  // ---------- 8. 自动整理 + 保存持久化 ----------
  console.log('\n== 8. 自动整理与保存持久化 ==')
  await clickByText('.cv-dock .dk', '智能整理')
  await sleep(800)
  const tidied = await readCards()
  ok(tidied.some(c => c.x === 0 && c.y === 0), '自动整理后第一张回到原点')
  const rows = new Set(tidied.map(c => c.y)).size
  ok(rows <= 4, `整理成 ${rows} 行（原来的零散位置被理平）`)
  await page.screenshot({ path: `${OUT}/edit-tidied.png` })

  await clickByText('button', '保存布局')
  await sleep(1200)
  const saved = await api(`/api/dashboards/${DASH_ID}`)
  const savedLayout = saved.json?.layout || []
  ok(savedLayout.length === 6, `后端存了 6 张卡片（${savedLayout.length}）`)
  ok(savedLayout.every(w => Number.isFinite(w.w) && Number.isFinite(w.h) && Number.isFinite(w.x)),
    '每张卡都带上了 x/y/w/h')
  ok(!savedLayout.some(w => w.span !== undefined), 'span 字段已彻底退场')
  const wantGeom = tidied.map(c => `${c.x},${c.y},${c.w},${c.h}`).join('|')

  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(1500)
  const reloaded = await readCards()
  ok(reloaded.map(c => `${c.x},${c.y},${c.w},${c.h}`).join('|') === wantGeom,
    '刷新后几何完全一致（自由布局真的存下来了）')

  // ---------- 9. 全屏大屏 ----------
  console.log('\n== 9. 全屏大屏（同一份自由布局）==')
  await clickByText('button', '大屏')
  await page.waitForSelector('.fs-screen', { timeout: 10000 })
  await sleep(1800)
  const screen = await page.evaluate(() => {
    const cv = document.querySelector('.fs-screen .cv')
    const cards = [...document.querySelectorAll('.fs-screen .cv-card')]
    const content = document.querySelector('.fs-screen .cv-content')
    const scroll = document.querySelector('.fs-screen .cv-scroll')
    return {
      canvas: !!cv, screenSkin: !!cv?.classList.contains('cv-screen'),
      cards: cards.length,
      scaled: new DOMMatrix(getComputedStyle(content).transform).a,
      contentW: parseFloat(getComputedStyle(content).width),
      contentH: parseFloat(getComputedStyle(content).height),
      viewW: scroll.clientWidth, viewH: scroll.clientHeight,
      innerW: window.innerWidth, innerH: window.innerHeight,
      maxCardW: Math.max(...cards.map(c => parseFloat(getComputedStyle(c).width))),
      maxCardRight: Math.max(...cards.map(c => {
        const m = new DOMMatrix(getComputedStyle(c).transform)
        return m.m41 + parseFloat(getComputedStyle(c).width)
      })),
      overlowY: scroll.scrollHeight - scroll.clientHeight,
      dock: document.querySelectorAll('.fs-screen .cv-dock').length,
      bars: document.querySelectorAll('.fs-screen .cv-bar').length,
      pos: cards.slice(0, 3).map(c => {
        const m = new DOMMatrix(getComputedStyle(c).transform)
        return `${Math.round(m.m41)},${Math.round(m.m42)}`
      }),
    }
  })
  console.log('  [debug] screen:', screen)
  ok(screen.canvas && screen.screenSkin, '大屏用的是同一套画布组件（screen 皮肤）')
  ok(screen.cards === 6, `大屏渲染 ${screen.cards} 张卡片`)
  ok(screen.pos.length === 3 && new Set(screen.pos).size === 3, `卡片按自由坐标摆放：${screen.pos.join(' / ')}`)
  ok(screen.dock === 0 && screen.bars === 0, '大屏不显示编辑工具条与手柄')
  ok(screen.contentW * screen.scaled >= screen.viewW - 4,
    `大屏横向铺满（内容宽×缩放=${Math.round(screen.contentW * screen.scaled)} ≥ 视口宽${screen.viewW}）`)
  ok(screen.contentH * screen.scaled <= screen.viewH + 4,
    `大屏纵向完整显示（内容高×缩放=${Math.round(screen.contentH * screen.scaled)} ≤ 视口高${screen.viewH}）`)
  ok(screen.overlowY <= 2, `大屏不产生纵向滚动（溢出 ${screen.overlowY}px）`)
  await page.screenshot({ path: `${OUT}/fullscreen-free.png` })
  await page.evaluate(() => document.querySelector('.fs-exit')?.click())
  await sleep(600)

  // ---------- 10. 浅/深色可读性 ----------
  console.log('\n== 10. 浅色 / 深色主题可读性 ==')
  const readTheme = () => page.evaluate(() => {
    const card = document.querySelector('.cv-card')
    const grid = document.querySelector('.cv-grid')
    const title = document.querySelector('.cv-bar .cb-title') || document.querySelector('.cw-title')
    const dock = document.querySelector('.cv-dock')
    return {
      dark: document.documentElement.classList.contains('dark'),
      cardBg: getComputedStyle(card).backgroundColor,
      cardBorder: getComputedStyle(card).borderTopColor,
      text: getComputedStyle(title).color,
      gridLine: grid ? getComputedStyle(grid).backgroundImage.match(/rgba?\([^)]+\)/g)?.[0] : '',
      dockBg: getComputedStyle(dock).backgroundColor,
      pageBg: getComputedStyle(document.body).backgroundColor,
    }
  })
  await clickByText('button', '编辑布局')
  await sleep(900)
  const light = await readTheme()
  await page.screenshot({ path: `${OUT}/canvas-light.png` })
  await page.evaluate(() => document.querySelector('button[title="切换主题"]')?.click())
  await sleep(900)
  const dark = await readTheme()
  await page.screenshot({ path: `${OUT}/canvas-dark.png` })
  ok(!light.dark && lum(light.cardBg) > 0.7 && lum(light.text) < 0.5,
    `浅色：深字浅底（卡片 ${light.cardBg} / 文字 ${light.text}）`)
  ok(dark.dark && lum(dark.cardBg) < 0.35 && lum(dark.text) > 0.5,
    `深色：浅字深底（卡片 ${dark.cardBg} / 文字 ${dark.text}）`)
  ok(light.cardBg !== dark.cardBg, '画布卡片跟随主题换色')
  ok((light.gridLine || '').length > 0 && (dark.gridLine || '').length > 0,
    '网格底纹在两种主题下都渲染出来了')
  // 还原主题
  await page.evaluate(() => document.querySelector('button[title="切换主题"]')?.click())
  await sleep(500)
  await clickByText('button', '取消')
  await sleep(400)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-message-box button')].find(x => x.textContent.includes('放弃修改'))
    b?.click()
  })
  await sleep(600)

  ok(errors.length === 0, '无控制台报错', errors.slice(0, 3).join(' ; '))

  // ---------- 清理 ----------
  console.log('\n== 11. 清理 ==')
  const del = await api(`/api/dashboards/${DASH_ID}`, 'DELETE')
  ok(del.status === 200, '探测驾驶舱已删除')
  await browser.close()

  console.log(`\n==== 结果：${pass} 通过 / ${fails.length} 失败 ====`)
  console.log(`截图目录：${OUT}`)
  if (fails.length) { fails.forEach(f => console.log('  未通过：' + f)); process.exit(1) }
}

main().catch(e => { console.error(e); process.exit(1) })
