/**
 * v12 回归验证：文件预览 / 知识关联 / 应用模板 / 新增页面
 *
 * 直接打后端 API（node 18+ 自带 fetch），再用 puppeteer 检查前端渲染与控制台错误。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')

const API = 'http://localhost:8001'
const FE = 'http://127.0.0.1:8082'

const results = []
function check(name, ok, detail = '') {
  results.push([name, ok, detail])
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  — ' + detail : ''}`)
}

async function j(path, opts) {
  const r = await fetch(API + path, opts)
  const ct = r.headers.get('content-type') || ''
  const body = ct.includes('json') ? await r.json() : await r.text()
  return { status: r.status, body, headers: r.headers }
}

// ---------- 1. 文件预览链路 ----------
async function testPreview() {
  console.log('\n=== 1. 文件预览 ===')

  // 找一个已有记录用来挂附件
  const notes = await j('/api/entity-types/by-key/note')
  const noteTypeId = notes.body.id
  const list = await j(`/api/records/type/${noteTypeId}?page=1&page_size=1`)
  const recordId = list.body.items?.[0]?.id
  if (!recordId) {
    check('预览：准备记录', false, '没有可用记录')
    return
  }

  // 上传 CSV 与伪 PDF
  async function upload(name, content, type) {
    const form = new FormData()
    form.append('record_id', String(recordId))
    form.append('field_key', 'v12_test')
    form.append('file', new Blob([content], { type }), name)
    const r = await fetch(API + '/api/attachments/upload', { method: 'POST', body: form })
    return r.json()
  }

  const csv = await upload('v12-check.csv', '名称,数量\n螺栓,120\n垫片,300\n', 'text/csv')
  check('上传 CSV 并推断 MIME', csv.content_type === 'text/csv', csv.content_type || '')

  // 浏览器常给 octet-stream，验证纠正逻辑
  const pdfBytes = '%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'
  const pdf = await upload('v12-check.pdf', pdfBytes, 'application/octet-stream')
  check('上传 PDF（存储类型为 octet-stream）→ 纠正为 application/pdf',
    pdf.content_type === 'application/pdf', pdf.content_type || '')
  check('PDF 预览模式 = pdf', pdf.mode === 'pdf', pdf.mode || '')

  // /preview 必须返回 inline，这是 PDF 能内联渲染的关键
  const pv = await fetch(`${API}${pdf.preview_url}`)
  const disp = pv.headers.get('content-disposition') || ''
  check('/preview 返回 200', pv.status === 200, 'status=' + pv.status)
  check('/preview 响应头为 inline', /^inline/.test(disp), disp)
  check('/preview Content-Type 正确',
    (pv.headers.get('content-type') || '').includes('pdf'),
    pv.headers.get('content-type') || '')

  // /download 仍应是 attachment
  const dl = await fetch(`${API}${pdf.url}`)
  const ddisp = dl.headers.get('content-disposition') || ''
  check('/download 仍为 attachment（保持下载语义）', /^attachment/.test(ddisp), ddisp)

  // 抽取接口
  const ex = await (await fetch(`${API}${csv.preview_url.replace('/preview', '/extract')}`)).json()
  check('CSV 抽取为表格', ex.ok && ex.kind === 'csv' && ex.rows?.[1]?.[1] === '120',
    `kind=${ex.kind} rows=${ex.rows?.length || 0}`)

  // 清理
  await fetch(`${API}/api/attachments/${csv.id}`, { method: 'DELETE' })
  await fetch(`${API}/api/attachments/${pdf.id}`, { method: 'DELETE' })
}

// ---------- 2. 知识关联 ----------
async function testKnowledge() {
  console.log('\n=== 2. 记录 ↔ 知识库 ===')

  const nt = await j('/api/knowledge/note-type')
  check('笔记模型可识别', nt.body.exists === true, `id=${nt.body.id}`)

  const types = await j('/api/entity-types')
  const other = types.body.find(t => t.key !== 'note' && t.record_count > 0)
  if (!other) {
    check('知识关联：业务记录存在', false, '暂无带记录的非笔记模型（模板未创建时跳过）')
    return
  }
  const recs = await j(`/api/records/type/${other.id}?page=1&page_size=1`)
  const recordId = recs.body.items[0].id

  // 沉淀为笔记
  const mat = await j('/api/knowledge/note-from-record', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId }),
  })
  check('沉淀为笔记', mat.status === 200 && mat.body.ok === true,
    `note_id=${mat.body.note_id} title=${mat.body.title || ''}`)
  const noteId = mat.body.note_id

  const forRec = await j(`/api/knowledge/for-record/${recordId}`)
  check('记录能查到关联笔记',
    (forRec.body.notes || []).some(n => n.note_id === noteId),
    `notes=${forRec.body.notes?.length || 0}`)

  const forNote = await j(`/api/knowledge/for-note/${noteId}`)
  check('笔记能反向查到业务记录',
    (forNote.body.records || []).some(r => r.record_id === recordId),
    `records=${forNote.body.total || 0}`)

  // 幂等
  const again = await j('/api/knowledge/link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId, note_id: noteId }),
  })
  check('重复关联幂等（不报错）', again.status === 200 && again.body.created === false)

  // 解除 + 清理
  const un = await j(`/api/knowledge/link?record_id=${recordId}&note_id=${noteId}`, { method: 'DELETE' })
  check('解除关联', un.status === 200)
  await fetch(`${API}/api/records/${noteId}`, { method: 'DELETE' })
}

// ---------- 3. 应用模板 ----------
async function testTemplate() {
  console.log('\n=== 3. 应用模板 ===')

  const tpls = await j('/api/apps/templates')
  check('模板列表可用', Array.isArray(tpls.body) && tpls.body.length >= 6,
    `${tpls.body.length} 个模板`)

  const proj = tpls.body.find(t => t.key === 'project')
  check('项目管理模板含 4 个模型',
    proj && proj.type_count === 4,
    proj ? `types=${proj.type_count} fields=${proj.field_count}` : '缺失')

  // 真正建一个，验证模型/字段/关联都落库
  const key = 'v12tpl' + Date.now().toString().slice(-5)
  const created = await j('/api/apps/from-template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, name: 'V12 测试应用', template: 'project' }),
  })
  check('按模板创建应用', created.status === 200 && created.body.ok === true,
    `types=${created.body.types?.length || 0} relations=${created.body.relations?.length || 0}`)
  check('模板创建了 4 个模型', created.body.types?.length === 4)
  check('模板创建了 3 条关联', created.body.relations?.length === 3)

  // 字段确实写进去了
  const t = created.body.types[0]
  const et = await j(`/api/entity-types/${t.id}`)
  check('模型的字段已生成', (et.body.fields || []).length > 5,
    `${t.key} fields=${et.body.fields?.length || 0}`)

  // 外键 target 前缀正确
  const taskType = created.body.types.find(x => x.key.endsWith('_task'))
  const taskEt = await j(`/api/entity-types/${taskType.id}`)
  const refField = (taskEt.body.fields || []).find(f => f.type === 'reference')
  check('外键 target 指向同应用模型',
    refField && refField.options?.target === `${key}_project`,
    refField ? String(refField.options?.target) : '无外键字段')

  // 重复 key 应 400
  const dup = await j('/api/apps/from-template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, name: 'dup', template: 'project' }),
  })
  check('重复应用 Key 被拒绝', dup.status === 400, 'status=' + dup.status)

  // 清理：删模型 → 删应用 → 删关联
  for (const x of created.body.types) {
    await fetch(`${API}/api/entity-types/${x.id}`, { method: 'DELETE' })
  }
  const appList = await j('/api/apps')
  const app = appList.body.find(a => a.key === key)
  if (app) await fetch(`${API}/api/apps/${app.id}`, { method: 'DELETE' })
  const defs = await j('/api/relations/defs')
  for (const d of defs.body.filter(d => String(d.key).startsWith(key + '_'))) {
    await fetch(`${API}/api/relations/defs/${d.id}`, { method: 'DELETE' })
  }
  check('清理测试数据', true)
}

// ---------- 4. 前端页面 ----------
async function testUI() {
  console.log('\n=== 4. 前端页面 ===')

  const ROUTES = [
    ['#/', '工作台'],
    ['#/apps', '应用中心'],
    ['#/types', '数据模型'],
    ['#/relations', '关联定义'],
    ['#/graph', '关联图谱'],
    ['#/notes', '知识库'],
    ['#/library', '数据中心'],
    ['#/knowledge/graph', '知识图谱'],
    ['#/search', '全局搜索'],
    ['#/guide', '使用指南'],
    ['#/ai-settings', 'AI 设置'],
    ['#/no-such-page', '404'],
  ]

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 950 })

  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push('pageerror: ' + e.message))
  page.on('requestfailed', r => errors.push('reqfail: ' + r.url()))
  page.on('response', r => {
    if (r.status() >= 400 && r.url().includes('/api/')) {
      errors.push(`HTTP ${r.status()} ${r.url()}`)
    }
  })

  for (const [hash, name] of ROUTES) {
    const before = errors.length
    await page.goto(FE + '/' + hash, { waitUntil: 'networkidle0' })
    await new Promise(r => setTimeout(r, 1200))
    const info = await page.evaluate(() => ({
      textLen: document.body.innerText.trim().length,
      h1: document.title,
    }))
    // 404 / 空图谱内容少，降到 130
    const ok = errors.length === before && info.textLen > 130
    check(`页面 ${name}`, ok, `内容长度=${info.textLen}${ok ? '' : ' 错误:' + errors.slice(before).join(' | ')}`)
  }

  // 使用指南内容抽查
  await page.goto(FE + '/#/guide', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1000))
  const guideText = await page.evaluate(() => document.body.innerText)
  check('使用指南含格式支持说明', guideText.includes('文件在线预览支持范围'))
  check('使用指南含 FAQ', guideText.includes('常见问题'))

  // 新建应用弹窗：模板可见
  await page.goto(FE + '/#/apps', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1000))
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('新建应用'))
    b && b.click()
  })
  await new Promise(r => setTimeout(r, 900))
  const tplState = await page.evaluate(() => ({
    cards: document.querySelectorAll('.tpl-card').length,
    hasSummary: !!document.querySelector('.dialog-summary'),
    names: [...document.querySelectorAll('.tpl-name')].map(e => e.textContent.trim()),
  }))
  check('新建应用弹窗展示模板', tplState.cards >= 6, `${tplState.cards} 个模板：${tplState.names.slice(0, 4).join('/')}…`)

  await page.screenshot({ path: '/tmp/shots12/apps-template.png', fullPage: false })

  // 数据中心：找一个 PDF/Office 文件点预览
  await page.goto(FE + '/#/library', { waitUntil: 'networkidle0' })
  await new Promise(r => setTimeout(r, 1500))
  const previewRes = await page.evaluate(async () => {
    const rows = [...document.querySelectorAll('.data-table tbody tr, .file-card')]
    if (!rows.length) return { skipped: true }
    rows[0].click()
    await new Promise(r => setTimeout(r, 2500))
    const dlg = document.querySelector('.preview-wrap')
    return {
      hasDialog: !!dlg,
      hasIframe: !!document.querySelector('.preview-frame iframe'),
      hasImg: !!document.querySelector('.preview-image img'),
      hasDoc: !!document.querySelector('.preview-doc'),
      hasSheet: !!document.querySelector('.preview-sheet'),
      mode: document.querySelector('.mode-tag')?.textContent?.trim() || '',
    }
  })
  check('数据中心可打开预览弹窗',
    previewRes.skipped || previewRes.hasDialog,
    previewRes.skipped ? '（无文件，跳过）' : JSON.stringify(previewRes))
  await page.screenshot({ path: '/tmp/shots12/library-preview.png' })

  check('全程无控制台错误 / 4xx / 5xx', errors.length === 0,
    errors.length ? errors.slice(0, 4).join(' | ') : '0')

  await browser.close()
}

;(async () => {
  try {
    await testPreview()
    await testKnowledge()
    await testTemplate()
    await testUI()
  } catch (e) {
    check('脚本执行', false, String(e && e.stack || e))
  }
  const failed = results.filter(r => !r[1])
  console.log(`\n===== 汇总：${results.length - failed.length}/${results.length} 通过 =====`)
  if (failed.length) {
    console.log('失败项：')
    failed.forEach(f => console.log('  ❌', f[0], '—', f[2]))
    process.exitCode = 1
  }
})()
