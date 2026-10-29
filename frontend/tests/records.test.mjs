// 记录字段逻辑的纯函数断言
// 覆盖 utils/recordFields.js：显示名、空值判断、校验、归一、搜索、筛选、显示值
// 这些函数同时被「记录页」和「应用独立页」使用，钉住它们就等于钉住了两个页面的行为
import {
  recordDisplayName, isBlankValue, validateRecordData, coerceFieldValue,
  coerceRecordData, recordMatchesKeyword, fieldMatchesFilter, filterRecords,
  referenceLabel, displayValue, fieldChoices,
  defaultColumnKeys, filterColumnsByKeys, countActiveFilters, cleanFilterParams,
  tableCandidateFields, TABLE_EXCLUDED_TYPES,
} from '../src/utils/recordFields.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  ' + detail : ''}`)
}
const has = (s, sub) => String(s).includes(sub)

const FIELDS = [
  { key: 'name', name: '客户名称', type: 'text', required: true },
  { key: 'level', name: '等级', type: 'select', options: { choices: ['A', 'B', 'C'] } },
  { key: 'tags', name: '标签', type: 'multiselect', options: { choices: ['重点', '新客'] } },
  { key: 'amount', name: '金额', type: 'number' },
  { key: 'signed', name: '已签约', type: 'boolean' },
  { key: 'date', name: '签约日期', type: 'date' },
  { key: 'owner', name: '负责人', type: 'reference', options: { target: 'user' } },
]

// ---------- 候选项：两种字段形态都要认 ----------
{
  // 接口返回的是后端形态：选项在 options.choices
  assert('后端形态的选项能取到',
    JSON.stringify(fieldChoices({ type: 'select', options: { choices: ['A', 'B'] } })) === '["A","B"]')
  // 编辑器形态：选项在 choices
  assert('编辑器形态的选项能取到',
    JSON.stringify(fieldChoices({ type: 'select', choices: ['A', 'B'] })) === '["A","B"]')
  assert('没有选项时是空数组',
    JSON.stringify(fieldChoices({ type: 'text' })) === '[]')
}

// ---------- recordDisplayName ----------
{
  assert('优先取 name', recordDisplayName({ id: 7, data: { name: '阿里' } }) === '阿里')
  assert('其次取 title', recordDisplayName({ id: 7, data: { title: '合同' } }) === '合同')
  assert('再次取 code', recordDisplayName({ id: 7, data: { code: 'C-01' } }) === 'C-01')
  assert('都没有就用 id', recordDisplayName({ id: 7, data: {} }) === '#7')
  assert('空记录不炸', recordDisplayName(null) === '#')
}

// ---------- isBlankValue：false 与 0 不是空 ----------
{
  assert('null 是空', isBlankValue('text', null))
  assert('undefined 是空', isBlankValue('text', undefined))
  assert('空串是空', isBlankValue('text', '   '))
  assert('空数组是空', isBlankValue('multiselect', []))
  assert('false 不是空', !isBlankValue('boolean', false))
  assert('0 不是空', !isBlankValue('number', 0))
}

// ---------- validateRecordData ----------
{
  const r = validateRecordData(FIELDS, { name: '阿里' })
  assert('必填齐了就没有错误', r.ok, JSON.stringify(r.errors))
  assert('错误信息里带字段名', r.messages.every(m => has(m, '「')))

  const miss = validateRecordData(FIELDS, { name: '  ' })
  assert('必填没填不通过', !miss.ok)
  assert('必填提示是中文', has(miss.messages[0], '是必填项'), miss.messages[0])

  const badNum = validateRecordData(FIELDS, { name: 'x', amount: 'abc' })
  assert('数字字段填错值会报错', !badNum.ok)
  assert('数字提示友好', has(badNum.messages[0], '需要填一个数字'), badNum.messages[0])

  const badChoice = validateRecordData(FIELDS, { name: 'x', level: 'D' })
  assert('枚举值不在候选里会报错', !badChoice.ok)
  assert('枚举提示列出候选', has(badChoice.messages[0], 'A、B、C'), badChoice.messages[0])

  const badDate = validateRecordData(FIELDS, { name: 'x', date: '不是日期' })
  assert('日期格式不对会报错', !badDate.ok)

  const badRef = validateRecordData(FIELDS, { name: 'x', owner: 'abc' })
  assert('关联字段非法会报错', !badRef.ok)

  const okMulti = validateRecordData(FIELDS, { name: 'x', tags: ['重点'] })
  assert('多选值合法时通过', okMulti.ok)
}

// ---------- coerceFieldValue：落库前收口 ----------
{
  assert('数字转成 number', coerceFieldValue({ type: 'number' }, '12') === 12)
  assert('布尔 true 归一', coerceFieldValue({ type: 'boolean' }, 'true') === true)
  assert('布尔 false 归一', coerceFieldValue({ type: 'boolean' }, false) === false)
  assert('空布尔归一成 false', coerceFieldValue({ type: 'boolean' }, '') === false)
  assert('多选拆成数组', JSON.stringify(coerceFieldValue({ type: 'multiselect' }, '重点,新客')) === '["重点","新客"]')
  assert('空多选归一成空数组', JSON.stringify(coerceFieldValue({ type: 'multiselect' }, '')) === '[]')
  assert('日期只留到天', coerceFieldValue({ type: 'date' }, '2026-03-05') === '2026-03-05')
  assert('时间去掉 T', coerceFieldValue({ type: 'datetime' }, '2026-03-05T10:20') === '2026-03-05 10:20')
  assert('文本转成字符串', coerceFieldValue({ type: 'text' }, 5) === '5')

  const cleaned = coerceRecordData(FIELDS, { name: 'x', amount: '3', 脏字段: '不要' })
  assert('只保留模型里定义的字段', !('脏字段' in cleaned))
  assert('定义内的字段被归一', cleaned.amount === 3)
}

// ---------- recordMatchesKeyword ----------
{
  const rec = { id: 1, data: { name: '阿里巴巴', level: 'A', tags: ['重点'] } }
  assert('空关键词命中', recordMatchesKeyword(rec, ''))
  assert('按字段值搜', recordMatchesKeyword(rec, '阿里'))
  assert('大小写不敏感', recordMatchesKeyword(rec, 'a'))
  assert('搜不到就不命中', !recordMatchesKeyword(rec, '腾讯'))
  assert('数组值也算', recordMatchesKeyword(rec, '重点'))
}

// ---------- 筛选 ----------
{
  const RECS = [
    { id: 1, data: { name: '甲', level: 'A', signed: true } },
    { id: 2, data: { name: '乙', level: 'B', signed: false } },
    { id: 3, data: { name: '丙', level: 'A', signed: false } },
  ]
  assert('布尔筛选命中', fieldMatchesFilter('boolean', true, true))
  assert('布尔筛选排除', !fieldMatchesFilter('boolean', false, true))
  assert('未设置筛选条件时全部命中', fieldMatchesFilter('text', '任意', null))
  assert('单选筛选命中', fieldMatchesFilter('select', 'A', 'A'))
  assert('单选筛选排除', !fieldMatchesFilter('select', 'B', 'A'))
  assert('多选命中其一即可', fieldMatchesFilter('multiselect', ['重点', '新客'], ['新客']))
  assert('多选都不命中则排除', !fieldMatchesFilter('multiselect', ['重点'], ['新客']))

  const hit = filterRecords(RECS, { level: 'A' }, FIELDS)
  assert('按枚举过滤', hit.length === 2, `实际 ${hit.length}`)
  const hit2 = filterRecords(RECS, { level: 'A', signed: true }, FIELDS)
  assert('多条件同时满足', hit2.length === 1)
  assert('没有筛选条件时原样返回', filterRecords(RECS, {}, FIELDS).length === 3)
  assert('空数组筛选不生效', filterRecords(RECS, { level: [] }, FIELDS).length === 3)
  assert('不改动原数组', RECS.length === 3)
}

// ---------- 显示值 ----------
{
  const labels = { 'user:3': '张三' }
  assert('空值显示破折号', displayValue({ type: 'text' }, '').text === '—')
  assert('布尔显示是/否', displayValue({ type: 'boolean' }, true).text === '是')
  assert('单选是标签', displayValue({ type: 'select' }, 'A').kind === 'tag')
  assert('多选是标签组', displayValue({ type: 'multiselect' }, ['A', 'B']).kind === 'tags')
  assert('数字保持数字样式', displayValue({ type: 'number' }, 12).kind === 'number')
  assert('日期截到天', displayValue({ type: 'date' }, '2026-03-05T10:00').text === '2026-03-05')
  assert('时间保留到分', displayValue({ type: 'datetime' }, '2026-03-05T10:20').text === '2026-03-05 10:20')
  assert('关联显示名称而不是 id',
    displayValue({ type: 'reference', options: { target: 'user' } }, 3, labels).text === '张三')
  assert('关联没有名字时退回 id',
    displayValue({ type: 'reference', options: { target: 'user' } }, 9, labels).text === '#9')
  assert('外键显示名查找', referenceLabel(labels, { options: { target: 'user' } }, 3) === '张三')
  assert('外键没有目标模型返回空', referenceLabel(labels, { options: {} }, 3) === '')
}

// ---------- 列显示设置：两页共用（记录页 / 应用独立页） ----------
{
  const COLS = [
    { key: 'a', name: '甲', type: 'text' },
    { key: 'b', name: '乙', type: 'select' },
    { key: 'c', name: '丙', type: 'textarea' },
    { key: 'd', name: '丁', type: 'file' },
    { key: 'e', name: '戊', type: 'image' },
    { key: 'f', name: '己', type: 'richtext' },
    { key: 'g', name: '庚', type: 'number' },
  ]
  // 长文本与附件不进表格列（它们在卡片视图里看得到）
  assert('长文本与附件不作为表格列',
    JSON.stringify(tableCandidateFields(COLS).map(f => f.key)) === '["a","b","g"]',
    JSON.stringify(tableCandidateFields(COLS).map(f => f.key)))
  assert('排除类型就是那四种',
    JSON.stringify(TABLE_EXCLUDED_TYPES) === '["file","image","textarea","richtext"]')

  // 默认勾 8 个
  const many = Array.from({ length: 12 }, (_, i) => ({ key: `k${i}`, name: `字段${i}`, type: 'text' }))
  assert('默认最多 8 列', defaultColumnKeys(many).length === 8, String(defaultColumnKeys(many).length))
  assert('默认列取前 8 个', defaultColumnKeys(many)[0] === 'k0')
  assert('默认列跳过被排除的类型',
    JSON.stringify(defaultColumnKeys(COLS)) === '["a","b","g"]')

  // 按勾选过滤列
  assert('按勾选过滤列',
    JSON.stringify(filterColumnsByKeys(COLS, ['b', 'g']).map(f => f.key)) === '["b","g"]')
  assert('一个都没勾就没有列', filterColumnsByKeys(COLS, []).length === 0)
  assert('勾了不存在的 key 不出错', filterColumnsByKeys(COLS, ['zzz']).length === 0)
}

// ---------- 筛选条件计数与参数整理 ----------
{
  assert('没有筛选条件时计数为 0', countActiveFilters({}) === 0)
  assert('有一个条件时计数为 1', countActiveFilters({ level: 'A' }) === 1)
  assert('空串不算条件', countActiveFilters({ level: '' }) === 0)
  assert('null 不算条件', countActiveFilters({ level: null }) === 0)
  assert('空数组不算条件', countActiveFilters({ level: [] }) === 0)
  assert('多选有值算条件', countActiveFilters({ level: ['A'] }) === 1)
  assert('false 也算条件（布尔筛选用）', countActiveFilters({ signed: false }) === 1)

  assert('空条件整理成空对象', JSON.stringify(cleanFilterParams({})) === '{}')
  assert('剔掉空串与 null',
    JSON.stringify(cleanFilterParams({ a: '', b: null, c: undefined })) === '{}')
  assert('剔掉空数组',
    JSON.stringify(cleanFilterParams({ level: [] })) === '{}')
  assert('保留有效条件',
    JSON.stringify(cleanFilterParams({ level: 'A' })) === '{"level":"A"}')
  assert('保留多选数组',
    JSON.stringify(cleanFilterParams({ level: ['A', 'B'] })) === '{"level":["A","B"]}')
  assert('保留 false（布尔筛选用）',
    JSON.stringify(cleanFilterParams({ signed: false })) === '{"signed":false}')
}

console.log(failed ? `\n❌ ${failed} 项断言未通过` : '\n✅ 记录字段逻辑全部通过')
process.exit(failed ? 1 : 0)
