/**
 * v16 回归验证：Jevko → JSON，以及「用 JSON 回写字段 / 新建模型」
 *
 * 校验核心命题：
 * 1. 自定义 Jevko 语法已经被标准 JSON 全面取代（接口 / 组件 / 文案 / 附件元数据）
 * 2. 用户随手写的 JSON（带注释、尾逗号、中文别名、中文类型名）也能建出正确的模型
 * 3. JSON 能落库（新建）、能回写（覆盖 / target_id），并且会挡住误操作（key 冲突）
 * 4. 前端 JSON 面板：实时预览 → 校验 → 应用到表单 闭环可用
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const S = require('./lib/session.cjs')

const API = 'http://localhost:8001'
const FE = 'http://127.0.0.1:8082'

const results = []
const RUN = Date.now().toString(36)
const createdTypes = []      // 本次创建的模型，跑完删掉
const createdNotes = []      // 本次创建的笔记

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
  return { status: r.status, body }
}

async function post(path, payload) {
  return j(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

async function del(path) {
  return j(path, { method: 'DELETE' })
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }

/**
 * 轮询等一个前端结果落地。
 * 前端请求是异步的，固定 sleep 只能碰运气 —— 之前「校验」用例就是因此误判。
 */
async function waitFor(page, fn, ms = 8000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    const v = await page.evaluate(fn)
    if (v) return v
    await sleep(150)
  }
  return null
}

// ============================================================ 1
async function testJsonApi() {
  console.log('\n=== 1. JSON 工具接口（取代 /api/jevko/*）===')

  const legacy = await post('/api/jevko/parse', { text: 'a[b]' })
  check('旧 /api/jevko/parse 已下线', legacy.status === 404, `status=${legacy.status}`)

  const ok = await post('/api/json/parse', {
    text: '{"合同":{"金额":120,"生效":true,"附件":null,"标签":["a","b"]}}',
  })
  check('合法 JSON 解析成功', ok.status === 200 && ok.body.tree.length === 1,
    `status=${ok.status}`)
  const root = ok.body.tree[0]
  check('根节点标为 object', root.kind === 'object', root.kind)
  check('容器节点不携带 value（回归保护）',
    root.value === null && root.children[0].value === null,
    `root=${JSON.stringify(root.value)}`)
  check('统计包含节点数与深度',
    ok.body.summary.node_count >= 8 && ok.body.summary.max_depth >= 2,
    JSON.stringify(ok.body.summary))
  const leaf = root.children[0].children.find(c => c.key === '金额')
  check('叶子节点类型/取值正确', leaf && leaf.kind === 'number' && leaf.value === '120',
    leaf && `${leaf.kind}:${leaf.value}`)

  const bad = await post('/api/json/parse', { text: '{a:1,}' })
  check('非法 JSON 返回 400 且带行列',
    bad.status === 400 && /第 1 行第 2 列/.test(bad.body.detail || ''),
    (bad.body.detail || '').slice(0, 60))

  const long = await post('/api/json/parse', { text: JSON.stringify({ s: 'x'.repeat(500) }) })
  const snode = long.body.tree[0].children[0]
  check('超长字符串截断并保留原长度',
    snode.chars === 500 && snode.value.endsWith('…'), `chars=${snode.chars}`)

  const ser = await post('/api/json/serialize', { value: { a: [1, 2], 中文: 'ok' } })
  check('serialize 可往返', JSON.parse(ser.body.text).中文 === 'ok', ser.body.text)

  const tt = await post('/api/json/to-tree', { value: { x: 1 } })
  check('to-tree 支持直接传对象', tt.status === 200 && tt.body.tree[0].count === 1, '')
}

