/**
 * 知识库分组 全流程体检
 *
 * 为什么单独写一个：
 * 分组功能涉及「建 → 笔记进组 → 删组（两种安置方式）」，
 * 每一环都可能只在最后一步露馅（例如「组删了但笔记被一起删了」、
 * 「移出分组后笔记落进了谁也看不见的地方」）。
 *
 * **数据用接口造，断言用浏览器看**：
 *   上一版用「在界面上一步步点」来造数据，结果被 Element Plus 的
 *   弹层、焦点、动画搅得半真半假 —— 断言报的「问题」大半是自己点错元素。
 *   所以这里改成：接口负责造数（可靠），浏览器只负责回答
 *   「用户看到的对不对」（这才是界面该保证的事）。
 *
 * 断言全部用文本与计算样式，不截图。
 *
 * 用法：
 *   BASE=http://localhost:5173 API=http://localhost:8001 node scripts/v32-verify-note-groups.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')

const BASE = process.env.BASE || 'http://127.0.0.1:5173'
const API = process.env.API || 'http://127.0.0.1:8001'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let cookie = ''

async function api(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  return { status: res.status, data }
}

async function main() {
  const lr = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  })
  if (!lr.ok) {
    console.log(`✘ 接口登录失败（HTTP ${lr.status}）—— 体检无法进行`)
    process.exit(1)
  }
  cookie = (lr.headers.getSetCookie?.() || []).map((c) => c.split(';')[0]).join('; ')

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 1000 })

  const problems = []
  const ok = (msg) => console.log(`✔ ${msg}`)
  const bad = (msg) => { console.log(`✘ ${msg}`); problems.push(msg) }

  const sideRow = (name) => page.evaluate((n) => {
    const rows = Array.from(document.querySelectorAll('.ng-side-row'))
    const row = rows.find((r) => {
      const nm = r.querySelector('.ng-side-name')
      return nm && nm.textContent.trim() === n
    })
    if (!row) return null
    const num = row.querySelector('.ng-side-num')
    return { name: n, count: num ? num.textContent.trim() : null }
  }, name)

  const fixedRows = () => page.evaluate(() => {
    const out = {}
    for (const b of document.querySelectorAll('.ng-side-item')) {
      const nm = b.querySelector('.ng-side-name')
      const num = b.querySelector('.ng-side-num')
      if (nm && num) out[nm.textContent.trim()] = num.textContent.trim()
    }
    return out
  })

  const listTitles = () => page.evaluate(() => {
    const out = []
    for (const el of document.querySelectorAll('.note-row-title, .notes-item-title, .notes-title, .note-title, [data-note-title], .ng-note-title')) {
      const t = (el.textContent || '').trim()
      if (t && !out.includes(t)) out.push(t)
    }
    return out
  })

  const TAG = `体检组${Date.now().toString().slice(-4)}`
  const TAG2 = `${TAG}乙`
  const NOTE_A = `${TAG}笔记甲`
  const NOTE_B = `${TAG}笔记乙`

  try {
    // ---- 造数（接口）----
    const g1 = await api('POST', '/api/note-groups', { name: TAG, color: '#5b5fc7' })
    if (g1.status !== 201) { bad(`接口建分组失败（HTTP ${g1.status}）`); throw new Error('建组失败') }
    const g2 = await api('POST', '/api/note-groups', { name: TAG2, color: '#4a7fd4' })
    if (g2.status !== 201) { bad(`接口建第二个分组失败（HTTP ${g2.status}）`); throw new Error('建组失败') }

    const types = await api('GET', '/api/entity-types')
    const noteType = (types.data || []).find((t) => t.key === 'note')
    if (!noteType) { bad('找不到「笔记」模型'); throw new Error('无笔记模型') }

    const n1 = await api('POST', `/api/records/type/${noteType.id}`, {
      data: { title: NOTE_A, content: '体检用笔记甲', group_id: g1.data.id },
    })
    const n2 = await api('POST', `/api/records/type/${noteType.id}`, {
      data: { title: NOTE_B, content: '体检用笔记乙', group_id: g2.data.id },
    })
    if (n1.status >= 300 || n2.status >= 300) {
      bad(`接口建笔记失败（${n1.status} / ${n2.status}）`)
      throw new Error('建笔记失败')
    }
    const noteId = n1.data.id

    const counts = (await api('GET', '/api/note-groups')).data || []
    const c1 = counts.find((g) => g.id === g1.data.id)
    if (c1 && c1.count === 1) ok(`接口计数对：${TAG} = ${c1.count}`)
    else bad(`接口计数不对：${TAG} = ${c1 ? c1.count : '?'}`)

    // ---- 界面验收 ----
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(1200)
    const inputs = await page.$$('input')
    await inputs[0].click({ clickCount: 3 }); await inputs[0].press('Backspace')
    await inputs[0].type(USER, { delay: 8 })
    await inputs[1].click({ clickCount: 3 }); await inputs[1].press('Backspace')
    await inputs[1].type(PASS, { delay: 8 })
    await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll('button')).find((x) => (x.innerText || '').trim() === '登录')
      if (b) b.click()
    })
    for (let i = 0; i < 30; i++) {
      await sleep(500)
      if (!(await page.evaluate(() => String(location.hash).includes('/login')))) break
    }
    if (await page.evaluate(() => String(location.hash).includes('/login'))) {
      bad('登录失败'); throw new Error('登录失败')
    }
    ok('登录成功')

    await page.goto(`${BASE}/#/notes`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2500)

    const r1 = await sideRow(TAG)
    const r2 = await sideRow(TAG2)
    if (r1 && r1.count === '1') ok(`侧栏里 ${TAG} 的计数是 1`)
    else bad(`侧栏里 ${TAG} 的计数是 ${r1 ? r1.count : '没有这一行'}`)
    if (r2 && r2.count === '1') ok(`侧栏里 ${TAG2} 的计数是 1`)
    else bad(`侧栏里 ${TAG2} 的计数是 ${r2 ? r2.count : '没有这一行'}`)

    const fixed = await fixedRows()
    const allNum = Number(fixed['全部笔记'])
    const unNum = Number(fixed['未分组'])
    const groupSum = counts.reduce((s, g) => s + (g.count || 0), 0)
    if (allNum === unNum + groupSum) {
      ok(`「全部 ${allNum}」= 「未分组 ${unNum}」+ 各分组 ${groupSum}（对得上）`)
    } else {
      bad(`计数对不上：全部 ${allNum} ≠ 未分组 ${unNum} + 各分组 ${groupSum}`)
    }

    await page.evaluate((n) => {
      const btn = Array.from(document.querySelectorAll('.ng-side-item'))
        .find((x) => (x.querySelector('.ng-side-name') || {}).textContent?.trim() === n)
      if (btn) btn.click()
    }, TAG)
    await sleep(1800)
    const inGroup = await listTitles()
    if (inGroup.includes(NOTE_A)) ok(`点进 ${TAG}，列表里有那篇笔记`)
    else bad(`点进 ${TAG}，列表里没有那篇笔记（实际：${inGroup.slice(0, 5).join('、') || '空'}）`)
    if (!inGroup.includes(NOTE_B)) ok(`点进 ${TAG}，另一组的笔记不在列表里`)
    else bad(`点进 ${TAG}，另一组的笔记也混进来了`)

    const hash = await page.evaluate(() => location.hash)
    if (/group=/.test(hash)) ok(`地址栏记住了分组（${hash}）`)
    else bad(`地址栏没带分组参数（${hash}）`)

    await page.reload({ waitUntil: 'networkidle2' })
    await sleep(2200)
    const afterReload = await listTitles()
    if (afterReload.includes(NOTE_A)) ok('刷新后仍在同一个分组')
    else bad('刷新后分组丢了')

    await page.goto(`${BASE}/#/notes/${noteId}`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2200)
    const detailHasGroup = await page.evaluate(() => !!document.querySelector('.nd-group-select'))
    if (detailHasGroup) ok('笔记详情页有分组选择器')
    else bad('笔记详情页没有分组选择器')

    await page.goto(`${BASE}/#/notes`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2200)
    await page.evaluate((n) => {
      const btn = Array.from(document.querySelectorAll('.ng-side-more'))
        .find((b) => (b.getAttribute('aria-label') || '') === `${n} 的更多操作`)
      if (btn) btn.click()
    }, TAG)
    await sleep(900)
    await page.evaluate(() => {
      // 关掉的 el-dropdown 菜单仍留在 DOM 里，find() 取到的可能是上一个菜单的项。
      // 所以只认**看得见的**那一个。
      const item = Array.from(document.querySelectorAll('.el-dropdown-menu__item'))
        .find((x) => /删除分组/.test(x.innerText || '')
          && x.getBoundingClientRect().height > 0
          && x.closest('.el-dropdown-menu')?.getBoundingClientRect().height > 0)
      if (item) item.click()
    })
    await sleep(1200)
    const dlg = await page.evaluate(() => {
      const d = document.querySelector('.el-dialog')
      return d ? (d.innerText || '') : ''
    })
    if (/不会被删除|不会删/.test(dlg)) ok('删除前说清了「笔记不会被删除」')
    else bad(`删除对话框没说清笔记会不会被删（${dlg.slice(0, 60).replace(/\n/g, ' ')}）`)

    await page.evaluate(() => {
      const r = Array.from(document.querySelectorAll('.el-radio'))
        .find((x) => /移到其他分组/.test(x.innerText || ''))
      if (r) r.click()
    })
    await sleep(700)
    // 目标下拉要用**真实鼠标点**：Element Plus 的 select 监听的是
    // mousedown/click 组合，合成事件打不开弹层（点了没反应，还以为是自己脚本的锅）
    const targetSel = await page.evaluateHandle(() => {
      const list = Array.from(document.querySelectorAll('.el-dialog .el-select'))
        .filter((s) => s.getBoundingClientRect().height > 0)
      return list[list.length - 1] || null
    })
    const selEl = targetSel.asElement()
    if (selEl) {
      const inner = await selEl.$('.el-select__wrapper')
      const box = await (inner || selEl).boundingBox()
      if (box) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
      await sleep(1000)
    }
    // 目标项要用**这个下拉自己的**那一项：
    //   页面工具栏上还有一个分组筛选下拉，它的选项里也有同名的分组 ——
    //   不认准就点到了别人头上，下拉看着「选了」，对话框里的值却是空的。
    // Element Plus 用 aria-controls 把 select 和它的 popper 关联起来，按这个认。
    const picked = await page.evaluate((n) => {
      const sel = Array.from(document.querySelectorAll('.el-dialog .el-select'))
        .filter((s) => s.getBoundingClientRect().height > 0)
        .pop()
      if (!sel) return false
      const ctrl = sel.querySelector('[aria-controls]')?.getAttribute('aria-controls')
        || sel.getAttribute('aria-controls')
      let scope = ctrl ? document.getElementById(ctrl) : null
      if (!scope) {
        // 兜底：取最后一个可见的下拉（刚打开的那个）
        const dds = Array.from(document.querySelectorAll('.el-select-dropdown'))
          .filter((d) => d.getBoundingClientRect().height > 0)
        scope = dds[dds.length - 1]
      }
      if (!scope) return false
      const opt = Array.from(scope.querySelectorAll('.el-select-dropdown__item'))
        .find((x) => (x.innerText || '').trim().includes(n))
      if (opt) { opt.click(); return true }
      return false
    }, TAG2)
    if (!picked) {
      const dd = await page.evaluate(() => Array.from(document.querySelectorAll('.el-select-dropdown'))
        .map((d) => `items=${d.querySelectorAll('.el-select-dropdown__item').length} txt=${(d.innerText || '').slice(0, 40)}`))
      bad(`目标分组下拉里找不到「${TAG2}」（${dd.join(' ; ')}）`)
    }
    await sleep(600)
    await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll('.el-dialog button'))
        .find((x) => /删除分组/.test((x.innerText || '').trim()))
      if (b) b.click()
    })
    await sleep(2200)

    await page.goto(`${BASE}/#/notes`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2500)
    const stillThere = await sideRow(TAG)
    if (!stillThere) ok('分组已删除')
    else bad('分组没删掉')

    const after = (await api('GET', '/api/note-groups')).data || []
    const moved = after.find((g) => g.id === g2.data.id)
    if (moved && moved.count === 2) ok('笔记搬过去了，目标分组计数是 2')
    else bad(`搬过去的笔记没算进目标分组：${moved ? moved.count : '?'}`)

    const rec = await api('GET', `/api/records/${noteId}`)
    if (rec.status === 200) ok('笔记还在（没被连带删除）')
    else bad(`笔记不见了 —— 删分组把笔记一起删了（HTTP ${rec.status}）`)

    await api('DELETE', `/api/note-groups/${g2.data.id}`)
    // 两篇笔记都要删 —— 只删一篇的话，另一篇会留在用户的库里
    await api('DELETE', `/api/records/${noteId}`)
    await api('DELETE', `/api/records/${n2.data.id}`)
    const rest = (await api('GET', '/api/note-groups')).data || []
    // 只管自己造的那两个 —— 别人的残留不该算成我的问题
    const mine = rest.filter((g) => g.name === TAG || g.name === TAG2)
    if (!mine.length) ok('测试数据已清理干净')
    else bad(`测试数据没清干净：还剩 ${mine.map((g) => g.name).join('、')}`)

  } catch (e) {
    if (!problems.length) bad(`脚本异常：${e.message}`)
  } finally {
    await browser.close()
  }

  console.log('')
  if (problems.length) {
    console.log(`分组流程体检未通过：${problems.length} 项问题`)
    problems.forEach((p) => console.log(`  ✘ ${p}`))
    process.exit(1)
  } else {
    console.log('分组流程体检通过')
  }
}

main()
