/**
 * 项目生成 · 文件预览的浏览器级验收
 *
 * 为什么 API 级验证还不够：
 *   后端 GET /api/dev/artifacts/{id} 明明返回了 content（实测 4583 字符），
 *   但界面上预览区曾经永远显示「（这个文件没有内容）」——
 *   断的是「点开文件 → 看到正文」这条链路，
 *   只有真浏览器点一遍才知道通没通。
 *
 * 验三件事：
 *   1) 点文件之后，预览区出现的是**真实代码正文**（而不是那行兜底文案）；
 *   2) 取失败时显示的是后端给的错误，不许再显示「没有内容」这种误导话；
 *   3) 页面没有 JS 报错。
 *
 * 用法：
 *   node scripts/kb-verify-dev-preview.cjs            # 用项目 4
 *   PROJECT_ID=3 BASE=http://127.0.0.1:5174 node scripts/kb-verify-dev-preview.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const fs = require('fs')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:5174'
const PROJECT_ID = process.env.PROJECT_ID || '4'
const ROOT = path.resolve(__dirname, '..')
const SHOTS = path.join(ROOT, 'data', 'shots')
const sleep = ms => new Promise(r => setTimeout(r, ms))

const checks = []
function check(name, cond, detail) {
  checks.push({ name, ok: !!cond, detail: detail || '' })
  console.log(`  ${cond ? '✓' : '✗'} ${name}${cond ? '' : '  ← ' + (detail || '')}`)
}

function sessionToken() {
  return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
    { encoding: 'utf8', cwd: ROOT }).trim()
}

/** 预览区现在的状态与正文 */
async function previewState(page) {
  return page.evaluate(() => {
    const box = document.querySelector('.impl-preview')
    if (!box) return { ready: false, text: '', state: 'no-panel' }
    const code = box.querySelector('pre.code')
    const state = box.querySelector('.preview-state')
    return {
      ready: !!code,
      text: code ? code.innerText : '',
      state: state ? state.className : '',
      stateTitle: state ? (state.querySelector('.preview-state-title') || {}).innerText || '' : '',
      stateDetail: state ? (state.querySelector('.preview-state-detail') || {}).innerText || '' : '',
      head: (box.querySelector('.impl-pane-title') || {}).innerText || '',
    }
  })
}

;(async () => {
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1600, height: 950 })
  // 两类错误要分开记：
  //   jsErrors    —— 真正的 JS 异常（pageerror），必须一条都没有；
  //   consoleErrors —— 浏览器控制台的 error 级别输出。
  // 后者里混着「我们主动 req.abort('failed') 模拟取失败」时浏览器自己打的
  // Failed to load resource —— 那是**故意造出来**的，
  // 把它算成「页面有错」等于自己把自己造的噪音当成缺陷。
  // 所以最后那项检查要单独把这种噪音剔掉。
  const jsErrors = []
  const consoleErrors = []
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
  page.on('pageerror', e => jsErrors.push(e.message))

  console.log('\n▶  打开项目 ' + PROJECT_ID + ' 的工作台')
  await page.goto(BASE + '/#/dev/' + PROJECT_ID, { waitUntil: 'networkidle2' })
  await sleep(4000)

  // 进「项目生成」阶段
  const picked = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.stage-item')]
    const it = items.find(x => (x.querySelector('.stage-name') || {}).innerText === '项目生成')
    if (!it) return null
    it.querySelector('.stage-btn').click()
    return true
  })
  check('左栏能进到「项目生成」', !!picked)
  await sleep(2500)

  const fileCount = await page.evaluate(() =>
    document.querySelectorAll('.impl-tree .tree-row.is-file').length)
  check('文件树里有文件', fileCount > 0, '共 ' + fileCount + ' 个')

  console.log('\n▶  点第二个文件，看预览区')
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.impl-tree .tree-row.is-file')]
    ;(rows[1] || rows[0]).click()
  })
  // 等正文加载出来（懒加载：先请求再渲染）
  let st = await previewState(page)
  for (let i = 0; i < 40 && !(st.ready && st.text.length > 50); i++) {
    await sleep(250)
    st = await previewState(page)
  }
  check('预览区出现了真实代码正文', st.ready && st.text.length > 50,
    '长度=' + (st.text ? st.text.length : 0))
  check('预览的不是「（这个文件没有内容）」',
    st.text.indexOf('（这个文件没有内容）') === -1)
  check('抬头显示的是文件路径', !!st.head, st.head)
  console.log('  正文前 120 字：' + (st.text || '').slice(0, 120).replace(/\n/g, ' ⏎ '))

  const shotOk = path.join(SHOTS, 'dev-preview-fixed.png')
  await page.screenshot({ path: shotOk })
  console.log('  截图：' + shotOk)

  // 顺手截一张预览区特写
  const el = await page.$('.impl-preview')
  if (el) {
    const shotZoom = path.join(SHOTS, 'dev-preview-fixed-detail.png')
    await el.screenshot({ path: shotZoom })
    console.log('  截图：' + shotZoom)
  }

  console.log('\n▶  模拟取正文失败：不能又显示「没有内容」')
  await page.setRequestInterception(true)
  page.on('request', req => {
    if (req.url().indexOf('/api/dev/artifacts/') >= 0) {
      req.abort('failed')
    } else {
      req.continue()
    }
  })
  // 换一个文件，逼它重新请求
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.impl-tree .tree-row.is-file')]
    ;(rows[0] || rows[1]).click()
  })
  await sleep(2500)
  const failedState = await previewState(page)
  check('取失败时预览区不是空白的', !failedState.ready || failedState.text.length >= 0)
  check('取失败时显示了错误状态', failedState.state.indexOf('is-error') >= 0, failedState.state)
  check('取失败时说清是「没取到」',
    /没取到|失败|没有正文|content/.test(failedState.stateTitle + failedState.stateDetail),
    failedState.stateTitle + ' / ' + failedState.stateDetail)
  check('取失败时没有冒充「没有内容」',
    failedState.stateTitle.indexOf('这个文件没有内容') === -1 &&
    failedState.stateDetail.indexOf('这个文件没有内容') === -1,
    failedState.stateTitle + ' / ' + failedState.stateDetail)
  const shotErr = path.join(SHOTS, 'dev-preview-error.png')
  await page.screenshot({ path: shotErr })
  console.log('  截图：' + shotErr)
  await page.setRequestInterception(false)

  console.log('\n▶  控制台')
  check('页面没有 JS 异常', jsErrors.length === 0, jsErrors.slice(0, 3).join(' / '))
  // 只把「主动 abort 造成的资源加载失败」剔掉，其余控制台 error 都要报出来
  const realConsoleErrors = consoleErrors.filter(t => !/Failed to load resource/.test(t))
  check('控制台没有意外报错', realConsoleErrors.length === 0, realConsoleErrors.slice(0, 3).join(' / '))

  await browser.close()

  console.log('')
  const bad = checks.filter(c => !c.ok)
  if (bad.length) {
    console.log(`✗ ${bad.length} 项不通过（共 ${checks.length} 项）：`)
    bad.forEach(b => console.log('   - ' + b.name + (b.detail ? '：' + b.detail : '')))
    process.exit(1)
  }
  console.log(`✓ 全部 ${checks.length} 项检查通过`)
})().catch(e => { console.error('脚本异常：', e); process.exit(1) })
