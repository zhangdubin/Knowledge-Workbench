import { computed, onMounted, onScopeDispose, reactive, ref, watch } from 'vue'
import { knowledgeService as api } from '../../api/knowledgeService.js'
import {
  createKnowledgeState, createRequestPanel, createRetryKeys, feedbackCategories,
  knowledgeCapabilities, knowledgeError, queryPayload, sourceIsSelected,
} from '../../utils/knowledgeService.js'

export function useKnowledgeWorkspace(auth, initialScope, initialQuestion) {
  const state = reactive(createKnowledgeState())
  const catalog = reactive(createRequestPanel())
  const filters = reactive({ ontology_id: '', question: typeof initialQuestion === 'string' ? initialQuestion : '', type_id: '', scope: '', topic: '', as_of: '', generate: false })
  const space = computed(() => catalog.data?.spaces.find(item => item.id === filters.ontology_id))
  const capabilities = computed(() => knowledgeCapabilities(auth, catalog.data, space.value))
  const scopeOptions = computed(() => [...new Set([...(space.value?.scopes || []), filters.scope].filter(Boolean))])
  const tab = ref('search')
  const details = ref('')
  const notice = ref('')
  const queryForm = reactive({ task: '', placeholder: '输入中文问题、关键词或文号' })
  const feedbackTarget = ref(null)
  const feedbackForm = reactive({ category: feedbackCategories[0], message: '' })
  const resolution = ref('')
  const submissionKeys = createRetryKeys()
  const resolutionKeys = createRetryKeys()
  let queryRunId = null
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
    queryRunId = null
    state.reset({ ...filters })
    closeDetails()
  }

  function changeSpace(id) {
    Object.assign(filters, { scope: '', topic: '', type_id: '', ontology_id: id })
    state.sources.clear()
  }

  function refreshAuthorization(message) {
    notice.value = message
    return loadCatalog()
  }

  async function request(panel, target, load, fallback, {
    recheck = false, requestId = panel.begin(target), publish = true,
  } = {}) {
    const isCurrent = () => panel.requestId === requestId
    try {
      const data = await load(isCurrent)
      if (!isCurrent()) return null
      if (publish) panel.accept(requestId, data)
      return data
    } catch (error) {
      const message = knowledgeError(error, fallback)
      if (!panel.fail(requestId, message)) return null
      const status = error?.response?.status
      if (status === 401 || (!recheck && [403, 404, 409].includes(status))) {
        invalidate()
        notice.value = message
        if (panel !== catalog && status !== 401) void loadCatalog()
      }
      return null
    }
  }

  // Hide cached evidence as soon as a dependent action starts. Recheck after the
  // detail response so an independently readable item cannot preserve a revoked run.
  async function withQueryRecheck(load, openedRunId = null) {
    const runId = queryRunId
    const requestId = runId ? state.query.begin(runId) : null
    const detail = await load()
    if (!runId || state.query.requestId !== requestId) return { detail, checkedRun: null }
    const fallback = '无法重新核对原查询。请重新检索。'
    const checkedRun = await request(state.query, runId, async isCurrent => {
      const run = openedRunId === runId ? detail : await api.run(runId, isCurrent)
      if (!run) throw new Error(fallback)
      return {
        ...run,
        question: run.request?.question ?? run.question,
        as_of: run.request?.as_of ?? run.as_of,
        scope: run.request?.scope ?? run.scope,
        revalidated: true,
      }
    }, fallback, { recheck: true, requestId })
    if (!checkedRun && state.query.requestId === requestId) {
      queryRunId = null
      state.terms.clear()
    }
    return { detail, checkedRun }
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
    if (scopeHint && available) filters.scope = scopeHint
    scopeHint = ''
    if (tab.value === 'sources') void loadSources()
    if (tab.value === 'feedback') void loadFeedback()
  }

  async function switchTab(next) {
    if (tab.value === next) return
    notice.value = ''
    invalidate()
    tab.value = next
    if (next === 'sources') await loadSources()
    if (next === 'feedback') await loadFeedback()
  }

  async function search() {
    if (tab.value !== 'search' || !space.value || !filters.question.trim()) return
    invalidate()
    notice.value = ''
    const requestId = state.query.begin()
    const result = await request(state.query, null, isCurrent => api.query(queryPayload(filters), isCurrent),
      '检索未完成，请重试。', { requestId })
    if (result && state.query.requestId === requestId) queryRunId = result.run_id
  }

  async function lookupTerms() {
    if (tab.value !== 'search' || !space.value) return
    const params = { ontology_id: filters.ontology_id, q: filters.question.trim() }
    if (filters.scope) params.scope = filters.scope
    await request(state.terms, null, isCurrent => api.terms(params, isCurrent), '术语查询未完成，请重试。')
  }

  function pickTerm(term) {
    const authorized = [state.terms.data?.items, state.result?.terms]
      .some(terms => terms?.some(option => option.id === term.id && option.scope === term.scope && option.preferred === term.preferred))
    if (!authorized) return
    filters.question = term.preferred
    if (term.scope) filters.scope = term.scope
    return search()
  }

  async function loadSources(offset = 0) {
    if (tab.value !== 'sources' || !space.value) return
    closeDetails()
    const ontology_id = filters.ontology_id
    await request(state.sources, offset, isCurrent => api.listSources({ ontology_id, limit: 50, offset }, isCurrent),
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
    await withQueryRecheck(() =>
      request(state.item, recordId, isCurrent => api.item(recordId, isCurrent), '无法查看条目详情，请重试。'))
  }

  async function openSource(revisionId, citation = null, origin) {
    const current = details.value === 'item' ? state.item.data : details.value === 'run' ? state.run.data : null
    const browse = !citation && tab.value === 'sources' && state.sources.data?.items.some(row => row.id === revisionId)
    const parent = origin || (sourceIsSelected(current, revisionId, citation?.id) ? current : state.result)
    if (!browse && (!parent || ![current, state.result].includes(parent) || !sourceIsSelected(parent, revisionId, citation?.id))) return
    const owner = browse ? {} : parent.run_id ? { runId: parent.run_id } : { itemId: parent.id, version: parent.version }
    closeDetails()
    details.value = 'source'
    return loadSourceView(revisionId, owner, citation?.id)
  }

  async function compareSource(revisionId) {
    if (state.source.target?.checking) return
    const source = state.source.data
    if (!revisionId || !source?.group_revisions.some(item => item.id !== source.id && item.id === revisionId)) {
      state.comparison.clear()
      return
    }
    const { owner, citationId } = state.source.target
    return loadSourceView(source.id, owner, citationId, revisionId)
  }

  async function loadSourceView(revisionId, owner, citationId, comparisonId) {
    const activeRunId = queryRunId
    const target = { revisionId, owner, citationId, citation: null, checking: true }
    const baseId = state.source.begin(target)
    const compareId = comparisonId ? state.comparison.begin(comparisonId) : null
    const isCurrent = () => state.source.requestId === baseId && (!comparisonId || state.comparison.requestId === compareId)
    const fallback = '无法重新核对资料及其引用关系，请重新打开。'
    const { detail, checkedRun } = await withQueryRecheck(() =>
      request(state.source, target, async () => {
        const [base, comparison] = await Promise.all([
          api.source(revisionId, isCurrent),
          comparisonId ? api.source(comparisonId, isCurrent) : null,
        ])
        if (!isCurrent()) return null
        let parent
        if (owner.itemId) parent = await api.item(owner.itemId, isCurrent)
        if (owner.runId && owner.runId !== activeRunId) parent = await api.run(owner.runId, isCurrent)
        return { base, comparison, parent }
      }, fallback, { requestId: baseId, publish: false, recheck: true }),
    )
    if (!isCurrent()) return
    const parent = detail?.parent || checkedRun
    const validOwner = owner.itemId
      ? parent?.id === owner.itemId && parent.version === owner.version
      : !owner.runId || parent?.run_id === owner.runId
    if (!detail || (activeRunId && !checkedRun) || !validOwner ||
        ((owner.itemId || owner.runId) && !sourceIsSelected(parent, revisionId, citationId))) {
      const message = state.source.error || state.query.error || fallback
      state.source.fail(baseId, message)
      if (comparisonId) state.comparison.fail(compareId, message)
      return
    }
    const citations = [...(parent?.citations || []), ...(parent?.conflict_citations || [])]
    state.source.target.citation = citations.find(item => item.id === citationId && item.revision_id === revisionId) || null
    state.source.target.checking = false
    state.source.accept(baseId, detail.base)
    if (comparisonId) state.comparison.accept(compareId, detail.comparison)
    return detail.base
  }

  async function openRun(runId) {
    if (!runId || (state.result?.run_id !== runId && state.feedback.data?.run_id !== runId)) return
    closeDetails()
    details.value = 'run'
    await withQueryRecheck(() =>
      request(state.run, runId, isCurrent => api.run(runId, isCurrent), '无法查看查询回放，请重试。'), runId)
  }

  async function startFeedback(target) {
    const activeRunId = queryRunId
    closeDetails()
    details.value = 'submit'
    const requestId = state.submission.begin()
    const fallback = '原反馈目标已不可用，请重新核对条目或查询。'
    const { detail, checkedRun } = await withQueryRecheck(() =>
      request(state.submission, target, async isCurrent => {
        if (!target.run_id) return api.item(target.record_id, isCurrent)
        if (target.run_id !== activeRunId) return api.run(target.run_id, isCurrent)
        return null
      }, fallback, { requestId, publish: false, recheck: true }),
    )
    if (state.submission.requestId !== requestId) return
    const run = target.run_id === activeRunId ? checkedRun : detail
    const item = target.run_id ? run?.items?.find(row => row.id === target.record_id) : detail
    if ((target.run_id && run?.run_id !== target.run_id) ||
        (target.record_id && (item?.id !== target.record_id || item.version !== target.record_version))) {
      state.submission.fail(requestId, state.submission.error || fallback)
      return
    }
    const label = target.record_id ? `${item.title} · 版本 ${item.version}` : '本次查询'
    feedbackTarget.value = { ...target, label }
    state.submission.accept(requestId, null)
  }

  function startRunFeedback() {
    const run = state.result
    if (run?.run_id) return startFeedback({ run_id: run.run_id })
  }

  function startRunItemFeedback(run, item) {
    if (!run?.run_id || (run !== state.result && run !== state.run.data)) return
    if (!run.items?.some(selected => selected.id === item.id && selected.version === item.version)) return
    return startFeedback({ run_id: run.run_id, record_id: item.id, record_version: item.version })
  }

  function startItemFeedback(item) {
    if (state.item.data !== item) return
    return startFeedback({ record_id: item.id, record_version: item.version })
  }

  async function submitFeedback() {
    const { label, ...target } = feedbackTarget.value || {}
    const message = feedbackForm.message.trim()
    if (!label || !message || state.submission.busy) return
    const payload = { ...target, category: feedbackForm.category, message }
    const idempotency_key = submissionKeys.forPayload(payload)
    const saved = await request(state.submission, null, isCurrent => api.submitFeedback({ ...payload, idempotency_key }, isCurrent),
      '提交未确认。请重试，系统会识别重复提交。')
    if (saved) submissionKeys.clear()
  }

  async function loadFeedback(offset = 0) {
    if (tab.value !== 'feedback') return
    closeDetails()
    await request(state.feedbackList, offset, isCurrent => api.listFeedback({ limit: 50, offset }, isCurrent),
      '无法加载反馈记录，请重试。')
  }

  async function openFeedback(id) {
    if (!state.feedbackList.data?.items.some(row => row.id === id) && state.submission.data?.id !== id) return
    closeDetails()
    details.value = 'feedback'
    await withQueryRecheck(() =>
      request(state.feedback, id, isCurrent => api.feedback(id, isCurrent), '无法打开反馈记录，请重试。'))
  }

  async function resolveFeedback() {
    const target = state.feedback.data
    if (!target || target.status !== 'pending' || !capabilities.value.review || !resolution.value.trim() || state.resolution.busy) return
    const payload = { expected_version: target.version, resolution: resolution.value.trim() }
    const idempotency_key = resolutionKeys.forPayload({ id: target.id, ...payload })
    // A stale version requires a fresh read. A transport failure can be repeated with the same key.
    const updated = await request(state.resolution, target.id, isCurrent => api.resolveFeedback(target.id, { ...payload, idempotency_key }, isCurrent),
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
    state, catalog, filters, space, scopeOptions, capabilities, tab, details, notice, queryForm, feedbackTarget,
    feedbackForm, resolution, loadCatalog, refreshAuthorization, changeSpace, switchTab, search, lookupTerms, pickTerm,
    loadSources, openItem, openSource, compareSource, openRun, closeDetails, startRunFeedback, startRunItemFeedback, startItemFeedback,
    submitFeedback, loadFeedback, openFeedback, resolveFeedback,
  }
}
