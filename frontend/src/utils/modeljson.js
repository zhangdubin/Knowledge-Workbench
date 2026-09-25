// 数据模型的 JSON 归一化（前端版，与后端 services/model_json.py 同源同口径）
//
// 存在的意义：用户把 JSON 粘进编辑器时，立刻能看到「解析成什么样」，
// 点「应用到表单」就能把字段填进可视化编辑器，不必等一趟网络往返。
// 真正落库仍走后端 /api/entity-types/import，由后端做最终裁决。

import { locateError } from './jsonview'

export const FIELD_TYPES = [
  'text', 'textarea', 'richtext', 'number', 'date', 'datetime',
  'select', 'multiselect', 'boolean', 'file', 'image', 'reference',
]

const CHOICE_TYPES = ['select', 'multiselect']
const REF_TYPES = ['reference']

export const TYPE_ALIASES = {
  text: 'text', string: 'text', str: 'text', varchar: 'text', char: 'text',
  单行文本: 'text', 文本: 'text', 字符串: 'text',
  textarea: 'textarea', text_area: 'textarea', longtext: 'textarea',
  multiline: 'textarea', 多行文本: 'textarea', 长文本: 'textarea',
  正文: 'textarea', 备注: 'textarea', remark: 'textarea',
  richtext: 'richtext', rich_text: 'richtext', html: 'richtext', 富文本: 'richtext',
  number: 'number', num: 'number', int: 'number', integer: 'number',
  float: 'number', double: 'number', decimal: 'number',
  money: 'number', currency: 'number', 数字: 'number', 数值: 'number',
  金额: 'number', 价格: 'number',
  date: 'date', day: 'date', 日期: 'date',
  datetime: 'datetime', date_time: 'datetime', timestamp: 'datetime',
  日期时间: 'datetime', 时间: 'datetime',
  select: 'select', enum: 'select', radio: 'select', single: 'select',
  single_select: 'select', 单选: 'select', 下拉: 'select', 下拉选择: 'select',
  multiselect: 'multiselect', multi_select: 'multiselect', multi: 'multiselect',
  tags: 'multiselect', tag: 'multiselect', checkbox: 'multiselect',
  array: 'multiselect', list: 'multiselect', 多选: 'multiselect',
  标签: 'multiselect', 多选标签: 'multiselect',
  boolean: 'boolean', bool: 'boolean', switch: 'boolean',
  布尔: 'boolean', 开关: 'boolean', 是否: 'boolean',
  file: 'file', files: 'file', attachment: 'file', 附件: 'file', 文件: 'file',
  image: 'image', img: 'image', picture: 'image', photo: 'image',
  图片: 'image', 图像: 'image',
  reference: 'reference', ref: 'reference', relation: 'reference',
  foreign: 'reference', foreign_key: 'reference', fk: 'reference',
  link: 'reference', 引用: 'reference', 外键: 'reference', 关联: 'reference',
}

const MODEL_KEY_ALIASES = ['key', 'slug', 'identifier', 'id', '标识', '键']
const MODEL_NAME_ALIASES = ['name', 'title', 'label', '名称', '模型名', '模型']
const MODEL_ICON_ALIASES = ['icon', '图标']
const MODEL_DESC_ALIASES = ['description', 'desc', 'remark', '说明', '描述', '备注']
const MODEL_APP_ALIASES = ['app', 'application', '应用', '分组']
const MODEL_ORDER_ALIASES = ['order', 'sort', 'seq', '排序', '顺序']
const MODEL_FIELDS_ALIASES = ['fields', 'columns', 'properties', 'props', '字段', '字段定义']

