/**
 * 三张图谱的「全屏显示」与「文字随缩放自动调整」验收
 *
 *   ① DNA 双螺旋图谱（/#/dna）
 *   ② 关联图谱（/#/graph）
 *   ③ 知识图谱（/#/knowledge/graph）
 *
 * 验的是什么（都是用户真正会踩到的点）：
 *   · 点「全屏」→ 画布真的变大（vis 只在初始化时量过一次尺寸，
 *     不显式 setSize 的话画面会被 CSS 拉大 —— 糊的、位置还是偏的）
 *   · 全屏时背景页面不能跟着滚（滚轮要留给缩放图）
 *   · Esc 能退出全屏（这是用户唯一的退路）
 *   · 缩小到看不清时，字要自己藏起来，并给一句「放大就能看见」
 *   · 放大回来，字要自己回来
 *
 * 用法：node scripts/kb-verify-graph-fullscreen.cjs
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

let fail = 0
const ok = (cond, tag, extra) => {
  if (cond) console.log('  ✓ ' + tag + (extra ? ' → ' + extra : ''))
  else { console.log('  ✗ ' + tag + (extra ? ' → ' + extra : '')); fail++ }
}

/** 读全屏状态：根节点 class、画布实际尺寸、滚动锁 */
function PROBE_FS() {
  const root = document.querySelector('.dna-graph.is-fs, .gc.is-fs')
  const host = document.querySelector('.dg-canvas, .gc-canvas')
  // 哪张图就取哪张图的 network：__kbGraph 可能是上一张图留下的（组件卸载时会清掉）
  const net = document.querySelector('.dna-graph') ? window.__dnaNet : window.__kbGraph
  const back = net && net.canvas && net.canvas.frame ? net.canvas.frame.canvas : null
  const alive = net && typeof net.getScale === 'function'
  return {
    fs: !!root,
    hostW: host ? host.clientWidth : 0,
    hostH: host ? host.clientHeight : 0,
    backW: back ? back.width : 0,
    backH: back ? back.height : 0,
    scale: alive ? net.getScale() : 0,
    locked: document.body.style.overflow === 'hidden',
    // 提示可能有两条（缩放下限提示 + 文字档位提示），都要收
    hints: [...document.querySelectorAll('.dg-tier-hint, .gc-zoom-hint')].map(e => (e.textContent || '').trim()),
    lblOff: !!document.querySelector('.dg-stage.lbl-off'),
    lblOpacity: (() => {
      const l = document.querySelector('.dg-lbl')
      return l ? getComputedStyle(l).opacity : 'none'
    })(),
    // canvas 上的节点名（vis 画在 canvas 里，DOM 读不到）
    nodeLabel: (() => {
      if (!alive || !net.body || !net.body.data) return ''
      const ids = net.body.data.nodes.getIds()
      if (!ids.length) return ''
      return net.body.data.nodes.get(ids[0]).label || ''
    })(),
  }
}

/** 查工具条上的按钮在不在（不点 —— 「查」和「点」混在一起会把自己测错） */
async function hasBtn(page, selector) {
  return page.evaluate((sel) => !!document.querySelector(sel), selector)
}

/** 点工具条上的按钮（按 aria-label 或 class 找） */
async function clickBtn(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return false
    el.click()
    return true
  }, selector)
}

/** 等缩放稳定下来（物理引擎稳定后会自己 fit 一次，动画还在跑时读到的值是中间值） */
async function waitStableScale(page, timeoutMs = 8000) {
  const t0 = Date.now()
  let last = -1, same = 0
  while (Date.now() - t0 < timeoutMs) {
    const s = await page.evaluate(() => {
      const net = document.querySelector('.dna-graph') ? window.__dnaNet : window.__kbGraph
      return net ? net.getScale() : -1
    })
    // 连续 6 次（约 1.2 秒）不变才算稳定 —— 物理引擎的 fit 动画有 380ms
    if (Math.abs(s - last) < 0.001) { if (++same >= 6) return s } else { same = 0 }
    last = s
    await sleep(200)
  }
  return last
}

