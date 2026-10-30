/**
 * 一键升级弹窗体检
 *
 * 为什么需要这个脚本：
 * 升级弹窗是这套系统里最容易「看着有、其实没法用」的地方 ——
 * 之前它有 47 个 class 却是零样式（渲染出来是一堵文字墙），
 * 而「能点」和「点了有用」是两件事：判定结果、阻塞项、引导命令、
 * 手动命令、资产列表、阶段进度，都得真的出现在屏幕上。
 *
 * 这里全部用**计算样式**和**文本内容**来断言 ——
 * 不截图（截图得靠眼睛看，测不出「其实没渲染出来」），
 * 也不靠「元素存在」（存在但透明、零高度、白字白底，一样是坏的）。
 *
 * 用法：
 *   BASE=http://localhost:8096 node scripts/v30-verify-upgrade-dialog.cjs
 *   KB_USER=admin KB_PASS=xxx BASE=... node scripts/v30-verify-upgrade-dialog.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')

const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 元素是否「真的看得见」：有面积、不透明、在视口里、没被藏起来 */
const VISIBLE = (sel) => {
  const el = document.querySelector(sel)
  if (!el) return { ok: false, why: '元素不存在' }
  const r = el.getBoundingClientRect()
  if (r.width < 2 || r.height < 2) return { ok: false, why: `没有面积 ${Math.round(r.width)}×${Math.round(r.height)}` }
  const s = getComputedStyle(el)
  if (s.display === 'none' || s.visibility === 'hidden') return { ok: false, why: '被隐藏了' }
  if (Number(s.opacity) < 0.05) return { ok: false, why: `透明度 ${s.opacity}` }
  return { ok: true, text: (el.innerText || '').trim(), bg: s.backgroundColor, fg: s.color, h: Math.round(r.height) }
}