const FIELD_KEY_ALIASES = ['key', 'field', 'slug', 'code', 'id', '标识', '字段']
const FIELD_NAME_ALIASES = ['name', 'label', 'title', '名称', '字段名', '显示名']
const FIELD_TYPE_ALIASES = ['type', 'kind', 'datatype', 'data_type', '类型']
const FIELD_REQUIRED_ALIASES = ['required', 'is_required', 'must', '必填', '必填项']
const FIELD_OPTIONS_ALIASES = ['options', 'opt', 'config', '配置', '选项配置']
const FIELD_CHOICES_ALIASES = ['choices', 'enum', 'options_list', 'values', '选项']
const FIELD_TARGET_ALIASES = ['target', 'ref', 'reference', 'to', '指向', '目标', '目标模型']
const FIELD_HINT_ALIASES = ['hint', 'help', 'placeholder', 'tip', '提示', '说明']

const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

/** 去掉注释与尾随逗号（只处理字符串字面量之外的部分） */
export function stripJsonNoise(text) {
  const out = []
  const mask = []
  let i = 0
  let inStr = false
  const n = text.length
  while (i < n) {
    const c = text[i]
    if (inStr) {
      out.push(c); mask.push(false)
      if (c === '\\' && i + 1 < n) { out.push(text[i + 1]); mask.push(false); i += 2; continue }
      if (c === '"') inStr = false
      i += 1
      continue
    }
    if (c === '"') { inStr = true; out.push(c); mask.push(false); i += 1; continue }
    if (c === '/' && text[i + 1] === '/') { while (i < n && text[i] !== '\n') i += 1; continue }
    if (c === '/' && text[i + 1] === '*') {
      i += 2
      while (i < n && !(text[i] === '*' && text[i + 1] === '/')) i += 1
      i += 2
      continue
    }
    out.push(c); mask.push(true); i += 1
  }
  const res = []
  for (let idx = 0; idx < out.length; idx++) {
    const ch = out[idx]
    if (ch === ',' && mask[idx]) {
      let j = idx + 1
      while (j < out.length && /\s/.test(out[j]) && mask[j]) j += 1
      if (j < out.length && mask[j] && (out[j] === '}' || out[j] === ']')) continue
    }
    res.push(ch)
  }
  return res.join('')
}

/** 宽松解析：先按标准 JSON 解析，失败再去注释/尾逗号重试 */
export function parseLooseJson(text) {
  const raw = String(text ?? '')
  if (!raw.trim()) return { ok: false, value: null, error: '内容为空，请粘贴 JSON' }
  try {
    return { ok: true, value: JSON.parse(raw), error: '' }
  } catch (e) { /* 继续尝试宽松解析 */ }
  const cleaned = stripJsonNoise(raw)
  try {
    return { ok: true, value: JSON.parse(cleaned), error: '' }
  } catch (e) {
    return {
      ok: false, value: null,
      error: locateError(cleaned, e.message) + (cleaned === raw ? '' : '（已自动忽略注释与尾随逗号）'),
    }
  }
}

// ---------------------------------------------------------------- 小工具

function pick(raw, aliases) {
  if (!raw || typeof raw !== 'object') return undefined
  const lower = {}
  for (const k of Object.keys(raw)) lower[String(k).toLowerCase()] = raw[k]
  for (const a of aliases) {
    if (raw[a] !== undefined && raw[a] !== null && raw[a] !== '') return raw[a]
    const lv = lower[a.toLowerCase()]
    if (lv !== undefined && lv !== null && lv !== '') return lv
  }
  return undefined
}

function text(v) {
  if (v === undefined || v === null) return ''
  if (typeof v === 'object') return ''
  return String(v).trim()
}

function toList(v) {
  if (v === undefined || v === null) return []
  if (Array.isArray(v)) return v.map(x => String(x).trim()).filter(Boolean)
  if (typeof v === 'object') return Object.keys(v).map(k => String(k).trim()).filter(Boolean)
  const s = String(v).trim()
  if (!s) return []
  return s.split(/[,，/、|]/).map(p => p.trim()).filter(Boolean)
}

export function slugKey(raw) {
  let s = text(raw).toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/_{2,}/g, '_').replace(/^_|_$/g, '')
  if (!s) return ''
  if (!KEY_RE.test(s)) s = 'f_' + s
  return s
}

