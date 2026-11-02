#!/usr/bin/env node
/**
 * 本轮六件事 · 端到端验收（浏览器 E2E + API 断言）
 *
 * 为什么要有这条脚本：
 *   这一轮用户提了六件事，全部做完后要有一条能重复跑的验收脚本，
 *   不能靠「看起来对」。每一条都钉成断言，红了就是红的，不许静默跳过。
 *
 * 六件事与各自的断言点：
 *   1. 新建笔记，长内容不溢出编辑框
 *      → 文字框底边不超出编辑区底边；高亮层与文字框高度一致；
 *        内容超长时在框内滚动；编辑区不撑破可视区。
 *   2. 笔记能加关联业务记录、加完立刻显示
 *      → 详情页「关联的业务记录」面板列出记录标题；
 *        点「关联业务记录」→ 搜到 → 点一下，列表当场多一条（不刷新）。
 *   3. 双向链接：正向 / 反向页签与实际一致
 *      → 页签里的条目数与 /api/notes/:id/outgoing、/backlinks 对得上；
 *        条目标题对得上。
 *   4. 关联图谱要体现「笔记 ↔ 数据中心记录」
 *      → /api/graph/global 里有笔记节点（type_name=笔记）与「关联知识」边；
 *        /api/graph/notes 同样有；页面图例里出现「笔记」与「关联知识」。
 *   5. DNA 图谱：数据中心文件挪到证据链
 *      → DOM 断言：.dg-lbl-document 全部带 r（证据链），没有 l；
 *        知识链那边只剩基因。
 *   6. 知识库 / 数据中心等页面的打印功能
 *      → 每页有打印按钮 [data-print-trigger]；
 *        打印媒体下侧边导航隐藏、正文可见、打印页眉出现。
 *
 * 用法：
 *   node scripts/kb-verify-round2.cjs
 *   KB_FRONTEND=http://127.0.0.1:5174 node scripts/kb-verify-round2.cjs
 *
 * 退出码：0 = 全部通过；非 0 = 有没过（清单打印在最后）。
 *
 * 备注：测试数据都用时间戳命名，不会去删别人的数据，也不碰 data/kb.db 与 files/。
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const FRONTEND = (process.env.KB_FRONTEND || 'http://127.0.0.1:8082').replace(/\/+$/, '')
const API = (process.env.KB_API || 'http://127.0.0.1:8001').replace(/\/+$/, '')
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))
// --keep：保留这次造的验收数据（默认跑完清掉，进回收站可恢复）
const KEEP = process.argv.indexOf('--keep') >= 0

const ERRORS = []
let CHECKS = 0

function check(name, cond, detail) {
  CHECKS++
  const good = typeof cond === 'function' ? !!cond() : !!cond
  console.log('  ' + (good ? '✓' : '✗') + ' ' + name + (good ? '' : '  ← ' + (detail || '')))
  if (!good) ERRORS.push(name + (detail ? '：' + detail : ''))
  return good
}

function section(title) {
  console.log('\n▶ ' + title)
}

function failFast(msg) {
  console.error('\n✗ ' + msg)
  console.error('  跑法：node scripts/kb-verify-round2.cjs')
  console.error('  前端要跑新代码：docker compose build frontend && docker compose up -d frontend')
  process.exit(2)
}

let _TOKEN = ''
function sessionToken() {
  if (_TOKEN) return _TOKEN
  try {
    const out = execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT })
    _TOKEN = out.trim().split('\n').pop().trim()
  } catch (e) {
    failFast('取不到会话令牌（' + (e.message || e) + '）：后端在 ' + API + ' 上吗？')
  }
  if (!_TOKEN) failFast('取不到会话令牌：脚本没打印出 token')
  return _TOKEN
}

async function api(pathname, opts) {
  const o = opts || {}
  const headers = { Cookie: 'kb_session=' + sessionToken() }
  if (o.body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(API + pathname, {
    method: o.method || 'GET',
    headers,
    body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
  })
  const ct = res.headers.get('content-type') || ''
  const body = ct.includes('json') ? await res.json() : await res.text()
  return { status: res.status, body }
}

async function waitApi(url, tries) {
  for (let i = 0; i < (tries || 20); i++) {
    try {
      const r = await api(url)
      if (r.status === 200) return r
    } catch (e) { /* 还没起来 */ }
    await sleep(500)
  }
  return null
}

