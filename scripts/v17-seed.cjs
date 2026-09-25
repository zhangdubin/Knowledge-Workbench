/**
 * v17 演示数据：给「知识图谱」铺一张像样的笔记网
 *
 * 背景：在此之前库里只有 1 条笔记、0 条双链，知识图谱页打开就是一屏空白，
 * 没法评判「可用性和美观」到底行不行。这个脚本幂等地补一组互相引用的笔记，
 * 让图谱有真实的结构（枢纽节点、叶子节点、成对互引、孤立笔记）。
 *
 * 幂等：已经存在 5 条以上笔记就跳过，不会重复灌。
 * 全部笔记都带 `示例` 标签，不想要时按标签筛出来删掉即可。
 *
 *   node scripts/v17-seed.cjs            # 补水
 *   node scripts/v17-seed.cjs --force    # 忽略阈值，强制补
 *   node scripts/v17-seed.cjs --clean    # 删除本脚本创建的示例笔记
 */
const S = require('./lib/session.cjs')

const NOTE_TYPE = 'note'
const DEMO_TAG = '示例'

// 刻意设计成一张有形状的网：一个枢纽（概览）、两组成对互引、一条孤立笔记。
// 全连成一片的网状图看起来都一个样，看不出布局好坏；有枢纽 + 有叶子才考验得上。
const NOTES = [
  {
    title: '知识工作台概览',
    tags: [DEMO_TAG, '入门'],
    body: [
      '这是一套「模型自定义」的数据底座：数据模型、字段、关联都由 JSON 定义，文件与记录是同级的一等公民。',
      '',
      '## 四块能力',
      '- 数据建模：见 [[数据模型设计]]，字段与关联都能改',
      '- 关系成网：见 [[关联与图谱]]，记录和文件互相挂接',
      '- 找得到：见 [[检索与向量]]，全文 + 向量混合检索',
      '- 看得清：见 [[驾驶舱配置]]，按需拼指标卡片',
      '',
      '从零上手之前建议先看 [[部署与运维]]。',
    ].join('\n'),
  },
  {
    title: '数据模型设计',
    tags: [DEMO_TAG, '设计'],
    body: [
      '一个「模型」= 一组字段 + 一组关联。模型用 JSON 描述，可以直接粘贴导入，也能从已有模型导出后改。',
      '',
      '字段类型覆盖文本、数字、金额、日期、单选、多选、外键、附件等；外键会自动在图谱里连成边。',
      '写 JSON 时的宽容写法（注释、尾逗号、中文键名）见 [[JSON 定义规范]]。',
      '',
      '模型定完之后，[[关联与图谱]] 才会长出东西来。',
    ].join('\n'),
  },
  {
    title: 'JSON 定义规范',
    tags: [DEMO_TAG, '设计'],
    body: [
      '模型定义就是标准 JSON，但解析器允许三种手写习惯：`//` 注释、尾逗号、以及中文键名别名。',
      '',
      '最小可用示例：',
      '```json',
      '{ "标识": "contract", "模型名": "合同",',
      '  "fields": [ {"key": "title", "名称": "标题", "类型": "字符串", "必填": true} ] }',
      '```',
      '',
      '校验是 dry-run 的：先看报错，再决定落库。回到 [[数据模型设计]]。',
    ].join('\n'),
  },
  {
    title: '关联与图谱',
    tags: [DEMO_TAG, '进阶'],
    body: [
      '关联定义说明「哪一端的什么类型」连到「另一端的什么类型」，两端都可以是业务记录，也可以是数据中心的文件。',
      '',
      '图谱里三种边各有含义：',
      '- 实线箭头 = 手工建立的关联',
      '- 曲线 = 外键字段自动连出来的引用',
      '- 虚线 = 笔记的 [[双向链接]]，没有方向',
      '',
      '一个典型用法是把合同扫描件挂到合同记录上，再从合同走到客户，见 [[知识工作台概览]]。',
      '如果要点开某个数据看指标，去 [[驾驶舱配置]]。',
    ].join('\n'),
  },
  {
    title: '检索与向量',
    tags: [DEMO_TAG, '进阶'],
    body: [
      '文件入库时会抽取正文、建 FTS5 全文索引，并按段落切块写入向量索引。',
      '',
      '检索是两路合并：全文命中给精确匹配，向量命中给语义相近，最后统一重排。',
      'AI 问答也走这条链路，所以「找得到」和「答得准」用的是同一份证据。',
      '',
      '回到 [[知识工作台概览]]。',
    ].join('\n'),
  },
  {
    title: '驾驶舱配置',
    tags: [DEMO_TAG, '进阶'],
    body: [
      '驾驶舱是「把想盯的数据拖成卡片」的地方，一个驾驶舱可以放多张卡片。',
      '',
      '目前支持的卡片：指标大数、图表（柱/折线/饼）、表格、列表、文本。每张卡片自己选数据源、指标、分组和筛选。',
      '配置完可以「试算」，看到的就是保存后看到的那张卡片。',
      '',
      '数据找不全的时候先回 [[检索与向量]] 看看。',
    ].join('\n'),
  },
  {
    title: '权限与审计',
    tags: [DEMO_TAG, '运维'],
    body: [
      '权限是三层：页面能不能进、模型能不能读写、具体功能能不能用。三层组合成「角色」，用户挂角色。',
      '',
      '鉴权走服务端会话，因此停用账号、改口令、强制下线都是立即生效的，不用等令牌过期。',
      '所有写操作与登录事件都进审计表，可按人、按资源、按动作筛。',
      '',
      '部署相关见 [[部署与运维]]。',
    ].join('\n'),
  },
  {
    title: '部署与运维',
    tags: [DEMO_TAG, '运维'],
    body: [
      '两个容器：后端（FastAPI + SQLite）与前端（Nginx 托管构建产物），数据目录整体挂载，升级时镜像换掉即可。',
      '',
      '健康检查直接探后端的 `/api/health`；首次启动会用环境变量里的口令建一个管理员账号，并要求登录后立刻改密。',
      '',
      '安全与权限模型见 [[权限与审计]]。',
    ].join('\n'),
  },
  // 故意留一条没有任何连接的笔记：图谱要能看出「孤立节点」
  {
    title: '零散想法（尚未归类）',
    tags: [DEMO_TAG],
    body: '还没想清楚放哪儿的一些碎片，暂时不引用任何笔记。',
  },
]