/** 点「缩小」n 次，等动画走完 */
async function zoomOut(page, sel, n) {
  for (let i = 0; i < n; i++) {
    await clickBtn(page, sel)
    await sleep(320)
  }
}
async function zoomIn(page, sel, n) {
  for (let i = 0; i < n; i++) {
    await clickBtn(page, sel)
    await sleep(320)
  }
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
  await page.setViewport({ width: 1440, height: 900 })

  const pages = [
    { name: 'DNA 双螺旋图谱', url: '/#/dna?__e2e=1', fs: '.dg-fs-btn', zoomOut: '.dg-zoom .el-button:nth-child(2)', zoomIn: '.dg-zoom .el-button:nth-child(1)' },
    { name: '关联图谱', url: '/#/graph?__e2e=1', fs: '.gt-btn[aria-label="全屏显示"]', zoomOut: '.gt-btn[aria-label="缩小"]', zoomIn: '.gt-btn[aria-label="放大"]' },
    { name: '知识图谱', url: '/#/knowledge/graph?__e2e=1', fs: '.gt-btn[aria-label="全屏显示"]', zoomOut: '.gt-btn[aria-label="缩小"]', zoomIn: '.gt-btn[aria-label="放大"]' },
  ]

  for (const p of pages) {
    console.log('\n' + p.name)
    await page.goto(BASE + p.url, { waitUntil: 'networkidle2' })
    await sleep(5200)

    const btnOk = await hasBtn(page, p.fs)
    ok(btnOk, '有全屏按钮')
    if (!btnOk) continue

    // ---------- ⓪ 先把缩放调成一个固定值 ----------
    // 为什么要在进全屏**之前**调：
    //   「退出全屏后视角原样回来」这条，只有在进全屏前有一个已知的缩放值才验得了。
    //
    // 为什么先要等缩放稳定：
    //   物理引擎稳定后会自己 fit 一次（带 380ms 动画），
    //   测试设的缩放会被那次 fit 覆盖 —— 基准值必须是**实际生效**的那个，
    //   所以设置完再读回来，退出后跟读回来的值比。
    await waitStableScale(page)
    await page.evaluate(() => {
      const net = document.querySelector('.dna-graph') ? window.__dnaNet : window.__kbGraph
      if (net) net.setOptions({ physics: { enabled: false } })
    })
    await sleep(400)
    // 用**应用自己的**放大按钮把缩放调到一个特征值。
    //   为什么不用脚本直接改 scale：物理引擎稳定时会自己 fit 一次，
    //   脚本设的值会被那次 fit 覆盖，基准值就不可信了。
    await zoomIn(page, p.zoomIn, 2)
    const setScale = await page.evaluate(() => {
      const net = document.querySelector('.dna-graph') ? window.__dnaNet : window.__kbGraph
      return net ? net.getScale() : 0
    })

    // ---------- ① 全屏：画布要真的变大 ----------
    const before = await page.evaluate(PROBE_FS)
    await clickBtn(page, p.fs)
    await sleep(1200)
    const inFs = await page.evaluate(PROBE_FS)
    ok(inFs.fs, '进入全屏', 'is-fs=' + inFs.fs)
    ok(inFs.backW > before.backW, '画布真的变大了（vis 重新量过尺寸）',
      before.backW + ' → ' + inFs.backW)
    ok(inFs.hostW >= before.hostW, '画布区域变宽',
      before.hostW + ' → ' + inFs.hostW)
    ok(inFs.locked, '背景页面已锁滚动（滚轮留给缩放）')

    // ---------- ① 全屏里点节点：详情必须浮在图上面 ----------
    // 为什么专门验这一条：
    //   节点详情抽屉是 append-to-body 的，z-index 由 Element Plus 统一发号。
    //   全屏浮层要是压得比它高，就会出现「点了节点什么也没发生」——
    //   这种问题在代码里完全看不出来，只有真点一次才知道。
    if (p.name === 'DNA 双螺旋图谱') {
      const clicked = await page.evaluate(() => {
        const l = document.querySelector('.dg-lbl')
        if (!l) return false
        l.click()
        return true
      })
      await sleep(700)
      const d = await page.evaluate(() => {
        const box = document.querySelector('.dg-detail')
        if (!box) return { opened: false }
        const r = box.getBoundingClientRect()
        return { opened: true, top: Math.round(r.top), h: Math.round(r.height) }
      })
      ok(clicked && d.opened && d.h > 0, '全屏里点标题 → 详情面板出现', JSON.stringify(d))
    } else {
      // 先把物理引擎停掉再点：
      // 物理还在跑的时候节点每帧都在动，按坐标点会点空 ——
      // 那不是点不中，是点的那一刻节点已经挪走了。
      await page.evaluate(() => {
        const net = window.__kbGraph
        if (net) net.setOptions({ physics: { enabled: false } })
      })
      await sleep(1200)
      const pos = await page.evaluate(() => {
        const net = window.__kbGraph
        if (!net) return null
        const ids = net.body.data.nodes.getIds()
        if (!ids.length) return null
        const all = net.getPositions(ids)
        // 挑一个离画面中心最近的节点：边缘上的节点可能被视口裁掉，点不到
        let cx = 0, cy = 0
        for (const id of ids) { cx += all[id].x; cy += all[id].y }
        cx /= ids.length; cy /= ids.length
        let best = null, bestD = Infinity
        for (const id of ids) {
          const d = Math.hypot(all[id].x - cx, all[id].y - cy)
          if (d < bestD) { bestD = d; best = id }
        }
        const dom = net.canvasToDOM(all[best])
        const rect = net.canvas.frame.canvas.getBoundingClientRect()
        const x = rect.left + dom.x, y = rect.top + dom.y
        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return null
        return { x, y, id: best }
      })
      ok(!!pos, '找到画布内可点的节点', pos ? pos.id : 'none')
      if (pos) await page.mouse.click(pos.x, pos.y)
      await sleep(1400)
      const drawer = await page.evaluate(() => {
        const el = document.querySelector('.gc-drawer')
        if (!el) return { open: false }
        const r = el.getBoundingClientRect()
        const ov = el.closest('.el-overlay')
        return {
          open: true,
          w: Math.round(r.width), h: Math.round(r.height),
          z: ov ? getComputedStyle(ov).zIndex : 'none',
          vis: r.width > 0 && r.height > 0,
        }
      })
      ok(drawer.open && drawer.vis, '全屏里点节点 → 详情抽屉出现', JSON.stringify(drawer))
      // 抽屉必须在浮层之上：拿两者的 z-index 比一比
      const stack = await page.evaluate(() => {
        const ov = document.querySelector('.gc.is-fs')
        const dr = document.querySelector('.gc-drawer')
        const z = e => (e ? Number(getComputedStyle(e).zIndex) || 0 : 0)
        const drOverlay = dr ? dr.closest('.el-overlay') : null
        return { overlay: z(ov), drawer: z(drOverlay) }
      })
      ok(stack.drawer > stack.overlay, '抽屉浮在全屏浮层之上',
        `浮层 ${stack.overlay} < 抽屉 ${stack.drawer}`)
      await page.keyboard.press('Escape')
      await sleep(500)
    }

    // ---------- ② Esc 退出 ----------
    await page.keyboard.press('Escape')
    await sleep(900)
    const outFs = await page.evaluate(PROBE_FS)
    ok(!outFs.fs, 'Esc 退出全屏')
    ok(!outFs.locked, '退出后恢复滚动')
    // 退出全屏必须把用户自己的视角还回去。
    //   以前退出也走 fit()，缩放被改了两轮（实测 1.0 → 0.60 → 0.45），
    //   图缩成一小团还得自己拉回来 —— 这就是「全屏显示有问题」里最明显的一条。
    ok(Math.abs(outFs.scale - setScale) < 0.05, '退出后视角原样还原（缩放没被冲掉）',
      setScale.toFixed(2) + ' → ' + outFs.scale.toFixed(2))

    // ---------- ③ 缩小 → 文字自动收起 ----------
    await zoomOut(page, p.zoomOut, 5)
    const small = await page.evaluate(PROBE_FS)
    ok(small.scale < 0.5, '已缩到看不清的区间', 'scale=' + small.scale.toFixed(2))
    if (p.name === 'DNA 双螺旋图谱') {
      ok(small.lblOff, '标题整层收起（不再压字）')
      ok(Number(small.lblOpacity) === 0, '标题确实不可见', 'opacity=' + small.lblOpacity)
    } else {
      ok(small.nodeLabel === '', '节点名已收起', JSON.stringify(small.nodeLabel))
    }
    ok(small.hints.some(h => /名称已隐藏|只显示图标/.test(h)),
      '给了「放大就能看见」的提示', small.hints.join(' | '))

    // ---------- ④ 放大回来 → 文字自动回来 ----------
    // 从 0.15 回到「给完整名字」那一档（≥0.8）需要 1.25^8 ≈ 5.96 → 0.89
    await zoomIn(page, p.zoomIn, 9)
    await sleep(700)
    const big = await page.evaluate(PROBE_FS)
    ok(big.scale > 0.5, '放大回来', 'scale=' + big.scale.toFixed(2))
    if (p.name === 'DNA 双螺旋图谱') {
      ok(!big.lblOff, '标题重新出现')
      ok(Number(big.lblOpacity) > 0, '标题重新可见', 'opacity=' + big.lblOpacity)
    } else {
      ok(big.nodeLabel.length > 3, '节点名重新出现（不是只剩图标）', JSON.stringify(big.nodeLabel))
    }
    ok(!big.hints.some(h => /名称已隐藏|只显示图标/.test(h)),
      '提示自动消失', big.hints.join(' | '))
  }

  console.log('\n--- errors ---')
  console.log(errs.length ? [...new Set(errs)].slice(0, 8).join('\n') : 'none')
  await browser.close()
  console.log(fail ? 'FAIL: ' + fail : 'PASS')
  process.exit(fail ? 1 : 0)
})()
