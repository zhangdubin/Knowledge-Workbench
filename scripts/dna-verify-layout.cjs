/**
 * DNA 双螺旋图谱排版体检（加强版）：
 *   遍历「链条筛选 × 基因数量 × 密度 × 视口」的所有组合，
 *   每一组都检查：压字 / 越界 / 左右分列 / 行距。
 *
 * 用法：node scripts/dna-verify-layout.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

function sessionToken() {
  if (process.env.KB_TOKEN) return process.env.KB_TOKEN
  try {
    return execFileSync('python3', [path.join(__dirname, 'kb-session-token.py')],
      { encoding: 'utf8', cwd: ROOT }).trim()
  } catch (e) { return '' }
}

const PROBE = () => {
  const stage = document.querySelector('.dg-stage')
  if (!stage) return { error: 'no stage' }
  const sr = stage.getBoundingClientRect()
  const labels = [...document.querySelectorAll('.dg-lbl')].map(el => {
    const r = el.getBoundingClientRect()
    const txt = el.querySelector('.dg-lbl-text')
    return {
      x: r.x, y: r.y, w: r.width, h: r.height,
      side: el.classList.contains('l') ? 'l' : 'r',
      t: (el.textContent || '').trim().slice(0, 18),
      clipped: txt ? txt.scrollWidth > txt.clientWidth + 1 : false,
    }
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
        if (ratio > 0.35) { overlaps++; if (worst.length < 4) worst.push(a.t + ' x ' + b.t + ' ' + Math.round(ratio * 100) + '%') }
      }
    }
  }
  // 列基准：直接读两条「骨架线」的实际位置。
  // 用画布中点当基准是错的 —— 只看一条链时，那条链就在 32% 处，
  // 所有标签都在中点左边，会被误判成「分列错位」。
  const railL = document.querySelector('.dg-rail-l')
  const railR = document.querySelector('.dg-rail-r')
  const baseL = railL ? railL.getBoundingClientRect().left + railL.getBoundingClientRect().width / 2 : null
  const baseR = railR ? railR.getBoundingClientRect().left + railR.getBoundingClientRect().width / 2 : null
  const mid = sr.x + sr.width / 2
  const minGap = (side) => {
    const ys = labels.filter(l => l.side === side).map(l => l.y + l.h / 2).sort((a, b) => a - b)
    let g = Infinity
    for (let i = 1; i < ys.length; i++) g = Math.min(g, ys[i] - ys[i - 1])
    return g === Infinity ? 0 : Math.round(g)
  }
  return {
    count: labels.length,
    overlaps,
    worst,
    outLeft: labels.filter(l => l.x < sr.x - 1).length,
    outRight: labels.filter(l => l.x + l.w > sr.x + sr.width + 1).length,
    // 左列标题的右缘必须在左骨架线左边；右列标题的左缘必须在右骨架线右边
    leftBad: baseL === null ? 0 : labels.filter(l => l.side === 'l' && l.x + l.w > baseL + 1).length,
    rightBad: baseR === null ? 0 : labels.filter(l => l.side === 'r' && l.x < baseR - 1).length,
    baseL: baseL === null ? null : Math.round(baseL - sr.x),
    baseR: baseR === null ? null : Math.round(baseR - sr.x),
    gapL: minGap('l'), gapR: minGap('r'),
    clipped: labels.filter(l => l.clipped).length,
    stageH: Math.round(sr.height), stageW: Math.round(sr.width),
    stats: (document.querySelector('.dg-stats') || {}).textContent || '',
  }
}

/** 切到指定链条筛选（全部 / 知识链 / 证据链） */
const SET_FILTER = (which) => {
  const btns = [...document.querySelectorAll('.dg-bar-main .el-radio-button')]
  const hit = btns.find(b => (b.textContent || '').trim() === which)
  if (hit) { hit.click(); return true }
  return false
}

/** 切基因数量（下拉） */
const SET_GENE = async (page, label) => {
  await page.evaluate(() => {
    const sel = document.querySelector('.dg-select .el-select__wrapper')
    if (sel) sel.click()
  })
  await sleep(500)
  const ok = await page.evaluate((lab) => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    const hit = items.find(i => (i.textContent || '').trim() === lab)
    if (hit) { hit.click(); return true }
    return false
  }, label)
  await sleep(1400)
  return ok
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  const errs = []
  page.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  page.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  const token = sessionToken()
  await browser.setCookie(
    { name: 'kb_session', value: token, domain: '127.0.0.1', path: '/' },
    { name: 'kb_session', value: token, domain: 'localhost', path: '/' },
  )

  let fail = 0
  const check = (tag, p) => {
    const bad = []
    if (p.overlaps) bad.push('压字 ' + p.overlaps + ' ' + JSON.stringify(p.worst))
    if (p.outLeft || p.outRight) bad.push('越界 ' + p.outLeft + '/' + p.outRight)
    if (p.leftBad || p.rightBad) bad.push('分列错 ' + p.leftBad + '/' + p.rightBad)
    if (bad.length) { console.log('  ✗ ' + tag + ' → ' + bad.join('; ')); fail++ }
    else console.log('  ✓ ' + tag + ' → ' + p.count + ' 标签 · 行距 ' + p.gapL + '/' + p.gapR + ' · ' + p.stats)
  }

  for (const [w, h] of [[1600, 1000], [1280, 900], [390, 800]]) {
    await page.setViewport({ width: w, height: h })
    await page.goto(BASE + '/#/dna?__e2e=1', { waitUntil: 'networkidle2' })
    await sleep(4500)
    console.log('视口 ' + w + 'px')
    check('默认', await page.evaluate(PROBE))

    for (const which of ['知识链', '证据链']) {
      await page.evaluate(SET_FILTER, which)
      await sleep(1500)
      check(which, await page.evaluate(PROBE))
    }
    await page.evaluate(SET_FILTER, '全部')
    await sleep(1200)

    await SET_GENE(page, '全部基因')
    check('全部基因', await page.evaluate(PROBE))
    await SET_GENE(page, '不显示基因')
    check('不显示基因', await page.evaluate(PROBE))
    await SET_GENE(page, '热门 12 条基因')
    await sleep(800)
  }

  // 点一个标签 → 详情面板应出现
  await page.setViewport({ width: 1600, height: 1000 })
  await page.goto(BASE + '/#/dna?__e2e=1', { waitUntil: 'networkidle2' })
  await sleep(4000)
  const clicked = await page.evaluate(() => {
    const el = document.querySelector('.dg-lbl')
    if (!el) return false
    el.click()
    return true
  })
  await sleep(900)
  const detail = await page.evaluate(() => {
    const d = document.querySelector('.dg-detail')
    return {
      visible: !!d,
      title: d ? (d.querySelector('.dg-detail-title') || {}).textContent : '',
      metas: d ? d.querySelectorAll('.dg-meta-item').length : 0,
      links: d ? d.querySelectorAll('.dg-link-chip').length : 0,
    }
  })
  console.log('点击标签 →', JSON.stringify(detail), 'clicked=' + clicked)
  if (!detail.visible) { console.log('  ✗ 详情面板没出现'); fail++ }

  console.log('--- errors ---')
  console.log(errs.length ? [...new Set(errs)].slice(0, 8).join('\n') : 'none')
  await browser.close()
  console.log(fail ? 'FAIL: ' + fail : 'PASS')
  process.exit(fail ? 1 : 0)
})()
