/**
 * 记录（业务数据行）的字段逻辑 —— 纯函数
 * ---------------------------------------------------------------------------
 * 为什么单独抽出来：
 * - 同一个「字段定义」要在四个地方被解释：表格单元格怎么显示、卡片怎么排、
 *   表单用什么控件、筛选器给哪些选项。四处各写一份，迟早会出现
 *   「表格里日期带时分、卡片里只有日期」这种不一致。
 * - 校验与取值归一（数字存成字符串、布尔存成 "true"）是数据落库前的最后一道关口，
 *   必须是纯函数，才能在单测里钉住。
 *
 * 与后端的关系：
 * 字段类型集合、选择项、外键目标都必须和 backend/app/services/model_json.py 同口径，
 * 否则前端放行、后端才报错，用户看到的是一句莫名其妙的 500。
 */
import { choicesOf, isChoiceType, isReferenceType } from './modelFields.js'

/**
 * 取一个选择字段的候选项
 *
 * 为什么不能直接用 modelFields 的 choicesOf：
 * 那个函数认的是「编辑器形态」（field.choices / field.choicesText），
 * 而从接口拿回来的模型定义是「后端形态」（field.options.choices）。
 * 两种形态都得认，否则接口回来的字段一个选项都没有 ——
 * 筛选器是空的、校验也形同虚设。
 */
export function fieldChoices(field) {
  const fromOptions = field?.options?.choices
  if (Array.isArray(fromOptions)) {
    return fromOptions.map(s => String(s).trim()).filter(Boolean)
  }
  return choicesOf(field)
}

/** 记录没有「标题字段」时的兜底：优先 name / title / code，最后用 id */
export function recordDisplayName(record) {
  const d = record?.data || {}
  const v = d.name || d.title || d.code
  return v ? String(v) : `#${record?.id ?? ''}`
}

/**
 * 字段是否「空」
 * 布尔 false 与数字 0 都是有效值，不能当成没填 —— 这是表单校验最常见的错。
 */
export function isBlankValue(type, value) {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

/**
 * 校验一条记录的数据
 * @param {Array} fields 模型的字段定义
 * @param {object} data 记录数据
 * @returns {{ok: boolean, errors: Record<string,string>, messages: string[]}}
 */
export function validateRecordData(fields = [], data = {}) {
  const errors = {}
  const messages = []
  for (const f of fields) {
    const key = f?.key
    if (!key) continue
    const value = data[key]
    const name = f.name || key
    if (f.required && isBlankValue(f.type, value)) {
      errors[key] = `「${name}」是必填项`
      messages.push(errors[key])
      continue
    }
    if (isBlankValue(f.type, value)) continue
    if (f.type === 'number' && !Number.isFinite(Number(value))) {
      errors[key] = `「${name}」需要填一个数字`
      messages.push(errors[key])
      continue
    }
    if (f.type === 'date' && Number.isNaN(Date.parse(String(value)))) {
      errors[key] = `「${name}」的日期格式不对`
      messages.push(errors[key])
      continue
    }
    if (f.type === 'datetime' && Number.isNaN(Date.parse(String(value).replace(' ', 'T')))) {
      errors[key] = `「${name}」的时间格式不对`
      messages.push(errors[key])
      continue
    }
    if (isChoiceType(f.type)) {
      const choices = fieldChoices(f)
      if (choices.length) {
        const picked = Array.isArray(value) ? value : [value]
        const bad = picked.find(v => !choices.includes(String(v)))
        if (bad !== undefined) {
          errors[key] = `「${name}」只能选：${choices.join('、')}`
          messages.push(errors[key])
          continue
        }
      }
    }
    if (isReferenceType(f.type) && !Number.isFinite(Number(value))) {
      errors[key] = `「${name}」需要选择一条关联记录`
      messages.push(errors[key])
    }
  }
  return { ok: !messages.length, errors, messages }
}

/**
 * 落库前的取值归一
 * 数字存成字符串、布尔存成 "true"、多选存成逗号串，是这类系统最常见的数据脏法；
 * 在这里统一收口，后端就不用到处兼容。
 */
export function coerceFieldValue(field, value) {
  const type = field?.type
  if (isBlankValue(type, value)) {
    if (type === 'boolean') return false
    if (type === 'multiselect') return []
    return null
  }
  switch (type) {
    case 'number': {
      const n = Number(value)
      return Number.isFinite(n) ? n : value
    }
    case 'boolean':
      return value === true || value === 'true' || value === 1 || value === '1'
    case 'multiselect':
      return Array.isArray(value) ? value : String(value).split(/[,，]/).map(s => s.trim()).filter(Boolean)
    case 'reference': {
      const n = Number(value)
      return Number.isFinite(n) ? n : value
    }
    case 'date':
      return String(value).slice(0, 10)
    case 'datetime':
      return String(value).replace('T', ' ').slice(0, 19)
    case 'select':
    case 'text':
    case 'textarea':
    case 'richtext':
      return String(value)
    default:
      return value
  }
}

/** 整条记录归一：只保留模型里定义的字段，避免脏数据混进来 */
export function coerceRecordData(fields = [], data = {}) {
  const out = {}
  for (const f of fields) {
    if (!f?.key) continue
    out[f.key] = coerceFieldValue(f, data[f.key])
  }
  return out
}

/** 模糊搜索：把记录里所有值摊平成一段文本再找 */
export function recordMatchesKeyword(record, keyword) {
  const kw = String(keyword || '').trim().toLowerCase()
  if (!kw) return true
  const d = record?.data || {}
  for (const v of Object.values(d)) {
    if (v === null || v === undefined) continue
    const text = Array.isArray(v) ? v.join(' ') : String(v)
    if (text.toLowerCase().includes(kw)) return true
  }
  return recordDisplayName(record).toLowerCase().includes(kw)
}

/** 单个字段的筛选命中 */
export function fieldMatchesFilter(type, value, expected) {
  if (expected === null || expected === undefined || expected === '') return true
  if (type === 'boolean') {
    const want = expected === true || expected === 'true' || expected === 1 || expected === '1'
    return Boolean(value) === want
  }
  // 记录的值与期望值都摊平成数组再比：
  // 多选字段存的是数组，单选字段存的是字符串，筛选用「命中其一」最符合直觉
  const vals = Array.isArray(value) ? value : [value]
  const wanted = Array.isArray(expected) ? expected : [expected]
  return wanted.some(w => vals.some(v => String(v) === String(w)))
}

/**
 * 按字段过滤（本地）
 *
 * 为什么是本地过滤：记录列表接口目前没有暴露字段过滤参数
 * （后端 service 里有 filters，路由没往下传），所以筛选只能在前端做。
 * 有筛选时上层会一次性把该模型的记录拉全（上限 500 条）再本地筛，
 * 避免出现「筛选后翻页翻到别的页就没结果」的错觉。
 *
 * @param {Array} records
 * @param {object} filters 字段 key → 期望值
 * @param {Array} fields 字段定义（用来知道每个字段的类型）
 */
export function filterRecords(records = [], filters = {}, fields = []) {
  const entries = Object.entries(filters || {}).filter(([, v]) =>
    v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length))
  if (!entries.length) return [...records]
  const typeOf = key => fields.find(f => f.key === key)?.type || 'text'
  return records.filter(r => entries.every(([key, expected]) =>
    fieldMatchesFilter(typeOf(key), r.data?.[key], expected)))
}

