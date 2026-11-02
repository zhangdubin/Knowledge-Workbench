/**
 * 交付截图：把这一轮的关键界面拍下来（给人看，不是给机器看）。
 * 用法：node scripts/kb-shots-round2.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const fs = require('fs')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const OUT = '/tmp/kb-round2'
const sleep = ms => new Promise(r => setTimeout(r, ms))

function sessionToken() {
  try {
    return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT }).trim()
  } catch (e) { return '' }
}

const SHOTS = [
  { name: 'dna-graph-light', hash: '/#/dna', w: 1680, h: 1050, theme: 'light' },
  { name: 'dna-graph-dark', hash: '/#/dna', w: 1680, h: 1050, theme: 'dark' },
  { name: 'dna-library-upload-limit', hash: '/#/dna-library', w: 1680, h: 1050, theme: 'light',
    after: async (page) => {
      await page.evaluate(() => {
        const t = [...document.querySelectorAll('.el-tabs__item')].find(x => (x.textContent || '').includes('源码树'))
        if (t) t.click()
      })
      await sleep(1500)
    } },
  { name: 'dev-projects', hash: '/#/dev', w: 1680, h: 1050, theme: 'light' },
  { name: 'dev-settings', hash: '/#/dev/settings', w: 1680, h: 1050, theme: 'light' },
]

const setTheme = async (page, theme) => {
  await page.evaluate((t) => {
    const KEY = 'kb-theme'
    try { localStorage.setItem(KEY, t) } catch (e) {}
    document.documentElement.classList.toggle('dark', t === 'dark')
    document.documentElement.setAttribute('data-theme', t)
  }, theme)
}

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  for (const s of SHOTS) {
    await page.setViewport({ width: s.w, height: s.h })
    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
    await setTheme(page, s.theme)
    await page.goto(BASE + s.hash, { waitUntil: 'networkidle2' })
    await sleep(5000)
    await setTheme(page, s.theme)
    await sleep(1200)
    if (s.after) await s.after(page)
    const file = path.join(OUT, s.name + '.png')
    await page.screenshot({ path: file })
    console.log('✓', file)
  }
  await browser.close()
})()
