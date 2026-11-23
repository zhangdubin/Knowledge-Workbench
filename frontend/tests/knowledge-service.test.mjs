import assert from 'node:assert/strict'
import { register } from 'node:module'
import { test } from 'node:test'
import { createRenderer, nextTick, reactive } from 'vue'
import {
  createKnowledgeState, createRetryKeys, generationLabel, knowledgeCapabilities,
  queryPayload, quoteParts, sourceIsSelected, statusLabel, validQuote,
} from '../src/utils/knowledgeService.js'

const apiStub = 'data:text/javascript,' + encodeURIComponent('export const Api = {}')
register('data:text/javascript,' + encodeURIComponent(`
  export async function resolve(specifier, context, nextResolve) {
    if (specifier === 'element-plus' && context.parentURL?.endsWith('/api/index.js')) {
      const ui = 'data:text/javascript,' + encodeURIComponent('export const ElMessage = { warning() {}, error() {} }')
      return { url: ui, shortCircuit: true, format: 'module' }
    }
    if (specifier === '../api') return { url: '${apiStub}', shortCircuit: true, format: 'module' }
    return nextResolve(specifier, context)
  }
`), import.meta.url)

test('query states and unavailable generation are clear in Chinese', () => {
  assert.deepEqual(['supported', 'conflict', 'insufficient', 'incomplete', 'ambiguous'].map(statusLabel),
    ['有依据', '存在冲突', '信息不足', '结果不完整', '术语有歧义'])
  assert.equal(generationLabel('disabled'), '生成式答复未启用，仍可查看已核实事实和资料。')
})

test('source excerpt coordinates count Unicode code points and require an exact snapshot match', () => {
  const text = '规程😀\n正文'
  const quote = { start: 0, end: 3, quote: '规程😀' }
  assert.equal(validQuote(text, quote), true)
  assert.deepEqual(quoteParts(text, quote), ['', '规程😀', '\n正文'])
  assert.equal(validQuote(text, { ...quote, end: 4 }), false)
  assert.equal(validQuote(text, { ...quote, end: 8 }), false)
  assert.equal(validQuote(text, { ...quote, start: -1 }), false)
  assert.equal(validQuote(text, { ...quote, quote: '规程😃' }), false)
})

test('search sends every chosen filter and omits blank filters', () => {
  assert.deepEqual(queryPayload({
    ontology_id: 'space', question: '  维护规程  ', scope: '保障', topic: '',
    type_id: 'item', as_of: '2023-02-04', generate: false,
  }), {
    ontology_id: 'space', question: '维护规程', scope: '保障',
    type_id: 'item', as_of: '2023-02-04', generate: false, limit: 50, depth: 2,
  })
})

test('changing filters clears all content and invalidates outstanding requests', () => {
  const state = createKnowledgeState()
  const scope = { scope: '保障' }
  const next = { scope: '培训' }
  const previous = state.begin(scope)
  state.query.accept(previous, { answer: '旧答复' })
  const panels = ['terms', 'item', 'source', 'comparison', 'run', 'sources', 'feedbackList', 'feedback', 'submission', 'resolution']
  const pending = panels.map(name => {
    const panel = state[name]
    panel.accept(panel.begin(), { name })
    return panel.begin()
  })
  state.reset(next)
  assert.deepEqual(state.filters, next)
  assert.equal(state.result, null)
  assert.equal(state.query.accept(previous, { answer: '迟到的答复' }), false)
  for (const [index, name] of panels.entries()) {
    assert.equal(state[name].accept(pending[index], { name }), false)
    assert.equal(state[name].data, null)
  }
})

test('replaced details ignore late successes and errors and failed details clear their content', () => {
  const state = createKnowledgeState()
  const first = state.item.begin('first')
  const second = state.item.begin('second')
  assert.equal(state.item.accept(first, { title: '旧内容' }), false)
  assert.equal(state.item.fail(first, '旧错误'), false)
  assert.equal(state.item.busy, true)
  assert.equal(state.item.fail(second, '无法查看条目'), true)
  assert.equal(state.item.data, null)
  assert.equal(state.item.error, '无法查看条目')
  assert.equal(state.item.busy, false)
})

