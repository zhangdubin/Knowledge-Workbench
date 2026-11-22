const statusLabels = {
  supported: '有依据',
  conflict: '存在冲突',
  insufficient: '信息不足',
  incomplete: '结果不完整',
  ambiguous: '术语有歧义',
}

const generationLabels = {
  disabled: '生成式答复未启用，仍可查看已核实事实和资料。',
  not_requested: '本次检索未请求生成式答复。',
  generated: '已使用本次检索的引文生成答复。',
  error: '本次未能生成答复，仍可查看已核实事实和资料。',
}

export const statusLabel = status => statusLabels[status] || '状态未知'
export const generationLabel = generation => generationLabels[generation] || ''

export const feedbackCategories = ['引用不正确', '版本不适用', '回答不完整', '存在分歧', '希望补充资料']
export const feedbackStatus = status => status === 'resolved' ? '已处理' : '待处理'

export function effectivePeriod({ effective_from: from, effective_to: to }) {
  if (from && to) return `${from} 至 ${to}`
  if (from) return `自 ${from} 起 · 未登记结束日期`
  if (to) return `截至 ${to}`
  return '未限定适用日期'
}

export function dateTime(value) {
  return value?.replace('T', ' ').slice(0, 19) || '未记录'
}

export function displayValue(value) {
  if (Array.isArray(value)) return value.map(displayValue).join('、')
  if (value && typeof value === 'object') return Object.values(value).map(displayValue).join(' · ')
  if (typeof value === 'boolean') return value ? '是' : '否'
  return value == null || value === '' ? '—' : String(value)
}

export function quoteParts(text, citation) {
  if (typeof text !== 'string' || !citation) return null
  const { start, end, quote } = citation
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null
  const points = Array.from(text)
  if (end > points.length || points.slice(start, end).join('') !== quote) return null
  return [points.slice(0, start).join(''), quote, points.slice(end).join('')]
}

export const validQuote = (text, citation) => quoteParts(text, citation) !== null

export function queryPayload(filters) {
  const payload = {
    ontology_id: filters.ontology_id,
    question: filters.question.trim(),
    generate: Boolean(filters.generate),
    limit: 50,
    depth: 2,
  }
  for (const key of ['scope', 'topic', 'type_id', 'as_of']) {
    if (filters[key]) payload[key] = filters[key]
  }
  return payload
}

export function createRequestPanel() {
  return {
    requestId: 0,
    target: null,
    data: null,
    error: '',
    busy: false,
    clear() {
      this.requestId += 1
      this.target = null
      this.data = null
      this.error = ''
      this.busy = false
    },
    begin(target = null) {
      this.clear()
      this.target = target
      this.busy = true
      return this.requestId
    },
    accept(requestId, data) {
      if (requestId !== this.requestId) return false
      this.data = data
      this.busy = false
      return true
    },
    fail(requestId, error) {
      if (requestId !== this.requestId) return false
      this.data = null
      this.error = error
      this.busy = false
      return true
    },
  }
}

export function createKnowledgeState() {
  const channels = ['query', 'terms', 'item', 'source', 'comparison', 'run', 'sources',
    'feedbackList', 'feedback', 'submission', 'resolution']
  return {
    filters: null,
    ...Object.fromEntries(channels.map(name => [name, createRequestPanel()])),
    get result() { return this.query.data },
    reset(filters = null) {
      this.filters = filters
      for (const name of channels) this[name].clear()
    },
    begin(filters) {
      this.reset(filters)
      return this.query.begin()
    },
  }
}

export function sourceIsSelected(record, revisionId, citationId) {
  if (!record || !revisionId) return false
  const citations = [...(record.citations || []), ...(record.conflict_citations || [])]
  return citations.some(c => c.revision_id === revisionId && (!citationId || c.id === citationId))
    || (!citationId && record.sources?.some(source => source.id === revisionId)) || false
}

export function newKnowledgeKey() {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

export function createRetryKeys(makeKey = newKnowledgeKey) {
  let lastPayload
  let lastKey
  return {
    forPayload(payload) {
      const signature = JSON.stringify(Object.entries(payload).sort(([a], [b]) => a.localeCompare(b)))
      if (signature !== lastPayload) {
        lastPayload = signature
        lastKey = makeKey()
      }
      return lastKey
    },
    clear() {
      lastPayload = undefined
      lastKey = undefined
    },
  }
}

export function knowledgeCapabilities(auth, catalog, space) {
  const page = auth.canPage('knowledge_service')
  return {
    template: Boolean(page && catalog?.can_manage && auth.canPage('types')
      && auth.can('model_manage') && auth.can('relation_manage')),
    review: Boolean(page && catalog?.can_review && auth.can('knowledge_review')),
    sources: Boolean(page && space?.can_manage_sources && auth.can('file_write')),
  }
}

export function knowledgeError(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && /[\u3400-\u9fff]/.test(detail) ? detail : fallback
}
