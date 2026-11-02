/**
 * DNA 双螺旋图谱现状截图 + 压字体检
 *
 * 登录：用 data/kb.db 里现成的会话 token（kb_session Cookie），
 * 避免为了截图去改管理员口令。
 *
 * 用法：node scripts/dna-shot.cjs   输出目录由 OUT 决定（默认 /tmp/kb-dna-shot）
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const OUT = process.env.OUT || '/tmp/kb-dna-shot'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

/** 从本地库里捞一条还没过期的会话 token —— 只读，不写库 */
function sessionToken() {
  if (process.env.KB_TOKEN) return process.env.KB_TOKEN
  try {
    return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT }).trim()
  } catch (e) {
    return ''
  }
}

const PROBE = () => {
  const host = document.querySelector('.dg-canvas')
  const stage = document.querySelector('.dg-stage')
  const labels = [...document.querySelectorAll('.dg-lbl')].map(el => {
    const r = el.getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height, t: (el.textContent || '').trim().slice(0, 20) }
  })
  let overlaps = 0
  const worst = []
  for (let i = 0; i < labels.length; i++) {
    for (let j = i + 1; j < labels.length; j++) {
      const a = labels[i], b = labels[j]
      const ix = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x))
      const iy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y))
      const inter = ix * iy
      if (inter > 0) {
        const ratio = inter / Math.min(a.w * a.h, b.w * b.h)
        if (ratio > 0.35) { overlaps++; if (worst.length < 10) worst.push(a.t + ' x ' + b.t + ' ' + Math.round(ratio * 100) + '%') }
      }
    }
  }
  const st = stage ? stage.getBoundingClientRect() : null
  const tool = document.querySelector('.dg-toolbar')
  return {
    labelCount: labels.length,
    overlaps,
    worst,
    stageH: st ? Math.round(st.height) : 0,
    stageW: st ? Math.round(st.width) : 0,
    toolbarH: tool ? Math.round(tool.getBoundingClientRect().height) : 0,
    hostH: host ? host.clientHeight : 0,
    docOverflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  }
}

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const errs = []
  page.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  page.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })

  const token = sessionToken()
  if (token) {
    await browser.setCookie(
      { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
      { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
    )
    console.log('session token: ' + token.slice(0, 6) + '...')
  } else {
    console.log('!! 没有可用会话：请设 KB_TOKEN 环境变量')
  }

  for (const dark of [false, true]) {
    for (const [w, h] of [[1600, 1000], [1280, 900], [390, 800]]) {
      await page.setViewport({ width: w, height: h })
      await page.goto(BASE + '/#/dna?__e2e=1', { waitUntil: 'networkidle2' })
      // 主题要在页面里切：about:blank 上访问 localStorage 会被浏览器拒绝
      await page.evaluate(d => {
        document.documentElement.classList.toggle('dark', d)
        try { localStorage.setItem('kb-theme', d ? 'dark' : 'light') } catch (e) { /* 无所谓 */ }
      }, dark)
      await sleep(4500)
      let probe
      try { probe = await page.evaluate(PROBE) } catch (e) { probe = { error: e.message } }
      const tag = 'dna-' + w + '-' + (dark ? 'dark' : 'light')
      console.log(tag, JSON.stringify(probe))
      await page.screenshot({ path: OUT + '/' + tag + '.png', fullPage: false })
    }
  }
  console.log('--- errors ---')
  console.log(errs.length ? [...new Set(errs)].slice(0, 10).join('\n') : 'none')
  await browser.close()
})()
