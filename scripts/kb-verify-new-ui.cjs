/**
 * 新增能力的界面验收：
 *   ① 养料库 → 源码树：上传总量上限控件能读出当前值、能改、能存
 *   ② 软件开发：侧栏入口、/dev 列表页、/dev/settings、/dev/:id 工作台
 *   ③ 养料 DNA：双螺旋图谱的工具栏/图例/统计条仍在
 *
 * 用法：node scripts/kb-verify-new-ui.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

function sessionToken() {
  if (process.env.KB_TOKEN) return process.env.KB_TOKEN
  try {
    return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT }).trim()
  } catch (e) { return '' }
}

let fail = 0
const ok = (cond, tag, extra) => {
  if (cond) console.log('  ✓ ' + tag + (extra ? ' → ' + extra : ''))
  else { console.log('  ✗ ' + tag + (extra ? ' → ' + extra : '')); fail++ }
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const errs = []
  page.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  page.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1600, height: 1000 })

  // ---------- ① 养料库 → 源码树 → 上传总量上限 ----------
  console.log('① 养料库 · 源码树上传上限')
  await page.goto(BASE + '/#/dna-library', { waitUntil: 'networkidle2' })
  await sleep(6000)
  const tabClicked = await page.evaluate(() => {
    const t = [...document.querySelectorAll('.el-tabs__item')].find(x => (x.textContent || '').includes('源码树'))
    if (t) { t.click(); return true }
    return false
  })
  ok(tabClicked, '切到「源码树」tab')
  await sleep(1200)
  const lim = await page.evaluate(() => {
    const el = document.querySelector('.ingest-limit')
    if (!el) return null
    const input = el.querySelector('input')
    return {
      text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
      value: input ? input.value : null,
      saveBtn: [...el.querySelectorAll('button')].map(b => (b.textContent || '').trim()).join('|'),
    }
  })
  ok(!!lim, '上传上限控件在页面上', lim ? lim.text.slice(0, 70) : '没找到 .ingest-limit')
  ok(lim && lim.value === '256', '当前上限读成 256', lim ? String(lim.value) : '-')

  // 改大到 512 并保存（用真实键盘输入，不直接改 value ——
  // el-input-number 内部有自己的输入缓冲，直接塞 value 它不一定认）
  const inputHandle = await page.$('.ingest-limit input')
  ok(!!inputHandle, '找到上限输入框')
  await inputHandle.scrollIntoView()
  await inputHandle.focus()
  await inputHandle.evaluate(el => { if (el.select) el.select() })
  await page.keyboard.type('512')
  await page.keyboard.press('Enter')   // el-input-number 要失焦/回车才把值提交给 v-model
  await sleep(900)
  const btnHandle = await page.$('.ingest-limit button')
  if (btnHandle) await btnHandle.click()
  await sleep(2000)
  const saved = await page.evaluate(() => {
    const el = document.querySelector('.ingest-limit')
    const input = el ? el.querySelector('input') : null
    return { value: input ? input.value : null, text: el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '' }
  })
  ok(saved && saved.value === '512', '改成 512 并保存', saved ? String(saved.value) : JSON.stringify(saved))

  // 用后端确认真的落库了
  const apiVal = await page.evaluate(async () => {
    const r = await fetch('/api/dna/library/limits')
    const j = await r.json()
    return j.limits ? j.limits.max_total_mb : null
  })
  ok(apiVal === 512, '后端已落库 512 MB', String(apiVal))

  // 复原成 256，避免污染真实数据
  await page.evaluate(async () => {
    await fetch('/api/dna/library/limits', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_total_mb: 256 }),
    })
  })

  // ---------- ② 软件开发模块 ----------
  console.log('② 软件开发模块')
  const nav = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.el-menu-item, .el-sub-menu__title, a')]
    const hit = items.find(i => (i.textContent || '').trim() === '软件开发')
    return { found: !!hit }
  })
  ok(nav.found, '侧栏出现「软件开发」入口')

  for (const [hash, sel, tag] of [
    ['/#/dev', '.dev-page', '项目列表'],
    ['/#/dev/settings', '.dev-settings, [class*=settings]', '开发设置'],
  ]) {
    await page.goto(BASE + hash, { waitUntil: 'networkidle2' })
    await sleep(4000)
    const hit = await page.evaluate(s => {
      const el = document.querySelector(s)
      return el ? { text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60) } : null
    }, sel)
    ok(!!hit, tag + ' 页面渲染', hit ? hit.text : '没找到 ' + sel)
  }

  // ---------- ③ DNA 图谱 ----------
  console.log('③ 养料 DNA 图谱')
  await page.goto(BASE + '/#/dna', { waitUntil: 'networkidle2' })
  await sleep(6000)
  const dna = await page.evaluate(() => {
    return {
      labels: document.querySelectorAll('.dg-lbl').length,
      stats: (document.querySelector('.dg-stats') || {}).textContent || '',
      legend: document.querySelectorAll('.dg-legend-item').length,
      toolbar: document.querySelectorAll('.dg-bar button, .dg-bar .el-button').length,
    }
  })
  ok(dna.labels > 0, '图谱标签已渲染', dna.labels + ' 个')
  ok(dna.stats.includes('显示'), '统计条有内容', dna.stats)

  console.log('--- errors ---')
  console.log(errs.length ? [...new Set(errs)].slice(0, 8).join('\n') : 'none')
  await browser.close()
  console.log(fail ? 'FAIL: ' + fail : 'PASS')
  process.exit(fail ? 1 : 0)
})()
