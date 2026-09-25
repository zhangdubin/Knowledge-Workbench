/**
 * 系统设置页截图
 *
 * 与 storage-shots.cjs 同一套思路：不假设知道任何口令，从 KB_SESSION_TOKEN
 * 注入一个已存在的会话 cookie。
 *
 *   KB_SESSION_TOKEN=xxx node scripts/settings-shots.cjs
 */
const { createRequire } = require('module')
const fs = require('fs')
const path = require('path')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = path.join(__dirname, '..', 'docs', 'screenshots', 'settings')

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

  async function loadSettings(page, dark) {
    await page.goto(`${FE}/#/system/settings`, { waitUntil: 'networkidle2' })
    await page.evaluate((d) => {
      document.documentElement.classList.toggle('dark', d)
    }, dark)
    // 等配置项渲染出来（三项：备份目录 / 保留份数 / 初始口令）
    await page.waitForFunction(
      () => document.querySelectorAll('.set-row').length >= 3
        && document.querySelectorAll('.cand-box tbody tr').length > 0,
      { timeout: 20000 },
    )
    await sleep(1400)
  }

  // ---- 明亮：整页 ----
  let page = await open(false)
  await loadSettings(page, false)
  await snap(page, '01-settings-light')

  // 滚到「候选目录」：这一段是本页最需要被人看懂的地方
  await page.evaluate(() => {
    document.querySelector('.cand-box')?.scrollIntoView({ block: 'center' })
  })
  await sleep(600)
  await snap(page, '02-settings-targets-light')
  await page.close()

  // ---- 暗色 ----
  page = await open(true)
  await loadSettings(page, true)
  await snap(page, '03-settings-dark')
  await page.evaluate(() => {
    document.querySelector('.cand-box')?.scrollIntoView({ block: 'center' })
  })
  await sleep(600)
  await snap(page, '04-settings-targets-dark')
  await page.close()

  // ---- 窄屏 ----
  page = await open(false)
  await page.setViewport({ width: 430, height: 940, deviceScaleFactor: 2 })
  await loadSettings(page, false)
  await snap(page, '05-settings-mobile')
  await page.close()

  await browser.close()

  console.log(`\n共 ${shots.length} 张截图 → docs/screenshots/settings/`)
  if (errors.length) {
    console.log(`\n⚠️ 控制台异常 ${errors.length} 条：`)
    errors.slice(0, 8).forEach(e => console.log('   -', e.slice(0, 160)))
    process.exitCode = 2
  } else {
    console.log('控制台无异常')
  }
}

main().catch(e => { console.error(e); process.exit(1) })
