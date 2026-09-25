/**
 * 数据模型删除链路 UI 验证
 *
 * 背景：模型建完之后，前端只在 /types 列表里点一下就进了记录页，
 * 「删除」入口压根不存在（Api.deleteEntityType 定义了却无人调用）。
 * 本脚本端到端验证新增的入口与守门：
 *   卡片 ⋯ 菜单 → 删除模型 → 输入 Key 确认 → 列表刷新
 * 并特意覆盖两条容易漏的路径：
 *   - 模型下**有记录**时的删除（CASCADE 会一起带走）
 *   - Key 输错时必须拦住（negative case）
 *
 * 探测用的模型是脚本自己建的，跑完即删，不碰任何既有模型。
 *
 *   KB_SESSION_TOKEN=xxx node scripts/v18-verify-model-delete.cjs
 */
const { createRequire } = require('module')
const fs = require('fs')
const path = require('path')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = process.env.KB_SHOT_DIR || '/tmp/kb-model-delete'
const PROBE_KEY = '__v18_del_probe'
const PROBE_NAME = 'V18删除探测'

const sleep = ms => new Promise(r => setTimeout(r, ms))

async function main() {
  if (!TOKEN) {
    console.error('缺少 KB_SESSION_TOKEN')
    process.exit(1)
  }
  fs.mkdirSync(OUT, { recursive: true })

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1500, height: 950, deviceScaleFactor: 2 })
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(`console: ${m.text()}`) })
  page.on('pageerror', e => errors.push(`pageerror: ${e}`))
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })

  // 借用页面自身的会话直接打 API：省得在脚本里再拼一套认证
  // URL 必须绝对化 —— about:blank 上没有 base，相对路径会直接抛 TypeError
  const api = (p, method = 'GET', body) => page.evaluate(async (url, method, body) => {
    const r = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { status: r.status, json: await r.json().catch(() => null) }
  }, `${FE}${p}`, method, body)

  const shots = []
  const snap = async (name) => {
    const f = path.join(OUT, `${name}.png`)
    await page.screenshot({ path: f })
    shots.push(f)
    console.log('  ✓', `${name}.png`)
  }
  const check = (label, ok, extra = '') =>
    console.log(`  ${ok ? '✓' : '✗'} ${label}${extra ? ' — ' + extra : ''}`)

  // ---------- 1. 造一个带记录的探测模型 ----------
  console.log('\n[1/7] 建探测模型（含 2 字段 + 1 条记录）')
  // 先落到目标源上，cookie 才会随请求带出去
  await page.goto(`${FE}/#/types`, { waitUntil: 'domcontentloaded' })
  // 上一轮跑挂了会留下同 key 的残留，先清掉，保证脚本可重复执行
  const pre = await api('/api/entity-types')
  const stale = (pre.json || []).find(t => t.key === PROBE_KEY)
  if (stale) {
    await api(`/api/entity-types/${stale.id}`, 'DELETE')
    console.log(`    清掉上次残留 #${stale.id}`)
  }
  const created = await api('/api/entity-types', 'POST', {
    key: PROBE_KEY, name: PROBE_NAME, icon: 'Document', description: 'UI 删除链路验证用',
    app: 'default', order: 999,
    fields: [
      { key: 'name', name: '名称', type: 'text', required: true, options: {}, order: 1 },
      { key: 'amount', name: '金额', type: 'number', required: false, options: {}, order: 2 },
    ],
  })
  if (created.status >= 300) throw new Error(`建模型失败 ${created.status} ${JSON.stringify(created.json)}`)
  const probeId = created.json.id
  console.log(`    模型 #${probeId} 已建`)
  const rec = await api(`/api/records/type/${probeId}`, 'POST', { data: { name: '待删记录', amount: 1 } })
  check('记录已写入', rec.status < 300, `status=${rec.status}`)

  // ---------- 2. 打开数据模型页 ----------
  console.log('\n[2/7] 打开 /#/types')
  await page.goto(`${FE}/#/types`, { waitUntil: 'networkidle2' })
  // 步骤 1 已经落在这个 URL 上过（为了带 cookie），再 goto 同一个 URL 在 Chrome 里
  // 只是 hash 变更：组件不会重新挂载，列表还是建模型之前那一份。
  // 必须强制 reload 才能拿到新数据 —— 否则这里会一直等不到探测模型那张卡片。
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.entity-tile', { timeout: 20000 })
  await page.waitForFunction(
    (n) => [...document.querySelectorAll('.entity-tile .name')].some(e => e.textContent.includes(n)),
    { timeout: 15000 }, PROBE_NAME,
  )
  await sleep(800)
  await snap('01-model-list')

  // ---------- 2b. 模型编辑页也提供删除入口 ----------
  console.log('\n[2b/7] 编辑页入口')
  await page.goto(`${FE}/#/types/${probeId}/edit`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.field-row', { timeout: 15000 })
  await sleep(700)
  const hasDelBtn = await page.$$eval('button', els =>
    els.some(b => b.textContent.trim().includes('删除模型'))
  )
  check('编辑页有「删除模型」按钮', hasDelBtn)
  await snap('02b-editor-delete-btn')

  // 回到列表继续走删除流程
  await page.goto(`${FE}/#/types`, { waitUntil: 'networkidle2' })
  // 同上：再跑一次 reload 确保列表组件重新挂载，数据最新
  await page.reload({ waitUntil: 'networkidle2' })

  // ---------- 3. 展开卡片菜单 ----------
  console.log('\n[3/7] 悬停卡片 → 打开 ⋯ 菜单')
  await page.waitForFunction(
    (n) => [...document.querySelectorAll('.entity-tile')]
      .some(e => e.querySelector('.name')?.textContent.includes(n)),
    { timeout: 15000 }, PROBE_NAME,
  )
  const tile = await page.evaluateHandle((n) => {
    return [...document.querySelectorAll('.entity-tile')]
      .find(e => e.querySelector('.name')?.textContent.includes(n))
  }, PROBE_NAME)
  await tile.asElement().hover()
  await sleep(300)
  await snap('02-tile-hover')
  await tile.asElement().$eval('.tile-menu-btn', el => el.click())
  // 注意：每张卡片的菜单 popper 都在 DOM 里，只是隐藏着 —— 必须按可见性过滤，
  // 否则 $$('.el-dropdown-menu__item') 会捞到全部卡片 + 顶栏头像菜单的项，
  // 后面按文字点「删除模型」就会点到别的模型上（实测踩到过）。
  await page.waitForFunction(
    () => [...document.querySelectorAll('.el-dropdown-menu__item')]
      .some(e => e.offsetParent !== null && e.textContent.includes('删除模型')),
    { timeout: 8000 },
  )
  await sleep(400)
  const items = await page.$$eval('.el-dropdown-menu__item',
    els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim()))
  check('菜单项齐全',
    ['查看记录', '编辑模型', '导出 JSON', '删除模型'].every(x => items.some(i => i.includes(x))),
    items.join(' / '))
  await snap('03-dropdown-menu')

  // 只在**可见**的菜单里点，避免误伤隐藏菜单
  const clickVisibleItem = (text) => page.evaluate((text) => {
    const el = [...document.querySelectorAll('.el-dropdown-menu__item')]
      .find(e => e.offsetParent !== null && e.textContent.includes(text))
    if (!el) return false
    el.click()
    return true
  }, text)

  // ---------- 4. 点删除 → 确认框 ----------
  console.log('\n[4/7] 点「删除模型」')
  check('找到可见的删除项', await clickVisibleItem('删除模型'))
  await page.waitForSelector('.el-message-box', { timeout: 8000 })
  await sleep(500)
  const boxText = await page.$eval('.el-message-box__content', el => el.innerText)
  const hasInput = await page.$('.el-message-box__input input') !== null
  check('确认框指向本模型', boxText.includes(PROBE_NAME), boxText.replace(/\s+/g, ' ').slice(0, 60))
  check('确认框要求输入 Key', hasInput)
  check('提示了记录数', boxText.includes('1 条记录'), boxText.replace(/\s+/g, ' ').slice(0, 110))
  await snap('04-confirm-dialog')

  // ---------- 5. negative：Key 输错必须拦住 ----------
  console.log('\n[5/7] 负例：故意输错 Key')
  const inputSel = '.el-message-box__input input'
  const typeIntoBox = async (text) => {
    // 用 focus + 键盘输入而不是 page.click：对话框刚渲染时坐标点可能还没稳定，
    // 直接点会抛 "Node is either not clickable"。
    // 清空必须补一个 input 事件，否则只改了 DOM，ElMessageBox 的 v-model 还留着旧值。
    await page.$eval(inputSel, el => {
      el.value = ''
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.focus()
    })
    await page.keyboard.type(text)
  }
  await typeIntoBox('wrong-key')
  await page.evaluate(() => {
    [...document.querySelectorAll('.el-message-box__btns button')]
      .find(b => b.textContent.includes('确认删除'))?.click()
  })
  await sleep(700)
  const stillOpen = await page.$('.el-message-box') !== null
  const errShown = await page.evaluate(() => !!document.querySelector('.el-message-box__errormsg'))
  check('输错时不关闭、不放行', stillOpen && errShown)
  await snap('05-guard-wrong-key')
  const aliveAfterWrong = await api(`/api/entity-types/${probeId}`)
  check('模型仍存在', aliveAfterWrong.status === 200)

  // ---------- 6. 输对 Key → 真删 ----------
  console.log('\n[6/7] 输对 Key 并确认')
  await typeIntoBox(PROBE_KEY)
  await sleep(200)
  await page.evaluate(() => {
    [...document.querySelectorAll('.el-message-box__btns button')]
      .find(b => b.textContent.includes('确认删除'))?.click()
  })
  await page.waitForFunction(() => !document.querySelector('.el-message-box'), { timeout: 10000 })
  await page.waitForFunction(
    (n) => ![...document.querySelectorAll('.entity-tile .name')].some(e => e.textContent.includes(n)),
    { timeout: 15000 }, PROBE_NAME,
  )
  await sleep(700)
  await snap('06-after-delete')

  const gone = await api(`/api/entity-types/${probeId}`)
  check('接口层已查不到该模型', gone.status === 404, `status=${gone.status}`)
  const list = await api('/api/entity-types')
  const keys = (list.json || []).map(t => t.key)
  check('列表里已消失', !keys.includes(PROBE_KEY))
  check('既有模型未被误删', keys.includes('feiyong') && keys.includes('project'), `共 ${keys.length} 个`)

  // ---------- 7. 清理 ----------
  console.log('\n[7/7] 清理探测数据')
  if (gone.status !== 404) {
    await api(`/api/entity-types/${probeId}`, 'DELETE')
    console.log('    残留模型已强制清除')
  } else {
    console.log('    无残留')
  }

  if (errors.length) {
    console.log('\n浏览器错误：')
    errors.slice(0, 10).forEach(e => console.log('  !', e))
  } else {
    console.log('\n无浏览器报错')
  }
  console.log(`\n截图目录：${OUT}`)
  await browser.close()
}

main().catch(e => { console.error(e); process.exit(1) })
