/**
 * 数据模型（实体类型）的字段元数据 + 表单校验 + 列表筛选排序的纯函数
 *
 * 为什么单独抽出来：
 * 1) 字段类型的「说明文案」是这套交互里最容易悄悄腐烂的东西 ——
 *    类型下拉里写着「支持 [[双链]]」但实际渲染不认，就会误导用户。
 *    抽成纯函数后可以用单测钉住：类型集合必须和 utils/format.js 的 FIELD_TYPES 一致。
 * 2) Key 规则、字段名唯一性这类校验散在模板里就没法测。
 *    搬进弹窗后校验要同时驱动「行内报错」和「保存拦截」，纯函数最合适。
 * 3) 列表的筛选/排序也是纯计算，没必要在组件里写一堆 watch。
 *
 * 注意：这里的规则必须和后端 app/services/model_json.py 同口径
 * （KEY_RE、选择类型的 choices、外键的 target），否则前端放行、后端才报错。
 */
// 带 .js 后缀：Node 的 ESM 单测直接跑本文件，不带后缀解析不到
import { FIELD_TYPES, fieldTypeLabel } from './format.js'

/**
 * 字段类型元数据：图标 + 颜色 + 一句话说明
 *
 * desc 不是装饰 —— 它是用户在「选类型」这一步唯一能看到的解释，
 * 写清楚「选它意味着什么」（存什么、列表页怎么渲染）比写「多行文本」有用得多。
 */
export const FIELD_TYPE_META = [
  { value: 'text', label: '单行文本', icon: 'Aa', color: '#5b5fc7', group: '文本', desc: '短文本：名称、编号、联系人等，单行输入，最常用' },
  { value: 'textarea', label: '多行文本', icon: '¶', color: '#7a6ad0', group: '文本', desc: '长文本：说明、备注、正文；正文里写 [[双链]] 可关联笔记' },
  { value: 'richtext', label: '富文本', icon: '✎', color: '#bb5a86', group: '文本', desc: '需要加粗、列表等排版时用；数据本身仍是纯文本' },
  { value: 'number', label: '数字', icon: '#', color: '#b4801e', group: '数值与日期', desc: '金额、数量、百分比；可排序、可求和' },
  { value: 'date', label: '日期', icon: 'D', color: '#0f9b72', group: '数值与日期', desc: '如 2026-09-24，不带时间' },
  { value: 'datetime', label: '日期时间', icon: 'DT', color: '#0f9b72', group: '数值与日期', desc: '精确到时分，如 2026-09-24 18:30' },
  { value: 'select', label: '单选', icon: '▼', color: '#3f8fa8', group: '选择', desc: '从固定选项里选一个；列表页渲染成彩色标签' },
  { value: 'multiselect', label: '多选', icon: '☷', color: '#3f8fa8', group: '选择', desc: '可同时选多个，如标签、关键词' },
  { value: 'boolean', label: '布尔', icon: '◉', color: '#6b9b3a', group: '选择', desc: '是 / 否开关，如「已完成」「已归档」' },
  { value: 'file', label: '文件', icon: 'F', color: '#c2703a', group: '附件与关联', desc: '上传任意附件，支持 PDF / Word / Excel 在线预览' },
  { value: 'image', label: '图片', icon: 'I', color: '#bb5a86', group: '附件与关联', desc: '上传图片，列表与详情里直接显示缩略图' },
  { value: 'reference', label: '外键引用', icon: 'R', color: '#4a7fb5', group: '附件与关联', desc: '指向另一个模型的记录，建立结构化关联' },
]

/** 类型下拉按组展示，避免 12 个选项平铺让人无从下手 */
export const FIELD_TYPE_GROUPS = (() => {
  const out = []
  for (const m of FIELD_TYPE_META) {
    let g = out.find(x => x.group === m.group)
    if (!g) { g = { group: m.group, types: [] }; out.push(g) }
    g.types.push(m)
  }
  return out
})()

const META_MAP = new Map(FIELD_TYPE_META.map(m => [m.value, m]))

export function fieldTypeMeta(type) {
  return META_MAP.get(type) || { value: type, label: fieldTypeLabel(type), icon: '?', color: '#8a8f9b', group: '其他', desc: '' }
}

