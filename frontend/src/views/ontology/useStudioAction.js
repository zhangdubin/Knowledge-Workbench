import { ref } from 'vue'
import { errorText } from '../../utils/ontology'
export function useStudioAction() {
  const busy = ref(false)
  const error = ref('')
  async function run(action) {
    if (busy.value) return
    busy.value = true
    error.value = ''
    try {
      return await action()
    } catch (e) {
      error.value = errorText(e)
    } finally {
      busy.value = false
    }
  }
  return { busy, error, run }
}
