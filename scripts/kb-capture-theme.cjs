// 抓关键组件的计算样式：用来对比「样式改成按需引入前后」有没有变色
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const fs = require('fs')
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const TOKEN = fs.readFileSync('/tmp/kb-tok.txt', 'utf8').trim()

async function main() {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000 })
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' })
  await page.goto('http://127.0.0.1:8082/#/records/1', { waitUntil: 'networkidle2', timeout: 45000 })
  await new Promise(r => setTimeout(r, 2500))
  const out = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement)
    const pick = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const cs = getComputedStyle(el)
      return { bg: cs.backgroundColor, color: cs.color, border: cs.borderColor, font: cs.fontSize }
    }
    return {
      primary: root.getPropertyValue('--el-color-primary').trim(),
      success: root.getPropertyValue('--el-color-success').trim(),
      textPrimary: root.getPropertyValue('--el-text-color-primary').trim(),
      border: root.getPropertyValue('--el-border-color').trim(),
      bg: root.getPropertyValue('--el-bg-color').trim(),
      primaryBtn: pick('.el-button--primary'),
      plainBtn: pick('.el-button'),
      tag: pick('.el-tag'),
      input: pick('.el-input__inner'),
      bodyBg: getComputedStyle(document.body).backgroundColor,
      bodyColor: getComputedStyle(document.body).color,
    }
  })
  console.log(JSON.stringify(out, null, 2))
  await browser.close()
}
main().catch(e => { console.error('ERR', e.message); process.exit(1) })