test('citation links are restricted to the current result or currently opened detail', () => {
  const result = {
    citations: [{ id: 'current', revision_id: 'edition' }],
    conflict_citations: [{ id: 'conflict', revision_id: 'other-edition' }],
    sources: [{ id: 'clue-edition', verified: false }],
  }
  assert.equal(sourceIsSelected(result, 'edition', 'current'), true)
  assert.equal(sourceIsSelected(result, 'other-edition', 'conflict'), true)
  assert.equal(sourceIsSelected(result, 'clue-edition'), true)
  assert.equal(sourceIsSelected(result, 'edition', 'conflict'), false)
  assert.equal(sourceIsSelected(result, 'removed-edition'), false)
  assert.equal(sourceIsSelected(null, 'edition', 'current'), false)
})

test('feedback and resolution retries reuse the key for the same unchanged payload', () => {
  let nextKey = 0
  const keys = createRetryKeys(() => String(++nextKey))
  const feedback = { run_id: 'a', category: '引用不正确', message: '请核对' }
  assert.equal(keys.forPayload(feedback), '1')
  assert.equal(keys.forPayload({ ...feedback }), '1')
  assert.equal(keys.forPayload({ ...feedback, run_id: 'b' }), '2')
  assert.equal(keys.forPayload({ ...feedback, message: '已修改' }), '3')
  const resolution = { id: 'f', expected_version: 2, resolution: '已核对' }
  assert.equal(keys.forPayload(resolution), '4')
  assert.equal(keys.forPayload(resolution), '4')
  assert.equal(keys.forPayload({ ...resolution, expected_version: 3 }), '5')
  keys.clear()
  assert.equal(keys.forPayload(resolution), '6')
})

test('the reader can use the workspace without studio or library permissions', async () => {
  const { getWorkspaceNavigation, searchWorkspaceCommands } = await import('../src/utils/workspaceNavigation.js')
  const { permForPath } = await import('../src/composables/useNavItems.js')
  const canPage = permission => permission === 'knowledge_service'
  const canFeature = () => false
  const navigation = getWorkspaceNavigation({ canPage, canFeature })
  assert.equal(permForPath('/knowledge-service?scope=保障'), 'knowledge_service')
  assert.deepEqual(searchWorkspaceCommands(navigation.groups, '知识服务').map(item => item.path), ['/knowledge-service'])
  assert.deepEqual(navigation.primary.map(item => item.path), ['/knowledge-service'])
  assert.deepEqual(knowledgeCapabilities({ canPage, can: canFeature }, {
    can_manage: true, can_review: true,
  }, { can_manage_sources: true }), { template: false, review: false, sources: false })
})

test('the API can withhold a permission from a locally capable administrator', () => {
  const auth = { canPage: () => true, can: () => true }
  assert.deepEqual(knowledgeCapabilities(auth, {}, { can_manage_sources: false }),
    { template: false, review: false, sources: false })
  assert.deepEqual(knowledgeCapabilities(auth, {
    can_manage: true, can_review: true,
  }, { can_manage_sources: true }), { template: true, review: true, sources: true })
})

test('permission-hidden custom links stay hidden while important destinations stay primary', async () => {
  const { getWorkspaceNavigation, searchWorkspaceCommands } = await import('../src/utils/workspaceNavigation.js')
  const customItems = [{ path: '/knowledge-service?scope=保障', label: '保障知识服务' }]
  const hidden = getWorkspaceNavigation({ canPage: perm => perm !== 'knowledge_service', canFeature: () => true, customItems })
  assert.deepEqual(searchWorkspaceCommands(hidden.groups, '知识服务'), [])
  const allowed = getWorkspaceNavigation({ canPage: () => true, canFeature: () => true })
  assert.deepEqual(allowed.primary.map(item => item.path), ['/', '/knowledge-service', '/library', '/notes', '/apps', '/ontology', '/knowledge/graph'])
})