// ============================================================ 2
async function testModelValidate() {
  console.log('\n=== 2. 模型 JSON 校验（dry-run，不落库）===')

  const loose = `{
  // 注释 + 尾逗号 + 中文别名，都是手写 JSON 的高频写法
  "标识": "v16_loose_${RUN}",
  "模型名": "宽容解析演示",
  "fields": [
    {"key": "title", "名称": "标题", "类型": "字符串", "必填": true},
    {"key": "amount", "name": "金额", "type": "money"},
    {"key": "status", "name": "状态", "type": "单选", "choices": ["草稿", "生效"]},
    {"key": "owner", "name": "负责人", "type": "外键", "target": "customer"},
  ],
}`
  const r = await post('/api/entity-types/import', { text: loose, dry_run: true })
  check('宽松 JSON 通过校验', r.body.ok === true, JSON.stringify(r.body.errors || []))
  const types = (r.body.model?.fields || []).map(f => `${f.key}:${f.type}`)
  check('中文类型名被归一化',
    types.join(',') === 'title:text,amount:number,status:select,owner:reference', types.join(','))
  check('必填被识别', r.body.model.fields[0].required === true, '')
  check('choices 落到 options.choices',
    JSON.stringify(r.body.model.fields[2].options.choices) === '["草稿","生效"]', '')
  check('外键 target 保留', r.body.model.fields[3].options.target === 'customer', '')
  check('clean JSON 不产生多余警告', (r.body.warnings || []).length === 0,
    JSON.stringify(r.body.warnings))

  const noKey = await post('/api/entity-types/import', {
    text: '{"name":"没有标识","fields":[{"key":"a"}]}', dry_run: true,
  })
  check('缺 key 被拦下', noKey.body.ok === false && /缺少模型标识/.test(noKey.body.errors[0]),
    noKey.body.errors[0])

  const noField = await post('/api/entity-types/import', {
    text: '{"key":"x_no_field","fields":[]}', dry_run: true,
  })
  check('没有字段被拦下', noField.body.ok === false, noField.body.errors[0])

  const broken = await post('/api/entity-types/import', { text: '{bad}', dry_run: true })
  check('非法 JSON 报行列', broken.body.ok === false && /第 1 行/.test(broken.body.errors[0]),
    broken.body.errors[0])

  const sloppy = await post('/api/entity-types/import', {
    text: `{"key":"v16_sloppy_${RUN}","fields":[{"key":"a","type":"单选"},{"name":"中文名"},{"key":"a","type":"number"}]}`,
    dry_run: true,
  })
  const w = (sloppy.body.warnings || []).join(' / ')
  check('缺选项 / 缺英文 key / key 重复 都有警告',
    /没有选项/.test(w) && /没有英文 key/.test(w) && /重复/.test(w),
    w.slice(0, 120))

  const objForm = await post('/api/entity-types/import', {
    model: {
      key: `v16_obj_${RUN}`, name: '对象直传',
      fields: [{ key: 'a', name: 'A' }, { key: 'b', name: 'B', type: '数字' }],
    },
    dry_run: true,
  })
  check('model 字段可直接传对象（前端也能用）',
    objForm.body.ok === true && objForm.body.model.fields[1].type === 'number',
    JSON.stringify(objForm.body.errors || []))

  const wrapped = await post('/api/entity-types/import', {
    model: { model: { key: `v16_wrap_${RUN}`, name: '包装写法' }, fields: [{ key: 'n', name: '名称' }] },
    dry_run: true,
  })
  check('{"model":{...},"fields":[...]} 包装写法可用',
    wrapped.body.ok === true && wrapped.body.model.fields.length === 1,
    JSON.stringify(wrapped.body.errors || []))
}

// ============================================================ 3
async function testCreateAndExport() {
  console.log('\n=== 3. 用 JSON 新建模型 + 导出回环 ===')

  const KEY = `v16_model_${RUN}`
  const body = JSON.stringify({
    key: KEY,
    name: 'JSON 建模演示',
    icon: 'Document',
    description: 'v16 验证用模型',
    fields: [
      { key: 'title', name: '标题', type: 'text', required: true },
      { key: 'amount', name: '金额', type: 'number' },
      { key: 'status', name: '状态', type: 'select', options: { choices: ['新建', '完成'] } },
      { key: 'customer', name: '客户', type: 'reference', options: { target: 'customer' } },
      { key: 'files', name: '附件', type: 'file' },
    ],
  })

  const created = await post('/api/entity-types/import', { text: body, dry_run: false })
  check('JSON 建模成功', created.body.ok === true && created.body.action === 'created',
    `action=${created.body.action}`)
  const id = created.body.entity_type?.id
  createdTypes.push(id)
  check('返回新建模型 id', !!id, `id=${id}`)

  const list = await j('/api/entity-types')
  check('新模型出现在模型列表',
    list.body.some(t => t.key === KEY && t.field_count === 5), KEY)

  const detail = await j(`/api/entity-types/${id}`)
  check('字段按 JSON 落库',
    detail.body.fields.map(f => `${f.key}:${f.type}`).join(',')
      === 'title:text,amount:number,status:select,customer:reference,files:file',
    detail.body.fields.map(f => f.key).join(','))
  check('select 选项落库',
    JSON.stringify(detail.body.fields[2].options.choices) === '["新建","完成"]', '')
  check('reference 目标落库',
    detail.body.fields[3].options.target === 'customer', '')

  const exported = await j(`/api/entity-types/${id}/export`)
  check('导出为 JSON 文本', typeof exported.body.json === 'string'
    && exported.body.json.includes(KEY), '')
  const parsed = JSON.parse(exported.body.json)
  check('导出的 JSON 是标准 JSON 且字段齐全',
    parsed.fields.length === 5 && parsed.key === KEY, `fields=${parsed.fields.length}`)

  // 导出 → 再导入（改个名字）应当能原样重建，验证回环不丢信息
  parsed.key = `${KEY}_copy`
  parsed.name = 'JSON 建模演示（副本）'
  const copy = await post('/api/entity-types/import', { text: JSON.stringify(parsed), dry_run: false })
  if (copy.body.ok) createdTypes.push(copy.body.entity_type.id)
  check('导出→导入 无损回环', copy.body.ok === true
    && copy.body.entity_type.fields?.length === 5,
    `fields=${copy.body.entity_type?.fields?.length}`)

  return { id, key: KEY, body }
}

