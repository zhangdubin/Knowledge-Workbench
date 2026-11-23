import { ref } from 'vue'

export function useIngestionSelection(loadDocument, loadJob) {
  const doc = ref(null)
  const job = ref(null)
  const plan = ref(null)
  function clear() {
    doc.value = null
    job.value = null
    plan.value = null
  }
  async function chooseDoc(id) {
    clear()
    if (id) doc.value = await loadDocument(Number(id))
  }
  async function openJob(id) {
    clear()
    if (!id) return
    const nextJob = await loadJob(id)
    const nextDoc = await loadDocument(nextJob.document_id)
    doc.value = nextDoc
    job.value = nextJob
  }
  return { doc, job, plan, chooseDoc, openJob }
}
