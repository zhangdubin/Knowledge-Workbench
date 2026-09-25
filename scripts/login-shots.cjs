/**
 * 登录页专项截图：桌面明/暗 + 窄屏 + 展开「首次部署」提示
 *
 *   node scripts/login-shots.cjs [--head]
 *
 * 只截登录页，所以不进系统，直接以未登录状态打开 /#/login。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')
const S = require('./lib/session.cjs')

const OUT = '/Volumes/Samsung/poc/知识库/kb-workbench/docs/screenshots/login'
fs.mkdirSync(OUT, { recursive: true })

const errs = []
let n = 0

async function snap(p, name) {
  n += 1
  const file = `${OUT}/${String(n).padStart(2, '0')}-${name}.png`
  await p.screenshot({ path: file })
  console.log(`  📸 ${file.replace(OUT + '/', '')}`)
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: process.argv.includes('--head') ? false : 'shell',
    args: ['--no-sandbox'],
  })
  const p = await browser.newPage()
  p.on('console', m => { if (m.type() === 'error') errs.push(`console: ${m.text().slice(0, 160)}`) })
  p.on('pageerror', e => errs.push(`pageerror: ${String(e).slice(0, 160)}`))
  p.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400 && !r.url().includes('/api/auth/')) {
      errs.push(`http ${r.status()} ${r.url()}`)
    }
  })

  await p.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 })

  // 干净来访：清掉可能残留的会话与主题偏好
  await p.goto(S.FE, { waitUntil: 'domcontentloaded' })
  await p.evaluate(() => { localStorage.clear(); sessionStorage.clear() })

  // ---- 桌面 · 浅色
  await p.goto(`${S.FE}/#/login`, { waitUntil: 'networkidle2' })
  await p.evaluate(() => document.documentElement.classList.remove('dark'))
  await S.sleep(700)
  await snap(p, 'desktop-light')

  // ---- 桌面 · 暗色
  await p.evaluate(() => document.documentElement.classList.add('dark'))
  await S.sleep(500)
  await snap(p, 'desktop-dark')

  // ---- 桌面 · 展开「首次部署」提示
  await p.evaluate(() => document.documentElement.classList.remove('dark'))
  await p.evaluate(() => { const d = document.querySelector('.setup-hint'); if (d) d.open = true })
  await S.sleep(450)
  await snap(p, 'desktop-light-hint-open')

  // ---- 校验输入的交互态（聚焦光环 + 填充）
  await p.evaluate(() => { const d = document.querySelector('.setup-hint'); if (d) d.open = false })
  await p.type('input[autocomplete="username"]', '')
  await p.$eval('input[autocomplete="username"]', el => { el.value = '' })
  await p.type('input[autocomplete="username"]', 'admin')
  await p.focus('input[autocomplete="current-password"]')
  await p.type('input[autocomplete="current-password"]', 'secret')
  await S.sleep(350)
  await snap(p, 'desktop-light-filled')

  // ---- 窄屏（左侧品牌面收起，小 logo 出现）
  await p.setViewport({ width: 430, height: 900, deviceScaleFactor: 2 })
  await p.goto(`${S.FE}/#/login`, { waitUntil: 'networkidle2' })
  await p.evaluate(() => document.documentElement.classList.remove('dark'))
  await S.sleep(650)
  await snap(p, 'mobile-light')
  await p.evaluate(() => document.documentElement.classList.add('dark'))
  await S.sleep(400)
  await snap(p, 'mobile-dark')

  await browser.close()

  const uniq = [...new Set(errs)]
  console.log(uniquesMsg(uniq))
  process.exit(uniq.length ? 1 : 0)
}

function uniquesMsg(list) {
  return list.length
    ? `\n⚠️  捕获到 ${list.length} 条异常：\n   - ${list.join('\n   - ')}`
    : '\n✅ 控制台与接口无异常'
}

main().catch(e => { console.error(e); process.exit(1) })
