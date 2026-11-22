import { computed, onMounted, onScopeDispose, reactive, ref, watch } from 'vue'
import { knowledgeService as api } from '../../api/knowledgeService.js'
import { createRequestPanel, knowledgeError, newKnowledgeKey } from '../../utils/knowledgeService.js'

export function useKnowledgeManagement(props, emit) {
  const definition = reactive(createRequestPanel())
  const preview = reactive(createRequestPanel())
  const saving = reactive(createRequestPanel())
  const name = ref('')
  const form = reactive({
    document_id: '', group_key: '', label: '', scope: '', topic: '',
    effective_from: '', effective_to: '', supersedes_id: '',
  })
  const schema = computed(() => preview.data?.preview.schema || definition.data?.schema)
  const predecessors = computed(() => {
    const rows = props.revisions.filter(row => row.group_key === form.group_key && row.scope === form.scope)
    const selected = props.selectedRevision
    if (selected?.id === form.supersedes_id && !rows.some(row => row.id === selected.id)) return [...rows, selected]
    return rows
  })
  const spaceKey = ref('')

  async function request(panel, load, fallback, matchesDraft = () => true) {
    const id = panel.begin()
    const isCurrent = () => panel.requestId === id && matchesDraft()
    try {
      const data = await load(isCurrent)
      return isCurrent() && panel.accept(id, data) ? data : null
    } catch (error) {
      if (!isCurrent()) return null
      const message = knowledgeError(error, fallback)
      panel.fail(id, message)
      if ([401, 403, 404].includes(error?.response?.status)) emit('permission', message)
      return null
    } finally {
      if (panel.requestId === id && !matchesDraft()) panel.clear()
    }
  }

  const loadDefinition = () => request(definition, api.template, '无法读取模板，请重试。')
  async function previewTemplate() {
    if (!name.value || preview.data || preview.busy || saving.busy) return
    saving.clear()
    spaceKey.value ||= 'ks' + newKnowledgeKey()
    const draft = { key: spaceKey.value, name: name.value }
    await request(preview, isCurrent => api.previewTemplate(draft, isCurrent),
      '无法生成安装预览，请重试。')
  }
  async function confirmTemplate() {
    if (!preview.data || saving.busy) return
    const id = preview.data.change_id
    const data = await request(saving, isCurrent => api.confirmTemplate(id, isCurrent), '无法确认模板安装，请重试。')
    if (data) emit('installed', data.space_id)
  }
  function sourceDraft() {
    return { ontology_id: props.spaceId, ...form,
      effective_from: form.effective_from || null, effective_to: form.effective_to || null,
      supersedes_id: form.supersedes_id || null,
    }
  }

  async function registerSource() {
    if (!form.document_id || saving.busy) return
    const payload = sourceDraft()
    const signature = JSON.stringify(payload)
    const matchesDraft = () => JSON.stringify(sourceDraft()) === signature
    const data = await request(saving, isCurrent => api.registerSource(payload, isCurrent),
      '无法登记资料修订，请重试。', matchesDraft)
    if (data && matchesDraft()) emit('registered', data)
  }

  watch(name, () => {
    preview.clear()
    saving.clear()
    spaceKey.value = ''
  }, { flush: 'sync' })
  watch([() => form.scope, () => form.group_key], () => { form.supersedes_id = '' }, { flush: 'sync' })
  watch(() => props.selectedRevision, row => {
    if (!row || saving.busy) return
    form.group_key = row.group_key
    form.scope = row.scope
    form.topic = row.topic
    form.supersedes_id = row.id
  })
  watch(() => saving.busy, busy => emit('saving', busy), { flush: 'sync' })
  onMounted(() => {
    if (props.kind === 'template') void loadDefinition()
  })
  onScopeDispose(() => {
    definition.clear()
    preview.clear()
    saving.clear()
    emit('saving', false)
  })

  return { definition, preview, saving, name, form, schema, predecessors,
    loadDefinition, previewTemplate, confirmTemplate, registerSource }
}