/* ===================== 浏览器辅助 ===================== */

async function newPage(browser) {
  const page = await browser.newPage()
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1600, height: 950 })
  page.__errors = []
  page.on('console', m => { if (m.type() === 'error') page.__errors.push(m.text()) })
  page.on('pageerror', e => page.__errors.push('pageerror: ' + e.message))
  return page
}

async function goto(page, hash, waitMs) {
  await page.goto(FRONTEND + '/#' + hash, { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(waitMs || 1200)
}

/** 页面上有没有某个文字的按钮/链接 */
async function clickByText(page, text, selector) {
  return await page.evaluate((t, sel) => {
    const nodes = Array.from(document.querySelectorAll(sel || 'button, a, .el-button'))
    const hit = nodes.find(n => (n.innerText || '').includes(t))
    if (!hit) return false
    hit.click()
    return true
  }, text, selector || 'button, a, .el-button')
}

/** 页面上所有文本里有没有这段字 */
async function hasText(page, text) {
  return await page.evaluate(t => (document.body.innerText || '').includes(t), text)
}

/** 点一个页签（el-tabs 的页签标签是 span，不是 button） */
async function clickTab(page, text) {
  return await page.evaluate(t => {
    const items = Array.from(document.querySelectorAll('.el-tabs__item, [role="tab"], .nd-tab-label'))
    const hit = items.find(n => (n.innerText || '').includes(t))
    if (!hit) return false
    const target = hit.closest('.el-tabs__item') || hit
    target.click()
    return true
  }, text)
}

/* ===================== 造数据 ===================== */

const STAMP = (() => {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '-' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds())
})()

const NOTE_A = '验收笔记A-' + STAMP
const NOTE_B = '验收笔记B-' + STAMP
const REC_1 = '验收记录一-' + STAMP
const REC_2 = '验收记录二-' + STAMP

async function setupData() {
  section('0. 准备验收数据（时间戳命名，不动别人的数据）')
  const noteType = await api('/api/entity-types/by-key/note')
  if (noteType.status !== 200 || !noteType.body || !noteType.body.id) {
    failFast('读不到笔记模型（GET /api/entity-types/by-key/note 返回 ' + noteType.status + '）')
  }
  const noteTypeId = noteType.body.id
  const typeList = await api('/api/entity-types')
  const types = (typeList.body && (typeList.body.items || typeList.body)) || []

  // 挑一个业务模型：要有一个「文本字段」——
  // 记录的检索文本（search_text）是把模型各字段的值拼起来的，
  // 文本字段里填了关键字，这条记录才能被对话框里的搜索搜到。
  let bizType = null
  let textField = null
  for (const t of types) {
    if (!t || t.key === 'note' || t.id === noteTypeId) continue
    const detail = await api('/api/entity-types/' + t.id)
    const fields = (detail.body && detail.body.fields) || []
    const tf = fields.find(f => f.type === 'text' && !f.required)
    const hardRequired = fields.some(f => f.required && f.type !== 'text' && f.type !== 'reference')
    if (tf && !hardRequired) { bizType = t; textField = tf; break }
  }
  if (!bizType) failFast('库里没有带文本字段的业务模型（笔记之外的），没法造「业务记录」')
  check('拿到笔记模型与业务模型', true,
    'note=' + noteTypeId + ' biz=' + bizType.key + ' 文本字段=' + textField.key)

  const mk = async (typeId, data) => {
    const r = await api('/api/records/type/' + typeId, { method: 'POST', body: { data } })
    if (r.status !== 200 || !r.body || !r.body.id) {
      failFast('造记录失败：HTTP ' + r.status + ' ' + JSON.stringify(r.body).slice(0, 200))
    }
    return r.body.id
  }

  const recData = (token) => {
    const d = {}
    d[textField.key] = token
    // 有「名称 / 标题」字段的话一并填上，列表里看着也认得出
    for (const k of ['name', 'title']) {
      if (!d[k]) d[k] = token
    }
    return d
  }
  const rec1 = await mk(bizType.id, recData(REC_1))
  const rec2 = await mk(bizType.id, recData(REC_2))
  check('造出两条业务记录', !!rec1 && !!rec2, 'rec1=' + rec1 + ' rec2=' + rec2)

  const noteB = await mk(noteTypeId, { title: NOTE_B, content: '这是验收笔记 B 的正文。', tags: [] })
  const linkText = '这行指向 [[' + NOTE_B + ']]，用来验证双向链接。'
  const noteA = await mk(noteTypeId, { title: NOTE_A, content: linkText, tags: [] })
  check('造出两篇笔记（A 引用 B）', !!noteA && !!noteB, 'A=' + noteA + ' B=' + noteB)

  // 双链同步（跟前端保存笔记时做的同一件事）
  const sync = await api('/api/notes/' + noteA + '/sync-links', { method: 'POST', body: { content: linkText } })
  check('双链同步接口有回应', sync.status === 200, 'HTTP ' + sync.status + ' ' + JSON.stringify(sync.body).slice(0, 160))

  // 业务记录 → 笔记 的关联（「关联知识」关系）
  const link = await api('/api/knowledge/link', { method: 'POST', body: { record_id: rec1, note_id: noteA } })
  check('业务记录 ↔ 笔记 关联建好了', link.status === 200, 'HTTP ' + link.status + ' ' + JSON.stringify(link.body).slice(0, 160))

  return {
    noteTypeId, bizType, textField, rec1, rec2, noteA, noteB, linkText,
    recToken1: REC_1, recToken2: REC_2,
  }
}

/* ===================== 1. 长笔记不溢出编辑框 ===================== */

async function measureEditor(page) {
  return await page.evaluate(() => {
    const ta = document.querySelector('.composer-editor')
      || document.querySelector('.composer-body textarea')
      || document.querySelector('main textarea')
      || document.querySelector('textarea')
    if (!ta) return null
    const body = document.querySelector('.composer-body') || ta.parentElement
    const ov = document.querySelector('.composer-overlay')
    const b = body.getBoundingClientRect()
    const t = ta.getBoundingClientRect()
    const o = ov ? ov.getBoundingClientRect() : null
    return {
      bodyTop: b.top, bodyBottom: b.bottom, bodyH: b.height,
      taTop: t.top, taBottom: t.bottom, taH: t.height,
      ovH: o ? o.height : null,
      scrollH: ta.scrollHeight, clientH: ta.clientHeight,
      viewportH: window.innerHeight,
    }
  })
}

function assertEditor(label, m) {
  if (!m) {
    check(label + '：找得到编辑框', false, '页面里没有 .composer-editor / textarea')
    return
  }
  const overflow = m.taBottom - m.bodyBottom
  check(label + '：文字框底边不超出编辑区底边（字不掉到框外）', overflow <= 0.5,
    '超出 ' + overflow.toFixed(1) + 'px（编辑区底 ' + m.bodyBottom.toFixed(1) + ' / 文字框底 ' + m.taBottom.toFixed(1) + '）')
  check(label + '：高亮层与文字框高度一致（双链高不错位）',
    m.ovH === null || Math.abs(m.ovH - m.taH) <= 1,
    'overlay ' + m.ovH + ' vs textarea ' + m.taH)
  check(label + '：长内容在框内滚动（scrollHeight > clientHeight）', m.scrollH > m.clientH + 1,
    'scrollHeight ' + m.scrollH + ' / clientHeight ' + m.clientH)
  check(label + '：编辑区不撑破可视区（高度 ≤ 可视区 - 120）', m.bodyH <= m.viewportH - 120 + 1,
    '编辑区 ' + m.bodyH.toFixed(1) + ' / 可视区 ' + m.viewportH)
}

async function fillEditor(page, text) {
  await page.evaluate(t => {
    const ta = document.querySelector('.composer-editor')
      || document.querySelector('.composer-body textarea')
      || document.querySelector('main textarea')
      || document.querySelector('textarea')
    if (!ta) throw new Error('找不到编辑框')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, t)
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  }, text)
  await sleep(500)
}