const { default: http } = await import('../src/api/index.js')
const { useKnowledgeWorkspace } = await import('../src/views/knowledge-service/useKnowledgeWorkspace.js')
const renderer = createRenderer({
  createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null,
})
const manager = () => reactive({ user: { id: 1 }, canPage: () => true, can: () => true })
const catalogResponse = {
  spaces: [{ id: 'space', name: '知识空间', types: [], scopes: ['保障'], topics: [], can_manage_sources: true }],
  can_manage: true, can_review: true, source_candidates: [{ id: 2, title: '维护规程', filename: '维护规程.txt' }],
}
const originalItem = { id: 8, version: 1, title: '维护条目' }
const originalRun = {
  run_id: 'original', status: 'supported', generation: 'generated', answer: '已有结论',
  as_of: '2026-02-01', request: { question: '维护规程', as_of: '2026-02-01' },
  items: [originalItem], facts: [{ id: 'fact' }],
  citations: [{ id: 'cite', revision_id: 'edition', quote: '旧引文' }],
  terms: [], sources: [], conflicts: [],
}
const edition = { id: 'edition', ontology_id: 'space', text: '授权文字', group_revisions: [] }
const currentItem = { ...originalItem, version: 2, citations: [], facts: [], relations: [], history: [] }

function deferred() {
  let resolve, reject
  const wait = new Promise((done, failed) => { resolve = done; reject = failed })
  return { wait, resolve, reject }
}
const rejectHttp = status => ({ response: { status, data: { detail: '当前授权已变更' } } })
const settle = () => new Promise(resolve => setImmediate(resolve))

function mountController(t, useController, respond) {
  const adapter = http.defaults.adapter
  http.defaults.adapter = async config => {
    const path = config.url.replace('/api/knowledge-service', '')
    try {
      const data = await respond(path, config)
      return { data, config }
    } catch (error) {
      error.config = config
      throw error
    }
  }
  let controller
  const app = renderer.createApp({
    setup() {
      controller = useController()
      return () => null
    },
  })
  app.mount({})
  t.after(() => {
    app.unmount()
    http.defaults.adapter = adapter
  })
  return controller
}

function workspace(t, respond) {
  return mountController(t, () => useKnowledgeWorkspace(manager()), (path, config) =>
    path === '/catalog' ? catalogResponse : respond(path, config))
}

test('leaving search invalidates late query successes and term errors', async t => {
  const query = deferred()
  const terms = deferred()
  const ws = workspace(t, path => ({
    '/query': query.wait, '/terms': terms.wait, '/sources': { items: [edition] }, '/sources/edition': edition,
  })[path])
  await settle()
  ws.filters.question = '维护规程'
  const search = ws.search()
  const lookup = ws.lookupTerms()
  await ws.switchTab('sources')
  await ws.openSource('edition')
  query.resolve(originalRun)
  terms.reject(rejectHttp(403))
  await Promise.all([search, lookup])
  assert.deepEqual(ws.state.source.data, edition)
  assert.equal(ws.notice.value, '')
  await ws.switchTab('search')
  assert.equal(ws.state.result, null)
  assert.equal(ws.state.terms.error, '')
  assert.equal(ws.state.sources.data, null)
})

test('leaving source and feedback tabs invalidates both delayed page requests', async t => {
  const sources = deferred()
  const feedback = deferred()
  const ws = workspace(t, path => ({
    '/sources': sources.wait, '/feedback': feedback.wait, '/query': originalRun,
  })[path])
  await settle()
  const browse = ws.switchTab('sources')
  const review = ws.switchTab('feedback')
  await ws.switchTab('search')
  sources.reject(rejectHttp(403))
  feedback.resolve({ items: [{ id: 'obsolete' }] })
  await Promise.all([browse, review])
  assert.equal(ws.state.sources.error, '')
  assert.equal(ws.state.feedbackList.data, null)
  assert.equal(ws.notice.value, '')
})

test('a stale knowledge 401 does not redirect, and a current 401 uses the login flow', async t => {
  const old = deferred()
  let calls = 0
  const ws = workspace(t, path => {
    if (path === '/query' && ++calls === 1) return old.wait
    if (path === '/query') throw rejectHttp(401)
    if (path === '/sources') return { items: [] }
  })
  const originalWindow = globalThis.window
  const originalStorage = globalThis.sessionStorage
  const redirected = new Map()
  globalThis.window = { location: { hash: '#/knowledge-service' } }
  globalThis.sessionStorage = { setItem: (key, value) => redirected.set(key, value) }
  t.after(() => {
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
    if (originalStorage === undefined) delete globalThis.sessionStorage
    else globalThis.sessionStorage = originalStorage
  })
  await settle()
  ws.filters.question = '维护规程'
  const pending = ws.search()
  await settle()
  await ws.switchTab('sources')
  old.reject(rejectHttp(401))
  await pending
  assert.equal(globalThis.window.location.hash, '#/knowledge-service')
  await ws.switchTab('search')
  await ws.search()
  assert.equal(globalThis.window.location.hash, '#/login')
  assert.equal(redirected.get('kb_return_to'), '#/knowledge-service')
})

