/**
 * 存储与备份页截图
 *
 * 需要登录态，而这一轮验证期间 admin 口令已被使用者改过，脚本不该假设知道它。
 * 所以从 KB_SESSION_TOKEN 环境变量读一个已存在的会话 token 注入 cookie ——
 * 这样截图脚本不需要口令，也不会去动任何账号。
 *
 *   KB_SESSION_TOKEN=xxx node scripts/storage-shots.cjs
 */
const { createRequire } = require('module')
const fs = require('fs')
const path = require('path')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = path.join(__dirname, '..', 'docs', 'screenshots', 'storage')

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

async function main() {
  if (!TOKEN) {
    console.error('缺少 KB_SESSION_TOKEN，无法注入登录态')
    process.exit(1)
  }
  fs.mkdirSync(OUT, { recursive: true })

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox', '--force-device-scale-factor=2'],
  })

  const errors = []
  const shots = []

  async function snap(page, name) {
    const p = path.join(OUT, `${name}.png`)
    await page.screenshot({ path: p, fullPage: true })
    shots.push(p)
    console.log('  ✓', `${name}.png`)
  }

  async function open(dark) {
    const page = await browser.newPage()
    await page.setViewport({ width: 1560, height: 1000, deviceScaleFactor: 2 })
    page.on('console', m => { if (m.type() === 'error') errors.push(`console: ${m.text()}`) })
    page.on('pageerror', e => errors.push(`pageerror: ${e}`))
    await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })
    await page.evaluateOnNewDocument((d) => {
      localStorage.setItem('kb-theme', d ? 'dark' : 'light')
    }, dark)
    return page
  }

  async function loadStorage(page, dark) {
    await page.goto(`${FE}/#/system/storage`, { waitUntil: 'networkidle2' })
    await page.evaluate((d) => {
      document.documentElement.classList.toggle('dark', d)
    }, dark)
    // 等三块数据都回来：概览卡有数值 + 容量条渲染出来 + 备份表有行
    await page.waitForFunction(
      () => document.querySelectorAll('.cap-row').length > 0
        && !!document.querySelector('.stat-card .value'),
      { timeout: 20000 },
    )
    await sleep(1400)
  }

  // ---- 明亮 ----
  let page = await open(false)
  await loadStorage(page, false)
  await snap(page, '01-storage-light')

  // 悬停到容量区，顺带把「体检结论」也带进视野
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.card-title-text')]
      .find(e => e.innerText.includes('体检结论'))
    el?.scrollIntoView({ block: 'start' })
  })
  await sleep(500)
  await snap(page, '02-storage-index-light')
  await page.close()

  // ---- 暗色 ----
  page = await open(true)
  await loadStorage(page, true)
  await snap(page, '03-storage-dark')
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.card-title-text')]
      .find(e => e.innerText.includes('备份'))
    el?.scrollIntoView({ block: 'start' })
  })
  await sleep(500)
  await snap(page, '04-storage-backup-dark')
  await page.close()

  // ---- 窄屏 ----
  page = await open(false)
  await page.setViewport({ width: 430, height: 940, deviceScaleFactor: 2 })
  await loadStorage(page, false)
  await snap(page, '05-storage-mobile')
  await page.close()

  await browser.close()

  console.log(`\n共 ${shots.length} 张截图 → docs/screenshots/storage/`)
  if (errors.length) {
    console.log(`\n⚠️ 控制台异常 ${errors.length} 条：`)
    errors.slice(0, 8).forEach(e => console.log('   -', e.slice(0, 160)))
    process.exitCode = 2
  } else {
    console.log('控制台无异常')
  }
}

main().catch(e => { console.error(e); process.exit(1) })