export function fieldTypeDesc(type) {
  return fieldTypeMeta(type).desc || ''
}

export function fieldTypeIcon(type) {
  return fieldTypeMeta(type).icon
}

export function fieldTypeColor(type) {
  return fieldTypeMeta(type).color
}

/** 选择类：需要一组固定选项 */
export function isChoiceType(type) {
  return type === 'select' || type === 'multiselect'
}

/** 外键类：需要指定目标模型 */
export function isReferenceType(type) {
  return type === 'reference'
}

/** 与后端 model_json.py 的 KEY_RE 同口径 */
export const MODEL_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

/**
 * 模型 Key 校验
 * @param {string} key
 * @param {object} opts existingKeys 其他模型已占用的 key（编辑时要排除自己）
 * @returns {{ok: boolean, msg: string}}
 */
export function validateModelKey(key, { existingKeys = [] } = {}) {
  const k = String(key ?? '').trim()
  if (!k) return { ok: false, msg: '请填写模型标识（Key）' }
  if (!MODEL_KEY_RE.test(k)) {
    return { ok: false, msg: 'Key 只能包含字母、数字、下划线，且不能以数字开头' }
  }
  if (existingKeys.includes(k)) {
    return { ok: false, msg: `标识「${k}」已被其他模型占用` }
  }
  return { ok: true, msg: '' }
}

/**
 * 字段标识校验（同一模型内唯一）
 * @param {string} key
 * @param {Array} fields 全部字段（用于查重）
 * @param {number} index 当前字段下标（用于报错时指向别的字段）
 */
export function validateFieldKey(key, fields = [], index = -1) {
  const k = String(key ?? '').trim()
  if (!k) return { ok: false, msg: '请填写字段标识' }
  if (!MODEL_KEY_RE.test(k)) {
    return { ok: false, msg: '只能用字母、数字、下划线，且不能以数字开头' }
  }
  const dup = fields.findIndex((f, i) => i !== index && String(f.key ?? '').trim() === k)
  if (dup >= 0) {
    return { ok: false, msg: `与第 ${dup + 1} 个字段的标识重复` }
  }
  return { ok: true, msg: '' }
}

/** 把「未选类型 / 选类型」等都归一，判断是否需要固定选项
 *  两种来源都认：编辑器里的 choices 数组，和 JSON 里的 choicesText 字符串 */
export function choicesOf(field) {
  const arr = field?.choices
  if (Array.isArray(arr)) return arr.map(s => String(s).trim()).filter(Boolean)
  const raw = field?.choicesText
  if (Array.isArray(raw)) return raw.map(s => String(s).trim()).filter(Boolean)
  return String(raw ?? '')
    .split(/[,，]/)
    .map(s => s.trim())
    .filter(Boolean)
}

/**
 * 校验整个模型表单
 *
 * allowEmptyChoices：这些字段的「选择类型没配选项」只当提醒、不拦保存。
 * 为什么要开这个口子：存量模型里确实有「多选标签」这种没配选项的字段
 * （标签本来就是自由输入的），用户只想改个描述却被拦住会非常恼火。
 * 新建的字段不走这个口子 —— 新加的选择字段还是应该逼着配选项。
 *
 * @returns {{ok: boolean, errors: {key: string, name: string, fields: Object}, messages: string[]}}
 */