test('an independently readable item cannot leave a withdrawn run answer and quote on screen', async t => {
  const detail = deferred()
  const recheck = deferred()
  const calls = []
  const ws = workspace(t, (path, config) => {
    calls.push(path)
    return { '/query': originalRun, '/items/8': detail.wait, '/runs/original': recheck.wait }[path]
  })
  await settle()
  ws.filters.question = '维护规程'
  await ws.search()
  assert.equal(ws.state.result.citations[0].quote, '旧引文')
  const opening = ws.openItem(8)
  assert.equal(ws.state.result, null)
  await settle()
  assert.deepEqual(calls, ['/query', '/items/8'])
  detail.resolve(currentItem)
  await settle()
  assert.deepEqual(calls, ['/query', '/items/8', '/runs/original'])
  recheck.reject(rejectHttp(403))
  await opening
  assert.equal(ws.state.item.data.version, 2)
  assert.deepEqual(ws.state.item.data.citations, [])
  assert.equal(ws.state.result, null)
})

test('authorized replay preserves the original selection for historical item feedback', async t => {
  const sent = []
  const replay = { ...originalRun, answer: null, citations: [], facts: [] }
  const ws = workspace(t, (path, config) => {
    if (path === '/feedback') {
      sent.push(JSON.parse(config.data))
      return { id: 'feedback-receipt' }
    }
    return { '/query': originalRun, '/runs/original': replay }[path]
  })
  await settle()
  ws.filters.question = '维护规程'
  await ws.search()
  await ws.openRun('original')
  assert.equal(ws.state.result.answer, null)
  assert.deepEqual(ws.state.result.citations, [])
  assert.equal(ws.state.result.as_of, '2026-02-01')
  await ws.startRunItemFeedback(ws.state.run.data, originalItem)
  ws.feedbackForm.message = '请核对原结论'
  await ws.submitFeedback()
  assert.equal(sent.length, 1)
  assert.deepEqual(
    { run_id: sent[0].run_id, record_id: sent[0].record_id, record_version: sent[0].record_version },
    { run_id: 'original', record_id: 8, record_version: 1 },
  )
  assert.equal(ws.state.submission.data.id, 'feedback-receipt')
})

test('selecting an authorized term applies its scope even outside the catalog scopes', async t => {
  const term = { id: 7, preferred: '处置', aliases: [], scope: '培训' }
  let request
  const ws = workspace(t, (path, config) => {
    if (path === '/terms') return { items: [term], ambiguous: true }
    if (path === '/query') {
      request = JSON.parse(config.data)
      return { ...originalRun, items: [], citations: [] }
    }
  })
  await settle()
  ws.filters.question = '处置'
  await ws.lookupTerms()
  await ws.pickTerm(ws.state.terms.data.items[0])
  assert.equal(request.scope, '培训')
  assert.deepEqual(ws.scopeOptions.value, ['保障', '培训'])
})

test('a repeated successful template preview keeps the same confirmable change', async t => {
  const { useKnowledgeManagement } = await import('../src/views/knowledge-service/useKnowledgeManagement.js')
  const writes = []
  const management = mountController(t, () => useKnowledgeManagement(
    reactive({ kind: 'template', revisions: [] }), () => {},
  ), (path, config) => {
    if (config.method === 'post') writes.push([path, JSON.parse(config.data)])
    if (path === '/template' && config.method === 'post') {
      return { change_id: 'change-' + writes.length, preview: { schema: {} } }
    }
    if (path.startsWith('/template/change-')) return { space_id: 'installed' }
    return { schema: {} }
  })
  management.name.value = '业务知识'
  await management.previewTemplate()
  await management.previewTemplate()
  assert.equal(writes.length, 1)
  assert.equal(management.preview.data.change_id, 'change-1')
  await management.confirmTemplate()
  assert.equal(writes[1][0], '/template/change-1/confirm')
  management.name.value = '安全知识'
  await management.previewTemplate()
  assert.notEqual(writes[0][1].key, writes[2][1].key)
})

