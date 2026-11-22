import assert from 'node:assert/strict'
import { register } from 'node:module'
import { test } from 'node:test'
import {
  createKnowledgeState, createRetryKeys, generationLabel, knowledgeCapabilities,
  queryPayload, quoteParts, sourceIsSelected, statusLabel, validQuote,
} from '../src/utils/knowledgeService.js'

const apiStub = 'data:text/javascript,' + encodeURIComponent('export const Api = {}')
register('data:text/javascript,' + encodeURIComponent(`
  export async function resolve(specifier, context, nextResolve) {
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
  assert.deepEqual(navigation.primary, [])
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

test('permission-hidden custom links stay hidden while the main navigation stays at five', async () => {
  const { getWorkspaceNavigation, searchWorkspaceCommands } = await import('../src/utils/workspaceNavigation.js')
  const customItems = [{ path: '/knowledge-service?scope=保障', label: '保障知识服务' }]
  const hidden = getWorkspaceNavigation({ canPage: perm => perm !== 'knowledge_service', canFeature: () => true, customItems })
  assert.deepEqual(searchWorkspaceCommands(hidden.groups, '知识服务'), [])
  const allowed = getWorkspaceNavigation({ canPage: () => true, canFeature: () => true })
  assert.deepEqual(allowed.primary.map(item => item.path), ['/', '/library', '/notes', '/knowledge/graph', '/apps'])
})
