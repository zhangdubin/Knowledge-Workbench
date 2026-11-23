import { computed, ref } from 'vue'
import { clone } from '../../utils/ontology.js'

export function useObjectSelection(defaultType, loadDetail) {
  const selectedId = ref('')
  const object = ref(null)
  const typeId = ref(defaultType)
  const data = ref({})
  const history = ref([])
  const moreHistory = ref(false)
  const context = ref({ relations: [], facts: [] })
  const canSave = computed(() => !!typeId.value && (!selectedId.value || !!object.value))

  async function select(id) {
    selectedId.value = id
    object.value = null
    typeId.value = id ? null : defaultType
    data.value = {}
    history.value = []
    moreHistory.value = false
    context.value = { relations: [], facts: [] }
    if (!id) return

    const loaded = await loadDetail(id)
    object.value = loaded.row
    typeId.value = loaded.row.type_id
    data.value = clone(loaded.row.data)
    history.value = loaded.history
    moreHistory.value = loaded.history.length === 50
    context.value = loaded.context
  }
  return { selectedId, object, typeId, data, history, moreHistory, context, canSave, select }
}