test('writing a source locks the selected replacement, and mismatched draft completion is ignored', async t => {
  const { useKnowledgeManagement } = await import('../src/views/knowledge-service/useKnowledgeManagement.js')
  const result = deferred()
  const events = []
  const props = reactive({ kind: 'sources', spaceId: 'space', revisions: [], selectedRevision: null })
  const management = mountController(t, () => useKnowledgeManagement(props, (...event) => events.push(event)),
    path => path === '/sources' ? result.wait : null)
  Object.assign(management.form, { document_id: 2, label: '第一版', group_key: '手册' })
  const saving = management.registerSource()
  assert.equal(management.saving.busy, true)
  props.selectedRevision = { id: 'other', group_key: '其他', scope: '保障', topic: '维护' }
  await nextTick()
  assert.equal(management.form.supersedes_id, '')
  management.form.label = '另一稿'
  result.resolve({ id: 'registered' })
  await saving
  assert.equal(events.some(([type]) => type === 'registered'), false)
})

test('source registration 404 from a revoked file reloads the workspace and catalog', async t => {
  const { useKnowledgeManagement } = await import('../src/views/knowledge-service/useKnowledgeManagement.js')
  const result = deferred()
  const refresh = deferred()
  let calls = 0
  let ws
  const management = mountController(t, () => {
    ws = useKnowledgeWorkspace(manager())
    return useKnowledgeManagement(
      reactive({ kind: 'sources', spaceId: 'space', revisions: [] }), (type, message) => {
        if (type === 'permission') void ws.refreshAuthorization(message)
      },
    )
  }, (path, config) => {
    if (path === '/catalog') return ++calls === 1 ? catalogResponse : refresh.wait
    if (path === '/sources/edition') return edition
    if (path === '/sources') return config.method === 'post' ? result.wait : { items: [edition] }
  })
  await settle()
  await ws.switchTab('sources')
  await ws.openSource('edition')
  Object.assign(management.form, { document_id: 2, label: '修订', group_key: '手册' })
  const saving = management.registerSource()
  result.reject(rejectHttp(404))
  await saving
  assert.equal(ws.state.source.data, null)
  assert.equal(ws.state.sources.data, null)
  assert.equal(ws.catalog.data, null)
  refresh.resolve({ ...catalogResponse, source_candidates: [] })
  await settle()
  assert.deepEqual(ws.catalog.data.source_candidates, [])
})

test('citation authorization settles before a comparison can replace its recheck', async t => {
  const recheck = deferred()
  const second = { id: 'edition-2', group_revisions: [] }
  const first = { ...edition, group_revisions: [edition, second] }
  const cited = originalRun.citations[0]
  const replay = { ...originalRun, answer: null }
  let compares = 0
  const ws = workspace(t, path => {
    if (path === '/sources/edition-2') {
      compares++
      return second
    }
    return { '/query': originalRun, '/runs/original': recheck.wait, '/sources/edition': first }[path]
  })
  await settle()
  ws.filters.question = '维护规程'
  await ws.search()
  const opening = ws.openSource('edition', cited)
  await settle()
  assert.equal(ws.state.source.target.citation, null)
  const earlyCompare = ws.compareSource('edition-2')
  await settle()
  const prematureRequests = compares
  recheck.resolve(replay)
  await Promise.all([opening, earlyCompare])
  assert.equal(prematureRequests, 0)
  assert.deepEqual(ws.state.source.target.citation, cited)
  await ws.compareSource('edition-2')
  assert.equal(ws.state.comparison.data.id, 'edition-2')
})

