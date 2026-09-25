/**
 * 版本标识 UI 验证
 *
 * 版本号事实来源是 backend/app/config.py 的 app_version，本脚本验证它
 * 在三处 UI 都正确落格：
 *   1. 登录页 stage-foot（未登录即可见）
 *   2. 侧栏底部 sys-version（登录后可见）
 *   3. 系统设置 → 关于系统（登录后可见）
 *
 *   node scripts/v19-verify-version.cjs [KB_SESSION_TOKEN=xxx]
 *   不带 token 时只验证登录页（第 1 项）。
 */
const { createRequire } = require('module')
const fs = require('fs')
const path = require('path')

const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const FE = process.env.KB_FE || 'http://127.0.0.1:8082'
const TOKEN = (process.env.KB_SESSION_TOKEN || '').trim()
const OUT = process.env.KB_SHOT_DIR || '/tmp/kb-version'
const sleep = ms => new Promise(r => setTimeout(r, ms))

async function main() {
  // 版本号以后端 /api/health 为准，不硬编码在脚本里
  const { version } = await (await fetch(`${FE}/api/health`)).json()
  console.log(`后端报告版本: v${version}`)
  fs.mkdirSync(OUT, { recursive: true })

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox', '--force-device-scale-factor=2'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1500, height: 950, deviceScaleFactor: 2 })
  // 注意：cookie 要在登录页验证完之后再注入 —— 已登录状态下路由守卫
  // 会把 /#/login 直接弹回工作台，永远等不到 .stage-foot。
  const shots = []
  const snap = async name => {
    const f = path.join(OUT, `${name}.png`)
    await page.screenshot({ path: f })
    shots.push(f)
    console.log('  ✓', `${name}.png`)
  }
  const check = (label, ok, extra = '') =>
    console.log(`  ${ok ? '✓' : '✗'} ${label}${extra ? ' — ' + extra : ''}`)

  // 1. 登录页
  console.log('\n[1/3] 登录页底部')
  await page.goto(`${FE}/#/login`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.stage-foot', { timeout: 15000 })
  await sleep(900)
  const loginFoot = await page.$eval('.stage-foot', el => el.innerText)
  check(`登录页显示 v${version}`, loginFoot.includes(`v${version}`), loginFoot.replace(/\s+/g, ' '))
  await snap('01-login-version')

  if (!TOKEN) {
    console.log('\n（未提供 KB_SESSION_TOKEN，跳过登录后的验证）')
    await browser.close()
    return
  }

  // 现在才注入会话，验证登录后的两处。
  // 注入后必须 reload：auth store 在登录页已经跑过 bootstrap() 且 ready=true，
  // 不重载的话 store 里还是未登录状态，路由守卫会把 '#/' 一直弹回登录页。
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })

  // 2. 侧栏底部
  console.log('\n[2/3] 侧栏底部')
  await page.goto(`${FE}/#/`, { waitUntil: 'networkidle2' })
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.sys-version', { timeout: 15000 })
  await sleep(800)
  const sideVer = await page.$eval('.sys-version', el => el.textContent.trim())
  check(`侧栏显示 v${version}`, sideVer === `v${version}`, sideVer)
  await snap('02-sidebar-version')

  // 3. 系统设置 → 关于系统
  console.log('\n[3/3] 系统设置 → 关于系统')
  await page.goto(`${FE}/#/system/settings`, { waitUntil: 'networkidle2' })
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.about-rows', { timeout: 15000 })
  await sleep(900)
  const aboutText = await page.$eval('.about-rows', el => el.innerText)
  check(`关于系统显示 v${version}`, aboutText.includes(`v${version}`),
    aboutText.replace(/\s+/g, ' ').slice(0, 70))
  await snap('03-settings-about')

  console.log(`\n截图目录：${OUT}`)
  await browser.close()
}

main().catch(e => { console.error(e); process.exit(1) })