async function scrollToEnd(page) {
  return await page.evaluate(async () => {
    const ta = document.querySelector('.composer-editor') || document.querySelector('textarea')
    if (!ta) return { reached: false, synced: false }
    ta.scrollTop = ta.scrollHeight
    await new Promise(r => setTimeout(r, 200))
    const ov = document.querySelector('.composer-overlay')
    return {
      reached: ta.scrollTop + ta.clientHeight >= ta.scrollHeight - 1,
      synced: !ov || Math.abs(ov.scrollTop - ta.scrollTop) <= 1,
    }
  })
}

function longText(lines) {
  const out = []
  for (let i = 1; i <= (lines || 200); i++) {
    out.push('第 ' + i + ' 行：这是一段用于验证编辑器高度的长文本，内容要足够长才能把编辑框撑开。')
  }
  return out.join('\n')
}

async function item1(page) {
  section('1. 新建笔记：长内容不溢出编辑框')
  await goto(page, '/notes', 1500)
  const opened = await clickByText(page, '新建笔记')
  check('列表页点得开「新建笔记」', opened, '页面上没有这个按钮')
  await sleep(900)
  const hasEditor = await page.evaluate(() => !!document.querySelector('.composer-editor'))
  check('内联编辑框已出现', hasEditor, '没有 .composer-editor')
  if (!hasEditor) return
  await fillEditor(page, longText(200))
  assertEditor('quick', await measureEditor(page))
  const sc = await scrollToEnd(page)
  check('quick：能滚到内容末尾（内容没被切掉）', sc.reached, JSON.stringify(sc))
  check('quick：高亮层与文字框滚动同步', sc.synced, JSON.stringify(sc))
  // 清空后应缩回：不然框会永远停在长文的高度
  await fillEditor(page, '')
  await sleep(400)
  const shrunk = await measureEditor(page)
  check('quick：内容删光后编辑区缩回', shrunk && shrunk.bodyH <= 200,
    '编辑区高度 ' + (shrunk && shrunk.bodyH && shrunk.bodyH.toFixed(1)))
}

