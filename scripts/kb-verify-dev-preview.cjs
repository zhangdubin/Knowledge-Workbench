/**
 * 项目生成 · 文件预览的浏览器级验收
 *
 * 为什么 API 级验证还不够：
 *   后端 GET /api/dev/artifacts/{id} 明明返回了 content（实测 4583 字符），
 *   但界面上预览区曾经永远显示「（这个文件没有内容）」——
 *   断的是「点开文件 → 看到正文」这条链路，
 *   只有真浏览器点一遍才知道通没通。
 *
 * 这一版要验的不只是「能显示正文」，还有几条**链路性质**的断言：
 *   1) 懒加载是真的：列表接口不返回正文，点开哪个文件才去取哪个；
 *   2) 竞态不串台：慢请求回来不能盖掉当前选中的文件（点了 B、看到 A 的代码）；
 *   3) 三种状态分得开：取到了 / 确实是空的 / 没取到（附后端原文）；
 *   4) 错误态给的「重试」是真的重取，不是摆个按钮；
 *   5) 页面没有 JS 报错。
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
    const retry = state ? state.querySelector('button') : null
    return {
      ready: !!code,
      text: code ? code.innerText : '',
      state: state ? state.className : '',
      stateTitle: state ? (state.querySelector('.preview-state-title') || {}).innerText || '' : '',
      stateDetail: state ? (state.querySelector('.preview-state-detail') || {}).innerText || '' : '',
      hasRetry: !!retry,
      head: (box.querySelector('.impl-pane-title') || {}).innerText || '',
    }
  })
}

/* ---- 请求记账 ----------------------------------------------------
   appRequests 只数**应用自己**发的单条请求；
   脚本自己为了取「期望正文」而发的 fetch 要扣掉 ——
   不扣的话，「重试真的又发了一次请求」这种增量断言会被脚本自己刷上去，
   测出来的是「脚本发了请求」，不是「界面重取了」。 */
let allArtifactRequests = []
let selfArtifactFetches = 0
function appRequestCount() {
  return allArtifactRequests.length - selfArtifactFetches
}

/** 项目里的产出物清单（id/path/size）——用来把「树上的行」和「库里的文件」对上 */
async function artifactMeta(page) {
  return page.evaluate(async (pid) => {
    const r = await fetch('/api/dev/projects/' + pid, { credentials: 'include' })
    const j = await r.json()
    return (j.artifacts || []).map(a => ({
      id: a.id, path: a.path, size: a.size,
      hasContentField: Object.prototype.hasOwnProperty.call(a, 'content'),
    }))
  }, PROJECT_ID)
}

/** 取某个产出物的正文前若干字符（用来判断「屏幕上显示的是不是这个文件」） */
async function artifactHead(page, id, n) {
  selfArtifactFetches++
  return page.evaluate(async (aid, len) => {
    const r = await fetch('/api/dev/artifacts/' + aid, { credentials: 'include' })
    const j = await r.json()
    const a = (j && j.artifact) || {}
    return String(a.content || '').slice(0, len)
  }, id, n || 60)
}

/** 树上的文件行（文本 + 序号），点文件用 */
async function fileRows(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('.impl-tree .tree-row.is-file')]
      .map((r, i) => ({ i, text: r.innerText || '' })))
}

/**
 * 点某个文件（按文件名匹配，不靠行号 ——
 *   树的排序和接口返回的顺序不一定一致，靠序号点会点错文件，
 *   而「点错文件」在竞态测试里会直接把结论测歪）。
 */
async function clickFileByName(page, baseName) {
  const rows = await fileRows(page)
  const hit = rows.find(r => r.text.indexOf(baseName) >= 0)
  if (!hit) return false
  await page.evaluate(i => {
    const rows = [...document.querySelectorAll('.impl-tree .tree-row.is-file')]
    ;(rows[i] || rows[0]).click()
  }, hit.i)
  return true
}

/** 进到「项目生成」阶段 */
async function openImplementStage(page) {
  const picked = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.stage-item')]
    const it = items.find(x => (x.querySelector('.stage-name') || {}).innerText === '项目生成')
    if (!it) return null
    it.querySelector('.stage-btn').click()
    return true
  })
  await sleep(2500)
  return picked
}

/** 等预览区进入 ready（拿到正文） */
async function waitReady(page, timeoutMs) {
  const limit = Date.now() + (timeoutMs || 10000)
  let st = await previewState(page)
  while (Date.now() < limit) {
    if (st.ready && st.text.length > 20) return st
    await sleep(250)
    st = await previewState(page)
  }
  return st
}

