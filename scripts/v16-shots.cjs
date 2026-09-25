/**
 * v16 截图：Jevko → JSON 之后的四个关键界面
 *   1. 类型编辑器的「JSON 定义」面板（左源右预览 + 校验结论）
 *   2. 数据中心的「JSON 元数据」标签页（展开一个文件的节点树）
 *   3. JSON 试验场（随手粘一段 JSON 就能看树）
 *   4. 笔记详情的 JSON 标签页
 * 明暗两套主题都抓，顺带断言控制台与接口无异常。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')

const FE = 'http://127.0.0.1:8082'
const API = 'http://localhost:8001'
const OUT = '/Volumes/Samsung/poc/知识库/kb-workbench/docs/screenshots/v16'
fs.mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise(r => setTimeout(r, ms))
const errs = []

async function waitFor(p, fn, ms = 8000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    const v = await p.evaluate(fn)
    if (v) return v
    await sleep(150)
  }
  return null
}

/** 找一个 id 最小的模型，进它的编辑页 */
async function anyTypeId() {
  const r = await fetch(`${API}/api/entity-types`)
  const d = await r.json()
  const items = d.items || d
  return items.length ? items[items.length - 1].id : null
}

;(async () => {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 980, deviceScaleFactor: 2 })

  p.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  p.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  p.on('response', r => { if (r.status() >= 400) errs.push(`[http ${r.status()}] ${r.url()}`) })

  const typeId = await anyTypeId()

  for (const mode of ['light', 'dark']) {
    const setTheme = async () => {
      await p.evaluate(m => document.documentElement.classList.toggle('dark', m === 'dark'), mode)
      await sleep(250)
    }

    // 1) JSON 定义面板（新建态：预填可编辑的示例）
    await p.goto(`${FE}/#/types/new?mode=json`, { waitUntil: 'networkidle0' })
    await setTheme()
    await sleep(1500)
    await p.evaluate(() => {
      const el = document.querySelector('.json-editor')
      if (el) el.scrollIntoView({ block: 'center' })
    })
    await sleep(400)
    await p.screenshot({ path: `${OUT}/01-typeeditor-json-${mode}.png` })

    // 点一次「校验」，把服务端结论也带上（这是 JSON 建模闭环的关键反馈）
    await p.evaluate(() => {
      const el = document.querySelector('.je-input textarea')
      el.value = el.value.replace(/"key"\s*:\s*"[^"]+"/, '"key": "v16_shot_demo"')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await p.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(x => x.textContent.includes('校验'))
      btn && btn.click()
    })
    await waitFor(p, () => {
      const el = document.querySelector('.je-check .je-block')
      return el ? el.innerText : ''
    })
    await sleep(300)
    await p.evaluate(() => {
      const el = document.querySelector('.json-editor')
      if (el) el.scrollIntoView({ block: 'start' })
    })
    await sleep(300)
    await p.screenshot({ path: `${OUT}/02-typeeditor-check-${mode}.png` })

    // 2) 已存在的模型：JSON 反映现有字段（编辑态）
    if (typeId) {
      await p.goto(`${FE}/#/types/${typeId}/edit`, { waitUntil: 'networkidle0' })
      await setTheme()
      await sleep(1500)
      await p.evaluate(() => {
        const el = document.querySelector('.json-editor')
        if (el) el.scrollIntoView({ block: 'center' })
      })
      await sleep(400)
      await p.screenshot({ path: `${OUT}/03-typeeditor-existing-${mode}.png` })
    }

    // 3) 数据中心的 JSON 元数据（展开第一个文件）
    await p.goto(`${FE}/#/library`, { waitUntil: 'networkidle0' })
    await setTheme()
    await sleep(1600)
    await p.evaluate(() => {
      const t = [...document.querySelectorAll('.el-tabs__item')]
        .find(x => x.innerText.includes('JSON 元数据'))
      t && t.click()
    })
    await sleep(900)
    await p.evaluate(() => {
      const h = document.querySelector('.json-head')
      h && h.click()
    })
    await waitFor(p, () => {
      const el = document.querySelector('.json-body')
      const t = el ? el.innerText : ''
      return t.includes('filename') ? t : ''
    })
    await sleep(400)
    await p.screenshot({ path: `${OUT}/04-library-json-meta-${mode}.png` })

    // 4) JSON 试验场
    await p.goto(`${FE}/#/library`, { waitUntil: 'networkidle0' })
    await setTheme()
    await sleep(1400)
    await p.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(x => x.textContent.includes('JSON 试验场'))
      btn && btn.click()
    })
    await sleep(1400)
    await p.screenshot({ path: `${OUT}/05-json-playground-${mode}.png` })
    await p.keyboard.press('Escape')
    await sleep(600)
  }

  // 5) 笔记详情的 JSON 标签页
  const nt = await fetch(`${API}/api/entity-types/by-key/note`).then(r => r.json())
  const recs = await fetch(`${API}/api/records/type/${nt.id}?page=1&page_size=1`).then(r => r.json())
  const noteId = recs.items?.[0]?.id
  if (noteId) {
    await p.goto(`${FE}/#/notes/${noteId}`, { waitUntil: 'networkidle0' })
    await sleep(1600)
    await p.evaluate(() => {
      const t = [...document.querySelectorAll('.el-tabs__item')].find(x => x.innerText.trim() === 'JSON')
      t && t.click()
    })
    await sleep(900)
    await p.screenshot({ path: `${OUT}/06-note-json-light.png` })
    console.log('note json tab ok')
  }

  await b.close()
  console.log('--- errors ---')
  console.log(errs.length ? [...new Set(errs)].join('\n') : 'none')
})()