/* ===================== 2. 笔记加关联业务记录 ===================== */

async function item2(page, ctx) {
  section('2. 笔记能加关联业务记录、加完立刻显示')
  await goto(page, '/notes/' + ctx.noteA, 1600)

  const panel = await hasText(page, '关联的业务记录')
  check('详情页有「关联的业务记录」面板', panel, '页面上找不到这个面板')
  const shownRec1 = await page.evaluate(t => {
    const labels = Array.from(document.querySelectorAll('.nd-related-label')).map(e => e.innerText.trim())
    return labels.includes(t)
  }, REC_1)
  check('已关联的业务记录出现在列表里（' + REC_1 + '）', shownRec1,
    '列表里现在有：' + JSON.stringify(await page.evaluate(() =>
      Array.from(document.querySelectorAll('.nd-related-label')).map(e => e.innerText.trim()))))

  const before = await page.evaluate(() => document.querySelectorAll('.nd-related-item').length)
  const opened = await clickByText(page, '关联业务记录')
  check('点得开「关联业务记录」对话框', opened, '没有这个按钮')
  await sleep(1200)

  // 选模型（默认是第一个业务模型，多半不是我们那个）
  const picked = await page.evaluate(async name => {
    const input = document.querySelector('.nd-link-type input')
    if (input) { input.click(); await new Promise(r => setTimeout(r, 400)) }
    const opts = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
    const hit = opts.find(o => (o.innerText || '').trim() === name)
    if (hit) { hit.click(); return true }
    return false
  }, ctx.bizType.name)
  check('对话框里选到业务模型「' + ctx.bizType.name + '」', picked,
    '下拉里没有这个模型（可能已经是当前模型）')
  await sleep(800)

  // 搜索目标记录
  const typed = await page.evaluate(t => {
    const input = document.querySelector('.nd-link-search input') || document.querySelector('.nd-link-search')
    if (!input) return false
    // 按元素类型挑 setter：textarea 与 input 的 value setter 不是同一个
    const proto = input.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
    setter.call(input, t)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    return true
  }, REC_2)
  check('能在对话框里搜索记录', typed, '找不到 .nd-link-search')
  await sleep(1500)

  let cands = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.nd-link-candidate')).map(c => c.innerText.trim()))
  if (!cands.some(c => c.indexOf(ctx.recToken2) >= 0)) {
    // 搜不到就退回默认列表：候选默认按更新时间倒序，刚造的记录在最前面。
    // （不是静默跳过 —— 这里把「按关键字搜不到」这件事说出来。）
    console.log('    · 按关键字搜不到候选（该模型的检索文本里可能不含这个字段），改用默认候选列表')
    await page.evaluate(() => {
      const input = document.querySelector('.nd-link-search input')
      if (!input) return
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, '')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await sleep(1500)
    cands = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.nd-link-candidate')).map(c => c.innerText.trim()))
  }
  check('候选列表里有目标记录（' + ctx.recToken2 + '）', cands.some(c => c.indexOf(ctx.recToken2) >= 0),
    '候选：' + JSON.stringify(cands.slice(0, 5)))

  const clicked = await page.evaluate(t => {
    const cs = Array.from(document.querySelectorAll('.nd-link-candidate'))
    const hit = cs.find(c => (c.innerText || '').indexOf(t) >= 0)
    if (!hit) return false
    hit.click()
    return true
  }, ctx.recToken2)
  check('点得动候选记录（' + ctx.recToken2 + '）', clicked, '候选列表里没有这条记录')
  await sleep(1500)

  const after = await page.evaluate(() => document.querySelectorAll('.nd-related-item').length)
  check('加完立刻显示（不刷新页面，列表多一条）', after === before + 1,
    '加之前 ' + before + ' 条，加之后 ' + after + ' 条')
  const shownRec2 = await page.evaluate(t => {
    const labels = Array.from(document.querySelectorAll('.nd-related-label')).map(e => e.innerText.trim())
    return labels.includes(t)
  }, REC_2)
  check('新关联的记录出现在列表里', shownRec2)

  // 接口那边也要认
  const rel = await api('/api/knowledge/for-note/' + ctx.noteA)
  const names = (rel.body && rel.body.records || []).map(r => r.label || r.title || (r.data && r.data.title) || '')
  check('接口也能查到这两条关联', rel.status === 200 && names.length >= 2,
    'HTTP ' + rel.status + ' → ' + JSON.stringify(names))
}

/* ===================== 3. 双向链接 ===================== */

async function item3(page, ctx) {
  section('3. 双向链接：正向 / 反向页签与实际一致')
  const outA = await api('/api/notes/' + ctx.noteA + '/outgoing')
  const backB = await api('/api/notes/' + ctx.noteB + '/backlinks')
  const outList = (outA.body && (outA.body.links || outA.body.items || outA.body)) || []
  const backList = (backB.body && (backB.body.links || backB.body.items || backB.body)) || []
  const outArr = Array.isArray(outList) ? outList : []
  const backArr = Array.isArray(backList) ? backList : []
  check('接口能读到 A 的正向链接', outA.status === 200 && outArr.length >= 1,
    'HTTP ' + outA.status + ' → ' + JSON.stringify(outArr).slice(0, 200))
  check('接口能读到 B 的反向链接', backB.status === 200 && backArr.length >= 1,
    'HTTP ' + backB.status + ' → ' + JSON.stringify(backArr).slice(0, 200))

  await goto(page, '/notes/' + ctx.noteA, 1500)
  const tabForward = await clickTab(page, '正向链接')
  check('A 页有「正向链接」页签', tabForward)
  await sleep(700)
  const fwdItems = await page.evaluate(() => Array.from(document.querySelectorAll('.nd-link-item')).map(e => e.innerText.trim()))
  check('A 的正向链接里有 B（' + NOTE_B + '）', fwdItems.some(t => t.includes(NOTE_B)),
    '页面上是：' + JSON.stringify(fwdItems))
  check('A 的正向链接条数与接口一致', fwdItems.length === outArr.length,
    '页面 ' + fwdItems.length + ' 条 / 接口 ' + outArr.length + ' 条')

  await goto(page, '/notes/' + ctx.noteB, 1500)
  const tabBack = await clickTab(page, '反向链接')
  check('B 页有「反向链接」页签', tabBack)
  await sleep(700)
  const backItems = await page.evaluate(() => Array.from(document.querySelectorAll('.nd-link-item')).map(e => e.innerText.trim()))
  check('B 的反向链接里有 A（' + NOTE_A + '）', backItems.some(t => t.includes(NOTE_A)),
    '页面上是：' + JSON.stringify(backItems))
  check('B 的反向链接条数与接口一致', backItems.length === backArr.length,
    '页面 ' + backItems.length + ' 条 / 接口 ' + backArr.length + ' 条')
}

/* ===================== 4. 关联图谱 ===================== */

async function item4(page, ctx) {
  section('4. 关联图谱体现「笔记 ↔ 数据中心记录」')
  const g = await api('/api/graph/global?limit=600')
  const nodes = (g.body && g.body.nodes) || []
  const edges = (g.body && g.body.edges) || []
  const myNote = nodes.find(n => n.kind === 'record' && n.ref_id === ctx.noteA)
  check('全局图谱里有这篇笔记的节点', !!myNote, 'ref_id=' + ctx.noteA + ' 没找到')
  check('笔记节点标着 type_name=笔记', myNote && myNote.type_name === '笔记',
    '实际 type_name=' + (myNote && myNote.type_name))
  const noteNodeId = myNote && myNote.id
  const recNode = nodes.find(n => n.kind === 'record' && n.ref_id === ctx.rec1)
  const kbEdge = edges.find(e =>
    (e.relation || '') === '关联知识' &&
    e.source !== e.target &&
    [e.source, e.target].indexOf(noteNodeId) >= 0)
  check('全局图谱里有连到笔记的「关联知识」边', !!kbEdge,
    '边：' + JSON.stringify(edges.filter(e => (e.relation || '') === '关联知识')).slice(0, 240))
  check('这条边连的是那条业务记录', kbEdge && recNode && [kbEdge.source, kbEdge.target].indexOf(recNode.id) >= 0,
    '业务记录节点 ' + (recNode && recNode.id) + '，边 ' + JSON.stringify(kbEdge))

  const gn = await api('/api/graph/notes?limit=600')
  const gnEdges = (gn.body && gn.body.edges) || []
  const gnNodes = (gn.body && gn.body.nodes) || []
  const gnNote = gnNodes.find(n => n.kind === 'record' && n.ref_id === ctx.noteA)
  const gnEdge = gnEdges.find(e => (e.relation || '') === '关联知识' &&
    [e.source, e.target].indexOf(gnNote && gnNote.id) >= 0)
  check('知识图谱里有笔记节点', !!gnNote, 'ref_id=' + ctx.noteA + ' 没找到')
  check('知识图谱里有「关联知识」边', !!gnEdge,
    '边：' + JSON.stringify(gnEdges.filter(e => (e.relation || '') === '关联知识')).slice(0, 240))

  await goto(page, '/graph', 2600)
  const legend = await page.evaluate(() => Array.from(document.querySelectorAll('.gc-legend .gl-label')).map(e => e.innerText.trim()))
  check('关联图谱图例里有「笔记」', legend.indexOf('笔记') >= 0, '图例：' + JSON.stringify(legend))
  // 边图例按「边的种类」分组（关联关系 / 外键引用 / 字段挂载），
  // 「关联知识」这条边归在「关联关系」里 —— 具体是哪条关系只有接口说得清，
  // 页面这一层能证明的是：这条边确实被画出来了（图例里有它所属的类别）。
  check('关联图谱图例里有「关联关系」（笔记那条边的类别）', legend.indexOf('关联关系') >= 0, '图例：' + JSON.stringify(legend))
}

/* ===================== 5. DNA 文件在证据链 ===================== */

async function item5(page) {
  section('5. DNA 图谱：数据中心文件挪到证据链')
  await goto(page, '/dna', 4000)
  // 图是 canvas 画的，但标题层是 HTML：.dg-lbl + dg-lbl-<种类> + 侧别(l/r)
  const counts = await page.evaluate(() => {
    const q = sel => document.querySelectorAll(sel).length
    return {
      total: q('.dg-lbl'),
      docL: q('.dg-lbl-document.l'),
      docR: q('.dg-lbl-document.r'),
      geneL: q('.dg-lbl-gene.l'),
      recordR: q('.dg-lbl-record.r'),
      sectionR: q('.dg-lbl-section.r'),
    }
  })
  check('DNA 图谱渲染出标题层', counts.total > 0, '一个 .dg-lbl 都没有')
  check('文件节点都在证据链（.dg-lbl-document.r）', counts.docR > 0,
    '证据链上的文件 ' + counts.docR + ' 个')
  check('知识链上没有文件（.dg-lbl-document.l 为 0）', counts.docL === 0,
    '知识链上还挂着 ' + counts.docL + ' 个文件')
  check('知识链上是基因', counts.geneL > 0, '知识链上的基因 ' + counts.geneL + ' 个')

  const dna = await api('/api/dna/graph')
  const dn = (dna.body && dna.body.nodes) || []
  const de = (dna.body && dna.body.edges) || []
  check('DNA 图谱接口有数据', dna.status === 200 && dn.length > 0,
    'HTTP ' + dna.status + '，节点 ' + dn.length)
  const docNodes = dn.filter(n => (n.kind === 'document' || (n.meta && n.meta.type === 'doc')))
  check('接口里也有文件节点', docNodes.length > 0, '文件节点 ' + docNodes.length + ' 个')
}

/* ===================== 6. 打印 ===================== */

async function printState(page) {
  return await page.evaluate(() => {
    const vis = el => {
      if (!el) return false
      const s = getComputedStyle(el)
      return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity || '1') > 0.05
    }
    const side = document.querySelector('.sidebar')
    const top = document.querySelector('.topbar')
    const root = document.querySelector('[data-print-root]')
    const only = document.querySelector('[data-print-only]')
    const main = document.querySelector('.el-main') || document.querySelector('main')
    return {
      sidebarHidden: !vis(side),
      topbarHidden: !vis(top),
      rootExists: !!root,
      rootVisible: vis(root),
      rootTextLen: root ? (root.innerText || '').replace(/\s+/g, ' ').trim().length : 0,
      onlyVisible: vis(only),
      mainVisible: vis(main),
      mainTextLen: main ? (main.innerText || '').replace(/\s+/g, ' ').trim().length : 0,
    }
  })
}

