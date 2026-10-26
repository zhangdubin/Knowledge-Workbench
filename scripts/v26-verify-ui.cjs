/**
 * v24 浏览器端验证：搜索高亮的 XSS 修复 + 数据中心关键词搜正文
 *
 * 为什么要在浏览器里验：XSS 的要害是「v-html 里的字符串有没有被当成标签解析」，
 * 光看后端返回值说明不了问题 —— 必须让真实浏览器把结果页渲染一遍，
 * 看 DOM 里到底有没有多出 <img> 元素、有没有真的执行 onerror。
 *
 * 前置：容器已启动（8001 / 8082），管理员口令已知。
 *   node scripts/v24-verify-ui.cjs
 */
const path = require('path')
const PUPPETEER = '/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core'
const puppeteer = require(PUPPETEER)
const S = require('./lib/session.cjs')
const { FE, API, USER, PASS } = S

const results = []
function check(name, got, want) {
  const ok = got === want
  results.push({ name, ok, got, want })
  console.log(`${ok ? '✅' : '❌'} ${name}${ok ? '' : `  （实际 ${JSON.stringify(got)}，期望 ${JSON.stringify(want)}）`}`)
}

const sleep = ms => new Promise(r => setTimeout(r, ms))

async function main() {
  await S.login()

  // ---------- 准备：造一个文件名带 HTML 的文件 ----------
  const evilName = '<img src=x onerror="window.__XSS_FIRED__=1">.txt'
  const probe = 'zebra-probe-' + Date.now().toString(36)
  const up = await fetch(`${API}/api/documents/upload`, {
    method: 'POST',
    headers: { Cookie: S.cookies() },
    body: (() => {
      const fd = new FormData()
      fd.append('file', new Blob([probe], { type: 'text/plain' }), evilName)
      return fd
    })(),
  })
  if (!up.ok) throw new Error(`上传探针文件失败：HTTP ${up.status}`)
  const upBody = await up.json().catch(() => ({}))
  const probeId = upBody.id || upBody.document_id
  console.log(`探针文件：#${probeId}（文件名带 HTML）`)

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })

  try {
    const page = await browser.newPage()
    await page.setViewport({ width: 1440, height: 900 })

    // 登录
    await page.goto(`${FE}/#/login`, { waitUntil: 'networkidle2' })
    await page.waitForSelector('input[placeholder*="用户名"], input[name=username]', { timeout: 15000 })
    const inputs = await page.$$('input')
    // 用户名框默认预填了 admin，不清掉会变成 "adminverify_admin" 直接 401
    const clear = async (el) => {
      await el.click({ clickCount: 3 })
      await page.keyboard.press('Backspace')
    }
    await clear(inputs[0])
    await inputs[0].type(USER)
    await clear(inputs[1])
    await inputs[1].type(PASS)
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle2' }).catch(() => {}),
      page.click('button[type=submit], .el-button--primary'),
    ])
    await sleep(2500)
    // ---------- 1. 搜索页：XSS 不该触发 ----------
    console.log('\n=== A. 搜索页高亮（XSS 回归）===')
    await page.goto(`${FE}/#/search`, { waitUntil: 'networkidle2' })
    await sleep(1200)
    // 先注入标记，确认探针页面在同一个 origin
    await page.evaluate(() => { window.__XSS_FIRED__ = 0 })

    const box = await page.$('input[placeholder*="关键字"]')
    if (!box) throw new Error('搜索页找不到搜索框')
    await box.click()
    await box.type('zebra')
    await page.keyboard.press('Enter')
    await sleep(2500)

    const xssProbe = await page.evaluate(() => {
      const titles = [...document.querySelectorAll('.result-title')].map(el => ({
        html: el.innerHTML,
        tags: [...el.querySelectorAll('*')].map(n => n.tagName),
      }))
      return {
        fired: window.__XSS_FIRED__,
        imgCount: document.querySelectorAll('.result-title img').length,
        titles,
        stats: (document.querySelector('.result-stats, .stats, .search-stats') || {}).textContent || '',
      }
    })
    check('恶意文件名没有执行 onerror', xssProbe.fired, 0)
    check('结果标题里没有生成 <img> 元素', xssProbe.imgCount, 0)
    check('恶意文件名被转义成文本', xssProbe.titles.some(t => t.html.includes('&lt;img')), true)
    check('转义后不再有 IMG 标签', xssProbe.titles.filter(t => t.tags.includes('IMG')).length, 0)

    // ---------- 2. 数据中心：关键词搜正文 ----------
    console.log('\n=== B. 数据中心关键词搜正文 ===')
    await page.goto(`${FE}/#/library`, { waitUntil: 'networkidle2' })
    await sleep(2000)
    const before = await page.evaluate(() => document.querySelectorAll('.file-tile, .el-table__row').length)

    // 探针文件的内容里有 probe，正文命中；文件名里没有
    const kwBox = await page.$('input[placeholder*="搜索文件名或正文"]')
    if (!kwBox) throw new Error('数据中心找不到关键词搜索框')
    await kwBox.click()
    await kwBox.type(probe)
    await page.keyboard.press('Enter')
    await sleep(2500)

    const after = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.file-tile, .el-table__row')]
      return {
        count: rows.length,
        names: rows.map(r => (r.textContent || '').trim().slice(0, 80)),
      }
    })
    check('按正文内容也能搜到文件（文件名里没有该词）', after.count, 1)
    check('搜到的是那个探针文件', after.names.some(n => n.includes('zebra') || n.includes('img')), true)
    console.log(`   （搜索前 ${before} 行 → 搜索后 ${after.count} 行）`)

    // ---------- 3. 知识库笔记界面（Obsidian 式）----------
    console.log('\n=== C. 知识库笔记界面 ===')
    await page.goto(`${FE}/#/notes`, { waitUntil: 'networkidle2' })
    await sleep(2000)
    const notes = await page.evaluate(() => ({
      hasSearch: !!document.querySelector('input[placeholder*="搜索"], .note-search input'),
      listItems: document.querySelectorAll('.note-item, .note-list-item, .note-row').length,
      body: (document.querySelector('.notes-view, .notes-page') || document.body).textContent.slice(0, 200),
    }))
    check('笔记页有搜索框', notes.hasSearch, true)
    check('笔记列表渲染出条目', notes.listItems > 0, true)
    console.log(`   （笔记条目 ${notes.listItems} 个）`)

    // ---------- 4. 系统设置：升级与更新 ----------
    console.log('\n=== D. 系统设置 · 升级与更新 ===')
    await page.goto(`${FE}/#/system/settings`, { waitUntil: 'networkidle2' })
    await sleep(2000)
    const upd = await page.evaluate(() => {
      const text = document.body.textContent
      return {
        hasRepo: text.includes('仓库'),
        hasProxy: text.includes('代理'),
        hasRepoInput: !!document.querySelector('input[placeholder*="owner"], input[placeholder*="仓库"]'),
        hasProxyInput: !!document.querySelector('input[placeholder*="http"], input[placeholder*="proxy"]'),
      }
    })
    check('设置页有「仓库」配置项', upd.hasRepo, true)
    check('设置页有「代理」配置项', upd.hasProxy, true)
    check('有仓库地址输入框', upd.hasRepoInput, true)
    check('有代理输入框', upd.hasProxyInput, true)

    // ---------- 5. 应用中心：AI 建应用入口 ----------
    console.log('\n=== E. 应用中心 · AI 建应用 ===')
    await page.goto(`${FE}/#/apps`, { waitUntil: 'networkidle2' })
    await sleep(2000)
    const apps = await page.evaluate(() => {
      const text = document.body.textContent
      return {
        hasAI: text.includes('AI') || text.includes('智能'),
        hasTemplate: text.includes('模板'),
        buttons: [...document.querySelectorAll('button')].map(b => (b.textContent || '').trim()).filter(Boolean),
      }
    })
    check('应用中心有 AI 入口', apps.hasAI, true)
    check('应用中心有模板入口', apps.hasTemplate, true)
    console.log(`   （按钮：${apps.buttons.slice(0, 8).join(' | ')}）`)
  } finally {
    await browser.close()
    // 清理探针文件
    try {
      // 硬删（彻底删除）：soft=false 先进回收站，hard=true 直接抹掉
      await fetch(`${API}/api/documents/${probeId}?hard=true`, {
        method: 'DELETE',
        headers: { Cookie: S.cookies() },
      })
    } catch (e) { /* 忽略 */ }
    console.log(`\n探针文件 #${probeId} 已清理`)
  }
}

main()
  .catch(e => { console.error('❌ 验证脚本异常：', e.message); process.exitCode = 1 })
  .finally(() => {
    const bad = results.filter(r => !r.ok)
    console.log(`\n共 ${results.length} 项，${results.length - bad.length} 项通过`)
    if (bad.length) {
      console.log('❌ 失败项：')
      for (const r of bad) console.log(`   ${r.name}  实际 ${JSON.stringify(r.got)} / 期望 ${JSON.stringify(r.want)}`)
    }
    process.exit(bad.length ? 1 : 0)
  })
