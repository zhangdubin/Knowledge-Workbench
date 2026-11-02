/**
 * 给三张图谱拍「全屏 + 不同缩放」的照片
 *
 * 用途：改动是「眼睛看得见」的东西，光靠单测和 DOM 断言说不清楚，
 * 留几张图，review 的人一眼就知道变成了什么样。
 *
 * 用法：node scripts/kb-graph-shots.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const fs = require('fs')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const OUT = path.join(ROOT, 'docs', 'screenshots')
const sleep = ms => new Promise(r => setTimeout(r, ms))

function sessionToken() {
  if (process.env.KB_TOKEN) return process.env.KB_TOKEN
  try {
    return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT }).trim()
  } catch (e) { return '' }
}

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=2'],
  })
  const page = await browser.newPage()
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )
  await page.setViewport({ width: 1600, height: 950, deviceScaleFactor: 2 })

  const shots = [
    { name: 'graph-fullscreen-dna', url: '/#/dna?__e2e=1', fs: '.dg-fs-btn' },
    { name: 'graph-fullscreen-relation', url: '/#/graph?__e2e=1', fs: '.gt-btn[aria-label="全屏显示"]' },
    { name: 'graph-fullscreen-knowledge', url: '/#/knowledge/graph?__e2e=1', fs: '.gt-btn[aria-label="全屏显示"]' },
  ]

  for (const s of shots) {
    await page.goto(BASE + s.url, { waitUntil: 'networkidle2' })
    await sleep(5200)
    // 进全屏
    await page.evaluate((sel) => {
      const el = document.querySelector(sel)
      if (el) el.click()
    }, s.fs)
    await sleep(1600)
    await page.screenshot({ path: path.join(OUT, s.name + '.png') })
    console.log('✓ ' + s.name + '.png')
    // 退出全屏
    await page.keyboard.press('Escape')
    await sleep(800)
  }

  // 再拍一张「缩到看不清」的：证明字会自己藏起来
  await page.goto(BASE + '/#/graph?__e2e=1', { waitUntil: 'networkidle2' })
  await sleep(5200)
  for (let i = 0; i < 5; i++) {
    await page.evaluate(() => {
      const b = document.querySelector('.gt-btn[aria-label="缩小"]')
      if (b) b.click()
    })
    await sleep(340)
  }
  await sleep(600)
  await page.screenshot({ path: path.join(OUT, 'graph-zoom-text-hidden.png') })
  console.log('✓ graph-zoom-text-hidden.png')

  await browser.close()
})()
