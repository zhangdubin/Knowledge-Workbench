import { ref } from 'vue'

const commandOpen = ref(false)
const catalogOpen = ref(false)
const assistantOpen = ref(false)
const assistantQuestion = ref(null)

export function useWorkspaceActions() {
  function openAssistant(question = '') {
    const text = question.trim()
    if (text) assistantQuestion.value = { text }
    assistantOpen.value = true
  }

  return { commandOpen, catalogOpen, assistantOpen, assistantQuestion, openAssistant }
}
