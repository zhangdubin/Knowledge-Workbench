export const fieldTypes = [
  'text',
  'textarea',
  'richtext',
  'number',
  'date',
  'datetime',
  'select',
  'multiselect',
  'boolean',
  'file',
  'image',
  'reference',
]
export const cardinalities = ['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many']
export const statusLabels = {
  draft: '草稿',
  validated: '已校验',
  published: '已发布',
  ready: '可预览',
  needs_review: '需要消歧',
  failed: '失败',
  not_configured: '未配置模型',
  unsupported: '不支持',
  candidate: '待核验',
  accepted: '已接受',
  rejected: '已拒绝',
  disputed: '有争议',
  superseded: '已替代',
  supported: '有证据支持',
  conflict: '证据冲突',
  unknown: '信息不足',
  incomplete: '检索未完成',
}
export const label = (status) => statusLabels[status] || status
export const pretty = (value) => JSON.stringify(value, null, 2)
export const clone = (value) => JSON.parse(JSON.stringify(value))
export function newType(key = '', name = '') {
  // Relation endpoints must refer to identities even before the first draft save.
  return { id: crypto.randomUUID(), key, name, fields: [] }
}
export function newField(key = '', name = '') {
  return { key, name, type: 'text', required: false, options: {} }
}
export function sampleSchema() {
  const suffix = crypto.randomUUID().replaceAll('-', '')
  const a = newType('project_' + suffix, '项目')
  const b = newType('team_' + suffix, '团队')
  for (const type of [a, b]) type.fields.push(newField('name', '名称'))
  return {
    types: [a, b],
    relations: [
      { key: 'owned_by_' + suffix, name: '负责团队', source: a.id, target: b.id, cardinality: 'many-to-one' },
    ],
  }
}
export function validateSchema(schema) {
  function keys(rows) {
    const seen = new Set()
    for (const row of rows) {
      if (!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(row.key))
        throw Error('标识须以字母或下划线开头，最长 64 位')
      if (seen.has(row.key)) throw Error('重复标识：' + row.key)
      seen.add(row.key)
    }
  }
  keys(schema.types)
  keys(schema.relations)
  for (const type of schema.types) {
    keys(type.fields)
    for (const field of type.fields)
      if (!fieldTypes.includes(field.type)) throw Error('不支持的属性类型')
  }
  for (const rel of schema.relations) {
    if (!cardinalities.includes(rel.cardinality)) throw Error('无效关系基数')
    if (![rel.source, rel.target].every((id) => schema.types.some((t) => t.id === id)))
      throw Error('请选择关系两端的类型')
  }
}
export function quoteRange(text, quote, occurrence = 1) {
  if (!quote || !Number.isInteger(occurrence) || occurrence < 1) throw Error('请选择原文引句和出现序号')
  let index = -1
  for (let i = 0; i < occurrence; i++) {
    index = text.indexOf(quote, index + 1)
    if (index < 0) throw Error('原文中找不到该次引句')
  }
  const start = Array.from(text.slice(0, index)).length
  return { start, end: start + Array.from(quote).length, quote }
}
export const versionedData = (data, version) =>
  version == null ? { data } : { data, expected_version: version }
export const confirmBody = (pending) => ({ change_id: pending.change_id })
export const reviewBody = (action, claim, replacement) => ({
  action, expected_version: claim.version, ...(action === 'supersede' ? {superseded_by: replacement} : {}),
})
export function errorText(e) {
  const detail = e.response?.data?.detail || e.message
  return typeof detail === 'string' ? detail : pretty(detail)
}
export const draftSchema = (revision) => clone(revision.schema)
export function impactSummary({ counts }) {
  return `涉及 ${counts.types} 个类型、${counts.records} 条记录、${counts.relations} 条关联`
}

export function initialRevision(space) {
  if (!space.current_revision_id) return space.revisions[0]
  return space.revisions.find(r => r.id === space.current_revision_id) || {
    id: space.current_revision_id, status: 'published', schema: space.schema,
  }
}

export function eligibleReplacements(fact, rows) {
  return rows.filter(other => other.id !== fact.id && other.status === 'accepted'
    && other.object_id === fact.object_id && other.predicate_id === fact.predicate_id)
}

export async function loadObjectContext(spaceId, recordId, listRelations, listClaims) {
  const [relations, facts] = await Promise.all([
    listRelations(recordId),
    listClaims(spaceId + '/claims', { object_id: recordId, limit: 50 }),
  ])
  return { relations, facts }
}
