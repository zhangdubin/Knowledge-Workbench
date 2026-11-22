import { computed, onMounted, onScopeDispose, reactive, ref, watch } from 'vue'
import { knowledgeService as api } from '../../api/knowledgeService.js'
import {
  createKnowledgeState, createRequestPanel, createRetryKeys, feedbackCategories,
  knowledgeCapabilities, knowledgeError, queryPayload, sourceIsSelected,
} from '../../utils/knowledgeService.js'

export function useKnowledgeWorkspace(auth, initialScope) {
  const state = reactive(createKnowledgeState())
  const catalog = reactive(createRequestPanel())
  const filters = reactive({ ontology_id: '', question: '', type_id: '', scope: '', topic: '', as_of: '', generate: false })
  const space = computed(() => catalog.data?.spaces.find(item => item.id === filters.ontology_id))
  const capabilities = computed(() => knowledgeCapabilities(auth, catalog.data, space.value))
  const tab = ref('search')
  const details = ref('')
  const notice = ref('')
  const queryForm = reactive({ task: '', placeholder: '输入中文问题、关键词或文号' })
  const feedbackTarget = ref(null)
  const feedbackForm = reactive({ category: feedbackCategories[0], message: '' })
  const resolution = ref('')
  const submissionKeys = createRetryKeys()
  const resolutionKeys = createRetryKeys()
  let scopeHint = typeof initialScope === 'string' ? initialScope : ''

  function clearSubmission() {
    feedbackTarget.value = null
    feedbackForm.category = feedbackCategories[0]
    feedbackForm.message = ''
    state.submission.clear()
    submissionKeys.clear()
  }

  function clearReview() {
    state.feedback.clear()
    state.resolution.clear()
    resolution.value = ''
    resolutionKeys.clear()
  }

  function closeDetails() {
    details.value = ''
    state.item.clear()
    state.run.clear()
    state.source.clear()
    state.comparison.clear()
    clearReview()
    clearSubmission()
  }

  function invalidate() {
    state.reset({ ...filters })
    closeDetails()
  }

  function changeSpace(id) {
    Object.assign(filters, { scope: '', topic: '', type_id: '', ontology_id: id })
    state.sources.clear()
  }

  async function request(panel, target, load, fallback, { sensitive = true } = {}) {
    const id = target === null && panel === state.query ? panel.requestId : panel.begin(target)
    try {
      const data = await load()
      return panel.accept(id, data) ? data : null
    } catch (error) {
      const message = knowledgeError(error, fallback)
      if (!panel.fail(id, message)) return null
      if (sensitive && [401, 403, 404, 409].includes(error?.response?.status)) {
        invalidate()
        notice.value = message
        if (panel !== catalog) void loadCatalog()
      }
      return null
    }
  }

  async function loadCatalog(preferredId) {
    invalidate()
    const current = preferredId || filters.ontology_id
    const data = await request(catalog, null, api.catalog, '无法加载知识空间，请重试。')
    if (!data) return
    const available = data.spaces.find(item => item.id === current)
      || data.spaces.find(item => scopeHint && item.scopes.includes(scopeHint))
      || data.spaces[0]
    if (available?.id !== filters.ontology_id) changeSpace(available?.id || '')
    if (!available?.scopes.includes(filters.scope)) filters.scope = ''
    if (!available?.topics.includes(filters.topic)) filters.topic = ''
    if (!available?.types.some(type => type.id === filters.type_id)) filters.type_id = ''
    if (scopeHint && available?.scopes.includes(scopeHint)) filters.scope = scopeHint
    scopeHint = ''
    if (tab.value === 'sources') void loadSources()
    if (tab.value === 'feedback') void loadFeedback()
  }

  async function switchTab(next) {
    notice.value = ''
    closeDetails()
    tab.value = next
    if (next === 'sources') await loadSources()
    if (next === 'feedback') await loadFeedback()
  }

  async function search() {
    if (!space.value || !filters.question.trim()) return
    closeDetails()
    notice.value = ''
    state.begin({ ...filters })
    await request(state.query, null, () => api.query(queryPayload(filters)), '检索未完成，请重试。')
  }

  async function lookupTerms() {
    if (!space.value) return
    const params = { ontology_id: filters.ontology_id, q: filters.question.trim() }
    if (filters.scope) params.scope = filters.scope
    await request(state.terms, null, () => api.terms(params), '术语查询未完成，请重试。')
  }

  function pickTerm(term) {
    filters.question = term.preferred
    if (term.scope && space.value?.scopes.includes(term.scope)) filters.scope = term.scope
    return search()
  }

  async function loadSources(offset = 0) {
    if (!space.value) return
    closeDetails()
    const ontology_id = filters.ontology_id
    await request(state.sources, offset, () => api.listSources({ ontology_id, limit: 50, offset }),
      '无法加载资料修订，请重试。')
  }

  async function openItem(recordId) {
    const parents = [state.result, state.run.data]
    const selected = parents.some(parent => parent?.items?.some(item => item.id === recordId))
      || state.item.data?.relations?.some(relation => relation.target === recordId)
      || state.feedback.data?.record_id === recordId
    if (!selected) return
    closeDetails()
    details.value = 'item'
    await request(state.item, recordId, () => api.item(recordId), '无法查看条目详情，请重试。')
  }

  async function openSource(revisionId, citation = null) {
    const current = details.value === 'item' ? state.item.data : details.value === 'run' ? state.run.data : null
    const isBrowseSelection = !citation && tab.value === 'sources' &&
      state.sources.data?.items.some(item => item.id === revisionId)
    if (!isBrowseSelection && ![state.result, current].some(record => sourceIsSelected(record, revisionId, citation?.id))) return
    closeDetails()
    details.value = 'source'
    const data = await request(state.source, { revisionId, citation }, () => api.source(revisionId),
      '无法打开资料快照，请重试。')
    return data
  }

  async function compareSource(revisionId) {
    const source = state.source.data
    if (!revisionId || !source?.group_revisions.some(item => item.id !== source.id && item.id === revisionId)) {
      state.comparison.clear()
      return
    }
    await request(state.comparison, revisionId, () => api.source(revisionId), '无法打开对照版本，请重试。')
  }

  async function openRun(runId) {
    if (!runId || (state.result?.run_id !== runId && state.feedback.data?.run_id !== runId)) return
    closeDetails()
    details.value = 'run'
    await request(state.run, runId, () => api.run(runId), '无法查看查询回放，请重试。')
  }

  function startFeedback(target, label) {
    closeDetails()
    feedbackTarget.value = { ...target, label }
    details.value = 'submit'
  }

  async function submitFeedback() {
    const { label, ...target } = feedbackTarget.value || {}
    const message = feedbackForm.message.trim()
    if (!label || !message || state.submission.busy) return
    const payload = { ...target, category: feedbackForm.category, message }
    const idempotency_key = submissionKeys.forPayload(payload)
    const saved = await request(state.submission, null, () => api.submitFeedback({ ...payload, idempotency_key }),
      '提交未确认。请重试，系统会识别重复提交。')
    if (saved) submissionKeys.clear()
  }

  async function loadFeedback(offset = 0) {
    closeDetails()
    await request(state.feedbackList, offset, () => api.listFeedback({ limit: 50, offset }),
      '无法加载反馈记录，请重试。')
  }

  async function openFeedback(id) {
    if (!state.feedbackList.data?.items.some(row => row.id === id) && state.submission.data?.id !== id) return
    closeDetails()
    details.value = 'feedback'
    await request(state.feedback, id, () => api.feedback(id), '无法打开反馈记录，请重试。')
  }

  async function resolveFeedback() {
    const target = state.feedback.data
    if (!target || target.status !== 'pending' || !capabilities.value.review || !resolution.value.trim() || state.resolution.busy) return
    const payload = { expected_version: target.version, resolution: resolution.value.trim() }
    const idempotency_key = resolutionKeys.forPayload({ id: target.id, ...payload })
    // A stale version requires a fresh read. A transport failure can be repeated with the same key.
    const updated = await request(state.resolution, target.id, () => api.resolveFeedback(target.id, { ...payload, idempotency_key }),
      '处理未确认。请重试，系统会识别重复提交。')
    if (!updated) return
    state.feedback.data = updated
    const result = state.feedbackList.data
    if (result) result.items = result.items.map(row => row.id === updated.id ? updated : row)
    resolutionKeys.clear()
    resolution.value = ''
  }

  watch(filters, invalidate, { flush: 'sync' })
  watch(() => auth.user, () => {
    catalog.clear()
    invalidate()
    if (auth.canPage('knowledge_service')) void loadCatalog()
  }, { deep: true, flush: 'sync' })
  onMounted(loadCatalog)
  onScopeDispose(() => {
    catalog.clear()
    invalidate()
  })

  return {
    state, catalog, filters, space, capabilities, tab, details, notice, queryForm, feedbackTarget,
    feedbackForm, resolution, loadCatalog, changeSpace, switchTab, search, lookupTerms, pickTerm,
    loadSources, openItem, openSource, compareSource, openRun, closeDetails, startFeedback,
    submitFeedback, loadFeedback, openFeedback, resolveFeedback,
  }
}