/** 外键显示名：`${目标模型key}:${记录id}` → 名称 */
export function referenceLabel(labels = {}, field, value) {
  if (!value) return ''
  const tkey = field?.options?.target
  if (!tkey) return ''
  return labels[`${tkey}:${value}`] || ''
}

/**
 * 表格 / 卡片里显示用的值（已经转成人话）
 * @returns {{kind: string, text: string, items?: string[], label?: string}}
 */
export function displayValue(field, value, labels = {}) {
  const type = field?.type
  if (value === null || value === undefined || value === '') {
    return { kind: 'empty', text: '—' }
  }
  if (type === 'boolean') {
    return { kind: 'boolean', text: value ? '是' : '否' }
  }
  if (type === 'select') {
    return { kind: 'tag', text: String(value), items: [String(value)] }
  }
  if (type === 'multiselect') {
    const arr = Array.isArray(value) ? value : [value]
    return { kind: 'tags', text: arr.join('、'), items: arr.map(String) }
  }
  if (type === 'reference') {
    const label = referenceLabel(labels, field, value)
    return { kind: 'reference', text: label || `#${value}`, label }
  }
  if (type === 'number') {
    return { kind: 'number', text: String(value) }
  }
  if (type === 'date') {
    return { kind: 'date', text: String(value).slice(0, 10) }
  }
  if (type === 'datetime') {
    return { kind: 'datetime', text: String(value).replace('T', ' ').slice(0, 16) }
  }
  return { kind: 'text', text: String(value) }
}

/**
 * 默认显示哪些列
 *
 * 为什么长文本与附件不进表格：表格宽度有限，一个长文本列会把其它列全挤没；
 * 而这些字段在卡片视图里看得到，所以不是「丢掉」，是换个地方呈现。
 */
export const TABLE_EXCLUDED_TYPES = ['file', 'image', 'textarea', 'richtext']
export const DEFAULT_COLUMN_LIMIT = 8

/** 可以显示成表格列的候选字段（长文本与附件排除在外） */
export function tableCandidateFields(fields = []) {
  return (fields || []).filter(f => !TABLE_EXCLUDED_TYPES.includes(f?.type))
}

/**
 * 默认勾选的列（字段 key 列表）
 *
 * 为什么默认只勾 8 个：字段多的模型（如「文献」有 11 个字段）全塞进表格，
 * 横向滚动会滚到用户放弃。默认给 8 个，剩下的让用户在「列显示设置」里自己加。
 */
export function defaultColumnKeys(fields = [], limit = DEFAULT_COLUMN_LIMIT) {
  return tableCandidateFields(fields).slice(0, limit).map(f => f.key)
}

/**
 * 按用户勾选的 key 过滤出真正的列
 * @param {Array} fields 候选字段
 * @param {Array} keys 勾选的字段 key
 */
export function filterColumnsByKeys(fields = [], keys = []) {
  const set = new Set(keys || [])
  return (fields || []).filter(f => set.has(f.key))
}

/**
 * 当前有几个筛选条件生效
 * 空串、空数组、null 都不算 —— 筛选器里「选了又清空」不该显示成有条件
 */
export function countActiveFilters(filters = {}) {
  return Object.values(filters || {}).filter(v =>
    v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length)).length
}

/**
 * 把筛选状态整理成能发给接口的参数
 *
 * 为什么空值要剔掉：接口收到 {"level": []} 会当成「筛 level 等于空数组」，
 * 结果一条都查不出来 —— 用户看到的却是「这个模型没有数据」。
 */
export function cleanFilterParams(filters = {}) {
  const out = {}
  for (const [k, v] of Object.entries(filters || {})) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) {
      if (v.length) out[k] = v
    } else {
      out[k] = v
    }
  }
  return out
}
