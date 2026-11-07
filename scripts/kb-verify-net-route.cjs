/**
 * 「出网代理」这套东西的验收
 *
 * 验的是什么：
 *   ① 「测出网」按钮在，点了能把代理与直连各自的耗时/结论显示出来；
 *   ② 检查更新**不因为代理坏掉而失败** ——
 *      代理不通时要自动改走直连，并明确提示；
 *   ③ 提示的方向与探测结果一致（该提示就提示，不该提示就别添乱）。
 *
 * 这套逻辑的由来：真实踩到过一个「假活」的代理 ——
 * 端口开着、TCP 连得上，但它往上游取东西时一个字节也不回，
 * 而直连好得很。原来的实现死抱代理不放，用户只会看到
 * 「访问 GitHub 超时（8 秒）：容器到 api.github.com 的链路不通」。
 *
 * 断言只认**错误提示框**，不认整页文字：
 * Release Notes 里会引用旧报错的原文（CHANGELOG 里就写着），
 * 拿整页文字去匹配会把说明文字当成错误。
 *
 * 用法：node scripts/kb-verify-net-route.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

let failed = 0
function check(ok, label, extra) {
  console.log((ok ? '  ✓ ' : '  ✗ ') + label + (extra ? '  — ' + extra : ''))
  if (!ok) failed++
}

const WS = /\s+/g

async function main() {
  const token = execFileSync('python3', [path.join(ROOT, 'scripts/kb-session-token.py')],
    { encoding: 'utf8' }).trim()

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })
  await browser.setCookie({
    name: 'kb_session', value: token, domain: '127.0.0.1', path: '/',
  })

  console.log('打开系统设置页…')
  await page.goto(BASE + '/#/system/settings', { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(2500)

  await page.evaluate(() => {
    const el = document.querySelector('#sec-update')
    if (el) el.scrollIntoView({ block: 'start' })
  })
  await sleep(600)

  // ① 「测出网」按钮存在
  const hasProbeBtn = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('#sec-update button')]
    return btns.some(b => b.textContent.includes('测出网'))
  })
  check(hasProbeBtn, '「测出网」按钮存在')

  let probe = null
  if (hasProbeBtn) {
    // ② 点「测出网」，等出结果
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('#sec-update button')]
        .find(x => x.textContent.includes('测出网'))
      if (b) b.click()
    })
    await page.waitForSelector('.probe-panel', { timeout: 40000 })
    await sleep(800)

    probe = await page.evaluate(() => {
      const panel = document.querySelector('.probe-panel')
      if (!panel) return null
      const rows = [...panel.querySelectorAll('.probe-row')]
        .map(r => r.textContent.replace(/\s+/g, ' ').trim())
      return {
        rows,
        note: panel.querySelector('.probe-note')?.textContent.trim() || '',
        proxyOk: panel.querySelectorAll('.probe-row')[0]?.querySelector('.el-tag')?.textContent.trim() === '通',
        directOk: panel.querySelectorAll('.probe-row')[1]?.querySelector('.el-tag')?.textContent.trim() === '通',
        // 「压根没配代理」与「配了但坏了」是两回事：
        // 前者没什么可绕过的（不该提示），后者必须提示。
        proxyConfigured: panel.getAttribute('data-proxy-configured') === 'true',
      }
    })
    check(!!probe, '探测结果面板已渲染')
    if (probe) {
      console.log('    面板内容：')
      probe.rows.forEach(r => console.log('      · ' + r))
      console.log('      · 结论：' + probe.note)
      const proxyRow = probe.rows.find(r => r.includes('出站代理')) || ''
      const directRow = probe.rows.find(r => r.includes('直连')) || ''
      check(/代理/.test(proxyRow), '面板里给出了代理的结论')
      check(/直连/.test(directRow), '面板里给出了直连的结论')
      check(/ms/.test(proxyRow + directRow), '面板里给出了各自耗时')
    }
  }

  // ③ 点「检查更新」—— 代理坏着也必须成功（走直连）
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#sec-update button')]
      .find(x => x.textContent.includes('检查更新'))
    if (b) b.click()
  })
  await sleep(9000)

  const after = await page.evaluate(() => {
    const alerts = [...document.querySelectorAll('#sec-update .el-alert')]
    const errs = alerts.filter(a => a.className.includes('el-alert--error'))
    const warns = alerts.filter(a => a.className.includes('el-alert--warning'))
    return {
      errorTexts: errs.map(a => a.textContent.replace(/\s+/g, ' ').trim()),
      warnTexts: warns.map(a => a.textContent.replace(/\s+/g, ' ').trim()),
      hasBypassWarn: warns.some(a => a.textContent.includes('已自动改用直连')),
      showsVersion: /v\d+\.\d+\.\d+/.test(
        document.querySelector('#sec-update .ver-bar')?.textContent || ''),
    }
  })

  // 检查更新的错误框必须是空的 ——
  // 代理坏掉时正确表现是「成功 + 提示绕过」，不是「报错」。
  check(after.errorTexts.length === 0, '检查更新没有错误提示框',
    after.errorTexts.join(' | ') || '')
  check(after.showsVersion, '检查更新有结果（版本号已显示）')

  // 绕过的提示只在该提示时出现：
  //   配了代理且代理不通 → 要提示；
  //   压根没配代理 → 没什么可绕过的，不该提。
  const shouldWarn = !!(probe && probe.proxyConfigured && !probe.proxyOk && probe.directOk)
  if (shouldWarn) {
    check(after.hasBypassWarn, '明确提示「已自动改用直连」',
      after.warnTexts.join(' | ') || '（没有 warning 框）')
  } else {
    const why = probe && !probe.proxyConfigured ? '（没配代理）' : '（代理可用，无需绕过）'
    check(!after.hasBypassWarn, '不需要绕过时不啰嗦「已自动改用直连」' + why)
  }

  await browser.close()
  console.log(failed === 0 ? '\n全部通过 ✅' : '\n有 ' + failed + ' 项未通过 ❌')
  process.exit(failed === 0 ? 0 : 1)
}

main().catch(e => { console.error(e); process.exit(1) })