// ============================================================ 4
async function testWriteBack(ctx) {
  console.log('\n=== 4. 覆盖 / 回写 / 冲突保护 ===')

  const dup = await post('/api/entity-types/import', { text: ctx.body, dry_run: false })
  check('同 key 未勾选覆盖会被拦下',
    dup.body.ok === false && /已存在标识/.test(dup.body.errors[0]),
    dup.body.errors[0].slice(0, 50))

  const overwrite = await post('/api/entity-types/import', {
    text: JSON.stringify({
      key: ctx.key, name: 'JSON 建模演示 v2', icon: 'Document',
      fields: [
        { key: 'title', name: '标题', type: 'text', required: true },
        { key: 'score', name: '评分', type: 'number' },
      ],
    }),
    dry_run: false, overwrite: true,
  })
  check('勾选覆盖 → 走更新', overwrite.body.ok === true && overwrite.body.action === 'updated',
    `action=${overwrite.body.action}`)
  const after = await j(`/api/entity-types/${ctx.id}`)
  check('覆盖后字段被替换', after.body.fields.length === 2
    && after.body.name === 'JSON 建模演示 v2',
    `${after.body.name} / ${after.body.fields.map(f => f.key).join(',')}`)

  // target_id：直接回写指定模型的字段（编辑器里的「JSON 回写」走这条路）
  const back = await post('/api/entity-types/import', {
    target_id: ctx.id, dry_run: false,
    text: JSON.stringify({
      key: ctx.key, name: 'JSON 建模演示 v3',
      fields: [
        { key: 'title', name: '标题', type: 'text' },
        { key: 'due', name: '截止日期', type: '日期' },
        { key: 'tags', name: '标签', type: '标签', choices: '重点,长期' },
      ],
    }),
  })
  check('target_id 回写成功', back.body.ok === true && back.body.action === 'updated',
    `action=${back.body.action}`)
  const after2 = await j(`/api/entity-types/${ctx.id}`)
  check('回写字段与类型都生效',
    after2.body.fields.map(f => `${f.key}:${f.type}`).join(',')
      === 'title:text,due:date,tags:multiselect',
    after2.body.fields.map(f => `${f.key}:${f.type}`).join(','))
  check('逗号字符串形式的 options 被拆成数组',
    JSON.stringify(after2.body.fields[2].options.choices) === '["重点","长期"]',
    JSON.stringify(after2.body.fields[2].options.choices))

  const conflict = await post('/api/entity-types/import', {
    target_id: ctx.id, dry_run: false,
    text: JSON.stringify({ key: 'project', name: 'x', fields: [{ key: 'a' }] }),
  })
  check('回写时改成他人 key 被挡住',
    conflict.body.ok === false && /占用/.test(conflict.body.errors[0]),
    conflict.body.errors[0])

  const missing = await post('/api/entity-types/import', {
    target_id: 999999, dry_run: true,
    text: JSON.stringify({ key: 'whatever', name: 'x', fields: [{ key: 'a' }] }),
  })
  check('回写不存在的模型给出明确报错',
    missing.body.ok === false && /不存在/.test(missing.body.errors[0]),
    missing.body.errors[0])
}

