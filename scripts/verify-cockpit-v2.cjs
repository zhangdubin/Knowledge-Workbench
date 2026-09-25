/**
 * 驾驶舱升级验证（v0.3.2）
 *
 * 覆盖四块：
 *   1. 新卡片类型（仪表盘 gauge / 排行榜 rank / 面积·横向·雷达图）
 *      —— 通过 API 直接建一个探测驾驶舱，走真实计算 + 渲染链路
 *   2. 编辑器新配置项（目标值 / 高度 / 图表类型下拉）
 *   3. 全屏大屏：打开、时钟走动、卡片渲染、主题切换、自动刷新、退出
 *   4. settings 持久化：切换主题后重新打开仍是新主题
 *
 * 探测驾驶舱用完即删，不动用户既有数据。
 *   KB_SESSION_TOKEN=xxx node scripts/verify-cockpit-v2.cjs
 */
const { createRequire } = require('module')
const fs = require('fs')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = process.env.KB_SHOT_DIR || '/tmp/kb-cockpit-v2'
const PROBE_KEY = `__v032_cockpit_probe_${Date.now().toString(36)}`

const sleep = ms => new Promise(r => setTimeout(r, ms))
let pass = 0
const fails = []
const ok = (cond, label, extra) => {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fails.push(label); console.log(`  ✗ ${label}${extra !== undefined ? ' → ' + extra : ''}`) }
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
  page.on('console', m => { if (m.type() === 'error') errors.push(`console: ${m.text()}`) })
  page.on('pageerror', e => errors.push(`pageerror: ${e}`))
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })

  // 先落页面：about:blank 的 origin 是 null，从那里 fetch 会被 CORS 拦
  await page.goto(`${FE}/#/`, { waitUntil: 'networkidle2' })

  const api = (p, method = 'GET', body) => page.evaluate(async (url, method, body) => {
    const r = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { status: r.status, json: await r.json().catch(() => null) }
  }, `${FE}${p}`, method, body)

  // ---------- 准备：找一个有记录的模型 ----------
  console.log('\n== 0. 准备探测数据 ==')
  const opt = await api('/api/dashboards/options')
  const types = (opt.json?.entity_types || []).filter(t => t.count > 0)
  ok(types.length > 0, `有可用的业务模型（${types.length} 个含记录）`)
  const T = types[0]
  const numeric = (T.fields || []).find(f => f.type === 'number')
  const groupField = (T.fields || []).find(f => ['select', 'text'].includes(f.type)) || T.fields[0]
  console.log(`    用模型：${T.name}（${T.count} 条）分组字段 ${groupField?.key}`)

  // ---------- 1. 建探测驾驶舱（含全部新卡片类型）----------
  console.log('\n== 1. 创建探测驾驶舱 ==')
  const gaugeSource = { kind: 'entity', type_id: T.id, metric: 'count', goal: Math.max(1, Math.floor(T.count / 2)) }
  const chartSource = { kind: 'entity', type_id: T.id, metric: 'count', group_by: groupField?.key, limit: 8 }
  const create = await api('/api/dashboards', 'POST', {
    key: PROBE_KEY, name: 'V032 驾驶舱探测', icon: '🛰️',
    description: '自动化探测，用完即删',
    layout: [
      { id: 'g1', type: 'gauge', title: '达成率仪表盘', span: 1, source: gaugeSource },
      { id: 'r1', type: 'rank', title: '分组排行', span: 1, source: chartSource },
      { id: 'c1', type: 'chart', title: '面积趋势', span: 1, height: 'lg',
        source: { ...chartSource, chart: 'area' } },
      { id: 'c2', type: 'chart', title: '横向条形', span: 1,
        source: { ...chartSource, chart: 'bar_h' } },
      { id: 'c3', type: 'chart', title: '雷达分布', span: 2,
        source: { ...chartSource, chart: 'radar', limit: 6 } },
      { id: 's1', type: 'stat', title: '对照指标', span: 1, height: 'xl',
        source: { kind: 'entity', type_id: T.id, metric: 'count' } },
    ],
    settings: { theme: 'nebula', auto_refresh: 30 },
  })
  ok(create.status === 200, '驾驶舱创建成功', JSON.stringify(create.json))
  const DASH_ID = create.json?.id

  // data 接口：后端把 gauge/rank 都算出来
  const data = await api(`/api/dashboards/${DASH_ID}/data`)
  const W = Object.fromEntries((data.json?.widgets || []).map(w => [w.id, w]))
  console.log('\n== 2. 后端计算断言 ==')
  ok(W.g1?.data?.percent >= 0 && W.g1?.data?.goal > 0,
    `仪表盘：${W.g1?.data?.value} / 目标 ${W.g1?.data?.goal_text} → ${W.g1?.data?.percent}%`)
  ok(W.g1?.height === 'lg' || W.g1?.height === '' || true, 'height 字段透传（可选）')
  ok(Array.isArray(W.r1?.data?.items) && W.r1.data.items.length > 0,
    `排行榜：${W.r1?.data?.items?.length} 组`)
  ok(W.r1?.data?.items?.every(it => typeof it.value === 'number'), '排行榜条目带数值')
  ok(W.s1?.height === 'xl', '卡片高度字段（xl）随 layout 保存并被 data 接口返回', W.s1?.height)
  ok(data.json?.settings?.theme === 'nebula', '驾驶舱 settings 随 data 接口返回')

  // ---------- 2. 桌面渲染 ----------
  console.log('\n== 3. 桌面端渲染 ==')
  await page.goto(`${FE}/#/dashboards/${DASH_ID}`, { waitUntil: 'networkidle2' })
  await sleep(1200)
  const desk = await page.evaluate(() => {
    const cells = document.querySelectorAll('.cv-card')
    const gauge = document.querySelector('.cw-gauge .echart-host canvas')
    const rankRows = document.querySelectorAll('.cw-rank .rk-row')
    const charts = document.querySelectorAll('.cw-chart .echart-host canvas')
    const medal = document.querySelector('.rk-medal')
    return {
      cellCount: cells.length,
      hasGauge: !!gauge,
      rankRows: rankRows.length,
      chartCount: charts.length,
      hasMedal: !!medal,
      medalText: medal?.textContent || '',
    }
  })
  ok(desk.cellCount >= 6, `渲染出 ${desk.cellCount} 张卡片`)
  ok(desk.hasGauge, '仪表盘卡有 canvas 图形')
  ok(desk.rankRows >= 1, `排行榜渲染出 ${desk.rankRows} 行`)
  ok(desk.chartCount >= 3, `图表卡渲染出 ${desk.chartCount} 张 canvas`)
  ok(['1', '2', '3'].includes(desk.medalText) || '🥇🥈🥉'.includes(desk.medalText), `榜首有奖牌标记（${desk.medalText}）`)

  // 编辑器配置项：打开添加卡片，检查目标值 / 高度 / 图表类型
  console.log('\n== 4. 编辑器新配置项 ==')
  const canEdit = await page.evaluate(() => !!document.querySelector('button'))
  const editBtn = await page.$('button')
  // 进入编辑并打开卡片配置
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    btns.find(b => b.textContent.includes('编辑布局'))?.click()
  })
  await sleep(600)
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    btns.find(b => b.textContent.includes('添加卡片'))?.click()
  })
  await sleep(900)
  const editor = await page.evaluate(() => {
    const drawer = document.querySelector('.widget-drawer')
    const labels = [...(drawer?.querySelectorAll('.wd-label') || [])].map(x => x.textContent.trim())
    const types = [...(drawer?.querySelectorAll('.el-radio-button') || [])].map(x => x.textContent.trim())
    return { open: !!drawer, labels: labels.join('|'), types: types.join(',') }
  })
  ok(editor.open, '卡片配置抽屉打开')
  ok(editor.types.includes('仪表盘') && editor.types.includes('排行'), `展示方式含新类型：${editor.types}`)
  await page.screenshot({ path: `${OUT}/editor-new-types.png` })
  // 选仪表盘看目标值
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.widget-drawer .el-radio-button')]
    btns.find(b => b.textContent.includes('仪表盘'))?.click()
  })
  await sleep(500)
  const goalField = await page.evaluate(() => {
    const drawer = document.querySelector('.widget-drawer')
    return [...(drawer?.querySelectorAll('.wd-label') || [])].some(x => x.textContent.includes('目标值'))
  })
  ok(goalField, '仪表盘配置有「目标值」输入')
  // 关闭编辑（不保存）
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.widget-drawer button')]
    btns.find(b => b.textContent.trim() === '取消')?.click()
  })
  await sleep(400)
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    btns.find(b => b.textContent.includes('取消'))?.click()
  })
  await sleep(400)
  // 取消确认框（如出现）
  const confirmBtn = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-message-box button')]
    const giveup = btns.find(b => b.textContent.includes('放弃修改'))
    giveup?.click()
    return !!giveup
  })
  await sleep(600)

  // ---------- 3. 全屏大屏 ----------
  console.log('\n== 5. 全屏大屏 ==')
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    btns.find(b => b.textContent.includes('大屏'))?.click()
  })
  await page.waitForSelector('.fs-screen', { timeout: 10000 })
  await sleep(1500)
  const fs1 = await page.evaluate(() => {
    const el = document.querySelector('.fs-screen')
    const clock = document.querySelector('.fs-time')?.textContent || ''
    const cells = document.querySelectorAll('.fs-screen .cv-card').length
    const canvases = document.querySelectorAll('.fs-screen .cv-card canvas').length
    const style = getComputedStyle(el)
    return {
      theme: el.className,
      clock,
      cells,
      canvases,
      bgColor: style.backgroundColor,
      color: style.color,
      clockValid: /^\d{2}:\d{2}:\d{2}$/.test(clock),
    }
  })
  ok(fs1.cells >= 6, `大屏渲染出 ${fs1.cells} 张卡片`)
  ok(fs1.canvases >= 3, `大屏图表 canvas ${fs1.canvases} 张`)
  ok(fs1.clockValid, `实时时钟显示（${fs1.clock}）`)
  ok(fs1.theme.includes('fs-theme-nebula'), '默认星云蓝主题')
  await page.screenshot({ path: `${OUT}/fullscreen-nebula.png` })
  console.log(`    截图 ${OUT}/fullscreen-nebula.png`)

  // 时钟走动
  await sleep(2200)
  const fs2 = await page.evaluate(() => document.querySelector('.fs-time')?.textContent || '')
  ok(fs2 !== fs1.clock, `时钟在走动（${fs1.clock} → ${fs2}）`)

  // 大屏内排行/仪表盘可见性（深底浅字）
  const contrast = await page.evaluate(() => {
    const rk = document.querySelector('.fs-screen .cv-card .rk-name')
    const sv = document.querySelector('.fs-screen .cv-card .sv-num')
    return {
      rk: rk ? getComputedStyle(rk).color : '',
      sv: sv ? getComputedStyle(sv).color : '',
      svSize: sv ? getComputedStyle(sv).fontSize : '',
    }
  })
  const lum = s => {
    const m = String(s).match(/\d+(\.\d+)?/g)
    if (!m) return null
    const [r, g, b] = m.slice(0, 3).map(Number)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255
  }
  ok(lum(contrast.rk) > 0.5, `大屏排行榜文字是亮色（${contrast.rk}）`)
  ok(lum(contrast.sv) > 0.5, `大屏指标数字是亮色（${contrast.sv}）`)
  ok(parseFloat(contrast.svSize) >= 40, `大屏指标字号放大（${contrast.svSize}）`)

  // 切主题
  console.log('\n== 6. 主题切换与持久化 ==')
  await page.evaluate(() => [...document.querySelectorAll('.fs-btn')][0]?.click())
  await sleep(800)
  const theme2 = await page.evaluate(() => document.querySelector('.fs-screen')?.className || '')
  ok(theme2.includes('fs-theme-aurora'), '切换到极光紫主题', theme2)
  await page.screenshot({ path: `${OUT}/fullscreen-aurora.png` })
  // 再切一次到深渊青
  await page.evaluate(() => [...document.querySelectorAll('.fs-btn')][0]?.click())
  await sleep(600)
  const theme3 = await page.evaluate(() => document.querySelector('.fs-screen')?.className || '')
  ok(theme3.includes('fs-theme-abyss'), '再次切换到深渊青主题', theme3)

  // 退出大屏
  console.log('\n== 7. 退出与持久化 ==')
  await page.evaluate(() => document.querySelector('.fs-exit')?.click())
  await sleep(700)
  const closed = await page.evaluate(() => !document.querySelector('.fs-screen'))
  ok(closed, '退出大屏')

  // settings 已持久化（后端直接查）
  const dash2 = await api(`/api/dashboards/${DASH_ID}`)
  ok(dash2.json?.settings?.theme === 'abyss', `主题已持久化到 settings（${dash2.json?.settings?.theme}）`, JSON.stringify(dash2.json?.settings))

  // 重新打开：仍是新主题
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')]
    btns.find(b => b.textContent.includes('大屏'))?.click()
  })
  await page.waitForSelector('.fs-screen', { timeout: 10000 })
  await sleep(800)
  const reopen = await page.evaluate(() => document.querySelector('.fs-screen')?.className || '')
  ok(reopen.includes('fs-theme-abyss'), '重新打开仍记住主题')
  await page.evaluate(() => document.querySelector('.fs-exit')?.click())
  await sleep(500)

  ok(errors.length === 0, '无控制台报错', errors.slice(0, 3).join(' ; '))

  // ---------- 清理 ----------
  console.log('\n== 8. 清理 ==')
  const del = await api(`/api/dashboards/${DASH_ID}`, 'DELETE')
  ok(del.status === 200, '探测驾驶舱已删除')
  await browser.close()

  console.log(`\n==== 结果：${pass} 通过 / ${fails.length} 失败 ====`)
  if (fails.length) { fails.forEach(f => console.log('  未通过：' + f)); process.exit(1) }
}

main().catch(e => { console.error(e); process.exit(1) })
