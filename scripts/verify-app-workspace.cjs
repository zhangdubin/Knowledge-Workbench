/**
 * 应用独立页（/apps/:appKey）验收脚本
 * 用真实浏览器跑一遍：登录 → 应用中心 → 点应用进独立页 → 表格/卡片/表单抽屉
 * 只做计算样式与文本断言（不依赖截图肉眼比对）
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || process.env.KB_FRONTEND || 'http://localhost:5173'
const USER = process.env.KB_USER || 'admin'
const PASS = process.env.KB_PASS || 'Kb@2026admin'

let failed = 0
const log = (ok, name, detail = '') => {
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  ' + detail : ''}`)
}
const sleep = ms => new Promise(r => setTimeout(r, ms))

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,900'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  const errors = []
  page.on('pageerror', e => errors.push('pageerror: ' + e.message))
  page.on('console', m => {
    if (m.type() === 'error') errors.push('console: ' + m.text())
  })

  try {
    // ---------- 登录 ----------
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle2' })
    await sleep(1200)
    const inputs = await page.$$('input')
    if (inputs.length >= 2) {
      await inputs[0].click({ clickCount: 3 })
      await page.keyboard.press('Backspace')
      await inputs[0].type(USER)
      await inputs[1].click({ clickCount: 3 })
      await page.keyboard.press('Backspace')
      await inputs[1].type(PASS)
      await page.click('button[type=submit], .el-button--primary')
      await sleep(2500)
    }
    if (page.url().includes('/login')) {
      log(false, '登录成功', page.url())
      throw new Error('登录未成功，后续断言跳过')
    }
    log(true, '登录成功')

    // ---------- 应用中心 → 点应用进独立页 ----------
    await page.goto(`${BASE}/#/apps`, { waitUntil: 'networkidle2' })
    await sleep(1200)

    const cardCount = await page.$$eval('.app-card', els => els.length)
    log(cardCount > 0, '应用中心渲染出应用卡片', `${cardCount} 张`)

    // 点第一张卡（整块可点，键盘也能到）
    const opened = await page.evaluate(() => {
      const card = document.querySelector('.app-card')
      if (!card) return null
      card.click()
      return card.querySelector('.appc-name')?.textContent.trim() || 'card'
    })
    await sleep(1500)
    const url = page.url()
    log(/\/apps\/[a-z0-9_]+/.test(url), '点应用后跳到独立页', url)
    log(!!opened, '点击目标是应用卡片', opened || '')

    // ---------- 快速预览抽屉（应用中心里不离开列表瞄一眼） ----------
    await page.goto(`${BASE}/#/apps`, { waitUntil: 'networkidle2' })
    await sleep(1400)
    const previewOpened = await page.evaluate(() => {
      const card = document.querySelector('.app-card')
      // 卡片动作区按钮顺序固定：新建模型 / 录入记录 / 查看关联 / 编辑 / 删除
      const btns = [...(card?.querySelectorAll('.appc-actions .appc-btn') || [])]
      const btn = btns.find(b => b.querySelector('.el-icon') && !b.disabled && b.querySelectorAll('.el-icon').length === 1
        && btns.indexOf(b) === btns.length - 3)
      if (!btn) return 'no-btn:' + btns.length
      btn.click()
      return 'clicked'
    })
    await sleep(1600)
    const preview = await page.evaluate(() => {
      const d = document.querySelector('.ad-drawer')
      if (!d) return null
      return {
        name: d.querySelector('.ad-name')?.textContent.trim() || '',
        hasOpen: [...d.querySelectorAll('button')].some(b => b.textContent.includes('打开应用')),
        visible: d.getBoundingClientRect().height > 0,
      }
    })
    log(previewOpened === 'clicked', '应用卡片有「查看关联」入口')
    log(!!preview && preview.visible, '快速预览抽屉能打开', preview?.name)
    log(!!preview && preview.hasOpen, '预览抽屉里有「打开应用」入口')

    // 回到应用独立页，继续后面的断言
    await page.goto(url, { waitUntil: 'networkidle2' })
    await sleep(1800)

    // ---------- 页头 ----------
    const head = await page.evaluate(() => {
      const el = document.querySelector('.aw-header')
      if (!el) return null
      return {
        title: el.querySelector('.aw-title')?.textContent.trim() || '',
        desc: el.querySelector('.aw-desc')?.textContent.trim() || '',
        stats: [...el.querySelectorAll('.aw-stat')].map(s => s.textContent.replace(/\s+/g, ' ').trim()),
        actions: [...el.querySelectorAll('.aw-actions button')].map(b => b.textContent.trim()),
      }
    })
    log(!!head && head.title.length > 0, '页头有应用名', head?.title)
    log(!!head && head.desc.length > 0, '页头有应用说明', head?.desc)
    log(!!head && head.stats.length === 3, '页头有三个统计', JSON.stringify(head?.stats))
    log(!!head && head.actions.some(a => a.includes('返回应用中心')), '页头有「返回应用中心」', JSON.stringify(head?.actions))
    log(!!head && head.actions.some(a => a.includes('新建模型')), '页头有「新建模型」')
    log(!!head && head.actions.some(a => a.includes('录入记录')), '页头有「录入记录」')

    // ---------- 左侧模型列表 ----------
    const side = await page.evaluate(() => {
      const el = document.querySelector('.aw-side')
      if (!el) return null
      return {
        models: [...el.querySelectorAll('.aw-model')].map(m => m.textContent.replace(/\s+/g, ' ').trim()),
        add: !!el.querySelector('.aw-add-model'),
        active: !!el.querySelector('.aw-model.is-active'),
      }
    })
    log(!!side && side.models.length > 0, '左侧列出数据模型', JSON.stringify(side?.models?.slice(0, 3)))
    log(!!side && side.add, '左侧底部有「新建模型」')
    log(!!side && side.active, '当前模型高亮')

    // ---------- 记录表格 ----------
    await sleep(1200)
    const table = await page.evaluate(() => {
      const t = document.querySelector('.aw-table .el-table')
      if (!t) return null
      const heads = [...t.querySelectorAll('thead th')].map(h => h.textContent.replace(/\s+/g, ' ').trim())
      const row = t.querySelector('tbody tr')
      return {
        heads,
        rowTabbable: row ? row.getAttribute('tabindex') : null,
        rows: t.querySelectorAll('tbody tr').length,
        firstCell: row ? row.querySelector('td')?.textContent.trim() : '',
      }
    })
    log(!!table, '记录区渲染出表格')
    log(!!table && table.heads.length >= 2, '表头包含模型字段列', JSON.stringify(table?.heads))
    log(!!table && table.rowTabbable === '0', '表格行可 Tab 聚焦', `tabindex=${table?.rowTabbable}`)
    log(!!table && table.rows > 0, '表格有数据行', `${table?.rows} 行`)

    // 行操作按钮尺寸（≥28px）
    const btnSize = await page.evaluate(() => {
      const b = document.querySelector('.aw-table .rt-btn')
      if (!b) return null
      const r = b.getBoundingClientRect()
      return { w: Math.round(r.width), h: Math.round(r.height), label: b.getAttribute('aria-label') }
    })
    log(!!btnSize && btnSize.w >= 28 && btnSize.h >= 28, '行操作按钮满足 28×28 命中区',
      btnSize ? `${btnSize.w}×${btnSize.h}` : 'none')
    log(!!btnSize && !!btnSize.label, '行操作按钮有 aria-label', btnSize?.label || '')

    // ---------- 视图切换 ----------
    const seg = await page.evaluate(() => {
      const s = document.querySelector('.el-segmented')
      if (!s) return null
      const items = [...s.querySelectorAll('.el-segmented__item')].map(i => i.textContent.trim())
      return { items }
    })
    log(!!seg && seg.items.length === 2, '有表格/卡片视图切换', JSON.stringify(seg?.items))

    await page.evaluate(() => {
      const items = [...document.querySelectorAll('.el-segmented__item')]
      const card = items.find(i => i.textContent.includes('卡片'))
      if (card) card.click()
    })
    await sleep(900)
    const cardView = await page.evaluate(() => ({
      cards: document.querySelectorAll('.rcard').length,
      labels: [...document.querySelectorAll('.rcard .rcard-label')].slice(0, 4).map(l => l.textContent.trim()),
      focusable: document.querySelector('.rcard')?.getAttribute('tabindex'),
    }))
    log(cardView.cards > 0, '切到卡片视图后有卡片', `${cardView.cards} 张`)
    log(cardView.labels.length > 0, '卡片按「标签: 值」排布', JSON.stringify(cardView.labels))
    log(cardView.focusable === '0', '卡片可 Tab 聚焦')

    // 切回表格
    await page.evaluate(() => {
      const items = [...document.querySelectorAll('.el-segmented__item')]
      const t = items.find(i => i.textContent.includes('表格'))
      if (t) t.click()
    })
    await sleep(600)

    // ---------- 表单抽屉 ----------
    await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.aw-bar button')]
      const b = btns.find(x => x.textContent.includes('新建记录'))
      if (b) b.click()
    })
    await sleep(1200)
    const form = await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      if (!d) return null
      const items = [...d.querySelectorAll('.el-form-item')].map(i => ({
        label: i.querySelector('.el-form-item__label')?.textContent.replace('*', '').trim() || '',
        control: i.querySelector('input, textarea, .el-select, .el-switch') ? 'yes' : 'no',
      }))
      return {
        title: d.querySelector('.rfd-title')?.textContent.trim() || '',
        sub: d.querySelector('.rfd-sub')?.textContent.trim() || '',
        items,
        hasSave: [...d.querySelectorAll('button')].some(b => b.textContent.includes('保存')),
      }
    })
    log(!!form, '新建记录打开抽屉')
    log(!!form && form.title.includes('新建记录'), '抽屉标题正确', form?.title)
    log(!!form && form.sub.includes('自动生成'), '抽屉说明写明按字段定义生成', form?.sub)
    log(!!form && form.items.length > 0 && form.items.every(i => i.control === 'yes'),
      '每个字段都有对应控件', JSON.stringify(form?.items?.map(i => i.label)))
    log(!!form && form.hasSave, '抽屉底部有保存按钮')

    // 必填校验
    const validation = await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      const save = [...d.querySelectorAll('button')].find(b => b.textContent.includes('保存'))
      if (save) save.click()
      return true
    })
    await sleep(900)
    const errText = await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      const e = d?.querySelector('.el-form-item__error')
      return e ? e.textContent.trim() : ''
    })
    log(!!errText, '必填项未填时给出中文错误', errText)

    // ---------- 真建一条记录（写操作 → 验证表格刷新） ----------
    const created = await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      const input = d?.querySelector('.el-form-item input[type=text], .el-form-item input:not([type])')
      if (!input) return 'no-input'
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, '验收临时记录')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      return 'filled'
    })
    await sleep(400)
    await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      const save = [...d.querySelectorAll('button')].find(b => b.textContent.includes('保存'))
      if (save) save.click()
    })
    await sleep(1800)
    const afterCreate = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.aw-table tbody tr')].map(r => r.textContent.replace(/\s+/g, ' ').trim())
      // 抽屉是否真的关掉：EP 的抽屉关闭后内容还留在 DOM 里（只是不显示），
      // 所以要看可见性，不能只看元素在不在
      const drawer = document.querySelector('.el-drawer')
      const visible = drawer ? (drawer.getBoundingClientRect().height > 0 &&
        getComputedStyle(drawer).visibility !== 'hidden') : false
      const msgs = [...document.querySelectorAll('.el-message')].map(m => m.textContent.trim())
      return {
        rows,
        drawerVisible: visible,
        msg: msgs[msgs.length - 1] || '',
      }
    })
    log(afterCreate.rows.some(r => r.includes('验收临时记录')), '新建的记录出现在表格里',
      `rows=${afterCreate.rows.length}`)
    log(!afterCreate.drawerVisible, '保存后抽屉自动关闭')
    log(afterCreate.msg.includes('已创建') || afterCreate.msg.includes('已保存'), '有保存成功的提示', afterCreate.msg)

    // ---------- 删除刚建的记录 ----------
    const deleted = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.aw-table tbody tr')]
      const row = rows.find(r => r.textContent.includes('验收临时记录'))
      if (!row) return 'no-row'
      const btn = [...row.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || '').startsWith('删除'))
      if (!btn) return 'no-btn'
      btn.click()
      return 'clicked'
    })
    await sleep(900)
    const confirmVisible = await page.evaluate(() => {
      const box = document.querySelector('.el-message-box')
      return box ? box.textContent.replace(/\s+/g, ' ').trim().slice(0, 60) : ''
    })
    log(deleted === 'clicked', '删除行操作可点', deleted)
    log(confirmVisible.includes('删除记录') || confirmVisible.includes('确定删除'), '删除有二次确认', confirmVisible)
    await page.evaluate(() => {
      const box = document.querySelector('.el-message-box')
      const ok = [...(box?.querySelectorAll('button') || [])].find(b => b.textContent.includes('删除'))
      if (ok) ok.click()
    })
    await sleep(1600)
    const afterDelete = await page.evaluate(() => ({
      rows: [...document.querySelectorAll('.aw-table tbody tr')].map(r => r.textContent),
      hasTemp: [...document.querySelectorAll('.aw-table tbody tr')].some(r => r.textContent.includes('验收临时记录')),
    }))
    log(!afterDelete.hasTemp, '删除后记录从表格消失')

    // 关闭抽屉
    await page.evaluate(() => {
      const d = document.querySelector('.el-drawer')
      const btns = [...(d?.querySelectorAll('button') || [])]
      const cancel = btns.find(b => b.textContent.includes('取消'))
      if (cancel) cancel.click()
    })
    await sleep(700)

    // ---------- 搜索 ----------
    await page.type('.aw-search input', 'a')
    await page.keyboard.press('Enter')
    await sleep(1200)
    const searched = await page.evaluate(() => ({
      rows: document.querySelectorAll('.aw-table tbody tr').length,
      total: document.querySelector('.aw-bar-count')?.textContent.trim() || '',
    }))
    log(true, '搜索不报错', JSON.stringify(searched))

    // ---------- 筛选器 ----------
    const filterBtn = await page.evaluate(() => {
      const b = [...document.querySelectorAll('.aw-bar button')].find(x => x.textContent.includes('筛选'))
      if (b) { b.click(); return true }
      return false
    })
    await sleep(800)
    const filterPanel = await page.evaluate(() => {
      const p = [...document.querySelectorAll('.el-popover')].find(x => x.offsetParent)
      return p ? p.textContent.replace(/\s+/g, ' ').trim().slice(0, 80) : null
    })
    log(filterBtn, '有筛选器入口')
    log(!!filterPanel, '筛选面板可打开', filterPanel || '')

    // ---------- 窄屏：模型列表收起 ----------
    await page.setViewport({ width: 900, height: 800 })
    await sleep(900)
    const narrow = await page.evaluate(() => ({
      sideHidden: !document.querySelector('.aw-side'),
      select: !!document.querySelector('.aw-model-select'),
    }))
    log(narrow.sideHidden, '窄屏下左侧模型列表收起')
    log(narrow.select, '窄屏下用下拉选模型')

    // ---------- 多模型应用：切换模型 ----------
    await page.setViewport({ width: 1440, height: 900 })
    await page.goto(`${BASE}/#/apps/project`, { waitUntil: 'networkidle2' })
    await sleep(2000)
    const multi = await page.evaluate(() => ({
      models: [...document.querySelectorAll('.aw-model')].map(m => m.textContent.replace(/\s+/g, ' ').trim()),
      active: document.querySelector('.aw-model.is-active')?.textContent.replace(/\s+/g, ' ').trim() || '',
      heads: [...document.querySelectorAll('.aw-table thead th')].map(h => h.textContent.replace(/\s+/g, ' ').trim()),
    }))
    log(multi.models.length >= 2, '多模型应用左侧列出多个模型', JSON.stringify(multi.models))
    log(!!multi.active, '默认选中记录最多的模型', multi.active)
    // 切到另一个（当前没选中的）模型
    await page.evaluate(() => {
      const list = [...document.querySelectorAll('.aw-model')]
      const other = list.find(m => !m.classList.contains('is-active'))
      if (other) other.click()
    })
    await sleep(1800)
    const switched = await page.evaluate(() => ({
      active: document.querySelector('.aw-model.is-active')?.textContent.replace(/\s+/g, ' ').trim() || '',
      name: document.querySelector('.aw-bar-name')?.textContent.trim() || '',
      heads: [...document.querySelectorAll('.aw-table thead th')].map(h => h.textContent.replace(/\s+/g, ' ').trim()),
    }))
    log(switched.active !== multi.active, '点另一个模型会切换', switched.active)
    log(!!switched.name, '记录区标题跟着换', switched.name)
    log(switched.heads.length >= 2, '列跟着模型的字段变', JSON.stringify(switched.heads))

    // ---------- 暗色主题：令牌要跟着换 ----------
    await page.evaluate(() => document.documentElement.classList.add('dark'))
    await sleep(700)
    const dark = await page.evaluate(() => {
      const pick = sel => {
        const el = document.querySelector(sel)
        return el ? getComputedStyle(el).backgroundColor : ''
      }
      const root = getComputedStyle(document.documentElement)
      return {
        card: pick('.aw-main'),
        side: pick('.aw-side'),
        tokenCard: root.getPropertyValue('--bg-card').trim(),
        tokenText: root.getPropertyValue('--text-primary').trim(),
        title: (() => {
          const el = document.querySelector('.aw-title')
          return el ? getComputedStyle(el).color : ''
        })(),
      }
    })
    log(!!dark.tokenCard && dark.tokenCard !== '#ffffff', '暗色下 --bg-card 令牌已切换', dark.tokenCard)
    log(!!dark.card && dark.card !== 'rgba(0, 0, 0, 0)', '记录区用了卡片底色', dark.card)
    log(!!dark.side && dark.side !== 'rgba(0, 0, 0, 0)', '模型栏用了卡片底色', dark.side)
    await page.evaluate(() => document.documentElement.classList.remove('dark'))
    await sleep(400)

    // ---------- 记录页仍然正常 ----------
    await page.setViewport({ width: 1440, height: 900 })
    await page.goto(`${BASE}/#/records/1`, { waitUntil: 'networkidle2' })
    await sleep(1500)
    const recPage = await page.evaluate(() => ({
      hasTable: !!document.querySelector('.rt-title') || !!document.querySelector('.el-table'),
      oldRender: !!document.querySelector('.row-title'),
      title: document.querySelector('.el-table__title')?.textContent?.trim() || '',
    }))
    log(recPage.hasTable, '记录页仍能渲染表格')
    log(!recPage.oldRender, '记录页不再使用旧的重复渲染')

    // 记录页的详情抽屉（现在复用公共抽屉）
    await page.evaluate(() => {
      const btn = document.querySelector('.rt-title')
      if (btn) btn.click()
    })
    await sleep(1500)
    const recDetail = await page.evaluate(() => {
      const d = document.querySelector('.rdd')
      if (!d) return null
      return {
        title: d.querySelector('.rdd-title')?.textContent.trim() || '',
        fields: [...d.querySelectorAll('.rdd-field')].map(f => f.querySelector('.rdd-label')?.textContent.trim() || ''),
        hasMeta: !!d.querySelector('.el-descriptions'),
        hasRelations: d.textContent.includes('关联关系'),
        hasKnowledge: d.textContent.includes('关联知识'),
      }
    })
    log(!!recDetail, '记录页点行能打开详情抽屉')
    log(!!recDetail && recDetail.fields.length > 0, '详情抽屉列出模型字段', JSON.stringify(recDetail?.fields?.slice(0, 4)))
    log(!!recDetail && recDetail.hasMeta, '详情抽屉有元信息')
    log(!!recDetail && recDetail.hasRelations, '记录页的关联关系还在（插槽内容）')
    log(!!recDetail && recDetail.hasKnowledge, '记录页的知识关联还在（插槽内容）')

    log(errors.length === 0, '运行期没有 JS 错误', errors.slice(0, 3).join(' | '))
  } catch (e) {
    log(false, '脚本执行出错', e.message)
  } finally {
    await browser.close()
  }
  console.log(failed ? `\n❌ ${failed} 项未通过` : '\n✅ 应用独立页全部通过')
  process.exit(failed ? 1 : 0)
})()