// ============================================================ 5
async function testAttachmentMeta() {
  console.log('\n=== 5. 附件元数据改为 JSON ===')

  const all = await j('/api/attachments/all?page=1&page_size=20')
  const items = all.body.items || []
  check('附件列表可访问', all.status === 200 && items.length > 0, `${items.length} 条`)

  const withMeta = items.filter(x => x.json_text && (x.json_tree || []).length)
  check('每条附件都带 JSON 元数据', withMeta.length === items.length,
    `${withMeta.length}/${items.length}`)

  const one = withMeta[0]
  let parsed = null
  try { parsed = JSON.parse(one.json_text) } catch (e) { /* 下面断言会报 */ }
  check('json_text 是合法 JSON', !!parsed, (one.json_text || '').slice(0, 40))
  check('元数据含文件名/存储方式等字段',
    parsed && parsed.attachment && parsed.attachment.filename === one.filename
      && parsed.attachment.storage === 'sqlite-blob',
    parsed ? Object.keys(parsed.attachment).join(',') : '')

  const flat = []
  const walk = (n) => { flat.push(n); (n.children || []).forEach(walk) }
  one.json_tree.forEach(walk)
  check('json_tree 可遍历且含 filename 叶子',
    flat.some(n => n.key === 'filename' && n.kind === 'string'), `${flat.length} 个节点`)
  check('出参里已无 jevko 字段',
    !('jevko_text' in one) && !('jevko_tree' in one),
    Object.keys(one).filter(k => /jevko/i.test(k)).join(','))

  // 前端展开某个文件时走的按需接口：形状必须与 /attachments/all 内联的一致
  const single = await j(`/api/documents/${one.id}/meta`)
  check('单文件元数据接口可用',
    single.status === 200 && (single.body.json_tree || []).length > 0,
    `status=${single.status}`)
  let singleParsed = null
  try { singleParsed = JSON.parse(single.body.json_text) } catch (e) { /* 下面断言会报 */ }
  check('两个入口元数据完全一致',
    single.body.json_text === one.json_text,
    single.body.json_text === one.json_text ? '' : '形状不一致')
  check('元数据带关联记录与上传时间',
    !!singleParsed && Array.isArray(singleParsed.attachment.links)
      && !!singleParsed.attachment.uploaded_at,
    singleParsed ? Object.keys(singleParsed.attachment).join(',') : '')
}