function normalizeType(raw, warnings, where) {
  const t = text(raw).toLowerCase()
  if (!t) return 'text'
  if (TYPE_ALIASES[t]) return TYPE_ALIASES[t]
  warnings.push(`${where}：无法识别的类型「${raw}」，已按单行文本（text）处理`)
  return 'text'
}

function toInt(v, dft = 0) {
  const n = parseInt(v, 10)
  return Number.isFinite(n) ? n : dft
}

// ---------------------------------------------------------------- 主流程

function splitPayload(payload) {
  if (Array.isArray(payload)) return { meta: {}, fields: payload }
  if (!payload || typeof payload !== 'object') {
    throw new Error('JSON 顶层必须是对象 {...} 或字段数组 [...]')
  }
  const inner = payload.model && typeof payload.model === 'object' ? payload.model : null
  const grab = (obj) => {
    for (const a of MODEL_FIELDS_ALIASES) {
      if (obj && Array.isArray(obj[a])) return obj[a]
    }
    return null
  }
  if (inner) {
    const fields = grab(payload) || grab(inner) || []
    const meta = {}
    for (const k of Object.keys(inner)) {
      if (!MODEL_FIELDS_ALIASES.includes(k)) meta[k] = inner[k]
    }
    return { meta, fields }
  }
  const fields = grab(payload) || []
  const meta = {}
  for (const k of Object.keys(payload)) {
    if (!MODEL_FIELDS_ALIASES.includes(k)) meta[k] = payload[k]
  }
  return { meta, fields }
}

export function normalizeField(raw, idx, used, warnings) {
  const where = `第 ${idx + 1} 个字段`
  let item = raw
  if (typeof item === 'string') item = { key: item, name: item, type: 'text' }
  if (!item || typeof item !== 'object') {
    warnings.push(`${where}：不是对象，已按单行文本处理`)
    item = {}
  }

  const optsRaw = pick(item, FIELD_OPTIONS_ALIASES)
  const options = optsRaw && typeof optsRaw === 'object' ? { ...optsRaw } : {}

  let rawType = pick(item, FIELD_TYPE_ALIASES)
  if (rawType && typeof rawType === 'object') {
    Object.assign(options, rawType)
    rawType = undefined
  }
  let choices = pick(item, FIELD_CHOICES_ALIASES)
  if (choices === undefined) choices = options.choices
  let target = pick(item, FIELD_TARGET_ALIASES)
  if (target === undefined) target = options.target
  const hint = pick(item, FIELD_HINT_ALIASES)

  const ftype = normalizeType(rawType, warnings, where)
  let name = text(pick(item, FIELD_NAME_ALIASES))
  const keyRaw = pick(item, FIELD_KEY_ALIASES)

  let key = slugKey(keyRaw) || slugKey(name)
  if (!key) {
    key = `field_${idx + 1}`
    if (name) warnings.push(`${where}：「${name}」没有英文 key（中文名无法自动转写），已暂用 ${key}，建议手动指定`)
    else warnings.push(`${where}：缺少 key / 名称，已自动命名为 ${key}`)
  }
  const base = key
  let n = 2
  while (used.has(key)) { key = `${base}_${n++}` }
  if (key !== base) warnings.push(`${where}：key「${base}」重复，已改为「${key}」`)
  used.add(key)
  if (!name) name = key

  const clean = {}
  if (CHOICE_TYPES.includes(ftype)) {
    const lst = toList(choices)
    if (!lst.length) warnings.push(`${where}「${name}」是选择类型但没有选项，已置为空选项`)
    clean.choices = lst
  } else if (REF_TYPES.includes(ftype)) {
    const tgt = text(target)
    if (!tgt) warnings.push(`${where}「${name}」是引用类型但没有指定目标模型（target）`)
    clean.target = tgt
  } else {
    for (const k of Object.keys(options)) {
      if (k !== 'choices' && k !== 'target') clean[k] = options[k]
    }
  }
  if (hint) clean.hint = text(hint)

  const reqRaw = pick(item, FIELD_REQUIRED_ALIASES)
  let required
  if (typeof reqRaw === 'string') required = ['1', 'true', 'yes', 'y', '是', '必填'].includes(reqRaw.trim().toLowerCase())
  else required = !!reqRaw

  return {
    key,
    name,
    type: ftype,
    required,
    options: clean,
    order: toInt(pick(item, ['order', 'sort', '排序']), idx + 1),
  }
}

