// 应用中心重做的纯函数断言
// 覆盖 utils/apps.js：搜索命中、分组解析、过滤、排序、分组表读写、批量导出
import {
  DEFAULT_GROUP, ALL_GROUPS, SORT_OPTIONS,
  matchApp, resolveGroup, collectGroups, filterApps, sortApps,
  assignGroup, parseGroupMap, serializeGroupMap,
  resolveAppIcon, appDescription, appsToCsv, appsToJson,
} from '../src/utils/apps.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  ' + detail : ''}`)
}
const has = (s, sub) => String(s).includes(sub)

const APPS = [
  { id: 1, key: 'knowledge', name: '知识库', description: '笔记与文章', icon: 'Notebook', order: 0, entity_count: 3, record_count: 12 },
  { id: 2, key: 'project', name: '项目管理', description: '项目 / 任务 / 里程碑', icon: 'Management', order: 1, entity_count: 4, record_count: 8 },
  { id: 3, key: 'sales', name: '销售管理', description: '', icon: 'TrendCharts', order: 2, entity_count: 2, record_count: 5 },
  { id: 4, key: 'contract', name: '合同台账', description: '合同与回款', icon: 'Files', order: 3, entity_count: 1, record_count: 0 },
]
const GROUPS = { project: '交付', sales: '交付', contract: '财务' }

// ---------- matchApp：名称 / 描述 / Key 都得能搜到 ----------
{
  assert('空关键词命中全部', APPS.every(a => matchApp(a, '')))
  assert('按名称搜', matchApp(APPS[0], '知识'))
  assert('按描述搜', matchApp(APPS[1], '里程碑'))
  assert('按 Key 搜', matchApp(APPS[2], 'sal'))
  assert('大小写不敏感', matchApp(APPS[2], 'SALES'))
  assert('忽略首尾空格', matchApp(APPS[0], '  知识库  '))
  assert('不命中无关词', !matchApp(APPS[0], '合同'))
  assert('空对象不炸', matchApp(null, 'x') === false)
}

// ---------- resolveGroup：后端字段优先，其次本地分组表 ----------
{
  assert('没有分组信息时落在未分组', resolveGroup(APPS[0], {}) === DEFAULT_GROUP)
  assert('本地分组表生效', resolveGroup(APPS[1], GROUPS) === '交付')
  assert('后端返回的 group 优先于本地表', resolveGroup({ ...APPS[1], group: '服务端' }, GROUPS) === '服务端')
  assert('空字符串等于没分组', resolveGroup({ key: 'x', group: '  ' }, GROUPS) === DEFAULT_GROUP)
}

// ---------- collectGroups：分组下拉要带数量 ----------
{
  const gs = collectGroups(APPS, GROUPS)
  const delivery = gs.find(g => g.name === '交付')
  const finance = gs.find(g => g.name === '财务')
  const none = gs.find(g => g.name === DEFAULT_GROUP)
  assert('交付组有 2 个应用', delivery?.count === 2, JSON.stringify(delivery))
  assert('财务组有 1 个应用', finance?.count === 1)
  assert('未分组统计正确', none?.count === 1)
  assert('未分组排在最后', gs[gs.length - 1].name === DEFAULT_GROUP)
}

// ---------- filterApps：关键词与分组是「与」 ----------
{
  assert('按分组筛', filterApps(APPS, { group: '交付', groupMap: GROUPS }).length === 2)
  assert('按分组+关键词筛', filterApps(APPS, { group: '交付', keyword: '合同', groupMap: GROUPS }).length === 0)
  assert('全部分组哨兵不过滤', filterApps(APPS, { group: ALL_GROUPS, groupMap: GROUPS }).length === 4)
  assert('关键词过滤', filterApps(APPS, { keyword: '合同' }).length === 1)
}

// ---------- sortApps：四种排序 ----------
{
  const byModels = sortApps(APPS, 'models')
  assert('按模型数降序', byModels[0].key === 'project' && byModels[3].key === 'contract')
  const byRecords = sortApps(APPS, 'records')
  assert('按记录数降序', byRecords[0].key === 'knowledge')
  const byName = sortApps(APPS, 'name')
  assert('按名称排序（中文按拼音）', byName.map(a => a.name).join(',') === '合同台账,项目管理,销售管理,知识库', byName.map(a => a.name).join(','))
  assert('名称排序结果与 localeCompare 一致',
    byName.map(a => a.name).join(',') === [...APPS.map(a => a.name)].sort((x, y) => x.localeCompare(y, 'zh-Hans-CN')).join(','))
  const byUpdated = sortApps([
    { key: 'a', name: 'A', order: 2, updated_at: '2026-01-01T00:00:00Z' },
    { key: 'b', name: 'B', order: 1, updated_at: '2026-09-01T00:00:00Z' },
  ], 'updated')
  assert('按更新时间降序（新的在前）', byUpdated[0].key === 'b')
  const noTime = sortApps([
    { key: 'x', name: 'X', order: 5, id: 2 },
    { key: 'y', name: 'Y', order: 1, id: 3 },
  ], 'updated')
  assert('没有更新时间时退化成默认顺序', noTime.map(a => a.key).join(',') === 'y,x')
  assert('排序不改动原数组', APPS[0].key === 'knowledge')
  assert('排序选项齐全', SORT_OPTIONS.length === 4)
}

// ---------- assignGroup：批量改分组 ----------
{
  const next = assignGroup(GROUPS, ['knowledge', 'contract'], '归档')
  assert('批量改分组生效', next.knowledge === '归档' && next.contract === '归档')
  assert('原表不被改动', GROUPS.knowledge === undefined)
  assert('传空分组名等于移出分组', assignGroup(GROUPS, ['project'], '').project === undefined)
}

// ---------- 分组表的存取：脏数据不能把页面带崩 ----------
{
  assert('空串解析成空表', JSON.stringify(parseGroupMap('')) === '{}')
  assert('坏 JSON 解析成空表', JSON.stringify(parseGroupMap('{oops')) === '{}')
  assert('数组解析成空表', JSON.stringify(parseGroupMap('[]')) === '{}')
  assert('正常解析', parseGroupMap('{"a":"销售"}').a === '销售')
  assert('忽略空值项', parseGroupMap('{"a":"  ","b":"x"}').a === undefined)
  assert('序列化再解析保持一致', parseGroupMap(serializeGroupMap(GROUPS)).project === '交付')
}

// ---------- 图标与描述兜底 ----------
{
  assert('合法图标名直接用', resolveAppIcon({ icon: 'Files' }, ['Files', 'Grid']) === 'Files')
  assert('emoji 图标退回按 key 推导', resolveAppIcon({ key: 'sales', icon: '📦' }, ['Files']) === 'TrendCharts')
  assert('没有描述时给兜底文案', appDescription({ description: '  ' }) === '暂无说明')
}

// ---------- 批量导出 ----------
{
  const csv = appsToCsv(APPS, GROUPS)
  const lines = csv.split('\n')
  assert('CSV 含表头', has(lines[0], '名称,Key,说明,分组,模型数,记录数'))
  assert('CSV 行数 = 应用数 + 1', lines.length === APPS.length + 1)
  assert('CSV 带分组', has(csv, '交付'))
  const quoted = appsToCsv([{ key: 'k', name: '带"引号",的应用', description: '', entity_count: 0, record_count: 0 }], {})
  assert('CSV 转义引号与逗号', has(quoted, '"带""引号"",的应用"'))
  const json = JSON.parse(appsToJson(APPS, GROUPS))
  assert('JSON 带总数', json.total === 4)
  assert('JSON 带导出时间', !!json.exported_at)
  assert('JSON 里分组正确', json.apps[1].group === '交付')
}

if (failed) {
  console.log(`\n❌ ${failed} 项断言未通过`)
  process.exit(1)
}
console.log('\n✅ 应用中心纯函数断言全部通过')