// ============================================================ 6
async function testFrontendEditor(page, contractId) {
  console.log('\n=== 6. 前端：JSON 编辑面板 ===')

  await page.goto(FE + '#/types/new?mode=json', { waitUntil: 'networkidle2' })
  await sleep(1600)
  check('JSON 面板存在', await page.$('.json-editor') !== null, '')

  const txt = await page.$eval('.je-input textarea', el => el.value)
  check('预填了可用的示例 JSON', txt.includes('"fields"') && txt.includes('"key"'),
    `${txt.split('\n').length} 行`)

  const nodes = await page.$$eval('.jn-node', els => els.length)
  check('实时预览渲染出 JSON 树', nodes > 5, `${nodes} 个节点`)
  const hasColorClass = await page.evaluate(() =>
    !!document.querySelector('.k-string .jn-val, .k-number .jn-val'))
  check('值按类型着色', hasColorClass, '')

  // 校验（服务端 dry-run）
  // 先把示例的 key 换成运行时唯一值：示例里是 contract，而库里已经有同名模型，
  // 未勾选覆盖时被冲突保护拦下是**正确行为**，不该在这条用例里当成失败。
  const uiKey = `v16_ui_${RUN}`
  await page.evaluate((k) => {
    const el = document.querySelector('.je-input textarea')
    el.value = el.value.replace(/"key"\s*:\s*"[^"]+"/, `"key": "${k}"`)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  }, uiKey)
  await sleep(300)

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('校验'))
    b && b.click()
  })
  const okBlock = await waitFor(page, () => {
    const el = document.querySelector('.je-check .je-block')
    return el ? el.innerText : ''
  })
  check('校验通过并展示识别到的字段数',
    /校验通过/.test(okBlock || ''), (okBlock || '').replace(/\n/g, ' '))

  // 反例：key 撞上库里已有模型时，校验必须给出可操作的提示而不是静默通过
  await page.evaluate(() => {
    const el = document.querySelector('.je-input textarea')
    el.value = el.value.replace(/"key"\s*:\s*"[^"]+"/, '"key": "contract"')
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await sleep(200)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('校验'))
    b && b.click()
  })
  const conflictBlock = await waitFor(page, () => {
    const el = document.querySelector('.je-check .je-block.is-error')
    return el ? el.innerText : ''
  })
  check('key 撞库时校验拦下并给出提示',
    /已存在标识/.test(conflictBlock || ''), (conflictBlock || '').replace(/\n/g, ' ').slice(0, 60))

  // 应用到表单
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('应用到表单'))
    b && b.click()
  })
  await sleep(900)
  const rows = await page.$$eval('.field-row', els => els.length)
  check('应用到表单 → 字段真的填进可视化编辑器', rows === 11,
    `${rows - 1} 个字段（示例 10 个）`)
  const firstKey = await page.$eval('.field-row:not(.header) input', el => el.value).catch(() => '')
  check('字段 key 与 JSON 一致', firstKey === 'title', firstKey)

  const state = await page.$eval('.json-state', el => el.innerText).catch(() => '')
  check('状态标记回到「已与表单同步」', state.includes('同步'), state)

  // 编辑已有模型：JSON 应当反映当前字段
  await page.goto(FE + `#/types/${contractId}/edit`, { waitUntil: 'networkidle2' })
  await sleep(1800)
  const editTxt = await page.$eval('.je-input textarea', el => el.value)
  check('编辑页 JSON 反映现有模型', editTxt.includes('"contract"') && editTxt.includes('"fields"'),
    editTxt.split('\n')[0])
  const editNodes = await page.$$eval('.jn-node', els => els.length)
  check('编辑页预览可用', editNodes > 10, `${editNodes} 个节点`)

  // 改坏 JSON → 应用应报错而不是把表单清空
  await page.evaluate(() => {
    const el = document.querySelector('.je-input textarea')
    el.value = '{"key": "contract", "name": "坏的"'
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await sleep(400)
  const errState = await page.$eval('.json-state', el => el.innerText).catch(() => '')
  check('破坏 JSON 后状态提示语法错误', errState.includes('错误'), errState)
  const errView = await page.evaluate(() =>
    (document.querySelector('.jv-msg.is-error') || {}).innerText || '')
  check('预览区直接给出定位信息', /行/.test(errView), errView.slice(0, 60))

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('从表单生成'))
    b && b.click()
  })
  await sleep(600)
  const restored = await page.$eval('.je-input textarea', el => el.value)
  check('「从表单生成」可一键还原', restored.includes('"fields"'), '')
}

// ============================================================ 7
async function testFrontendLibrary(page) {
  console.log('\n=== 7. 前端：数据中心的 JSON 元数据与试验场 ===')

  await page.goto(FE + '#/library', { waitUntil: 'networkidle2' })
  await sleep(1800)

  const bodyText = await page.evaluate(() => document.body.innerText)
  check('已无 Jevko 字样', !/jevko/i.test(bodyText), '')

  const tabs = await page.$$eval('.el-tabs__item', els => els.map(x => x.innerText.trim()))
  check('标签页改名 JSON 元数据', tabs.some(t => t.includes('JSON 元数据')), tabs.join(' | '))

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('JSON 试验场'))
    b && b.click()
  })
  await sleep(1200)
  const pgNodes = await page.$$eval('.playground .jn-node', els => els.length)
  check('JSON 试验场：双栏并实时渲染', pgNodes > 3, `${pgNodes} 个节点`)

  // 在试验场里粘贴一段坏 JSON，应给出行列错误
  await page.evaluate(() => {
    const el = document.querySelector('.playground textarea')
    el.value = '{"a": }'
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await sleep(500)
  const pgErr = await page.evaluate(() =>
    (document.querySelector('.playground .jv-msg.is-error') || {}).innerText || '')
  check('试验场对坏 JSON 给出定位', /行/.test(pgErr), pgErr.slice(0, 50))

  await page.keyboard.press('Escape')
  await sleep(700)

  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.el-tabs__item')]
      .find(x => x.innerText.includes('JSON 元数据'))
    t && t.click()
  })
  await sleep(900)
  const heads = await page.$$eval('.json-head', els => els.length)
  check('JSON 元数据页列出附件', heads > 0, `${heads} 条`)
  await page.evaluate(() => {
    const h = document.querySelector('.json-head')
    h && h.click()
  })
  const metaText = await waitFor(page, () => {
    const el = document.querySelector('.json-body')
    const t = el ? el.innerText : ''
    return t.includes('filename') ? t : ''
  })
  check('展开后能看到 JSON 树内容',
    !!metaText && metaText.includes('filename') && metaText.includes('attachment'),
    (metaText || '').replace(/\s+/g, ' ').slice(0, 60))

  const badge = await waitFor(page, () => {
    const el = document.querySelector('.json-head .badge')
    const t = el ? el.innerText : ''
    return /节点/.test(t) ? t : ''
  })
  check('展开后列表显示真实节点数', !!badge, badge || '（仍是占位文案）')
}