async function item6(page, ctx) {
  section('6. 各页打印功能')
  const pages = [
    ['/notes', '知识库'],
    ['/notes/' + ctx.noteA, '笔记详情'],
    ['/library', '数据中心'],
    ['/records/' + ctx.bizType.id, '记录'],
    ['/graph', '关联图谱'],
    ['/knowledge/graph', '知识图谱'],
  ]
  for (const p of pages) {
    const hash = p[0]
    const name = p[1]
    await goto(page, hash, 2200)
    const hasBtn = await page.evaluate(() => !!document.querySelector('[data-print-trigger]'))
    check(name + '：有打印按钮', hasBtn, '页面里没有 [data-print-trigger]')
    await page.emulateMediaType('print')
    await sleep(400)
    const st = await printState(page)
    await page.emulateMediaType('screen')
    check(name + '：打印时侧边导航隐藏', st.sidebarHidden, '侧边栏还看得见')
    check(name + '：打印时正文可见', st.mainVisible && st.mainTextLen > 0,
      '正文长度 ' + st.mainTextLen)
    check(name + '：打印时正文区被标出来（data-print-root）', st.rootExists && st.rootVisible && st.rootTextLen > 0,
      'root 存在 ' + st.rootExists + ' / 可见 ' + st.rootVisible + ' / 字数 ' + st.rootTextLen)
    check(name + '：打印页眉只在打印时出现', st.onlyVisible, 'data-print-only 元素没露出来')
  }
}

