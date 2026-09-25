/**
 * v14 截图：数据中心（文件入库 + 混合检索）、AI 设置（embedding）、使用指南
 * 另外单独抓一张「回收站」弹窗，验证彻底删除入口。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs')

const PAGES = [
  ['', '01-dashboard'],
  ['library', '02-library'],
  ['library', '03-library-trash'],
  ['ai-settings', '04-ai'],
  ['guide', '05-guide'],
  ['search', '06-search'],
]

const OUT = '/Volumes/Samsung/poc/知识库/kb-workbench/docs/screenshots/v14'
fs.mkdirSync(OUT, { recursive: true })

const errs = []

;(async () => {
  const b = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const p = await b.newPage()
  await p.setViewport({ width: 1440, height: 950, deviceScaleFactor: 2 })

  p.on('console', m => { if (m.type() === 'error') errs.push('[console] ' + m.text()) })
  p.on('pageerror', e => errs.push('[pageerror] ' + e.message))
  p.on('response', r => { if (r.status() >= 400) errs.push(`[http ${r.status()}] ${r.url()}`) })

  for (const mode of ['light', 'dark']) {
    for (const [path, name] of PAGES) {
      // 连续两次 goto 同一 hash 不会重新导航，先跳到别处再回来
      if (name.includes('trash')) {
        await p.goto('http://127.0.0.1:8082/#/', { waitUntil: 'networkidle0' })
      }
      await p.goto('http://127.0.0.1:8082/#' + path, { waitUntil: 'networkidle0' })
      await p.evaluate(m => document.documentElement.classList.toggle('dark', m === 'dark'), mode)

      // 回收站弹窗：点开「回收站」按钮再截图
      if (name.includes('trash')) {
        await new Promise(r => setTimeout(r, 1200))
        await p.evaluate(() => {
          const el = [...document.querySelectorAll('button, .el-button')]
            .find(b => (b.innerText || '').includes('回收站'))
          if (el) el.click()
        })
        await new Promise(r => setTimeout(r, 1400))
      } else {
        await new Promise(r => setTimeout(r, 1600))
      }

      await p.screenshot({ path: `${OUT}/${name}-${mode}.png` })
    }
    console.log('done', mode)
  }

  // 断言：数据中心应出现向量索引统计与回收站入口
  await p.goto('http://127.0.0.1:8082/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1500))
  const txt = await p.evaluate(() => document.body.innerText)
  console.log('已建向量索引 =', txt.includes('已建向量索引'))
  console.log('回收站入口   =', txt.includes('回收站'))

  await b.close()
  console.log('--- errors ---')
  console.log(errs.length ? [...new Set(errs)].join('\n') : 'none')
})()