// ============================================================ 8
async function testFrontendNote(page) {
  console.log('\n=== 8. 前端：笔记详情的 JSON 视图 ===')

  const noteType = await j('/api/entity-types/by-key/note')
  if (!noteType.body.id) {
    check('笔记模型存在', false, '找不到 note 模型')
    return
  }
  let recs = await j(`/api/records/type/${noteType.body.id}?page=1&page_size=1`)
  let noteId = recs.body.items?.[0]?.id
  if (!noteId) {
    const c = await post(`/api/records/type/${noteType.body.id}`, { data: { title: 'v16 临时笔记', content: '临时' } })
    noteId = c.body.id
    createdNotes.push(noteId)
  }

  await page.goto(FE + `#/notes/${noteId}`, { waitUntil: 'networkidle2' })
  await sleep(1800)
  const tabs = await page.$$eval('.el-tabs__item', els => els.map(x => x.innerText.trim()))
  check('标签页里有 JSON', tabs.some(t => t.trim() === 'JSON'), tabs.join(' | '))

  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.el-tabs__item')].find(x => x.innerText.trim() === 'JSON')
    t && t.click()
  })
  await sleep(800)
  const recText = await page.evaluate(() =>
    (document.querySelector('.json-viewer') || {}).innerText || '')
  check('默认展示记录数据（永远是合法 JSON）',
    recText.includes('title') && recText.includes('节点'), recText.replace(/\s+/g, ' ').slice(0, 60))

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-radio-button__inner')]
      .find(x => x.innerText.includes('正文'))
    b && b.click()
  })
  await sleep(700)
  const hasViewer = await page.$('.json-viewer') !== null
  const contentText = await page.evaluate(() =>
    (document.querySelector('.json-viewer') || {}).innerText || '')
  check('切到「正文」仍渲染出 JSON 卡片（非法内容给出错误而非白屏）',
    hasViewer && contentText.length > 0, contentText.replace(/\s+/g, ' ').slice(0, 60))

  const bodyText = await page.evaluate(() => document.body.innerText)
  check('笔记详情已无 Jevko 字样', !/jevko/i.test(bodyText), '')
  check('侧栏元信息改名 JSON 节点', bodyText.includes('JSON 节点'), '')
}

// ============================================================ 9
async function cleanup() {
  let n = 0
  for (const id of createdTypes) {
    if (!id) continue
    const r = await del(`/api/entity-types/${id}`)
    if (r.status === 200) n++
  }
  for (const id of createdNotes) {
    await del(`/api/records/${id}`)
  }
  console.log(`\n（清理：移除本次创建的 ${n}/${createdTypes.length} 个测试模型、`
    + `${createdNotes.length} 条测试笔记）`)
}

async function main() {
  await S.login()
  const ctx = await testJsonApi().then(testModelValidate).then(testCreateAndExport)
  await testWriteBack(ctx)
  await testAttachmentMeta()

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })
  await S.loginPage(page)

  const errors = []
  const bad = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))
  page.on('response', r => {
    const u = r.url()
    if (r.status() >= 400 && u.includes('/api/')) bad.push(`${r.status()} ${u}`)
  })

  const contract = await j('/api/entity-types/by-key/contract')

  await testFrontendEditor(page, contract.body.id)
  await testFrontendLibrary(page)
  await testFrontendNote(page)

  console.log('\n=== 9. 前端控制台与接口健康 ===')
  check('前端无控制台错误', errors.length === 0, errors.slice(0, 3).join(' | '))
  check('无 4xx/5xx 接口调用', bad.length === 0, bad.slice(0, 3).join(' | '))

  await browser.close()
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