test('comparison clears both snapshots and the highlight if the original run loses access', async t => {
  const compare = deferred()
  const recheck = deferred()
  const second = { id: 'edition-2', text: '乙文正文', group_revisions: [] }
  const first = { ...edition, text: '甲文正文', group_revisions: [edition, second] }
  const cited = { ...originalRun.citations[0], quote: '甲文', start: 0, end: 2 }
  const query = { ...originalRun, citations: [cited] }
  const replay = { ...query, answer: null }
  let reads = 0
  let checks = 0
  const ws = workspace(t, path => {
    if (path === '/sources/edition') { reads++; return first }
    if (path === '/runs/original') return ++checks === 1 ? replay : recheck.wait
    if (path === '/sources/edition-2') return compare.wait
    if (path === '/query') return query
  })
  await settle()
  ws.filters.question = '维护规程'
  await ws.search()
  await ws.openSource('edition', cited)
  assert.equal(ws.state.source.data.text, '甲文正文')
  assert.equal(ws.state.source.target.citation.quote, '甲文')
  const comparison = ws.compareSource('edition-2')
  const hiddenWhileLoading = [ws.state.source.data, ws.state.source.target?.citation, ws.state.comparison.data]
  compare.resolve(second)
  await settle()
  const hiddenWhileChecking = [ws.state.source.data, ws.state.source.target?.citation, ws.state.comparison.data]
  recheck.reject(rejectHttp(404))
  await comparison
  assert.equal(ws.state.source.data, null)
  assert.equal(ws.state.comparison.data, null)
  assert.equal(ws.state.source.target?.citation ?? null, null)
  assert.equal(ws.state.result, null)
  assert.deepEqual(hiddenWhileLoading, [null, null, null])
  assert.deepEqual(hiddenWhileChecking, [null, null, null])
  assert.equal(reads, 2)
  assert.equal(checks, 2)
})

test('comparison from the source list rechecks the original snapshot when no run exists', async t => {
  const base = deferred()
  const second = { id: 'edition-2', text: '乙文正文', group_revisions: [] }
  const first = { ...edition, text: '甲文正文', group_revisions: [edition, second] }
  let reads = 0
  let comparisons = 0
  const ws = workspace(t, path => {
    if (path === '/sources') return { items: [first, second] }
    if (path === '/sources/edition') return ++reads === 1 ? first : base.wait
    if (path === '/sources/edition-2') { comparisons++; return second }
  })
  await settle()
  await ws.switchTab('sources')
  await ws.openSource(first.id)
  assert.equal(ws.state.source.data.text, '甲文正文')
  const comparison = ws.compareSource(second.id)
  await settle()
  const hiddenWhileChecking = [ws.state.source.data, ws.state.comparison.data]
  if (reads === 2) base.reject(rejectHttp(404))
  await comparison
  assert.equal(ws.state.source.data, null)
  assert.equal(ws.state.comparison.data, null)
  assert.deepEqual(hiddenWhileChecking, [null, null])
  assert.equal(reads, 2)
  assert.equal(comparisons, 1)
})

test('the restored query card uses the original question, date and scope from the replay request', async t => {
  const question = '查培训规程第六条'
  const replay = {
    run_id: 'original', status: 'supported', generation: 'not_requested', answer: null,
    request: { question, as_of: '2024-03-03', scope: '培训' },
    items: [originalItem], citations: [], facts: [], sources: [],
  }
  const ws = workspace(t, path => ({
    '/query': { ...originalRun, as_of: '2024-03-03', scope: '培训' },
    '/items/8': currentItem, '/runs/original': replay,
  })[path])
  await settle()
  ws.filters.question = question
  ws.filters.as_of = '2024-03-03'
  ws.filters.scope = '培训'
  await ws.search()
  await ws.openItem(8)
  const restored = ws.state.result
  assert.deepEqual([restored.question, restored.as_of, restored.scope],
    [question, '2024-03-03', '培训'])
})

async function openFeedbackHistory(ws) {
  await settle()
  await ws.switchTab('feedback')
  await ws.openFeedback('case')
  await ws.openRun('original')
}

function historyWorkspace(t, respond) {
  const feedback = { id: 'case', run_id: 'original' }
  let opened = false
  return workspace(t, (path, config) => {
    if (path === '/feedback') return { items: [feedback] }
    if (path === '/feedback/case') return feedback
    if (path === '/runs/original' && !opened) { opened = true; return originalRun }
    return respond(path, config)
  })
}