/** 文字颜色和背景色的对比度（WCAG） */
function contrast(fg, bg) {
  const lum = (c) => {
    const m = c.match(/[\d.]+/g)
    if (!m) return null
    const [r, g, b] = m.slice(0, 3).map(Number)
    const f = (v) => {
      v /= 255
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  const l1 = lum(fg), l2 = lum(bg)
  if (l1 == null || l2 == null) return null
  const a = Math.max(l1, l2), b = Math.min(l1, l2)
  return Math.round(((a + 0.055) / (b + 0.055)) * 100) / 100
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 1000 })

  const problems = []
  const ok = (msg) => console.log(`✔ ${msg}`)
  const bad = (msg) => { console.log(`✘ ${msg}`); problems.push(msg) }

  try {
    // ---- 登录 ----
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(1200)
    const inputs = await page.$$('input')
    if (inputs.length < 2) {
      bad('登录页没找到用户名/密码输入框')
    } else {
      // 先清空：登录页会预填用户名，直接 type 会叠成 "adminadmin"
      await inputs[0].click({ clickCount: 3 })
      await inputs[0].press('Backspace')
      await inputs[0].type(USER, { delay: 8 })
      await inputs[1].click({ clickCount: 3 })
      await inputs[1].press('Backspace')
      await inputs[1].type(PASS, { delay: 8 })
      // 按可见文字找登录按钮 —— 选择器容易被主题样式带偏，
      // 文字不会（登录页上就那一个「登录」按钮）
      const clicked = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button'))
          .find(x => (x.innerText || '').trim() === '登录')
        if (!b) return false
        b.click()
        return true
      })
      if (!clicked) bad('没找到「登录」按钮')
      // 等跳走（最多 15 秒）—— 登录失败会留在原地，不能只看固定时长
      for (let i = 0; i < 30; i++) {
        await sleep(500)
        const u = await page.evaluate(() => location.hash)
        if (!u.includes('/login')) break
      }
      const after = await page.evaluate(() => location.hash)
      if (after.includes('/login')) bad('登录没成功（还停在登录页）')
      else ok(`登录成功（${after}）`)
    }

    // ---- 进系统设置 ----
    await page.goto(`${BASE}/#/system/settings`, { waitUntil: 'networkidle2', timeout: 30000 })
    await sleep(2500)

    const hasDialog = await page.evaluate(() =>
      Array.from(document.querySelectorAll('button, .el-button')).some(b => /一键升级|检查更新/.test(b.innerText || '')))
    if (!hasDialog) {
      bad('设置页里找不到「一键升级」入口')
    } else {
      ok('设置页里有「一键升级」入口')
    }

    // ---- 打开弹窗 ----
    // 用真实鼠标点：设置页很长，按钮在视口外 2000 多像素处，
    // 不先滚过去就等于点了空气（element.click() 倒是能触发，
    // 但真实点击更接近用户，滚动这一步同时也暴露了「按钮藏得太深」）。
    const btnBox = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll('button, .el-button'))
        .find(x => /一键升级/.test(x.innerText || ''))
      if (!b) return null
      b.scrollIntoView({ block: 'center' })
      const r = b.getBoundingClientRect()
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
    })
    if (!btnBox) {
      bad('找不到「一键升级」按钮')
    } else {
      await sleep(600)
      const b2 = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button, .el-button'))
          .find(x => /一键升级/.test(x.innerText || ''))
        const r = b.getBoundingClientRect()
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
      })
      await page.mouse.click(b2.x, b2.y)
    }
    await sleep(3500)

    const dlg = await page.evaluate(() => {
      const el = document.querySelector('.el-dialog')
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { text: el.innerText || '', w: Math.round(r.width), h: Math.round(r.height) }
    })
    if (!dlg) {
      bad('弹窗没有打开')
    } else {
      ok(`弹窗已打开（${dlg.w}×${dlg.h}）`)
      const t = dlg.text

      // 1. 结论必须说清楚（两种状态各有一套说法，都算数）
      const canUpgrade = /可以自动升级/.test(t)
      const cannotUpgrade = /不能自动升级|暂不支持|条件不满足/.test(t)
      const isLatest = /已是最新版本/.test(t)
      if (canUpgrade || cannotUpgrade || isLatest) {
        ok(`弹窗给出了结论（${canUpgrade ? '可以自动升级'
          : isLatest ? '当前已是最新版本' : '当前不能自动升级'}）`)
      } else {
        bad('弹窗没有给出明确结论')
      }
      // 已是最新时，不能用「环境坏了」的口气说话
      if (isLatest && /当前环境不能自动升级/.test(t)) {
        bad('已是最新版本，却还写着「当前环境不能自动升级」')
      }

      // 2. 阻塞项 / 引导命令
      //
      // 「已是最新版本」时不该有这两样 —— 没有要升的版本，
      // 也就没有障碍要解决、没有命令要给。
      // （原来无条件要求，实例升到最新后体检就误报了）
      if (isLatest) {
        if (/阻塞|没法|无法/.test(t)) bad('已是最新版本，却还在说升级受阻')
        else ok('已是最新版本，不显示障碍与升级命令（正确）')
      } else {
        if (/阻塞|缺|没法|无法|开启|命令/.test(t)) ok('弹窗说明了障碍或给出了开启引导')
        else bad('弹窗既没说障碍，也没给开启引导')

        // 3. 手动命令（可升级时也给 —— 万一自动升级失败，人得有办法接手）
        if (/docker|compose|curl|bash\s+install\.sh/.test(t)) ok('弹窗里有可复制的命令')
        else bad('弹窗里没有任何可执行命令')
      }

      // 3b. 能升级时必须把四个阶段讲清楚，用户才知道会经历什么
      // （不能升级时不显示阶段是对的 —— 那时候先要解决障碍）
      if (canUpgrade) {
        if (/查询|镜像资产/.test(t) && /下载/.test(t) && /导入/.test(t) && /重启/.test(t))
          ok('四个阶段都写出来了')
        else bad('没把升级的四个阶段讲清楚')
      }

      // 3c. 有障碍时，每条都得说清「怎么办」
      //
      // 「有障碍」不能靠弹窗上的文字去猜 —— 已经武装好的部署本来就没有障碍，
      // 弹窗会直接说「已是最新」，这时一张卡片都不该有。
      // 所以以接口返回的 blockers 为准：卡片数要跟障碍数对上。
      const planBlockers = await page.evaluate(async () => {
        const r = await fetch('/api/system/update/plan', { credentials: 'include' })
        const j = await r.json()
        return Array.isArray(j?.blockers) ? j.blockers : []
      })
      if (planBlockers.length) {
        const blocks = await page.evaluate(() => {
          // 从弹窗根上找，别从第一张卡片里找卡片（那样只会找到空集）
          const root = document.querySelector('.el-dialog')
          if (!root) return []
          return Array.from(root.querySelectorAll('.upgrade-blocker')).map(x => (x.innerText || '').trim())
        })
        if (blocks.length !== planBlockers.length) {
          bad(`接口有 ${planBlockers.length} 条障碍，弹窗却渲染了 ${blocks.length} 张卡片`)
        } else {
          ok(`${planBlockers.length} 条障碍都渲染了卡片`)
          const noFix = blocks.filter(b => !/怎么办/.test(b))
          if (!noFix.length) ok(`${blocks.length} 条障碍都给了「怎么办」`)
          else bad(`有障碍没给解决办法：${noFix.length} 条`)
        }
      } else {
        ok('接口没有障碍，弹窗也不该有障碍卡片')
      }

      // 4. 样式：弹窗体不能是「裸 HTML」
      const style = await page.evaluate(() => {
        const el = document.querySelector('.el-dialog')
        if (!el) return null
        const s = getComputedStyle(el)
        const body = el.querySelector('.el-dialog__body')
        const bs = body ? getComputedStyle(body) : null
        return {
          radius: s.borderRadius, shadow: s.boxShadow,
          bodyPad: bs ? bs.padding : '', bodyBg: bs ? bs.backgroundColor : '',
          maxW: Math.round(el.getBoundingClientRect().width),
          scrollH: el.scrollHeight, clientH: el.clientHeight,
        }
      })
      if (style && style.radius && style.radius !== '0px') ok(`弹窗有圆角（${style.radius}）`)
      else bad('弹窗没有圆角，像裸 HTML')
      if (style && style.shadow && style.shadow !== 'none') ok('弹窗有阴影，和背景分得开')
      else bad('弹窗没有阴影')
      if (style && style.maxW >= 600) ok(`弹窗宽度 ${style.maxW}px，内容放得开`)
      else bad(`弹窗宽度只有 ${style && style.maxW}px，太窄`)
      if (style && style.bodyPad && style.bodyPad !== '0px') ok('弹窗内容有内边距')
      else bad('弹窗内容没有内边距')

      // 5. 文字对比度（正文）
      const c = await page.evaluate(() => {
        const el = document.querySelector('.el-dialog__body')
        if (!el) return null
        const s = getComputedStyle(el)
        let bg = s.backgroundColor
        // 往上找一层不透明的背景
        let p = el.parentElement
        while (p && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
          bg = getComputedStyle(p).backgroundColor
          p = p.parentElement
        }
        return { fg: s.color, bg }
      })
      if (c) {
        const r = contrast(c.fg, c.bg)
        if (r == null) bad('算不出正文对比度')
        else if (r >= 4.5) ok(`正文对比度 ${r}:1（达标）`)
        else bad(`正文对比度只有 ${r}:1，读不清`)
      }

      // 6. 按钮可点（且不溢出）
      const btns = await page.evaluate(() => {
        const el = document.querySelector('.el-dialog')
        if (!el) return []
        const dr = el.getBoundingClientRect()
        return Array.from(el.querySelectorAll('button')).map(b => {
          const r = b.getBoundingClientRect()
          const s = getComputedStyle(b)
          return {
            text: (b.innerText || '').trim(), w: Math.round(r.width), h: Math.round(r.height),
            overflow: r.right > dr.right + 1 || r.bottom > dr.bottom + 1,
            disabled: b.disabled || s.pointerEvents === 'none',
          }
        })
      })
      // 溢出判定要区分两种情况：
      //   真溢出（按钮跑到弹窗外，用户根本够不着）—— 那是布局 bug
      //   在可滚动区域内（弹窗内容长，要往下滚才看得到）—— 那是正常现象
      // 所以先把按钮滚进视野再判：滚进来还在弹窗外，才是真溢出。
      const overflowReal = []
      for (const b of btns) {
        if (!b.overflow) continue
        const fixed = await page.evaluate((text) => {
          const el = Array.from(document.querySelectorAll('.el-dialog button'))
            .find(x => (x.innerText || '').trim() === text)
          if (!el) return null
          el.scrollIntoView({ block: 'center' })
          const dr = document.querySelector('.el-dialog').getBoundingClientRect()
          const r = el.getBoundingClientRect()
          return { inside: r.right <= dr.right + 1 && r.bottom <= dr.bottom + 1 && r.left >= dr.left - 1 }
        }, b.text)
        if (fixed && !fixed.inside) overflowReal.push(b.text)
      }
      if (!overflowReal.length) ok(`弹窗内 ${btns.length} 个按钮都能点到（滚得动的算正常）`)
      else bad(`按钮真的溢出弹窗：${overflowReal.join('、')}`)

      const tooSmall = btns.filter(b => b.w > 0 && b.h > 0 && b.h < 28)
      if (!tooSmall.length) ok('按钮高度都够（≥28px）')
      else bad(`按钮太小：${tooSmall.map(b => `${b.text}(${b.h}px)`).join('、')}`)
    }
  } catch (e) {
    bad(`脚本异常：${e.message}`)
  } finally {
    await browser.close()
  }

  console.log('')
  if (problems.length) {
    console.log(`共发现 ${problems.length} 个问题`)
    process.exit(1)
  }
  console.log('一键升级弹窗体检通过')
}

main()