export function validateModelForm(form, { existingKeys = [], allowEmptyChoices = [] } = {}) {
  const errors = { key: '', name: '', fields: {} }
  const messages = []

  const keyRes = validateModelKey(form?.key, { existingKeys })
  if (!keyRes.ok) { errors.key = keyRes.msg; messages.push(keyRes.msg) }
  if (!String(form?.name ?? '').trim()) {
    errors.name = '请填写模型名'
    messages.push(errors.name)
  }

  const fields = Array.isArray(form?.fields) ? form.fields : []
  if (!fields.length) messages.push('至少需要 1 个字段')

  fields.forEach((f, i) => {
    const fe = {}
    const kRes = validateFieldKey(f?.key, fields, i)
    if (!kRes.ok) fe.key = kRes.msg
    if (!String(f?.name ?? '').trim()) fe.name = '请填写字段名'
    if (isChoiceType(f?.type) && !choicesOf(f).length
        && !allowEmptyChoices.includes(String(f?.key ?? '').trim())) {
      fe.options = '请至少填写一个选项'
    }
    // 目标模型：编辑器形态存在 f.target，后端形态是 f.options.target —— 两种都认，
    // 否则「外键字段没目标」的报错会误伤每一个本来就好好的存量模型
    if (isReferenceType(f?.type) && !String(f?.target ?? f?.options?.target ?? '').trim()) {
      fe.options = '请选择目标模型'
    }
    if (Object.keys(fe).length) errors.fields[i] = fe
  })

  const ok = !errors.key && !errors.name && fields.length > 0 && !Object.keys(errors.fields).length
  return { ok, errors, messages }
}

/** 默认值按类型收一下形态，避免把 "12" 当字符串塞进数字字段 */
function coerceDefault(value, type) {
  const s = String(value ?? '').trim()
  if (!s) return ''
  if (type === 'number') {
    const n = Number(s)
    return Number.isFinite(n) ? n : s
  }
  if (type === 'boolean') {
    if (['true', '1', '是', 'yes'].includes(s.toLowerCase())) return true
    if (['false', '0', '否', 'no'].includes(s.toLowerCase())) return false
  }
  return s
}

/**
 * 字段 → options
 *
 * 选择类的选项和外键的目标都存在 options 里（后端 schema 就是这么定义的），
 * unique / default 也塞进 options：后端 options 是自由 dict，
 * 先把语义记下来，记录表单那边再读它执行。
 */
export function buildFieldOptions(field) {
  const opts = {}
  const type = field?.type
  if (isChoiceType(type)) {
    opts.choices = choicesOf(field)
  } else if (isReferenceType(type)) {
    // 编辑器里目标模型直接放在 field.target；后端形态则是 options.target
    opts.target = String(field?.target ?? field?.options?.target ?? '').trim()
  }
  if (field?.unique) opts.unique = true
  const dv = coerceDefault(field?.defaultValue, type)
  if (dv !== '' && dv !== undefined && dv !== null) opts.default = dv
  return opts
}

/**
 * 编辑器表单 → 后端 payload（EntityTypeIn）
 *
 * 字段顺序用数组下标决定（后端 import 也是这么解释的），
 * 所以 order 一定按当前数组顺序重排，不能保留旧值。
 */
export function buildModelPayload(form) {
  const fields = (form?.fields || []).map((f, i) => ({
    key: String(f?.key ?? '').trim(),
    name: String(f?.name ?? '').trim(),
    type: f?.type || 'text',
    required: !!f?.required,
    options: buildFieldOptions(f),
    order: i + 1,
  }))
  return {
    key: String(form?.key ?? '').trim(),
    name: String(form?.name ?? '').trim(),
    icon: form?.icon || 'Document',
    description: String(form?.description ?? '').trim(),
    app: form?.app || 'default',
    order: Number(form?.order) || 0,
    fields,
  }
}

/**
 * 后端字段定义 → 编辑器字段（统一成编辑器内部形态）
 *
 * 编辑器内部用 choices（数组）存选项：类型下拉旁边的多选框直接绑数组，
 * 输入回车即新增选项，比让用户手打逗号分隔的字符串省事得多。
 */
export function toEditorFields(fields = []) {
  return (fields || []).map((f, i) => ({
    key: f?.key || '',
    name: f?.name || f?.key || `字段${i + 1}`,
    type: f?.type || 'text',
    required: !!f?.required,
    unique: !!f?.options?.unique,
    defaultValue: f?.options?.default ?? '',
    choices: Array.isArray(f?.options?.choices) ? [...f.options.choices] : [],
    target: f?.options?.target || '',
  }))
}