test('a citation from feedback history waits for the owning run and drops a withdrawn source association', async t => {
  const replay = deferred()
  let checks = 0
  const ws = historyWorkspace(t, path => {
    if (path === '/sources/edition') return edition
    if (path === '/runs/original') { checks++; return replay.wait }
  })
  await openFeedbackHistory(ws)
  const opening = ws.openSource('edition', ws.state.run.data.citations[0])
  await settle()
  const pending = ws.state.source.target?.citation
  if (checks) replay.reject(rejectHttp(404))
  await opening
  assert.equal(checks, 1)
  assert.equal(pending, null)
  assert.equal(ws.state.source.data, null)
  assert.equal(ws.state.source.target?.citation ?? null, null)
})

test('historical feedback uses the owning run selection and title returned at form opening', async t => {
  let selection = [{ ...originalItem, title: '已核对标题' }]
  const ws = historyWorkspace(t, path => {
    if (path === '/runs/original') return { ...originalRun, items: selection }
  })
  await openFeedbackHistory(ws)
  await ws.startRunItemFeedback(ws.state.run.data, originalItem)
  assert.equal(ws.feedbackTarget.value?.label, '已核对标题 · 版本 1')
  await ws.openFeedback('case')
  await ws.openRun('original')
  selection = []
  await ws.startRunItemFeedback(ws.state.run.data, ws.state.run.data.items[0])
  assert.equal(ws.feedbackTarget.value, null)
})

test('current item citations and comparisons re-read the exact owning item version', async t => {
  let item = { ...currentItem, citations: [{ ...originalRun.citations[0], quote: '原引文' }] }
  const second = { ...edition, id: 'other' }
  const ws = workspace(t, path => ({
    '/query': originalRun, '/runs/original': originalRun, '/items/8': item,
    '/sources/edition': { ...edition, group_revisions: [edition, second] }, '/sources/other': second,
  })[path])
  await settle()
  ws.filters.question = '维护规程'
  await ws.search()
  await ws.openItem(8)
  const clicked = ws.state.item.data.citations[0]
  item = { ...item, citations: [{ ...clicked, quote: '重新核对引文' }] }
  await ws.openSource('edition', clicked)
  assert.equal(ws.state.source.target?.citation?.quote, '重新核对引文')
  item = { ...item, version: 3 }
  await ws.compareSource('other')
  assert.equal(ws.state.comparison.data, null)
  assert.equal(ws.state.source.data, null)
})

test('item-only feedback waits for a current matching item version', async t => {
  let item = currentItem
  const ws = workspace(t, path => ({
    '/query': originalRun, '/runs/original': originalRun, '/items/8': item,
  })[path])
  await settle()
  ws.filters.question = '维护规程'
  await ws.search()
  await ws.openItem(8)
  item = { ...currentItem, version: 3 }
  await ws.startItemFeedback(ws.state.item.data)
  assert.equal(ws.feedbackTarget.value, null)
})

test('editor searches older file names and submits the selected authorized document', async t => {
  const { useKnowledgeManagement } = await import('../src/views/knowledge-service/useKnowledgeManagement.js')
  const calls = []
  const management = mountController(t, () => useKnowledgeManagement({
    kind: 'sources', spaceId: 'space', revisions: [], candidates: catalogResponse.source_candidates,
  }, () => {}), (path, config) => {
    calls.push([path, config.params, config.data])
    if (path === '/source-candidates') return { items: [{ id: 41, filename: '旧手册.txt' }], incomplete: false }
    return { id: 'registered' }
  })
  assert.deepEqual(management.fileOptions?.value, catalogResponse.source_candidates)
  management.fileQuery.value = '旧手册'
  await management.searchFiles()
  assert.deepEqual(calls[0].slice(0, 2), ['/source-candidates', { ontology_id: 'space', q: '旧手册' }])
  management.form.document_id = management.fileOptions.value[0].id
  await management.registerSource()
  assert.equal(JSON.parse(calls[1][2]).document_id, 41)
})

test('home knowledge handoff prefills both filters and only reads the catalog on mount', async t => {
  const calls = []
  const ws = mountController(t, () => useKnowledgeWorkspace(manager(), '保障', '哪份规程适用？'),
    path => { calls.push(path); return catalogResponse })
  await settle()
  assert.deepEqual([ws.filters.question, ws.filters.scope, ws.filters.generate], ['哪份规程适用？', '保障', false])
  assert.deepEqual(calls, ['/catalog'])
})