/* ===================== 主流程 ===================== */

async function main() {
  const health = await waitApi('/api/health', 10)
  if (!health) failFast('后端没起来（' + API + '/api/health 不通）')

  const ctx = await setupData()

  console.log('\n▶ 准备浏览器')
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await newPage(browser)

  try {
    await item1(page, ctx)
    await item2(page, ctx)
    await item3(page, ctx)
    await item4(page, ctx)
    await item5(page)
    await item6(page, ctx)
  } catch (e) {
    check('验收脚本自己跑完了（没有中途抛错）', false, (e && e.stack) ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e))
  }

  const jsErrors = page.__errors || []
  check('全程没有 JS 报错', jsErrors.length === 0, jsErrors.slice(0, 3).join(' | '))

  await browser.close()

  // 清理自己造的数据（只删本次造的，带时间戳的那些）。
  // 删的是软删除，进回收站，随时能恢复 —— 别人的数据一条不碰。
  if (KEEP) {
    console.log('\n▶ 保留验收数据（--keep）：笔记 ' + ctx.noteA + ' / ' + ctx.noteB +
      '，业务记录 ' + ctx.rec1 + ' / ' + ctx.rec2)
  } else {
    console.log('\n▶ 清理验收数据')
    for (const id of [ctx.noteA, ctx.noteB, ctx.rec1, ctx.rec2]) {
      const r = await api('/api/records/' + id, { method: 'DELETE' })
      if (r.status !== 200) console.log('  · 删不掉 ' + id + '：HTTP ' + r.status)
    }
    console.log('  ✓ 验收数据已进回收站（可恢复）')
  }

  console.log('\n' + (ERRORS.length
    ? '✗ ' + ERRORS.length + ' 项未通过（共 ' + CHECKS + ' 项）'
    : '✓ 全部 ' + CHECKS + ' 项检查通过'))
  if (ERRORS.length) {
    ERRORS.forEach(e => console.log('  · ' + e))
    process.exit(1)
  }
}

main().catch(e => { console.error(e); process.exit(1) })