/** 列表筛选：应用 / 关键词 / 有记录-空模型 */
export function filterModels(list, { app = 'all', keyword = '', fill = 'all' } = {}) {
  const kw = String(keyword || '').trim().toLowerCase()
  return (list || []).filter((t) => {
    if (app && app !== 'all' && t.app !== app) return false
    const rc = t.record_count || 0
    if (fill === 'with' && rc <= 0) return false
    if (fill === 'empty' && rc > 0) return false
    if (!kw) return true
    return (
      String(t.name || '').toLowerCase().includes(kw) ||
      String(t.key || '').toLowerCase().includes(kw) ||
      String(t.description || '').toLowerCase().includes(kw) ||
      String(t.app || '').toLowerCase().includes(kw)
    )
  })
}

const byName = (a, b) => String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-Hans-CN')

/** 列表排序：默认按应用+排序值，其余按名称 / 字段数 / 记录数 */
export function sortModels(list, sortBy = 'default') {
  const arr = [...(list || [])]
  switch (sortBy) {
    case 'name':
      return arr.sort((a, b) => byName(a, b) || (a.id || 0) - (b.id || 0))
    case 'fields':
      return arr.sort((a, b) => (b.field_count || 0) - (a.field_count || 0) || byName(a, b))
    case 'records':
      return arr.sort((a, b) => (b.record_count || 0) - (a.record_count || 0) || byName(a, b))
    default:
      return arr.sort((a, b) =>
        String(a.app || '').localeCompare(String(b.app || '')) ||
        (a.order || 0) - (b.order || 0) ||
        (a.id || 0) - (b.id || 0))
  }
}

/**
 * 卡片上的字段类型标签预览（Airtable 那样露出前几个字段）
 * @returns {Array<{key,name,type,label,icon,color,required}>}
 */
export function fieldPreviewTags(fields, limit = 4) {
  return (fields || []).slice(0, limit).map((f) => ({
    key: f?.key || '',
    name: f?.name || f?.key || '',
    type: f?.type || 'text',
    label: fieldTypeLabel(f?.type),
    icon: fieldTypeIcon(f?.type),
    color: fieldTypeColor(f?.type),
    required: !!f?.required,
  }))
}

/** 常用「快捷字段」预设：一次点击补齐 key / 名称 / 类型 / 选项 */
export const FIELD_PRESETS = [
  { key: 'name', name: '名称', type: 'text', required: true },
  { key: 'code', name: '编号', type: 'text' },
  { key: 'status', name: '状态', type: 'select', choices: ['未开始', '进行中', '已完成', '已暂停'] },
  { key: 'owner', name: '负责人', type: 'text' },
  { key: 'priority', name: '优先级', type: 'select', choices: ['低', '中', '高', '紧急'] },
  { key: 'amount', name: '金额（元）', type: 'number' },
  { key: 'start_date', name: '开始日期', type: 'date' },
  { key: 'end_date', name: '结束日期', type: 'date' },
  { key: 'tags', name: '标签', type: 'multiselect', choices: [] },
  { key: 'files', name: '附件', type: 'file' },
  { key: 'images', name: '图片', type: 'image' },
  { key: 'description', name: '说明', type: 'textarea' },
]

/**
 * 加一个快捷字段：key 撞车时自动加后缀
 * （模型内字段 key 必须唯一，撞了保存会被拒）
 */
export function makePresetField(preset, existingFields = []) {
  const used = new Set((existingFields || []).map(f => String(f?.key || '').trim()))
  let key = preset.key
  let n = 2
  while (used.has(key)) key = `${preset.key}_${n++}`
  return {
    key,
    name: preset.name,
    type: preset.type,
    required: !!preset.required,
    unique: false,
    defaultValue: '',
    choices: [...(preset.choices || [])],
    target: '',
  }
}

/** 新建一个空字段：默认名与 key 都带序号，避免用户面对空白 */
export function makeEmptyField(existingFields = []) {
  const idx = (existingFields || []).length + 1
  const used = new Set((existingFields || []).map(f => String(f?.key || '').trim()))
  let key = `field_${idx}`
  let n = idx
  while (used.has(key)) { n += 1; key = `field_${n}` }
  return {
    key,
    name: `字段${idx}`,
    type: 'text',
    required: false,
    unique: false,
    defaultValue: '',
    choices: [],
    target: '',
  }
}