test('knowledge-only home form routes its question and business scope on explicit submit', async t => {
  const { readFile } = await import('node:fs/promises')
  const { parse, compileScript } = await import('@vue/compiler-sfc')
  const { transform } = await import('esbuild')
  const vue = await import('vue')
  const src = await readFile(new URL('../src/views/Dashboard.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(src).descriptor, { id: 'home', inlineTemplate: true }).content
  const { code } = await transform(script, { format: 'cjs' })
  const routes = []
  const modules = {
    vue,
    'vue-router': { useRouter: () => ({ push: target => routes.push(target) }) },
    '../stores/auth': { useAuthStore: () => ({
      canPage: key => ['dashboard', 'knowledge_service'].includes(key), can: () => false, canModel: () => false,
    }) },
    '../composables/useWorkspaceActions': { useWorkspaceActions: () => ({ openAssistant: assert.fail }) },
  }
  const loaded = { exports: {} }
  new Function('require', 'module', 'exports', code)(key => modules[key] || {}, loaded, loaded.exports)
  let tree
  const app = renderer.createApp({
    setup() {
      const render = loaded.exports.default.setup({}, { expose() {} })
      return () => { tree = render({}, []); return null }
    },
  })
  for (const name of ['MagicStick', 'Search', 'ArrowRight', 'el-icon', 'Upload', 'EditPen', 'RouterLink']) {
    app.component(name, { render: () => null })
  }
  app.mount({})
  t.after(() => app.unmount())
  function find(node, type) {
    if (node?.type === type) return node
    if (Array.isArray(node?.children)) return node.children.map(child => find(child, type)).find(Boolean)
  }
  const form = find(tree, 'form')
  assert.ok(form)
  find(form, 'textarea').props['onUpdate:modelValue'](' 查制度 ')
  find(form, 'input').props['onUpdate:modelValue']('培训')
  assert.deepEqual(routes, [])
  await nextTick()
  find(tree, 'form').props.onSubmit({ preventDefault() {} })
  assert.deepEqual(routes, [{ name: 'knowledge-service', query: { question: '查制度', scope: '培训' } }])
})

test('a current denied snapshot clears old source rows and refreshes the authorized list', async t => {
  let sourceReads = 0
  const refresh = deferred()
  const ws = workspace(t, path => {
    if (path === '/sources') return ++sourceReads === 1 ? { items: [edition] } : refresh.wait
    if (path === '/sources/edition') throw rejectHttp(404)
  })
  await settle()
  await ws.switchTab('sources')
  assert.equal(ws.state.sources.data.items[0].id, 'edition')
  await ws.openSource('edition')
  await settle()
  assert.equal(ws.state.sources.data, null)
  assert.equal(ws.state.source.data, null)
  refresh.resolve({ items: [] })
  await settle()
  assert.deepEqual(ws.state.sources.data.items, [])
  assert.equal(sourceReads, 2)
})

test('a denied feedback-history owner clears old feedback bodies and reloads visible rows', async t => {
  const refresh = deferred()
  const feedback = { id: 'case', run_id: 'original', message: '应撤回的旧正文' }
  let listReads = 0
  let runReads = 0
  const ws = workspace(t, path => {
    if (path === '/feedback') return ++listReads === 1 ? { items: [feedback] } : refresh.wait
    if (path === '/feedback/case') return feedback
    if (path === '/runs/original') {
      if (++runReads === 1) return originalRun
      throw rejectHttp(403)
    }
    if (path === '/sources/edition') return edition
  })
  await openFeedbackHistory(ws)
  assert.equal(ws.state.feedbackList.data.items[0].message, feedback.message)
  await ws.openSource('edition', ws.state.run.data.citations[0])
  await settle()
  assert.equal(ws.state.feedbackList.data, null)
  assert.equal(ws.state.run.data, null)
  assert.equal(ws.state.source.data, null)
  refresh.resolve({ items: [] })
  await settle()
  assert.deepEqual(ws.state.feedbackList.data.items, [])
  assert.equal(listReads, 2)
})
