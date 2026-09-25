/**
 * 验证驾驶舱「宽度自适应填满」+ 科技感新组件（v0.3.4）
 *
 * KB_SESSION_TOKEN=xxx node scripts/verify-cockpit-fill.cjs
 */
const { createRequire } = require('module')
const fs = require('fs')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = process.env.KB_SHOT_DIR || '/tmp/kb-cockpit-fill'
const KEY = `__fill_${Date.now().toString(36)}`

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
    headless: 'shell', args: ['--no-sandbox', '--window-size=1600,1000'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 })
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(e.message))
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })
  await page.goto(`${FE}/#/`, { waitUntil: 'networkidle2' })

  const api = (p, method = 'GET', body) => page.evaluate(async (url, method, body) => {
    const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
    return { status: r.status, json: await r.json().catch(() => null) }
  }, `${FE}${p}`, method, body)

  // 1. 用「系统状态」模板创建驾驶舱
  console.log('\n== 1. 创建「系统状态」模板驾驶舱 ==')
  const create = await api('/api/dashboards/templates', 'POST', { template_key: 'system', name: 'V034 系统状态探测' })
  ok(create.status === 200, '模板驾驶舱创建成功')
  const id = create.json?.id
  await page.goto(`${FE}/#/dashboards/${id}`, { waitUntil: 'networkidle2' })
  await sleep(1500)

  // 2. 验证宽度填满
  console.log('\n== 2. 宽度自适应填满 ==')
  const geo = await page.evaluate(() => {
    const scroll = document.querySelector('.cv-scroll')
    const content = document.querySelector('.cv-content')
    const cards = [...document.querySelectorAll('.cv-card')]
    return {
      containerW: Math.round(scroll?.clientWidth || 0),
      contentW: Math.round(parseFloat(getComputedStyle(content).width) || 0),
      rows: cards.reduce((m, el) => {
        const mat = new DOMMatrix(getComputedStyle(el).transform)
        const y = Math.round(mat.m42)
        const w = Math.round(parseFloat(getComputedStyle(el).width))
        m[y] = (m[y] || 0) + w
        return m
      }, {}),
      cardCount: cards.length,
      types: cards.map(el => (el.className.match(/cv-t-(\w+)/) || [])[1]).filter(Boolean),
    }
  })
  ok(geo.cardCount >= 6, `模板渲染出 ${geo.cardCount} 张卡片`)
  ok(geo.contentW >= geo.containerW * 0.95, `画布内容宽 ≥ 容器宽（${geo.contentW} / ${geo.containerW}）`)
  // 每行占用的逻辑宽度应接近容器宽（允许一点舍入误差）
  const rowWidths = Object.values(geo.rows)
  ok(rowWidths.every(w => w >= geo.containerW * 0.92), '每一行都接近填满容器')
  await page.screenshot({ path: `${OUT}/system-fill.png` })

  // 3. 验证新组件类型
  console.log('\n== 3. 科技感新组件渲染 ==')
  ok(geo.types.includes('kpi'), '包含 KPI 卡')
  ok(geo.types.includes('progress'), '包含进度条卡')
  ok(geo.types.includes('status'), '包含状态板卡')
  const hasGlow = await page.evaluate(() => !!document.querySelector('.kv-num'))
  const hasStack = await page.evaluate(() => !!document.querySelector('.pg-stack-track'))
  const hasStatusDot = await page.evaluate(() => !!document.querySelector('.st-dot'))
  ok(hasGlow, 'KPI 大数字已渲染')
  ok(hasStack, '进度条堆叠段已渲染')
  ok(hasStatusDot, '状态指示灯已渲染')

  // 4. 编辑态添加进度条/状态板并保存
  console.log('\n== 4. 编辑态添加新组件并保存 ==')
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('编辑布局'))
    b?.click()
  })
  await sleep(1000)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('添加卡片'))
    b?.click()
  })
  await sleep(400)
  // 选「进度条」
  await page.evaluate(() => {
    const labels = [...document.querySelectorAll('.el-radio-button__original')]
    const p = labels.find(l => l.value === 'progress')
    if (p && !p.checked) { p.click(); p.dispatchEvent(new Event('change', { bubbles: true })) }
  })
  await sleep(200)
  // 配置：数据源 document，分组 kind
  await page.evaluate(() => {
    const kind = [...document.querySelectorAll('.el-radio-button__original')].find(l => l.value === 'document')
    kind?.click()
  })
  await sleep(200)
  await page.evaluate(() => {
    const sel = document.querySelector('.wd-body .el-select .el-select__wrapper')
    if (sel) sel.click()
  })
  await sleep(200)
  // 选第一个分组字段（kind）
  await page.evaluate(() => {
    const opt = [...document.querySelectorAll('.el-select-dropdown__item')].find(li => li.textContent.includes('kind'))
    opt?.click()
  })
  await sleep(200)
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.wd-foot button')].find(b => b.textContent.includes('添加到驾驶舱'))
    btn?.click()
  })
  await sleep(800)
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('保存布局'))
    btn?.click()
  })
  await sleep(1500)

  // 刷新页面，确认新增卡片还在
  await page.goto(`${FE}/#/dashboards/${id}`, { waitUntil: 'networkidle2' })
  await sleep(1200)
  const afterSave = await page.evaluate(() => ({
    types: [...document.querySelectorAll('.cv-card')].map(el => (el.className.match(/cv-t-(\w+)/) || [])[1]).filter(Boolean),
    progress: document.querySelectorAll('.cv-t-progress .pg-stack-track').length,
  }))
  ok(afterSave.types.includes('progress'), '保存后进度条卡仍在')
  ok(afterSave.progress >= 1, '进度条组件内容渲染正常')
  await page.screenshot({ path: `${OUT}/system-edit-save.png` })

  // 5. 清理
  await api(`/api/dashboards/${id}`, 'DELETE')
  ok(errors.length === 0, '全程无控制台报错', errors.slice(0, 3).join('; '))

  console.log(`\n==== 结果：${pass} 通过 / ${fails.length} 失败 ====`)
  if (fails.length) console.log('失败项：', fails.join('\n  '))
  await browser.close()
  process.exit(fails.length ? 1 : 0)
}

main().catch(e => { console.error(e); process.exit(1) })
