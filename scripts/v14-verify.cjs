/**
 * v14 回归验证：文件存进数据库（BLOB）+ FTS5 + sqlite-vec 混合检索
 *
 * 校验核心命题：文件原文真的进了 kb.db，且不依赖磁盘文件；
 * 数据中心不再伪造笔记；索引与检索链路可用；旧 URL 不失效。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const S = require('./lib/session.cjs')

const API = 'http://localhost:8001'
const FE = 'http://127.0.0.1:8082'

const results = []
// 记录本脚本自己创建的文件，跑完清掉 —— 否则每次运行都会给库里堆数据，
// 还会让「重复内容识别」这类断言命中上一次运行的残留而误报。
const created = []
const RUN = Date.now().toString(36)

function check(name, ok, detail = '') {
  results.push([name, ok, detail])
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  — ' + detail : ''}`)
}

async function j(path, opts = {}) {
  if (!S.cookies()) await S.login()
  const headers = { ...(opts.headers || {}), Cookie: S.cookies() }
  const r = await fetch(API + path, { ...opts, headers })
  const ct = r.headers.get('content-type') || ''
  const body = ct.includes('json') ? await r.json() : await r.text()
  return { status: r.status, body, headers: r.headers, raw: r }
}

async function uploadDoc(name, content, type) {
  const form = new FormData()
  form.append('file', new Blob([content], { type }), name)
  const r = await fetch(API + '/api/documents/upload', { method: 'POST', headers: { Cookie: S.cookies() }, body: form })
  const body = await r.json()
  if (body && body.id) created.push(body.id)
  return { status: r.status, body }
}

// ---------- 1. 上传即入库 ----------
async function testUpload() {
  console.log('\n=== 1. 上传即入库（不依赖任何记录）===')

  const text = `采购合同 深圳某某科技有限公司

第一条 甲方深圳某某科技有限公司向乙方采购服务器设备一批，合同金额 120 万元。
第二条 付款条件：合同签订后 30 日内支付 40% 预付款，验收合格后支付剩余 60%。
第三条 交付地点：深圳市南山区科技园。违约金按日万分之五计算。
`
  const up = await uploadDoc('v14-采购合同.txt', text, 'text/plain')
  check('上传返回 200', up.status === 200, `status=${up.status}`)
  const doc = up.body
  check('返回文档 id', !!doc.id, `id=${doc.id}`)
  check('不与记录绑定（links 为空）', (doc.links || []).length === 0,
    `links=${(doc.links || []).length}`)
  check('正文抽取成功', doc.extract_status === 'ok', doc.extract_status)
  check('标出抽取字数', (doc.extract_chars || 0) > 50, `${doc.extract_chars} 字`)

  return doc
}

// ---------- 2. 数据中心不再伪造笔记 ----------
async function testNoFakeNote() {
  console.log('\n=== 2. 数据中心不再伪造笔记 ===')

  const noteType = await j('/api/entity-types/by-key/note')
  const before = await j(`/api/records/type/${noteType.body.id}?page=1&page_size=1`)
  const n1 = before.body.total || 0

  await uploadDoc('v14-不产生笔记.txt', '验证上传文件不会再创建伪笔记容器', 'text/plain')

  const after = await j(`/api/records/type/${noteType.body.id}?page=1&page_size=1`)
  const n2 = after.body.total || 0
  check('上传文件后笔记数量不变', n1 === n2, `上传前 ${n1} → 上传后 ${n2}`)

  // 库里不应再有 _auto 伪笔记
  const all = await j(`/api/records/type/${noteType.body.id}?page=1&page_size=500`)
  const fakes = (all.body.items || []).filter(r =>
    JSON.stringify(r.data?.tags || []).includes('_auto'))
  check('知识库中已无 _auto 伪笔记', fakes.length === 0, `发现 ${fakes.length} 条`)
}

// ---------- 3. 文件真的在数据库里 ----------
async function testBlobInDb(doc) {
  console.log('\n=== 3. 文件原文在数据库中 ===')

  const raw = await j(`/api/documents/${doc.id}/raw`)
  check('预览接口可用', raw.status === 200, `status=${raw.status}`)
  check('预览返回 inline（可内联渲染）',
    (raw.headers.get('content-disposition') || '').startsWith('inline'),
    raw.headers.get('content-disposition') || '')
  const body = typeof raw.body === 'string' ? raw.body : ''
  check('预览内容与上传一致', body.includes('深圳某某科技有限公司'),
    `${body.length} 字节`)

  const dl = await j(`/api/documents/${doc.id}/download`)
  check('下载返回 attachment',
    (dl.headers.get('content-disposition') || '').startsWith('attachment'),
    dl.headers.get('content-disposition') || '')

  const st = await j('/api/documents/stats')
  check('统计显示存储方式为 sqlite-blob',
    st.body.storage === 'sqlite-blob', st.body.storage || '')
  check('统计总数 > 0', (st.body.total || 0) > 0, `total=${st.body.total}`)

  const detail = await j(`/api/documents/${doc.id}?with_text=true`)
  check('正文已落库（可用于 AI）',
    (detail.body.extracted_text || '').includes('违约金'), '')
  check('记录了 sha256', (detail.body.sha256 || '').length === 64,
    (detail.body.sha256 || '').slice(0, 12))
}

// ---------- 4. 内容抽取 ----------
async function testExtract() {
  console.log('\n=== 4. 内容抽取 ===')

  const csv = await uploadDoc('v14-台账.csv', '名称,数量,单价\n螺栓,120,0.5\n垫片,300,0.1\n', 'text/csv')
  const c = await j(`/api/documents/${csv.body.id}/content`)
  check('CSV 抽取为表格结构', c.body.ok && c.body.kind === 'csv',
    `${c.body.kind} rows=${(c.body.rows || []).length}`)

  const md = await uploadDoc('v14-说明.md', '# 标题\n\n这是 **Markdown** 正文，用于验证文本抽取。\n', 'text/markdown')
  const m = await j(`/api/documents/${md.body.id}/content`)
  check('Markdown 抽取为文本', m.body.ok && m.body.kind === 'text', m.body.kind || '')

  // PDF：内容为最小合法 PDF，验证不会崩（能抽出文字更好）
  const pdfMin = `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 60 >> stream
BT /F1 14 Tf 20 100 Td (Hello PDF Text) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
trailer << /Root 1 0 R >>
%%EOF`
  const pdf = await uploadDoc('v14-测试.pdf', pdfMin, 'application/pdf')
  const p = await j(`/api/documents/${pdf.body.id}/content`)
  check('PDF 可被解析（不报错）', p.status === 200, `kind=${p.body.kind}`)
  check('PDF 保留预览模式 = pdf', pdf.body.mode === 'pdf', pdf.body.mode || '')
  return pdf.body
}

// ---------- 5. 检索 ----------
async function testSearch(doc) {
  console.log('\n=== 5. 混合检索 ===')

  // 中文两字查询（FTS5 unicode61 逐字切分方案的关键验证点）
  const r1 = await j(`/api/documents/search?q=${encodeURIComponent('深圳')}&mode=keyword`)
  check('关键词检索命中中文两字查询', (r1.body.items || []).length > 0,
    `命中 ${(r1.body.items || []).length} 条`)

  const r2 = await j(`/api/documents/search?q=${encodeURIComponent('采购合同')}&mode=keyword`)
  const hit2 = (r2.body.items || []).some(i => i.id === doc.id)
  check('关键词检索命中「采购合同」', hit2, `命中 ${(r2.body.items || []).length} 条`)

  const r3 = await j(`/api/documents/search?q=${encodeURIComponent('违约金怎么算')}&mode=hybrid`)
  check('混合检索可返回结果', r3.status === 200,
    `fts=${r3.body.channels?.fts} vector=${r3.body.channels?.vector}`)
  check('混合检索返回命中通道标记',
    (r3.body.items || []).every(i => Array.isArray(i.matched_by)), '')

  // FTS5 语法安全：用户随便输入特殊字符不应 500
  for (const q of ['(', 'a"b', 'OR', 'NEAR(x)', '*']) {
    const rr = await j(`/api/documents/search?q=${encodeURIComponent(q)}&mode=keyword`)
    if (rr.status !== 200) {
      check(`特殊字符检索不报错：${q}`, false, `status=${rr.status}`)
      return
    }
  }
  check('特殊字符检索全部安全（不 500）', true, '含 ( " OR NEAR * ')
}

// ---------- 6. 去重与软删除 ----------
async function testDedupAndTrash() {
  console.log('\n=== 6. 去重提示 / 回收站 ===')

  // 内容带运行标识，避免命中上一次运行留下的同内容文件
  const body = `这段内容会被上传两次，用于验证 sha256 去重提示 (${RUN})`
  const a = await uploadDoc('v14-重复A.txt', body, 'text/plain')
  const b = await uploadDoc('v14-重复B.txt', body, 'text/plain')
  check('首次上传不算重复', a.body.duplicate_of == null, `dup=${a.body.duplicate_of}`)
  check('重复内容被识别（duplicate_of）',
    b.body.duplicate_of === a.body.id, `dup=${b.body.duplicate_of} 原=${a.body.id}`)
  check('重复内容不合并（两条独立记录）', a.body.id !== b.body.id, '')

  // 软删除
  const del = await j(`/api/documents/${b.body.id}`, { method: 'DELETE' })
  check('软删除返回 ok', del.status === 200 && del.body.ok, '')

  const gone = await j(`/api/documents/${b.body.id}`)
  check('软删除后详情 404', gone.status === 404, `status=${gone.status}`)

  const trash = await j('/api/documents?include_deleted=true&page_size=200')
  const inTrash = (trash.body.items || []).some(x => x.id === b.body.id && x.deleted_at)
  check('回收站能看到已删文件', inTrash, '')

  const st = await j('/api/documents/stats')
  check('统计里有回收站数量', (st.body.deleted || 0) >= 1, `deleted=${st.body.deleted}`)

  // 恢复
  const res = await j(`/api/documents/${b.body.id}/restore`, { method: 'POST' })
  check('恢复成功', res.status === 200 && res.body.id === b.body.id, '')
  const back = await j(`/api/documents/${b.body.id}`)
  check('恢复后详情可访问', back.status === 200, '')

  // 彻底删除
  await j(`/api/documents/${b.body.id}`, { method: 'DELETE' })
  const hard = await j(`/api/documents/${b.body.id}?hard=true`, { method: 'DELETE' })
  check('彻底删除成功', hard.status === 200, '')
  const nowhere = await j(`/api/documents/${b.body.id}`)
  check('彻底删除后不可访问', nowhere.status === 404, `status=${nowhere.status}`)
}

// ---------- 7. 兼容层：记录字段上传 + 旧 URL ----------
async function testCompat() {
  console.log('\n=== 7. 兼容层（记录字段 / 旧 URL）===')

  const noteType = await j('/api/entity-types/by-key/note')
  const list = await j(`/api/records/type/${noteType.body.id}?page=1&page_size=1`)
  let recordId = list.body.items?.[0]?.id
  if (!recordId) {
    const created = await j(`/api/records/type/${noteType.body.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: { title: 'v14 兼容测试', content: '临时' } }),
    })
    recordId = created.body.id
  }

  const form = new FormData()
  form.append('record_id', String(recordId))
  form.append('field_key', 'v14_field')
  form.append('file', new Blob(['字段上传测试内容 关联验证'], { type: 'text/plain' }), 'v14-字段.txt')
  const r = await fetch(API + '/api/attachments/upload', { method: 'POST', body: form })
  const att = await r.json()
  check('记录字段上传仍可用', r.status === 200 && !!att.id, `id=${att.id}`)
  check('返回新文档 URL', (att.url || '').includes('/api/documents/'), att.url || '')

  const oldPreview = await j(`/api/attachments/${att.id}/preview`)
  check('旧预览 URL 仍可用（历史数据不失效）', oldPreview.status === 200,
    `status=${oldPreview.status}`)

  const forRec = await j(`/api/attachments/for-record/${recordId}`)
  const found = (forRec.body || []).some(x => x.id === att.id)
  check('按记录查附件可用', found, `返回 ${(forRec.body || []).length} 条`)

  // 兼容测试的过程文件也清掉（它的 link 会随 document 级联删除）
  await j(`/api/documents/${att.id}?hard=true`, { method: 'DELETE' })

  return att
}

// ---------- 8. AI 打通 ----------
async function testAI(doc) {
  console.log('\n=== 8. AI 检索打通 ===')

  const emb = await j('/api/ai/embedding')
  check('向量化状态接口可用', emb.status === 200, `model=${emb.body.model}`)
  check('自动推导出 embedding 地址',
    (emb.body.url || '').endsWith('/embeddings'), emb.body.url || '')

  const ask = await j('/api/ai/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: '这份合同的付款条件是什么？',
      document_ids: [doc.id],
      auto_retrieve: false,
    }),
  })
  check('AI 问答接口可用', ask.status === 200, `status=${ask.status}`)
  check('返回上下文条数', (ask.body.context_count || 0) > 0,
    `context_count=${ask.body.context_count}`)
  check('返回来源列表（可溯源）',
    Array.isArray(ask.body.sources) && ask.body.sources.length > 0,
    `sources=${(ask.body.sources || []).length}`)

  // 上传的正文真的进了上下文
  const r2 = await j('/api/ai/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '深圳某某科技有限公司', auto_retrieve: true }),
  })
  check('自动检索也能定位到文件', (r2.body.sources || []).some(s => s.type === 'document'),
    `sources=${JSON.stringify((r2.body.sources || []).map(s => s.type))}`)
}

// ---------- 9. 前端渲染 ----------
async function testFrontend() {
  console.log('\n=== 9. 前端页面 ===')

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000 })

  const errors = []
  const bad = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))
  page.on('response', r => {
    const u = r.url()
    if (r.status() >= 400 && u.includes('/api/')) bad.push(`${r.status()} ${u}`)
  })

  for (const [path, name] of [['/', '工作台'], ['/library', '数据中心'],
                              ['/ai-settings', 'AI 设置'], ['/notes', '知识库']]) {
    await page.goto(FE + '#' + path, { waitUntil: 'networkidle2' })
    await new Promise(r => setTimeout(r, 1200))
    const text = await page.evaluate(() => document.body.innerText)
    check(`页面可渲染：${name}`, text.length > 80, `${text.length} 字符`)
  }

  await page.goto(FE + '#/library', { waitUntil: 'networkidle2' })
  await new Promise(r => setTimeout(r, 1500))
  const hasTrash = await page.evaluate(() =>
    document.body.innerText.includes('回收站'))
  check('数据中心有回收站入口', hasTrash, '')
  const hasIndexed = await page.evaluate(() =>
    document.body.innerText.includes('已建向量索引'))
  check('数据中心展示向量索引统计', hasIndexed, '')

  check('前端无控制台错误', errors.length === 0, errors.slice(0, 3).join(' | '))
  check('无 4xx/5xx 接口调用', bad.length === 0, bad.slice(0, 3).join(' | '))

  await browser.close()
}

async function cleanup() {
  let n = 0
  for (const id of created) {
    const r = await fetch(`${API}/api/documents/${id}?hard=true`, { method: 'DELETE' })
    if (r.ok) n++
  }
  console.log(`\n（清理：移除本次创建的 ${n}/${created.length} 个测试文件）`)
}

async function main() {
  await S.login()
  const doc = await testUpload()
  await testNoFakeNote()
  await testBlobInDb(doc)
  await testExtract()
  await testSearch(doc)
  await testDedupAndTrash()
  await testCompat()
  await testAI(doc)
  await testFrontend()
  await cleanup()

  const pass = results.filter(r => r[1]).length
  console.log(`\n${'='.repeat(56)}`)
  console.log(`结果：${pass}/${results.length} 通过`)
  const failed = results.filter(r => !r[1])
  if (failed.length) {
    console.log('\n未通过：')
    failed.forEach(([n, , d]) => console.log(`  ❌ ${n}  ${d}`))
    process.exit(1)
  }
}

main().catch(e => { console.error(e); process.exit(1) })