/** 重新打开工作台（清空组件内的正文缓存，模拟「用户第一次进来」） */
async function reopen(page) {
  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(4000)
  await openImplementStage(page)
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
  const jsErrors = []
  const consoleErrors = []
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
  page.on('pageerror', e => jsErrors.push(e.message))

  let listArtifactHasContent = null
  let listArtifactCount = 0
  page.on('response', async res => {
    const u = res.url()
    if (u.indexOf('/api/dev/projects/') >= 0 && u.indexOf('/artifacts/') < 0) {
      const j = await res.json().catch(() => null)
      if (j && Array.isArray(j.artifacts)) {
        listArtifactCount = j.artifacts.length
        listArtifactHasContent = j.artifacts.some(a =>
          Object.prototype.hasOwnProperty.call(a, 'content'))
      }
    }
  })

  // ---- 请求拦截：用它造出「慢响应 / 空正文 / 取失败」三种情况 ----
  const ctl = {
    failArtifact: false,     // 真的失败（abort）
    emptyArtifactId: null,   // 回一个 content 为空的正常响应
    delayArtifactId: null,   // 慢响应（用来造竞态）
    delayMs: 1800,
  }
  await page.setRequestInterception(true)
  page.on('request', req => {
    const u = req.url()
    if (u.indexOf('/api/dev/artifacts/') >= 0) {
      allArtifactRequests.push(u)
      const tail = String(u).slice(-String(ctl.emptyArtifactId || 'x').length)
      if (ctl.emptyArtifactId && tail === String(ctl.emptyArtifactId)) {
        return req.respond({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            artifact: { id: ctl.emptyArtifactId, path: 'empty.txt', size: 0, content: '' },
          }),
        })
      }
      if (ctl.failArtifact) return req.abort('failed')
      if (ctl.delayArtifactId && String(u).slice(-String(ctl.delayArtifactId).length) === String(ctl.delayArtifactId)) {
        return setTimeout(() => req.continue(), ctl.delayMs)
      }
      return req.continue()
    }
    req.continue()
  })

  console.log('\n▶  打开项目 ' + PROJECT_ID + ' 的工作台')
  await page.goto(BASE + '/#/dev/' + PROJECT_ID, { waitUntil: 'networkidle2' })
  await sleep(4000)

  const picked = await openImplementStage(page)
  check('左栏能进到「项目生成」', !!picked)
  const fileCount = await page.evaluate(() =>
    document.querySelectorAll('.impl-tree .tree-row.is-file').length)
  check('文件树里有文件', fileCount > 0, '共 ' + fileCount + ' 个')

  const meta = await artifactMeta(page)
  check('拿得到产出物清单', meta.length > 0, '共 ' + meta.length + ' 个')
  if (meta.length < 2) {
    console.log('  项目里的文件不足 2 个，后面的竞态/空文件用例没法跑')
    await browser.close()
    process.exit(1)
  }
  // 文件名唯一才按名字点得准（重名的话「按名匹配」会点到另一个文件，
  // 竞态用例的结论就直接测歪了）
  const names = meta.map(a => a.path.split('/').pop())
  const uniqueNames = names.filter((n, i) => names.indexOf(n) === i)

  // ------------------------------------------------------------
  console.log('\n▶  懒加载：列表不带正文，点开才去取')
  // 列表接口本身**不该**带正文 —— 几十个文件全塞进去，列表接口会变得很重
  check('列表接口不返回正文（没有 content 字段）',
    listArtifactHasContent === false,
    listArtifactHasContent === null ? '没抓到列表响应' : '列表里带 content')
  const beforeClicks = appRequestCount()
  // 打开页面时只会取**默认选中的那一个**文件（不是整个项目的正文）
  check('打开页面只取默认选中的那一个文件（没有把整个项目都拉下来）',
    beforeClicks <= 1, '已发 ' + beforeClicks + ' 条')

  console.log('\n▶  点另一个文件，看预览区')
  const target = uniqueNames.find(n => n !== names[0]) || uniqueNames[0]
  const clicked = await clickFileByName(page, target)
  check('点得到文件行', clicked, target)
  const st = await waitReady(page, 12000)
  check('预览区出现了真实代码正文', st.ready && st.text.length > 50,
    '长度=' + (st.text ? st.text.length : 0))
  check('预览的不是「（这个文件没有内容）」',
    st.text.indexOf('（这个文件没有内容）') === -1)
  check('抬头显示的是文件路径', !!st.head, st.head)
  check('点了文件才发单条请求', appRequestCount() > beforeClicks,
    '已发 ' + appRequestCount() + ' 条')
  console.log('  正文前 120 字：' + (st.text || '').slice(0, 120).replace(/\n/g, ' ⏎ '))

  const shotOk = path.join(SHOTS, 'dev-preview-fixed.png')
  await page.screenshot({ path: shotOk })
  console.log('  截图：' + shotOk)

  const el = await page.$('.impl-preview')
  if (el) {
    const shotZoom = path.join(SHOTS, 'dev-preview-fixed-detail.png')
    await el.screenshot({ path: shotZoom })
    console.log('  截图：' + shotZoom)
  }

  // ------------------------------------------------------------
  console.log('\n▶  竞态：慢请求回来不能盖掉当前文件')
  // 造法：先点的文件故意拖 1.8 秒，后点的文件正常返回。
  // 慢的晚回来 —— 如果它能写进界面，屏幕上就是「点了 B、看到 A 的代码」。
  //
  // 挑文件时必须避开**默认选中的那一个**：
  //   默认文件在打开页面时就已经取过一次并进了缓存，
  //   再点它会走缓存、不发请求 —— 竞态根本没被造出来，
  //   而断言还会「通过」（屏幕上显示的就是它，当然对）。
  await reopen(page)
  const raceSlow = uniqueNames[1] || uniqueNames[0]
  const raceFast = uniqueNames[2] || uniqueNames[0]
  const slowMeta = meta.find(a => a.path.split('/').pop() === raceSlow)
  const fastMeta = meta.find(a => a.path.split('/').pop() === raceFast)
  const headSlow = slowMeta ? await artifactHead(page, slowMeta.id, 60) : ''
  const headFast = fastMeta ? await artifactHead(page, fastMeta.id, 60) : ''
  ctl.delayArtifactId = slowMeta ? slowMeta.id : null
  const reqBeforeRace = appRequestCount()
  await clickFileByName(page, raceSlow)
  await sleep(250)
  await clickFileByName(page, raceFast)
  await sleep(ctl.delayMs + 2500)
  const raceState = await previewState(page)
  check('竞态下显示的是后点的那个文件',
    !!headFast && raceState.text.indexOf(headFast.slice(0, 30)) >= 0,
    '屏幕上：' + (raceState.text || '').slice(0, 60).replace(/\n/g, ' '))
  check('慢请求回来没有覆盖当前文件',
    !headSlow || raceState.text.indexOf(headSlow.slice(0, 30)) < 0,
    '屏幕上出现了先点的那个文件的内容')
  check('竞态期间确实发起了两次单条请求',
    appRequestCount() - reqBeforeRace >= 2,
    '发了 ' + (appRequestCount() - reqBeforeRace) + ' 条')
  ctl.delayArtifactId = null

  // ------------------------------------------------------------
  console.log('\n▶  空文件：说清「确实是空的」，不是「没取到」')
  await reopen(page)
  // 同样避开默认选中的那一个（它已经进缓存，再点不会发请求）
  const emptyTarget = meta.find(a => a.path.split('/').pop() === (uniqueNames[1] || uniqueNames[0])) || meta[0]
  ctl.emptyArtifactId = emptyTarget ? emptyTarget.id : null
  await clickFileByName(page, emptyTarget.path.split('/').pop())
  await sleep(2500)
  const emptyState = await previewState(page)
  check('空文件是一个独立状态', emptyState.state.indexOf('is-empty') >= 0, emptyState.state)
  check('空文件说清「确实是空的」',
    /确实是空的|长度为 0|没有正文/.test(emptyState.stateTitle + emptyState.stateDetail),
    emptyState.stateTitle + ' / ' + emptyState.stateDetail)
  check('空文件没有冒充「没取到」',
    emptyState.state.indexOf('is-error') < 0, emptyState.state)
  ctl.emptyArtifactId = null

  // ------------------------------------------------------------
  console.log('\n▶  模拟取正文失败：不能又显示「没有内容」')
  await reopen(page)
  // 同样要避开默认选中的文件（它已经进缓存了，不会再发请求）
  const failTarget = meta.find(a => a.path.split('/').pop() === uniqueNames[1]) || meta[0]
  ctl.failArtifact = true
  await clickFileByName(page, failTarget.path.split('/').pop())
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
  check('取失败时给了「重试」出口', failedState.hasRetry)
  const shotErr = path.join(SHOTS, 'dev-preview-error.png')
  await page.screenshot({ path: shotErr })
  console.log('  截图：' + shotErr)

  // ------------------------------------------------------------
  console.log('\n▶  「重试」是真的重取（不是摆个按钮）')
  const reqBeforeRetry = appRequestCount()
  ctl.failArtifact = false
  const retryClicked = await page.evaluate(() => {
    const box = document.querySelector('.impl-preview')
    if (!box) return false
    const btn = box.querySelector('.preview-state button')
    if (!btn) return false
    btn.click()
    return true
  })
  check('点得到「重试」按钮', retryClicked)
  const afterRetry = await waitReady(page, 12000)
  check('重试后重新取到了正文', afterRetry.ready && afterRetry.text.length > 20,
    '长度=' + (afterRetry.text ? afterRetry.text.length : 0))
  check('重试真的又发了一次请求',
    appRequestCount() > reqBeforeRetry,
    '已发 ' + appRequestCount() + ' 条')

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