async function noteTypeId() {
  const r = await S.j(`/api/entity-types/by-key/${NOTE_TYPE}`)
  if (r.status !== 200) throw new Error(`拿不到 note 模型：${r.status} ${JSON.stringify(r.body)}`)
  return r.body.id
}

async function listNotes(typeId) {
  const r = await S.j(`/api/records/type/${typeId}?page_size=200`)
  return r.body.items || []
}

async function createNote(typeId, n) {
  const r = await S.post(`/api/records/type/${typeId}`, {
    data: { title: n.title, content: n.body, tags: n.tags },
  })
  if (r.status !== 200) throw new Error(`创建笔记「${n.title}」失败：${r.status} ${JSON.stringify(r.body)}`)
  return r.body.record?.id || r.body.id || r.body.item?.id
}

async function main() {
  const clean = process.argv.includes('--clean')
  const force = process.argv.includes('--force')

  await S.login()
  const typeId = await noteTypeId()
  const existing = await listNotes(typeId)

  if (clean) {
    let n = 0
    for (const rec of existing) {
      const tags = rec.data?.tags
      const list = Array.isArray(tags) ? tags : String(tags || '').split(',')
      if (list.map(s => String(s).trim()).includes(DEMO_TAG)) {
        await S.del(`/api/records/${rec.id}`)
        n++
      }
    }
    console.log(`已删除 ${n} 条示例笔记`)
    return
  }

  if (existing.length >= 5 && !force) {
    console.log(`跳过：库里已有 ${existing.length} 条笔记（≥5），如需强制补水用 --force`)
    return
  }

  const have = new Set(existing.map(r => r.data?.title))
  const created = []
  // 先全部建出来，再统一 sync-links —— 否则先建的笔记会把后建的引用成空占位笔记
  for (const n of NOTES) {
    if (have.has(n.title)) continue
    const id = await createNote(typeId, n)
    created.push({ id, title: n.title })
    console.log(`＋ ${n.title}  #${id}`)
  }

  let links = 0
  for (const n of NOTES) {
    const row = created.find(c => c.title === n.title)
      || existing.find(r => r.data?.title === n.title)
    if (!row) continue
    const id = row.id || row.record_id
    const r = await S.post(`/api/notes/${id}/sync-links`, { content: n.body })
    if (r.status === 200) links += r.body.linked_count || 0
  }

  const after = await listNotes(typeId)
  console.log(`\n完成：新建 ${created.length} 条笔记，同步出 ${links} 条双链，当前共 ${after.length} 条笔记`)
}

main().catch(e => { console.error(e); process.exit(1) })