/**
 * 任意 JSON 输入 → { model, warnings }，结构性错误抛 Error
 * @param {any} payload 对象 / 字段数组 / 字符串
 */
export function normalizeModel(payload) {
  const warnings = []
  let data = payload
  if (typeof payload === 'string') {
    const r = parseLooseJson(payload)
    if (!r.ok) throw new Error(r.error)
    data = r.value
  }

  const { meta, fields } = splitPayload(data)

  let name = text(pick(meta, MODEL_NAME_ALIASES))
  let key = slugKey(pick(meta, MODEL_KEY_ALIASES))
  if (!key) key = slugKey(name)
  if (!key) throw new Error('缺少模型标识 key（英文/数字/下划线），例如 "key": "contract"')
  if (!name) { name = key; warnings.push(`未提供模型名，已用 key「${key}」代替`) }

  if (!Array.isArray(fields) || !fields.length) throw new Error('没有解析到任何字段，请检查 fields 数组')

  const used = new Set()
  const normalized = fields.map((f, i) => normalizeField(f, i, used, warnings))

  return {
    model: {
      key,
      name,
      icon: text(pick(meta, MODEL_ICON_ALIASES)) || 'Document',
      description: text(pick(meta, MODEL_DESC_ALIASES)),
      app: text(pick(meta, MODEL_APP_ALIASES)) || 'default',
      order: toInt(pick(meta, MODEL_ORDER_ALIASES), 0),
      fields: normalized,
    },
    warnings,
  }
}

/**
 * 表单 → JSON 文本（与服务端 /export 输出保持一致）
 * @param {object} form TypeEditor 的 form
 */
export function buildModelJson(form) {
  const fields = (form.fields || []).map(f => {
    const item = { key: f.key, name: f.name, type: f.type }
    if (f.required) item.required = true
    const opts = f.options || {}
    if (CHOICE_TYPES.includes(f.type)) {
      item.options = { choices: opts.choices || [] }
    } else if (REF_TYPES.includes(f.type)) {
      item.options = { target: opts.target || '' }
    } else if (opts && Object.keys(opts).length) {
      item.options = { ...opts }
    }
    return item
  })
  return JSON.stringify({
    key: form.key || '',
    name: form.name || '',
    icon: form.icon || 'Document',
    description: form.description || '',
    app: form.app || 'default',
    order: form.order || 0,
    fields,
  }, null, 2)
}

/** 新手模板：能直接跑通的示例，方便照着改 */
export function exampleModelJson() {
  return JSON.stringify({
    key: 'contract',
    name: '合同',
    icon: 'Document',
    description: '采购 / 销售合同台账',
    app: 'default',
    order: 0,
    fields: [
      { key: 'title', name: '合同名称', type: 'text', required: true },
      { key: 'code', name: '合同编号', type: 'text' },
      { key: 'amount', name: '金额（元）', type: 'number' },
      { key: 'status', name: '状态', type: 'select', options: { choices: ['草稿', '生效中', '已归档'] } },
      { key: 'sign_date', name: '签订日期', type: 'date' },
      { key: 'owner', name: '负责人', type: 'text' },
      { key: 'tags', name: '标签', type: 'multiselect', options: { choices: ['重点', '长期', '续签'] } },
      { key: 'files', name: '合同附件', type: 'file' },
      { key: 'signed', name: '是否盖章', type: 'boolean' },
      { key: 'remark', name: '备注', type: 'textarea' },
    ],
  }, null, 2)
}
