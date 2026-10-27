// 数据模型（实体类型）纯函数断言
// 覆盖 utils/modelFields.js：字段类型元数据、Key 规则、字段校验、
// payload 构造、列表筛选与排序、卡片字段预览
//
// 为什么这些要有单测：
// 字段类型说明文案是弹窗里唯一的「选型指南」，类型集合一旦和
// utils/format.js 的 FIELD_TYPES 漂移，下拉里就会出现渲染器不认识的类型；
// Key 规则又必须和后端 model_json.py 同口径，否则前端放行、后端才报错。
import {
  FIELD_TYPE_META, FIELD_TYPE_GROUPS, MODEL_KEY_RE,
  fieldTypeMeta, fieldTypeDesc, fieldTypeIcon, fieldTypeColor,
  isChoiceType, isReferenceType, choicesOf,
  validateModelKey, validateFieldKey, validateModelForm,
  buildFieldOptions, buildModelPayload, toEditorFields,
  filterModels, sortModels, fieldPreviewTags,
  FIELD_PRESETS, makePresetField, makeEmptyField,
} from '../src/utils/modelFields.js'
import { FIELD_TYPES } from '../src/utils/format.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'}${name}${detail ? '  ' + detail : ''}`)
}
const has = (s, sub) => String(s).includes(sub)

// ---------- 字段类型元数据：必须和渲染器认识的类型完全一致 ----------
{
  const metaValues = FIELD_TYPE_META.map(m => m.value)
  const renderValues = FIELD_TYPES.map(t => t.value)
  assert('类型集合与 FIELD_TYPES 一致（不多不少）',
    metaValues.length === renderValues.length && metaValues.every(v => renderValues.includes(v)),
    metaValues.join(','))
  assert('每个类型都有说明文案', FIELD_TYPE_META.every(m => m.desc && m.desc.length >= 8))
  assert('每个类型都有图标和颜色', FIELD_TYPE_META.every(m => m.icon && /^#[0-9a-f]{6}$/i.test(m.color)))
  assert('类型分组不重不漏', (() => {
    const flat = FIELD_TYPE_GROUPS.flatMap(g => g.types.map(t => t.value))
    return flat.length === FIELD_TYPE_META.length && new Set(flat).size === flat.length
  })())
  assert('未知类型有兜底而不是崩', fieldTypeMeta('nope').label === 'nope')
  assert('单选/多选归为选择类', isChoiceType('select') && isChoiceType('multiselect') && !isChoiceType('text'))
  assert('外键单独归类', isReferenceType('reference') && !isReferenceType('text'))
  assert('类型说明可单独取用', has(fieldTypeDesc('text'), '短文本'))
  assert('类型图标可单独取用', fieldTypeIcon('number') === '#')
  assert('类型颜色可单独取用', fieldTypeColor('text') === '#5b5fc7')
}

// ---------- Key 规则：与后端 model_json.py 的 KEY_RE 同口径 ----------
{
  assert('合法 Key 通过', validateModelKey('contract').ok)
  assert('下划线开头通过', validateModelKey('_x1').ok)
  assert('数字开头被拒', !validateModelKey('1abc').ok)
  assert('中文 Key 被拒', !validateModelKey('合同').ok)
  assert('含横线被拒', !validateModelKey('a-b').ok)
  assert('空 Key 被拒', !validateModelKey('').ok)
  assert('空白 Key 被拒', !validateModelKey('   ').ok)
  assert('占用提示指明是哪个 Key', has(validateModelKey('dup', { existingKeys: ['dup'] }).msg, 'dup'))
  assert('Key 正则与后端一致', MODEL_KEY_RE.test('a_b1') && !MODEL_KEY_RE.test('1a'))
}

// ---------- 字段标识：模型内唯一 ----------
{
  const fields = [{ key: 'name' }, { key: 'code' }]
  assert('字段 Key 合法通过', validateFieldKey('owner', fields, 2).ok)
  assert('字段 Key 重复被拒', has(validateFieldKey('name', fields, 1).msg, '第 1 个'))
  assert('字段 Key 撞自己不算重复', validateFieldKey('name', fields, 0).ok)
  assert('空字段 Key 被拒', !validateFieldKey('', fields, 0).ok)
  assert('非法字段 Key 被拒', !validateFieldKey('1x', fields, 0).ok)
}

// ---------- 表单级校验 ----------
{
  const okForm = {
    key: 'project', name: '项目',
    fields: [{ key: 'name', name: '名称', type: 'text', required: true }],
  }
  assert('完整表单校验通过', validateModelForm(okForm).ok)
  assert('缺模型名被拦', !validateModelForm({ ...okForm, name: '' }).ok)
  assert('缺字段被拦', !validateModelForm({ ...okForm, fields: [] }).ok)
  assert('字段名缺失被拦', !validateModelForm({
    ...okForm, fields: [{ key: 'a', name: '', type: 'text' }],
  }).ok)
  assert('选择类型没有选项被拦', !validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'select', choicesText: '' }],
  }).ok)
  assert('选择类型有选项就放行', validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'select', choicesText: '甲, 乙' }],
  }).ok)
  assert('外键没目标被拦', !validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'reference', options: {} }],
  }).ok)
  // 存量模型里「选择类型没配选项」的字段不该拦住保存（只提醒）
  assert('允许放行存量空选项字段', validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'multiselect', choices: [] }],
  }, { allowEmptyChoices: ['a'] }).ok)
  assert('新加的空选项字段仍然被拦', !validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'multiselect', choices: [] }],
  }).ok)
  assert('放行名单之外的字段仍被拦', !validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'multiselect', choices: [] }],
  }, { allowEmptyChoices: ['b'] }).ok)
  assert('外键有目标就放行', validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'reference', options: { target: 'other' } }],
  }).ok)
  assert('校验信息能直接给人看', validateModelForm({ key: '', name: '', fields: [] }).messages.length >= 3)
  assert('字段级错误能定位到下标', !!validateModelForm({
    ...okForm, fields: [{ key: 'a', name: 'A', type: 'text' }, { key: 'a', name: 'B', type: 'text' }],
  }).errors.fields[1])
}

// ---------- payload 构造：后端 EntityTypeIn 的形状 ----------
{
  const form = {
    key: ' contract ', name: ' 合同 ', icon: 'Files', description: ' 说明 ', app: 'sales', order: 3,
    fields: [
      { key: 'title', name: '标题', type: 'text', required: true, unique: true, defaultValue: '' },
      { key: 'status', name: '状态', type: 'select', required: false, choicesText: '草稿, 生效' },
      { key: 'owner_id', name: '负责人', type: 'reference', options: { target: 'hr_employee' } },
    ],
  }
  const p = buildModelPayload(form)
  assert('payload key 已 trim', p.key === 'contract')
  assert('payload name 已 trim', p.name === '合同')
  assert('payload description 已 trim', p.description === '说明')
  assert('payload 字段顺序按数组重排', p.fields.map(f => f.order).join(',') === '1,2,3')
  assert('选择类型选项进 options.choices', JSON.stringify(p.fields[1].options.choices) === '["草稿","生效"]')
  assert('外键目标进 options.target', p.fields[2].options.target === 'hr_employee')
  assert('唯一标记进 options', p.fields[0].options.unique === true)
  assert('非选择类型不带 choices', p.fields[0].options.choices === undefined)
  assert('默认值数字字段转成数字', buildModelPayload({
    ...form, fields: [{ key: 'a', name: 'A', type: 'number', defaultValue: '12' }],
  }).fields[0].options.default === 12)
  assert('默认值布尔字段转成布尔', buildFieldOptions({
    type: 'boolean', defaultValue: '是',
  }).default === true)
  assert('空默认值不落进 options', buildFieldOptions({ type: 'text', defaultValue: '' }).default === undefined)
  assert('choicesOf 支持中英文逗号', choicesOf({ choicesText: '甲,乙，丙' }).length === 3)
  assert('choicesOf 也吃数组', choicesOf({ choicesText: ['甲', '乙'] }).length === 2)
}

// ---------- 编辑器字段形态互转 ----------
{
  const editor = toEditorFields([
    { key: 'a', name: 'A', type: 'select', required: true, options: { choices: ['x', 'y'], unique: true, default: 'x' } },
  ])
  assert('后端字段转成编辑器字段', editor[0].choices.join(',') === 'x,y')
  assert('后端 unique 转成编辑器标记', editor[0].unique === true)
  assert('后端 default 转成编辑器默认值', editor[0].defaultValue === 'x')
}

// ---------- 列表筛选 ----------
{
  const list = [
    { id: 1, key: 'contract', name: '合同', description: '合同台账', app: 'sales', field_count: 5, record_count: 10 },
    { id: 2, key: 'note', name: '笔记', description: '', app: 'default', field_count: 3, record_count: 0 },
    { id: 3, key: 'project', name: '项目', description: '交付', app: 'sales', field_count: 8, record_count: 2 },
  ]
  assert('按应用筛选', filterModels(list, { app: 'sales' }).length === 2)
  assert('全部应用不筛', filterModels(list, { app: 'all' }).length === 3)
  assert('按名称搜', filterModels(list, { keyword: '项目' }).length === 1)
  assert('按 key 搜', filterModels(list, { keyword: 'contract' }).length === 1)
  assert('按描述搜', filterModels(list, { keyword: '台账' }).length === 1)
  assert('搜不到时为空', filterModels(list, { keyword: '不存在的词' }).length === 0)
  assert('只看有记录的', filterModels(list, { fill: 'with' }).length === 2)
  assert('只看空模型', filterModels(list, { fill: 'empty' }).length === 1)
  assert('筛选组合生效', filterModels(list, { app: 'sales', fill: 'with' }).length === 2)
}

// ---------- 列表排序 ----------
{
  const list = [
    { id: 1, name: '乙', app: 'b', order: 1, field_count: 3, record_count: 5 },
    { id: 2, name: '甲', app: 'a', order: 2, field_count: 9, record_count: 1 },
    { id: 3, name: '丙', app: 'a', order: 1, field_count: 5, record_count: 7 },
  ]
  assert('默认按应用分组', sortModels(list, 'default')[0].app === 'a')
  assert('按字段数倒序', sortModels(list, 'fields')[0].field_count === 9)
  assert('按记录数倒序', sortModels(list, 'records')[0].record_count === 7)
  assert('排序不改动原数组', list[0].name === '乙')
  assert('按名称排序有结果', sortModels(list, 'name').length === 3)
}

// ---------- 卡片字段预览 ----------
{
  const tags = fieldPreviewTags([
    { key: 'title', name: '标题', type: 'text', required: true },
    { key: 'amount', name: '金额', type: 'number' },
    { key: 'd', name: '日期', type: 'date' },
    { key: 'x', name: 'X', type: 'text' },
    { key: 'y', name: 'Y', type: 'text' },
  ], 3)
  assert('只露出前 N 个字段', tags.length === 3)
  assert('预览带类型标签', tags[0].label === '单行文本')
  assert('预览带类型图标', tags[1].icon === '#')
  assert('预览带必填标记', tags[0].required === true)
  assert('字段不足时全露出', fieldPreviewTags([{ key: 'a', name: 'A', type: 'text' }]).length === 1)
}

// ---------- 快捷字段与新字段 ----------
{
  const fields = [{ key: 'name' }]
  const p = makePresetField(FIELD_PRESETS[0], fields)
  assert('快捷字段撞 key 时自动加后缀', p.key === 'name_2')
  assert('快捷字段带出选项', makePresetField(FIELD_PRESETS[2], []).choices.includes('未开始'))
  assert('新字段 key 不撞车', makeEmptyField([{ key: 'field_1' }]).key === 'field_2')
  assert('新字段默认是单行文本', makeEmptyField([]).type === 'text')
}

console.log(failed ? `\n${failed} 个断言失败` : '\n全部断言通过 ✅')
process.exit(failed ? 1 : 0)
