// v11 UI 综合验证：全部路由 + 弹窗交互 + 关键组件渲染 + 截图
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const S = require('./lib/session.cjs')

const BASE = 'http://127.0.0.1:8082'
const SHOTS = '/tmp/shots11'

const ROUTES = [
  ['#/', '工作台'],
  ['#/apps', '应用中心'],
  ['#/notes', '知识库'],
  ['#/library', '数据中心'],
  ['#/types', '数据模型'],
  ['#/types/new', '新建模型'],
  ['#/graph', '关联图谱'],
  ['#/knowledge/graph', '知识图谱'],
  ['#/search', '全局搜索'],
  ['#/ai-settings', 'AI 设置'],
  ['#/no-such-page', '404'],
]

const IGNORE = /vis-data|hammerjs|deprecated|ResizeObserver|favicon|Download the Vue Devtools/i

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell', args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 950, deviceScaleFactor: 2 })

  await S.loginPage(page)

  const errors = []
  page.on('pageerror', e => errors.push(`[页面崩溃] ${e.message}`))
  page.on('console', msg => {
    if (msg.type() !== 'error') return
    const t = msg.text()
    if (!t || IGNORE.test(t)) return
    errors.push(`[控制台] ${t.slice(0, 200)}`)
  })
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400) errors.push(`[接口 ${r.status()}] ${r.url()}`)
  })

  console.log('====== 1. 路由遍历 ======')
  for (const [hash, name] of ROUTES) {
    const before = errors.length
    await page.goto(BASE + '/' + hash, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1200))
    const info = await page.evaluate(() => {
      const el = document.querySelector('h1, .page-title, .pt-title')
      return { title: el?.textContent?.trim() || '', len: document.body.innerText.length }
    })
    const ok = errors.length === before && info.len > 120
    console.log(`${ok ? '✅' : '❌'} ${name.padEnd(8)} 标题="${info.title}" 内容长度=${info.len}`)
  }

  console.log('\n====== 2. 动态路由 ======')
  // 取一个应用 key、一个实体类型 id、一条笔记 id
  const ctx = await page.evaluate(async () => {
    const j = async (u) => (await fetch(u)).json()
    const apps = await j('/api/apps')
    const types = await j('/api/entity-types')
    const noteType = types.find(t => t.key === 'note')
    let noteId = null
    if (noteType) {
      const r = await j(`/api/records/type/${noteType.id}?page=1&page_size=1`)
      noteId = r.items?.[0]?.id || null
    }
    return { appKey: apps?.[0]?.key, typeId: types?.[0]?.id, noteId, typeName: types?.[0]?.name }
  })
  const dyn = []
  if (ctx.appKey) dyn.push([`#/apps/${ctx.appKey}`, `应用详情(${ctx.appKey})`])
  if (ctx.typeId) dyn.push([`#/records/${ctx.typeId}`, `记录列表(${ctx.typeName})`])
  if (ctx.typeId) dyn.push([`#/types/${ctx.typeId}/edit`, '模型编辑'])
  if (ctx.noteId) dyn.push([`#/notes/${ctx.noteId}`, '笔记详情'])
  for (const [hash, name] of dyn) {
    const before = errors.length
    await page.goto(BASE + '/' + hash, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1400))
    const len = await page.evaluate(() => document.body.innerText.length)
    const ok = errors.length === before && len > 120
    console.log(`${ok ? '✅' : '❌'} ${name.padEnd(16)} 内容长度=${len}`)
  }

  console.log('\n====== 3. 弹窗与组件检查 ======')
  const checks = []

  // 3.1 应用中心 -> 新建应用弹窗（图标选择器）
  await page.goto(BASE + '/#/apps', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1200))
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('新建应用'))
    b && b.click()
  })
  await new Promise(r => setTimeout(r, 900))
  const appDlg = await page.evaluate(() => ({
    open: !!document.querySelector('.el-dialog'),
    iconChoices: document.querySelectorAll('.icon-choice').length,
    summary: !!document.querySelector('.dialog-summary'),
    footerBtns: document.querySelectorAll('.el-dialog__footer button').length,
  }))
  checks.push(['应用弹窗 · 图标选择器', appDlg.open && appDlg.iconChoices >= 12, `${appDlg.iconChoices} 个图标`])
  checks.push(['应用弹窗 · 摘要提示', appDlg.summary, ''])
  checks.push(['应用弹窗 · 底部按钮', appDlg.footerBtns >= 2, `${appDlg.footerBtns} 个`])
  await page.screenshot({ path: `${SHOTS}/dialog-apps.png` })
  await page.keyboard.press('Escape')
  await new Promise(r => setTimeout(r, 500))

  // 3.2 数据中心 -> JSON 试验场
  await page.goto(BASE + '/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1500))
  const lib = await page.evaluate(() => ({
    tabs: [...document.querySelectorAll('.el-tabs__item')].map(x => x.textContent.trim()),
    dropzone: !!document.querySelector('.dropzone'),
    viewToggle: !!document.querySelector('.toolbar .el-radio-group'),
  }))
  checks.push(['数据中心 · Tab 分段', lib.tabs.length >= 3, lib.tabs.join(' | ')])
  checks.push(['数据中心 · 上传区', lib.dropzone, ''])
  checks.push(['数据中心 · 视图切换', lib.viewToggle, ''])

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('JSON 试验场'))
    b && b.click()
  })
  await new Promise(r => setTimeout(r, 1000))
  const pg = await page.evaluate(() => ({
    open: !!document.querySelector('.playground'),
    tree: document.querySelectorAll('.jn-node, .pg-tree *').length,
  }))
  checks.push(['JSON 试验场 · 双栏', pg.open && pg.tree > 3, `${pg.tree} 个节点元素`])
  await page.screenshot({ path: `${SHOTS}/dialog-json.png` })
  await page.keyboard.press('Escape')
  await new Promise(r => setTimeout(r, 500))

  // 3.3 数据中心 -> 网格视图
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.toolbar .el-radio-button')]
    const grid = btns.find(b => b.textContent.trim() === '')
    grid && grid.click()
  })
  await new Promise(r => setTimeout(r, 800))
  const gridOk = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.toolbar .el-radio-button')]
    btns[btns.length - 1]?.querySelector('input')?.click()
    return true
  })
  await new Promise(r => setTimeout(r, 800))
  const gridCount = await page.evaluate(() => document.querySelectorAll('.file-tile').length)
  checks.push(['数据中心 · 网格视图', gridCount > 0, `${gridCount} 个磁贴`])
  await page.screenshot({ path: `${SHOTS}/library-grid.png` })

  // 3.4 知识库 -> 新建笔记弹窗
  await page.goto(BASE + '/#/notes', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1400))
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('新建笔记'))
    b && b.click()
  })
  await new Promise(r => setTimeout(r, 900))
  const noteDlg = await page.evaluate(() => ({
    open: !!document.querySelector('.el-dialog'),
    summary: !!document.querySelector('.dialog-summary'),
  }))
  checks.push(['笔记弹窗', noteDlg.open, noteDlg.summary ? '含摘要提示' : ''])
  await page.screenshot({ path: `${SHOTS}/dialog-note.png` })

  // 3.5 笔记详情 · 「编辑」必须回填表单（回归检查）
  if (ctx.noteId) {
    await page.goto(`${BASE}/#/notes/${ctx.noteId}`, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1600))
    const readLen = await page.evaluate(() => document.querySelector('.rendered')?.innerText?.length || 0)
    checks.push(['笔记详情 · 阅读视图', readLen > 0, `${readLen} 字`])
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === '编辑')
      b && b.click()
    })
    await new Promise(r => setTimeout(r, 1200))
    const editState = await page.evaluate(() => {
      const ta = document.querySelector('.editor')
      const titleIn = document.querySelector('.title-input input')
      return {
        hasEditor: !!ta,
        contentLen: ta?.value?.length || 0,
        titleValue: titleIn?.value || '',
      }
    })
    checks.push([
      '笔记详情 · 编辑回填',
      editState.hasEditor && editState.contentLen > 0 && editState.titleValue.length > 0,
      `标题「${editState.titleValue}」/ 正文 ${editState.contentLen} 字`,
    ])
    await page.screenshot({ path: `${SHOTS}/note-edit.png` })
  }

  console.log('')
  let failed = 0
  for (const [name, ok, extra] of checks) {
    if (!ok) failed++
    console.log(`${ok ? '✅' : '❌'} ${name.padEnd(24)} ${extra}`)
  }

  console.log('\n====== 4. 页面截图 ======')
  const SHOT_PAGES = [
    ['#/', 'dashboard'], ['#/apps', 'apps'], ['#/library', 'library'],
    ['#/notes', 'notes'], ['#/types', 'types'],
  ]
  for (const [hash, name] of SHOT_PAGES) {
    await page.goto(BASE + '/' + hash, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1600))
    await page.screenshot({ path: `${SHOTS}/${name}.png` })
    console.log('  shot', name)
  }

  console.log('\n====== 5. 错误汇总 ======')
  if (!errors.length) console.log('✅ 零错误')
  else { console.log(`❌ 共 ${errors.length} 条：`); errors.forEach(e => console.log('   ', e)) }

  await browser.close()
  process.exit(errors.length || failed ? 1 : 0)
})()
